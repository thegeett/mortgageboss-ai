> **✅ RESOLVED by LP-442.** All 72 remaining uncataloged spec types are now reconciled: **4 merges**
> (`aba`→`affiliated_business_disclosure`, `consent_…`→`e_consent_disclosure`,
> `k_1_schedule_1065_1120s`→`k1_statement`, `mortgage_payoff`→`payoff_statement`), **1 split**
> (`alimony_income_verification`→`alimony_income` + `child_support_income`), **67 new catalog types +
> indicators**, and **1 retire** (`borrower_authorization`, decision 2). **Every spec `document_type` now
> resolves to a catalog entry — 109/109.** The full reconciliation table, the verified payoff target, the 17
> deliberate non-merges, and every indicator written are in [`../tickets/LP-442.md`](../tickets/LP-442.md) and
> ADR-347. The table below is the LP-441 snapshot that motivated the follow-up — kept for provenance.

# Vocabulary mapping — the 82 schema `document_type`s not in the catalog (LP-441)

The schema-spec vocabulary diverged from the catalog/classifier vocabulary. This maps every one of the
82 uncataloged spec `document_type`s to a catalog key, or marks it NO MATCH. **Only UNAMBIGUOUS renames
were applied** (a wrong one silently breaks routing — the exact failure that motivated this). UNSURE and
NO MATCH are reported for a follow-up taxonomy decision (add a catalog entry + a classifier indicator,
or confirm the candidate).

- **APPLIED (catalog-aligned): 10** · **APPLIED (validity/form_*): 4** · **UNSURE: 21** · **NO MATCH: rest**

