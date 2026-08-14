"""Tenants, users and API keys."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import UserRole
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import TimestampType, UUIDType


class Tenant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tenants"

    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    locale: Mapped[str] = mapped_column(String(10), default="en", nullable=False)

    users: Mapped[list[User]] = relationship(back_populates="tenant", cascade="all, delete-orphan")


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Hash only. A plaintext password must never reach this table or any log.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(String(32), default=UserRole.VIEWER, nullable=False)
    locale: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)

    # The code a stranger types to say who sent them. Unique, because two
    # accounts sharing one would credit whichever the query found first - a bug
    # nobody notices until somebody is owed points.
    referral_code: Mapped[str | None] = mapped_column(
        String(16), unique=True, index=True, nullable=True
    )
    # Set once, at registration, and never rewritten. SET NULL rather than
    # CASCADE: deleting a referrer must not delete the people they introduced.
    referred_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # Stamped by email verification and by nothing else. A referral paid out on
    # registration is a machine for printing points; control of a real inbox is
    # the cheapest proof available that the new account belongs to somebody the
    # referrer does not control.
    referral_confirmed_at: Mapped[datetime | None] = mapped_column(
        TimestampType, nullable=True
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    tenant: Mapped[Tenant] = relationship(back_populates="users")
    referred_by: Mapped[User | None] = relationship(
        remote_side="User.id", backref="referrals"
    )


class AccountToken(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A single-use, expiring link: verify an address, reset a password.

    The token is stored as a hash and never in the clear. This is the table an
    email address is joined to, which makes it the first one an attacker reads,
    and a leaked database must not hand out working links.

    `purpose` is separate for the same reason two keys are separate: a
    verification token that also resets a password is a verification link that
    takes over an account.
    """

    __tablename__ = "account_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    #: The non-secret half, so a lookup does not scan and compare every row.
    token_prefix: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TimestampType, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)


class ApiKey(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """API keys are stored as a hash plus a non-secret prefix for display."""

    __tablename__ = "api_keys"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    scopes: Mapped[str] = mapped_column(String(255), default="read", nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
