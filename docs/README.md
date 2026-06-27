# Documentation

Project documentation for **mortgageboss-ai**, a loan processing assistant for
mortgage processors. Start here to find your way around.

## Documents

| Document                                             | What's in it                                              |
| ---------------------------------------------------- | --------------------------------------------------------- |
| [architecture.md](architecture.md)                   | System architecture overview, components, data flow, principles |
| [database.md](database.md)                           | Database & migrations: base/mixins, shared types, enums, Alembic workflow |
| [authentication.md](authentication.md)               | Password hashing (bcrypt) and JWT (PyJWT) — minimal claims, stateless tradeoff |
| [onboarding-and-tenancy.md](onboarding-and-tenancy.md) | Company/user onboarding model, tenancy, staged build plan, dev seed |
| [frontend-architecture.md](frontend-architecture.md) | Route groups, the protected app shell, adding pages, role-aware nav |
| [api.md](api.md)                                     | HTTP API surface: conventions, tenant scoping, loan-file CRUD |
| [document-model.md](document-model.md)               | The three-tier document model: tiers, the type catalog, tier-aware routing |
| [glossary.md](glossary.md)                           | Mortgage domain terms and technical terms                 |
| [poc-learnings.md](poc-learnings.md)                 | Lessons from the prototype (with a developer TODO section)|
| [project-structure.md](project-structure.md)         | Repository layout and "where does X go?" conventions      |
| [development-workflow.md](development-workflow.md)    | CI/CD pipelines and pre-commit hooks                      |
| [phases/phase-1.md](phases/phase-1.md)               | Ticket-by-ticket phase plan (Epics 1–6)                   |
| [tickets/](tickets/)                                 | Per-ticket implementation records (`LP-XXX.md`)           |

## Also in the repository root

- [`../README.md`](../README.md) — setup and quick start (the project's front door).
- [`../decisions.md`](../decisions.md) — Architecture Decision Records (ADR log).
- [`../CLAUDE.md`](../CLAUDE.md) — conventions for Claude Code; a concise summary
  of how this project is built.

## Canonical product plan

The authoritative product plan is the external **V1 Build Plan v2**. The
in-repo [`phases/phase-1.md`](phases/phase-1.md) mirrors its ticket breakdown for
Phase 1.
