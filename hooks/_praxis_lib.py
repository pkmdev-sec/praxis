"""
PRAXIS — shared hook library.

Provides the primitives every Praxis hook needs:
  - Session / turn identity (stable within one Claude Code conversation).
  - HMAC-signed record emission — the "receipt" primitive that makes allocations
    and outcomes tamper-evident on disk.
  - A single resolver for the ledger directory so allocation, outcome, and any
    future hook all write to the same place.

The signing key is loaded lazily from ``PRAXIS_RECEIPT_KEY`` or a keyfile at
``$PRAXIS_HOME/receipt.key`` (auto-generated on first run, chmod 600). The
format is intentionally boring: SHA-256 HMAC over the canonical JSON encoding
of the record. No PKI, no rotation story yet — we ship the primitive, and only
harden it once someone actually needs multi-writer trust.

Receipt schema (v1) — common envelope used by every record type::

    {
      "v": 1,                         # schema version
      "type": "alloc" | "outcome",
      "sid": "<session_id>",
      "tid": <turn_id:int>,
      "ts": <unix_ts:float>,
      "policy_version": "<semver>",   # Praxis version that produced the record
      "payload": { ... },             # type-specific body
      "sig": "<hex sha256-hmac>"      # over v,type,sid,tid,ts,policy_version,payload
    }

The signature covers *everything except itself*, so any downstream tool can
verify integrity with only the shared key and the record bytes.
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

SCHEMA_VERSION = 1
POLICY_VERSION = "1.1.0"


# ── Paths ───────────────────────────────────────────────────────────────────


def praxis_home() -> str:
    """
    Resolve the directory Praxis uses for on-disk state.

    Resolution order:
      1. ``$PRAXIS_HOME`` if set and non-empty.
      2. The ``assets/`` directory adjacent to the Praxis checkout (derived
         from this file's location). This keeps dev installs self-contained.
      3. ``~/.praxis`` as a last resort so the hook still works when symlinked
         into a Claude Code config outside the repo.
    """
    override = os.environ.get("PRAXIS_HOME")
    if override and override.strip():
        return os.path.expanduser(override.strip())

    this_file = os.path.abspath(__file__)
    repo_root = os.path.dirname(os.path.dirname(this_file))
    assets = os.path.join(repo_root, "assets")
    if os.path.isdir(assets):
        return assets

    return os.path.expanduser("~/.praxis")


def ledger_path(name: str) -> str:
    """Return the absolute path of a ledger file under PRAXIS_HOME."""
    base = praxis_home()
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        pass
    return os.path.join(base, name)


# ── Signing key ─────────────────────────────────────────────────────────────


def _load_or_create_key() -> bytes:
    """
    Load the HMAC signing key, creating a fresh 32-byte random key on first run.

    Resolution order mirrors ``praxis_home`` so dev and prod installs behave
    the same:
      1. ``$PRAXIS_RECEIPT_KEY`` (hex) — useful for ephemeral CI.
      2. ``$PRAXIS_HOME/receipt.key`` — persistent, 0600-permissioned.
    """
    env = os.environ.get("PRAXIS_RECEIPT_KEY")
    if env and env.strip():
        try:
            return bytes.fromhex(env.strip())
        except ValueError:
            # Fall through to file-based key; don't crash the hook on bad env.
            print(
                "[PRAXIS] PRAXIS_RECEIPT_KEY is not valid hex; using keyfile",
                file=sys.stderr,
            )

    keyfile = ledger_path("receipt.key")
    if os.path.exists(keyfile):
        try:
            with open(keyfile, "rb") as fh:
                raw = fh.read().strip()
            return bytes.fromhex(raw.decode("ascii"))
        except (OSError, ValueError):
            # Corrupt keyfile — regenerate rather than crash.
            pass

    key = secrets.token_bytes(32)
    try:
        with open(keyfile, "wb") as fh:
            fh.write(key.hex().encode("ascii"))
        os.chmod(keyfile, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        # Non-fatal: we still return the key so signing works this run.
        pass
    return key


def _canonical(payload: dict) -> bytes:
    """
    Canonical JSON encoding for signing.

    Uses sorted keys + compact separators so two semantically-identical
    records produce byte-identical input to HMAC, regardless of insertion
    order. ``ensure_ascii=False`` keeps Unicode prompts intact.
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sign_record(record: dict) -> dict:
    """
    Add a SHA-256 HMAC signature to a record in place and return it.

    Signs the canonical JSON of the record with its ``sig`` field stripped,
    then writes the hex digest to ``record["sig"]``.
    """
    key = _load_or_create_key()
    unsigned = {k: v for k, v in record.items() if k != "sig"}
    digest = hmac.new(key, _canonical(unsigned), hashlib.sha256).hexdigest()
    record["sig"] = digest
    return record


def verify_record(record: dict) -> bool:
    """Return True iff ``record["sig"]`` matches the current signing key."""
    if not isinstance(record, dict) or "sig" not in record:
        return False
    expected = record["sig"]
    unsigned = {k: v for k, v in record.items() if k != "sig"}
    key = _load_or_create_key()
    actual = hmac.new(key, _canonical(unsigned), hashlib.sha256).hexdigest()
    return hmac.compare_digest(actual, expected)


# ── Session / turn identity ─────────────────────────────────────────────────


def _turn_state_path() -> str:
    """Per-session turn counter, keyed by session id."""
    return ledger_path("turn-state.json")


def resolve_session_id(data: dict) -> str:
    """
    Resolve a stable session id for the current Claude Code conversation.

    Claude Code passes ``session_id`` on every hook payload in recent versions
    (https://docs.claude.com/en/docs/claude-code/hooks). We fall back to
    ``conversation_id`` if present, then to ``$PRAXIS_SESSION_ID`` for tests,
    then mint a fresh uuid4 only as a last resort.
    """
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
    """
    Return a monotonic turn id for the given session.

    Uses a tiny JSON file under PRAXIS_HOME to persist counters across hook
    invocations. Swallows all IO errors because a broken counter must never
    break the user's session — we'd rather have duplicate turn ids in a
    diagnostics log than break Claude Code.
    """
    path = _turn_state_path()
    state = {}
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
    """Return the most recently issued turn id for a session (0 if none)."""
    path = _turn_state_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            state = json.load(fh) or {}
        return int(state.get(session_id, 0))
    except (OSError, json.JSONDecodeError, ValueError):
        return 0


# ── Record emission ─────────────────────────────────────────────────────────


def emit_record(
    ledger_name: str,
    record_type: str,
    session_id: str,
    turn_id: int,
    payload: dict,
) -> dict:
    """
    Sign ``payload`` into a v1 envelope and append it to ``ledger_name``.

    Failures are logged to stderr and swallowed so hook errors never break
    the user's turn — receipts are diagnostics, not load-bearing.
    """
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
