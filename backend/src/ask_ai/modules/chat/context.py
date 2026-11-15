from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor

from ask_ai.modules.conversations.models import Message
from ask_ai.modules.llm.config import LLMModelConfig
from ask_ai.modules.llm.schemas import ChatMessage, MessageRole


@dataclass(frozen=True, slots=True)
class ContextSelection:
    messages: list[ChatMessage]
    estimated_input_tokens: int
    dropped_history_messages: int
    input_token_budget: int


def estimate_text_tokens(text: str) -> int:
    """Conservative, dependency-free estimate (not a provider tokenizer).

    ASCII text is budgeted at roughly one token per three characters; non-ASCII
    characters are counted individually. This intentionally overestimates many
    languages and must never be presented as provider-reported usage.
    """
    if not text:
        return 0
    ascii_characters = sum(1 for character in text if ord(character) < 128)
    non_ascii_characters = len(text) - ascii_characters
    return max(1, ceil(ascii_characters / 3) + non_ascii_characters)


def estimate_message_tokens(message: ChatMessage) -> int:
    # Four tokens are reserved for role/message framing. This is a planning estimate.
    return 4 + estimate_text_tokens(message.content)


def estimate_messages_tokens(messages: list[ChatMessage]) -> int:
    return sum(estimate_message_tokens(message) for message in messages) + 2


def select_context(
    *,
    history: list[Message],
    latest_user_content: str,
    model: LLMModelConfig,
    max_output_tokens: int,
    system_prompt: str | None,
    safety_factor: float,
) -> ContextSelection:
    """Keep the newest complete turns that fit inside a conservative model budget."""
    input_budget = floor((model.context_window - max_output_tokens) * safety_factor)
    if input_budget < 1:
        raise ValueError("The selected output budget leaves no room for input context")

    system_messages = (
        [ChatMessage(role=MessageRole.SYSTEM, content=system_prompt)]
        if system_prompt and system_prompt.strip()
        else []
    )
    latest = ChatMessage(role=MessageRole.USER, content=latest_user_content)
    minimum = system_messages + [latest]
    minimum_tokens = estimate_messages_tokens(minimum)
    if minimum_tokens > input_budget:
        raise ValueError("The latest message exceeds the selected model's available context")

    selected_reversed: list[ChatMessage] = []
    used_tokens = minimum_tokens
    dropped = 0
    eligible = [
        row
        for row in history
        if row.role in {"user", "assistant"} and row.status == "complete"
    ]
    for index in range(len(eligible) - 1, -1, -1):
        row = eligible[index]
        candidate = ChatMessage(role=MessageRole(row.role), content=row.content)
        cost = estimate_message_tokens(candidate)
        if used_tokens + cost > input_budget:
            # Preserve a contiguous suffix of history; never include older messages
            # while silently omitting a newer turn that did not fit.
            dropped += index + 1
            break
        selected_reversed.append(candidate)
        used_tokens += cost

    # Do not preserve an orphaned assistant answer when its initiating user turn
    # was dropped at the context boundary. An unfinished latest user turn is valid.
    if selected_reversed and selected_reversed[-1].role == MessageRole.ASSISTANT:
        selected_reversed.pop()
        dropped += 1
        used_tokens = estimate_messages_tokens(
            system_messages + list(reversed(selected_reversed)) + [latest]
        )

    chronological_history = list(reversed(selected_reversed))
    messages = system_messages + chronological_history + [latest]
    return ContextSelection(
        messages=messages,
        estimated_input_tokens=estimate_messages_tokens(messages),
        dropped_history_messages=dropped,
        input_token_budget=input_budget,
    )
