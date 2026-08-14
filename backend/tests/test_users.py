"""Who can create an account, and what that account can reach.

This deployment sat in a state nobody could sign in to: one seeded user row
with no password, a broker form behind a session, and no route that could
create the first account. The site was up, healthy, and unusable.

So these tests are mostly about the three doors staying different sizes - claim
once, register as a viewer, create at a chosen role only if already trusted -
and about the deployment never ending up locked out of itself again.
"""

from __future__ import annotations

import pytest

from app.core.enums import UserRole
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.models.tenancy import User
from app.services import sessions_auth
from app.services import users as user_service

GOOD_PASSWORD = "a long enough phrase"
OTHER_PASSWORD = "another long phrase"


def claim_owner(session, email="owner@example.com"):
    created = user_service.claim(session, email=email, password=GOOD_PASSWORD)
    session.flush()
    return created


class TestClaimingAnUnclaimedDeployment:
    def test_the_first_account_becomes_the_owner(self, session):
        created = user_service.claim(
            session, email="Owner@Example.com ", password=GOOD_PASSWORD
        )

        assert created.role is UserRole.OWNER
        assert created.claimed_deployment is True
        # Normalised on the way in, so signing in with a different case works.
        assert created.email == "owner@example.com"

    def test_a_second_claim_is_refused(self, session):
        claim_owner(session)

        with pytest.raises(ConflictError) as exc:
            user_service.claim(session, email="squatter@example.com", password=OTHER_PASSWORD)

        assert "already has an account" in str(exc.value)

    def test_a_seeded_row_without_a_password_does_not_close_the_window(self, session):
        """The exact state this deployment was in: one user row, no password,
        and no way in. Counting rows rather than passwords would have locked it
        out of itself permanently."""
        session.add(
            User(
                tenant_id=user_service._tenant(session).id,
                email="trader@molidotrade.local",
                display_name="trader (key holder)",
                password_hash=None,
                role=UserRole.TRADER,
                is_active=True,
            )
        )
        session.flush()

        assert user_service.is_claimed(session) is False

        created = user_service.claim(session, email="owner@example.com", password=GOOD_PASSWORD)

        assert created.role is UserRole.OWNER

    def test_claiming_with_the_seeded_address_adopts_that_row(self, session):
        """Rather than colliding with the unique constraint on (tenant, email)
        and failing with a database error the person cannot act on."""
        session.add(
            User(
                tenant_id=user_service._tenant(session).id,
                email="trader@molidotrade.local",
                password_hash=None,
                role=UserRole.TRADER,
                is_active=True,
            )
        )
        session.flush()

        created = user_service.claim(
            session, email="trader@molidotrade.local", password=GOOD_PASSWORD
        )

        assert created.role is UserRole.OWNER
        assert user_service.is_claimed(session) is True

    def test_the_owner_can_actually_sign_in_afterwards(self, session):
        """The point of the whole flow. A claim that writes a row nobody can
        authenticate against has achieved nothing."""
        user_service.claim(session, email="owner@example.com", password=GOOD_PASSWORD)
        session.flush()

        result = sessions_auth.sign_in(
            session, email="owner@example.com", password=GOOD_PASSWORD
        )

        assert result.role is UserRole.OWNER
        assert result.token


class TestSelfRegistration:
    def test_registering_lands_as_a_viewer_and_nothing_more(self, session):
        """An open sign-up form that granted more would make the door to the
        marketing page the same door as the door to the broker connection."""
        claim_owner(session)

        created = user_service.register(
            session, email="stranger@example.com", password=OTHER_PASSWORD
        )

        assert created.role is UserRole.VIEWER

    def test_a_viewer_cannot_reach_anything_that_moves_money(self, session):
        """Stated as a test rather than a comment: if the role table ever grants
        a viewer SIMULATE, this fails and the sign-up form stops being safe."""
        from app.api.deps import ROLE_PERMISSIONS
        from app.core.enums import Permission

        viewer = ROLE_PERMISSIONS[UserRole.VIEWER]

        assert Permission.SIMULATE not in viewer
        assert Permission.EXECUTE not in viewer
        assert user_service.SELF_REGISTERED_ROLE is UserRole.VIEWER

    def test_registering_before_the_deployment_is_claimed_is_refused(self, session):
        """Otherwise the first stranger to find the URL becomes a viewer and the
        owner window is still open behind them - two doors where there is one."""
        with pytest.raises(ConflictError) as exc:
            user_service.register(session, email="early@example.com", password=GOOD_PASSWORD)

        assert "no owner yet" in str(exc.value)

    def test_a_taken_address_is_refused(self, session):
        claim_owner(session, email="taken@example.com")

        with pytest.raises(ConflictError):
            user_service.register(session, email="taken@example.com", password=OTHER_PASSWORD)

    def test_the_address_is_matched_case_insensitively(self, session):
        """`Taken@…` and `taken@…` are one account everywhere else, so they must
        be one account here too."""
        claim_owner(session, email="taken@example.com")

        with pytest.raises(ConflictError):
            user_service.register(session, email="TAKEN@example.com", password=OTHER_PASSWORD)


