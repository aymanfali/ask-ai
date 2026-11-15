# LLM Foundation

## Scope

The LLM foundation provides a provider-neutral contract, operator-managed provider configuration, a model catalog, two adapter implementations, and a small orchestration facade. It deliberately does **not** expose a user-facing generation endpoint; that is delivered in Milestone 5 with generation persistence, quotas, idempotency, and SSE lifecycle management.

## Component boundaries

- `modules/llm/config.py`: validated provider, model, capability, and pricing settings.
- `modules/llm/schemas.py`: normalized text-generation requests, results, token usage, and stream events.
- `modules/llm/protocols.py`: provider adapter contract.
- `modules/llm/adapters/openai_compatible.py`: OpenAI Chat Completions-compatible adapter.
- `modules/llm/adapters/anthropic.py`: native Anthropic Messages API adapter.
- `modules/llm/registry.py`: app-lifespan ownership of provider SDK clients.
- `modules/llm/catalog.py`: immutable, sanitized model/provider metadata catalog.
- `modules/llm/service.py`: provider-independent `generate()` and `stream()` facade for the future chat module.
- `api/v1/endpoints/llm.py`: public, non-secret provider and model catalog endpoints.

The chat module must depend on `LLMService`, not on provider SDK classes. Provider SDK objects must never cross the adapter boundary.

## Provider configuration

Provider credentials are supplied through server-side environment configuration (`LLM_PROVIDERS`). The supported discriminators are:

- `openai_compatible`: requires a base URL and supports the OpenAI Chat Completions shape. Configure `max_output_tokens_parameter` as `max_tokens` for providers expecting the common compatibility field, or `max_completion_tokens` for providers that use the newer OpenAI field.
- `anthropic`: uses the native Anthropic Messages API. `base_url` is optional and is intended for operator-controlled compatible gateways.

Provider settings use `SecretStr`. Public catalog responses never serialize provider configuration or credentials. SDK retries are disabled (`max_retries=0`) because retries must be controlled by the application after it knows whether output has already been delivered to a user.

Do not accept end-user-supplied provider URLs or credentials in this milestone. Provider endpoints are trusted operator configuration. If custom gateways are exposed to tenant admins later, add endpoint allowlisting, DNS/IP validation, egress controls, secret vaulting, and credential ownership rules before shipping that feature.

## Model catalog

`LLM_MODELS` defines application-owned stable model IDs and their upstream provider model IDs. It also defines context/output limits, upstream capabilities, and optional versioned pricing.

Capabilities currently describe the upstream model metadata supplied by the operator; they do not imply that every feature (tools, vision, structured output) is already implemented by the Ask AI chat product. The initial normalized request contract is text-only.

Pricing records contain:

- a unique version identifier per model;
- a timezone-aware `effective_from` timestamp;
- a three-letter currency code;
- input, output, and cached-input prices per million tokens.

The catalog returns only the latest pricing record whose `effective_from` is not in the future. An absent price is `null`/unknown. The system must never infer, copy, or hardcode prices from model names. The pricing version is returned so later usage accounting can persist the exact rate applied.

## Normalized request contract

`GenerationRequest` contains an internal `model_id`, ordered messages (`system`, `developer`, `user`, `assistant`), optional maximum output tokens, temperature, top-p, and stop sequences. Model resolution happens in `LLMService`; provider adapters receive the validated model definition and request.

`GenerationResult` contains text, normalized finish reason, provider/model IDs, provider request ID, and token usage. Token counts are nullable. `total_tokens` is calculated only when both input and output values are known, otherwise it remains unknown.

`GenerationEvent` has three internal event types:

- `text_delta`: incremental generated text;
- `usage`: provider-reported token counts when available;
- `completed`: terminal metadata and finish reason.

These are internal events, not the public SSE wire protocol. Milestone 5 owns the API event names, durable generation state machine, and client disconnect behavior.

## Provider-specific normalization

### OpenAI-compatible

The adapter uses the asynchronous `chat.completions` API because it is the common denominator across OpenAI-compatible gateways. It maps normalized messages and supported generation parameters, reads prompt/completion usage when supplied, and optionally requests final streaming usage using `stream_options.include_usage`. Gateways that do not support that extension must set `include_usage_in_stream=false`.

### Anthropic

The adapter uses the native Messages API. `system` and `developer` messages are mapped to the top-level system field, and consecutive same-role user/assistant messages are joined because Anthropic expects alternating conversational roles. System/developer instructions after conversational messages are rejected rather than silently reordered. Anthropic's mutually exclusive `temperature` and `top_p` parameters are validated.

Both adapters handle unknown stream event types gracefully. Anthropic stream error events are translated into normalized provider errors without returning raw upstream error messages. A stream is not reported as completed unless the provider emits its protocol terminal marker (OpenAI-compatible finish reason or Anthropic \`message_stop\`); an upstream EOF without the terminal marker is treated as an invalid provider response so partial output cannot be mistaken for a completed answer.

## Error taxonomy

Adapters raise provider-neutral errors:

- `provider_authentication_failed`: invalid upstream credential;
- `provider_rate_limited`: throttled, optionally with parsed `Retry-After`;
- `provider_timeout`: upstream timeout;
- `provider_unavailable`: transport or upstream 5xx/overload;
- `provider_rejected_request`: upstream validation/model request rejected;
- `invalid_provider_response`: malformed or unusable upstream response.

Errors intentionally omit raw messages, response bodies, headers, and credentials. The future chat API must map these codes to stable client-facing errors and retry only transient errors when the generation has not emitted visible output.

## Lifecycle

Provider SDK clients are created when FastAPI lifespan starts and closed during shutdown. The registry is app-scoped and is not shared across worker processes. Each worker creates its own provider clients. Provider configuration is immutable for a process lifetime; rotating a provider secret requires a controlled restart/redeployment until a dedicated secret refresh mechanism is designed.

## API

- `GET /api/v1/providers`: enabled providers, names, adapter kinds, and configured model counts; no keys or URLs.
- `GET /api/v1/models`: enabled models, provider names, upstream model IDs, context/output limits, upstream capability metadata, and current effective pricing. Optional filter: `provider_id`.

A missing or disabled provider/model is omitted from public catalog results. Model lookup in `LLMService` returns a stable 404 application error when no enabled catalog entry exists.

## Security and operations

- Credentials remain in server configuration and are wrapped as `SecretStr`.
- Never log prompts, completions, API keys, raw provider errors, or authorization headers by default.
- Do not expose a generic proxy endpoint that allows arbitrary base URLs.
- SDK retry behavior is disabled to avoid hidden duplicate cost or duplicate user-visible output.
- Set finite connection/request timeouts per provider.
- Keep provider calls outside database transactions.
- Do not automatically fail over after user-visible output starts.
- Use real provider model limits and prices from the operator's account/provider documentation.
