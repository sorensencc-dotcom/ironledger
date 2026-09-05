# IronLedger Phase 2b exit evidence

Status: evidence for operator review. No Phase 3 work is authorized until this gate is approved.

## 1. Scope delivered

Contra-account categorization, the database-backed payee rule engine with import-time
auto-fill, the pending/categorized/approved/rejected state machine, `review show`,
`review categorize`, `review auto-match`, `review approve`, `review reject`,
`review reopen`, the guided interactive loop, and `rule add` / `rule list` / `rule disable`.
Migration 0004 applied. `_with_placeholder_account` removed.

## 2. Test evidence (focused suite only)

`PYTHONPATH=src python -m pytest -q` -> `251 passed, 1 skipped in 3.09s`

Baseline going into Task 15 was `242 passed, 1 skipped`, matching the Phase 2b ledger.
Task 15 added 9 tests to close verified gaps against the spec section 12 test contract
(see the mapping table below); no production code changed.

| Spec section 12 item | Covering test(s) |
|---|---|
| 1 migration | `tests/test_migration_0004.py` (fresh apply, `status` `CHECK`, new columns, rebuild preserves rows/FKs, identity uniqueness, `categorization_rules` table/index, source-record index survives rebuild), `tests/test_migration_0004_rules.py` (`categorization_rules` constraints), `tests/test_migrations.py` (generic, applies to migration 0004: gapless sequence, reapply is a no-op, interrupted migration does not advance version, interrupted migration is recoverable, checksum-change rejection, `schema_migrations` row recorded) |
| 2 state machine | `tests/test_review_state_categorize.py` (`test_categorize_pending_advances_to_categorized`, `test_categorize_again_replaces_account_keeps_status`, `test_categorize_rejects_rejected_state`, `test_categorize_rejects_approved_state` — both name `review reopen` in the error), `tests/test_review_state_decisions.py` (`test_approve_sets_approved_and_decided_at`, `test_reject_with_reason`, `test_reject_is_idempotent`, `test_reopen_from_rejected_clears_fields_keeps_contra`, `test_reopen_from_categorized_clears_fields_keeps_contra` **[new]**, `test_approved_is_terminal` for reject/reopen/categorize on an approved row), `tests/test_review_approve_gate.py::test_approved_row_blocks_on_status` (a second `approve` is blocked by the same gate `approve()` calls, with `reason == "status"`) |
| 3 rule resolution | `tests/test_review_rules_resolve.py` (exact/prefix/regex match, no-match, priority-then-created_at ordering, importing_account scope, inactive-rule skip, uncompilable regex skipped-and-audited with `audit_skips=True`, uncompilable regex writes zero audit rows with `audit_skips=False`), `tests/test_review_rules_crud.py::test_add_rule_rejects_uncompilable_regex` (rejected at `rule add`) |
| 4 import-time auto-fill | `tests/test_ingest_pipeline_rules.py` (matching rule fills contra and row stays pending with correct `rules_applied` count, no match leaves contra NULL with `rules_applied=0`, re-import after rule change is a no-op, OFX without `--importing-account` is a `ParseError`, CSV with `--importing-account` is a `ParseError`, OFX with `--importing-account` and a matching rule fills contra), `tests/test_ingest_stage_contra.py` (contra NULL vs filled at the `upsert_staged` layer, idempotency preserved) |
| 5 `--persist-rule` | `tests/test_review_rules_crud.py` (`test_persist_exact_rule_writes_scoped_priority_50`, `test_persist_exact_rule_collision_raises_with_existing_id`), `tests/test_cli_review_phase2b.py::test_categorize_persist_rule_creates_rule` |
| 6 `auto-match` | `tests/test_review_state_auto_match.py` (`test_auto_match_fills_and_categorizes` — fills only pending/NULL-contra rows, one `auto-match` event per matched row plus a summary event, `test_auto_match_skips_already_categorized`, `test_auto_match_honors_importing_account_filter`) |
| 7 authorization | `tests/test_cli_auth_phase2b.py` (`test_phrases` — the fixed phrase per action across all seven gated actions, `test_require_operator_authorizes_approve_with_confirm` — confirms `require_operator` returns `"confirm-flag"` for a matching `--confirm`, `test_safe_mode_off_helper_denies_and_audits`, `test_safe_mode_off_helper_passes_when_off`); CLI wiring per gated command: `tests/test_cli_review_phase2b.py` (`test_approve_without_confirm_on_non_tty_is_denied`, `test_safe_mode_blocks_categorize`, `test_safe_mode_blocks_reject` **[new]**, `test_safe_mode_blocks_reopen` **[new]**, `test_safe_mode_blocks_auto_match` **[new]**, `test_safe_mode_blocks_rule_add` **[new]**, `test_safe_mode_blocks_rule_disable` **[new]**) — each asserts exit code 3 and a `denied` audit row. This coverage is the phrase gate itself, safe-mode gating, and the confirm-flag authorization path; it does not cover persisting the authorizing mechanism (tty vs. confirm-flag) into the audit event — every CLI caller in `cli/__main__.py` discards `require_operator`'s returned mechanism string, so no audit row records which mechanism authorized a command. |
| 8 approve gate | `tests/test_review_approve_gate.py` (`test_null_contra_account_blocks`, `test_invalid_account_blocks`, `test_unbalanced_blocks`, `test_multi_currency_blocks`, `test_categorized_and_balanced_passes`, `test_approved_row_blocks_on_status`), `tests/test_review_state_decisions.py::test_approve_propagates_gate_failure` |
| 9 guided loop | `tests/test_review_loop.py` (`test_loop_categorize_then_approve_then_reject_then_quit`, `test_loop_first_decision_without_phrase_fails_closed`, `test_loop_phrase_prompted_once_only`, `test_loop_approve_gate_error_reshows_same_row`, `test_loop_full_session_categorize_reject_skip_quit` **[new]** — exercises an actual `c`+`a`, `c`+`r`, and `s` across three rows, then lets the loop end naturally once every row has been decided or skipped (the script supplies a decision for each row rather than driving an explicit `q` or a genuinely exhausted stdin stream), asserting end states, the `c=2 a=1 r=1 s=1` session-end audit line, session start/end bracketing, and exactly one audit event per non-skip decision) |
| 10 read-only surfaces | `tests/test_cli_render_phase2b.py` (pure render-function coverage for `review show` text/JSON and `rule list`), `tests/test_cli_review_phase2b.py::test_review_list_status_categorized`, `tests/test_cli_review_phase2b.py::test_review_show_and_json_emit_no_audit_event` **[new]** (`review show`, `review show --json`, and `rule list` in sequence write zero new audit rows), `tests/test_cli_review_phase2b.py::test_review_show_uncompilable_regex_suggestion_writes_no_audit` **[new]** (`review show` on a row whose only matching rule has an uncompilable regex proves the `audit_skips=False` path emits zero audit writes) |

