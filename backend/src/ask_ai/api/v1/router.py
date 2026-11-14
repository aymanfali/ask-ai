from fastapi import APIRouter

from ask_ai.api.v1.endpoints import health

api_router = APIRouter()
api_router.include_router(health.router)
