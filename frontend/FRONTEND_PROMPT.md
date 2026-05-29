# QA Platform Frontend Implementation Prompt

> Historical prompt: this file captured the initial frontend implementation brief. It is not the current API contract and must not be used as implementation input without checking current source. Prefer backend OpenAPI/schemas, `frontend/README.md`, and `docs/doc-conflict-audit.md` when maintaining the app.

## Project Overview

Build a complete frontend SPA for a QA Automation Execution Platform. The backend API is already implemented (FastAPI). The original brief referenced a Linear-like dark developer tool; current visual decisions are maintained in `../DESIGN.md`.

## Tech Stack

- **Framework**: React 19 + TypeScript
- **Build**: Vite 8
- **Styling**: TailwindCSS 4 + Radix UI primitives + local `components/ui` wrappers
- **Routing**: React Router v7
- **State**: TanStack Query (React Query) for server state
- **Forms**: React Hook Form + Zod validation
- **Icons**: Lucide React
- **Font**: Inter (display/body) + JetBrains Mono (code/logs)
- **Charts**: Recharts (for test result trends)

## Design System — Historical Dark Theme

### Color Tokens (Tailwind CSS custom colors)

```css
:root {
  --canvas: #010102;
  --surface-1: #0f1011;
  --surface-2: #141516;
  --surface-3: #18191a;
  --surface-4: #191a1b;
  --hairline: #23252a;
  --hairline-strong: #34343a;
  --ink: #f7f8f8;
  --ink-muted: #d0d6e0;
  --ink-subtle: #8a8f98;
  --ink-tertiary: #62666d;
  --primary: #5e6ad2;
  --primary-hover: #828fff;
  --primary-focus: #5e69d1;
  
  /* Semantic status colors for QA */
  --status-passed: #27a644;
  --status-failed: #e5484d;
  --status-running: #f5a623;
  --status-queued: #8a8f98;
  --status-cancelled: #62666d;
  --status-skipped: #62666d;
}
```

### Typography

- Display headings: Inter, weight 600, letter-spacing 0
- Body: Inter, weight 400, 16px, line-height 1.5
- Small/Caption: Inter, weight 400, 12-14px
- Code/Logs: JetBrains Mono, weight 400, 13px
- Buttons: Inter, weight 500, 14px

### Spacing

- Base unit: 4px
- Component padding: 8px 14px (buttons), 8px 12px (inputs), 24px (cards)
- Section gaps: 96px between major sections
- Card gaps: 24px

### Border Radius

- Buttons/Inputs: 8px
- Cards/tool panels: 8px for new work; older `rounded-xl` instances may be retired opportunistically
- Screenshot panels: 16px
- Pills/Badges: 9999px

### Elevation

No drop shadows. Use surface ladder + 1px hairline borders for depth:
- Level 0: canvas background
- Level 1: surface-1 + 1px hairline border
- Level 2: surface-2 + 1px hairline-strong border
- Focus: 2px primary-focus outline at 50% opacity

### Key Design Principles

