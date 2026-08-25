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

        assert "api." in source, f"{page.parent.name} renders without reading anything"
