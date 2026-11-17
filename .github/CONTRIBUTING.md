# Contributing

## Workflow

- Branch from `main` using `feat/`, `fix/`, `docs/`, `refactor/`, or `test/` prefixes.
- Keep pull requests focused on one issue or cohesive change.
- Link the issue and explain user impact, implementation approach, and risks.
- Never commit secrets, local databases, generated credentials, or real user content.

## Quality gates

For backend changes, run from `backend/`:

```bash
uv run ruff check .
uv run mypy src
uv run pytest
```

Add unit tests for business rules, integration tests for persistence and provider boundaries, and contract tests for each provider adapter. Streaming changes must cover disconnects, cancellation, partial output, provider errors, and final usage handling.


For frontend changes, run from `frontend/`:

```bash
npm install
npm test
npm run typecheck
npm run build
```

The browser client must not persist access tokens in browser storage or expose provider API keys. Streaming changes must test UTF-8 chunk boundaries, CRLF split boundaries, malformed events, cancellation, and missing terminal events.

## Review expectations

Reviewers must check authorization, data isolation, transaction boundaries, resource cleanup, timeout behavior, logging/privacy, migrations, and backwards compatibility. Do not merge with failing required checks.
