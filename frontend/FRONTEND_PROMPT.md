# QA Platform Frontend Implementation Prompt

## Project Overview

Build a complete frontend SPA for a QA Automation Execution Platform. The backend API is already implemented (FastAPI). The frontend should be a modern, dark-themed developer tool with Linear's design aesthetic.

## Tech Stack

- **Framework**: React 19 + TypeScript
- **Build**: Vite 6
- **Styling**: TailwindCSS 4 + shadcn/ui
- **Routing**: React Router v7
- **State**: TanStack Query (React Query) for server state
- **Forms**: React Hook Form + Zod validation
- **Icons**: Lucide React
- **Font**: Inter (display/body) + JetBrains Mono (code/logs)
- **Charts**: Recharts (for test result trends)

## Design System — Linear Style (Dark Theme)

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

- Display headings: Inter, weight 600, negative letter-spacing (-1px to -3px)
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
- Cards: 12px
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

### Authentication
- `POST /login` → `{ access_token, refresh_token, token_type, expires_in }`
- `POST /refresh` → `{ access_token, refresh_token }`
- `POST /tokens` → Create API token
- `DELETE /tokens/{token_id}` → Revoke API token
- `GET /tokens` → List API tokens

### Projects
- `GET /projects?page=1&per_page=20&search=&status=active` → Paginated list
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
- `POST /runs` → Trigger run `{ pipeline_id, branch?, env_overrides?, params? }`
- `GET /runs?status=&page=1&per_page=20&sort=-created_at` → List runs
- `GET /runs/{id}` → Run detail
- `POST /runs/{id}/cancel` → Cancel run `{ reason? }`
- `GET /runs/{id}/results?page=1&per_page=50` → Test results for a run
- `GET /runs/{id}/artifacts` → Artifacts for a run

### Artifacts
- `GET /artifacts/{id}/download` → Download artifact (presigned URL redirect)

### SSE (Server-Sent Events)
- `GET /runs/{id}/logs/stream` → Real-time log stream
- `GET /runs/{id}/events` → Run status change events

### Health
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
  stages: Stage[];
  selector: { framework: string; pattern: string; tags?: string[] };
  trigger_config: { on_push: boolean; on_schedule?: string; branches?: string[] };
  timeout_seconds: number;
  retry_policy: { max_retries: number; backoff: string } | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}
```

### Run
```typescript
interface Run {
  id: string;
  project_id: string;
  pipeline_id: string;
  pipeline_name: string;
  status: "queued" | "preparing" | "running" | "collecting" | "passed" | "failed" | "cancelled" | "timed_out";
  branch: string;
  git_sha: string | null;
  triggered_by: string;
  trigger_type: "manual" | "schedule" | "webhook";
  env_overrides: Record<string, string>;
  params: Record<string, any>;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  total_tests: number;
  passed_tests: number;
  failed_tests: number;
  skipped_tests: number;
  error_message: string | null;
  worker_id: string | null;
  cancel_requested_at: string | null;
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
  status: "passed" | "failed" | "skipped" | "error";
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
/projects/:id/pipelines/:pid    → Pipeline detail + run history
/runs/:id                       → Run detail (logs, test results, artifacts)
/settings                       → User settings (API tokens)
```

## Pages to Implement

### 1. Login Page (`/login`)
- Centered card on canvas background
- Email + password form
- "Sign in" primary button
- Error state for invalid credentials
- Redirect to /projects on success
- Store tokens in memory (access) + httpOnly cookie or localStorage (refresh)

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
  - Table/list of runs with: status icon, pipeline name, branch, duration, triggered_by, created_at
  - Click row → navigate to run detail
  - "Trigger Run" button → modal with pipeline selector + branch input
- **Pipelines tab**:
  - List of pipelines with: name, framework, enabled toggle, last run status
  - "New Pipeline" button → creation form/modal
  - Click → pipeline detail
- **Environments tab**:
  - List of environments with key-value pairs (values masked)
  - CRUD operations
- **Settings tab**:
  - Project name, description, git settings edit form
  - Danger zone: archive/delete project

### 4. Run Detail (`/runs/:id`)
- Header: run status (large badge), pipeline name, branch, git SHA, duration, triggered by
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
  - List existing tokens (name, created_at, last_used, prefix)
  - "Create Token" button → modal (name input, shows token ONCE)
  - Revoke button per token

## Component Library (shadcn/ui based, customized to Linear theme)

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
   - TailwindCSS with Linear color tokens
   - shadcn/ui installation + theme customization
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
├── tailwind.config.ts
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── globals.css
│   ├── lib/
│   │   ├── api.ts              # Axios instance + interceptors
│   │   ├── auth.ts             # Token management
│   │   └── utils.ts            # cn(), formatDuration(), etc.
│   ├── hooks/
│   │   ├── use-auth.ts
│   │   ├── use-projects.ts
│   │   ├── use-runs.ts
│   │   ├── use-pipelines.ts
│   │   └── use-sse.ts
│   ├── components/
│   │   ├── ui/                 # shadcn/ui components
│   │   ├── layout/
│   │   │   ├── app-layout.tsx
│   │   │   ├── sidebar.tsx
│   │   │   └── top-nav.tsx
│   │   ├── run-status-badge.tsx
│   │   ├── log-viewer.tsx
│   │   ├── test-results-table.tsx
│   │   ├── duration-display.tsx
│   │   └── relative-time.tsx
│   ├── pages/
│   │   ├── login.tsx
│   │   ├── projects/
│   │   │   ├── list.tsx
│   │   │   └── detail.tsx
│   │   ├── runs/
│   │   │   └── detail.tsx
│   │   └── settings.tsx
│   └── types/
│       └── api.ts              # TypeScript interfaces
```

## Key UX Details

- **Optimistic updates**: When triggering a run, immediately show it in "queued" state
- **Polling fallback**: If SSE disconnects, fall back to polling every 5s for active runs
- **Error boundaries**: Graceful error states per section, not full-page crashes
- **URL state**: Filters (status, page) reflected in URL query params
- **Keyboard navigation**: Tab through tables, Enter to open, Escape to close modals
- **Responsive**: Sidebar collapses to hamburger on mobile
- **Loading states**: Skeleton loaders matching the shape of content

## Authentication Flow

1. User submits email + password to `POST /api/v1/login`
2. Store `access_token` in memory (React state/context)
3. Store `refresh_token` in localStorage
4. Attach `Authorization: Bearer {access_token}` to all API requests
5. On 401 response, attempt token refresh via `POST /api/v1/refresh`
6. If refresh fails, redirect to /login
7. On logout, clear tokens and redirect to /login
