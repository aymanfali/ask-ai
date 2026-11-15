from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ask_ai.core.config import Settings
from ask_ai.core.errors import ApplicationError
from ask_ai.modules.chat.context import estimate_text_tokens, select_context
from ask_ai.modules.chat.models import GenerationRequestRecord, UsageLedger
from ask_ai.modules.chat.schemas import GenerationCreateRequest
from ask_ai.modules.conversations.constants import DEFAULT_CONVERSATION_TITLE
from ask_ai.modules.conversations.models import Conversation, Message
from ask_ai.modules.llm.catalog import ModelCatalog
from ask_ai.modules.llm.errors import ProviderError, ProviderResponseError
from ask_ai.modules.llm.schemas import (
    ChatMessage,
    GenerationEvent,
    GenerationEventType,
    GenerationRequest,
    MessageRole,
    TokenUsage,
)
from ask_ai.modules.llm.service import LLMService

logger = logging.getLogger(__name__)
MAX_GENERATED_CONTENT_CHARACTERS = 256_000
PARTIAL_FLUSH_INTERVAL_SECONDS = 1.0
SSE_HEARTBEAT_INTERVAL_SECONDS = 15.0
_HEARTBEAT = object()


@dataclass(frozen=True, slots=True)
class OutboundGenerationEvent:
    name: str
    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PreparedGeneration:
    generation_id: UUID
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    assistant_sequence: int
    request: GenerationRequest | None
    model: Any | None
    estimated_input_tokens: int
    replay: bool = False
    replay_status: str | None = None
    replay_content: str = ""
    replay_usage: dict[str, Any] | None = None
    replay_error_code: str | None = None
    replay_finish_reason: str | None = None
    replay_provider_request_id: str | None = None


class ExplicitGenerationCancellation(Exception):
    """Raised when the shared cancellation marker is observed."""


