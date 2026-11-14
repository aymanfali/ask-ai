# Security Threat Model — MVP

## Assets

Account credentials, refresh sessions, conversation content, provider credentials, usage/account limits, model configuration, operational logs, and service availability.

## Trust boundaries

1. Browser to API.
2. API to PostgreSQL/Redis.
3. API to external model providers.
4. CI/CD to deployment environment and secret store.

## Principal threats and controls

| Threat | Controls / verification |
|---|---|
| Broken object-level authorization | Scope every conversation/message query by authenticated user; test cross-user read/write/delete attempts. |
| Credential theft / session replay | Argon2id password hashing, short access-token TTL, hashed rotating refresh tokens, revocation, secure cookie/CSRF strategy. |
| Secret exposure | Secret manager or protected environment; never return provider keys; redact headers and environment; secret scanning. |
| Prompt and completion leakage | No content logging by default; explicit retention policy; access-controlled support diagnostics. |
| Unbounded consumption | Per-IP/user/model limits, concurrency caps, context/output ceilings, quota reservation and reconciliation. |
| Provider SSRF | No user-configurable base URLs in MVP; fixed provider endpoints and egress controls. |
| Malicious model output | Treat all model output as untrusted; safe Markdown rendering; no raw HTML execution; sanitize links and code blocks. |
| CORS/CSRF abuse | Explicit CORS origins; secure cookie settings; CSRF protection if cookie auth is used. |
| Retry storms / duplicate charges | Bounded retries, jitter, idempotency keys, unique ledger constraints, circuit-breaker policy where justified. |
| Stream resource exhaustion | Connection limits, timeouts, output caps, concurrency control, backpressure, cancellation cleanup. |
| Dependency/supply-chain compromise | Lockfiles, pinned CI actions, vulnerability scanning, least-privilege workflow permissions. |

## Required security tests

- User A cannot read or mutate User B's conversations/messages.
- Revoked/expired refresh tokens cannot mint new sessions.
- Malformed auth headers fail safely.
- Oversized prompt, output, and request body limits are enforced.
- Provider endpoint configuration cannot be influenced by end users.
- Logs and error payloads contain no credentials or full private conversation content.
- Model output cannot execute arbitrary HTML/script in the chat renderer.
- Rate limits work across multiple API replicas (Redis-backed).

## Operational policy

Security findings are triaged by severity. Critical and high-severity vulnerabilities block release. Incident response must include credential rotation, session revocation, log review, and user notification assessment. Retention and deletion policies must be documented before collecting production user data.
