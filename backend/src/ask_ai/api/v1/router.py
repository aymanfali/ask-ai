from fastapi import APIRouter

from ask_ai.api.v1.endpoints import auth, conversations, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(conversations.router)
