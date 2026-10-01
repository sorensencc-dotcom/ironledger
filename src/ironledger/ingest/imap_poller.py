"""Small IMAP poller for staging RFC 822 receipt messages."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime
import email
import imaplib
import json
import os
from pathlib import Path
import re
from typing import Any

from ironledger.ingest.errors import ConfigError


@dataclass(frozen=True)
class ImapAccount:
    name: str
    host: str
    username: str
    password: str
    port: int = 993
    mailbox: str = "INBOX"
    search: str = "ALL"
    inbox_dir: Path = Path("inbox/receipts")
    limit: int | None = None


@dataclass(frozen=True)
class PollResult:
    account: str
    staged_paths: tuple[Path, ...]
    skipped_uids: tuple[str, ...]
    fetched_uids: tuple[str, ...]
    ingested_paths: tuple[Path, ...] = ()


IngestRunner = Callable[[tuple[Path, ...]], object]


def load_accounts(config_path: str | Path) -> list[ImapAccount]:
    raw = json.loads(Path(config_path).read_text(encoding="utf-8"))
    accounts = raw.get("accounts")
    if not isinstance(accounts, list) or not accounts:
        raise ConfigError("IMAP config requires non-empty accounts list")
    return [_load_account(item) for item in accounts]


def poll_config(
    config_path: str | Path,
    *,
    state_path: str | Path | None = None,
    ingest: bool = False,
    ingest_runner: IngestRunner | None = None,
) -> list[PollResult]:
    accounts = load_accounts(config_path)
    state_file = Path(state_path) if state_path else Path(config_path).with_suffix(".state.json")
    return poll_accounts(accounts, state_path=state_file, ingest=ingest, ingest_runner=ingest_runner)


def poll_accounts(
    accounts: list[ImapAccount],
    *,
    state_path: str | Path,
    ingest: bool = False,
    ingest_runner: IngestRunner | None = None,
) -> list[PollResult]:
    state_file = Path(state_path)
    state = _read_state(state_file)
    results = []
    for account in accounts:
        result = poll_account(account, state=state, ingest=ingest, ingest_runner=ingest_runner)
        results.append(result)
    _write_state(state_file, state)
    return results


def poll_account(
    account: ImapAccount,
    *,
    state: dict[str, list[str]] | None = None,
    ingest: bool = False,
    ingest_runner: IngestRunner | None = None,
) -> PollResult:
    seen = set((state or {}).get(account.name, []))
    account.inbox_dir.mkdir(parents=True, exist_ok=True)
    staged: list[Path] = []
    skipped: list[str] = []
    fetched: list[str] = []

    conn = imaplib.IMAP4_SSL(account.host, account.port)
    try:
        conn.login(account.username, account.password)
        status, _ = conn.select(account.mailbox)
        if status != "OK":
            raise ConfigError(f"IMAP select failed for {account.name}: {account.mailbox}")
        status, data = conn.uid("SEARCH", None, account.search)
        if status != "OK":
            raise ConfigError(f"IMAP search failed for {account.name}")
        uids = (data[0] or b"").split()
        if account.limit is not None:
            uids = uids[-account.limit :]

        for uid_bytes in uids:
            uid = uid_bytes.decode("ascii")
            state_uid = f"{account.name}:{uid}"
            if state_uid in seen:
                skipped.append(uid)
                continue
            status, fetch_data = conn.uid("FETCH", uid_bytes, "(RFC822)")
            if status != "OK":
                continue
            raw_msg = _extract_rfc822(fetch_data)
            if raw_msg is None:
                continue
            path = _write_message(account.inbox_dir, uid, raw_msg)
            staged.append(path)
            fetched.append(uid)
            seen.add(state_uid)
    finally:
        try:
            conn.logout()
        except Exception:
            pass

    if state is not None:
        state[account.name] = sorted(seen)
    ingested = _try_ingest(tuple(staged), ingest_runner) if ingest else ()
    return PollResult(account.name, tuple(staged), tuple(skipped), tuple(fetched), ingested)


def _load_account(raw: Any) -> ImapAccount:
    if not isinstance(raw, dict):
        raise ConfigError("IMAP account must be an object")
    if "password" in raw:
        raise ConfigError("IMAP config must use password_env, not plaintext password")
    password_env = raw.get("password_env")
    if not password_env:
        raise ConfigError("IMAP account requires password_env")
    password = os.environ.get(str(password_env))
    if not password:
        raise ConfigError(f"Missing IMAP password env var: {password_env}")
    for key in ("name", "host", "username"):
        if not raw.get(key):
            raise ConfigError(f"IMAP account requires {key}")
    return ImapAccount(
        name=str(raw["name"]),
        host=str(raw["host"]),
        port=int(raw.get("port", 993)),
        username=str(raw["username"]),
        password=password,
        mailbox=str(raw.get("mailbox", "INBOX")),
        search=str(raw.get("search", "ALL")),
        inbox_dir=Path(raw.get("inbox_dir", "inbox/receipts")),
        limit=int(raw["limit"]) if raw.get("limit") is not None else None,
    )


def _read_state(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError("IMAP state file must contain an object")
    return {str(k): [str(v) for v in vals] for k, vals in data.items() if isinstance(vals, list)}


def _write_state(path: Path, state: dict[str, list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _extract_rfc822(fetch_data: Any) -> bytes | None:
    for part in fetch_data or ():
        if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], bytes):
            return part[1]
    return None


def _write_message(inbox_dir: Path, uid: str, raw_msg: bytes) -> Path:
    msg = email.message_from_bytes(raw_msg)
    subject = _sanitize(_header(msg, "Subject") or "no_subject")
    sender = _sanitize(_header(msg, "From") or "unknown_sender")
    date = _message_date(msg)
    path = inbox_dir / f"{date}_{sender}_{subject}_{uid}.eml"
    path.write_bytes(raw_msg)
    return path


def _header(msg: Message, name: str) -> str:
    try:
        return str(make_header(decode_header(msg.get(name, ""))))
    except Exception:
        return msg.get(name, "")


def _message_date(msg: Message) -> str:
    raw = msg.get("Date")
    if not raw:
        return "00000000"
    try:
        return parsedate_to_datetime(raw).strftime("%Y%m%d")
    except Exception:
        return "00000000"


def _sanitize(text: str, max_len: int = 40) -> str:
    cleaned = re.sub(r'[\\/*?:"<>|]', "", text)
    cleaned = re.sub(r"\s+", "_", cleaned).strip(" ._-")
    return (cleaned or "unknown")[:max_len]


def _try_ingest(paths: tuple[Path, ...], ingest_runner: IngestRunner | None) -> tuple[Path, ...]:
    if not paths:
        return ()
    if ingest_runner is None:
        raise ConfigError("ingest=True requires ingest_runner")
    ingest_runner(paths)
    return paths