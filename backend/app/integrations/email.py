"""Send mail over SMTP, and say so plainly when it cannot.

**This is a relay client, not a mail server.** Running one on this host was
considered and rejected, and the reason belongs here rather than in a commit
message somebody will not find: a fresh VPS address has no sending reputation,
and Gmail and Outlook put mail from an unknown address with no aligned domain
into spam or refuse it outright. SPF, DKIM, DMARC and a matching reverse DNS
record are all necessary and none of them is sufficient - reputation is earned
over months. A verification mail that lands in spam produces a user who cannot
finish registering and an operator who goes looking for a bug in code that is
working correctly.

So this speaks to somebody else's relay: a Gmail app password, a transactional
provider, whatever the deployment has. If none is configured it does not
pretend. `configured()` returns a stated refusal, exactly as the Telegram
integration does, because "no credentials" must mean off and never open.

The one rule this file exists to enforce: **a failure to deliver is reported,
never swallowed.** A verification flow that reports success for a message
nobody receives is worse than one that reports nothing at all, because the
person who could fix it never learns there is something to fix.
"""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any

from app.core.config import get_settings

#: Short. A registration form that blocks for a minute on an unreachable relay
#: has become the outage.
TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class Delivery:
    """What happened to one message. Never carries the password or the body."""

    sent: bool
    reason: str | None = None
    to: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"sent": self.sent, "to": self.to, "reason": self.reason}


def configured() -> tuple[bool, str | None]:
    """Whether this deployment can send mail, and why not if it cannot."""
    settings = get_settings()
    host = (getattr(settings, "smtp_host", "") or "").strip()
    user = (getattr(settings, "smtp_user", "") or "").strip()
    sender = (getattr(settings, "smtp_from", "") or "").strip()

    if not host:
        return False, (
            "no SMTP relay is configured, so this deployment cannot send mail. "
            "That is a stated refusal, not a silent failure - set "
            "MOLIDO_SMTP_HOST, MOLIDO_SMTP_USER, MOLIDO_SMTP_PASSWORD and "
            "MOLIDO_SMTP_FROM to enable it"
        )
    if not user:
        return False, "an SMTP host is set but no user, so authentication would fail"
    if not sender:
        return False, (
            "an SMTP relay is set but no From address. Relays reject mail whose "
            "sender they do not recognise, so this would fail at delivery rather "
            "than here"
        )
    return True, None


def send(*, to: str, subject: str, body: str) -> Delivery:
    """One message, plain text.

    Plain text rather than HTML: this sends verification links and nothing
    else, an HTML part buys nothing a link cannot do, and every HTML mail is one
    more thing a spam filter weighs.
    """
    ready, reason = configured()
    if not ready:
        return Delivery(sent=False, reason=reason, to=to)

    settings = get_settings()
    host = settings.smtp_host.strip()
    port = int(getattr(settings, "smtp_port", 587) or 587)
    user = settings.smtp_user.strip()
    password = getattr(settings, "smtp_password", "") or ""
    sender = settings.smtp_from.strip()

    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        # STARTTLS on 587, implicit TLS on 465. Both encrypt; the difference is
        # when. Neither branch falls back to plaintext on failure - a relay that
        # cannot negotiate TLS is one that would carry the password in the
        # clear, and sending anyway is worse than not sending.
        if port == 465:
            with smtplib.SMTP_SSL(
                host, port, timeout=TIMEOUT_SECONDS, context=ssl.create_default_context()
            ) as relay:
                relay.login(user, password)
                relay.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=TIMEOUT_SECONDS) as relay:
                relay.starttls(context=ssl.create_default_context())
                relay.login(user, password)
                relay.send_message(message)
        return Delivery(sent=True, to=to)
    except smtplib.SMTPAuthenticationError:
        # Named specifically. With Gmail this is almost always an ordinary
        # account password where an app password is required, and "auth failed"
        # alone sends somebody to reset a password that was never wrong.
        return Delivery(
            sent=False,
            to=to,
            reason=(
                "the relay refused the credentials. With Gmail this usually "
                "means an ordinary account password was used where an app "
                "password is required"
            ),
        )
    except Exception as problem:  # noqa: BLE001 - reported, never swallowed
        # The type and nothing else. An SMTP exception can quote the message it
        # was carrying, and this one carries a working verification link.
        return Delivery(
            sent=False, to=to, reason=f"{type(problem).__name__} while sending"
        )


def check() -> dict[str, Any]:
    """Prove the relay accepts the credentials, without mailing anybody.

    Worth running before trusting the configuration: wrong credentials fail
    here rather than at the moment somebody is waiting on a verification link.
    """
    ready, reason = configured()
    if not ready:
        return {"configured": False, "reason": reason}

    settings = get_settings()
    host = settings.smtp_host.strip()
    port = int(getattr(settings, "smtp_port", 587) or 587)

    try:
        if port == 465:
            with smtplib.SMTP_SSL(
                host, port, timeout=TIMEOUT_SECONDS, context=ssl.create_default_context()
            ) as relay:
                relay.login(settings.smtp_user.strip(), settings.smtp_password or "")
        else:
            with smtplib.SMTP(host, port, timeout=TIMEOUT_SECONDS) as relay:
                relay.starttls(context=ssl.create_default_context())
                relay.login(settings.smtp_user.strip(), settings.smtp_password or "")
        return {
            "configured": True,
            "reachable": True,
            "note": "the relay accepted the credentials; nothing was sent to anybody",
        }
    except Exception as problem:  # noqa: BLE001
        return {
            "configured": True,
            "reachable": False,
            "reason": f"{type(problem).__name__} while connecting",
        }
