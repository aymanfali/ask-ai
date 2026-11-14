# Milestone 2 — Authentication and authorization

Status: Implemented in the source tree; run the full locked-dependency test suite and PostgreSQL concurrency tests before production use.

## Delivered

- Email registration and login with normalized email identifiers; password policy is enforced in both the request schema and service layer.
- Argon2id password hashing through `pwdlib[argon2]` (hashing and verification are run in a worker thread).
- Short-lived HS256 access tokens with fixed algorithm, issuer, audience, subject, session-family ID, token ID, `iat`, `nbf`, and `exp` validation.
- Opaque refresh tokens generated from cryptographic randomness. Only SHA-256 token verifiers are stored.
- Refresh-token rotation, token-family reuse detection, per-family revocation, and a fixed absolute session lifetime.
- Immediate access-token invalidation after logout/reuse detection by checking for an active session-family row on authenticated requests.
- Double-submit CSRF tokens signed with the application secret and required for refresh/logout.
- Redis-backed atomic authentication rate limits. The API fails closed if the rate limiter is unavailable.
- Google and Apple OpenID Connect authorization-code callbacks through Authlib. Provider login is optional and disabled until credentials are configured.
- Validated provider claims, verified-email requirement for first-time accounts, subject-based identity lookup, and safe linking only to already-verified local accounts.
- One-time OAuth exchange codes stored in Redis by hash, with a short TTL and atomic `GETDEL` exchange.
- Auth identity and refresh-session migrations.

## API routes

All routes are under `/api/v1`.

| Method | Route | Purpose |
|---|---|---|
| GET | `/auth/providers` | List configured OIDC providers |
| GET | `/auth/csrf` | Rehydrate an in-memory CSRF token from an active refresh-cookie session |
| POST | `/auth/register` | Create account and issue access token |
| POST | `/auth/login` | Authenticate email/password |
| POST | `/auth/refresh` | Rotate refresh token (CSRF required) |
| POST | `/auth/logout` | Revoke current device session family (CSRF required) |
| GET | `/auth/me` | Return the authenticated user |
| GET | `/auth/google/login` | Start Google OIDC (when configured) |
| GET | `/auth/google/callback` | Google OIDC callback |
| GET | `/auth/apple/login` | Start Apple OIDC (when configured) |
| POST | `/auth/apple/callback` | Apple OIDC `form_post` callback |
| POST | `/auth/oauth/exchange` | Exchange short-lived OIDC code for an application session |

### Email registration

```http
POST /api/v1/auth/register
Content-Type: application/json

{
  "email": "person@example.com",
  "password": "a-long-user-chosen-passphrase",
  "display_name": "Example Person"
}
```

A successful response contains an access token and public user data. The refresh token is never returned in JSON; it is set as an `HttpOnly` cookie. The signed CSRF value is returned as `csrf_token` in the auth response and also set in a host-only cookie. Keep the response value in application memory and mirror it in `X-CSRF-Token`; this also works when the frontend and API are on different subdomains.

### Authenticated request

```http
GET /api/v1/auth/me
Authorization: Bearer <access_token>
```

### Refresh

After a browser reload, first rehydrate the CSRF token from the active refresh-cookie session:

```http
GET /api/v1/auth/csrf
```

Keep the returned `csrf_token` in application memory, then send it in the header while the browser includes the HttpOnly refresh cookie:

```http
POST /api/v1/auth/refresh
X-CSRF-Token: <csrf_token>
```

The refresh endpoint rotates the refresh token. The previous token becomes unusable. If a previously rotated token is presented again, all refresh tokens in that device's family are revoked; the client must authenticate again.

### Logout

```http
POST /api/v1/auth/logout
X-CSRF-Token: <csrf_token>
```

Logout revokes every refresh token in the current session family. Access tokens from that family are rejected immediately because authentication checks the family in PostgreSQL.

## Frontend integration notes

- Keep the access token in application memory; do not put it in `localStorage` or `sessionStorage`.
- Send requests with `credentials: "include"` so the browser sends the refresh and OAuth state cookies.
- Keep the response `csrf_token` in memory and send it in `X-CSRF-Token` on refresh and logout. Do not persist it in localStorage or sessionStorage.
- After a page reload, call `GET /auth/csrf` with credentials enabled to rehydrate the CSRF value in memory, then call `/auth/refresh` to obtain a new access token.
- After OIDC callback, read the one-time `code` from `window.location.hash`, immediately remove the fragment with `history.replaceState`, and POST the code to `/auth/oauth/exchange` with credentials enabled. Do not send the code to analytics or logs.
- Concurrent refresh attempts from separate tabs can trigger strict refresh-token reuse detection and revoke that session family; coordinate refreshes in the client (single-flight or cross-tab coordination) so only one request rotates a token at a time.
- The backend redirects to a fixed configured `FRONTEND_AUTH_CALLBACK_URL`; it does not accept a caller-supplied arbitrary return URL.

## Google setup

