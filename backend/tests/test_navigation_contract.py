"""The seam between the menu, the pages and the translation table.

Three whole chapters shipped API routers for eighteen menu items and never
built their pages, so the menu kept rendering them greyed while the endpoints
behind them answered fine. Every suite passed the entire time: the backend
tested its routes, the frontend compiled, and nothing anywhere compared the two
lists. That is what these tests compare.

The rule they enforce is a menu item is exactly one of two things — a link to a
page that exists, or an honest `planned`. Both at once is a link that greys
itself out; neither is a dead entry that renders as a link and navigates to a
404. Neither state is reachable by reading `nav.ts` alone, which is why the
check has to hold the filesystem beside it.

The translation check is here rather than in the frontend because a missing key
does not fail a Next.js build. `t()` falls back to English and, when the key is
absent from both tables, renders the raw key — so a Persian page ships reading
`decisions.whyItStopsBody` to a user who requested Persian, and every automated
check stays green.
"""

from __future__ import annotations

import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"
NAV_TS = FRONTEND / "lib" / "nav.ts"
I18N_TS = FRONTEND / "lib" / "i18n.ts"
APP_DIR = FRONTEND / "app"

#: Why the nav table could not be read, if it could not.
_NAV_REFUSED: list[str] = []

NAV_ENTRY = re.compile(
    r'\{\s*key:\s*"(?P<key>[^"]+)",\s*'
    r'labelKey:\s*"(?P<label>[^"]+)",\s*'
    r'(?:href:\s*"(?P<href>[^"]+)",\s*)?'
    r'(?P<planned>planned:\s*true,\s*)?'
    r'(?:href:\s*"(?P<href2>[^"]+)",\s*)?'
    r'group:'
)


def nav_items() -> list[dict[str, str | None]]:
    """Never raises: this is called at import time to build parameter lists,
    and an exception here is a collection error that takes the suite with it.
    A missing or unparseable file returns nothing, and
    `test_the_menu_was_actually_read` reports it as one named failure."""
    try:
        source = NAV_TS.read_text(encoding="utf-8")
    except OSError as exc:
        _NAV_REFUSED.append(str(exc))
        return []
    items = [
        {
            "key": m.group("key"),
            "label": m.group("label"),
            "href": m.group("href") or m.group("href2"),
            "planned": bool(m.group("planned")),
        }
        for m in NAV_ENTRY.finditer(source)
    ]
    if len(items) < 25:
        _NAV_REFUSED.append(f"the nav parser found only {len(items)} items")
    return items


def dictionary(name: str) -> dict[str, str]:
    """One locale table out of `i18n.ts`, by its declaration."""
    source = I18N_TS.read_text(encoding="utf-8")
    match = re.search(rf"^const {name}: Dictionary = \{{(.*?)^\}};", source, re.S | re.M)
    assert match is not None, f"i18n.ts declares no {name} dictionary"
    return dict(re.findall(r'^\s*"([^"]+)":\s*"(.*?)",\s*$', match.group(1), re.M))


def page_files() -> list[pathlib.Path]:
    return sorted(APP_DIR.rglob("page.tsx"))


def test_the_menu_was_actually_read():
    """Guards the guard. Every parametrised check below is generated from
    `nav_items`, so an empty list would make all of them pass by describing
    nothing at all."""
    assert nav_items(), f"the menu could not be read: {'; '.join(_NAV_REFUSED) or 'no reason recorded'}"
    assert not _NAV_REFUSED, "; ".join(_NAV_REFUSED)


class TestEveryMenuItemIsOneThingOrTheOther:
    @pytest.mark.parametrize("item", nav_items(), ids=lambda i: str(i["key"]))
    def test_it_is_either_a_link_or_planned_but_not_both(self, item):
        assert bool(item["href"]) != bool(item["planned"]), (
            f"{item['key']} declares "
            f"{'both an href and planned' if item['href'] else 'neither an href nor planned'}"
        )

    @pytest.mark.parametrize(
        "item", [i for i in nav_items() if i["href"]], ids=lambda i: str(i["key"])
    )
    def test_a_linked_item_has_a_page_behind_it(self, item):
        """A menu entry that navigates to a 404 is worse than a greyed one."""
        href = str(item["href"])
        segment = href.strip("/")
        target = APP_DIR / "page.tsx" if not segment else APP_DIR / segment / "page.tsx"

        assert target.exists(), f"{item['key']} links to {href}, which has no page"

    def test_more_than_half_the_menu_is_reachable(self):
        """A guard on the direction of travel, not a quality bar.

        This started at three wired items out of twenty-eight. The number is
        deliberately loose; its job is to fail if a future change greys the
        application back out wholesale.
        """
        items = nav_items()
        linked = [i for i in items if i["href"]]

        assert len(linked) > len(items) / 2


