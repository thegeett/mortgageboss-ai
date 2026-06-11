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

## What's next

- **Epic 4** — loan-file list and the file workspace, built as pages inside the
  `(protected)` group (replacing the `/loan-files` stub), calling the API through
  the authenticated client.
