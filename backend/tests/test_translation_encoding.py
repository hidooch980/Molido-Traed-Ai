"""The Persian dictionary must contain Persian.

Seventeen strings in `i18n.ts` had been double-encoded: UTF-8 bytes read as
Latin-1 and written back, so `ثبت‌نام` was stored as `Ø«Ø¨ØªâÙØ§Ù`. They
rendered exactly like that on the live site - a button labelled in mojibake,
in production, for as long as nobody happened to open that page in Persian.

Nothing caught it. TypeScript is happy: they are valid strings. The build is
happy. Every test that reads a label reads the broken one and compares it to
itself. The corruption is only visible to a person looking at the rendered
page, in the right language, on the right route.

It is the same class of failure as `test_line_endings` - a file that is
byte-wrong rather than syntax-wrong, invisible to every tool that only asks
whether it parses. So it gets the same treatment: a mechanical check that runs
on every commit rather than on every screenshot.

The rule is narrow, which is what makes it checkable. Latin-1 mojibake of
Persian text has a signature: `Ø` and `Ù` are what the leading bytes of the
Arabic Unicode block become, and they do not otherwise occur in Persian, in
English, or in any product name this application uses.
"""

from __future__ import annotations

import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"
I18N = FRONTEND / "lib" / "i18n.ts"

#: What UTF-8 Arabic-block bytes look like after a Latin-1 round trip. `Ø` is
#: 0xD8 and `Ù` is 0xD9 - the two lead bytes of every Persian letter.
MOJIBAKE = re.compile(r"[ØÙÚ][-¿]")

#: Persian text, so a dictionary that is only mojibake cannot pass by being
#: empty of it.
PERSIAN = re.compile(r"[؀-ۿ]")


def source() -> str:
    return I18N.read_text(encoding="utf-8")


def dictionary_bounds(name: str) -> tuple[int, int]:
    text = source()
    start = text.index(f"const {name}: Dictionary = {{")
    rest = text[start:]
    # The dictionaries are top-level, so the first line that is exactly `};`
    # closes the one that opened.
    end = start + rest.index("\n};")
    return start, end


def lines_of(name: str) -> list[tuple[int, str]]:
    start, end = dictionary_bounds(name)
    text = source()
    offset = text[:start].count("\n")
    return [
        (offset + i + 1, line)
        for i, line in enumerate(text[start:end].split("\n"))
    ]


class TestNothingIsDoubleEncoded:
    """The bug that shipped. `Ø` and `Ù` are the leading bytes of Persian
    letters seen through the wrong decoder, and they occur nowhere else."""

    @pytest.mark.parametrize("name", ["fa", "en"])
    def test_no_dictionary_contains_mojibake(self, name):
        broken = [
            f"line {number}: {line.strip()[:80]}"
            for number, line in lines_of(name)
            if MOJIBAKE.search(line)
        ]

        assert not broken, (
            f"the {name} dictionary contains double-encoded text - UTF-8 read "
            f"as Latin-1 and written back. Repair with "
            f"`text.encode('latin-1').decode('utf-8')`:\n  "
            + "\n  ".join(broken)
        )

    def test_the_file_itself_is_utf_8(self):
        """A file that cannot be decoded is a file whose strings are all
        suspect, and the failure would otherwise arrive as a stack trace from
        whichever tool read it first."""
        I18N.read_bytes().decode("utf-8")


class TestThePersianDictionaryIsActuallyPersian:
    """A guard on the guard. Every check above passes on a dictionary that has
    been quietly replaced by its English fallback."""

    def test_most_of_it_is_persian_script(self):
        values = [
            line for _, line in lines_of("fa") if re.search(r'":\s*"', line)
        ]
        persian = [line for line in values if PERSIAN.search(line)]

        assert len(values) > 200, "the fa dictionary looks truncated"
        # Not all of it: model ids, `v0.2.0`, `MolidoTrade AI` and a handful of
        # deliberately-Latin labels are correct as they are.
        assert len(persian) / len(values) > 0.75, (
            f"only {len(persian)} of {len(values)} fa values contain Persian "
            "script - the dictionary may have been overwritten with English"
        )


class TestTheTwoDictionariesStayInStep:
    def test_every_english_key_exists_in_persian(self):
        def keys(name: str) -> set[str]:
            return {
                match.group(1)
                for _, line in lines_of(name)
                if (match := re.match(r'\s*"([^"]+)":', line))
            }

        missing = keys("en") - keys("fa")

        # A missing key falls back to English at runtime, which is a page in
        # two languages rather than a crash - visible only to somebody reading
        # it, which is exactly how the mojibake survived.
        assert not missing, f"keys with no Persian translation: {sorted(missing)[:12]}"
