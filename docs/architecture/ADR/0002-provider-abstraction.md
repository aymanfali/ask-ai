# ADR 0002: Provider-neutral LLM abstraction

- Status: Accepted
- Date: 2026-11-15

## Context

Ask AI must support more than one LLM provider without coupling chat, persistence, or API modules to provider SDK data structures. The product also needs stable model metadata and traceable pricing changes.

## Decision

Use a provider protocol with one adapter per upstream API shape. Start with an OpenAI Chat Completions-compatible adapter and a native Anthropic Messages adapter. Normalize text generation input, text results, token usage, stream deltas, finish reasons, and errors in the `modules/llm` domain. Build an app-scoped registry during FastAPI lifespan and close provider clients on shutdown.

Provider credentials and model catalog definitions are operator-managed environment configuration. They are not stored in the database or returned by public catalog endpoints in this milestone. Pricing is versioned by model, currency, and effective timestamp; unknown pricing remains unknown.

Use a modular monolith. Chat services call `LLMService`; provider adapters own all SDK-specific request and response mapping. Disable SDK retries so the future chat orchestration layer controls retry/failover based on persistence, idempotency, and whether output has reached a user.

## Consequences

- Adding a new provider requires an adapter and provider contract tests, not changes to conversation services.
- Provider configuration changes require process restart/redeployment for now.
- The initial normalized contract is text-only. Tool calling, vision payloads, audio, and structured output execution are future capabilities.
- A model's upstream capabilities are metadata and do not imply all corresponding Ask AI product features are already implemented.
- A generic user-supplied endpoint proxy is intentionally excluded due SSRF and secret-management risks.
