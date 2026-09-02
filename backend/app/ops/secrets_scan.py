"""A deterministic scan for secrets in the checkout, that never prints one.

`no_secrets_in_repository` was undeterminable because nothing looked. This
looks, the same way every time, and writes what it found as paths and
categories - never values - so the note it produces is safe to read anywhere.

**Standard library only, runnable by path.** The host runs it from cron with
the system python and no virtualenv, so it imports nothing from `app` and is
executed as `python3 backend/app/ops/secrets_scan.py --root /opt/molidotrade`.
The same functions are imported by the tests.

**Two gradings, because a filename is not a secret.** `frontend/.env.local` is
tracked on purpose and holds one public URL. Treating every `.env*` as a leak
would fail the check on a URL, and a check that fails on nothing is a check
that gets disabled. So:

- `secret`: a value that has the shape of a credential - a private key block,
  a provider token, an assignment of a long random-looking string to a name
  like `password` or `api_key`. Fails the check.
- `shape`: a file whose *name* is secret-shaped but whose contents carried no
  secret-shaped value. Reported so somebody sees it, does not fail the check.

**Placeholders are not secrets.** `changeme`, `<your-key>`, `${VAR}` and the
like are excluded by pattern; a template full of them is what a template is.

Git history is scanned when `--history` is given and `git` is available:
every blob reachable from HEAD is checked for the value patterns. It is
optional because it is slow on a large repository, and the result says
whether it ran.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Iterable

#: The host runs this with its system python (3.10), which has no
#: `datetime.UTC`. Spelled the long way so the same file runs there and here.
UTC = timezone.utc

#: Files whose names suggest they hold credentials. Matched on the path's last
#: segment so `docs/secrets-policy.md` is not caught by "secret".
NAME_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("env-file", re.compile(r"^\.env(\..+)?$", re.I)),
    ("private-key-file", re.compile(r"\.(pem|key|p12|pfx|jks|keystore)$", re.I)),
    ("ssh-key-file", re.compile(r"^id_(rsa|dsa|ecdsa|ed25519)(\.pub)?$", re.I)),
    ("credentials-file", re.compile(r"credentials?(\.json|\.ya?ml|\.txt)?$", re.I)),
)

#: Names that are templates by convention: their values are meant to be fake.
TEMPLATE_SUFFIXES = (".example", ".template", ".sample", ".dist")

#: Values with the shape of a credential. Each is specific enough that a hit
#: is worth a human's minute; a scanner that cries on every hex string is one
#: that gets ignored.
VALUE_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    # The marker *and* key material after it. A bare BEGIN line appears in
    # documentation, in this scanner's own tests and in error messages, and
    # none of those is a key; a key has a base64 body.
    (
        "private-key",
        re.compile(
            rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |)PRIVATE KEY-----[\r\n]+"
            rb"(?:[A-Za-z0-9+/=:,. -]*[\r\n]+)*?[A-Za-z0-9+/=]{60,}"
        ),
    ),
    ("aws-access-key", re.compile(rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack-token", re.compile(rb"\bxox[abpr]-[0-9A-Za-z-]{10,}\b")),
    ("telegram-bot-token", re.compile(rb"\b\d{8,10}:[A-Za-z0-9_-]{35,}")),
    ("google-api-key", re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("stripe-key", re.compile(rb"\b[sr]k_(?:live|test)_[0-9A-Za-z]{20,}\b")),
    ("jwt", re.compile(rb"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    (
        "credential-assignment",
        re.compile(
            rb"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|private[_-]?key|client[_-]?secret)\b"
            rb"\s*[:=]\s*[\"']?([A-Za-z0-9+/=_\-\.]{16,})[\"']?"
        ),
    ),
)

#: What a template value looks like. A credential-assignment whose value
#: matches one of these is a placeholder, and a placeholder is the point.
PLACEHOLDER = re.compile(
    rb"(?i)(change[-_ ]?me|replace[-_ ]?me|example|placeholder|your[-_]|xxx+|<[^>]*>|\$\{|dummy|sample|todo|redacted|\*{4,})"
)

#: Skipped outright: generated, vendored or binary trees where a hit is noise.
SKIP_DIRS = frozenset(
    {".git", "node_modules", ".next", "__pycache__", ".venv", "venv", "dist", "build", ".mypy_cache", ".pytest_cache"}
)
MAX_FILE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Finding:
    path: str
    category: str
    #: "secret" fails the check; "shape" is reported and does not.
    severity: str
    #: Where in the file, for the person who goes to look. Never the value.
    line: int | None = None


@dataclass
class ScanResult:
    root: str
    scanned_files: int
    findings: list[Finding] = field(default_factory=list)
    history_scanned: bool = False
    history_blobs: int = 0
    complete: bool = True
    notes: list[str] = field(default_factory=list)

    @property
    def secrets(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "secret"]

    @property
    def passed(self) -> bool:
        return self.complete and not self.secrets

    def as_dict(self) -> dict:
        return {
            "written_at": datetime.now(UTC).isoformat(),
            "root": self.root,
            "scanned_files": self.scanned_files,
            "complete": self.complete,
            "passed": self.passed,
            "history_scanned": self.history_scanned,
            "history_blobs": self.history_blobs,
            "findings": [asdict(f) for f in self.findings],
            "notes": self.notes,
            "note": "paths and categories only; this file never carries a secret value",
        }


def _is_template(name: str) -> bool:
    return name.lower().endswith(TEMPLATE_SUFFIXES)


def name_findings(relative: str) -> list[tuple[str, str]]:
    """Categories a path's *name* triggers, before any content is read."""
    leaf = pathlib.PurePosixPath(relative).name
    if _is_template(leaf):
        return []
    return [(category, "shape") for category, pattern in NAME_PATTERNS if pattern.search(leaf)]


