EPIC 1: Repo & Infrastructure Setup
Goal: V1 repository skeleton with all tooling, ready for code.
LP-1: Initialize V1 monorepo skeleton

Create new git repository named loan-processing-assistant
Set up monorepo structure with backend/, frontend/, docs/, .github/ directories
Add root .gitignore covering Python, Node, IntelliJ, OS files
Add root README.md with project overview and quick-start placeholder
Add decisions.md for architecture decision log
Initial commit with empty skeleton

LP-2: Docker Compose for local services

Create docker-compose.yml with PostgreSQL 16, Redis 7, MailHog
Use named volumes for data persistence
Expose Postgres on 5432, Redis on 6379, MailHog UI on 8025
Document setup in docker-compose.README.md
Verify docker-compose up brings everything online
Verify can connect to Postgres and Redis from host

LP-3: Backend project initialization

Create backend/pyproject.toml using uv as package manager
Define core dependencies (FastAPI, SQLAlchemy 2.x async, Alembic, anthropic, celery, pydantic, etc.)
Define dev dependencies (pytest, ruff, mypy, httpx for testing)
Add backend/.python-version pinning Python 3.12
Add backend/ruff.toml with formatting and linting config
Verify uv sync installs everything cleanly

LP-4: Backend directory scaffolding

Create backend/app/ with all subdirectories per V1 plan (core, models, schemas, api, ai, services, verification, tasks, storage)
Add __init__.py to every Python package
Add backend/app/main.py with minimal FastAPI app and health check endpoint
Add backend/tests/ structure with conftest.py and subdirectories (unit, integration)
Verify backend runs: uv run uvicorn app.main:app --reload

LP-5: Frontend project initialization

Create Next.js 15 app in frontend/ with TypeScript, App Router, Tailwind, ESLint
Choose pnpm as package manager
Add shadcn/ui setup with pnpm dlx shadcn@latest init
Install initial component primitives (button, card, dialog, form, input, table)
Add frontend/.env.example documenting required env vars
Verify frontend runs: pnpm dev shows default page on localhost:3000

LP-6: Environment configuration

Create root .env.example listing all required env vars (DATABASE_URL, REDIS_URL, ANTHROPIC_API_KEY, JWT_SECRET, etc.)
Create backend/app/core/config.py using Pydantic Settings
Load settings from environment with sensible defaults for development
Add .env to .gitignore (never commit secrets)
Document how to populate .env from .env.example in README

LP-7: CI/CD setup

Create .github/workflows/backend-ci.yml running ruff and pytest on push
Create .github/workflows/frontend-ci.yml running biome/eslint and type-check on push
Configure to run on PRs to main
Add CI status badge to README
Verify pipeline runs green on initial commit

LP-8: Initial documentation

Write CLAUDE.md at repo root with V1 architecture and conventions for Claude Code
Write docs/architecture.md with system overview
Write docs/poc-learnings.md capturing key insights from POC (lessons, edge cases, patterns to reuse)
Update root README with comprehensive setup instructions
Document the decision log practice (when to add entries)


EPIC 2: Database & Models
Goal: Complete database schema with SQLAlchemy models for all V1 entities.
LP-9: Alembic migrations setup

Initialize Alembic in backend/alembic/
Configure for async SQLAlchemy
Create backend/app/core/database.py with async engine and session factory
Set up Alembic env.py to use the same engine
Create empty initial migration to verify workflow
Document migration commands in docs/database.md

LP-10: Core SQLAlchemy base and mixins

Create backend/app/models/base.py with Base declarative base
Add TimestampMixin (created_at, updated_at)
Add SoftDeleteMixin (deleted_at, is_deleted property)
Add UUIDMixin for primary keys
Add type-safe column conventions (using SQLAlchemy 2.x Mapped style)

LP-11: Multi-tenancy models

Create Company model (name, slug, settings JSON)
Create User model with company_id FK, email, hashed_password, role, name
Add unique constraint on email (globally unique)
Add appropriate indexes (company_id, email)
Create Alembic migration
Add seed data script for one test company and one test user

LP-12: Lender model

Create Lender model with company_id FK, name, slug, contact info
Add lender_overlays JSON column for overlay rules (populated in Phase 3)
Add active/inactive flag
Create migration
Add seed data for UWM and Sun-West as initial test lenders

LP-13: Loan file core model