1. Create a Web OAuth client in Google Cloud Console.
2. Add the exact value of `GOOGLE_REDIRECT_URI` as an authorized redirect URI. Local default: `http://localhost:8000/api/v1/auth/google/callback`.
3. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in the backend environment.
4. Ensure the frontend origin is in `CORS_ORIGINS` and set `FRONTEND_AUTH_CALLBACK_URL`.

Authlib uses Google's OIDC discovery metadata and requests `openid email profile`. Authorization Code + PKCE S256 is enabled.

## Apple setup

1. Configure Sign in with Apple for an Apple Developer primary App ID.
2. Create a Services ID for the web client and associate the verified domain/return URL. The return URL must point to the backend POST callback (`/api/v1/auth/apple/callback`).
3. Create a Sign in with Apple private key.
4. Generate an Apple client-secret JWT signed with ES256 using the Team ID, Services ID (client ID), Key ID, and private key. Set that signed JWT as `APPLE_CLIENT_SECRET`.
5. Set `APPLE_CLIENT_ID` and the exact `APPLE_REDIRECT_URI` in the backend environment.
6. Rotate the developer-signed client-secret JWT before its expiry; Apple limits its validity period.

The Apple OAuth client uses `client_secret_post` at the token endpoint. Never commit the Apple private key or client-secret JWT.

## Security and lifecycle decisions

- Passwords: minimum 12 characters, maximum 128 characters/1024 UTF-8 bytes, no NUL; no arbitrary composition rules. Argon2id is supplied by pwdlib's recommended hasher. Benchmark work factors on production hardware.
- Access tokens: 15 minutes by default; HS256 is hard-coded rather than selected from token headers. JWT, OAuth-session, and CSRF signing use separately derived keys from `SECRET_KEY`.
- Refresh tokens: opaque 48-byte random tokens; database stores SHA-256 digests only. Normal lifetime 30 days, maximum family lifetime 90 days.
- Rotation: each refresh consumes one token and creates one replacement. PostgreSQL `SELECT ... FOR UPDATE` serializes concurrent refresh attempts. Reuse revokes the family.
- Access token revocation: every protected request verifies that the token's family still has an active refresh-session row. This adds a database lookup but provides immediate logout/reuse invalidation.
- CSRF: signed double-submit token; refresh and logout require matching cookie/header plus HMAC validation. Cookies are host-only (no Domain attribute), `SameSite=Lax` by default, and `Secure` in production.
- OAuth state: Authlib stores state/nonce/PKCE verifier in a short-lived signed, HttpOnly session cookie. Google returns by top-level GET and uses a `SameSite=Lax` OAuth-state cookie. Apple requires `response_mode=form_post` when requesting email/name scopes; its OAuth-state cookie therefore uses `SameSite=None; Secure`, and the backend safely normalizes the bounded URL-encoded form into the callback parameter interface Authlib expects. The callback is exact-match configured; its response uses a one-time, 60-second exchange code in the URL fragment.
- Identity linking: existing provider subject is authoritative. A new provider identity requires an OIDC-validated subject and verified email. A provider identity is automatically linked only when its verified email matches a local account whose email is already verified. A matching unverified local account is rejected; a separate authenticated identity-linking flow is deferred.
- Provider tokens: ID/access tokens received from Google/Apple are not retained after the callback.
- Rate limits: registration 5/IP and 3/email per 10 minutes; password login 10/IP and 8/email per 10 minutes; OAuth start 10/IP/provider per 10 minutes. Keys use an email SHA-256 digest, not raw email.
- Generic login errors avoid indicating whether an email is registered.
- Authentication responses set `Cache-Control: no-store` and `Pragma: no-cache`.

## Configuration

See the authentication section in the root `.env.example`. Production must set:

- A unique random `SECRET_KEY` of at least 32 bytes.
- `AUTH_COOKIE_SECURE=true`.
- HTTPS frontend callback and OAuth redirect URIs.
- `rediss://` Redis URL and TLS PostgreSQL connection.
- Strong database credentials and provider secrets supplied by a secret manager.

`GOOGLE_*` and `APPLE_*` settings are optional. If a provider is not configured, it is omitted from `/auth/providers` and its login route returns 503.

## Migration

Apply migrations from `backend/`:

```powershell
uv run alembic upgrade head
```

The migration `20261114_0002_authentication` creates `users`, `auth_identities`, and `refresh_sessions`.

## Verification

```powershell
cd backend
uv run pytest -q
uv run ruff check src tests
uv run mypy src/ask_ai
uv run alembic upgrade head
```

The SQLite-based async unit tests require the `aiosqlite` development dependency. Run the PostgreSQL-only concurrent refresh integration test against a disposable database before deployment.


## Implementation hardening notes

- Registration creates the first refresh-token family in the same database transaction as the user record.
- `GET /api/v1/auth/csrf` rehydrates a signed CSRF token after SPA reload; the route validates that the HttpOnly refresh cookie still represents an active session and emits `Cache-Control: no-store`.
- A verified OIDC email is not sufficient to auto-link an unverified local account. Such linking is rejected with `account_link_required` until an authenticated linking flow is implemented.
- OIDC callbacks convert expected OAuth, JOSE token-validation, and HTTP transport failures into a generic frontend failure redirect without exposing provider error details.
