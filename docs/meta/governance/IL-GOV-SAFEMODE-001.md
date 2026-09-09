# IronLedger Safe Mode policy

- **Document ID**: `IL-GOV-SAFEMODE-001`
- **Status**: Ratified
- **Domain**: Authorization, Mutation Safety, and Blast-Radius Control
- **Enforcement Level**: Invariant / Non-Bypassable

---

## 1. Safe Mode philosophy and defaults

Safe Mode is the primary blast-radius defense mechanism in IronLedger:
- **Default State**: Safe Mode is **ACTIVE BY DEFAULT** (`enabled: true`). If `config/safe-mode.json` is missing, corrupted, or unreadable, the system defaults closed to Safe Mode Active.
- **Operator Intent Requirement**: Dangerous mutations (compiling to disk, deleting rules, rebuilding projections) require explicit operator authorization phrases or ephemeral mutation tokens.

---

## 2. Action permission matrix

| Action / Endpoint | Safe Mode Active (`enabled: true`) | Safe Mode Unlocked (`enabled: false`) |
|---|---|---|
| Ingest files (`import`) | Allowed (with path phrase) | Allowed |
| Review & categorize (`staging/categorize`) | Allowed | Allowed |
| Create rules (`rules/add`) | Allowed | Allowed |
| Run dry-run simulation (`compile/simulate`) | **Allowed** (zero disk side-effects) | **Allowed** |
| Live ledger compile (`POST /api/compile`) | **Gated** (requires token `"authorize compile"`) | Allowed |
| Projection rebuild (`POST /api/project/rebuild`) | **Gated** (requires token `"authorize project"`) | Allowed |
| Bulk rule purge / deletion | **Blocked** | Gated |

---

## 3. Ephemeral token authorization protocol

When Safe Mode is active, mutating API endpoints require an ephemeral authorization token passed in request headers or JSON payloads:

```json
{
  "dry_run": false,
  "safe_mode_token": "authorize compile",
  "rebuild_projection": true
}
```

Any request lacking the exact phrase or valid cryptographic session signature is rejected with `HTTP 403 Forbidden` and logged as a `denied` event in the audit trail.
