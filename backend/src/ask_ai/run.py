import uvicorn

from ask_ai.core.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "ask_ai.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.app_env == "local" and settings.app_debug,
        proxy_headers=True,
    )


if __name__ == "__main__":
    main()
