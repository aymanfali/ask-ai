# Authentication security model

## Trust boundaries

- The browser receives short-lived first-party access tokens and opaque HttpOnly refresh cookies.
- The API is the only component that knows the signing key, password hashes, refresh-token hashes, and provider client secrets.
- Google and Apple are trusted only after Authlib validates the OIDC authorization response and ID Token signature/claims using provider discovery/JWKS metadata.
- Redis stores rate-limit counters and short-lived OAuth exchange grants. PostgreSQL remains the durable source of truth for users, identities, and session families.

## Credential handling

- Passwords use Argon2id through `pwdlib[argon2]`; the registration policy is checked at both the request boundary and service boundary.
- Refresh tokens are random opaque values. Only SHA-256 digests are persisted.
- Access JWTs use HS256 with a server-side secret of at least 256 bits. The accepted algorithm is fixed in code. JWT, OAuth-session, and CSRF signers use purpose-separated derived keys.
- Refresh tokens are delivered only in HttpOnly cookies; they are not returned in response JSON.
- Access tokens should be held in browser memory, not persistent web storage.
- OAuth provider tokens are discarded after identity claims are validated.

## Session lifecycle

A login creates a refresh-token family. Refresh rotates the active token under a PostgreSQL row lock. An old token reuse signal revokes the entire family. A family has a 90-day absolute lifetime even when individual refresh tokens are rotated. Protected API requests verify that the access token's family still has an active token row, which makes logout and reuse detection immediately effective for that family.

## CSRF

Refresh/logout are cookie-authenticated and require a signed double-submit token. The CSRF cookie is host-only, is not HttpOnly, and must be mirrored in `X-CSRF-Token`. The value is also returned in token responses for SPAs on sibling subdomains. After a reload, `GET /auth/csrf` validates the active refresh-cookie session and returns a fresh CSRF token without exposing the refresh token. The server verifies cookie/header equality and HMAC bound to the current refresh-token verifier using `SECRET_KEY`. First-party refresh/CSRF cookies use the configured `AUTH_COOKIE_SAMESITE` policy (Lax by default) and are Secure in production. The separate OAuth-state cookie uses Lax for Google top-level GET callbacks; when Apple is configured, it uses `SameSite=None; Secure` because Apple posts the authorization response cross-site.

## OIDC callback handling

Google uses the authorization-code callback over GET. Apple requests `response_mode=form_post` as required when requesting its `email` or `name` scopes. The Apple callback accepts only URL-encoded POST data, enforces a small callback payload bound, rejects duplicate security parameters, and adapts the received `code`/`state` into the query-parameter shape consumed by Authlib's Starlette adapter while preserving the original signed session state. This adapter is necessary because the Starlette client callback interface reads callback values from query parameters. State, nonce, PKCE, issuer, and ID Token validation remain delegated to Authlib; the adapter does not validate or trust the identity claims itself.

## OIDC identity rules

OIDC provider subject (`sub`) is the durable external identifier. A new identity requires a verified email claim. A verified provider email is auto-linked only to a local account whose email is already verified. A matching unverified local account is rejected; a separate authenticated identity-linking flow is deferred. Unverified claims cannot create or link accounts. Apple may supply email/name only on first consent; existing provider-subject identities continue to authenticate without those optional claims.

## Abuse controls

Registration and login are rate-limited by client IP and hashed normalized email. Provider login starts are rate-limited per IP/provider. If Redis is unavailable, authentication rate-limited endpoints fail closed with 503 rather than silently disabling abuse controls. Do not trust `X-Forwarded-For` until the deployment config declares trusted proxy hops.

## Operational safeguards

- Never log passwords, access/refresh tokens, CSRF tokens, OAuth codes, provider ID tokens, or raw Authorization/Cookie headers.
- Keep provider secrets out of source control and frontend bundles.
- Set a unique secret per environment and rotate it only with a planned session invalidation window.
- Use HTTPS for every non-local environment.
- Restrict CORS to explicit frontend origins.
- Monitor repeated refresh reuse signals, login throttling, and OIDC callback failures without logging credentials or claims payloads.

## Residual limitations

- Email verification delivery, password reset, MFA/passkeys, account recovery, administrator session management, and audit retention policy are not part of this milestone.
- The email provider linking rule should be re-evaluated if additional providers have different trust semantics.
- The current OAuth code is stored in Redis for 60 seconds and is single-use; deployments must use a Redis version that supports `GETDEL` (Redis 6.2+).
