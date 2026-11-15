"""Read-only preflight and transactional shadow-identity backfill.

No application factory, environment loading, network calls or session commits.
The caller owns the transaction. Phase 1 never authenticates from shadow hashes.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import re
import uuid

import sqlalchemy as sa

VERSION = "identity-shadow-v1"
PROVIDER = "web_password"


class MigrationConflict(RuntimeError):
    def __init__(self, report):
        super().__init__("auth_migration_preflight_failed")
        self.report = report


def legacy_account_id(value):
    """Parse legacy numeric account identifiers without accepting provider IDs."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("invalid_account_id")
    raw = str(value)
    if not re.fullmatch(r"[1-9][0-9]{0,9}", raw) or int(raw) > 2147483647:
        raise ValueError("invalid_account_id")
    return int(raw)


def _normalized(value):
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    if not 1 <= len(value) <= 255 or any(c.isspace() or ord(c) < 32 for c in value):
        return None
    try:
        value.encode("utf-8")
    except UnicodeError:
        return None
    # Preserve old login semantics; do not introduce DNS or new domain rules.
    if value.count("@") != 1 or not all(value.split("@")):
        return None
    return value


def _supported_hash(value):
    if not isinstance(value, str):
        return False
    if not re.fullmatch(
        r"(?:scrypt:[1-9][0-9]*:[1-9][0-9]*:[1-9][0-9]*|pbkdf2:sha(?:256|512):[1-9][0-9]*)\$[A-Za-z0-9]+\$[0-9a-f]+", value):
        return False
    method, _salt, digest = value.split("$")
    if method.startswith("scrypt:"):
        cost = int(method.split(":")[1])
        return cost > 1 and cost & (cost - 1) == 0 and len(digest) == 128
    return len(digest) == (64 if method.startswith("pbkdf2:sha256:") else 128)


def _fingerprint(user):
    # Never return credentials or this digest in public reports.
    payload = [user[k] for k in ("id", "email", "password_hash", "is_active_user")]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=True).encode()).hexdigest()


def _tables(conn):
    metadata = sa.MetaData()
    names = ("users", "account_external_identities", "account_mobile_sessions",
             "account_binding_challenges", "account_legacy_mappings", "auth_migration_runs")
    present = set(sa.inspect(conn).get_table_names())
    return {name: sa.Table(name, metadata, autoload_with=conn)
            if name in present else None for name in names}


def _plan(conn, tables):
    users = list(conn.execute(sa.select(tables["users"]).order_by(tables["users"].c.id)).mappings())
    identities = list(conn.execute(sa.select(tables["account_external_identities"])).mappings())
    mapping_table = tables["account_legacy_mappings"]
    mappings = ({r["source_user_id"]: r for r in conn.execute(sa.select(mapping_table)).mappings()}
                if mapping_table is not None else {})
    by_id = {u["id"]: u for u in users}
    identity_ids = {r["id"]: r for r in identities}
    web = {r["user_id"]: r for r in identities if r["provider"] == PROVIDER}
    errors, emails, subjects, plans = Counter(), Counter(), Counter(), []
    for row in identities:
        subjects[(row["provider"], row["client_id"], row["subject"])] += 1
        if row["user_id"] is not None and row["user_id"] not in by_id:
            errors["orphan_identity"] += 1
        if row["active"] and row["user_id"] is None:
            errors["unowned_active_identity"] += 1
        if row["provider"] == PROVIDER and row["user_id"] not in by_id:
            errors["invalid_web_identity"] += 1
    errors["duplicate_provider_subject"] += sum(n > 1 for n in subjects.values())
    for row in conn.execute(sa.select(tables["account_mobile_sessions"])).mappings():
        identity = identity_ids.get(row["identity_id"])
        if row["user_id"] not in by_id or identity is None:
            errors["orphan_session"] += 1
        elif row["revoked_at"] is None and identity["active"] and identity["user_id"] != row["user_id"]:
            errors["session_owner_mismatch"] += 1
    for row in conn.execute(sa.select(tables["account_binding_challenges"])).mappings():
        if row["user_id"] not in by_id:
            errors["orphan_challenge"] += 1
    for mapping in mappings.values():
        if mapping["source_user_id"] not in by_id or mapping["source_user_id"] != mapping["account_id"]:
            errors["invalid_account_mapping"] += 1
    for user in users:
        uid = user["id"]
        try:
            legacy_account_id(uid)
        except ValueError:
            errors["invalid_legacy_id"] += 1
        email = _normalized(user["email"])
        if email:
            emails[email] += 1
        excluded = not user["is_active_user"] and user["password_hash"] == "!"
        if not excluded:
            if email is None:
                errors["email_requires_manual_review"] += 1
            if not _supported_hash(user["password_hash"]):
                errors["password_format_requires_manual_review"] += 1
        identity = web.get(uid)
        expected_subject = hashlib.sha256(email.encode()).hexdigest() if email else None
        if identity is not None:
            if (excluded or identity["client_id"] != "web" or identity["identifier"] != email
                    or identity["subject"] != expected_subject or identity["password_hash"] != user["password_hash"]
                    or bool(identity["active"]) != bool(user["is_active_user"])
                    or identity["identity_type"] != "web_password"
                    or identity["verified_at"] != user.get("email_verified_at")):
                errors["shadow_identity_drift"] += 1
        mapping = mappings.get(uid)
        if mapping is not None and (mapping["source_digest"] != _fingerprint(user)
                or mapping["identity_id"] != (identity["id"] if identity else None)
                or (not excluded and identity is None)):
            errors["mapping_drift"] += 1
        plans.append((user, email, expected_subject, excluded, identity, mapping))
    errors["normalized_email_collision"] += sum(n > 1 for n in emails.values())
    errors = {key: count for key, count in errors.items() if count}
    report = {"version": VERSION, "scanned": len(users), "mapped": len(mappings),
              "excluded_disabled": sum(p[3] for p in plans),
              "identities_to_create": sum(not p[3] and p[4] is None for p in plans),
              "mappings_to_create": sum(p[5] is None for p in plans),
              "errors": errors, "ready": not errors}
    return report, plans


