# AI System Disclosure — Borrower email drafting (LP-810)

- **Feature:** the drafting engine that composes the document-request email a processor reviews
- **Ticket:** LP-810, disclosed under LP-821
- **Status of this document:** written by engineering from the code. **Not yet reviewed by the
  domain expert or by counsel** — see *Open items*.
- **Date:** 2026-09-09

`phase4.md` §6 requires one of these per AI feature, because **Fannie Mae LL-2026-04** (effective
Aug 2026) and **Freddie Mac Guide §1302.8** (effective Mar 2026) make our customers contractually
responsible for governing *our* AI "no less protective" than their own, with disclosure to Fannie on
demand.

---

## 1. Purpose

To draft the wording of a document request to a borrower, so a processor edits a first version
rather than writing one. It writes prose. **It does not decide anything.**

What is *not* AI, and is worth stating because a reader will assume otherwise: which documents are
needed (deterministic rules, Phase 3), who holds each one (LP-800's static catalog), whether a
request may be sent (LP-811a's guards), and whether an arriving document satisfies a need (LP-806,
a processor's click).

## 2. Model and version

| | |
|---|---|
| Provider | Anthropic, via **Amazon Bedrock** in the customer's region |
| Model | as configured in `settings.anthropic_model_reasoning` — pinned per environment, recorded per message |
| Prompt version | recorded per message on the evidence record (`prompt_version`) |

The model id and prompt version are stored on `communication_evidence` for every message the drafter
composed, so "which model wrote this" is answerable for a specific email rather than for a
deployment window.

## 3. Inputs and outputs

**Inputs.** A fact bundle assembled by the application: the loan file's display id, the list of
outstanding needs with their catalog labels and retrieval guidance, and the processor's tone profile
(LP-822). **No borrower name, no SSN, no account number, and no document content** — the drafter is
given what to ask for, not what the file contains.

**Outputs.** A subject line and a body. Nothing else; no scores, no classifications, no routing.

## 4. Where a human decides

Every send. There is no path in the product where a drafted message reaches a borrower without a
named, authenticated processor pressing send — `send_draft` requires `approver_user_id`, and the
evidence record stores it.

The processor's edit is captured separately from the draft (`body_composed` vs `body_as_sent`), so
"did a person change what the model wrote" is answerable per message.

**Feature flag:** the drafter ships **off by default**. With the flag off, every draft comes from a
fixed template (LP-817) and no model is called.

## 5. Guardrails

Deterministic, applied to every composition before it is stored or shown:

- A composition failing any guard is **discarded**, not shown and not cached; the plain template is
  used instead.
- One retry, then the template. No unbounded loop.
- The compliance scanner refuses wording that commits to a decision, states a rate, or implies
  approval.
- The same guard function re-checks the **cache on the way out**, so a guard added later heals
  stored prose rather than applying only to compositions made after it shipped.

**Not yet recorded, and stated here because an evidence record is read by people who were not
present.** `CommunicationEvidence.guardrail_fired` exists and is **empty for every send**. The
drafter runs before the send and returns prose, while the guard's verdict stays in
`email_draft_prose`, so nothing carries it across; threading it through is a service change rather
than a schema one. Until then a null in that column means **not recorded**, not "no guard fired",
and the same is true of `model_id` and `prompt_version`.

This paragraph replaced two statements that were wrong in the direction that flatters the system.
The first said which guard fired *is* recorded. The second said the cache is filtered "on the way
in" — which would apply a new guard only to prose stored after it, the opposite of the healing
property claimed in the same sentence, and the opposite of what the code does.

## 6. Monitoring

- Every composed message has an evidence row (LP-821): model, prompt version, which guard fired,
  and whether the processor edited it.
- `readonly.communication_evidence` exposes those without exposing any body, so "how often is the
  drafter edited, and how often does a guard fire" is answerable without reading borrower mail.
- Structured logs carry metadata only — never a body, a subject or an address.

## 7. Limitations

- **It writes prose about documents; it has no view of the file's substance.** It cannot be right or
  wrong about eligibility, because it is never told any.
- Guard coverage is a list, not a proof: a wording nobody anticipated can pass.
- The tone profile is learned from a processor's own past messages, so it reproduces their habits —
  including ones they would not defend if asked.
- **Not evaluated against a labelled corpus.** There is no accuracy figure here because none has
  been measured, and a number invented for a disclosure is worse than its absence.

## 8. Data handling

- **Bedrock, in the customer's region.** Zero-data-retention is **not** the Bedrock default — new
  accounts default to `inherit` — so it is set explicitly and must be locked with an SCP.
- Cross-region inference stores retained data in the **destination** region; inference-profile
  regions are pinned for that reason.
- Bedrock model-invocation logging is either disabled or its S3/CloudWatch destination is treated as
  a customer-information store with a CMK, access control and a retention schedule. It would
  otherwise contain borrower document text in prompt bodies — the most commonly missed NPI store in
  AI mortgage builds.
- No borrower data is used for training. No third party receives it.

## 9. NIST AI RMF mapping

| Function | Where |
|---|---|
| **GOVERN** | This document; the feature flag; `decisions.md`'s ADRs |
| **MAP** | §§1–3 above — purpose, inputs, and what the system is *not* for |
| **MEASURE** | §6 — per-message evidence; guard-fire and edit rates from the readonly view. **Weakest function: no offline evaluation exists.** |
| **MANAGE** | §5's guards, the template fallback, and human approval on every send |

---

## Open items

These are stated rather than smoothed, because a disclosure that reads as finished when it is not is
the failure this document exists to prevent.

1. **Not reviewed by the domain expert or by counsel.** Written from the code by engineering.
2. **No offline evaluation.** §9's MEASURE function has monitoring and no benchmark.
3. **The Bedrock retention settings are asserted, not verified in this repo.** They are an account
   and SCP configuration; nothing here proves the deployed state matches §8.
4. **`prompt_version` has no home yet** — LP-810's open escalation. Until it does, that field on the
   evidence record will be null for every message.
