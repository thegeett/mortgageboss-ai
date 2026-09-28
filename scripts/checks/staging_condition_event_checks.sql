-- Every CHECK constraint on condition_events.kind, with the values it allows (LP-909, LP-912).
--
-- WHY: LP-909 added the event kind round_reparse_requested with a swap that installed a
-- single-prefixed constraint beside LP-904's doubled one. A column's CHECKs are ANDed, so on
-- any database migrated through b6d1e93f57ac the new kind was rejected by the older CHECK, and
-- "Try again" on a stranded sheet could not be recorded. LP-912's migration repairs it by
-- dropping every spelling and installing one. This asks whether staging holds the repaired
-- shape.
--
-- HEALTHY: exactly ONE row, with admits_round_reparse_requested = true and
-- checks_on_column = 1. Its name is ck_condition_events_conditioneventkind (the model's name;
-- LP-912 installed it under that name, and LP-932 renames nothing on this column).
--
-- BROKEN (LP-909's shape): TWO rows. One is ck_condition_events_ck_condition_events_...
-- (doubled) without round_reparse_requested in allowed_values, and it wins, because both apply.
--
-- ALSO WRONG: zero rows (the column accepts any string), or one row with
-- admits_round_reparse_requested = false (a swap revoked the value).
--
-- Read-only: one SELECT over the system catalogs, which the readonly role can read. It names
-- no table in public, so it needs no readonly.* view. How to run it: docs/tickets/LP-912.md.
SELECT c.conname AS constraint_name,
       pg_get_constraintdef(c.oid) LIKE '%''round_reparse_requested''%'
           AS admits_round_reparse_requested,
       count(*) OVER () AS checks_on_column,
       array_to_string(
           ARRAY(
               SELECT m[1]
               FROM regexp_matches(pg_get_constraintdef(c.oid), '''([^'']+)''', 'g') AS m
               ORDER BY 1
           ),
           ', '
       ) AS allowed_values
FROM pg_catalog.pg_constraint c
JOIN pg_catalog.pg_class t ON t.oid = c.conrelid
JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
JOIN pg_catalog.pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
WHERE n.nspname = 'public'
  AND t.relname = 'condition_events'
  AND a.attname = 'kind'
  AND c.contype = 'c'
ORDER BY c.conname
