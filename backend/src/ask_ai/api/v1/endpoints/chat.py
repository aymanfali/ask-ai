from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ask_ai.core.errors import ApplicationError
from ask_ai.database.session import get_db_session
from ask_ai.modules.auth.dependencies import get_current_user
from ask_ai.modules.auth.models import User
from ask_ai.modules.chat.schemas import (
    GenerationCancelResponse,
    GenerationCreateRequest,
    GenerationStatusResponse,
    GenerationUsageResponse,
)
from ask_ai.modules.chat.service import GenerationService

router = APIRouter(tags=["chat-generation"])


def _service(request: Request, session: AsyncSession) -> GenerationService:
    session_factory = getattr(request.app.state, "db_session_factory", None)
    if session_factory is None:
        raise RuntimeError("Database session factory has not been initialized")
    return GenerationService(
        session=session,
        session_factory=session_factory,
        llm_service=request.app.state.llm_service,
        catalog=request.app.state.llm_catalog,
        redis=getattr(request.app.state, "redis", None),
        settings=request.app.state.settings,
    )


def _format_sse(event_name: str, data: dict[str, object], event_id: int) -> str:
    serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event_id}\nevent: {event_name}\ndata: {serialized}\n\n"


@router.post(
    "/conversations/{conversation_id}/messages/stream",
    summary="Generate an assistant response as a server-sent event stream",
    response_class=StreamingResponse,
)
async def stream_conversation_message(
    conversation_id: UUID,
    payload: GenerationCreateRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ] = None,
) -> StreamingResponse:
    if idempotency_key is None:
        raise ApplicationError(
            code="idempotency_key_required",
            message="The Idempotency-Key header is required for generation requests.",
            status_code=400,
        )
    service = _service(request, session)
    prepared = await service.prepare_generation(
        user_id=current_user.id,
        conversation_id=conversation_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )

    async def event_stream():
        event_id = 0
        async for event in service.stream(prepared):
            event_id += 1
            yield _format_sse(event.name, event.data, event_id)

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        headers["X-Request-ID"] = str(request_id)
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=headers,
    )


@router.get(
    "/generations/{generation_id}",
    response_model=GenerationStatusResponse,
    summary="Get generation status and usage",
)
async def get_generation(
    generation_id: UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GenerationStatusResponse:
    record, usage = await _service(request, session).get_generation(
        user_id=current_user.id,
        generation_id=generation_id,
    )
    return GenerationStatusResponse(
        id=record.id,
        conversation_id=record.conversation_id,
        user_message_id=record.user_message_id,
        assistant_message_id=record.assistant_message_id,
        provider_id=record.provider_id,
        model_id=record.model_id,
        status=record.status,
        error_code=record.error_code,
        finish_reason=record.finish_reason,
        provider_request_id=record.provider_request_id,
        started_at=record.started_at,
        completed_at=record.completed_at,
        created_at=record.created_at,
        usage=GenerationUsageResponse.model_validate(usage) if usage is not None else None,
    )


@router.post(
    "/generations/{generation_id}/cancel",
    response_model=GenerationCancelResponse,
    summary="Request cancellation of an active generation",
)
async def cancel_generation(
    generation_id: UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GenerationCancelResponse:
    current_status, requested = await _service(request, session).request_cancellation(
        user_id=current_user.id,
        generation_id=generation_id,
    )
    return GenerationCancelResponse(
        generation_id=generation_id,
        status=current_status,
        cancellation_requested=requested,
    )