class TestPasswords:
    def test_a_short_password_is_refused_with_the_reason(self, session):
        claim_owner(session)

        with pytest.raises(ValidationFailedError) as exc:
            user_service.register(session, email="new@example.com", password="short")

        assert str(user_service.PASSWORD_MIN_LENGTH) in str(exc.value)

    def test_the_plaintext_never_reaches_the_row(self, session):
        created = user_service.claim(
            session, email="owner@example.com", password=GOOD_PASSWORD
        )
        session.flush()

        user = session.get(User, created.id)

        assert user.password_hash is not None
        assert GOOD_PASSWORD not in user.password_hash

    def test_nothing_returned_carries_the_password(self, session):
        created = user_service.claim(
            session, email="owner@example.com", password=GOOD_PASSWORD
        )

        assert GOOD_PASSWORD not in str(created.as_dict())

    def test_the_listing_carries_no_hashes(self, session):
        claim_owner(session)

        rendered = str(user_service.listing(session))

        assert "pbkdf2" not in rendered
        assert GOOD_PASSWORD not in rendered


class TestCreatingSomebodyAtARole:
    def test_a_role_can_be_chosen(self, session):
        claim_owner(session)

        created = user_service.create(
            session,
            email="analyst@example.com",
            password=OTHER_PASSWORD,
            role=UserRole.ANALYST,
        )

        assert created.role is UserRole.ANALYST

    def test_owner_cannot_be_handed_out(self, session):
        """Owner comes from claiming an unclaimed deployment. An existing user
        minting a second one is how a deployment ends up with two people who
        each believe they are in charge."""
        claim_owner(session)

        with pytest.raises(ValidationFailedError) as exc:
            user_service.create(
                session,
                email="second@example.com",
                password=OTHER_PASSWORD,
                role=UserRole.OWNER,
            )

        assert "cannot be granted here" in str(exc.value)


class TestTheDeploymentCannotLockItselfOut:
    def test_the_last_owner_cannot_be_deactivated(self, session):
        created = claim_owner(session)

        with pytest.raises(ValidationFailedError) as exc:
            user_service.set_active(session, created.id, active=False)

        assert "last owner" in str(exc.value)

    def test_you_cannot_deactivate_yourself(self, session):
        """Even with another owner present - it is never what somebody meant to
        click."""
        first = claim_owner(session)
        session.flush()
        second = session.scalar(
            __import__("sqlalchemy").select(User).where(User.email == first.email)
        )
        assert second is not None

        with pytest.raises(ValidationFailedError) as exc:
            user_service.set_active(session, first.id, active=False, actor_id=first.id)

        assert "your own account" in str(exc.value)

    def test_a_non_owner_can_be_deactivated(self, session):
        claim_owner(session)
        viewer = user_service.register(
            session, email="viewer@example.com", password=OTHER_PASSWORD
        )
        session.flush()

        result = user_service.set_active(session, viewer.id, active=False)

        assert result["is_active"] is False

    def test_a_deactivated_account_cannot_sign_in(self, session):
        from app.core.errors import MolidoError

        claim_owner(session)
        viewer = user_service.register(
            session, email="viewer@example.com", password=OTHER_PASSWORD
        )
        session.flush()
        user_service.set_active(session, viewer.id, active=False)
        session.flush()

        with pytest.raises(MolidoError):
            sessions_auth.sign_in(
                session, email="viewer@example.com", password=OTHER_PASSWORD
            )

    def test_deactivating_keeps_the_row(self, session):
        """Deleting would take the audit trail with it, and that trail is the
        record of who connected which broker."""
        claim_owner(session)
        viewer = user_service.register(
            session, email="viewer@example.com", password=OTHER_PASSWORD
        )
        session.flush()

        user_service.set_active(session, viewer.id, active=False)

        assert session.get(User, viewer.id) is not None

    def test_an_unknown_user_is_not_found(self, session):
        import uuid

        with pytest.raises(NotFoundError):
            user_service.set_active(session, uuid.uuid4(), active=False)