class TestTheTranslationTableCoversWhatThePagesAsk:
    def test_the_two_locales_declare_the_same_keys(self):
        english, persian = dictionary("en"), dictionary("fa")
        missing = sorted(set(english) - set(persian))
        extra = sorted(set(persian) - set(english))

        assert not missing, f"keys with no Persian: {missing}"
        assert not extra, f"Persian keys with no English: {extra}"

    def test_every_key_a_page_asks_for_exists(self):
        """`t()` renders the raw key when it is absent from both tables.

        Which means a page can ship reading `decisions.whyItStopsBody` to the
        user and no build, type check or lint will have said anything.
        """
        english = dictionary("en")
        asked: dict[str, set[str]] = {}
        for page in page_files():
            for key in re.findall(r't\("([^"]+)"\)', page.read_text(encoding="utf-8")):
                asked.setdefault(key, set()).add(page.parent.name)

        unknown = {k: sorted(v) for k, v in asked.items() if k not in english}

        assert not unknown, f"pages ask for keys that do not exist: {unknown}"

    def test_every_menu_label_is_translated(self):
        english, persian = dictionary("en"), dictionary("fa")
        missing = [
            i["label"] for i in nav_items() if i["label"] not in english or i["label"] not in persian
        ]

        assert not missing, f"menu labels with no translation: {missing}"

    def test_no_translation_is_the_empty_string(self):
        """An empty string is not a translation; it renders as nothing at all
        and reads as a layout bug rather than a missing word."""
        for name in ("en", "fa"):
            blank = [k for k, v in dictionary(name).items() if not v.strip()]
            assert not blank, f"{name} has empty values: {blank}"


class TestThePagesThatClaimToBeBuiltActuallyRead:
    @pytest.mark.parametrize(
        "page", page_files(), ids=lambda p: p.parent.name or "root"
    )
    def test_a_page_either_calls_the_api_or_is_a_client_screen(self, page):
        """A page that renders only literals is a mock-up in production.

        `settings`, `charts`, `verify`, `login` and `register` are exempt
        because they read the API from the browser rather than on the server,
        which is a different mechanism and not an absence of data.

        Three of them have no choice. `verify` spends a token that only exists
        in the URL the person clicked, and a server render would spend it
        before the page was ever shown. `login` and `register` are one
        conversation - password, then a code, or a QR and a confirmation, and
        then recovery codes - where every step depends on what the server said
        about the one before it, and none of it exists at render time.
        """
        source = page.read_text(encoding="utf-8")
        if page.parent.name in {"settings", "charts", "verify", "login", "register"}:
            return

        # The landing page is the one page that reads nothing and must not.
        # It is the only page a visitor sees without an account, and every
        # figure this application holds is about somebody's account - so a
        # landing page that fetched live data would be publishing it to anybody
        # who loaded the URL. Its whole content is claims about the system,
        # which are true whether or not a database is reachable.
        if page.parent.name == "app":
            assert "api." not in source, (
                "the landing page is public and must read nothing"
            )
            return

        assert "api." in source, f"{page.parent.name} renders without reading anything"