- Dark canvas (#010102) is the anchor — never use pure #000000
- Primary lavender (#5e6ad2) is SCARCE — only for: primary CTA, focus rings, active nav items, links
- Status colors (green/red/yellow) are the main chromatic variety in a QA tool
- No atmospheric gradients, no spotlight cards
- Dense, information-rich layouts — this is a developer tool
- Product data (runs, test results) is the protagonist

## Backend API Reference

Base URL: `/api/v1`

> Historical examples below were part of the original prompt. Current code and `frontend/README.md` are authoritative when an endpoint differs.

### Authentication
- `POST /auth/login` → Login and issue access token; refresh token is stored in an HttpOnly cookie
- `POST /auth/refresh` → Refresh access token using cookie
- `POST /auth/tokens` → Create API token
- `DELETE /auth/tokens/{token_id}` → Revoke API token
- `GET /auth/tokens?page=1&per_page=20` → Paginated API token list

### Projects
- `GET /projects?page=1&per_page=20&q=&status=active` → Paginated list
- `POST /projects` → Create project
- `GET /projects/{id}` → Project detail
- `PUT /projects/{id}` → Update project
- `DELETE /projects/{id}` → Delete project

### Environments (per project)
- `GET /projects/{project_id}/environments` → List
- `POST /projects/{project_id}/environments` → Create
- `GET /projects/{project_id}/environments/{id}` → Detail
- `PUT /projects/{project_id}/environments/{id}` → Update
- `DELETE /projects/{project_id}/environments/{id}` → Delete

### Pipelines (per project)
- `GET /projects/{project_id}/pipelines` → List
- `POST /projects/{project_id}/pipelines` → Create
- `GET /projects/{project_id}/pipelines/{id}` → Detail
- `PUT /projects/{project_id}/pipelines/{id}` → Update
- `DELETE /projects/{project_id}/pipelines/{id}` → Delete

### Runs
- `POST /runs` → Trigger run `{ pipeline_id, git_ref?, priority? }`
- `GET /runs?status=&page=1&per_page=20&sort=-created_at` → List runs
- `GET /runs/{id}` → Run detail
- `POST /runs/{id}/cancel` → Cancel run `{ reason? }`
- `GET /runs/{id}/results?page=1&per_page=50` → Test results for a run
- `GET /runs/{id}/artifacts` → Artifacts for a run

### Artifacts
- `GET /artifacts/{id}/download` → Download artifact (returns `{ download_url, expires_in }`)

### SSE (Server-Sent Events)
- `POST /auth/sse-ticket` → Create one-time SSE ticket
- `GET /runs/{id}/logs?ticket=...` → Real-time log stream
- `GET /runs/{id}/events?ticket=...` → Run status change events

### Health (outside `/api/v1`)
- `GET /health` → `{ status: "ok" }`
- `GET /ready` → `{ status: "ok"|"degraded", checks: { db, redis } }`

## Data Models

### Project
```typescript
interface Project {
  id: string;
  tenant_id: string;
  name: string;
  slug: string;
  description: string | null;
  git_url: string;
  git_auth_method: "none" | "token" | "ssh_key";
  credential_id: string | null;
  default_branch: string;
  root_path: string;
  shallow_clone: boolean;
  default_env_id: string | null;
  settings: Record<string, any>;
  status: "active" | "archived";
  created_by: string;
  created_at: string;
  updated_at: string;
}
```

### Pipeline
```typescript
interface Pipeline {
  id: string;
  project_id: string;
  name: string;
  stages: Array<{
    name: string;
    plugin: string;
    config: Record<string, unknown>;
    continue_on_error: boolean;
    phase: "prepare" | "execute" | "collect" | "notify" | null;
  }>;
  selector: {
    include_paths: string[];
    exclude_paths: string[];
    tags: string[];
    expression: string | null;
    regex: string | null;
    on_empty: "fail" | "skip" | "warn";
  };
  trigger_config: {
    type: string;
    dedup_window_seconds: number | null;
    source: Record<string, unknown>;
    conditions: Record<string, unknown>;
    target: Record<string, unknown>;
  };
  collectors: Array<{
    plugin: string;
    config: Record<string, unknown>;
    enabled: boolean;
  }>;
  timeout_seconds: number;
  retry_policy: {
    max_attempts: number;
    retry_on: string[];
    backoff_seconds: number;
    scope: "pipeline" | "stage";
  } | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}
```

### Run
```typescript
interface Run {
  id: string;
  tenant_id: string;
  project_id: string;
  pipeline_id: string;
  pipeline_name: string;
  environment_id: string;
  status: "queued" | "preparing" | "running" | "collecting" | "done" | "failed" | "cancelled" | "timeout";
  trigger_type: "manual" | "schedule" | "webhook" | "api";
  priority: number;
  triggered_by: string | null;
  git_ref: string;
  git_sha: string | null;
  attempt: number;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  summary: Record<string, unknown> | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}
```

### TestResult
```typescript
interface TestResult {
  id: string;
  run_id: string;
  suite: string;
  name: string;
  status: "passed" | "failed" | "skipped" | "error" | "xfail";
  duration_ms: number;
  error_message: string | null;
  stack_trace: string | null;
  tags: string[];
  metadata: Record<string, any>;
}
```

### Artifact
```typescript
interface Artifact {
  id: string;
  run_id: string;
  type: string;
  name: string;
  storage_path: string;
  size_bytes: number;
  mime_type: string;
  expires_at: string | null;
  created_at: string;
}
```

## Page Structure & Routes

```
/login                          → Login page
/                               → Dashboard (redirect to /projects)
/projects                       → Project list
/projects/:id                   → Project detail (tabs: Runs, Pipelines, Environments, Settings)
/runs                           → Run list
/runs/:id                       → Run detail (logs, test results, artifacts)
/settings                       → User settings (API tokens)
/admin/status                   → Admin status page
```

## Pages to Implement

### 1. Login Page (`/login`)
- Centered card on canvas background
- Username + password form
- "Sign in" primary button
- Error state for invalid credentials
- Redirect to /projects on success
- Store the access token in memory; the backend stores the refresh token in an HttpOnly cookie

### 2. Projects List (`/projects`)
- Top bar: page title "Projects" + "New Project" primary button
- Search input with debounce
- Grid of project cards (3-up desktop, 2-up tablet, 1-up mobile)
- Each card shows: name, description (truncated), git_url, status badge, last run status, created_at
- Click card → navigate to project detail
- Empty state when no projects

### 3. Project Detail (`/projects/:id`)
- Header: project name, description, git URL, status badge
- Tab navigation: Runs | Pipelines | Environments | Settings
- **Runs tab** (default):
  - Filter bar: status dropdown, date range
  - Table/list of runs with: status icon, pipeline name, git ref/branch label, duration, triggered_by, created_at
  - Click row → navigate to run detail
  - "Trigger Run" button → modal with pipeline selector + git ref input
- **Pipelines tab**:
  - List of pipelines with: name, stage count, enabled toggle, trigger/retry summary, last run status
  - "New Pipeline" button → creation form/modal
  - Edit/view pipeline details within the project tab unless a dedicated route is added
- **Environments tab**:
  - List of environments with: name, base image, resource limits, env var count (values masked)
  - CRUD operations
- **Settings tab**:
  - Project name, description, git settings edit form
  - Danger zone: archive/delete project

### 4. Run Detail (`/runs/:id`)
- Header: run status (large badge), pipeline name, git ref/branch label, git SHA, duration, triggered by
- Action bar: "Cancel" button (if running), "Re-run" button
- Three sections (tabs or stacked):
  - **Logs**: Real-time log viewer using SSE stream
    - Monospace font, dark background (surface-1)
    - Auto-scroll to bottom, pause on scroll up
    - ANSI color support
    - Search within logs
  - **Test Results**: 
    - Summary bar: total, passed (green), failed (red), skipped (gray)
    - Filterable table: suite, name, status, duration
    - Expandable rows showing error_message + stack_trace for failures
  - **Artifacts**:
    - List with: name, type, size, download button

### 5. User Settings (`/settings`)
- API Tokens management
  - List existing tokens from `data[]` plus `page/per_page/total` metadata (token_id, name, scopes, expires_at, last_used_at, is_revoked, created_at)
  - "Create Token" button → modal (name input, shows token ONCE)
  - Revoke button per token

## Component Library (Radix UI primitives + local wrappers)

### Core Components Needed
- `Button` (primary, secondary, ghost, destructive variants)
- `Input` + `Textarea`
- `Select` / `Dropdown`
- `Dialog` / `Modal`
- `Table` (sortable, with pagination)
- `Tabs`
- `Badge` / `StatusBadge` (with status colors)
- `Card`
- `Toast` / `Sonner` for notifications
- `Skeleton` loaders
- `EmptyState`
- `Sidebar` navigation (collapsible)
- `CommandPalette` (Cmd+K) — nice to have

### Custom Components
- `RunStatusBadge` — colored pill based on run status
- `TestStatusIcon` — green check / red X / gray skip
- `LogViewer` — SSE-powered real-time log display
- `DurationDisplay` — human-readable duration (e.g., "2m 34s")
- `RelativeTime` — "3 minutes ago" with tooltip showing absolute time
- `BranchBadge` — git branch display with icon

## Layout Structure

```
┌─────────────────────────────────────────────────┐
│  Top Nav (56px): Logo | Breadcrumb | User Menu  │
├────────┬────────────────────────────────────────┤
│        │                                        │
│  Side  │         Main Content Area              │
│  Nav   │                                        │
│ (220px)│                                        │
│        │                                        │
│ - Proj │                                        │
│ - Runs │                                        │
│ - Sett │                                        │
│        │                                        │
└────────┴────────────────────────────────────────┘
```

- Sidebar: collapsible, shows projects list + global nav
- Top nav: breadcrumb trail, user avatar dropdown (logout)
- Main content: scrollable, max-width 1280px centered

## Implementation Order

1. **Phase 1 — Scaffold**
   - Vite + React + TypeScript setup
   - TailwindCSS with current QA Platform tokens
   - local `components/ui` primitives and theme customization
   - React Router setup with layout
   - API client (axios/fetch wrapper with auth interceptor)
   - Auth context + protected routes

2. **Phase 2 — Core Pages**
   - Login page
   - Projects list
   - Project detail with tabs
   - Run detail with log viewer

3. **Phase 3 — CRUD & Interactions**
   - Create/edit project forms
   - Pipeline CRUD
   - Environment CRUD
   - Trigger run modal
   - Cancel run

4. **Phase 4 — Real-time & Polish**
   - SSE log streaming
   - Run status live updates
   - Toast notifications
   - Loading skeletons
   - Empty states
   - Responsive design
   - Keyboard shortcuts (Cmd+K)

## File Structure

```
frontend/
├── index.html
├── package.json
├── vite.config.ts
├── tsconfig.json
├── eslint.config.js
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── index.css
│   ├── App.css
│   ├── lib/
│   │   ├── api.ts              # Axios instance + interceptors
│   │   └── utils.ts            # cn(), formatDuration(), etc.
│   ├── hooks/
│   │   ├── use-auth.tsx
│   │   ├── use-analytics.ts
│   │   ├── use-notifications.ts
│   │   ├── use-page-title.ts
│   │   ├── use-projects.ts
│   │   ├── use-runs.ts
│   │   ├── use-pipelines.ts
│   │   └── use-sse.ts
│   ├── components/
│   │   ├── ui/                 # local UI primitives
│   │   ├── layout/
│   │   │   ├── app-layout.tsx
│   │   │   ├── command-palette.tsx
│   │   │   ├── error-boundary.tsx
│   │   │   └── protected-route.tsx
│   │   ├── run-status-badge.tsx
│   │   ├── branch-badge.tsx
│   │   ├── priority-badge.tsx
│   │   ├── language-switcher.tsx
│   │   ├── runs/
│   │   │   ├── log-viewer.tsx
│   │   │   ├── trigger-run-modal.tsx
│   │   │   └── artifact-preview.tsx
│   │   ├── test-results-table.tsx
│   │   ├── duration-display.tsx
│   │   └── relative-time.tsx
│   ├── pages/
│   │   ├── login.tsx
│   │   ├── projects/
│   │   │   ├── list.tsx
│   │   │   └── detail.tsx
│   │   ├── runs/
│   │   │   ├── list.tsx
│   │   │   └── detail.tsx
│   │   ├── admin/
│   │   │   └── status.tsx
│   │   ├── settings.tsx
│   │   └── not-found.tsx
│   └── types/
│       └── api.ts              # TypeScript interfaces
```

## Key UX Details

- **Optimistic updates**: When triggering a run, immediately show it in "queued" state
- **SSE recovery**: reconnect with a fresh SSE ticket; a true polling fallback needs a normal JSON endpoint and should not poll the SSE URL directly
- **Error boundaries**: Graceful error states per section, not full-page crashes
- **URL state**: Filters (status, page) reflected in URL query params
- **Keyboard navigation**: Tab through tables, Enter to open, Escape to close modals
- **Responsive**: Sidebar collapses to hamburger on mobile
- **Loading states**: Skeleton loaders matching the shape of content

## Authentication Flow

1. User submits username + password to `POST /api/v1/auth/login`
2. Store `access_token` in memory (React state/context)
3. Refresh token is stored by the backend as an HttpOnly cookie
4. Attach `Authorization: Bearer {access_token}` to all API requests
5. On 401 response, attempt token refresh via `POST /api/v1/auth/refresh`
6. If refresh fails, redirect to /login
7. On logout, clear in-memory auth state and redirect to /login
