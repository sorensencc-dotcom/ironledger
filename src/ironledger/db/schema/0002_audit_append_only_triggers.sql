-- IronLedger Phase 1 migration 0002: append-only triggers for audit_events.
--
-- Prevents UPDATE and DELETE operations on audit_events to guarantee that the
-- audit log is strictly append-only.

CREATE TRIGGER audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only: UPDATE is forbidden');
END;

CREATE TRIGGER audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only: DELETE is forbidden');
END;
