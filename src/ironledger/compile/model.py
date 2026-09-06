from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Final

from ironledger.compile.errors import CompileInputError
from ironledger.conventions import ConventionError, validate_account_name, validate_same_currency_balance


@dataclass(frozen=True)
class ApprovedPosting:
    staged_posting_id: str
    staged_transaction_id: str
    source_record_id: str
    source_document_id: str
    role: str
    posting_index: int
    account: str | None
    minor_units: int
    currency: str
    minor_unit_scale: int
    identity_algo_version: int
    identity_method: str
    identity_fingerprint: str


@dataclass(frozen=True)
class ApprovedTransaction:
    staged_transaction_id: str
    source_record_id: str
    source_document_id: str
    proposed_date: str
    payee: str
    narration: str
    identity_algo_version: int
    identity_method: str
    identity_fingerprint: str
    postings: tuple[ApprovedPosting, ...]


@dataclass(frozen=True)
class ApprovedSet:
    transactions: tuple[ApprovedTransaction, ...]


def load_approved_set(conn: sqlite3.Connection) -> ApprovedSet:
    tx_cursor = conn.execute(
        "SELECT st.staged_transaction_id, st.source_record_id, sr.source_document_id, "
        "       st.proposed_date, st.payee, st.narration, st.identity_algo_version, "
        "       st.identity_method, st.identity_fingerprint "
        "FROM staged_transactions st "
        "JOIN source_records sr ON st.source_record_id = sr.source_record_id "
        "WHERE st.status = 'approved' "
        "ORDER BY st.proposed_date ASC, st.identity_fingerprint ASC"
    )
    tx_rows = tx_cursor.fetchall()

    # RULING PF-2: identity_* columns live on staged_transactions (migration 0001),
    # not staged_postings (migration 0003 has no such columns). Select them from
    # the joined `st` alias and populate ApprovedPosting.identity_* from those.
    postings_cursor = conn.execute(
        "SELECT sp.staged_posting_id, sp.staged_transaction_id, sp.source_record_id, sr.source_document_id, "
        "       sp.role, sp.posting_index, sp.account, sp.minor_units, sp.currency, sp.minor_unit_scale, "
        "       st.identity_algo_version, st.identity_method, st.identity_fingerprint "
        "FROM staged_postings sp "
        "JOIN staged_transactions st ON sp.staged_transaction_id = st.staged_transaction_id "
        "JOIN source_records sr ON sp.source_record_id = sr.source_record_id "
        "WHERE st.status = 'approved' "
        "ORDER BY sp.staged_transaction_id, sp.posting_index ASC"
    )
    postings_by_tx: dict[str, list[ApprovedPosting]] = {}
    for p in postings_cursor.fetchall():
        posting = ApprovedPosting(
            staged_posting_id=p[0],
            staged_transaction_id=p[1],
            source_record_id=p[2],
            source_document_id=p[3],
            role=p[4],
            posting_index=p[5],
            account=p[6],
            minor_units=p[7],
            currency=p[8],
            minor_unit_scale=p[9],
            identity_algo_version=p[10],
            identity_method=p[11],
            identity_fingerprint=p[12],
        )
        postings_by_tx.setdefault(posting.staged_transaction_id, []).append(posting)

    transactions: list[ApprovedTransaction] = []
    for t in tx_rows:
        tx_id = t[0]
        tx_postings = postings_by_tx.get(tx_id, [])
        transactions.append(
            ApprovedTransaction(
                staged_transaction_id=tx_id,
                source_record_id=t[1],
                source_document_id=t[2],
                proposed_date=t[3],
                payee=t[4],
                narration=t[5],
                identity_algo_version=t[6],
                identity_method=t[7],
                identity_fingerprint=t[8],
                postings=tuple(tx_postings),
            )
        )
    return ApprovedSet(transactions=tuple(transactions))


def validate_approved_set(approved_set: ApprovedSet) -> None:
    account_currencies: dict[str, str] = {}

    for tx in approved_set.transactions:
        if len(tx.postings) != 2:
            raise CompileInputError(f"Transaction {tx.staged_transaction_id} must have exactly 2 postings, got {len(tx.postings)}")

        # Finding 4: pin the role contract so render.py's imported-then-contra sort is
        # provably deterministic (two 'imported' legs would otherwise sort unstably).
        roles = sorted(p.role for p in tx.postings)
        if roles != ["contra", "imported"]:
            raise CompileInputError(
                f"Transaction {tx.staged_transaction_id} postings must be exactly one 'imported' and one 'contra', got {roles}"
            )

        posting_dicts = []
        for p in tx.postings:
            if p.account is None:
                raise CompileInputError(f"Transaction {tx.staged_transaction_id} {p.role} posting has NULL account")
            try:
                validate_account_name(p.account)
            except ConventionError as e:
                raise CompileInputError(f"Invalid account {p.account!r} in transaction {tx.staged_transaction_id}: {e}") from e

            if p.account in account_currencies and account_currencies[p.account] != p.currency:
                raise CompileInputError(
                    f"Account {p.account} referenced with multiple currencies: {account_currencies[p.account]} and {p.currency}"
                )
            account_currencies[p.account] = p.currency

            # RULING PF-8: validate_same_currency_balance requires a "scale" key on
            # every posting dict (conventions.py:231-263); omitting it raises
            # ConventionError and would fail the VALID set too.
            posting_dicts.append({
                "account": p.account,
                "minor_units": p.minor_units,
                "currency": p.currency,
                "scale": p.minor_unit_scale,
            })

        try:
            validate_same_currency_balance(posting_dicts)
        except ConventionError as e:
            raise CompileInputError(f"Transaction {tx.staged_transaction_id} does not balance: {e}") from e
