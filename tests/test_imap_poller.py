from __future__ import annotations

import json

import pytest

from ironledger.ingest.errors import ConfigError
from ironledger.ingest import imap_poller
from ironledger.ingest.imap_poller import ImapAccount, poll_accounts


RAW_MESSAGE = (
    b"From: Store <receipts@example.com>\n"
    b"Subject: Receipt\n"
    b"Date: Wed, 30 Sep 2026 10:00:00 -0400\n"
    b"\n"
    b"Total: $10.00\n"
)


class FakeImap:
    instances = []

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.fetches = 0
        FakeImap.instances.append(self)

    def login(self, username, password):
        self.username = username
        self.password = password
        return "OK", [b""]

    def select(self, mailbox):
        self.mailbox = mailbox
        return "OK", [b""]

    def uid(self, command, *args):
        if command == "SEARCH":
            return "OK", [b"101"]
        if command == "FETCH":
            self.fetches += 1
            return "OK", [(b"101 (RFC822 {1}", RAW_MESSAGE)]
        raise AssertionError(command)

    def logout(self):
        return "BYE", [b""]


def test_load_accounts_requires_env_secret(tmp_path, monkeypatch):
    config = tmp_path / "imap.json"
    config.write_text(
        json.dumps({"accounts": [{"name": "main", "host": "imap.example.com", "username": "me", "password_env": "MAIL_PASS"}]}),
        encoding="utf-8",
    )
    monkeypatch.delenv("MAIL_PASS", raising=False)

    with pytest.raises(ConfigError, match="Missing IMAP password env var"):
        imap_poller.load_accounts(config)


def test_load_accounts_rejects_plaintext_password(tmp_path):
    config = tmp_path / "imap.json"
    config.write_text(
        json.dumps({"accounts": [{"name": "main", "host": "imap.example.com", "username": "me", "password": "secret"}]}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="password_env"):
        imap_poller.load_accounts(config)


def test_poll_accounts_suppresses_duplicate_uids(tmp_path, monkeypatch):
    monkeypatch.setattr(imap_poller.imaplib, "IMAP4_SSL", FakeImap)
    FakeImap.instances.clear()
    account = ImapAccount(
        name="main",
        host="imap.example.com",
        username="me",
        password="secret",
        inbox_dir=tmp_path / "inbox",
    )
    state_path = tmp_path / "imap.state.json"

    first = poll_accounts([account], state_path=state_path)
    second = poll_accounts([account], state_path=state_path)

    assert [p.name for p in first[0].staged_paths] == ["20260930_Store_receipts@example.com_Receipt_101.eml"]
    assert first[0].fetched_uids == ("101",)
    assert second[0].staged_paths == ()
    assert second[0].skipped_uids == ("101",)
    assert FakeImap.instances[0].fetches == 1
    assert FakeImap.instances[1].fetches == 0


def test_poll_accounts_ingest_invokes_runner(tmp_path, monkeypatch):
    monkeypatch.setattr(imap_poller.imaplib, "IMAP4_SSL", FakeImap)
    FakeImap.instances.clear()
    account = ImapAccount(
        name="main",
        host="imap.example.com",
        username="me",
        password="secret",
        inbox_dir=tmp_path / "inbox",
    )
    calls = []

    result = poll_accounts(
        [account],
        state_path=tmp_path / "imap.state.json",
        ingest=True,
        ingest_runner=lambda paths: calls.append(paths),
    )

    assert calls == [result[0].staged_paths]
    assert result[0].ingested_paths == result[0].staged_paths


def test_poll_accounts_ingest_requires_runner(tmp_path, monkeypatch):
    monkeypatch.setattr(imap_poller.imaplib, "IMAP4_SSL", FakeImap)
    FakeImap.instances.clear()
    account = ImapAccount(
        name="main",
        host="imap.example.com",
        username="me",
        password="secret",
        inbox_dir=tmp_path / "inbox",
    )

    with pytest.raises(ConfigError, match="ingest=True requires ingest_runner"):
        poll_accounts([account], state_path=tmp_path / "imap.state.json", ingest=True)
