# Conversion notes

Converted **98** markdown designs (011–108) to JSON; copied **10** reviewed merged specs (001–010) unchanged. Total **108** specs.

**All 108 JSON files parse.**

## Totals

- Typed-core fields: **2112**
- Nested lists: **66** (≈ **315** plumbing sites)
- Rule-floor fields (a rule needs it, catalog omits it): **190**
- Open questions: **349**, of which **142** block implementation
- Degraded-type fields (enum/bool/percent/address/object → str): **739**
- Typed PII fields: **128**
- Existing-extractor specs (diff-style): **18**

## Ambiguities flagged during conversion

_Fields whose reason_class or type the source markdown did not cleanly support — recorded, not invented._


**011 homeowner-s-insurance**
- insured_property_address
- named_insured

**013 1040-individual-federal-tax-returns**
- tax_year
- home_address

**014 drivers-license**
- credential_type
- issue_date

**015 written-voe**
- employee_number
- employer_signer_title

**017 investment-account-statements**
- statement_period_start

**018 ira-401k**
- statement_period_start

**021 rental-agreements-lease-agreements**
- landlord_signature_date
- tenant_signature_date

**022 retiree-account-statement**
- statement_period_start
- statement_period_end

**024 flood-certification**
- determination_date (reason_class identity vs rule — marked 'IH-5/identity')

**025 gift-letter**
- transfer_method (reason_class disambiguator vs rule)
- donor_address (pii registration unresolved — set ADDRESS/pre_masked=false per recommendation)

**026 mortgage-payoff**
- wire_or_remittance_instructions (reason_class pii vs processor — why leads processor but governing reason is PII protection)

**027 property-tax-bill-subject**
- taxing_authority (reason_class identity vs rule — 'DT-4 context')
- current_balance (reason_class rule vs processor — 'RE-2 / processor')

**028 subject-property-note**
- rate_type (reason_class disambiguator vs processor — 'processor / disambiguator')
- note_date (reason_class identity vs rule — 'identity/attribution ... CL-6 execution timing')

**031 court-order-documents**
- judge_name_and_signature (authenticity/execution has no dedicated reason_class; mapped to processor)

**032 cpa-letter**
- cpa_license_number, license_status_or_verification, cpa_signature (authenticity/execution has no dedicated reason_class; mapped to processor)

**033 emd-withdrawal-proof**
- posting_date (typed str with a '(date)' annotation; degrading a coercer-eligible date to str is unusual)

**035 k-1-schedule-1065-1120s**
- partner_type_or_shareholder_status

**036 master-insurance-policy-for-condominium**
- flood_coverage_present

**037 profit-and-loss-statement-balance-sheet**
- issuer_name
- prepared_by

**038 resident-alien-card**
- issuer_name

**039 social-security-award-letter**
- representative_payee

**047 appraisal-payment**
- document_title (tagged identity/disambiguator — set to disambiguator)
- check_number_or_transaction_reference (pii.kind set to ACCOUNT as best guess)

**048 authorization-to-run-credit**
- authorized_bureaus_or_report_types (a flat str[] typed as str with degraded_from 'list')

**050 bankruptcy-discharge-notice**
- case_number (tagged PII confidential but design recommends unmasked typed identity — reason_class identity, pii null)

**051 bankruptcy-filing**
- case_number (tagged PII confidential but design recommends unmasked typed identity — reason_class identity, pii null)

**052 birth-certificate**
- certificate_or_state_file_number (pii.kind FILE_NUMBER not a standard registered kind)
- local_file_or_registration_number (pii.kind FILE_NUMBER not a standard registered kind)

**053 boarder-proof-of-residency**
- loan_number

**054 boarder-rental-payments**
- loan_number

**055 borrower-authorization-and-certification**
- loan_number
- borrower_signature_date

**056 borrower-s-authorization-for-counseling**
- loan_number
- counseling_type
- borrower_signature_date

**057 building-permits**
- permit_type

**058 business-existence-verification-cpa-ltr-bus-lic**
- industry_or_business_activity
- verification_document_type

**059 business-federal-tax-returns**
- signature_date: why tagged 'execution' (not one of the five classes) — mapped to processor
- paid_preparer_name: why tagged 'source' (not one of the five classes) — mapped to processor

**061 certificate-of-eligibility**
- va_file_or_loan_number: PII class unresolved (Open question 3) — carried as reason_class identity, pii null
- prior_va_loan_or_entitlement_charges nested-list fields inferred; the design doc did not enumerate them

**063 credit-card-authorization**
- authorization_or_transaction_id: 'audit/identity' restricted field flagged for review — carried as reason_class identity, pii null

**066 divorce-decree**
- judge_name — why tagged 'execution', not a valid reason_class; mapped to processor

**067 earnest-money-emd-receipt**
- recipient_name_and_title — why tagged 'execution', not a valid reason_class; mapped to processor

**069 financial-statements**
- total_assets — why tagged 'headline', not a valid reason_class; mapped to processor
- total_liabilities — 'headline' mapped to processor
- net_worth — 'headline' mapped to processor

