# Amendments

Changes to the spec, tickets or assets made *after* implementation started.
Read this alongside `TICKETS.md` — where the two disagree, this file wins.

---

## 2026-08-29 · from the LP-UI-001 review

Three findings were raised on `docs/tickets/LP-UI-001.md`. All three were checked
independently and all three were correct. Two were defects in the assets, and the
assets have been corrected; the third becomes extra acceptance criteria.

### A1 — `fontWeight` was in the wrong place. Fixed in the asset.

**The finding was right.** `fontWeight` sat under `theme.extend`, and Tailwind
*merges* `extend` with the default theme rather than replacing it, so `bold: 700`
survived and `font-bold` still resolved. The comment in the config claiming "700
does not exist in this system" was false.

`assets/tailwind.config.ts` now declares `fontWeight` at **`theme` level**, which
replaces the scale. Verified by compiling a probe through the Tailwind CLI:
`font-bold` emits nothing; `font-normal`, `font-medium` and `font-semibold` emit
400 / 500 / 600. `frontend/tailwind.config.ts` has been updated to match.

**Consequence, and it needs handling in the same breath:** the 12 existing
`font-bold` call sites now resolve to *nothing* and silently inherit their weight.
That is worse than 700 — text meant to be emphasised quietly stops being
emphasised. **This is now part of LP-UI-002** (see below).

The 12 sites are all page or section headings:

```
app/(protected)/admin/lenders/[id]/page.tsx    app/(protected)/dashboard/page.tsx
app/(protected)/admin/lenders/page.tsx         app/(protected)/loan-files/new/page.tsx
app/(protected)/admin/page.tsx                 app/(protected)/loan-files/page.tsx
app/(protected)/admin/validation/page.tsx      app/(auth)/login/page.tsx
app/(protected)/dev/extraction-bench/page.tsx (x2)   app/page.tsx
components/file/file-header.tsx
```

No other weight class is affected — the codebase uses only `font-normal` (13),
`font-medium` (155), `font-semibold` (105) and `font-bold` (12).

### A2 — `--muted-foreground` failed on two of its own surfaces. Fixed in the asset.

**The finding was right, and the arithmetic was right.** Light
`--muted-foreground` was checked against `background` and `card` only. Against the
other two surfaces it sits on it fell short:

| ground | at 44.3% | at 41.0% |
|---|---|---|
| `background` | 4.56 | **5.18** |
| `card` | 4.69 | **5.33** |
| `muted` | 4.28 ✗ | **4.87** |
| `accent` | 4.05 ✗ | **4.61** |

This does not bite today (two `bg-muted` usages, none paired), but the LP-UI-004
codemod maps `bg-gray-50/100 → bg-muted` and `text-gray-300/400/500 →
text-muted-foreground`, and **24 elements currently carry both** — every one would
have landed on 4.28:1.

Light `--muted-foreground` is now **`168.0 4.4% 41.0%`** (`#646D6B`), which clears
4.5:1 on all four grounds with margin. The finding proposed 41.5%; 41.0% was taken
instead because 41.5% reaches only 4.53 on `accent` and hex rounding could push
that under. Dark was already clear at 4.95:1 on its worst ground and is unchanged.

Both `assets/globals.css` and `frontend/app/globals.css` have been updated.

### A3 — Two colour literals the codemod cannot see. Becomes acceptance criteria.

**The finding was right.** `app/page.tsx:143` and `app/(auth)/login/page.tsx:18`
both carry the old Tailwind blue as an arbitrary value:

```
bg-[radial-gradient(circle_at_top,_hsl(217_91%_60%_/_0.08),_transparent_55%)]
```

The codemod only matches `{prop}-gray-{shade}`, so `rg "gray-[0-9]"` comes back
clean while these survive. `LP-UI-004`'s acceptance criteria are extended below.

---

## Ticket changes

### LP-UI-002 — now "Make the config's promises true"

Was: define the missing `danger` colour. The `danger` alias already ships inside
`assets/tailwind.config.ts`, so that half is done. The ticket now also carries the
`fontWeight` consequence from A1.

**Additional scope**

- Replace all 12 `font-bold` occurrences with `font-semibold`. Mechanical; the
  sizes on those headings get adjusted later by their own screen tickets.
- Verify `font-bold` emits nothing: compile a probe through the Tailwind CLI, or
  `rg "font-bold" app components lib` returning nothing is sufficient.

**Additional acceptance**

- [ ] `rg "font-bold" app components lib` returns nothing
- [ ] No heading silently loses weight — check the dashboard and file headers in
      the browser, not just the diff

### LP-UI-004 — extra acceptance criteria

The codemod's own report is not sufficient proof that the old palette is gone.

- [ ] `rg "gray-[0-9]" app components lib` returns nothing (as before)
- [ ] `rg "217 91%|217_91%" app components lib` returns nothing — the two
      arbitrary-value gradients in A3 are replaced with `hsl(var(--primary) / 0.08)`
- [ ] `rg "#[0-9a-fA-F]{3,8}\b" app components lib` returns nothing outside
      comments — no hex literal re-entered

### LP-UI-011 — also decide the root route

`app/page.tsx` is a 199-line developer health/splash page (backend health check,
dependency rows). It is not a processor screen and was deliberately not designed.
It should not survive as-is.

**Additional scope**

- Decide the root route: redirect `/` to `/dashboard` (authenticated) or `/login`,
  and either delete the health page or move it under `/dev` beside
  `extraction-bench`, which is where developer-only surfaces already live.
- Record the choice as an ADR.

---

## Standing note

The design assets are **not** infallible. LP-UI-001 found two real defects in them
by verifying rather than trusting, which is exactly right. Keep doing that: if a
ticket's premise does not survive contact with the code, say so on the ticket
rather than working around it, and the asset gets corrected here.