class TestTheClaimWindowIsReportedHonestly:
    def test_unclaimed_before_and_claimed_after(self, session):
        assert user_service.is_claimed(session) is False

        claim_owner(session)

        assert user_service.is_claimed(session) is True

    def test_an_inactive_owner_does_not_count_as_claimed(self, session):
        """If the only account with a password is switched off, nobody can sign
        in - and reporting that as claimed would leave no way back in."""
        created = claim_owner(session)
        user = session.get(User, created.id)
        user.is_active = False
        session.flush()

        assert user_service.is_claimed(session) is False


class TestChangingYourOwnPassword:
    """The current password is required even though the caller already holds a
    valid session, and every other session ends. Both exist for the same
    reason: a session can be stolen, and a password change that trusts the
    session alone lets the thief keep the account rather than lose it."""

    def setup_owner(self, session):
        created = claim_owner(session)
        session.flush()
        return created

    def test_the_password_actually_changes(self, session):
        owner = self.setup_owner(session)

        user_service.change_password(
            session, owner.id, current=GOOD_PASSWORD, replacement=OTHER_PASSWORD
        )
        session.flush()

        assert sessions_auth.sign_in(
            session, email=owner.email, password=OTHER_PASSWORD
        ).token

    def test_the_old_password_stops_working(self, session):
        from app.core.errors import MolidoError

        owner = self.setup_owner(session)
        user_service.change_password(
            session, owner.id, current=GOOD_PASSWORD, replacement=OTHER_PASSWORD
        )
        session.flush()

        with pytest.raises(MolidoError):
            sessions_auth.sign_in(session, email=owner.email, password=GOOD_PASSWORD)

    def test_a_stolen_session_is_not_enough_to_take_the_account(self, session):
        """Without the current-password check, a stolen cookie would be enough
        to lock the real owner out of their own deployment permanently."""
        owner = self.setup_owner(session)

        with pytest.raises(ValidationFailedError):
            user_service.change_password(
                session, owner.id, current="not the password", replacement=OTHER_PASSWORD
            )

    def test_the_wrong_current_password_says_nothing_useful(self, session):
        """Same wording as a failed sign-in. Confirming the current password was
        right while rejecting the new one turns this into an oracle."""
        owner = self.setup_owner(session)

        with pytest.raises(ValidationFailedError) as exc:
            user_service.change_password(
                session, owner.id, current="wrong", replacement="short"
            )

        assert "do not match" in str(exc.value)

    def test_the_new_password_must_meet_the_minimum(self, session):
        owner = self.setup_owner(session)

        with pytest.raises(ValidationFailedError) as exc:
            user_service.change_password(
                session, owner.id, current=GOOD_PASSWORD, replacement="short"
            )

        assert str(user_service.PASSWORD_MIN_LENGTH) in str(exc.value)

    def test_reusing_the_same_password_is_refused(self, session):
        """Changing it because it may be known and changing it to itself is a
        click that achieved nothing while reading as success."""
        owner = self.setup_owner(session)

        with pytest.raises(ValidationFailedError) as exc:
            user_service.change_password(
                session, owner.id, current=GOOD_PASSWORD, replacement=GOOD_PASSWORD
            )

        assert "already have" in str(exc.value)

    def test_other_sessions_end(self, session):
        """The entire point of changing a password after a compromise. Leaving
        them alive changes the lock and hands out a key that still works."""
        owner = self.setup_owner(session)
        first = sessions_auth.sign_in(session, email=owner.email, password=GOOD_PASSWORD)
        second = sessions_auth.sign_in(session, email=owner.email, password=GOOD_PASSWORD)
        session.flush()

        result = user_service.change_password(
            session, owner.id, current=GOOD_PASSWORD, replacement=OTHER_PASSWORD
        )
        session.flush()

        assert result["other_sessions_ended"] == 2
        assert sessions_auth.resolve(session, first.token) is None
        assert sessions_auth.resolve(session, second.token) is None

    def test_the_current_browser_keeps_its_session(self, session):
        """Changing a password must not sign you out of the page you are
        standing on - that reads as a failure and invites a second attempt."""
        owner = self.setup_owner(session)
        mine = sessions_auth.sign_in(session, email=owner.email, password=GOOD_PASSWORD)
        theirs = sessions_auth.sign_in(session, email=owner.email, password=GOOD_PASSWORD)
        session.flush()

        user_service.change_password(
            session,
            owner.id,
            current=GOOD_PASSWORD,
            replacement=OTHER_PASSWORD,
            keep_token_prefix=mine.token[:12],
        )
        session.flush()

        assert sessions_auth.resolve(session, mine.token) is not None
        assert sessions_auth.resolve(session, theirs.token) is None

    def test_an_unknown_user_is_not_found(self, session):
        import uuid

        with pytest.raises(NotFoundError):
            user_service.change_password(
                session, uuid.uuid4(), current=GOOD_PASSWORD, replacement=OTHER_PASSWORD
            )
