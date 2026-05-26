# QA Platform Frontend

React + TypeScript + Vite SPA for the QA Platform.

## Stack

- React 19
- Vite 8
- TypeScript 6
- TailwindCSS 4
- React Router 7
- TanStack Query
- Radix UI
- Recharts
- i18next

## Requirements

- Node.js 22.13+ or 20.19+

## Local Development

```bash
cd frontend
npm ci
npm run dev
```

The dev server defaults to `http://localhost:5173`.

Backend API calls are made under `/api/v1`; run the backend separately during local development.

## Scripts

```bash
npm run dev      # start Vite dev server
npm run build    # TypeScript project build + Vite production build
npm run lint     # ESLint
npm run preview  # preview production build
```

## API Contract Notes

Use backend schemas and OpenAPI as the source of truth. In particular:

- Auth routes live under `/api/v1/auth/*`.
- Refresh token is stored in an HttpOnly cookie by the backend, not in localStorage.
- SSE logs/events use `/api/v1/runs/{run_id}/logs?ticket=...` and `/api/v1/runs/{run_id}/events?ticket=...`.
- Artifact download returns JSON with `download_url` and `expires_in`; it is not an HTTP redirect.
- `src/types/api.ts` currently mixes backend-shaped DTOs with UI-normalized view models in a few places. Notable gaps include Run view fields, Environment `variables` vs backend `env_vars` / resource-limit fields, and older nested Pipeline selector / retry shapes; the current environment editor and pipeline modal payloads follow those older shapes too. Some hooks also need API realignment: project search currently sends `search` while the backend expects `q`, pipeline hooks still use non-existent `/pipelines/{id}` routes, notification rule list currently expects a bare array while the backend returns `PaginatedResponse`, and the SSE fallback should not poll the SSE URL as JSON. Run triggering also still carries ignored legacy `env_overrides` / `params`, and run normalization checks `summary.errors` even though backend summaries use singular `error`. Do not treat that file or nearby hooks as the raw backend contract until `T-FRONTEND-API` splits or realigns them.
- Backend Run statuses are `queued/preparing/running/collecting/done/failed/cancelled/timeout`; the current UI maps `done` to `passed` or `failed` from summary counts, and maps `timeout` to `timed_out`.
- Backend TestResult statuses are `passed/failed/error/skipped/xfail`; `src/types/api.ts` currently omits `xfail`, which is part of the `T-FRONTEND-API` realignment debt.

`FRONTEND_PROMPT.md` is a historical implementation prompt and is not the current API contract.

## Known TypeScript Debt

The current `main` branch may contain historical TypeScript errors outside new feature work. For task acceptance, follow the repository task guidance: changed frontend files must be TS-clean and must not introduce new TS errors. Clean the historical debt in a dedicated frontend TS task.
