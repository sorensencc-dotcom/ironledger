-- IronLedger Phase 3: append-only compile journal and recovery state tracking.

CREATE TABLE compile_journal (
    seq            INTEGER PRIMARY KEY,          -- explicit monotonic allocation, not AUTOINCREMENT
    compile_run_id TEXT NOT NULL
        REFERENCES compile_runs (compile_run_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    state          TEXT NOT NULL CHECK (state IN (
        'started', 'bean_checked', 'replaced', 'succeeded', 'failed', 'recovered', 'refused'
    )),
    ts_utc         TEXT NOT NULL CHECK (ts_utc GLOB '????-??-??T??:??:??*Z'),
    detail         TEXT NOT NULL DEFAULT '',
    CHECK (seq >= 1)
) STRICT;

CREATE INDEX idx_compile_journal_run ON compile_journal (compile_run_id);

CREATE TRIGGER compile_journal_no_update
BEFORE UPDATE ON compile_journal
BEGIN
    SELECT RAISE(ABORT, 'compile_journal is append-only: UPDATE is forbidden');
END;

CREATE TRIGGER compile_journal_no_delete
BEFORE DELETE ON compile_journal
BEGIN
    SELECT RAISE(ABORT, 'compile_journal is append-only: DELETE is forbidden');
END;