Create LoanFile model with human-readable ID (LF-XXX format)
Add fields: company_id, lender_id FKs, status, loan_program (conv/fha), loan_purpose (purchase/refi), loan_amount, loan_officer_name, loan_officer_email
Add inbox_token (random unguessable string for Phase 4 borrower inbox)
Add status enum with all lifecycle states
Implement LF-XXX ID generator service
Create migration with proper indexes

LP-14: Borrower and property models

Create Borrower model linked to LoanFile with first_name, last_name, middle_name, ssn (encrypted), dob, email, phone, marital_status
Create Property model linked to LoanFile with address fields, property_type, occupancy_type, estimated_value, purchase_price
Support multiple borrowers per file (co-borrower)
One property per file (V1 scope)
Create migrations with cascade rules

LP-15: Document model

Create Document model linked to LoanFile with original_filename, mime_type, file_size, storage_path
Add classification fields: document_type, classification_confidence, classification_status
Add processing status (pending, classifying, extracting, completed, failed)
Add document_category enum matching sister's categories (assets, borrower_info, credit, disclosures, income, property, misc)
Add uploaded_by user FK and uploaded_at timestamp
Create migration with indexes on file_id, type, status

LP-16: Extraction model

Create Extraction model linked to Document
Add version number (for versioned re-extractions)
Add extracted_data JSON column (flexible structure per document type)
Add extraction_status, model_used, tokens_used, cost_estimate
Add is_current flag (only one current per document)
Create migration with index on document_id and is_current

LP-17: Finding model

Create Finding model linked to LoanFile (and optionally Document)
Add rule_id, status (red/yellow/green), severity, category, message
Add source_document_id FK (which document triggered this)
Add resolution_status (open, resolved, accepted_risk, waived)
Add resolution_note and resolved_by user FK
Create migration

LP-18: Verification run model

Create Verification model linked to LoanFile
Add version, started_at, completed_at, total_rules_run, status
Link findings to verification run
Create migration

LP-19: Needs item model

Create NeedsItem model linked to LoanFile
Add fields: name, category, status (pending/received/verified/rejected/waived), priority
Add linked_document_id when received
Add auto-generated flag vs manual flag
Create migration

LP-20: Communication and activity models

Create Communication model with file_id, direction (inbound/outbound), type (email/note), subject, body, status (draft/sent/received), from/to addresses
Create ActivityLog model with file_id, actor_type (user/system/ai), actor_id, action, details JSON, timestamp
Add indexes for chronological queries
Create migration

LP-21: Placeholder tables for future phases

Create stub models for Phase 1.5: StatedAsset, StatedLiability, StatedIncomeItem, StatedEmployer, MismoImportRecord (just enough structure to migrate, fields can be expanded)
Create stub models for Phase 4.5: Condition, ConditionStateHistory, ConditionResolution, UwRound
Create stub for Phase 5: ChatConversation, ChatMessage
Create single migration adding all placeholders
Document that these will be populated in their phases


EPIC 3: Authentication & Authorization
Goal: Working login/logout/registration with JWT, scoped to company.
LP-22: Password hashing and JWT utilities

Create backend/app/core/auth.py with bcrypt password hashing
Implement JWT token creation (access + refresh tokens)
Implement JWT token verification with proper error handling
Add token expiry (24h for access, 30d for refresh)
Add unit tests for hash/verify and token round-trip
Configure JWT secret from env

LP-23: Authentication endpoints

Create backend/app/api/routes/auth.py
POST /api/auth/login (email + password, returns access + refresh tokens)
POST /api/auth/refresh (refresh token returns new access token)
POST /api/auth/logout (invalidate refresh token if using token revocation)
POST /api/auth/register (admin-only initially, creates user in company)
GET /api/auth/me (returns current user info)
Add request/response Pydantic schemas

LP-24: Auth dependencies and middleware

Create backend/app/api/deps.py with get_current_user dependency
Create require_admin dependency for admin-only routes
Create get_db async session dependency
Add company scope helper that filters queries by current user's company
Add unit tests verifying unauthorized requests are rejected

LP-25: Frontend auth implementation

Create frontend/lib/api/client.ts with axios or fetch wrapper
Add request interceptor to attach JWT to requests
Add response interceptor to handle 401 with refresh token flow
Create frontend/lib/auth/context.tsx React context for user state
Implement token storage in httpOnly cookies (preferred) or sessionStorage
Add automatic redirect to login on 401