**070 foster-care-verification**
- gross_payment_amount — why tagged 'headline', not a valid reason_class; mapped to processor

**072 hoa-certification**
- regular_hoa_dues (tagged 'headline', not a defined reason_class; mapped to processor)

**073 homeowner-s-insurance-quote**
- dwelling_coverage_a (tagged 'headline'; mapped to processor)
- annual_premium (tagged 'headline'; mapped to processor)
- replacement_cost_or_coinsurance_basis (tagged 'processor/disambiguator'; mapped to disambiguator)

**074 k-1-shareholder-profit-and-loss-transcripts**
- ordinary_business_income_or_loss (tagged 'headline'; mapped to processor)

**075 letter-of-explanation-asset**
- source_or_origin_of_funds (tagged 'headline'; mapped to processor)

**076 letter-of-explanation-child-care**
- current_childcare_expense (tagged 'headline'; mapped to processor)

**077 letter-of-explanation-income**
- signature_date reason_class: markdown tags it 'execution', not one of the five classes — set to processor

**078 letter-of-explanation-misc**
- signature_date reason_class: 'execution' → set to processor

**079 letter-of-explanation-property**
- signature_date reason_class: 'execution' → set to processor
- address_mismatch_orhistory: tagged 'processor/disambiguator' → set to processor (first-listed primary)

**096 termite-completion**
- company_representative_name
- company_representative_signed_date

**098 transcripts-of-1099**
- transcript_request_or_run_date

**099 trust-agreement**
- subject_property_in_trust
- trustee_signature_present

**100 trust-documents**
- document_execution_date

## Blocking open questions (resolve before code generation)

