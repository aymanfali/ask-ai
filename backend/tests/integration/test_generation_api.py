from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ask_ai.core.config import Settings
from ask_ai.database.base import Base
from ask_ai.database.session import get_db_session
from ask_ai.main import create_app
from ask_ai.modules.auth.dependencies import get_current_user
from ask_ai.modules.auth.models import User
from ask_ai.modules.chat.models import GenerationRequestRecord, UsageLedger
from ask_ai.modules.conversations.models import Conversation, Message
from ask_ai.modules.llm.catalog import ModelCatalog
from ask_ai.modules.llm.config import (
    LLMModelConfig,
    ModelCapabilitiesConfig,
    OpenAICompatibleProviderConfig,
    PricingVersionConfig,
)
from ask_ai.modules.llm.errors import ProviderRateLimitError
from ask_ai.modules.llm.registry import ProviderRegistry
from ask_ai.modules.llm.schemas import GenerationEvent, GenerationEventType, TokenUsage
from ask_ai.modules.llm.service import LLMService


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.values[key] = value
        return True


class FakeProvider:
    provider_id = "openai"
    provider_name = "OpenAI test provider"
    provider_type = "openai_compatible"

    def __init__(self, *, fail_before_first_event: bool = False) -> None:
        self.calls = 0
        self.fail_before_first_event = fail_before_first_event

    async def generate(self, model, request):  # pragma: no cover - not used by this milestone
        raise NotImplementedError

    async def stream(self, model, request) -> AsyncIterator[GenerationEvent]:
        self.calls += 1
        if self.fail_before_first_event and self.calls == 1:
            raise ProviderRateLimitError(self.provider_id, retry_after_seconds=0.01)
        yield GenerationEvent(type=GenerationEventType.TEXT_DELTA, text="Hello ")
        yield GenerationEvent(type=GenerationEventType.TEXT_DELTA, text="Ask AI")
        usage = TokenUsage(input_tokens=20, output_tokens=3, total_tokens=23)
        yield GenerationEvent(type=GenerationEventType.USAGE, usage=usage)
        yield GenerationEvent(
            type=GenerationEventType.COMPLETED,
            usage=usage,
            finish_reason="stop",
            provider_request_id="request-test-123",
        )

    async def close(self) -> None:
        return None


