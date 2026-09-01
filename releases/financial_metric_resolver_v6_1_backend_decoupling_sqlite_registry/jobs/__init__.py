"""Job orchestration package.

v6.1 defines persistent job state in SQLite. Controlled worker-pool execution is
intentionally deferred to the multi-PDF workflow release so UI migration does
not change parser semantics.
"""
