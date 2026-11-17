# Milestone 6 — Frontend chat experience

## Status

Implemented in the repository source. The frontend is a React 19 + TypeScript + Vite application that uses the backend's existing authentication, conversation, model-catalog, generation-status, cancellation, and POST-SSE contracts.

## User journeys

### Authentication

- Email/password sign-in and registration.
- Google and Apple buttons appear only when the backend reports those providers as configured.
- OAuth starts at the backend authorization endpoint. The callback returns a short-lived, single-use code in the URL fragment; the SPA exchanges that code with `POST /api/v1/auth/oauth/exchange` and immediately removes the fragment from browser history.
- Page reload restoration first obtains a CSRF token from `GET /api/v1/auth/csrf`, then rotates the HttpOnly refresh cookie through `POST /api/v1/auth/refresh`. Browser Web Locks serialize refresh rotation across tabs where supported; BroadcastChannel propagates sign-out/session-expiry events without sharing access tokens.

### Chat workspace

- Conversation list with local title search, cursor-based older-conversation loading, rename, and soft-delete.
- New conversations are created on the first message rather than leaving empty records behind.
- Persistent message history with cursor-based loading of older messages.
- Model selector is populated from the non-secret backend model catalog.
- Prompt suggestions, keyboard send behavior, streaming assistant output, stop generation, copy actions, and a run-prompt-again action.
- Per-generation token/cost metadata is displayed when supplied by the completed event.
- Loading, empty, unavailable-model, error, partial, failed, interrupted, and cancelled states are represented.

## API contract used

| Feature | Endpoint |
|---|---|
| Discover available sign-in providers | `GET /api/v1/auth/providers` |
| Login / register | `POST /api/v1/auth/login`, `POST /api/v1/auth/register` |
| Restore session / CSRF | `GET /api/v1/auth/csrf`, `POST /api/v1/auth/refresh` |
| Logout | `POST /api/v1/auth/logout` |
| OAuth exchange | `POST /api/v1/auth/oauth/exchange` |
| Conversations | `GET/POST /api/v1/conversations` |
| Rename / delete | `PATCH/DELETE /api/v1/conversations/{id}` |
| Message history | `GET /api/v1/conversations/{id}/messages` |
| Model catalog | `GET /api/v1/models`, `GET /api/v1/providers` |
| Stream generation | `POST /api/v1/conversations/{id}/messages/stream` |
| Generation status / cancel | `GET /api/v1/generations/{id}`, `POST /api/v1/generations/{id}/cancel` |

## Authentication and browser security

- Access tokens live in JavaScript memory only. They are not persisted in localStorage, sessionStorage, IndexedDB, or URL parameters.
- Cross-tab session coordination shares only sign-out/expiry events; bearer tokens are never broadcast.
- Refresh credentials remain in the backend's HttpOnly cookie. The client uses `credentials: include` and the backend's signed double-submit CSRF mechanism for refresh/logout.
- A single-flight refresh operation prevents concurrent 401 responses from rotating the refresh cookie repeatedly.
- API errors are parsed from the backend's `{ error: { code, message, details, request_id } }` envelope. Rejected input values are not rendered as error details.
- Provider credentials are never configured in Vite variables or sent from the browser.
- Markdown is rendered as React nodes; raw HTML is not interpreted. Links are restricted to HTTP, HTTPS, and mailto schemes and open with `noopener`/`noreferrer`.
- Remote font imports are intentionally avoided so the application does not make third-party font requests by default.

For a frontend and API on different sites, configure the backend cookies as `Secure` with `SameSite=None`, configure credentialed CORS for the exact frontend origin, and serve both over HTTPS. Same-site sibling subdomains can normally retain the backend's configured Lax policy. Do not use wildcard CORS with credentialed cookies.

## SSE behavior

The frontend uses `fetch()` with a POST JSON body and bearer authorization; native `EventSource` is not used because it cannot send the request body or Authorization header required by this endpoint.

The SSE reader handles UTF-8 boundaries, CRLF, comments/heartbeats, multi-line data, and JSON event payloads. It expects one terminal event: `generation.completed`, `generation.error`, or `generation.cancelled`. A stream that ends before a terminal event is treated as interrupted rather than silently successful.

The stop action first calls the generation cancellation endpoint and waits for the backend terminal event. If the stream does not close within a bounded fallback window, the browser aborts the connection; the backend will then persist an interrupted generation according to its disconnect policy.

## Scope boundaries and known limitations

- The backend does not currently expose a true assistant-message regeneration endpoint. **Run prompt again** deliberately submits the prior user prompt as a new conversation turn; it does not overwrite or mutate the prior assistant response.
- Usage is shown per response from the generation completion event. An aggregate account-wide usage dashboard is deferred until the backend exposes user-scoped usage summary/history endpoints.
- Profile editing, account recovery, MFA/passkeys, billing, attachments, RAG, and tool execution are outside this frontend milestone.
- There is no persistent browser draft/autosave. Draft content remains in component memory and is not written to browser storage.

## Local development

Prerequisites: Node.js 22.12+ (the SSE unit tests use Node's built-in type stripping), npm, and the running backend from Milestone 5.

```powershell
cd frontend
Copy-Item .env.example .env
npm install
npm test
npm run typecheck
npm run build
npm run dev
```

The Vite development server proxies `/api` to `http://127.0.0.1:8000`. Set `VITE_API_BASE_URL` only when using a separate API origin. Never use a `VITE_` variable for a secret.

## Verification

The repository includes focused unit tests for the SSE parser:

- events split across response chunks;
- CRLF and heartbeat comments;
- multiline data fields;
- malformed JSON payloads;
- stream termination without a terminal event;
- explicit terminal error events.

Before release, run the application against real PostgreSQL/Redis services and configured provider credentials, then complete the following browser checks:

1. Register and sign in; refresh the page and verify the refresh-cookie session is restored.
2. Sign out and verify protected endpoints reject the old access token.
3. Complete Google/Apple sign-in in a configured HTTPS environment.
4. Create, rename, search, paginate, select, and delete conversations.
5. Verify a user cannot load another user's conversation by changing its UUID.
6. Stream a long response, reload the history, and compare the persisted text.
7. Stop a generation and verify its terminal state and partial text.
8. Simulate provider timeout, rate limit, and network disconnect.
9. Verify model metadata contains no provider credentials.
10. Verify keyboard navigation, focus visibility, small-screen layout, and reduced-motion behavior.

The package does not claim a full browser/E2E test run until those checks are performed in the configured environment.
