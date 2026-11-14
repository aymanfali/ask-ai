# Frontend

The frontend is a planned milestone, not yet implemented. Target the following stable stack, verified against current package registries on 2026-11-14:

- React 19.3.1
- TypeScript 7.0.2
- Vite 8.3.8
- React Router 7.18.5 (retain the v7 API line for continuity with the existing React Router direction)

Use a typed API client and the Fetch streaming reader for POST-based SSE requests. Provider credentials must never be stored in or sent from the browser.

Initial screens: authentication, chat workspace, conversation history, model selector, usage dashboard, and account settings.
