# Frontend Architecture

How the Next.js (App Router) frontend is structured: route groups, the
authenticated app shell, and how new pages are added. Auth mechanics (token
storage, interceptors, login) live in [`authentication.md`](authentication.md);
this doc is about **structure and the shell**.

Relevant ADRs: **ADR-091** (protected route group + shell), **ADR-092** (shell
composition + role-aware nav); plus ADR-086 (frontend protection is UX, not
security).

## Route structure

```
app/
  layout.tsx              # root: <Providers> (incl. AuthProvider gate)
  page.tsx                # public home (system status, "Sign in")
  (auth)/
    login/page.tsx        # PUBLIC — outside the protected group, no shell
  (protected)/
    layout.tsx            # auth check + app shell (sidebar/header) around children
    dashboard/page.tsx    # authenticated landing
    loan-files/page.tsx   # stub (Epic 4 builds the real page)
    admin/page.tsx        # admin placeholder (nav gated to ADMIN)
```

Route groups (`(auth)`, `(protected)`) organize files **without** affecting URLs —
`/login`, `/dashboard`, `/loan-files`, `/admin` are the actual paths.

## The protected route group + shell

Everything authenticated lives under `app/(protected)/`, whose **layout** does two
things for every page in the group:

1. **Structural protection.** It calls `useRequireAuth()` (the LP-25 hook): if the
   user isn't authenticated it redirects to `/login`. This is done **once, in the
   layout** — pages don't re-implement protection. It is **UX, not security**; the
   backend verifies every request (ADR-086).
2. **The app shell.** It renders `<AppShell>` — sidebar + header — around
   `{children}`, so every authenticated page gets the same chrome for free.

**Coordination with silent refresh (no flicker).** The access token is in memory
only, so a page reload starts unauthenticated until the LP-25 silent refresh
resolves. The layout watches the store's `isInitializing`: while the initial check
is in flight it shows a `FullScreenLoader` and does **not** redirect; only once it
resolves as *unauthenticated* does it redirect to `/login`. So a refresh on a
protected page shows a brief loader and stays put — it never flashes the login
screen or bounces an authenticated user.

The `/login` page sits in `(auth)`, **outside** the protected group, so it renders
with no shell and is reachable while logged out.

## The shell anatomy

`components/layout/`:

- **`app-shell.tsx`** — composes the frame: a fixed `Sidebar` + a `Header` over a
  scrollable `<main>` content container. Landmarks: `<aside>`/`<nav>` (sidebar),
  `<header>`, `<main>`.
- **`sidebar.tsx`** — the persistent left rail (desktop): the `mortgageboss·ai`
  wordmark + the role-filtered nav with an active-route indicator (`usePathname` +
  `isActivePath`). Hidden below `md`.
- **`header.tsx`** — the top bar: a **mobile** nav menu (a dropdown shown below
  `md`, where the sidebar is hidden), the current section title, and the user menu.
- **`user-menu.tsx`** — the account dropdown (shadcn `dropdown-menu`): the user's
  initials + name, with **Log out** (the LP-25 flow: clear the in-memory token, hit
  the backend to clear the refresh cookie, redirect to `/login`). Profile/Settings
  are disabled placeholders.

## Navigation config & role-aware nav

`lib/navigation.ts` is the single source of truth (`NAV_ITEMS`) used by both the
desktop sidebar and the mobile menu. Each item may set `requiredRole`;
`visibleNavItems(role)` filters the list. Today:

| Item | Path | Visible to |
| --- | --- | --- |
| Dashboard | `/dashboard` | all |
| Loan Files | `/loan-files` | all |
| Administration | `/admin` | ADMIN only |

Role gating here is **UX only** — it hides chrome a user can't use. The backend is
the real authorization boundary (LP-24 `require_role`); the admin page itself also
reflects the user's role rather than assuming it.

## Adding a new authenticated page

1. Create `app/(protected)/<route>/page.tsx`. It automatically inherits protection
   **and** the shell from the group layout — no per-page auth code.
2. Add a `NAV_ITEMS` entry in `lib/navigation.ts` (with `requiredRole` if gated).

That's it: drop a file in the group, add a nav line. This is the frontend analog of
the backend's "auth as a declared dependency" — protection and chrome are applied
structurally, in one place.

## The file workspace (LP-33)

A single loan file is a **tabbed workspace** built as a Next.js **nested layout**
under the `(protected)` group:

```
app/(protected)/loan-files/[id]/
  layout.tsx        # fetches the file once → persistent header + tab nav; renders {children}
  page.tsx          # Overview (default; placeholder until LP-34)
  documents/        verification/   communication/   conditions/   lender-package/
```

- **`[id]` is the file's `display_id`** (`/loan-files/LF-XXXX`) — human-friendly, and
  the API accepts UUID or `display_id`. The dashboard rows (LP-31) and the intake redirect
  (LP-32) both navigate by `display_id`.
- **`layout.tsx`** (client) fetches the file via `useLoanFile(id)` and renders the
  **persistent header** (borrower name with graceful fallback, `display_id`, status badge,
  key dates) + **tab navigation**, with `{children}` (the active tab page) below. The
  header/tabs stay put while you switch tabs; only the content changes.