class TestTheFirstAccount:
    """The one form whose job changes on a deployment nobody owns yet.

    `is_claimed` is false until some account has a password, and the service
    refuses ordinary registration until one does - correctly, because the
    first account has to be the administrator rather than a viewer who can
    read everything and grant nothing. The consequence is that a sign-up form
    which only knows how to register answers every attempt on a fresh
    installation with a refusal telling the person to do something the
    interface does not offer, and the only route to a new deployment's first
    account is a dead end. That is what these keep closed.
    """

    def test_the_register_page_asks_whether_anybody_owns_this(self):
        source = (APP_DIR / "register" / "page.tsx").read_text(encoding="utf-8")
        assert "api.setup()" in source, (
            "the register page cannot know which form to show without reading "
            "whether the deployment has been claimed"
        )
        assert "unclaimed" in source

    def test_the_panel_can_send_both_kinds_of_sign_up(self):
        source = (FRONTEND / "components" / "LoginPanel.tsx").read_text(
            encoding="utf-8"
        )
        assert "/api/v1/users/claim" in source, (
            "without this the first account on a fresh deployment cannot be "
            "created through the browser at all"
        )
        assert "/api/v1/users/register" in source, (
            "and an installation that already has an owner still needs the "
            "ordinary door"
        )

    def test_the_human_check_purposes_are_ones_the_server_accepts(self):
        """A proof is minted for one form and refused at every other.

        The server binds each solved challenge to a purpose, so a frontend
        that asks for a purpose the backend does not know gets a challenge it
        cannot spend - and the failure appears as a rejected sign-up rather
        than as anything naming the cause.
        """
        from app.services import human_check

        source = (FRONTEND / "components" / "HumanCheck.tsx").read_text(
            encoding="utf-8"
        )
        match = re.search(r'purpose:\s*((?:"[a-z-]+"\s*\|?\s*)+)', source)
        assert match, "the purpose union is not where this test can read it"

        asked = set(re.findall(r'"([a-z-]+)"', match.group(1)))
        served = {human_check.SIGN_IN, human_check.REGISTER, human_check.CLAIM}
        assert asked <= served, f"the browser asks for purposes the API refuses: {asked - served}"
        assert human_check.CLAIM in asked, (
            "claiming needs its own proof - reusing the register purpose would "
            "make the cheaper form a mint for the more powerful one"
        )


class TestWhereSigningInLands:
    """The landing page is public, so arriving there proves nothing.

    Signing in used to send people to `/`, which was the dashboard until a
    marketing page took that address. After the move the redirect still worked
    perfectly and still went to `/` - a page that greets strangers, carries a
    "sign in" button, and shows no sign of a session. The result was four
    consecutive successful sign-ins, every one recorded by the server, and a
    person who could not tell any of them had happened.
    """

    def test_the_panel_does_not_send_people_to_the_public_page(self):
        source = (FRONTEND / "components" / "LoginPanel.tsx").read_text(
            encoding="utf-8"
        )
        assert 'window.location.href = "/"' not in source, (
            "`/` is the landing page; sending a freshly signed-in person there "
            "is indistinguishable from refusing them"
        )
        assert "/dashboard" in source

    def test_the_destination_refuses_to_leave_this_site(self):
        """`next` comes out of the URL, where anybody can put anything.

        A login page that forwards anywhere after authenticating is how a
        phishing link borrows a domain people already trust. `//elsewhere` is
        a URL rather than a path, so testing only for a leading slash is the
        version of this check that does not work.
        """
        source = (FRONTEND / "components" / "LoginPanel.tsx").read_text(
            encoding="utf-8"
        )
        assert 'startsWith("/")' in source
        assert 'startsWith("//")' in source

    def test_the_middleware_moves_a_signed_in_visitor_off_the_landing_page(self):
        source = (FRONTEND / "middleware.ts").read_text(encoding="utf-8")
        assert 'pathname === "/"' in source, (
            "somebody who is signed in and types the domain should arrive in "
            "the application, not on the page explaining it to strangers"
        )


class TestTheProofBetweenTheTwoSignInCalls:
    """Signing in with two factors is two requests, and the proof is spent once.

    The password call presents a proof of work and the server retires it. The
    code call is a second request to the same endpoint, so it needs a proof of
    its own - and without one it fails with "that human check has been used
    already", which is a sentence about robots delivered to somebody holding a
    phone displaying the correct six digits.
    """

    def _panel(self) -> str:
        return (FRONTEND / "components" / "LoginPanel.tsx").read_text(encoding="utf-8")

    def test_a_new_proof_is_requested_when_the_code_step_opens(self):
        source = self._panel()
        # Bounded by the statement that opens the step rather than by a
        # character count, so explaining the reason at length here cannot
        # push the line being checked out of the window.
        branch = source.split("two_factor_required")[1].split('setStage("code")')[0]
        assert "human.refresh()" in branch, (
            "the request that reached this branch spent the proof; the code "
            "submission that follows presents a retired one without this"
        )

    def test_the_code_step_shows_that_a_proof_is_being_solved(self):
        """It was the only step in the flow that did not.

        The hook starts solving as soon as it is asked, so the work overlaps
        with opening an authenticator app - but a person cannot wait for
        something they cannot see, and submitting early fails.
        """
        source = self._panel()
        code_step = source.split("function CodeStep")[1]
        assert "HumanCheckBox" in code_step


