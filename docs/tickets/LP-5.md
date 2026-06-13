# LP-5 — Frontend Project Initialization

- **Ticket:** LP-5 — Frontend project initialization
- **Epic:** Epic 1 — Repo & Infrastructure Setup
- **Status:** Completed
- **Date:** 2026-06-10

## Summary

This ticket initialized the Next.js 15 frontend for MortgageBoss AI: a TypeScript
App Router application in strict mode, styled with Tailwind CSS and shadcn/ui, and
managed with pnpm. It establishes the design-token theme (color palette,
typography, radius) as CSS variables, wires up the supporting libraries (TanStack
Query, Zustand, react-hook-form + zod, axios, date-fns, sonner), configures Biome
for lint/format (replacing ESLint + Prettier), and ships a styled, intentional
placeholder home page. No real application logic, authentication, or backend
integration is included yet — those arrive in later tickets. Every verification
step — install, typecheck, lint, format, build, and dev-server boot — passed.

## Acceptance Criteria

| #  | Criterion                                                             | Status |
| -- | --------------------------------------------------------------------- | ------ |
| 1  | Next.js 15 in `frontend/` (TS, App Router, Tailwind, no ESLint)       | ✅ Done |
| 2  | `frontend/package.json` lists all required dependencies               | ✅ Done |
| 3  | `frontend/pnpm-lock.yaml` generated and committed                     | ✅ Done |
| 4  | pnpm is the package manager (yaml lockfile)                           | ✅ Done |
| 5  | TypeScript strict mode enabled in `tsconfig.json`                     | ✅ Done |
| 6  | Tailwind configured with custom theme (design tokens)                 | ✅ Done |
| 7  | shadcn/ui initialized with `components.json`                          | ✅ Done |
| 8  | Components installed: button, card, input, label, form, dialog, dropdown-menu, table, badge, separator, toast (sonner) | ✅ Done |
| 9  | Biome configured for lint + format (replaces ESLint + Prettier)       | ✅ Done |
| 10 | TanStack Query installed and provider configured                     | ✅ Done |
| 11 | Zustand installed for client state                                    | ✅ Done |
| 12 | react-hook-form + zod installed                                       | ✅ Done |
| 13 | axios installed and configured with a base instance                   | ✅ Done |
| 14 | lucide-react installed for icons                                      | ✅ Done |
| 15 | date-fns installed for date utilities                                 | ✅ Done |
| 16 | `app/page.tsx` shows a styled placeholder (not default Next welcome)  | ✅ Done |
| 17 | `app/layout.tsx` configures metadata, fonts, and providers            | ✅ Done |
| 18 | Directory structure under `frontend/` matches the V1 plan             | ✅ Done |
| 19 | `frontend/.env.example` documents required env vars                   | ✅ Done |
| 20 | `pnpm install` runs successfully                                      | ✅ Done |
| 21 | `pnpm dev` starts the dev server on port 3000                         | ✅ Done |
| 22 | Visiting http://localhost:3000 shows the styled placeholder           | ✅ Done |
| 23 | `pnpm lint` runs Biome and passes                                     | ✅ Done |
| 24 | `pnpm format` runs the Biome formatter and passes                     | ✅ Done |
| 25 | `pnpm typecheck` runs TypeScript and passes                           | ✅ Done |
| 26 | `pnpm build` produces a production build without errors               | ✅ Done |
| 27 | README.md updated with frontend setup instructions                    | ✅ Done |
| 28 | New ADRs added to decisions.md (013–019)                              | ✅ Done |
| 29 | `docs/tickets/LP-5.md` created                                        | ✅ Done |

## What Was Built

### Files created / replaced

- `frontend/tailwind.config.ts` — custom theme: shadcn CSS-variable colors,
  custom semantic colors (success/warning/info), system font stack, container,
  radius scale, accordion animations.
- `frontend/app/globals.css` — design tokens as HSL CSS variables under
  `@layer base`, plus base border/background/foreground application.
- `frontend/biome.json` — Biome 1.9.4 config (formatter, linter, organize
  imports, VCS-aware ignore).
- `frontend/components.json` — shadcn/ui configuration (RSC, aliases, baseColor).
- `frontend/tsconfig.json` — added `noUncheckedIndexedAccess` and
  `noImplicitOverride` on top of the Next.js strict defaults.
- `frontend/app/layout.tsx` — root layout with metadata (title template),
  system-font body, and the `Providers` wrapper.
- `frontend/app/page.tsx` — styled placeholder home page (branding, status
  badge, two CTAs, capability grid, footer).
- `frontend/lib/utils.ts` — `cn()` Tailwind class-merge helper.
- `frontend/lib/api/client.ts` — axios base instance (interceptors deferred to LP-25).
- `frontend/lib/query-client.ts` — TanStack Query `makeQueryClient()` factory.
- `frontend/lib/config.ts` — frontend config constants.
- `frontend/components/providers.tsx` — client provider (QueryClientProvider,
  devtools, sonner Toaster).
- `frontend/.env.example` — documents `NEXT_PUBLIC_API_URL`.
- `frontend/components/ui/*.tsx` — shadcn components (see list below).

The bundled Geist fonts and the default Next.js welcome page were removed in
favor of the system font stack (ADR-019) and the custom home page.