- **Tabs are route-based links**, not ARIA tabs/tabpanels (each tab is a sub-route); the
  active link carries `aria-current="page"`, derived from `usePathname` via
  `activeTabKey` (`lib/loan-files/tabs.ts`).
- **All six tabs show now**; not-yet-built ones render clearly-labeled "coming in Phase X"
  placeholders (ADR-109) — honest about the file's lifecycle without faking features.
- **States:** skeleton header while loading; a `404` (missing *or* out-of-company —
  tenant-safe, both surface the same) shows "File not found" with a way back; other errors
  show a clean message.

**Adding real tab content** (LP-34+): replace a tab's placeholder `page.tsx`; it fetches
the same `["loan-file", id]` query (deduped by React Query) and renders into the existing
shell — no header/tab rework. The status→badge mapping is the shared
`components/status-badge.tsx` over `STATUS_META` (one mapping, reused everywhere).

## The Documents tab (LP-43)

The Documents tab (`[id]/documents/page.tsx`, replacing the LP-33 placeholder) is the
operable document workspace — where the processor uploads documents and watches the
pipeline read them.

- **Upload** — a drag-and-drop (+ click-to-browse) zone (`react-dropzone`,
  `components/file/documents/document-dropzone.tsx`) accepting PDF/JPG/PNG. It validates
  type + size client-side for fast feedback (`validateUploadFile`), but the **server
  (LP-36) is authoritative** — its `413`/`415` are surfaced as toasts too. Multiple files
  at once. On success the mutation invalidates the documents query, so the new `pending`
  documents appear and polling resumes.
- **Live status polling** — `useLoanFileDocuments` (`lib/api/documents.ts`) uses a
  **function `refetchInterval`**: ~2.5s while *any* document is non-terminal
  (`hasInProgressDocuments`), `false` once all are terminal
  (`completed`/`needs_review`/`failed`). So the list updates in near-real-time during
  processing and **stops** when settled — `Document.status` is the source of truth. (ADR-134.)
- **Grouped by category** — `groupDocumentsByCategory` buckets documents under the eight
  `DocumentCategory` labels (in order) plus a "Processing / uncategorized" group for
  not-yet-classified docs. Each row shows filename, classified type, size/date, and a live
  status badge (`DocumentStatusBadge` — a spinner while processing; green completed, amber
  **Needs review** (honest AI-uncertainty signal), red failed). Type **correction** is
  LP-44. (ADR-135.)
- **Detail drawer** — a shadcn `sheet` (`document-drawer.tsx`) fetches detail on open
  (`useDocumentDetail`, enabled only while open): metadata + the extraction rendered as
  labelled key/values (`extractionFields`; "No extraction — classified only" for
  non-pay-stub types) + an authed **download** (blob via `/documents/{id}/download`) +
  soft-delete.
- **Dev-only text-layer button** — non-production only (`process.env.NODE_ENV !==
  "production"`, statically eliminated from a prod build), calling the LP-40 dev endpoint
  to show the deterministic text layer for comparison. Absent in production (and the
  endpoint 404s there anyway). (ADR-136.)
- **No leaks** — `storage_path` / raw `ssn` / `inbox_token` never appear (the endpoints
  don't expose them); the dev text-layer text shows only via the gated dev button.

The presentation/logic helpers live in `lib/loan-files/documents.ts` (status map, grouping,
terminal rule, validation, extraction display) — unit-tested in `documents.test.ts`.

## Error handling & feedback (LP-46)

Failures are turned into clear, recoverable states (ADR-155) — no white screens,
no infinite spinners, no console-only errors.

- **Normalization** — `lib/errors/api-error.ts` `normalizeError()` maps any throw
  (axios error, network failure, stray `Error`) into one
  `{ kind, status, message, details }`, reading the backend envelope (LP-46) with
  a legacy `detail` fallback and a safe generic default. Components display
  `message` and branch on `kind`; mutation toasts use `getErrorMessage()`.
- **Session expiry** — the axios layer (`lib/api/client.ts`) refreshes once on a
  `401`; when the session is truly gone it clears auth and redirects to
  `/login?next=…&reason=session_expired`, and the login form shows a "your
  session expired" notice (a query param survives the navigation a toast would
  not).
- **Error boundary** — `components/error-boundary.tsx` (a class `ErrorBoundary` +
  `DefaultErrorFallback`) is mounted top-level in `Providers` and around the
  app-shell content. A render crash shows a friendly "Something went wrong" +
  Try again (remounts the subtree; clears the query cache on the top-level
  reset) instead of a blank page. The raw error is console-only, never rendered.
- **Inline error states + retry** — `components/ui/error-state.tsx` (`ErrorState`
  panel + compact `InlineErrorState`), each with a Retry that re-runs the failed
  query. Used by the documents list, the drawer's extraction, and the overview
  sections; the file-level 404 keeps the "doesn't exist or no access" state
  (`FileError`).

Component tests run under jsdom + React Testing Library (opt-in per file via a
`// @vitest-environment jsdom` docblock; `@vitejs/plugin-react` transforms the
`.tsx` test files).

## What's next

- **LP-47** — loading states & skeletons (the sibling of this ticket's error
  states).
