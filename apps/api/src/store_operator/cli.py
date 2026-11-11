"""Offline bootstrap commands for the first store owner and platform-admin grant."""

import argparse
from datetime import UTC, datetime
from getpass import getpass
from uuid import uuid4

from sqlalchemy import select

from store_operator.auth.security import hash_password, normalize_email
from store_operator.db import SessionLocal
from store_operator.models.identity import (
    AuditEvent,
    PlatformAdminGrant,
    Store,
    StoreMembership,
    User,
)


def bootstrap_store_owner(email: str, store_name: str) -> None:
    normalized_email = normalize_email(email)
    if not normalized_email or "@" not in normalized_email:
        raise SystemExit("A valid email address is required")
    if not store_name.strip():
        raise SystemExit("Store name is required")

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email_normalized == normalized_email))
        if user is None:
            password = getpass("Initial owner password (12+ characters): ")
            confirmation = getpass("Confirm password: ")
            if len(password) < 12 or password != confirmation:
                raise SystemExit("Password confirmation failed or password is too short")
            user = User(
                id=uuid4(),
                email_normalized=normalized_email,
                password_hash=hash_password(password),
                status="active",
                email_verified_at=datetime.now(UTC),
            )
            db.add(user)
            db.flush()
        elif user.status != "active":
            raise SystemExit("Existing user is not active")

        store = Store(id=uuid4(), name=store_name.strip(), status="active")
        db.add(store)
        db.flush()
        membership = StoreMembership(
            id=uuid4(),
            store_id=store.id,
            user_id=user.id,
            role="owner",
            status="active",
            joined_at=datetime.now(UTC),
        )
        db.add(membership)
        db.add(
            AuditEvent(
                actor_type="system",
                actor_id=None,
                actor_user_id=None,
                store_id=store.id,
                action="bootstrap.store_owner.created",
                target_type="store_membership",
                target_id=str(membership.id),
                result="success",
                request_id="bootstrap-cli",
                metadata_json={"email_fingerprint_only": True},
            )
        )
        db.commit()
        print(f"Created store {store.id} and owner membership for user {user.id}.")


def grant_platform_admin(email: str, reason: str) -> None:
    normalized_email = normalize_email(email)
    if not reason.strip():
        raise SystemExit("A non-empty reason is required")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email_normalized == normalized_email))
        if user is None or user.status != "active":
            raise SystemExit("An existing active user is required")
        grant = db.scalar(
            select(PlatformAdminGrant).where(PlatformAdminGrant.user_id == user.id)
        )
        now = datetime.now(UTC)
        if grant is not None and grant.status == "active":
            raise SystemExit("User already has an active platform-admin grant")
        if grant is None:
            grant = PlatformAdminGrant(
                id=uuid4(),
                user_id=user.id,
                status="active",
                granted_at=now,
                reason_code=reason.strip()[:120],
            )
            db.add(grant)
        else:
            grant.status = "active"
            grant.granted_at = now
            grant.revoked_at = None
            grant.reason_code = reason.strip()[:120]
        db.flush()
        db.add(
            AuditEvent(
                actor_type="system",
                actor_id=None,
                actor_user_id=None,
                store_id=None,
                action="platform_admin.granted",
                target_type="user",
                target_id=str(user.id),
                result="success",
                request_id="bootstrap-cli",
                metadata_json={"reason_code": reason.strip()[:120]},
            )
        )
        db.commit()
        print(f"Granted platform.store_members.manage to user {user.id}.")


def revoke_platform_admin(email: str, reason: str) -> None:
    normalized_email = normalize_email(email)
    if not reason.strip():
        raise SystemExit("A non-empty reason is required")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email_normalized == normalized_email))
        if user is None:
            raise SystemExit("User not found")
        grant = db.scalar(
            select(PlatformAdminGrant).where(PlatformAdminGrant.user_id == user.id)
        )
        if grant is None or grant.status != "active":
            raise SystemExit("No active platform-admin grant exists")
        grant.status = "revoked"
        grant.revoked_at = datetime.now(UTC)
        db.add(
            AuditEvent(
                actor_type="system",
                actor_id=None,
                actor_user_id=None,
                store_id=None,
                action="platform_admin.revoked",
                target_type="user",
                target_id=str(user.id),
                result="success",
                request_id="bootstrap-cli",
                metadata_json={"reason_code": reason.strip()[:120]},
            )
        )
        db.commit()
        print(f"Revoked platform-admin grant for user {user.id}.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="store-operator")
    commands = parser.add_subparsers(dest="command", required=True)

    owner = commands.add_parser("bootstrap-store-owner")
    owner.add_argument("--email", required=True)
    owner.add_argument("--store-name", required=True)

    grant = commands.add_parser("grant-platform-admin")
    grant.add_argument("--email", required=True)
    grant.add_argument("--reason", required=True)

    revoke = commands.add_parser("revoke-platform-admin")
    revoke.add_argument("--email", required=True)
    revoke.add_argument("--reason", required=True)

    args = parser.parse_args()
    if args.command == "bootstrap-store-owner":
        bootstrap_store_owner(args.email, args.store_name)
    elif args.command == "grant-platform-admin":
        grant_platform_admin(args.email, args.reason)
    elif args.command == "revoke-platform-admin":
        revoke_platform_admin(args.email, args.reason)


if __name__ == "__main__":
    main()
