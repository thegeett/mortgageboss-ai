"""The extraction bench (dev-only) — runs real documents through the LIVE classification
and extraction pipeline and reports what the schemas actually capture. It MEASURES
coverage; it does not validate accuracy, does not persist anything, and changes nothing
about the system under test. See docs/tickets/extraction-bench.md."""
