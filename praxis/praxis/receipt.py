"""
PRAXIS — Python receipt primitive.

Lifted from ``hooks/_praxis_lib.py`` into the installable package so adapters
can sign receipts without shelling out to the hook. Byte-identical
canonicalisation with ``lib/receipt.mjs``.

See ``docs/receipts.md`` for the schema, why HMAC (not PKI), and how
``bin/praxis verify`` uses these records to detect silent provider
degradation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
import sys
import time
import uuid
from typing import Any, Optional

__all__ = [
    "SCHEMA_VERSION",
    "POLICY_VERSION",
    "praxis_home",
    "ledger_path",
    "sign_record",
    "verify_record",
    "resolve_session_id",
    "next_turn_id",
    "peek_turn_id",
    "emit_record",
]

SCHEMA_VERSION = 1
POLICY_VERSION = "1.2.0"


def praxis_home() -> str:
    override = os.environ.get("PRAXIS_HOME")
    if override and override.strip():
        return os.path.expanduser(override.strip())

    # Walk up from this module to find a repo with an ``assets/`` sibling.
    here = os.path.abspath(os.path.dirname(__file__))
    for _ in range(4):
        parent = os.path.dirname(here)
        candidate = os.path.join(parent, "assets")
        if os.path.isdir(candidate):
            return candidate
        if parent == here:
            break
        here = parent

    return os.path.expanduser("~/.praxis")


def ledger_path(name: str) -> str:
    base = praxis_home()
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        pass
    return os.path.join(base, name)


_cached_key: Optional[bytes] = None


def _load_or_create_key() -> bytes:
    global _cached_key
    if _cached_key is not None:
        return _cached_key

    env = os.environ.get("PRAXIS_RECEIPT_KEY")
    if env and env.strip():
        try:
            _cached_key = bytes.fromhex(env.strip())
            if _cached_key:
                return _cached_key
        except ValueError:
            print(
                "[PRAXIS] PRAXIS_RECEIPT_KEY is not valid hex; using keyfile",
                file=sys.stderr,
            )

    keyfile = ledger_path("receipt.key")
    if os.path.exists(keyfile):
        try:
            with open(keyfile, "rb") as fh:
                raw = fh.read().strip()
            _cached_key = bytes.fromhex(raw.decode("ascii"))
            if _cached_key:
                return _cached_key
        except (OSError, ValueError):
            pass

    _cached_key = secrets.token_bytes(32)
    try:
        with open(keyfile, "wb") as fh:
            fh.write(_cached_key.hex().encode("ascii"))
        os.chmod(keyfile, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return _cached_key


def _reset_key_cache() -> None:
    """Test-only: wipe the key cache so tests can swap keys mid-process."""
    global _cached_key
    _cached_key = None


def _canonical(payload: dict) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sign_record(record: dict) -> dict:
    unsigned = {k: v for k, v in record.items() if k != "sig"}
    digest = hmac.new(_load_or_create_key(), _canonical(unsigned), hashlib.sha256).hexdigest()
    record["sig"] = digest
    return record


def verify_record(record: Any) -> bool:
    if not isinstance(record, dict) or "sig" not in record:
        return False
    unsigned = {k: v for k, v in record.items() if k != "sig"}
    actual = hmac.new(_load_or_create_key(), _canonical(unsigned), hashlib.sha256).hexdigest()
    return hmac.compare_digest(actual, record["sig"])


def _turn_state_path() -> str:
    return ledger_path("turn-state.json")


def resolve_session_id(data: Optional[dict]) -> str:
    if isinstance(data, dict):
        for key in ("session_id", "sessionId", "conversation_id", "conversationId"):
            v = data.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        session = data.get("session")
        if isinstance(session, dict):
            for key in ("id", "session_id"):
                v = session.get(key)
                if isinstance(v, str) and v.strip():
                    return v.strip()

    env = os.environ.get("PRAXIS_SESSION_ID")
    if env and env.strip():
        return env.strip()

    return str(uuid.uuid4())


def next_turn_id(session_id: str) -> int:
    path = _turn_state_path()
    state: dict = {}
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                state = json.load(fh) or {}
    except (OSError, json.JSONDecodeError):
        state = {}

    current = int(state.get(session_id, 0)) + 1
    state[session_id] = current

    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        os.replace(tmp, path)
    except OSError:
        pass

    return current


def peek_turn_id(session_id: str) -> int:
    path = _turn_state_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            state = json.load(fh) or {}
        return int(state.get(session_id, 0))
    except (OSError, json.JSONDecodeError, ValueError):
        return 0


def emit_record(
    ledger_name: str,
    record_type: str,
    session_id: str,
    turn_id: int,
    payload: dict,
) -> dict:
    record = {
        "v": SCHEMA_VERSION,
        "type": record_type,
        "sid": session_id,
        "tid": turn_id,
        "ts": time.time(),
        "policy_version": POLICY_VERSION,
        "payload": payload,
    }
    sign_record(record)
    try:
        with open(ledger_path(ledger_name), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"[PRAXIS] ledger write failed ({ledger_name}): {e}", file=sys.stderr)
    return record
