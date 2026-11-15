from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ask_ai.database.session import get_db_session
from ask_ai.modules.auth.dependencies import get_current_user
from ask_ai.modules.auth.models import User
from ask_ai.modules.conversations.schemas import (
    ConversationCreateRequest,
    ConversationPageResponse,
    ConversationResponse,
    ConversationUpdateRequest,
    MessageCreateRequest,
    MessagePageResponse,
    MessageResponse,
)
from ask_ai.modules.conversations.service import ConversationService

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post(
    "",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a conversation",
)
async def create_conversation(
    payload: ConversationCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConversationResponse:
    conversation = await ConversationService(session).create_conversation(
        user_id=current_user.id,
        title=payload.title,
    )
    return ConversationResponse.model_validate(conversation)


@router.get(
    "",
    response_model=ConversationPageResponse,
    summary="List conversations",
)
async def list_conversations(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(min_length=1, max_length=512)] = None,
) -> ConversationPageResponse:
    items, next_cursor = await ConversationService(session).list_conversations(
        user_id=current_user.id,
        limit=limit,
        cursor=cursor,
    )
    return ConversationPageResponse(
        items=[ConversationResponse.model_validate(item) for item in items],
        next_cursor=next_cursor,
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationResponse,
    summary="Get a conversation",
)
async def get_conversation(
    conversation_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConversationResponse:
    conversation = await ConversationService(session).get_conversation(
        user_id=current_user.id,
        conversation_id=conversation_id,
    )
    return ConversationResponse.model_validate(conversation)


@router.patch(
    "/{conversation_id}",
    response_model=ConversationResponse,
    summary="Rename a conversation",
)
async def update_conversation(
    conversation_id: UUID,
    payload: ConversationUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConversationResponse:
    conversation = await ConversationService(session).update_conversation_title(
        user_id=current_user.id,
        conversation_id=conversation_id,
        title=payload.title,
    )
    return ConversationResponse.model_validate(conversation)


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a conversation",
)
async def delete_conversation(
    conversation_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    await ConversationService(session).soft_delete_conversation(
        user_id=current_user.id,
        conversation_id=conversation_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Append a user message",
)
async def append_message(
    conversation_id: UUID,
    payload: MessageCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MessageResponse:
    message = await ConversationService(session).append_user_message(
        user_id=current_user.id,
        conversation_id=conversation_id,
        content=payload.content,
    )
    return MessageResponse.model_validate(message)


@router.get(
    "/{conversation_id}/messages",
    response_model=MessagePageResponse,
    summary="List conversation messages",
)
async def list_messages(
    conversation_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before_sequence: Annotated[int | None, Query(ge=1)] = None,
) -> MessagePageResponse:
    items, next_before_sequence = await ConversationService(session).list_messages(
        user_id=current_user.id,
        conversation_id=conversation_id,
        limit=limit,
        before_sequence=before_sequence,
    )
    return MessagePageResponse(
        items=[MessageResponse.model_validate(item) for item in items],
        next_before_sequence=next_before_sequence,
    )