LP-26: Login and register pages

Create frontend/app/(auth)/login/page.tsx with form using react-hook-form + Zod
Create frontend/app/(auth)/register/page.tsx (initially for admin-only use)
Add form validation (email format, password requirements)
Add error display for invalid credentials
Add loading states during submission
Style with shadcn/ui components

LP-27: Protected app layout

Create frontend/app/(app)/layout.tsx for authenticated routes
Check auth state on mount, redirect to login if not authenticated
Add top navigation bar with user info and logout
Add sidebar navigation (Dashboard, Files, Settings placeholder)
Implement logout (clear tokens, redirect to login)


EPIC 4: Loan File CRUD
Goal: Create, read, update, delete loan files with full UI support.
LP-28: Loan file API endpoints

Create backend/app/api/routes/files.py
POST /api/files (create new file)
GET /api/files (list with filters: status, lender, search, pagination)
GET /api/files/{id} (full file detail with relations)
PATCH /api/files/{id} (update file metadata)
DELETE /api/files/{id} (soft delete)
All endpoints scoped to current user's company
Add request/response Pydantic schemas

LP-29: Borrower and property API endpoints

POST /api/files/{file_id}/borrowers (add borrower)
PATCH /api/files/{file_id}/borrowers/{id} (update)
DELETE /api/files/{file_id}/borrowers/{id}
PATCH /api/files/{file_id}/property (update property)
Add validation rules (at least one borrower, one property per file)

LP-30: Loan file service layer

Create backend/app/services/files.py with business logic
Implement create_loan_file that handles ID generation, initial status, defaults
Implement generate_initial_needs_list based on loan program
Implement file listing with proper filtering and pagination
Add activity log entries for create/update/delete
Add unit tests for service layer

LP-31: Dashboard page

Create frontend/app/(app)/dashboard/page.tsx
Implement file list table with columns: ID, borrower, property, status, lender, last activity
Add filter pills (all, active, action needed, completed)
Add search box (by borrower name or file ID)
Add "New File" button
Add stats cards at top (active files count, action needed count, etc.)
Use TanStack Query for data fetching

LP-32: New file intake form

Create frontend/app/(app)/files/new/page.tsx
Build multi-step or single-page form for borrower, property, loan, lender info
Use react-hook-form + Zod for validation
Show lender dropdown populated from API
Add loan program selector (Conventional / FHA)
Submit creates file via API, redirects to file detail page on success
Add error handling and loading states

LP-33: File detail page shell

Create frontend/app/(app)/files/[id]/layout.tsx with tab navigation
Create frontend/app/(app)/files/[id]/page.tsx (overview, default tab)
Add placeholder pages for documents, verification, communication, conditions, lender-package
Show file header with borrower name, ID, status, key dates
Implement tab navigation with active state
Fetch file data using TanStack Query

LP-34: Overview tab basic content

Show borrower(s), property, loan details cards
Show needs list (pending items) — count and basic list
Show recent activity feed (from activity_log)
Add "AI summary coming in Phase 6" placeholder
Add "Key metrics coming in Phase 3" placeholder


EPIC 5: Document Upload & Processing
Goal: Upload documents, classify and extract them via async pipeline.
LP-35: Storage abstraction layer

Create backend/app/storage/base.py with StorageBackend interface
Create backend/app/storage/local.py implementing local filesystem storage
Support save, read, delete, get_url operations
Use path pattern: storage/{company_id}/{file_id}/{document_id}.{ext}
Make backend configurable via settings (prepares for S3 in production)
Add unit tests

LP-36: Document upload endpoint

Create backend/app/api/routes/documents.py
POST /api/files/{file_id}/documents (multipart upload, accepts multiple files)
GET /api/files/{file_id}/documents (list documents for file)
GET /api/documents/{id} (single document with extraction)
GET /api/documents/{id}/download (download original)
DELETE /api/documents/{id} (soft delete)
Validate file size (max 50MB) and type (PDF, JPG, PNG)

LP-37: Anthropic async client wrapper

Create backend/app/ai/client.py with singleton AsyncAnthropic client
Add retry logic with exponential backoff for transient failures
Add structured logging for all AI calls (model, tokens, latency)
Add cost tracking helper
Add unit tests with mocked responses

LP-38: Document classification module

