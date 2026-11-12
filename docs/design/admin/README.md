# Admin panel mockups

Reference screens for tickets `LP-MB-Admin-01` to `LP-MB-Admin-05` (`docs/tickets/`). Drawn
2026-11-12 from the frontend's own tokens (Petrol palette, IBM Plex, 52px rail, 216px context column,
44px top bar, 28px controls, 5px / 8px radii), not from a running build, so spacing is approximate and
the component code (`components/ui/*`) wins where they differ.

Each screen is a static HTML file (`html/`) and a 2x PNG (`png/`). The amber box in the corner of a
screen is an implementation note, not UI. Names, counts and dates are sample data; values in
`[BRACKETS]` are placeholders nobody has decided.

| # | Screen | Ticket | What it shows |
|---|---|---|---|
| 01 | `01-admin-overview` | 02 | Roles held, one row per section, company settings card |
| 03 | `03-people` | 03 | People table, tabs People / Invitations, filters |
| 04 | `04-edit-person` | 03 | Side sheet: details, roles, history, Deactivate |
| 05 | `05-edit-loan-officer` | 03 | Same sheet with the Licensing block (NMLS, states) |
| 06 | `06-deactivate-reassign` | 03 + 05 | Confirm dialog; the file-reassign section appears once teams exist |
| 07 | `07-invite-dialog` | 04 | Email + roles; inline error copy in the note |
| 08 | `08-pending-invitations` | 04 | Pending list; copy-link card when there is no mail transport |
| 09 | `09-accept-invite` | 04 | Public page, valid and invalid link states |
| 10 | `10-lenders-existing` | — | As it is today; only the permission gate changes |
| 11 | `11-email` | — | Proposed page; `/admin/email` is a stub today, separate ticket |
| 12 | `12-audit-log` | 03 | Company audit log, filters, before → after column |
| 13 | `13-file-team-card` | 05 | Team card on a file, broker shop (A) and processing company (B) |
| 14 | `14-pipeline-my-files` | 05 | Assigned-to filter, Loan officer and Processors columns |

Screen 02 (overview as a non-owner admin) was dropped: owner and admin are identical in capability.

The editable source is a Claude design canvas, "MortgageBoss admin panel screens"; these files are an
export of it. Re-export after changing the canvas rather than editing the HTML here.