@pytest.fixture
async def generation_api():
    # SQLite is sufficient for HTTP lifecycle tests; PostgreSQL-specific locking and
    # migration/concurrency behavior are covered by the PostgreSQL integration suite.
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    async with factory() as session:
        user = User(email=f"generation-{uuid4().hex}@example.test", is_active=True)
        session.add(user)
        await session.flush()
        conversation = Conversation(user_id=user.id, title="New conversation")
        session.add(conversation)
        await session.commit()
        await session.refresh(user)
        await session.refresh(conversation)

    provider_config = OpenAICompatibleProviderConfig(
        id="openai",
        name="OpenAI test provider",
        type="openai_compatible",
        api_key="test-provider-key",
        base_url="https://api.example.test/v1",
    )
    model_config = LLMModelConfig(
        id="openai:test-model",
        provider_id="openai",
        provider_model_id="test-model",
        name="Test model",
        context_window=16_000,
        max_output_tokens=2_000,
        capabilities=ModelCapabilitiesConfig(streaming=True),
        pricing=(
            PricingVersionConfig(
                version="test-pricing-v1",
                effective_from=datetime(2026, 1, 1, tzinfo=UTC),
                currency="USD",
                input_per_million_tokens=Decimal("1.00"),
                output_per_million_tokens=Decimal("2.00"),
            ),
        ),
    )
    settings = Settings(
        app_env="test",
        secret_key="test-generation-api-secret-that-is-long-enough",
        generation_max_retries=1,
        llm_providers=[provider_config],
        llm_models=[model_config],
    )
    app = create_app(settings)
    fake_provider = FakeProvider(fail_before_first_event=True)
    catalog = ModelCatalog(providers=[provider_config], models=[model_config])
    app.state.llm_catalog = catalog
    app.state.llm_service = LLMService(
        catalog=catalog,
        registry=ProviderRegistry([fake_provider]),
    )
    app.state.db_session_factory = factory
    app.state.redis = FakeRedis()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    async def override_user() -> User:
        return user

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield client, user, conversation, factory, fake_provider
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_generation_stream_persists_messages_usage_and_idempotent_replay(
    generation_api,
) -> None:
    client, user, conversation, factory, provider = generation_api
    endpoint = f"/api/v1/conversations/{conversation.id}/messages/stream"
    headers = {"Idempotency-Key": "generation-test-key-0001"}
    body = {"content": "Say hello", "model_id": "openai:test-model"}

    response = await client.post(endpoint, json=body, headers=headers)
    assert response.status_code == 200
    assert "event: generation.started" in response.text
    assert "event: message.delta" in response.text
    assert "event: generation.completed" in response.text
    assert provider.calls == 2  # one safe retry before any provider event was emitted

    async with factory() as session:
        generation = await session.scalar(
            select(GenerationRequestRecord).where(
                GenerationRequestRecord.user_id == user.id,
                GenerationRequestRecord.idempotency_key == headers["Idempotency-Key"],
            )
        )
        assert generation is not None
        assert generation.status == "completed"
        user_message = await session.get(Message, generation.user_message_id)
        assistant_message = await session.get(Message, generation.assistant_message_id)
        assert user_message is not None and user_message.content == "Say hello"
        assert assistant_message is not None and assistant_message.content == "Hello Ask AI"
        assert assistant_message.status == "complete"
        assert assistant_message.sequence == user_message.sequence + 1
        ledger = await session.scalar(
            select(UsageLedger).where(UsageLedger.generation_id == generation.id)
        )
        assert ledger is not None
        assert ledger.usage_source == "provider_reported"
        assert ledger.total_tokens == 23
        assert ledger.currency == "USD"

    replay = await client.post(endpoint, json=body, headers=headers)
    assert replay.status_code == 200
    assert "replayed" in replay.text
    assert provider.calls == 2

    mismatch = await client.post(
        endpoint,
        json={"content": "different payload", "model_id": "openai:test-model"},
        headers=headers,
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "idempotency_key_reused"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_generation_rejects_missing_idempotency_key(generation_api) -> None:
    client, _user, conversation, _factory, _provider = generation_api
    response = await client.post(
        f"/api/v1/conversations/{conversation.id}/messages/stream",
        json={"content": "hello", "model_id": "openai:test-model"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "idempotency_key_required"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stale_generation_is_recovered_when_same_idempotency_key_is_retried(
    generation_api,
) -> None:
    from datetime import timedelta

    from ask_ai.modules.chat.schemas import GenerationCreateRequest
    from ask_ai.modules.chat.service import GenerationService

    client, user, conversation, factory, provider = generation_api
    provider_config = OpenAICompatibleProviderConfig(
        id="openai",
        name="OpenAI test provider",
        type="openai_compatible",
        api_key="test-provider-key",
        base_url="https://api.example.test/v1",
    )
    model_config = LLMModelConfig(
        id="openai:test-model",
        provider_id="openai",
        provider_model_id="test-model",
        name="Test model",
        context_window=16_000,
        max_output_tokens=2_000,
        capabilities=ModelCapabilitiesConfig(streaming=True),
    )
    catalog = ModelCatalog(providers=[provider_config], models=[model_config])
    settings = Settings(
        app_env="test",
        secret_key="test-generation-api-secret-that-is-long-enough",
        llm_providers=[provider_config],
        llm_models=[model_config],
    )
    payload = GenerationCreateRequest(content="Recover abandoned work", model_id=model_config.id)
    key = "generation-stale-retry-0001"

    async with factory() as session:
        service = GenerationService(
            session=session,
            session_factory=factory,
            llm_service=LLMService(
                catalog=catalog,
                registry=ProviderRegistry([provider]),
            ),
            catalog=catalog,
            redis=FakeRedis(),
            settings=settings,
        )
        prepared = await service.prepare_generation(
            user_id=user.id,
            conversation_id=conversation.id,
            payload=payload,
            idempotency_key=key,
        )
        record = await session.get(GenerationRequestRecord, prepared.generation_id)
        assert record is not None
        record.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    response = await client.post(
        f"/api/v1/conversations/{conversation.id}/messages/stream",
        json=payload.model_dump(),
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 200
    assert "event: generation.started" in response.text
    assert '"code":"worker_lost"' in response.text
    assert provider.calls == 0

    async with factory() as session:
        record = await session.get(GenerationRequestRecord, prepared.generation_id)
        assert record is not None and record.status == "interrupted"
        message = await session.get(Message, record.assistant_message_id)
        assert message is not None and message.status == "interrupted"
        usage = await session.scalar(
            select(UsageLedger).where(UsageLedger.generation_id == prepared.generation_id)
        )
        assert usage is not None and usage.usage_source == "unavailable"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_committed_cancellation_wins_over_late_success_finalization(generation_api) -> None:
    from datetime import timedelta

    from ask_ai.modules.chat.service import GenerationService, PreparedGeneration
    from ask_ai.modules.llm.schemas import TokenUsage

    _client, user, conversation, factory, provider = generation_api
    provider_config = OpenAICompatibleProviderConfig(
        id="openai",
        name="OpenAI test provider",
        type="openai_compatible",
        api_key="test-provider-key",
        base_url="https://api.example.test/v1",
    )
    model_config = LLMModelConfig(
        id="openai:test-model",
        provider_id="openai",
        provider_model_id="test-model",
        name="Test model",
        context_window=16_000,
        max_output_tokens=2_000,
        capabilities=ModelCapabilitiesConfig(streaming=True),
    )
    catalog = ModelCatalog(providers=[provider_config], models=[model_config])
    settings = Settings(
        app_env="test",
        secret_key="test-generation-api-secret-that-is-long-enough",
        llm_providers=[provider_config],
        llm_models=[model_config],
    )
    generation_id = uuid4()
    user_message_id = uuid4()
    assistant_message_id = uuid4()
    now = datetime.now(UTC)

    async with factory() as session:
        parent = await session.get(Conversation, conversation.id)
        assert parent is not None
        user_sequence = parent.last_message_sequence + 1
        assistant_sequence = user_sequence + 1
        parent.last_message_sequence = assistant_sequence
        user_message = Message(
            id=user_message_id,
            conversation_id=conversation.id,
            role="user",
            content="Generate a response",
            status="complete",
            sequence=user_sequence,
        )
        assistant_message = Message(
            id=assistant_message_id,
            conversation_id=conversation.id,
            role="assistant",
            content="The full response",
            status="streaming",
            sequence=assistant_sequence,
        )
        session.add_all([user_message, assistant_message])
        await session.flush()
        session.add(
            GenerationRequestRecord(
                id=generation_id,
                user_id=user.id,
                conversation_id=conversation.id,
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
                idempotency_key="cancel-finalization-race-0001",
                request_hash="a" * 64,
                provider_id="openai",
                model_id=model_config.id,
                status="streaming",
                cancel_requested_at=now,
                lease_expires_at=now + timedelta(minutes=1),
                started_at=now,
            )
        )
        await session.commit()

    service = GenerationService(
        session=None,  # type: ignore[arg-type]
        session_factory=factory,
        llm_service=LLMService(
            catalog=catalog,
            registry=ProviderRegistry([provider]),
        ),
        catalog=catalog,
        redis=FakeRedis(),
        settings=settings,
    )
    prepared = PreparedGeneration(
        generation_id=generation_id,
        conversation_id=conversation.id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        assistant_sequence=assistant_sequence,
        request=None,
        model=model_config,
        estimated_input_tokens=12,
    )
    terminal_status = await service._finalize(
        prepared,
        status="completed",
        content="The full response",
        usage=TokenUsage(input_tokens=12, output_tokens=4, total_tokens=16),
        usage_source="provider_reported",
        estimated_cost=None,
        currency=None,
        pricing_version=None,
        finish_reason="stop",
    )

    assert terminal_status == "cancelled"
    async with factory() as session:
        record = await session.get(GenerationRequestRecord, generation_id)
        message = await session.get(Message, assistant_message_id)
        ledger = await session.scalar(
            select(UsageLedger).where(UsageLedger.generation_id == generation_id)
        )
        assert record is not None and record.status == "cancelled"
        assert record.error_code == "generation_cancelled"
        assert message is not None and message.status == "cancelled"
        assert ledger is not None and ledger.usage_source == "provider_reported"
