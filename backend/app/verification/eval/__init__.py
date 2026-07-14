"""The golden eval harness for the fact-tag verification architecture (LP-317).

The GO/NO-GO instrument: labeled fixtures with expected TAG-level and FINDING-level outcomes,
scored automatically against the real Stage-A → Stage-B → AS-1 pipeline. It proves AS-1 works in
BOTH directions (fires when it should, stays quiet when it should not), the LP-314a source-strength
distinction (verified / intrinsic / self_asserted / none), and calibration.

The harness EVALUATES; it never changes rule/tag logic. A failing case is a REPORTED regression, not
a cue to edit the pipeline (a revealed bug is a separate fix ticket).
"""
