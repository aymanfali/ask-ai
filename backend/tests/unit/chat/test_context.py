from types import SimpleNamespace

import pytest

from ask_ai.modules.chat.context import estimate_text_tokens, select_context
from ask_ai.modules.llm.config import LLMModelConfig
from ask_ai.modules.llm.schemas import MessageRole


def _model(context_window: int = 600) -> LLMModelConfig:
    return LLMModelConfig(
        id="provider:test-model",
        provider_id="provider",
        provider_model_id="test-model",
        name="Test model",
        context_window=context_window,
        max_output_tokens=200,
    )


def _message(role: str, content: str, status: str = "complete"):
    return SimpleNamespace(role=role, content=content, status=status)


def test_token_estimator_is_conservative_for_non_ascii_text() -> None:
    assert estimate_text_tokens("hello world") >= 3
    assert estimate_text_tokens("مرحبا بالعالم") >= len("مرحبا بالعالم")


def test_context_includes_system_prompt_latest_message_and_recent_history() -> None:
    history = [
        _message("user", "old question"),
        _message("assistant", "old answer"),
        _message("user", "recent question"),
        _message("assistant", "recent answer"),
        _message("assistant", "unfinished answer", status="streaming"),
    ]

    selected = select_context(
        history=history,
        latest_user_content="new question",
        model=_model(),
        max_output_tokens=100,
        system_prompt="Be helpful.",
        safety_factor=0.85,
    )

    assert selected.messages[0].role == MessageRole.SYSTEM
    assert selected.messages[-1].content == "new question"
    assert "unfinished answer" not in [item.content for item in selected.messages]
    assert selected.estimated_input_tokens <= selected.input_token_budget


def test_context_drops_oldest_history_as_a_contiguous_suffix() -> None:
    history = [
        _message("user", "old " + "x" * 700),
        _message("assistant", "old answer"),
        _message("user", "newer question"),
        _message("assistant", "newer answer"),
    ]
    selected = select_context(
        history=history,
        latest_user_content="latest question",
        model=_model(context_window=400),
        max_output_tokens=100,
        system_prompt=None,
        safety_factor=0.9,
    )
    contents = [item.content for item in selected.messages]
    assert "latest question" == contents[-1]
    assert "old answer" not in contents
    assert "newer answer" in contents
    assert selected.dropped_history_messages >= 2


def test_context_rejects_latest_message_that_cannot_fit() -> None:
    with pytest.raises(ValueError, match="latest message"):
        select_context(
            history=[],
            latest_user_content="x" * 5000,
            model=_model(context_window=400),
            max_output_tokens=100,
            system_prompt="system",
            safety_factor=0.85,
        )
