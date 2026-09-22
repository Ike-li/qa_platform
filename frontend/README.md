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
- `src/types/api.ts` keeps backend DTOs separate from UI view models for Environment and Run. Pipeline payloads follow the current backend schema (`stages[].plugin/config`, `selector.include_paths`, `trigger_config.type`, `collectors[].plugin/config`, `retry_policy.max_attempts`), project search maps UI `search` to backend `q`, notification rules unwrap `PaginatedResponse`, notification condition payloads support all/any grouping plus `consecutive_failures`, notification channel types cover the current first-class channels (`email`, `webhook`, `dingtalk`, `wecom`) with one entry per type in a rule and Slack handled through generic Webhook, run trigger payloads use the current `pipeline_id` / `git_ref` / `git_sha` / `environment_id` / `priority` contract, and SSE reconnect sends the last event cursor with the new ticket. Keep backend schemas / OpenAPI as the source of truth when adding new API types.
- Backend Run statuses are `queued/preparing/running/collecting/done/failed/cancelled/timeout`; the current UI maps `done` to `passed` or `failed` from summary counts, and maps `timeout` to `timed_out`.
- Backend TestResult statuses are `passed/failed/error/skipped/xfail`; `src/types/api.ts` includes the full set.


## TypeScript Gate

`npm run build` runs the TypeScript project build and Vite production build. Frontend changes are expected to keep both `npm run build` and `npm run lint -- --max-warnings=0` clean.