### Directory structure

```
frontend/
├── app/
│   ├── (auth)/.gitkeep        # unauthenticated routes (LP-26)
│   ├── (app)/.gitkeep         # authenticated app (LP-27)
│   ├── api/.gitkeep           # Next.js API routes
│   ├── layout.tsx
│   ├── page.tsx
│   └── globals.css
├── components/
│   ├── ui/                    # shadcn/ui components
│   └── providers.tsx
├── lib/
│   ├── api/client.ts
│   ├── utils.ts
│   ├── config.ts
│   └── query-client.ts
├── hooks/.gitkeep
├── public/
├── biome.json
├── components.json
├── tailwind.config.ts
├── tsconfig.json
├── next.config.ts
├── postcss.config.mjs
├── package.json
├── pnpm-lock.yaml
└── .env.example
```

## Dependencies Installed

| Category  | Package                              | Purpose                          |
| --------- | ------------------------------------ | -------------------------------- |
| Framework | next (^15, resolved 15.0.3)          | React framework with App Router  |
| Framework | react / react-dom (19.2.7)           | UI library                       |
| Language  | typescript (^5)                      | Type safety                      |
| Styling   | tailwindcss (^3.4)                    | Utility-first CSS                |
| Styling   | tailwindcss-animate (^1.0.7)          | Animation utilities              |
| Styling   | class-variance-authority (^0.7.1)     | Component variants               |
| Styling   | clsx (^2.1.1) + tailwind-merge (^3.6) | Conditional class names          |
| UI        | @radix-ui/* (via shadcn)             | Accessible primitives            |
| UI        | @radix-ui/react-icons (^1.3.2)        | Icon set                         |
| UI        | lucide-react (^1.17.0)                | Icon library                     |
| UI        | sonner (^2.0.7)                       | Toast notifications              |
| Data      | @tanstack/react-query (^5.101)        | Server state                     |
| Data      | @tanstack/react-query-devtools        | Query dev tools                  |
| State     | zustand (^5.0.14)                     | Client state                     |
| Forms     | react-hook-form (^7.78)               | Form handling                    |
| Forms     | @hookform/resolvers (^5.4)            | Validation integration           |
| Forms     | zod (^4.4.3)                          | Schema validation                |
| HTTP      | axios (^1.17)                         | API client                       |
| Utility   | date-fns (^4.4)                       | Date utilities                   |
| Dev       | @biomejs/biome (1.9.4)                | Linting and formatting           |
| Dev       | @types/node, @types/react(-dom)      | Type definitions                 |

## Design Decisions

- **Color palette** — primary blue (`#2563EB` family), cool-gray neutrals, and
  semantic success/warning/danger/info colors, exposed as HSL CSS variables so
  shadcn/ui themes correctly.
- **Typography** — system font stack (no web-font loading); see ADR-019.
- **Spacing** — Tailwind default (4px base unit).
- **Border radius** — `0.5rem` default (`--radius`), mapped to shadcn's
  lg/md/sm radius scale.
- See ADR-013 through ADR-019 in `decisions.md` for full rationale.

> Note: the ticket's neutral tokens (`#F9FAFB`, `#6B7280`, `#1F2937`) correspond
> to Tailwind's `gray` scale, so the home page uses `gray-*` utilities for an
> exact match while shadcn components use the CSS-variable theme.

## Components Installed via shadcn/ui

button, card, input, label, form, dialog, dropdown-menu, table, badge,
separator. Toast notifications are provided by **sonner** (wired into
`components/providers.tsx` via `<Toaster />`).

## Verification Performed

- `pnpm install` — succeeded.
- `pnpm typecheck` — passed (`tsc --noEmit`, exit 0).
- `pnpm lint` — passed (`biome check .`, 25 files, no issues).
- `pnpm format` — ran cleanly (Biome formatter).
- `pnpm build` — produced an optimized production build; `/` prerendered as
  static content (~119 kB First Load JS).
- `pnpm dev` — started on port 3000; `GET /` returned HTTP 200 and the rendered
  HTML contained the branding, both CTAs, and the "Phase 1 — Foundation" footer.

## Notes

- The placeholder home page is intentional but minimal; full UI arrives in later
  tickets.
- Auth providers and JWT handling are deferred to LP-25; the "Sign in" button is
  a placeholder link to `/login` (built in LP-26).
- Real API integration is deferred to LP-25; the axios client and TanStack Query
  client are configured but not yet used for live calls.
- Pinned versions of note: Next.js was scaffolded at 15.0.3 (Tailwind v3 era) so
  the v3-style `tailwind.config.ts` + `@tailwind` directives and shadcn work as
  specified; React was aligned to stable 19 with matching `@types/react`; Biome
  was pinned to 1.9.4 to match the v1 config schema.
- shadcn/ui components are installed as needed; more will be added in feature
  tickets.

## What's Next

LP-6 (Environment configuration) — connect the backend to `.env` files and set
up Pydantic Settings.

## References

- Next.js documentation: https://nextjs.org/docs
- shadcn/ui documentation: https://ui.shadcn.com
- TanStack Query documentation: https://tanstack.com/query
- Biome documentation: https://biomejs.dev
