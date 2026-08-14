"""No function may cross from a server page into a client component.

React refuses to serialise one, and the page fails at request time with
"Functions cannot be passed directly to Client Components". Nothing catches it
first: `tsc` is happy because the prop types line up, the production build is
happy because the page compiles, and the error appears only when somebody opens
the page. `/brokers` returned 500 in production for exactly this - a `t` prop
handed to a form.

The rule is narrow and mechanical, which is what makes it checkable: a file
carrying "use client" must not declare a prop whose type is a function. Labels
are resolved on the server and handed over as strings.

The first version of this file scanned only multi-line interface blocks and
passed happily against the real bug planted back in, because that bug was
written inline in the signature. A test that does not catch the defect it was
written for is worse than no test - it converts an open question into a
confident wrong answer. The extraction below reads the parameter list too, and
there is a test that plants the inline shape to prove it.
"""

from __future__ import annotations

import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"

#: `(key: string) => string`, `() => void`, `(x: T) => U` in a prop position.
FUNCTION_PROP = re.compile(r"(\w+)\??:\s*\([^)]*\)\s*=>")


def client_components() -> list[pathlib.Path]:
    return sorted(
        path
        for path in FRONTEND.rglob("*.tsx")
        if '"use client"' in path.read_text(encoding="utf-8")[:200]
    )


def prop_declarations(source: str) -> str:
    """Everything that could declare a prop, and nothing that could not.

    Two places: an `interface`/`type` body, and the parameter list of an
    exported component. The body of the component is excluded on purpose - a
    client component is free to build callbacks internally, and it is only the
    boundary that cannot carry them.
    """
    regions: list[str] = []

    for match in re.finditer(r"(?:interface|type)\s+\w+\s*=?\s*\{", source):
        depth, index = 1, match.end()
        while index < len(source) and depth:
            depth += (source[index] == "{") - (source[index] == "}")
            index += 1
        regions.append(source[match.end() : index])

    for match in re.finditer(r"export\s+(?:default\s+)?function\s+\w+\s*\(", source):
        depth, index = 1, match.end()
        while index < len(source) and depth:
            depth += (source[index] == "(") - (source[index] == ")")
            index += 1
        regions.append(source[match.end() : index])

    return "\n".join(regions)


def test_the_scan_actually_finds_client_components():
    """Guards the guard. An empty list would make every check below vacuous,
    and this suite has been bitten by exactly that before."""
    assert client_components(), "no client components were found to check"


def test_the_extraction_sees_an_inline_signature():
    """The shape that broke production was written inline, and the first
    version of this file scanned only multi-line blocks - so it passed against
    the real bug. This asserts the extraction reads both."""
    inline = 'export function Widget({ labels, t }: { labels: L; t: (k: string) => string }) {'
    block = "interface Props {\n  t: (key: string) => string;\n}"

    assert FUNCTION_PROP.search(prop_declarations(inline))
    assert FUNCTION_PROP.search(prop_declarations(block))


def test_a_component_body_is_not_scanned():
    """A client component may declare callbacks internally; only what crosses
    the boundary matters. Flagging those would be a false alarm teaching
    everyone to ignore this test."""
    source = (
        "export function Widget({ label }: { label: string }) {\n"
        "  const handler: (e: Event) => void = () => {};\n"
        "  return null;\n"
        "}\n"
    )

    assert not FUNCTION_PROP.search(prop_declarations(source))


@pytest.mark.parametrize("path", client_components(), ids=lambda p: p.name)
def test_no_function_typed_prop(path: pathlib.Path):
    source = path.read_text(encoding="utf-8")
    offenders = sorted({m.group(1) for m in FUNCTION_PROP.finditer(prop_declarations(source))})

    assert not offenders, (
        f"{path.name} declares function props {offenders}. A server page cannot "
        "pass those - React refuses to serialise a function across that "
        "boundary and the page 500s at request time, with nothing failing "
        "earlier. Resolve them to strings on the server first"
    )