def value_findings(data: bytes, *, is_test: bool = False) -> list[tuple[str, int]]:
    """(category, line) for every credential-shaped value in `data`.

    Test files are allowed the generic assignment pattern - a test that sets
    `password="correct horse battery staple"` is testing, not leaking - but
    still fail on a real key block or a provider token, because those are
    never a fixture anybody should have typed in.
    """
    out: list[tuple[str, int]] = []
    for category, pattern in VALUE_PATTERNS:
        if is_test and category == "credential-assignment":
            continue
        for match in pattern.finditer(data):
            if category == "credential-assignment" and not _looks_like_a_credential(
                match.group(1), data, match.start(1)
            ):
                continue
            line = data.count(b"\n", 0, match.start()) + 1
            out.append((category, line))
            break
    return out


def _looks_like_a_credential(value: bytes, data: bytes, start: int) -> bool:
    """Whether an assignment's right-hand side is a value rather than code.

    `password=request.password` and `secret = totp.generate_secret()` match
    the assignment shape and are code: the value is an expression, not a
    string. A credential that was typed in is a run of letters and digits,
    quoted or not, with no attribute access in it. Requiring both letters
    and digits is what separates a token from an English word.
    """
    if PLACEHOLDER.search(value):
        return False
    quoted = start > 0 and data[start - 1 : start] in (b'"', b"'")
    if not quoted and b"." in value:
        return False
    has_alpha = any(chr(c).isalpha() for c in value)
    has_digit = any(chr(c).isdigit() for c in value)
    return has_alpha and has_digit


def _is_test_path(relative: str) -> bool:
    parts = pathlib.PurePosixPath(relative).parts
    return any(p in ("tests", "test", "__tests__", "fixtures") for p in parts) or (
        pathlib.PurePosixPath(relative).name.startswith("test_")
    )