Nine tests were added in Task 15 to close verified gaps: `test_reopen_from_categorized_clears_fields_keeps_contra`
(item 2 — the `reopen`-from-`categorized` transition had no direct test), five per-command
safe-mode-denial CLI tests for `reject`/`reopen`/`auto-match`/`rule add`/`rule disable`
(item 7 — only `categorize` and `approve` had CLI-level denial coverage before this task),
`test_loop_full_session_categorize_reject_skip_quit` (item 9 — no existing test drove an
actual `s` skip through the loop), and two `review show` CLI tests (item 10 — no CLI-level
test exercised `review show`, `review show --json`, or the no-new-audit-event assertion
before this task).

## 3. Fixed authorization phrases (published)

| Action | Phrase |
|---|---|
| review approve | `approve <staged_transaction_id>` |
| review reject | `reject <staged_transaction_id>` |
| review reopen | `reopen <staged_transaction_id>` |
| review auto-match | `auto-match <importing-account|all>` |
| rule add | `rule <target_account>` |
| rule disable | `rule-disable <rule_id>` |
| review session (loop) | `review-session <db-basename>` |

`review categorize` is gated by safe mode only; it takes no phrase.

## 4. Deferred, unchanged

Beancount compile, `bean-check`, projection, search, MCP, SimpleFIN, RAG, mobile,
backups, Git publication. Full-suite, live-bank-file, and production evidence.

## 5. Operator verdict

<operator fills: approved / changes requested, date, transcript reference>
