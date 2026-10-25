"""Compile a bridge into a new output directory; never install or restart MT5.

Use the existing host's MetaEditor, optionally through its existing Wine prefix.
Official CLI: https://www.metatrader5.com/en/metaeditor/help/beginning/integration_ide
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess


def compile_bridge(*, source: pathlib.Path, editor: pathlib.Path,
                   output: pathlib.Path, wine_prefix: pathlib.Path | None = None) -> pathlib.Path:
    if not source.is_file() or not editor.is_file():
        raise ValueError("source and MetaEditor must be existing files")
    environment = os.environ.copy()
    if os.name != "nt":
        if wine_prefix is None or not wine_prefix.is_dir():
            raise ValueError("select the existing Wine prefix explicitly; none is created")
        environment["WINEPREFIX"] = str(wine_prefix.resolve())
    # A new directory rules out stale EX5s and cannot overwrite an installed EA.
    output.mkdir(parents=True, exist_ok=False)
    staged = output / "MolidoBridge.mq5"
    shutil.copyfile(source, staged)
    command = [str(editor.resolve())]
    compile_path = str(staged.resolve())
    if os.name != "nt":
        converted = subprocess.run(
            ["winepath", "-w", compile_path], env=environment,
            check=True, capture_output=True, text=True, timeout=15,
        )
        compile_path = converted.stdout.strip()
        if not compile_path:
            raise ValueError("winepath did not return the staged source path")
        command.insert(0, "wine")
    command += [f"/compile:{compile_path}", "/log"]
    result = subprocess.run(
        command, check=False, env=environment, capture_output=True, timeout=60,
    )
    log = output / "MolidoBridge.log"
    binary = output / "MolidoBridge.ex5"
    if not log.is_file():
        raise ValueError("MetaEditor produced no log; compilation is unverified")
    raw = log.read_bytes()
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    text = raw.decode(encoding, errors="replace")
    summaries = re.findall(r"\b(\d+) errors?,\s*(\d+) warnings?\b", text, re.IGNORECASE)
    if result.returncode != 0 or not summaries or summaries[-1][0] != "0":
        raise ValueError("MetaEditor did not confirm zero errors; inspect the staged log")
    if not binary.is_file() or binary.stat().st_size == 0:
        raise ValueError("zero-error log without a fresh non-empty EX5 is not success")
    manifest = {
        "source_sha256": hashlib.sha256(staged.read_bytes()).hexdigest(),
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "warnings": int(summaries[-1][1]),
        "installed": False,
        "terminal_restarted": False,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return binary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=pathlib.Path,
                        default=pathlib.Path(__file__).parent / "mql5/MolidoBridge.mq5")
    parser.add_argument("--metaeditor", type=pathlib.Path, required=True)
    parser.add_argument("--wine-prefix", type=pathlib.Path)
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    args = parser.parse_args()
    try:
        binary = compile_bridge(source=args.source, editor=args.metaeditor,
                                output=args.output_dir, wine_prefix=args.wine_prefix)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Compilation not verified: {exc}\n")
    print(f"Compiled for review: {binary}; not installed and no terminal restarted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
