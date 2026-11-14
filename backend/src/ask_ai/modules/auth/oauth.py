from authlib.integrations.starlette_client import OAuth

from ask_ai.core.config import Settings

GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
APPLE_DISCOVERY_URL = "https://appleid.apple.com/.well-known/openid-configuration"


def create_oauth_registry(settings: Settings) -> OAuth:
    oauth = OAuth()

    if settings.google_client_id and settings.google_client_secret:
        oauth.register(
            name="google",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret.get_secret_value(),
            server_metadata_url=GOOGLE_DISCOVERY_URL,
            client_kwargs={
                "scope": "openid email profile",
                "code_challenge_method": "S256",
            },
        )

    if settings.apple_client_id and settings.apple_client_secret:
        oauth.register(
            name="apple",
            client_id=settings.apple_client_id,
            # Apple client secrets are developer-signed ES256 JWTs, not ordinary passwords.
            client_secret=settings.apple_client_secret.get_secret_value(),
            server_metadata_url=APPLE_DISCOVERY_URL,
            client_kwargs={
                "scope": "openid email name",
                "token_endpoint_auth_method": "client_secret_post",
            },
        )

    return oauth
