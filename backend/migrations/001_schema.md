# Schema v2

SQLAlchemy metadata creates users, audits, workloads, candidates, experiments, telemetry, index_plans and index_operations on first startup. Workload/candidate natural names are UNIQUE; experiment snapshots are immutable JSON. Foreign keys prevent orphan references. Index trials affect only the dedicated telemetry table, under MySQL GET_LOCK, and drop only their own temporary index (`trial_ev_<experiment_id>`) after each execution; resident or externally created indexes are recorded as baseline and never removed by a trial.

## Index publishing (v2)

- `index_plans` records a publishable plan copied from a completed, result-equal experiment snapshot. Plan columns are frozen at creation, so later candidate edits do not change it. `index_name` is the resident index name on `telemetry`; `status` is one of pending/active/superseded/rolled_back/conflict/failed. `previous_plan_id` records which plan was active at publish time so rollback can restore it.
- `index_operations` records every publish/rollback attempt with actor, expected active plan, evidence and status. Retrying an operation reuses the row and the same queue item; execution is idempotent and adopts an already-built index instead of creating a duplicate.
- Publishing and rollback share the `index_trial_serial` GET_LOCK with trials. Before registration both re-check that the active plan has not changed; if it has, the operation is marked `conflict` and the database index field is left untouched.
- Success is only reported after `information_schema.statistics` confirms the index exists with the exact expected column order and is a non-unique BTREE. Same-name indexes with a different definition are rejected and preserved for manual review.
- Worker startup requeues pending/running operations and queued/running experiments; a crash after CREATE INDEX but before registration is recovered by adopting the built index.

Upgrading an existing v1 database requires creating the two new tables (metadata `create_all` does this on startup); existing experiments keep their snapshots and can be used to create plans.
