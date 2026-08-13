"""Shell scripts and Dockerfiles must keep LF endings.

This has now broken the deploy twice, and both times the message pointed
nowhere near the cause:

    infra/deploy.sh: line 14: $'\\r': command not found
    set: pipefail: invalid option name

A CRLF shebang makes the interpreter path `/usr/bin/env bash\\r`, which does not
exist, and every subsequent line carries a stray carriage return that bash
treats as part of the argument. On a Dockerfile the same corruption produces a
`RUN` command whose last argument ends in an invisible character.

`.gitattributes` already declares `*.sh text eol=lf`, and the repository blobs
are correct. What broke was the *working copy*: the attribute was added after
those files had already been checked out, `core.autocrlf` was true, and git
never went back to renormalise them. Fixing a file by hand fixes one file until
the next checkout.

So the check lives here, where it runs on every commit rather than on every
deploy failure.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]

# Files whose first line is read by an interpreter or a builder, where a stray
# carriage return is not cosmetic.
PATTERNS = ("*.sh", "Dockerfile", "*.Dockerfile", "*.bash")


#: Why git could not answer, if it could not. Populated by `tracked_files`.
_GIT_REFUSED: list[str] = []


def tracked_files() -> list[pathlib.Path]:
    """Ask git rather than globbing, so untracked scratch files are ignored.

    Never raises. This runs during collection, and an exception here takes the
    entire suite down before a single test executes - which is precisely what
    kept CI red for the whole life of the project: pytest exited 2, the code
    for "interrupted", and the summary blamed the build rather than naming a
    file. A helper that cannot answer now records why and returns nothing, and
    `test_the_audit_actually_finds_files` turns that into one visible failure.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", *PATTERNS],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        _GIT_REFUSED.append(f"git could not be run: {exc}")
        return []

    if result.returncode != 0:
        _GIT_REFUSED.append(
            f"git ls-files exited {result.returncode}: "
            f"{result.stderr.strip() or 'no stderr'}"
        )
        return []

    return [REPO / line for line in result.stdout.split("\n") if line.strip()]


def pytest_generate_tests(metafunc):
    if "script" in metafunc.fixturenames:
        files = tracked_files()
        metafunc.parametrize(
            "script", files, ids=[str(f.relative_to(REPO)) for f in files]
        )


def test_the_audit_actually_finds_files():
    """Guards the guard: an empty list would make every check below vacuous.

    This is also where a git failure surfaces. It is one red test with the
    reason attached, instead of a collection error that hides 1,253 green ones
    behind the word "interrupted".
    """
    files = tracked_files()

    assert files, (
        "no shell scripts or Dockerfiles were found to check"
        + (f" - {'; '.join(_GIT_REFUSED)}" if _GIT_REFUSED else "")
    )


def test_no_carriage_returns(script: pathlib.Path):
    content = script.read_bytes()
    crlf = content.count(b"\r\n")

    assert crlf == 0, (
        f"{script.relative_to(REPO)} has {crlf} CRLF line endings. On Linux the "
        f"shebang becomes an interpreter path that does not exist, and the error "
        f"names the line rather than the cause. Fix with:\n"
        f"    git config core.autocrlf false\n"
        f"    rm {script.relative_to(REPO)} && git checkout -- {script.relative_to(REPO)}"
    )


def test_the_shebang_is_intact(script: pathlib.Path):
    """A shebang is only a shebang if nothing follows the interpreter path."""
    if script.name.startswith("Dockerfile") or script.suffix == ".Dockerfile":
        pytest.skip("Dockerfiles have no shebang")

    first = script.read_bytes().split(b"\n", 1)[0]
    if not first.startswith(b"#!"):
        pytest.skip("no shebang")

    assert not first.endswith(b"\r"), f"{script.relative_to(REPO)} has a CRLF shebang"
