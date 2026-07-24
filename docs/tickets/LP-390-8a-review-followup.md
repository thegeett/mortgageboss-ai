# LP-390-8a review follow-up — derive `stmt.owner_matches_borrower` deterministically

**Status:** DEFERRED (proposal, not scheduled). Raised in the LP-390-8a code review; the team chose to keep
the AI path for now (AS-6 is mid-calibration with Priya) and track the deterministic alternative here.
**Not blocking** — AS-6 stays bar-ready/held either way.

## The finding

`stmt.owner_matches_borrower` ("does the account holder named on a bank statement resolve to a borrower on
the loan?") is produced as an **AI** tag by the `stmt_facts` group. LP-390-8a added infrastructure to feed the
AI the loan's borrower roster (`AiGroup.include_borrower_roster` → `loan_borrower_roster` →
`produce_ai_group_tags` merges `loan_borrowers` into each subject's context) and a prompt that asks the model
to name-match *tolerantly* (middle initial, nickname, maiden/married, joint = match-if-either). AS-6 is now
blocked on Priya calibrating that AI judgment (LP-390-5/6/8a/396/397).

But the question is a **deterministic name comparison**, and the codebase already implements exactly it:

- `app/services/borrower_name_matching.py` — `match_document(asserted_names, borrowers)` +
  `asserted_names_for(extracted_data, document_type)`, with `normalize_name` / nickname canonicalization /
  tolerant token matching (middle initial, accents, maiden/married). It is the **established** path: used by
  `documents_section.py` / `document_borrower_links.py` to resolve a document's `belongs_to`.
- The tolerant-matching rules the LP-390-8a prompt re-specifies in natural language are the *same* rules that
  service already encodes in code.

This also sits against the repo convention (root `CLAUDE.md`, Data-model principles): **"Deterministic rules.
AI only for perception (classify/extract)."** A name-match against a roster is a comparison, not extraction.

## Proposed change (when picked up)

Make `stmt.owner_matches_borrower` a **derived** tag (not AI):

```
owner_matches_borrower(statement) =
    "yes"      if match_document(asserted_names_for(statement.fields, "bank_statement"), roster)
    "no"       if asserted names present but none match a borrower
    "unknown"  if no asserted account-holder name could be read (fail-closed, with reason)
```

reusing the roster `loan_borrower_roster` already assembles.

**Note — NOT the same as `belongs_to`.** `belongs_to` can be human-overridden (`document_borrower_links`), so
deriving from "belongs_to non-empty" would miss the fraud AS-6 exists to catch (a statement manually attributed
to borrower A whose account holder is actually B). The derivation must be a **fresh** `match_document` of the
statement's asserted name against the roster, exactly as above.

### Benefits
- No AI calibration for AS-6 (it becomes `no-ai-dependency` / `input_resolves`, activatable directly — the
  whole LP-390-5/6/8a/396/397 AS-6 calibration arc is avoidable).
- No roster-in-prompt infrastructure; reuses the one tolerant matcher (one identity path, not two).
- Deterministic → same file, same answer; no abstention risk from prompt phrasing.

### Open question for Priya / domain
Does deterministic tolerant name-matching fully satisfy AS-6's intent, or is there judgment latitude the AI
was deliberately chosen for? The FN direction (accepting a statement NOT owned by the borrower) is the
dangerous one and is currently **untested** (the LF-6T3N calibration is one-sided — all `yes`; see the AS-6
bar caveat in `activation_bars.yaml`). A deterministic matcher makes the "no"/"unknown" behavior explicit and
testable, which is arguably safer than an uncalibrated AI "no".

## Folded-in efficiency note (LP-390-8a review finding 2)

`produce_ai_group_tags` merges the loan-level `loan_borrowers` roster into **each** subject's context, so a
batch of N statements serializes the identical roster N times in the prompt (`{"index": i, …,
"loan_borrowers": roster}` per subject). It could be hoisted to the batch context top-level and sent once
(keeping it per-subject only in the fingerprint, for cache invalidation). **Deliberately not done standalone
now:** it changes the AI-visible JSON format that AS-6's `measured_accuracy: 1.0` (5/5) was measured on, so it
belongs with the re-architecture or a re-calibration pass, not mid-calibration. The token cost today is
negligible (a couple of names × batch size).
