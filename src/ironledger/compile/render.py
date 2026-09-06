from __future__ import annotations

from ironledger.compile.model import ApprovedPosting, ApprovedSet, ApprovedTransaction


def format_amount(minor_units: int, scale: int) -> str:
    sign = "-" if minor_units < 0 else ""
    abs_units = abs(minor_units)
    if scale == 0:
        return f"{sign}{abs_units}"
    divisor = 10 ** scale
    whole = abs_units // divisor
    frac = abs_units % divisor
    return f"{sign}{whole}.{frac:0{scale}d}"


def escape_beancount_string(val: str) -> str:
    return val.replace("\\", "\\\\").replace('"', '\\"')


def render_accounts_beancount(approved_set: ApprovedSet) -> bytes:
    account_dates: dict[str, str] = {}
    account_currencies: dict[str, str] = {}

    for tx in approved_set.transactions:
        for p in tx.postings:
            assert p.account is not None
            if p.account not in account_dates or tx.proposed_date < account_dates[p.account]:
                account_dates[p.account] = tx.proposed_date
            account_currencies[p.account] = p.currency

    lines: list[str] = []
    for acct in sorted(account_dates.keys()):
        date = account_dates[acct]
        curr = account_currencies[acct]
        lines.append(f"{date} open {acct} {curr}")

    content = "\n".join(lines) + ("\n" if lines else "")
    return content.encode("utf-8")


def render_year_beancount(year: int, txns: list[ApprovedTransaction]) -> bytes:
    sorted_txns = sorted(txns, key=lambda t: (t.proposed_date, t.identity_fingerprint))
    chunks: list[str] = []

    for tx in sorted_txns:
        payee_esc = escape_beancount_string(tx.payee)
        narration_esc = escape_beancount_string(tx.narration)
        lines = [f'{tx.proposed_date} * "{payee_esc}" "{narration_esc}"']
        lines.append(f'  staged-transaction-id: "{tx.staged_transaction_id}"')

        # Imported leg first, then contra. validate_approved_set (Task 3, Finding 4)
        # guarantees roles are exactly {"imported", "contra"}, so this sort is total.
        sorted_postings = sorted(tx.postings, key=lambda p: 0 if p.role == "imported" else 1)
        for p in sorted_postings:
            amt_str = format_amount(p.minor_units, p.minor_unit_scale)
            lines.append(f"  {p.account}  {amt_str} {p.currency}")
            lines.append(f'    source-document-id: "{p.source_document_id}"')
            lines.append(f'    source-record-id: "{p.source_record_id}"')
            lines.append(f'    identity-algo-version: "{p.identity_algo_version}"')
            lines.append(f'    identity-method: "{p.identity_method}"')

        chunks.append("\n".join(lines))

    content = "\n\n".join(chunks) + ("\n" if chunks else "")
    return content.encode("utf-8")


def render_main_beancount(title: str, currencies: list[str], years: list[int]) -> bytes:
    lines = [f'option "title" "{escape_beancount_string(title)}"']
    for curr in sorted(set(currencies)):
        lines.append(f'option "operating_currency" "{curr}"')
    lines.append("")
    lines.append('include "accounts.beancount"')
    for y in sorted(set(years)):
        lines.append(f'include "txns/{y}.beancount"')
    content = "\n".join(lines) + "\n"
    return content.encode("utf-8")


def render_ledger(approved_set: ApprovedSet, *, title: str = "IronLedger") -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    files["accounts.beancount"] = render_accounts_beancount(approved_set)

    currencies: list[str] = []
    txns_by_year: dict[int, list[ApprovedTransaction]] = {}

    for tx in approved_set.transactions:
        year = int(tx.proposed_date.split("-")[0])
        txns_by_year.setdefault(year, []).append(tx)
        for p in tx.postings:
            currencies.append(p.currency)

    years = sorted(txns_by_year.keys())
    for y in years:
        files[f"txns/{y}.beancount"] = render_year_beancount(y, txns_by_year[y])

    files["main.beancount"] = render_main_beancount(title, currencies, years)
    return files
