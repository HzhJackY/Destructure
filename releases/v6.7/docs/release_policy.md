# Release policy

`releases/v6.4` is a frozen source snapshot. `releases/v6.5` is the only
directory changed for this delivery. Runtime financial evidence is intentionally
outside release folders and is resolved through `FIN_METRIC_DATA_HOME` or the
user-level DATA_HOME pointer.

Rollback means launching the previous release code against the same DATA_HOME.
Schema migrations are additive: v6.4 can still read its own assets, while a
rollback does not delete v6.5 certified knowledge or capture-plan records.
Older code will simply ignore v6.5-only tables. Do not copy, delete, or rewrite
DATA_HOME as part of a code rollback.