def preflight(conn):
    """No writes. Report contains only aggregate counts and stable error codes."""
    tables = _tables(conn)
    report = _plan(conn, tables)[0]
    report["phase1_schema_present"] = tables["account_legacy_mappings"] is not None
    return report


def backfill(conn):
    """Backfill only new rows. Any conflict aborts; caller MUST roll back on error."""
    if not conn.in_transaction():
        raise RuntimeError("explicit_transaction_required")
    if conn.dialect.name == "postgresql":
        # Blocks competing credential writes and new users for the complete rehearsal.
        # Operators must stop application writers first; timeout avoids indefinite waits.
        conn.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
        conn.exec_driver_sql("LOCK TABLE users, account_external_identities, account_legacy_mappings IN SHARE ROW EXCLUSIVE MODE")
    tables = _tables(conn)
    if tables["account_legacy_mappings"] is None or tables["auth_migration_runs"] is None:
        raise RuntimeError("phase1_schema_upgrade_required")
    report, plans = _plan(conn, tables)
    if not report["ready"]:
        raise MigrationConflict(report)
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    result = {**report, "run_id": run_id, "inserted": 0, "skipped": 0}
    conn.execute(tables["auth_migration_runs"].insert().values(
        id=run_id, version=VERSION, summary_json="{}", created_at=now))
    for user, email, subject, excluded, identity, mapping in plans:
        identity_id = identity["id"] if identity else None
        if not excluded and identity is None:
            inserted = conn.execute(tables["account_external_identities"].insert().values(
                provider=PROVIDER, client_id="web", subject=subject, identifier=email,
                user_id=user["id"], password_hash=user["password_hash"],
                active=bool(user["is_active_user"]), identity_type="web_password",
                created_at=user["created_at"], verified_at=user["email_verified_at"],
                last_login_at=user["last_login_at"]))
            identity_id = inserted.inserted_primary_key[0]
            result["inserted"] += 1
        else:
            result["skipped"] += 1
        if mapping is None:
            conn.execute(tables["account_legacy_mappings"].insert().values(
                source_user_id=user["id"], account_id=user["id"], identity_id=identity_id,
                source_digest=_fingerprint(user), run_id=run_id, created_at=now))
    after = preflight(conn)
    if not after["ready"] or after["identities_to_create"] or after["mappings_to_create"]:
        raise MigrationConflict(after)
    conn.execute(tables["auth_migration_runs"].update().where(
        tables["auth_migration_runs"].c.id == run_id).values(summary_json=json.dumps(result, sort_keys=True)))
    return result