| spec document_type | result | catalog key / candidate |
|---|---|---|
| 1040_personal_tax_transcripts | ✅ VALIDITY (still uncataloged) | form_1040_personal_tax_transcripts |
| 1065_partnership_tax_transcripts | ✅ VALIDITY (still uncataloged) | form_1065_partnership_tax_transcripts |
| 1120_corporate_tax_transcripts | ✅ VALIDITY (still uncataloged) | form_1120_corporate_tax_transcripts |
| 4506_t_request_for_transcript_of_tax_returns | ✅ VALIDITY (still uncataloged) | form_4506t_request_for_transcript |
| aba | ⚠️ UNSURE (not applied) | affiliated_business_disclosure (AfBA) |
| alimony_income_verification | ⚠️ UNSURE (not applied) | alimony_income / child_support_income (the spec covers BOTH support types) |
| application_1003 | ✅ RENAMED | uniform_residential_loan_application |
| application_loe | — NO MATCH | (needs a new catalog entry + indicator) |
| appraisal_payment | — NO MATCH | (needs a new catalog entry + indicator) |
| aus_findings | — NO MATCH | (needs a new catalog entry + indicator) |
| authorization_to_run_credit | ⚠️ UNSURE (not applied) | borrower_authorization (a credit-pull authorization — but see below) |
| bank_deposit_slip | — NO MATCH | (needs a new catalog entry + indicator) |
| bankruptcy_discharge_notice | ✅ RENAMED | bankruptcy_discharge |
| bankruptcy_filing | — NO MATCH | (needs a new catalog entry + indicator) |
| boarder_proof_of_residency | — NO MATCH | (needs a new catalog entry + indicator) |
| boarder_rental_payments | — NO MATCH | (needs a new catalog entry + indicator) |
| borrower_authorization_and_certification | ⚠️ UNSURE (not applied) | borrower_authorization (both this and authorization_to_run_credit claim it — collision) |
| borrower_s_authorization_for_counseling | — NO MATCH | (needs a new catalog entry + indicator) |
| building_permits | — NO MATCH | (needs a new catalog entry + indicator) |
| business_existence_verification_cpa_ltr_bus_lic | — NO MATCH | (needs a new catalog entry + indicator) |
| business_federal_tax_returns | ✅ RENAMED | business_tax_return |
| business_license | — NO MATCH | (needs a new catalog entry + indicator) |
| cancelled_checks_evidencing_receipt_of_note_income | — NO MATCH | (needs a new catalog entry + indicator) |
| certificate_of_eligibility | — NO MATCH | (needs a new catalog entry + indicator) |
| consent_to_use_electronic_records_and_signatures | ⚠️ UNSURE (not applied) | e_consent_disclosure |
| court_order_documents | — NO MATCH | (needs a new catalog entry + indicator) |
| cpa_letter | — NO MATCH | (needs a new catalog entry + indicator) |
| credit_card_authorization | — NO MATCH | (needs a new catalog entry + indicator) |
| custom | — NO MATCH | (needs a new catalog entry + indicator) |
| disability_award_letter | ⚠️ UNSURE (not applied) | disability_income_letter (award letter vs income letter) |
| earnest_money_emd_receipt | ✅ RENAMED | earnest_money_receipt |
| emd_withdrawal_proof | — NO MATCH | (needs a new catalog entry + indicator) |
| evidence_of_payment | — NO MATCH | (needs a new catalog entry + indicator) |
| financial_statements | — NO MATCH | (needs a new catalog entry + indicator) |
| flood_insurance | ✅ RENAMED | flood_insurance_policy |
| form_1099 | ✅ RENAMED | 1099 |
| foster_care_verification | — NO MATCH | (needs a new catalog entry + indicator) |
| government_issued_id | ⚠️ UNSURE (not applied) | drivers_license / passport / military_id (a GENERIC id — no single match) |
| hoa_certification | — NO MATCH | (needs a new catalog entry + indicator) |
| homeowner_s_insurance_quote | — NO MATCH | (needs a new catalog entry + indicator) |
| ira_401k | — NO MATCH | (needs a new catalog entry + indicator) |
| k_1_schedule_1065_1120s | ⚠️ UNSURE (not applied) | k1_statement (the K-1 form) |
| k_1_shareholder_profit_and_loss_transcripts | ⚠️ UNSURE (not applied) | k1_statement / tax_transcript (a K-1 TRANSCRIPT) |
| letter_of_explanation_asset | — NO MATCH | (needs a new catalog entry + indicator) |
| letter_of_explanation_child_care | — NO MATCH | (needs a new catalog entry + indicator) |
| letter_of_explanation_income | — NO MATCH | (needs a new catalog entry + indicator) |
| letter_of_explanation_misc | — NO MATCH | (needs a new catalog entry + indicator) |
| letter_of_explanation_property | — NO MATCH | (needs a new catalog entry + indicator) |
| life_insurance_policy | ⚠️ UNSURE (not applied) | life_insurance_statement (a POLICY vs a periodic STATEMENT) |
| master_insurance_policy_for_condominium | — NO MATCH | (needs a new catalog entry + indicator) |
| military_leave_and_earning_statement_les | — NO MATCH | (needs a new catalog entry + indicator) |
| miscellaneous_document | — NO MATCH | (needs a new catalog entry + indicator) |
| mortgage_loan_origination_agreement | — NO MATCH | (needs a new catalog entry + indicator) |
| mortgage_payoff | ⚠️ UNSURE (not applied) | payoff_statement / debt_payoff_statement (two candidates) |
| other_property_note | — NO MATCH | (needs a new catalog entry + indicator) |
| prior_closing_disclosure_final_cd_from_purchase | ⚠️ UNSURE (not applied) | closing_disclosure (a PRIOR CD vs the current-loan CD?) |
| proof_of_occupancy | — NO MATCH | (needs a new catalog entry + indicator) |
| property_profile_non_subject | — NO MATCH | (needs a new catalog entry + indicator) |
| property_profile_subject | — NO MATCH | (needs a new catalog entry + indicator) |
| property_survey | ✅ RENAMED | survey |
| property_tax_bill_non_subject | — NO MATCH | (needs a new catalog entry + indicator) |
| rental_agreements_lease_agreements | ✅ RENAMED | lease_agreement |
| resident_alien_card | ✅ RENAMED | permanent_resident_card |
| retirement_check | — NO MATCH | (needs a new catalog entry + indicator) |
| retirement_pension_award_letter | ⚠️ UNSURE (not applied) | retirement_income_letter / pension_statement (two candidates) |
| seller_signature_authority | — NO MATCH | (needs a new catalog entry + indicator) |
| social_security_administration_ssa_89 | — NO MATCH | (needs a new catalog entry + indicator) |
| social_security_card_copy | ✅ RENAMED | social_security_card |
| statement_of_account | — NO MATCH | (needs a new catalog entry + indicator) |
| subject_property_note | — NO MATCH | (needs a new catalog entry + indicator) |
| termite_completion | — NO MATCH | (needs a new catalog entry + indicator) |
| termite_report | — NO MATCH | (needs a new catalog entry + indicator) |
| transcripts_of_1099 | ⚠️ UNSURE (not applied) | tax_transcript (generic — collapse risk) |
| trust_agreement | — NO MATCH | (needs a new catalog entry + indicator) |
| trust_documents | — NO MATCH | (needs a new catalog entry + indicator) |
| trust_federal_tax_returns | — NO MATCH | (needs a new catalog entry + indicator) |
| unsecured_note | — NO MATCH | (needs a new catalog entry + indicator) |
| verbal_voe | ⚠️ UNSURE (not applied) | voe (the shipping VOE — but this is a VERBAL VOE, a distinct doc) |
| verification_of_assets | ⚠️ UNSURE (not applied) | verification_of_deposit (VOA vs VOD — related but distinct) |
| verification_of_mortgage | — NO MATCH | (needs a new catalog entry + indicator) |
| verification_of_rent | — NO MATCH | (needs a new catalog entry + indicator) |
| work_visa_ead_card | ⚠️ UNSURE (not applied) | visa_documentation (an EAD/work-auth card vs a visa) |
