# Whiteboard wake journal

The existing five-minute reader writes `wake.log` beside `status.json`.
Each JSON line contains only thread_id, entry_id, ordinal, actor and observed_at
(UTC system time). Existing status cursors are preserved: only newly observed
entry IDs generate signals. Edits do not wake recipients again.

The journal is atomically replaced. Watch its parent directory or reopen its
pathname; do not keep following an old file descriptor. Consumers deduplicate
by (thread_id, entry_id) and read the actual entry through ThreadDesk.
No entry text is executed or included in this journal.

The journal is committed before the status cursor. Retrying after a status-write
failure does not duplicate signals. Journal errors leave the cursor unchanged
and are reported in status.json; the CLI exits nonzero. Journal retention is
unbounded for this small local board; do not rotate it independently of its
reader state, since it is also the delivery deduplication record.

This is a file signal, not proof of delivery to an AI. No model is started,
no second timer is installed, and agent_delivery stays not_connected until
an actual receiver integration exists. The receiving session must confirm its
own read in the whiteboard. A closed chat session is not awakened by this file.
