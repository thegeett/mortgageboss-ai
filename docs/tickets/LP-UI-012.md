# LP-UI-012 — Login

- **Ticket:** LP-UI-012 — the login screen
- **Epic:** Ledger redesign → Epic C (Core screens) — first of thirteen
- **Status:** Completed
- **Date:** 2026-08-30
- **Mockup:** Login

## Summary

Split layout: the ledger motif and the thesis on the left, the form on the
right. The ticket calls this "the smallest real test of the token set — if login
looks right, the tokens are right", and it is: the screen uses `primary`,
`success`, `warning`, `destructive`, `muted`, `foreground-2`, the mono and serif
faces, the 13px scale and the rail idiom, with no new value anywhere.

## What Changed

- **`components/auth/ledger-figure.tsx`** (new) — the motif. Two columns,
  *Stated* and *Found in documents*, with a coloured mark in the margin wherever
  they disagree. Six rows: three agree, two differ, one is missing.
- **`app/(auth)/login/page.tsx`** — rewritten as the split layout. The centred
  card, the radial gradient and the blurred primary blob are gone.
- **`components/auth/login-form.tsx`** — the expired-session notice and the
  error both become **rails**.

## The two notices are rails now

This is SPEC rule 5 — state goes on the left rail and the glyph, never a
background fill — and it is the acceptance criterion this ticket names.

| | before | after |
|---|---|---|
| expired session | `border-warning/30 bg-warning/10 text-warning` | `border-l-2 border-l-warning` on `bg-muted/60`, `text-foreground-2` |
| login error | `border-destructive/30 bg-destructive/5 text-destructive` | `border-l-2 border-l-destructive` on `bg-muted/60` |

Measured in the browser: `border-left: 2px rgb(143, 93, 8)` in light,
`rgb(217, 160, 62)` in dark — the warning token in each theme, against a neutral
surface rather than a coloured one. An expired session is an explanation, not an
alarm, and a filled amber box makes it read as the latter.

The glyphs also moved onto the status vocabulary: `TriangleAlert` for attention,
`CircleX` for blocking, the same shapes `StatusToken` uses.

## Verification

Both themes, driven in a browser signed out:

- **Expired notice** renders as a rail in both themes (values above).
- **Thesis line** computes to `"IBM Plex Serif"` — the upright face the LP-UI-003
  review added when it found the italic-only load left `font-serif` falling back
  to Georgia silently.
- **Autofocus** lands on the email field; `autocomplete` is `email` and
  `current-password`; the password reveal button is present. All three
  behaviours the ticket asks to preserve, checked rather than assumed.
- **The non-enumerating error message is untouched** — `getLoginErrorMessage`
  was not edited; 401 still returns "Invalid email or password." for both a bad
  address and a bad password.
- **Below `lg`** (700px): the left panel is `display: none` and the form is
  visible.

**CI.** biome, tsc, 577 tests, build — green.

## Deviations from the mockup, and why

Three, all because the mockup shows data this screen cannot have:

1. **"Loan processing for Cascade Processing Group."** The mockup names the
   company under the heading. Login is pre-auth — the app does not know which
   company is signing in until it has. Kept "Enter your credentials to access
   your loan files."
2. **"Trouble signing in? Contact your admin."** The mockup makes that a link.
   There is no such route, and a link to nowhere is worse than the sentence
   alone. Kept "Accounts are provisioned by your administrator."
3. **The email is pre-filled in the mockup.** Illustrative only.

## Findings raised

1. **The thesis is a second use of the serif, and the SPEC says there is one.**
   SPEC rule: *"Plex Serif italic appears in exactly one place, text quoted
   verbatim from a document."* The mockup renders this line in upright serif,
   and the LP-UI-003 review already loaded the upright face for LP-UI-029's
   verbatim-snippet state. So the font is available and the mockup is explicit —
   I followed the mockup, since the brief wins where it is specific. But the
   SPEC sentence is now false as written, and should either say "two places" and
   name them, or the login thesis should drop to sans. A design call, not mine.

2. **Every signed-out visit to `/login` logs a console error.** The silent
   refresh fires on load and gets a 401 because there is no refresh cookie —
   the correct outcome, reported as `API error: Request failed with status code
   401`. Pre-existing and not this ticket's, but it means the console is never
   clean on the app's first screen, which is where a developer looks first when
   something else is wrong.

## Assumptions and decisions

- **Decided** the left panel is `hidden` below `lg` rather than stacked above
  the form. Someone signing in on a narrow screen wants the form, not the
  argument for a product they have already bought.
- **Decided** the figure is `aria-hidden`. Its numbers are invented and the
  sentence beneath states the same idea in words; reading six fake money values
  aloud is noise.
- **Decided** the wordmark repeats inside the form column only below `lg`, where
  the left panel that carries it is gone.
- **Assumed** the figure's exact values are illustrative. They are transcribed
  from the mockup, including the two amber rows and the one red.

## Files

- new: `components/auth/ledger-figure.tsx`
- changed: `app/(auth)/login/page.tsx`, `components/auth/login-form.tsx`
