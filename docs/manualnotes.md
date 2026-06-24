# Run application

To see the full picture: run pnpm dev (frontend, :3000) and uv run uvicorn app.main:app --reload (backend, :8000) in two terminals — no Docker needed.



How to do it manually

1. Rebuild + restart the worker (after any code change you want the worker to run):
   docker compose --profile worker up -d --build worker
   Watch it: docker logs -f mortgageboss-worker

2. Re-import a MISMO — two ways:
- The real way (UI): in the app, create a file via "Import MISMO" and upload your .xml. This hits the /import-mismo endpoint, which seeds the floor synchronously and enqueues the AI reasoning. (This is what a processor actually does.)
- The quick way (what I just ran): cd backend && uv run python /tmp/reimport_mismo.py — a small script that parses the fixture, calls the same import service, and enqueues the same task. Handy for testing without logging in. It currently targets your summit company.

3. Verify: the file appears with floor needs immediately; the AI needs land ~20–35s later (watch the worker log for ai_needs_ingested / succeeded).

  ---
Why rebuild the worker on every change?

Two things combine:

1. The worker is a separate long-running process. Celery loads your Python once at startup and doesn't hot-reload. So any code change needs the worker process restarted to take effect — same as you'd restart any server.
2. Our worker is containerized with the code baked in. In docker-compose.yml the worker uses build: ./backend, which copies the source into the image at build time — there's no live mount of your working directory. So the running container keeps its old copy of the code until you rebuild the image. That's why "restart the worker" becomes "rebuild + recreate" (up -d --build).

By contrast, your API (uvicorn, run locally with --reload) sees code changes instantly — no rebuild — which is why you only ever rebuild the worker.

Note for this specific change (LP-71.6): the Government ID actually comes from the import path (seeded synchronously by the API/script), not the worker — so the ID need would've appeared even without rebuilding. I rebuilt anyway so the worker stays in sync and to run the AI reasoning (which does need the worker). In general, only changes to code the worker runs (the AI reasoning / task path) strictly require a worker
rebuild.

Want to skip the rebuilds?

I can add a source volume mount to the worker service (volumes: - ./backend:/app) so the container always sees your live code — then a code change only needs a quick restart (docker compose restart worker), no rebuild. It's a small docker-compose.yml change (dev-only). Say the word and I'll set it up.

The two test files in your dev DB now are LF-FF9V and LF-RWNR (both summit) — delete whenever. Nothing pushed.
