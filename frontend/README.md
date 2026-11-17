# Ask AI Frontend

React + TypeScript + Vite chat workspace for the Ask AI API.

## Features

- Email/password authentication and conditional Google/Apple OIDC entry points.
- In-memory access-token handling with HttpOnly refresh-cookie restoration.
- Conversation search, pagination, rename, and delete.
- Model selection from the backend catalog.
- POST-based SSE chat with streaming deltas, cancellation, and per-generation usage metadata.
- Safe Markdown rendering (no raw HTML), code copy controls, responsive navigation, and accessible loading/error states.

## Development

```powershell
Copy-Item .env.example .env
npm install
npm test
npm run typecheck
npm run build
npm run dev
```

Node.js 22.12+ is required for the built-in TypeScript stripping used by the SSE parser tests. The default Vite configuration proxies `/api` to `http://127.0.0.1:8000`; set `VITE_API_BASE_URL` in `.env` only when using a separate API origin.

See [Milestone 6 implementation notes](../docs/development/MILESTONE_6.md) for API contracts, auth/cookie behavior, SSE protocol, known scope boundaries, and pre-release verification.