class GenerationService:
    """Durable chat generation orchestration around the provider-independent LLM service."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        session_factory: async_sessionmaker[AsyncSession],
        llm_service: LLMService,
        catalog: ModelCatalog,
        redis: Any,
        settings: Settings,
    ) -> None:
        self.session = session
        self.session_factory = session_factory
        self.llm_service = llm_service
        self.catalog = catalog
        self.redis = redis
        self.settings = settings

    async def prepare_generation(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        payload: GenerationCreateRequest,
        idempotency_key: str,
    ) -> PreparedGeneration:
        if not idempotency_key or not 8 <= len(idempotency_key) <= 128:
            raise ApplicationError(
                code="invalid_idempotency_key",
                message="Idempotency-Key must contain 8 to 128 characters.",
                status_code=400,
            )
        if any(
            not (character.isascii() and (character.isalnum() or character in "._:-"))
            for character in idempotency_key
        ):
            raise ApplicationError(
                code="invalid_idempotency_key",
                message="Idempotency-Key contains unsupported characters.",
                status_code=400,
            )

        # Fingerprint the caller's normalized request, not server defaults. A retry
        # remains idempotent even if the operator later changes the default output cap
        # or disables/reconfigures the provider that served the original request.
        request_hash = self._request_hash(conversation_id, payload)
        existing = await self._find_idempotent_request(user_id, idempotency_key)
        if existing is not None:
            return await self._prepare_replay(existing, request_hash)

        model = self.catalog.get_model(payload.model_id)
        if model is None:
            raise ApplicationError(
                code="model_not_found",
                message="The requested model is not available.",
                status_code=404,
            )
        output_tokens = payload.max_output_tokens or min(
            self.settings.generation_default_max_output_tokens,
            model.max_output_tokens,
        )
        llm_request_base = GenerationRequest(
            model_id=payload.model_id,
            messages=[ChatMessage(role=MessageRole.USER, content=payload.content)],
            max_output_tokens=output_tokens,
            temperature=payload.temperature,
            top_p=payload.top_p,
            stop_sequences=payload.stop_sequences,
        )
        # Resolve provider and validate streaming capability before writing messages.
        model = self.llm_service.validate_stream_request(llm_request_base)

        conversation = await self.session.scalar(
            select(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if conversation is None:
            raise ApplicationError(
                code="conversation_not_found",
                message="The conversation was not found.",
                status_code=404,
            )

        # A concurrent request using the same idempotency key may have committed
        # while this request waited for the conversation row lock.
        existing = await self._find_idempotent_request(user_id, idempotency_key, lock=True)
        if existing is not None:
            return await self._prepare_replay(existing, request_hash)

        active = await self.session.scalar(
            select(GenerationRequestRecord).where(
                GenerationRequestRecord.conversation_id == conversation_id,
                GenerationRequestRecord.status.in_(("pending", "streaming")),
            )
            .with_for_update()
        )
        if active is not None:
            recovered = await self._recover_stale_generation(active)
            if not recovered:
                raise ApplicationError(
                    code="generation_in_progress",
                    message="A generation is already active for this conversation.",
                    status_code=409,
                    details={"generation_id": str(active.id)},
                )

        history_result = await self.session.scalars(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.role.in_(("user", "assistant")),
                Message.status == "complete",
            )
            .order_by(Message.sequence.desc())
            .limit(self.settings.generation_history_max_messages)
        )
        history = list(reversed(list(history_result.all())))

        try:
            selection = select_context(
                history=history,
                latest_user_content=payload.content,
                model=model,
                max_output_tokens=output_tokens,
                system_prompt=self.settings.generation_system_prompt,
                safety_factor=self.settings.generation_context_safety_factor,
            )
        except ValueError as exc:
            raise ApplicationError(
                code="context_window_exceeded",
                message=(
                    "The latest message is too large for the selected model's available context."
                ),
                status_code=422,
            ) from exc

        try:
            llm_request = GenerationRequest(
                model_id=payload.model_id,
                messages=selection.messages,
                max_output_tokens=output_tokens,
                temperature=payload.temperature,
                top_p=payload.top_p,
                stop_sequences=payload.stop_sequences,
            )
        except ValidationError as exc:
            raise ApplicationError(
                code="context_window_exceeded",
                message="The selected conversation history exceeds the model input limits.",
                status_code=422,
            ) from exc
        self.llm_service.validate_stream_request(llm_request)

        now = datetime.now(UTC)
        user_sequence = conversation.last_message_sequence + 1
        assistant_sequence = user_sequence + 1
        user_message_id = uuid4()
        assistant_message_id = uuid4()
        generation_id = uuid4()

        user_message = Message(
            id=user_message_id,
            conversation_id=conversation.id,
            role="user",
            content=payload.content,
            status="complete",
            sequence=user_sequence,
        )
        assistant_message = Message(
            id=assistant_message_id,
            conversation_id=conversation.id,
            role="assistant",
            content="",
            status="pending",
            sequence=assistant_sequence,
        )
        record = GenerationRequestRecord(
            id=generation_id,
            user_id=user_id,
            conversation_id=conversation.id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            provider_id=model.provider_id,
            model_id=model.id,
            status="pending",
            lease_expires_at=now + timedelta(
                seconds=self.settings.generation_max_duration_seconds + 30
            ),
        )
        conversation.last_message_sequence = assistant_sequence
        conversation.updated_at = now
        if user_sequence == 1 and conversation.title == DEFAULT_CONVERSATION_TITLE:
            conversation.title = self._derive_title(payload.content)

        self.session.add_all([user_message, assistant_message])
        try:
            # Flush referenced messages before inserting the generation row that
            # holds foreign keys to both message IDs.
            await self.session.flush()
            self.session.add(record)
            await self.session.flush()
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            existing = await self._find_idempotent_request(user_id, idempotency_key)
            if existing is not None:
                return await self._prepare_replay(existing, request_hash)
            raise ApplicationError(
                code="generation_conflict",
                message="Another generation was started for this conversation. Retry safely.",
                status_code=409,
            ) from exc
        except Exception:
            await self.session.rollback()
            raise

        return PreparedGeneration(
            generation_id=generation_id,
            conversation_id=conversation.id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            assistant_sequence=assistant_sequence,
            request=llm_request,
            model=model,
            estimated_input_tokens=selection.estimated_input_tokens,
        )

    async def stream(self, prepared: PreparedGeneration) -> AsyncIterator[OutboundGenerationEvent]:
        started_event = OutboundGenerationEvent(
            "generation.started",
            {
                "generation_id": str(prepared.generation_id),
                "conversation_id": str(prepared.conversation_id),
                "user_message_id": str(prepared.user_message_id),
                "assistant_message_id": str(prepared.assistant_message_id),
                "assistant_sequence": prepared.assistant_sequence,
                "replayed": prepared.replay,
            },
        )
        if prepared.replay:
            yield started_event
            async for event in self._replay(prepared):
                yield event
            return

        content_parts: list[str] = []
        content_length = 0
        persisted_length = 0
        latest_usage: TokenUsage | None = None
        finish_reason: str | None = None
        provider_request_id: str | None = None
        completed_marker_seen = False
        last_flush = asyncio.get_running_loop().time()

        try:
            await self._mark_started(prepared.generation_id, prepared.assistant_message_id)
            # Persist the streaming state before exposing the first SSE event. Keeping
            # this yield inside the try block ensures a client disconnect at the start
            # still finalizes the generation as interrupted.
            yield started_event
            async with asyncio.timeout(self.settings.generation_max_duration_seconds):
                attempt = 0
                while True:
                    iterator = self.llm_service.stream(
                        prepared.request  # type: ignore[arg-type]
                    ).__aiter__()
                    received_event = False
                    try:
                        async for event in self._next_or_cancel(iterator, prepared.generation_id):
                            if event is None:
                                break
                            if event is _HEARTBEAT:
                                now_loop = asyncio.get_running_loop().time()
                                if (
                                    content_length > persisted_length
                                    and now_loop - last_flush >= PARTIAL_FLUSH_INTERVAL_SECONDS
                                ):
                                    await self._persist_partial(
                                        prepared.generation_id,
                                        prepared.assistant_message_id,
                                        "".join(content_parts),
                                    )
                                    persisted_length = content_length
                                    last_flush = now_loop
                                yield OutboundGenerationEvent(
                                    "stream.heartbeat",
                                    {"generation_id": str(prepared.generation_id)},
                                )
                                continue
                            received_event = True
                            if event.type == GenerationEventType.TEXT_DELTA and event.text:
                                content_length += len(event.text)
                                if content_length > MAX_GENERATED_CONTENT_CHARACTERS:
                                    raise ApplicationError(
                                        code="generated_output_too_large",
                                        message="The generated response exceeded the allowed size.",
                                        status_code=502,
                                    )
                                content_parts.append(event.text)
                                now_loop = asyncio.get_running_loop().time()
                                if (
                                    content_length - persisted_length
                                    >= self.settings.generation_partial_flush_characters
                                    or now_loop - last_flush >= PARTIAL_FLUSH_INTERVAL_SECONDS
                                ):
                                    await self._persist_partial(
                                        prepared.generation_id,
                                        prepared.assistant_message_id,
                                        "".join(content_parts),
                                    )
                                    persisted_length = content_length
                                    last_flush = now_loop
                                yield OutboundGenerationEvent(
                                    "message.delta",
                                    {
                                        "generation_id": str(prepared.generation_id),
                                        "message_id": str(prepared.assistant_message_id),
                                        "text": event.text,
                                    },
                                )
                            elif event.type == GenerationEventType.USAGE and event.usage:
                                latest_usage = event.usage
                                yield OutboundGenerationEvent(
                                    "generation.usage",
                                    {
                                        "generation_id": str(prepared.generation_id),
                                        "input_tokens": event.usage.input_tokens,
                                        "output_tokens": event.usage.output_tokens,
                                        "total_tokens": event.usage.total_tokens,
                                        "source": "provider_reported",
                                    },
                                )
                            elif event.type == GenerationEventType.COMPLETED:
                                completed_marker_seen = True
                                latest_usage = event.usage or latest_usage
                                finish_reason = event.finish_reason
                                provider_request_id = event.provider_request_id
                        break
                    except ProviderError as exc:
                        await self._close_iterator(iterator)
                        if (
                            exc.retryable
                            and exc.code == "provider_rate_limited"
                            and not received_event
                            and attempt < self.settings.generation_max_retries
                        ):
                            delay = self._retry_delay(exc, attempt)
                            attempt += 1
                            await asyncio.sleep(delay)
                            if await self._is_cancelled(prepared.generation_id):
                                raise ExplicitGenerationCancellation
                            continue
                        raise
                    finally:
                        await self._close_iterator(iterator)

            if await self._is_cancelled(prepared.generation_id):
                raise ExplicitGenerationCancellation
            final_content = "".join(content_parts)
            if not completed_marker_seen or not final_content:
                raise ProviderResponseError(prepared.model.provider_id)  # type: ignore[union-attr]

            usage_snapshot, source, estimated_cost, currency, pricing_version = self._resolve_usage(
                prepared, latest_usage, final_content
            )
            terminal_status = await self._finalize(
                prepared,
                status="completed",
                content=final_content,
                usage=usage_snapshot,
                usage_source=source,
                estimated_cost=estimated_cost,
                currency=currency,
                pricing_version=pricing_version,
                finish_reason=finish_reason,
                provider_request_id=provider_request_id,
            )
            if terminal_status is None:
                yield OutboundGenerationEvent(
                    "generation.error",
                    {
                        "generation_id": str(prepared.generation_id),
                        "code": "generation_already_finalized",
                    },
                )
                return
            if terminal_status == "cancelled":
                yield OutboundGenerationEvent(
                    "generation.cancelled",
                    {
                        "generation_id": str(prepared.generation_id),
                        "message_id": str(prepared.assistant_message_id),
                    },
                )
                return
            yield OutboundGenerationEvent(
                "generation.completed",
                {
                    "generation_id": str(prepared.generation_id),
                    "message_id": str(prepared.assistant_message_id),
                    "finish_reason": finish_reason,
                    "provider_request_id": provider_request_id,
                    "usage": self._usage_payload(usage_snapshot, source, estimated_cost, currency),
                },
            )

        except ExplicitGenerationCancellation:
            final_content = "".join(content_parts)
            terminal_status = await self._finalize_terminal(
                prepared,
                status="cancelled",
                content=final_content,
                code="generation_cancelled",
                usage=latest_usage,
            )
            if terminal_status == "cancelled":
                yield OutboundGenerationEvent(
                    "generation.cancelled",
                    {
                        "generation_id": str(prepared.generation_id),
                        "message_id": str(prepared.assistant_message_id),
                    },
                )
            else:
                yield OutboundGenerationEvent(
                    "generation.error",
                    {
                        "generation_id": str(prepared.generation_id),
                        "code": "generation_already_finalized",
                    },
                )
        except asyncio.CancelledError:
            # Client disconnected or server is shutting down. Preserve partial output.
            final_content = "".join(content_parts)
            await self._finalize_terminal(
                prepared,
                status="interrupted",
                content=final_content,
                code="client_disconnected",
                usage=latest_usage,
            )
            raise
        except TimeoutError:
            final_content = "".join(content_parts)
            terminal_status = await self._finalize_terminal(
                prepared,
                status="interrupted" if final_content else "failed",
                content=final_content,
                code="generation_timeout",
                usage=latest_usage,
            )
            if terminal_status == "cancelled":
                yield OutboundGenerationEvent(
                    "generation.cancelled",
                    {"generation_id": str(prepared.generation_id)},
                )
            else:
                yield OutboundGenerationEvent(
                    "generation.error",
                    {
                        "generation_id": str(prepared.generation_id),
                        "code": "generation_timeout"
                        if terminal_status is not None
                        else "generation_already_finalized",
                    },
                )
        except ProviderError as exc:
            final_content = "".join(content_parts)
            terminal_status = await self._finalize_terminal(
                prepared,
                status="interrupted" if final_content else "failed",
                content=final_content,
                code=exc.code,
                usage=latest_usage,
                provider_request_id=provider_request_id,
            )
            if terminal_status == "cancelled":
                yield OutboundGenerationEvent(
                    "generation.cancelled",
                    {"generation_id": str(prepared.generation_id)},
                )
            else:
                yield OutboundGenerationEvent(
                    "generation.error",
                    {
                        "generation_id": str(prepared.generation_id),
                        "code": exc.code
                        if terminal_status is not None
                        else "generation_already_finalized",
                    },
                )
        except ApplicationError as exc:
            final_content = "".join(content_parts)
            terminal_status = await self._finalize_terminal(
                prepared,
                status="interrupted" if final_content else "failed",
                content=final_content,
                code=exc.code,
                usage=latest_usage,
            )
            if terminal_status == "cancelled":
                yield OutboundGenerationEvent(
                    "generation.cancelled",
                    {"generation_id": str(prepared.generation_id)},
                )
            else:
                yield OutboundGenerationEvent(
                    "generation.error",
                    {
                        "generation_id": str(prepared.generation_id),
                        "code": exc.code
                        if terminal_status is not None
                        else "generation_already_finalized",
                    },
                )
        except Exception as exc:
            final_content = "".join(content_parts)
            logger.error(
                "generation_unhandled_failure",
                extra={
                    "generation_id": str(prepared.generation_id),
                    "error_type": type(exc).__name__,
                },
            )
            terminal_status = await self._finalize_terminal(
                prepared,
                status="interrupted" if final_content else "failed",
                content=final_content,
                code="generation_failed",
                usage=latest_usage,
            )
            if terminal_status == "cancelled":
                yield OutboundGenerationEvent(
                    "generation.cancelled",
                    {"generation_id": str(prepared.generation_id)},
                )
            else:
                yield OutboundGenerationEvent(
                    "generation.error",
                    {
                        "generation_id": str(prepared.generation_id),
                        "code": "generation_failed"
                        if terminal_status is not None
                        else "generation_already_finalized",
                    },
                )

    async def get_generation(self, *, user_id: UUID, generation_id: UUID) -> tuple[Any, Any | None]:
        record = await self.session.scalar(
            select(GenerationRequestRecord)
            .where(
                GenerationRequestRecord.id == generation_id,
                GenerationRequestRecord.user_id == user_id,
            )
            .with_for_update()
        )
        if record is None:
            raise ApplicationError(
                code="generation_not_found",
                message="The generation was not found.",
                status_code=404,
            )
        if await self._recover_stale_generation(record):
            await self.session.commit()
        usage = await self.session.scalar(
            select(UsageLedger).where(UsageLedger.generation_id == generation_id)
        )
        return record, usage

    async def request_cancellation(self, *, user_id: UUID, generation_id: UUID) -> tuple[str, bool]:
        record = await self.session.scalar(
            select(GenerationRequestRecord)
            .where(
                GenerationRequestRecord.id == generation_id,
                GenerationRequestRecord.user_id == user_id,
            )
            .with_for_update()
        )
        if record is None:
            raise ApplicationError(
                code="generation_not_found",
                message="The generation was not found.",
                status_code=404,
            )
        if await self._recover_stale_generation(record):
            await self.session.commit()
            return record.status, False
        if record.status not in {"pending", "streaming"}:
            return record.status, False
        try:
            await self.redis.set(
                self._cancel_key(generation_id),
                "1",
                ex=self.settings.generation_cancel_signal_ttl_seconds,
            )
        except Exception as exc:
            await self.session.rollback()
            raise ApplicationError(
                code="cancellation_unavailable",
                message="The generation could not be cancelled right now. Retry the request.",
                status_code=503,
            ) from exc
        record.cancel_requested_at = datetime.now(UTC)
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return record.status, True

    async def _find_idempotent_request(
        self, user_id: UUID, idempotency_key: str, *, lock: bool = False
    ) -> GenerationRequestRecord | None:
        statement = select(GenerationRequestRecord).where(
            GenerationRequestRecord.user_id == user_id,
            GenerationRequestRecord.idempotency_key == idempotency_key,
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def _recover_stale_generation(self, record: GenerationRequestRecord) -> bool:
        """Mark a lease-expired generation interrupted; return whether recovery occurred."""
        if record.status not in {"pending", "streaming"} or record.lease_expires_at is None:
            return False
        lease_expires_at = record.lease_expires_at
        if lease_expires_at.tzinfo is None:
            lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        if lease_expires_at > now:
            return False

        assistant = await self.session.get(Message, record.assistant_message_id)
        if assistant is not None:
            assistant.status = "interrupted"
        record.status = "interrupted"
        record.error_code = "worker_lost"
        record.completed_at = now
        record.updated_at = now
        existing_usage = await self.session.scalar(
            select(UsageLedger.id).where(UsageLedger.generation_id == record.id)
        )
        if existing_usage is None:
            self.session.add(
                UsageLedger(
                    generation_id=record.id,
                    user_id=record.user_id,
                    provider_id=record.provider_id,
                    model_id=record.model_id,
                    usage_source="unavailable",
                )
            )
        await self.session.flush()
        return True

    async def _prepare_replay(
        self, record: GenerationRequestRecord, request_hash: str
    ) -> PreparedGeneration:
        # Re-read under row lock so a status response, cleanup request, or concurrent
        # retry cannot race a live generation's terminal transition.
        locked = await self.session.scalar(
            select(GenerationRequestRecord)
            .where(GenerationRequestRecord.id == record.id)
            .with_for_update()
        )
        if locked is None:
            raise ApplicationError(
                code="generation_not_found",
                message="The generation was not found.",
                status_code=404,
            )
        record = locked
        if record.request_hash != request_hash:
            raise ApplicationError(
                code="idempotency_key_reused",
                message="This Idempotency-Key was already used for a different request.",
                status_code=409,
            )
        if record.status in {"pending", "streaming"}:
            recovered = await self._recover_stale_generation(record)
            if recovered:
                await self.session.commit()
            else:
                generation_id = record.id
                await self.session.rollback()
                raise ApplicationError(
                    code="generation_in_progress",
                    message=(
                        "This idempotent generation is still in progress. "
                        "Retrieve its status instead."
                    ),
                    status_code=409,
                    details={"generation_id": str(generation_id)},
                )
        assistant = await self.session.get(Message, record.assistant_message_id)
        usage = await self.session.scalar(
            select(UsageLedger).where(UsageLedger.generation_id == record.id)
        )
        usage_payload = self._ledger_payload(usage) if usage is not None else None
        return PreparedGeneration(
            generation_id=record.id,
            conversation_id=record.conversation_id,
            user_message_id=record.user_message_id,
            assistant_message_id=record.assistant_message_id,
            assistant_sequence=assistant.sequence if assistant else 0,
            request=None,
            model=None,
            estimated_input_tokens=usage.input_tokens if usage and usage.input_tokens else 0,
            replay=True,
            replay_status=record.status,
            replay_content=assistant.content if assistant else "",
            replay_usage=usage_payload,
            replay_error_code=record.error_code,
            replay_finish_reason=record.finish_reason,
            replay_provider_request_id=record.provider_request_id,
        )

    async def _replay(self, prepared: PreparedGeneration) -> AsyncIterator[OutboundGenerationEvent]:
        if prepared.replay_status == "completed":
            content = prepared.replay_content
            for offset in range(0, len(content), 4096):
                yield OutboundGenerationEvent(
                    "message.delta",
                    {
                        "generation_id": str(prepared.generation_id),
                        "message_id": str(prepared.assistant_message_id),
                        "text": content[offset : offset + 4096],
                    },
                )
            if prepared.replay_usage:
                yield OutboundGenerationEvent(
                    "generation.usage",
                    {"generation_id": str(prepared.generation_id), **prepared.replay_usage},
                )
            yield OutboundGenerationEvent(
                "generation.completed",
                {
                    "generation_id": str(prepared.generation_id),
                    "message_id": str(prepared.assistant_message_id),
                    "finish_reason": prepared.replay_finish_reason,
                    "provider_request_id": prepared.replay_provider_request_id,
                    "usage": prepared.replay_usage,
                    "replayed": True,
                },
            )
        elif prepared.replay_status == "cancelled":
            yield OutboundGenerationEvent(
                "generation.cancelled",
                {"generation_id": str(prepared.generation_id), "replayed": True},
            )
        else:
            yield OutboundGenerationEvent(
                "generation.error",
                {
                    "generation_id": str(prepared.generation_id),
                    "code": prepared.replay_error_code or "generation_failed",
                    "replayed": True,
                },
            )

    async def _mark_started(self, generation_id: UUID, assistant_message_id: UUID) -> None:
        async with self.session_factory() as session:
            record = await session.scalar(
                select(GenerationRequestRecord)
                .where(GenerationRequestRecord.id == generation_id)
                .with_for_update()
            )
            message = await session.get(Message, assistant_message_id)
            if record is None or message is None or record.status != "pending":
                raise RuntimeError("Generation state was not pending at stream start")
            record.status = "streaming"
            record.started_at = datetime.now(UTC)
            record.updated_at = datetime.now(UTC)
            message.status = "streaming"
            await session.commit()

    async def _persist_partial(
        self, generation_id: UUID, assistant_message_id: UUID, content: str
    ) -> None:
        async with self.session_factory() as session:
            record = await session.scalar(
                select(GenerationRequestRecord)
                .where(GenerationRequestRecord.id == generation_id)
                .with_for_update()
            )
            message = await session.get(Message, assistant_message_id)
            if record is None or message is None or record.status != "streaming":
                return
            message.content = content
            message.status = "streaming"
            record.updated_at = datetime.now(UTC)
            await session.commit()

    async def _finalize_terminal(
        self,
        prepared: PreparedGeneration,
        *,
        status: str,
        content: str,
        code: str,
        usage: TokenUsage | None,
        provider_request_id: str | None = None,
    ) -> str | None:
        usage_snapshot, source, estimated_cost, currency, pricing_version = self._resolve_usage(
            prepared, usage, content
        )
        return await self._finalize(
            prepared,
            status=status,
            content=content,
            usage=usage_snapshot,
            usage_source=source,
            estimated_cost=estimated_cost,
            currency=currency,
            pricing_version=pricing_version,
            error_code=code,
            provider_request_id=provider_request_id,
        )

    async def _finalize(
        self,
        prepared: PreparedGeneration,
        *,
        status: str,
        content: str,
        usage: TokenUsage,
        usage_source: str,
        estimated_cost: Decimal | None,
        currency: str | None,
        pricing_version: str | None,
        error_code: str | None = None,
        finish_reason: str | None = None,
        provider_request_id: str | None = None,
    ) -> str | None:
        async with self.session_factory() as session:
            record = await session.scalar(
                select(GenerationRequestRecord)
                .where(GenerationRequestRecord.id == prepared.generation_id)
                .with_for_update()
            )
            message = await session.get(Message, prepared.assistant_message_id)
            if record is None or message is None:
                raise RuntimeError("Generation persistence records disappeared")
            if record.status in {"completed", "failed", "cancelled", "interrupted"}:
                return None
            # If the cancellation endpoint committed its request before this terminal
            # lock was acquired, cancellation wins even if the provider just finished.
            if record.cancel_requested_at is not None and status != "cancelled":
                status = "cancelled"
                error_code = "generation_cancelled"
            message.content = content
            message.status = "complete" if status == "completed" else status
            record.status = status
            record.error_code = error_code
            record.finish_reason = finish_reason
            record.provider_request_id = provider_request_id
            record.completed_at = datetime.now(UTC)
            record.updated_at = datetime.now(UTC)
            existing_usage = await session.scalar(
                select(UsageLedger).where(UsageLedger.generation_id == prepared.generation_id)
            )
            if existing_usage is None:
                session.add(
                    UsageLedger(
                        generation_id=prepared.generation_id,
                        user_id=record.user_id,
                        provider_id=record.provider_id,
                        model_id=record.model_id,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                        total_tokens=usage.total_tokens,
                        cached_input_tokens=usage.cached_input_tokens,
                        usage_source=usage_source,
                        estimated_cost=estimated_cost,
                        currency=currency,
                        pricing_version=pricing_version,
                    )
                )
            await session.commit()
            return status

    def _resolve_usage(
        self,
        prepared: PreparedGeneration,
        provider_usage: TokenUsage | None,
        content: str,
    ) -> tuple[TokenUsage, str, Decimal | None, str | None, str | None]:
        provider_input = provider_usage.input_tokens if provider_usage else None
        provider_output = provider_usage.output_tokens if provider_usage else None
        provider_cached = provider_usage.cached_input_tokens if provider_usage else None
        if provider_input is not None and provider_output is not None:
            usage_source = "provider_reported"
            input_tokens = provider_input
            output_tokens = provider_output
        else:
            usage_source = "estimated"
            input_tokens = (
                provider_input
                if provider_input is not None
                else prepared.estimated_input_tokens
            )
            output_tokens = (
                provider_output if provider_output is not None else estimate_text_tokens(content)
            )
        total_tokens = input_tokens + output_tokens
        usage = TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_input_tokens=provider_cached,
        )
        model = prepared.model
        if model is None:
            raise RuntimeError("Model configuration is unavailable for usage pricing")
        pricing = self._current_pricing(model)
        if pricing is None:
            return usage, usage_source, None, None, None

        input_rate = pricing.input_per_million_tokens
        output_rate = pricing.output_per_million_tokens
        if input_rate is None or output_rate is None:
            cost = None
        else:
            cached_tokens = min(provider_cached or 0, input_tokens)
            cached_rate = pricing.cached_input_per_million_tokens
            if cached_rate is None:
                input_cost = Decimal(input_tokens) * input_rate
            else:
                input_cost = (
                    Decimal(input_tokens - cached_tokens) * input_rate
                    + Decimal(cached_tokens) * cached_rate
                )
            cost = (
                (input_cost + Decimal(output_tokens) * output_rate) / Decimal(1_000_000)
            ).quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)
        return usage, usage_source, cost, pricing.currency, pricing.version

    @staticmethod
    def _current_pricing(model: Any) -> Any | None:
        if model is None:
            return None
        now = datetime.now(UTC)
        return max(
            (price for price in model.pricing if price.effective_from <= now),
            key=lambda item: item.effective_from,
            default=None,
        )

    async def _next_or_cancel(
        self, iterator: AsyncIterator[GenerationEvent], generation_id: UUID
    ) -> AsyncIterator[GenerationEvent | object | None]:
        if await self._is_cancelled(generation_id):
            raise ExplicitGenerationCancellation
        next_task = asyncio.create_task(iterator.__anext__())
        loop = asyncio.get_running_loop()
        last_heartbeat = loop.time()
        try:
            while True:
                done, _ = await asyncio.wait({next_task}, timeout=0.25)
                if next_task in done:
                    try:
                        yield next_task.result()
                    except StopAsyncIteration:
                        yield None
                    return
                if await self._is_cancelled(generation_id):
                    next_task.cancel()
                    await asyncio.gather(next_task, return_exceptions=True)
                    raise ExplicitGenerationCancellation
                if loop.time() - last_heartbeat >= SSE_HEARTBEAT_INTERVAL_SECONDS:
                    last_heartbeat = loop.time()
                    yield _HEARTBEAT
        except asyncio.CancelledError:
            if not next_task.done():
                next_task.cancel()
                await asyncio.gather(next_task, return_exceptions=True)
            raise

    async def _is_cancelled(self, generation_id: UUID) -> bool:
        if self.redis is None:
            return False
        value = await self.redis.get(self._cancel_key(generation_id))
        return value is not None

    async def _close_iterator(self, iterator: AsyncIterator[GenerationEvent]) -> None:
        close = getattr(iterator, "aclose", None)
        if callable(close):
            try:
                await close()
            except Exception:
                pass

    def _retry_delay(self, error: ProviderError, attempt: int) -> float:
        if error.retry_after_seconds is not None:
            return min(max(error.retry_after_seconds, 0.05), 10.0)
        return min(self.settings.generation_retry_base_seconds * (2**attempt), 10.0)

    @staticmethod
    def _cancel_key(generation_id: UUID) -> str:
        return f"ask_ai:generation:cancel:{generation_id}"

    @staticmethod
    def _request_hash(conversation_id: UUID, payload: GenerationCreateRequest) -> str:
        canonical = {
            "conversation_id": str(conversation_id),
            "content": payload.content,
            "model_id": payload.model_id,
            "requested_max_output_tokens": payload.max_output_tokens,
            "temperature": payload.temperature,
            "top_p": payload.top_p,
            "stop_sequences": payload.stop_sequences,
        }
        raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _derive_title(content: str) -> str:
        first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
        return first_line[:79].rstrip() + "…" if len(first_line) > 80 else first_line

    @staticmethod
    def _ledger_payload(ledger: UsageLedger) -> dict[str, Any]:
        return {
            "input_tokens": ledger.input_tokens,
            "output_tokens": ledger.output_tokens,
            "total_tokens": ledger.total_tokens,
            "cached_input_tokens": ledger.cached_input_tokens,
            "usage_source": ledger.usage_source,
            "estimated_cost": (
                str(ledger.estimated_cost) if ledger.estimated_cost is not None else None
            ),
            "currency": ledger.currency,
            "pricing_version": ledger.pricing_version,
        }

    @staticmethod
    def _usage_payload(
        usage: TokenUsage, source: str, estimated_cost: Decimal | None, currency: str | None
    ) -> dict[str, Any]:
        return {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
            "cached_input_tokens": usage.cached_input_tokens,
            "usage_source": source,
            "estimated_cost": str(estimated_cost) if estimated_cost is not None else None,
            "currency": currency,
        }