- **001 1003-loan-application-urla** — Does a PDF 1003 need extraction at all, given MISMO is authoritative? _Rec: full typed core — the PDF is the cross-check against MISMO, and if the two can disagree that is an unwritten rule worth surfacing_
- **001 1003-loan-application-urla** — No PiiKind exists for DOB or ADDRESS _Rec: add both — the credit report needs them too_
- **004 title-commitment** — Legal description length vs the token ceiling _Rec: verbatim — TI-2 compares text, and a truncation would produce false mismatches. But test against a metes-and-bounds commitment plus two nested lists_
- **004 title-commitment** — Defer chain_of_title (~5 sites, serves only TI-6/FR-2)? _Rec: ship schedule_b_items first — it unblocks TI-3, TI-4 and CR-11; chain_of_title serves two AI-surface rules_
- **005 credit-report** — Three nested lists (~15 plumbing sites) — ship all now or phase? _Rec: all three — CR-5/CR-6/CR-11 are otherwise dead, and both extra lists are small (0-5 items), so the token cost is minor_
- **005 credit-report** — SSN storage vs ID-2's exact match _Rec: raw + snapshot hash — a last-4 mask defeats the 'differs in the first five digits' case ID-2 exists to catch_
- **005 credit-report** — Token ceiling on a large report _Rec: test against a real 30-page tri-merge before committing; 20+ tradelines x 14 fields plus two more lists is the largest output in the set_
- **006 appraisal** — UAD 3.6 cutover (~Nov 2026) — build for 2.6 now, or design both? _Rec: version-agnostic schema with prompt branching — the field NAMES are stable enough; it is the LOCATIONS and vocabularies that move_
- **009 condo-questionnaire** — The condo master policy is its own document type ('Master Insurance Policy for Condominium') _Rec: CONFIRM before relying on them — if IH-7 reads the policy document, the authoritative source is elsewhere and these are a cross-check_
- **010 aus-findings** — Multiple submissions in one file (2-5 DU runs are common) _Rec: separate documents — each is a distinct PDF, and a list would triple the nesting cost_
- **011 homeowner-s-insurance** — forms_and_endorsements as a nested list vs flattened string. _Rec: (a) — the list is cheap (few items) and is the durable home for the disambiguator the standard was written around._
- **011 homeowner-s-insurance** — Mortgagee as flat vs nested. Kept flat (mortgagee_name + _raw + _count) on the assumption of 1–2 lienholders. _Rec: revisit as a list only if a second-lien scenario needs each entry addressed individually._
- **012 prior-closing-disclosure-final-cd-from-purchase** — One combined line-item list vs two (loan costs A–D and other costs E–J). Combined here with a section discriminator. _Rec: keep combined — DC-4 needs every fee regardless of section, and one list is one plumbing site._
- **012 prior-closing-disclosure-final-cd-from-purchase** — Second nested list for the cash-to-close summary? AS-3 could benefit from the page-3 transaction-summary lines (deposit, adjustments, payoffs) rather than flattened totals. _Rec: start with flattened totals; add a transaction_summary_lines list only if AS-3's author needs line-level detail._
- **013 1040-individual-federal-tax-returns** — More than one nested list. Section 5 budgets one nested list/document, but IN-12 reads K-1 ordinary income/distributions and IN-14/OC-3 read Schedule E rental figures — genuinely repeating and rule-demanded. _Rec: (b) — the rules read all three; the plumbing already exists. Flag the multi-property / multi-K-1 count as the token-budget risk._
- **013 1040-individual-federal-tax-returns** — Schedule C add-back set. IN-12's methodology determines exactly which add-backs count. Included depreciation/depletion/amortization/business-use-of-home as the common set. _Rec: confirm the authoritative list before build so the calculator floor is complete._
- **013 1040-individual-federal-tax-returns** — total_net_rental_income placement. It is a derived Schedule E roll-up, not a 1040 line. _Rec: keep the top-level signal so detection does not depend on nested-list plumbing being wired._
- **013 1040-individual-federal-tax-returns** — home_address masking. Standard sensitivity, but a real home address in the unmasked catch-all was the section 6 incident. Promoted as typed (done) — should it also be _PII_FIELDS-registered? _Rec: Priya decides._
- **014 drivers-license** — DOB masking vs comparison. ID-3 compares actual dates, so DOB must be registered pre_masked=false and compared via the snapshot match-hash — confirm the snapshot exposes a date-comparable hash (not just an opaque string) so date-format tolerance still works. _Rec: register raw + rely on the normalized snapshot date for the compare, hash for storage/display._
- **014 drivers-license** — Name components vs raw only. ID-1 could split full_name_raw at runtime instead of storing components. _Rec: store both — components make the canonicalization deterministic and the raw line keeps a bad split auditable; cost is four cheap str fields._
- **015 written-voe** — gross_earnings_history shape. Item count is small and stable (~3 year-rows). _Rec: flat-row._
- **015 written-voe** — military_pay_components. Separate nested list vs drop. Rare outside VA files; the one-list budget is spent on earnings history. _Rec: drop now, revisit for VA-heavy pipelines._
- **015 written-voe** — employee_number may be an SSN. _Rec: treat as raw PII and confirm masking policy with Priya before go-live._
- **015 written-voe** — employment_status is absent from the catalog. It is a derived disambiguator IN-4 relies on to order present vs previous blocks. _Rec: include as a typed field (present/former)._
- **016 hoa-dues-statement-with-contact-info** — CO-4 reserve percentage is not on this document. CO-4's required docs are the HOA budget and condo questionnaire; a dues statement rarely prints a reserve %. _Rec: route CO-4 to the HOA-budget schema; keep the field here only opportunistically._
- **016 hoa-dues-statement-with-contact-info** — special_assessment_items shape/count. Item count is uncertain (0–3 typical, occasionally more). _Rec: flat-row nested (preserves per-item description/duration for future warrantability rules)._
- **016 hoa-dues-statement-with-contact-info** — owner_account_number_masked registration. New PII key distinct from account_number_masked. _Rec: register as pre_masked=true; confirm HOAs actually mask it (some print it in full → would need raw handling)._
- **017 investment-account-statements** — security_positions necessity/shape — AS-3/AS-4 operate on aggregate values; position detail only matters if reserves are discounted per-security (restricted vs marketable) _Rec: keep as flat-row for now, but confirm with Priya whether any rule discounts by position class before paying the ~5-site plumbing cost_
- **017 investment-account-statements** — liquidation_restrictions flattening — catalog type is string[] _Rec: single str — AS-11 needs to detect presence/terms, not enumerate items; keeps the one-list budget for security_positions_
- **019 letter-of-explanation-credit** — borrower_signature_present is not a standalone catalog field — the catalog carries only signature[] objects; LO-2's DET path needs a scalar boolean the engine can test _Rec: the flattened scalar + borrower_signature_date; revisit only if a rule must name each signer_
- **020 mortgage-statement** — property_address PII vs matchability — it is sensitive but RE-1 needs it in plaintext for tolerant matching; masking would break the rule _Rec: keep typed and unmasked, do not register in _PII_FIELDS; confirm this is an acceptable PII posture for a property address_
- **021 rental-agreements-lease-agreements** — Nested list — lease_amendments_or_addenda is CORE and can override monthly_rent/term _Rec: no list for V1 — items are few/rare and the catch-all preserves the raw addendum; item count uncertain (usually 0-2), flag for Priya_
- **021 rental-agreements-lease-agreements** — Signature capture — flatten to landlord_signature_date/tenant_signature_date vs a signatures nested list _Rec: flatten — exactly two parties_
- **021 rental-agreements-lease-agreements** — Third-party tenant PII — tenant_or_lessee_name (+ address via the raw string) is a non-borrower's PII at standard sensitivity _Rec: no _PII_FIELDS registration; confirm with Priya whether tenant identity should be masked_
- **022 retiree-account-statement** — PII field name — plan_or_account_number_masked vs the registered account_number_masked _Rec: register the new name in _PII_FIELDS (pre_masked=true) rather than renaming, to avoid breaking the existing extractor's field_
- **025 gift-letter** — donor_address / donor_phone PII. _Rec: register donor_address — a real address unmasked in the catch-all is the exact failure; leave donor_phone unregistered_
- **026 mortgage-payoff** — Which nested list. payoff_conditions_orlimitations (CORE string[]) vs other_fees_or_advances (object[]). _Rec: nest payoff_conditions_orlimitations (flat string rows — CORE, processor/TI-3 relevant); leave other_fees_or_advances to the catch-all since no rule reads line-item fees and total_payoff_amount is the consumed figure_
- **026 mortgage-payoff** — wire_or_remittance_instructions handling. _Rec: (a) flattened str + redactor now (one payoff = one instruction block); escalate to (b) only if a rule must read the routing/account individually_
- **027 property-tax-bill-subject** — Homestead/exemptions as a DT-4 disambiguator. Loss of a seller's homestead exemption on a new purchase raises the effective tax, which is exactly DT-4's under-estimate concern. _Rec: revisit (b) with the domain expert — currently left to catch-all to respect the one-list budget_
- **029 1099-form** — Nest box_values or not? IN-13 needs only the primary income amount + distribution code (both typed) _Rec: (a) now; revisit if a rule needs withholding or a non-primary box, since the catch-all is discarded at the snapshot boundary_
- **031 court-order-documents** — Flatten primary support vs nest support_awards — an order can grant alimony AND child support with different amounts/end dates _Rec: (b) — IN-13 must see every continuing stream and its end date_
- **031 court-order-documents** — Rule-floor gap registration — support_awards.end_date and .frequency are absent from the catalog _Rec: confirm they are added as first-class extracted values (via the nested list) so IN-13 is not dead on arrival_
- **033 emd-withdrawal-proof** — Wire trace as PII — wire_ach_trace_number is restricted _Rec: confirm registration (pre_masked false) so it is masked at the snapshot rather than stored raw in the catch-all_
- **035 k-1-schedule-1065-1120s** — k1_box_items shape — flat-row vs per-field-wrapped _Rec: flat-row, comfortably under the ceiling (box counts are moderate-to-many with lettered sub-codes)_
- **036 master-insurance-policy-for-condominium** — Merging three object[] into one building_limits list — the catalog separates building limits, property deductibles, and wind/hail deductibles _Rec: (a) one per-building row; flag (b) if a real blanket policy does not map cleanly per building_
- **037 profit-and-loss-statement-balance-sheet** — One combined nested list vs several — the document naturally has ~9 repeating groups _Rec: (a) one flat financial_line_items — stays within the one-list budget and keeps IN-12 add-backs addressable_
- **037 profit-and-loss-statement-balance-sheet** — Depreciation add-backs as scalars — IN-12 depends on depreciation/amortization add-backs _Rec: (a) leave them as tagged rows; promote a scalar only if the calculator wants a single number_
- **038 resident-alien-card** — A-number masking policy — register uscis_number_or_a_number raw (snapshot masks) or have the extractor pre-mask to last-3? _Rec: register raw (pre_masked false), consistent with recipient_tin; snapshot handles masking + match-hash_
- **038 resident-alien-card** — Conditional-resident detection — ID-8 cares whether the card is conditional (CR category, 2-year validity) _Rec: (a) derive downstream from category_code + card_expiration_date_
- **039 social-security-award-letter** — Deductions as a nested list vs catch-all — medicare_or_other_deductions is small and only supports gross→net reconciliation _Rec: (b) drop to catch-all unless a rule needs itemized deductions_
- **040 1040-personal-tax-transcripts** — Which object[] is the nested list — return_line_items, wages_and_income_summary, and account_adjustments are all repeating _Rec: (a) one flat return_line_items; a Wage & Income transcript may warrant its own list if a rule reads per-payer income_
- **041 1065-partnership-tax-transcripts** — Which repeating list — schedule_k_items (distributive shares to K-1) vs deduction_line_items vs balance-sheet lines _Rec: schedule_k_items, since partner qualifying income derives from Schedule K; revisit if a rule reads deductions or the balance sheet_
- **041 1065-partnership-tax-transcripts** — Partner-level attribution — the borrower's usable income is their ownership share; confirm whether the matching K-1 supplies the share or this transcript must carry per-partner detail _Rec: confirm with the rule author whether per-partner detail is needed on this transcript_
- **042 1120-corporate-tax-transcripts** — Which repeating list — officer_compensation (owner W-2 income) vs deduction_line_items vs balance-sheet lines _Rec: officer compensation, since it is the owner's direct income; revisit if a rule reads corporate cash flow or the balance sheet_
- **043 4506-t-request-for-transcript-of-tax-returns** — Years as a list vs flat string — years_or_periods_requested is date[] but <=4 tiny values _Rec: (a) flatten to one verbatim string — avoids ~5 sites of plumbing_
- **043 4506-t-request-for-transcript-of-tax-returns** — Raw-SSN handling — this form is a rare place a full unmasked SSN appears; confirm registration as raw PII (pre_masked false) so the snapshot masks it; verify the catch-all cannot receive it _Rec: register raw (snapshot masks + hashes), consistent with recipient_tin_
- **045 alimony-income-verification** — payment_history shape and length. Item count is uncertain (a verification letter may show 3 months or 24) _Rec: flat-row; revisit to per-field-wrapped only if a rule must attribute each row's source individually_
- **046 application-loe** — Nested-list choice. Three catalog fields repeat: event_chronology (object[]), supporting_document_list (string[]), relevant_amounts_accounts_or_addresses (object[]). Budget is one nested list _Rec: event_chronology as the nested list, supporting_document_list as a light flat str[], and defer relevant_amounts_accounts_or_addresses to the catch-all until a rule needs it (then it needs its own redactor for PII)_
- **047 appraisal-payment** — check_number_or_transaction_reference PII treatment — restricted but not a named _PII_FIELDS key. _Rec: register, since it can be tied back to a bank account_
- **047 appraisal-payment** — Nested list vs single transaction — assumed one payment per receipt (no nested list). _Rec: assume one payment per receipt; flag if combined/split-payment receipts prove common_
- **048 authorization-to-run-credit** — No rule consumes this document today (Tier 3, rule_count 0), yet it carries the highest-sensitivity PII in this batch (full SSN + DOB). Even absent a rule, these MUST be typed + registered so they are masked. _Rec: register now regardless of rule status — the PII-protection reason stands alone_
- **048 authorization-to-run-credit** — Flatten-to-two vs nested borrowers[]. _Rec: flatten to two borrowers; revisit to a nested list only if 3+ authorizers on one form prove common_
- **048 authorization-to-run-credit** — authorized_bureaus_or_report_types as flat str[] vs nested. _Rec: flat str[] (a handful of bureau names — light, no per-item source needed)_
- **049 bank-deposit-slip** — check_items PII — check-item rows carry check numbers and drawer names. _Rec: build the nested record with a redactor rather than leaving check numbers to the catch-all; confirm the redaction approach_
- **050 bankruptcy-discharge-notice** — case_number PII treatment — confidential, keys a public record. _Rec: keep as typed identity, unmasked (it is needed for public-record matching and is not an account/SSN), but flag for the privacy reviewer_
- **051 bankruptcy-filing** — Nested-list candidate — prior_bankruptcy_cases is the strongest repeating structure with mortgage relevance (multiple/serial bankruptcies affect eligibility). _Rec: defer until a multiple-bankruptcy rule exists; flag then_
- **051 bankruptcy-filing** — business_names_and_eins PII — if promoted, EINs need masking (registered kind employer_ein). _Rec: keep deferred; if promoted, build with a redactor, never catch-all_
- **051 bankruptcy-filing** — case_number PII treatment — same question as #050 (confidential, keys a public record). _Rec: typed identity, unmasked, but flag for the privacy reviewer_
- **052 birth-certificate** — PII registration scope — date_of_birth, certificate_or_state_file_number, local_file_or_registration_number are all high-sensitivity and unregistered. _Rec: register all three regardless of rule status — the PII-protection reason stands alone_
- **053 boarder-proof-of-residency** — supporting_documents shape — flat-row nested list of strings vs flatten to a single joined string in typed_core? _Rec: flat-row list, but acceptable to flatten if plumbing cost outweighs the value given zero rules_
- **053 boarder-proof-of-residency** — PII scope for home addresses — should a boarder's residence_address be registered/masked? _Rec: flag for the domain expert; standard sensitivity in the catalog suggests no, but it is a private residence_
- **054 boarder-rental-payments** — Two candidate lists — payment_history (chosen) vs supporting_bank_statements_or_checks. Budget is one list per document. _Rec: keep payment_history as the nested list; flatten supporting evidence to a bare string list only if a consumer appears_
- **055 borrower-authorization-and-certification** — Signatures flattened vs nested — flattened to present/date for up to two borrowers. _Rec: flatten; revisit as a nested list only if a rule must address more than two signers individually_
- **057 building-permits** — Which inspection list — inspection_results (chosen) vs required_inspections. They overlap; results carry outcomes. _Rec: keep inspection_results; fold 'required' into it if a jurisdiction lists both. Flag if a rule ever needs the required-vs-performed gap_
- **059 business-federal-tax-returns** — Which nested list — owner_partner_shareholder_records (chosen, for income attribution) vs expense_line_items (for add-back detail) vs schedule_k_and_k1_summary. Only one fits the budget with zero rules. _Rec: keep owner records (attributes income to the borrower); revisit when a self-employed-income rule specifies exactly which schedule it reads_
- **059 business-federal-tax-returns** — List shape — per-field-wrapped chosen on the assumption of few owners. If a return can carry many shareholders, switch to flat-row to protect the 16,384-token ceiling. _Rec: flag item-count uncertainty; default to per-field-wrapped for typical 1-5 owners_
- **059 business-federal-tax-returns** — Add-backs as scalars vs list — depreciation/depletion/guaranteed-payments are kept as scalar top-line figures rather than in a list. _Rec: acceptable for zero rules; a cash-flow rule may later want the full expense list_
- **060 cancelled-checks-evidencing-receipt-of-note-income** — One check vs a bundle — packets often bundle multiple cancelled checks. _Rec: keep the schema single-check and rely on the splitter to emit one extraction per check; only introduce a nested checks[] list if the pipeline cannot split and a rule needs all checks in one record. Flag the splitter behavior with the domain expert_
- **061 certificate-of-eligibility** — prior_va_loan_or_entitlement_charges shape. Item count is small but unbounded. _Rec: flat-row — a processor computing remaining entitlement needs it structured, and cost is low_
- **061 certificate-of-eligibility** — va_file_or_loan_number PII class. Confidential but not SSN-class. Register in _PII_FIELDS or leave as a plain typed field? _Rec: plain typed field, flagged_
- **062 consent-to-use-electronic-records-and-signatures** — Joint consent modeling. Two consumers with two emails/phones — flat pairing may misalign which email belongs to which name. _Rec: keep raw lists as str and flag alignment as a known limitation rather than nesting_
- **063 credit-card-authorization** — Two-in-one authorization + receipt. Some forms carry both the authorization (top) and the settled charge (bottom). _Rec: keep both fields; flag only if receipts routinely arrive separately_
- **063 credit-card-authorization** — expiration_month_year retention. Card expiry is restricted data with little downstream use once the charge clears. _Rec: register and keep — dropping to catch-all would store it unmasked, which is worse_
- **064 custom** — Should 'Custom' have a schema at all? It is a fallback for unclassified documents. _Rec: (a), because even a generic identity header lets a processor attach the document to a borrower/loan_
- **064 custom** — unmapped_key_value_pairs and PII. A key/value passthrough can capture SSNs, account numbers, addresses unmasked. _Rec: require a redactor sweep over this list before it is persisted, or cap it to non-sensitive labels. Must be resolved before Custom is trusted_
- **065 disability-award-letter** — deductions_or_offsets shape/count. Usually 0-3 offsets. _Rec: flat-row — needed to explain the gross-to-net gap for gross-up_
- **065 disability-award-letter** — Continuance as structured vs prose. The 3-year continuance decision hinges on this. _Rec: keep prose now; tags/rules judge continuance — a schema field should not_
- **066 divorce-decree** — Second and third nested lists. The domain arguably needs three repeating structures (support, debt, property); the standard budgets one per document absent rules. _Rec: (b) — support_obligations plus one merged asset/debt-allocation list, since the existing extractor already carries two lists and debt allocation drives DTI_
- **066 divorce-decree** — case_number PII class. Confidential but not SSN-class. Register in _PII_FIELDS or keep as a plain typed field? _Rec: plain typed field, flagged_
- **067 earnest-money-emd-receipt** — wire_or_ach_trace_number PII class. Restricted but not last-4-masked. _Rec: keep typed, flag — a bare trace number is lower-risk than an account number but should not sit in the unmasked catch-all_
- **068 evidence-of-payment** — check_reference_or_trace_number PII class. Restricted but not last-4-masked. _Rec: keep typed, flag_
- **069 financial-statements** — Which one nested list? asset_line_items vs liability_line_items — both are catalog CORE object[]. _Rec: (a) — assets drive reserve/liquidity use; revisit if an undisclosed-debt rule lands that must read individual liabilities_
- **070 foster-care-verification** — taxable_status vs reimbursement_vs_income_components — the taxable/reimbursement split can be a single enum-degraded string or a nested breakdown. _Rec: keep the flat taxable_status; only nest reimbursement_vs_income_components if a rule must read component amounts_
- **070 foster-care-verification** — Child data minimization — the catalog has no child-identifier field, which is correct. Confirm the prompt hard-blocks child PII from the catch-all, since the catch-all is stored unmasked. _Rec: confirm the prompt hard-blocks the foster child's name, DOB, and case-child identifiers from every field including the catch-all_
- **071 government-issued-id** — document_number masking — extract already-masked (map to existing id_number_masked, pre_masked true) or extract raw and let the snapshot mask (pre_masked false)? _Rec: pre-mask at extraction to match id_number_masked and never store the full number_
- **071 government-issued-id** — full_legal_name masking — names are normally unmasked, but this is a highly-sensitive identity document _Rec: keep typed and unmasked but flag for the PII reviewer_
- **071 government-issued-id** — residential_address — promote to a registered PII field, or accept as standard? _Rec: keep typed (out of the unmasked catch-all) and flag pre_masked false for review_
- **072 hoa-certification** — Which one nested list? special_assessments vs pending_litigation — both are CORE-adjacent object[] warrantability signals _Rec: nest special_assessments (amounts a processor sums) and carry pending-litigation as a flat presence flag; revisit if a litigation rule needs case-level detail_
- **073 homeowner-s-insurance-quote** — Which one nested list? mortgagee_or_lienholder_entries vs deductibles — both CORE object[] _Rec: nest mortgagee_entries (needed to verify the lender clause) and add a flat wind_hail_deductible / all_perils_deductible pair if a rule needs deductibles, rather than a second list_
- **073 homeowner-s-insurance-quote** — policy_number masking — pre-mask at extraction vs raw-then-snapshot _Rec: pre-mask (restricted)_
- **075 letter-of-explanation-asset** — Chronology vs parallel arrays — amounts_involved (money[]) and transaction_or_valuation_dates (date[]) could be kept as flat scalar lists instead of one object list _Rec: one transfer_path_or_chronology list so each amount stays bound to its date/step; revisit only if letters routinely give a single amount+date (then flatten to two scalars)_
- **076 letter-of-explanation-child-care** — dependents_or_children — count vs list vs omit _Rec: flat dependent_count int; the number of children covered is the only fact a processor needs_
- **077 letter-of-explanation-income** — supporting_documents shape. _Rec: (a) flat str — usually a short phrase, no consumer; leave until a rule needs to match named attachments_
- **077 letter-of-explanation-income** — income_amounts_orvariance as a list. _Rec: leave to the catch-all; flag for review if underwriting later wants itemized before/after figures typed_
- **078 letter-of-explanation-misc** — facts_and_chronology typed vs catch-all. _Rec: catch-all — no consumer today; flag if a future rule needs a typed timeline_
- **078 letter-of-explanation-misc** — supporting_documents shape. _Rec: flat str; escalate to a list only if attachment-matching becomes a rule_
- **079 letter-of-explanation-property** — facts_and_chronology / transfer dates typed vs catch-all. _Rec: catch-all — no consumer; flag if occupancy/flip rules later need a typed timeline_
- **079 letter-of-explanation-property** — Subject vs non-subject property. There is no subject_property_indicator in this catalog (unlike 084). Should we add one so occupancy logic knows which property the letter explains? _Rec: add as [absent from catalog] if occupancy rules materialize_
- **079 letter-of-explanation-property** — property_address when multiple properties are named. _Rec: kept as a single flattened address; revisit as a list only if a letter routinely covers several properties_
- **080 life-insurance-policy** — policy_number_masked registration. _Rec: add to _PII_FIELDS (pre_masked true) before this schema ships, or the value lands unmasked in the catch-all_
- **080 life-insurance-policy** — Owner/insured cardinality. _Rec: flattened to two scalars each; revisit as person[] only if a rule must address a third owner/insured_
- **081 military-leave-and-earning-statement-les** — One list or three. entitlements, deductions, allotments are three parallel object[]s. _Rec: (a) one entitlements list now — the sole income-calc consumer; escalate to (b) if a rule needs typed deductions/allotments_
- **081 military-leave-and-earning-statement-les** — Tax objects flattened to str. federal/fica/state_tax_data are objects degraded to strings. _Rec: keep flattened; if a withholding rule ever needs the components, they'd need sub-field promotion_
- **082 miscellaneous-document** — account_case_or_reference_number PII registration. _Rec: register in _PII_FIELDS (pre_masked false — the model cannot reliably pre-mask an unknown identifier; the snapshot masks raw). This is the highest-risk unmasked-PII path in the whole packet because the doc type is unknown_
- **082 miscellaneous-document** — How much to type at all. A misc document arguably needs only identity + key_value_pairs. _Rec: kept for reclassification; confirm they earn their tokens or drop to catch-all_
- **083 mortgage-loan-origination-agreement** — origination_and_broker_fee_items vs the comp scalars — the list may double-count borrower_paid_compensation. _Rec: keep both but flag the overlap for the reshaper; confirm whether a fee-reconciliation rule is planned before investing the ~5 sites of list plumbing_
- **083 mortgage-loan-origination-agreement** — state_license_numbers typed vs catch-all. _Rec: catch-all now; promote to a second flat list only if state-licensing validation becomes a rule_
- **084 other-property-note** — DTI consumer — monthly_principal_and_interest is typed on the expectation of a future DTI/liabilities rule. _Rec: confirm the intended snapshot_path and whether taxes/insurance (full PITI) are needed rather than P&I alone_
- **086 property-profile-non-subject** — Sales/transfer history and lien summary as nested lists — both genuinely repeat and would be useful to a future prior-transfer or existing-lien rule. _Rec: defer both to catch-all — no consumer exists, and building bespoke plumbing for a Tier-3 non-subject doc is premature_
- **087 property-profile-subject** — Sales/transfer & lien nested lists — same as 086. _Rec: defer to catch-all until a consumer exists_
- **088 property-survey** — Which findings list gets the one nested-list slot: encroachments vs easements? Both repeat and both matter for title. _Rec: a single merged survey_exceptions list if a survey-findings rule is ever built; encroachments-only for now_
- **089 property-tax-bill-non-subject** — Flatten installments vs nested list. _Rec: (a) nested — avoids losing a 4-installment bill, and the list is cheap_
- **092 seller-signature-authority** — Flatten signatures_and_notary vs nested list — there are usually <=2 signers plus a notary. _Rec: (a) nested — the notary block is the proof the authority is itself validly executed, and the list is cheap_
- **093 social-security-administration-ssa-89** — DOB + SSN together on one low-value document — two highly-restricted PII elements with no rule consuming them. _Rec: (a) extract and register both — identity matching may become a future rule and catch-all storage is unmasked/unsafe_
- **095 statement-of-account** — transactions_or_activity shape and inclusion. Item count spans a few (mortgage statement) to dozens (credit card). _Rec: flat-row list — token-safe and reusable_
- **096 termite-completion** — Which repeating list to keep. The catalog splits completed work across treatment_or_repair_items_completed, treatment_method_and_chemical, and contractor_repair_details. _Rec: one consolidated flat-row list; confirm this consolidation is acceptable vs three separate lists_
- **096 termite-completion** — areas_or_structures_treated flattened to str, joined into one string rather than a second list. _Rec: joined str, since it is short and the item list already carries per-item area; flag if a queryable structure list is wanted_
- **097 termite-report** — Consolidating three finding lists into one. _Rec: a single findings flat-row list with a category column; confirm this is acceptable vs preserving the catalog's three separate object[] fields_
- **097 termite-report** — obstructions_and_inaccessible_areas (CORE object[]) not nested. It genuinely repeats and is CORE (limits of inspection completeness), but a second nested list exceeds the one-list budget with no rule demanding it. _Rec: flatten to a joined str unless a completeness rule is planned_
- **098 transcripts-of-1099** — Masked-TIN registration. recipient_tin_masked and nested payer_tin_masked are masked variants not literally in the 7-field registry. _Rec: register the masked field names (pre_masked true); confirm the registry keys on exact field name_
- **099 trust-agreement** — Nested list for amendments. amendment_references determines which version of the trust governs — arguably the one structure worth nesting. _Rec: none now for a no-rule Tier-3 doc — flatten a count/latest-amendment date; revisit if a 'trust currency' rule is built_
- **099 trust-agreement** — More than two parties. Grantors/trustees/beneficiaries flattened to two + a count. Trusts can exceed two (multiple successor trustees, several beneficiaries). _Rec: flag when _count > 2 that the tail is in the catch-all; consider a person[] list only if a rule must address them individually_
- **100 trust-documents** — Which repeating list to keep. Chose authorized_signer_names_and_capacity (who may sign the mortgage) over property_or_asset_references. _Rec: authorized_signer_names_and_capacity is the higher-value list; if asset/property linkage is needed, flag whether a second list is warranted (exceeds the one-list budget)_
- **101 trust-federal-tax-returns** — Second/third nested list (deduction_line_items, K-1s, other-income) — the catalog offers three object[] structures. _Rec: keep only beneficiary_k1_records — it is the only one with a plausible future consumer (borrower distribution income); revisit if a trust-income recipe needs line-item deductions_
- **101 trust-federal-tax-returns** — EIN masking policy. _Rec: store raw — preserves K-1 join, snapshot masks; flagging rather than deciding_
- **104 verification-of-assets** — account_transactions — second nested list. The catalog offers a transactions object[] that would let a future large-deposit/NSF rule run (mirroring bank_statement.transactions). _Rec: keep only verified_accounts now — no rule consumes transactions yet, and two nested lists doubles the ~5-site plumbing cost; add when the first asset rule that needs transaction-level data is built_
- **105 verification-of-deposit** — loans_secured_by_or_held_at_institution — second nested list. The VOD's loan section can surface undisclosed debts or pledged assets (real mortgage value). _Rec: keep only deposit_accounts now — no rule consumes the loan section yet, and a second list is ~5 extra plumbing sites; flatten the presence signal into pledged_or_restricted_accounts for now and revisit when an undisclosed-debt rule exists_
- **106 verification-of-mortgage** — loan_number_masked registration + policy — needs adding to _PII_FIELDS (pre_masked=true). _Rec: confirm whether VOMs in practice arrive pre-masked or need extractor-side masking_
- **106 verification-of-mortgage** — late_payment_counts flattening — flattened to late_30/60/90 scalar ints assuming the fixed Fannie/Freddie 30/60/90 buckets. _Rec: if servicers report other buckets (120+, "worst rating"), the shape may need a fourth field; flag for a real-sample check_
- **107 verification-of-rent** — other_monthly_charges — second nested list. Utilities/parking/pet charges could matter for total housing cost. _Rec: (a) keep only rent_payment_history now — no rule consumes ancillary charges yet, and monthly_rent + subsidy_or_concession carry the core figure_
- **108 work-visa-ead-card** — Seven new _PII_FIELDS registrations. This one document nearly triples the current registry. _Rec: register all seven as listed; confirm the masking policy per field (last-4 vs raw+snapshot) with the security owner before build — flagging, not deciding_
- **108 work-visa-ead-card** — date_of_birth as PII + identity. DOB is highly_restricted but is the key disambiguator between same-named individuals. _Rec: keep typed, store raw, let the snapshot mask; do not drop it to the catch-all where it would be stored unmasked_
