# Phase 15 handoff — inbox attach + PDF wedge

**Status:** Shipped on local `main`. Packaging waits.  
**Date:** 2026-09-15  
**HEAD:** `e68ef25` (`fix(web): bump workbench HUD version to v0.15.0`)  
**Feature:** `926f4c5` (`feat(ingest): Phase 15 inbox attach + PDF wedge`)  
**Docs:** `7ab2250`  
**Live:** `http://127.0.0.1:8000/` HUD **v0.15.0**; `/docs/index.html` operator guide v0.15.0  
**Suite:** 1023 passed, 4 skipped (`uv run pytest -q`) on the feature land. Contract tests still green after docs/HUD follow-ups.  
**Repo:** local-only. No remote. Do not push, tag, or bump `pyproject` off `0.0.0`.

---

## What shipped

Later CSV/OFX/PDF rows propose attach to an existing economic event. Operator confirms. No second posting.

| Piece | Where |
|---|---|
| Join tables | `src/ironledger/db/schema/0018_event_evidence.sql` (`event_evidence`, `attach_proposals`) |
| Linker | `src/ironledger/ingest/attach.py` |
| PDF text-layer adapter | `src/ironledger/ingest/formats/pdf_engine.py` |
| Wedge profile | `config/pdf-profiles/example-card.json` — `Liabilities:CreditCard:ExampleCard`, `sign: as_printed`, `date_window_days: 3` |
| Confirm/reject | `src/ironledger/review/state.py`; CLI `review attach-confirm` / `attach-reject` |
| HTTP | `GET /api/staging/proposals`; `POST .../confirm` body `{"chosen_staged_id"}`; `POST .../reject`. Mutations need `X-IronLedger-Op-Token` when configured. |
| Inbox | `.pdf` allowed. Enter/Approve are a no-op on `item_type === 'attach'`. Inspector radios, none preselected, **Confirm attach**. |
| Exit contract | `docs/meta/contracts/ironledger-phase-15-exit-contract.md` |
| Brief | `.ijfw/memory/brief.md` (gitignored; copy of locks below) |

Match key: imported-leg `minor_units` + account + currency + integer calendar-day window. Payee is enrichment, not identity. Unique hits still require confirm. Ambiguous windows never auto-attach. Two rows from one source document cannot claim the same event. Flipped sign / outside window → near-miss, not a silent second posting. SimpleFIN stays on `ingest_simplefin_payload`.

---

## Locks (do not reopen)

- Never auto-attach.
- Never a second posting for a confirmed match.
- SimpleFIN is a match target, not an attach adapter.
- PDF `sign` is `as_printed` or `invert` only.
- `--pdf-profile` required for `.pdf`; rejected for CSV. Do not pass `--importing-account` when the profile sets the account.
- OCR, email, XLS, Zapier, NotebookLM, OAuth, identity v2, packaging: out until explicitly pulled in.
- New ingest modules: zero `ast.Div`, zero `import beancount`.

---

## Not verified in the wild

- Operator try-on of a **real** PDF against **live** SimpleFIN charges.
- Live click of Confirm attach on real data (API tests cover confirm/reject).
- R1 (false unique attach) and R2 (date/sign miss → duplicate pending).

---

## Suggested next steps (ranked)

### 1. Do now — real PDF try-on (product)

This is the Phase 15 exit in the world. Not more MIME types.

1. Copy `config/pdf-profiles/example-card.json` to a real name. Set `account`, `sign`, `date_formats`, `date_window_days`, `line_pattern` from one statement page.
2. Drop the PDF in inbox. Text layer required. Scans fail closed (no OCR).
3. Import:

```
python -m ironledger.cli import inbox/<file>.pdf --pdf-profile <name> --confirm "import <resolved-path>"
```

4. Count `staged_transactions` / `staged_postings` before confirm.
5. In the workbench, open an `attach` or `near-miss` row. Pick a radio. Click **Confirm attach**. Enter must not confirm.
6. Count again. Posting count must not increase. `event_evidence` gains a row. Target payee/narration/`identity_fingerprint` unchanged.

Pass: unique hits attach; unmatched stay pending; two same-amount hits in the window disambiguate.  
Fail R1: unique path attached the wrong charge.  
Fail R2: posted-date vs SimpleFIN-date skew or sign flip produced a duplicate pending instead of near-miss.

If it fails, tune the **profile** (sign, window, regex). Do not add OCR or a new format.

### 2. Do next if try-on passes — second real profile

A checking PDF or a second card. Still text-layer. Still inbox attach. Still no packaging.

### 3. Optional engineering (only after try-on, or if it blocks try-on)

- Version is hardcoded in `web/src/components/TopHUD.tsx`, `src/ironledger/web/app.py`, and `scripts/build-docs.py`. It drifted to v0.11.0 once; a single constant would stop that.
- Workbench static is `COPY web/dist/` into the image. After a UI change: `cd web && npm run build` then `docker compose up -d --build`. `web/dist/` is gitignored except `web/dist/docs/index.html`.
- Live attach confirm click on the workbench (happy path + reject + ambiguous radios).

### 4. Explicitly later (do not start)

| Ask | Why later |
|---|---|
| OCR | Wedge is text-layer. Empty-text PDFs fail closed on purpose. |
| Email / XLS / Zapier / NotebookLM / OAuth | Transport, not identity. Formats are adapters into the linker. |
| Packaging, tag, `pyproject` version | Brief Out. `0.0.0` stays. No remotes. |
| Identity v2 (rewrite payee/narration on attach) | Confirm must leave target identity/payee/narration unchanged. |
| SimpleFIN engine rewrite | Match target only. |

---

## Resume commands

```
uv run pytest -q
uv run pytest tests/test_ingest_attach.py tests/test_ingest_pdf.py tests/test_review_attach.py tests/test_phase15_exit_contract.py tests/test_web_attach.py tests/test_event_evidence_schema.py -q
docker compose up -d --build
```

Do not commit `graft/.cache/session/`.