Create backend/app/ai/classification.py
Implement classify_document(text: str) -> ClassificationResult async function
Load prompt from backend/app/ai/prompts/classification/document_classifier.txt (port from POC)
Use Claude Haiku model
Return typed Pydantic result with type, confidence, reasoning
Handle errors gracefully (return "unknown" with low confidence on failure)
Add unit tests with sample documents

LP-39: Document extraction module (pay stub only for Phase 1)

Create backend/app/ai/extraction/pay_stub.py
Define PayStubExtraction Pydantic schema (typed fields: employer, dates, gross/net pay, deductions)
Load extraction prompt from backend/app/ai/prompts/extraction/pay_stub.txt (port from POC)
Implement extract_pay_stub(text: str) -> PayStubExtraction async function
Use Claude Sonnet model
Return typed result; later phases add more document types
Add unit tests with sample documents

LP-40: PDF text extraction utility

Create backend/app/services/pdf_utils.py
Implement extract_text_from_pdf(file_path: str) -> str using PyMuPDF or pdfplumber
Handle multi-page documents
Handle scanned PDFs (skip OCR for V1; flag if no text extracted)
Add unit tests with sample PDFs

LP-41: Celery setup

Create backend/app/tasks/celery_app.py configuring Celery with Redis broker
Configure task serialization (JSON), result backend, timeouts
Add task base class with logging and error handling
Create startup command for worker: celery -A app.tasks.celery_app worker --loglevel=info
Document worker startup in README
Verify worker connects to Redis and can run tasks

LP-42: Document processing pipeline tasks

Create backend/app/tasks/document_processing.py
Implement classify_document_task(document_id) task
Implement extract_document_task(document_id) task
Chain tasks: upload triggers classify, classify triggers extract
Update document and extraction records as tasks complete
Update needs list items if document matches a pending need
Add activity log entries
Handle and log failures

LP-43: Documents tab in frontend

Create frontend/app/(app)/files/[id]/documents/page.tsx
Implement drag-and-drop upload zone using react-dropzone
Show documents grouped by category
Show classification status, type, confidence
Show extraction status with loading indicator
Polling for status updates (every 2-3 seconds while processing)
Add document detail drawer (click to view extracted fields, download, re-extract)

LP-44: Manual document type override

Add PATCH /api/documents/{id} endpoint allowing type override
When type is changed, trigger re-extraction with new type
UI: in document detail drawer, allow processor to select correct type from dropdown
Show confidence warning when overriding
Log override to activity_log


EPIC 6: Testing, Polish & Phase 1 Completion
Goal: Polished, tested, ready-for-sister-review Phase 1 build.
LP-45: Integration test suite for API

Create integration tests covering full auth flow (register → login → use protected endpoint)
Create integration tests for file CRUD lifecycle
Create integration tests for document upload + processing pipeline (mock Anthropic calls)
Create integration tests for tenant isolation (User A can't access Company B's data)
Aim for ~70% coverage on API endpoints

LP-46: Error handling and user feedback

Add error boundary components in frontend
Standardize error responses from backend (consistent JSON shape)
Add user-friendly error messages (no stack traces shown to users)
Add toast notifications for success/error feedback (sonner or shadcn toast)
Test error scenarios: upload failure, expired token, network errors

LP-47: Loading states everywhere

Audit every async operation in frontend
Add skeleton loaders for lists and cards (shadcn skeleton)
Add spinner buttons for form submissions
Add progress indicators for file uploads
Ensure no UI elements appear "frozen" during async operations

LP-48: Seed data script

Create backend/scripts/seed_dev_data.py
Creates: test company, admin user, processor user, 2 lenders (UWM, Sun-West), 3 sample loan files in different states
Document how to run: uv run python scripts/seed_dev_data.py
Make script idempotent (safe to run multiple times)
Useful for sister testing and reproducible dev environment

LP-49: Sister-ready demo prep

Verify full workflow end-to-end: register → login → create file → upload document → see classification + extraction
Fix any obvious UX rough edges
Add a simple "About this phase" note explaining what works and what's "coming in Phase X"
Test in clean environment (fresh database, fresh browser)
Document setup steps so sister could theoretically run it locally

LP-50: Phase 1 review session

Walk sister through the working Phase 1 build
Capture every reaction (positive, negative, surprised)
Document feedback in docs/phase-1-feedback.md
Note what she'd want changed before Phase 1.5 starts
Update decisions.md with any new decisions from feedback
Mark Phase 1 complete in project tracking
