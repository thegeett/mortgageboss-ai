# visual-check: screenshot a Stage 3 screen against its reference

Dev only (LP-934). Builds a screen's state on a scratch database from fictional fixtures, opens it at
**1600 px** in the **light** theme, and saves a PNG next to the reference so the two can be compared
line by line against the screen's **Must match** list in
[`docs/design/phase4.5-conditions/stage3/README.md`](../../docs/design/phase4.5-conditions/stage3/README.md).
It is the method LP-909 §5 used for Stage 1, kept this time.

## Run it

```bash
scripts/visual-check/run.sh S3-02            # -> docs/design/phase4.5-conditions/stage3/checks/S3-02-actual.png
scripts/visual-check/run.sh S3-02 review     # -> …/checks/S3-02-review.png (the reviewer's copy)
scripts/visual-check/run.sh base             # the file with round 1 imported; no reference PNG
VISUAL_STATES="S3-01 S3-02 S3-03" scripts/visual-check/run.sh all
```

Then open the saved PNG beside `screens/<S3-xx>-*.png`. A shot takes about 20 seconds once `next dev`
has compiled the page (the first run compiles it).

Needs: the dev Postgres and Redis running (`docker compose up`), `uv`, `pnpm`, Node 22 or newer (for the
built-in `WebSocket`), and Google Chrome or Chromium. Chrome is found at `$CHROME`, else the usual macOS
and Linux paths.

## What it does, in order

1. **Scratch database.** Drops and creates `mbai_visual_stage3` (override with `VISUAL_DB`, which must
   start with `mbai_visual_`) on the dev Postgres server, and runs `alembic upgrade head` on it. The dev
   database is refused by name, twice: `run.sh` checks it against `backend/.env`, and `seed.py` checks
   again before it imports anything that could connect.
2. **Seed** (`seed.py <state>`). Creates the file the screens draw (Alex Rivera, `LF-R7QK`, United
   Wholesale Mortgage, $242,199, 100 Example Ln, the letter's income and ratios), renders round 1 of
   `uwm_round1` as a PDF, parses it with the real task body, imports it with the real service, and stamps
   the timestamps from the stage3 README's "Today" table. It prints one JSON line: the path to open, the
   moment to freeze the clock at, and what to click.
3. **Servers.** An API on `:8011` and `next dev` on `:3011` against the scratch database, Redis db 9, a
   temporary storage folder and a fictional inbox domain. `next dev` builds into `.next-visual`, so a dev
   server on `:3000` and its `.next` are left alone. Both are stopped when the run ends.
4. **Shot** (`shoot.mjs`). Headless Chrome over the DevTools protocol, with Node's built-in `WebSocket`
   and `fetch` (no Playwright, no Puppeteer, no npm package). It signs in as the seeded processor through
   `/api/v1/auth/login`, sets 1600 px by the reference PNG's own height, the light theme, `en-US` and
   `America/New_York`, and starts the page's clock at the state's moment (it then runs forward, so timers
   still fire). It clicks what the state asks, hides `next dev`'s overlay and the TanStack Query devtools
   button, and saves the PNG. **Every page error and failed request is printed**, so hiding the overlay
   never hides what it was reporting.

`VISUAL_DEBUG=1` also prints every fixed-position element, which is how to find the next dev-only
widget that gets into a shot.

## Adding a screen's state (each Stage 3 UI ticket)

`seed.py` holds `STATES`: screen → builder. A ticket replaces its screens' `_later("LP-9xx")` entry with a
builder that calls `base(db)` (or another state) and then does what the screen shows **through the
product's own services**, never by writing rows the product could not write. Return a `Shot` with the
path, the moment from the "Today" table, and the clicks (visible text, matched exactly) that open the
screen. Keep every value fictional (ADR-405).