class TestWhereSigningOutLands:
    """The mirror of the sign-in bug, and it arrived by the same route.

    Signing out deleted the cookie and re-read the session, which turned the
    header back into a "sign in" button and left the person standing on the
    dashboard - server-rendered while they still had a session, so its
    contents stay on screen. The gate runs on navigation and there was no
    navigation, so nothing moved them. Signing out looked like not having
    signed out.
    """

    def test_signing_out_leaves_the_page_it_happened_on(self):
        source = (FRONTEND / "components" / "SignIn.tsx").read_text(encoding="utf-8")
        block = source.split("async function signOut")[1].split("}\n")[0]
        assert "window.location.href" in block, (
            "deleting the cookie does not move anybody; the page already "
            "rendered and the middleware only runs on a navigation"
        )

    def test_a_failed_sign_out_does_not_claim_to_have_worked(self):
        """The session may still exist, and the header should say so."""
        source = (FRONTEND / "components" / "SignIn.tsx").read_text(encoding="utf-8")
        block = source.split("async function signOut")[1][:1400]
        assert "response.ok" in block
        assert "refresh()" in block


class TestTheApiIsNotOpenToStrangers:
    """The middleware gates the pages. It does not gate the data.

    An anonymous caller holds `READ`, so with `require_auth` off every
    instrument, bar, journal entry, risk limit and account figure on the
    deployment was readable by anybody who knew the path - while the pages
    above them redirected politely to a login screen. The gate on the pages is
    the cheaper half of the pair and was the only half that existed.
    """

    def test_the_reader_forwards_the_visitors_session(self):
        source = (FRONTEND / "lib" / "api.ts").read_text(encoding="utf-8")
        assert "molido_session" in source, (
            "without the cookie the API sees an anonymous caller on every "
            "request, whatever the person signed in as"
        )
        assert "next/headers" in source

    def test_forwarding_never_throws_into_a_page(self):
        """`cookies()` raises outside a request rather than returning nothing,
        and a thrown error in a data reader renders as "backend unreachable"
        about a backend that is perfectly fine."""
        source = (FRONTEND / "lib" / "api.ts").read_text(encoding="utf-8")
        block = source.split("async function sessionHeader")[1].split("\n}")[0]
        assert "catch" in block

    def test_the_session_is_forwarded_rather_than_replaced_by_a_service_key(self):
        """One privileged identity for every visitor would work, and would
        hand a viewer whatever an owner can read."""
        source = (FRONTEND / "lib" / "api.ts").read_text(encoding="utf-8")
        request_body = source.split("async function request<T>")[1][:600]
        assert "sessionHeader()" in request_body


class TestTheMenuCanBeFiltered:
    """Thirty-seven destinations in five groups, two of them holding
    twenty-one between them.

    That is a list somebody reads rather than a menu somebody uses, and the
    reading was paid for on every navigation rather than once.
    """

    def _shell(self) -> str:
        return (FRONTEND / "components" / "Shell.tsx").read_text(encoding="utf-8")

    def test_the_rail_has_a_filter(self):
        assert "rail-search-input" in self._shell()

    def test_filtering_keeps_the_groups(self):
        """A flat result list would discard the one thing the grouping
        teaches - where a page lives - so the second visit learns nothing."""
        shell = self._shell()
        assert "rail-group-label" in shell
        assert "GROUPS.map" in shell

    def test_it_matches_the_key_as_well_as_the_label(self):
        """Somebody who knows the application types `dna` long before they
        type the translated label for it."""
        shell = self._shell()
        block = shell.split("const matches = NAV.filter")[1][:600]
        assert "item.key" in block

    def test_an_empty_group_disappears_rather_than_heading_nothing(self):
        shell = self._shell()
        assert "matches.length === 0" in shell

    def test_the_empty_message_only_appears_while_filtering(self):
        """A permanent "nothing found" under a full menu would be a lie."""
        shell = self._shell()
        assert "nav.filterEmpty" in shell
        block = shell.split("nav.filterEmpty")[0][-400:]
        assert "query.trim()" in block
