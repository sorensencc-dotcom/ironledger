# Phase 15 exit contract — inbox attach + PDF statement wedge

## Goal
A later statement row attaches to an existing economic event after operator confirm. Posting count does not increase.

## Must hold
1. Confirming an attach writes `event_evidence` and does not insert a new staged transaction or posting pair. Target `identity_fingerprint`, `payee`, and `narration` are unchanged.
2. Unique window hits still require confirm. Ambiguous windows never auto-attach. Two rows from one source document cannot attach to the same event.
3. Unmatched rows follow the ordinary `upsert_staged` pending path.
4. Amount+account hits outside the integer day window, or with flipped sign, are near-miss proposals.
5. Reimport of a content-hash whose source rows already have staged txns or pending/confirmed proposals short-circuits.
6. New modules under `src/ironledger/ingest/attach.py` and `src/ironledger/ingest/formats/pdf_engine.py` contain zero `ast.Div` and zero `import beancount`.

## Locks
- SimpleFIN ingest is a match target only; it is not rerouted through `run_import`.
- PDF `sign` is `as_printed` or `invert`. `example-card` is a `Liabilities:` account.
- New attach HTTP mutations require `X-IronLedger-Op-Token` when an operator token is configured.
- Enter/approve in the inbox does not confirm an attach proposal.

## Tests
`python -m pytest tests/test_ingest_attach.py tests/test_ingest_pdf.py tests/test_review_attach.py tests/test_ingest_pipeline.py tests/test_phase15_exit_contract.py tests/test_web_attach.py tests/test_event_evidence_schema.py tests/test_cli_import.py -q`

Then `python -m pytest -q`.