def tracked_files(root: pathlib.Path) -> list[str] | None:
    """Paths git tracks, or None when git is unavailable - the caller then
    walks the tree, and says so, because a walk also sees untracked files."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True,
            check=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return [p for p in proc.stdout.decode("utf-8", "surrogateescape").split("\0") if p]


def walk_files(root: pathlib.Path) -> list[str]:
    out: list[str] = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            full = pathlib.Path(base) / name
            out.append(full.relative_to(root).as_posix())
    return out


def scan_paths(root: pathlib.Path, paths: Iterable[str]) -> ScanResult:
    result = ScanResult(root=str(root), scanned_files=0)
    for relative in sorted(paths):
        full = root / relative
        if any(part in SKIP_DIRS for part in pathlib.PurePosixPath(relative).parts):
            continue
        try:
            size = full.stat().st_size
        except OSError:
            continue
        result.scanned_files += 1
        shapes = name_findings(relative)
        if size > MAX_FILE_BYTES:
            # Reported, not skipped silently: a 3 MB file is exactly where a
            # dumped database with a password column would live.
            result.notes.append(f"{relative}: {size} bytes, larger than the scan limit, not read")
            result.complete = False
            for category, severity in shapes:
                result.findings.append(Finding(relative, category, severity))
            continue
        try:
            data = full.read_bytes()
        except OSError:
            result.notes.append(f"{relative}: unreadable")
            result.complete = False
            continue
        values = value_findings(data, is_test=_is_test_path(relative))
        for category, line in values:
            result.findings.append(Finding(relative, category, "secret", line))
        if shapes and not values:
            for category, severity in shapes:
                result.findings.append(
                    Finding(relative, f"{category} (no secret-shaped value inside)", severity)
                )
    return result


def scan_history(root: pathlib.Path, result: ScanResult, *, max_blobs: int = 20000) -> None:
    """Check every blob reachable from HEAD for value patterns.

    Reports the *first* commit path that carried the blob. A secret that was
    committed and later removed is still in every clone, which is why this
    exists at all.
    """
    try:
        rev = subprocess.run(
            ["git", "-C", str(root), "rev-list", "--objects", "--all"],
            capture_output=True,
            check=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as problem:
        result.notes.append(f"history not scanned: {type(problem).__name__}")
        return
    seen: set[str] = set()
    checked = 0
    for line in rev.stdout.decode("utf-8", "surrogateescape").splitlines():
        sha, _, path = line.partition(" ")
        if not path or sha in seen:
            continue
        seen.add(sha)
        leaf = pathlib.PurePosixPath(path).name
        if any(part in SKIP_DIRS for part in pathlib.PurePosixPath(path).parts):
            continue
        if checked >= max_blobs:
            result.notes.append(f"history scan stopped at {max_blobs} blobs")
            result.complete = False
            break
        try:
            blob = subprocess.run(
                ["git", "-C", str(root), "cat-file", "-p", sha],
                capture_output=True,
                check=True,
                timeout=30,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        checked += 1
        if len(blob) > MAX_FILE_BYTES:
            continue
        for category, _line in value_findings(blob, is_test=_is_test_path(path)):
            result.findings.append(Finding(f"history:{path}", category, "secret"))
        _ = leaf
    result.history_scanned = True
    result.history_blobs = checked


def scan(root: pathlib.Path | str, *, history: bool = False) -> ScanResult:
    base = pathlib.Path(root).resolve()
    paths = tracked_files(base)
    if paths is None:
        result = scan_paths(base, walk_files(base))
        result.notes.append("git unavailable: walked the tree instead of the index")
    else:
        result = scan_paths(base, paths)
    if history:
        scan_history(base, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="repository root")
    parser.add_argument("--output", help="write the JSON note here (atomically)")
    parser.add_argument("--history", action="store_true", help="also scan git history")
    args = parser.parse_args(argv)

    result = scan(args.root, history=args.history)
    body = json.dumps(result.as_dict(), indent=2)
    if args.output:
        target = pathlib.Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(body, encoding="utf-8")
        os.replace(temporary, target)
    else:
        sys.stdout.write(body + "\n")

    verdict = "PASS" if result.passed else ("FAIL" if result.secrets else "UNKNOWN")
    sys.stderr.write(
        f"secrets scan: {verdict} - {result.scanned_files} files, "
        f"{len(result.secrets)} secret(s), {len(result.findings) - len(result.secrets)} shape finding(s)\n"
    )
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
