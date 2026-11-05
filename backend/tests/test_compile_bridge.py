"""Stub MetaEditor to test build verification without touching any terminal."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "compile_bridge", Path(__file__).parents[2] / "infra/compile-mt5-bridge.py"
)
compiler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compiler)


@pytest.fixture()
def build(tmp_path, monkeypatch):
    source = tmp_path / "input.mq5"
    source.write_text("void OnTick() {}")
    editor = tmp_path / "MetaEditor.exe"
    editor.touch()
    prefix = tmp_path / "prefix"
    prefix.mkdir()
    output = tmp_path / "new-build"
    calls = []

    def install(*, errors=0, binary=True, with_log=True, returncode=0):
        def run(command, **kwargs):
            calls.append(command)
            if command[0] == "winepath":
                return SimpleNamespace(stdout="Z:\\new-build\\MolidoBridge.mq5\n")
            if with_log:
                (output / "MolidoBridge.log").write_text(
                    f"Result: {errors} errors, 0 warnings", encoding="utf-16"
                )
            if binary:
                (output / "MolidoBridge.ex5").write_bytes(b"stub compiled output")
            return SimpleNamespace(returncode=returncode)
        monkeypatch.setattr(compiler.subprocess, "run", run)

    def invoke():
        return compiler.compile_bridge(source=source, editor=editor, output=output,
                                       wine_prefix=prefix)
    return install, invoke, output, calls


def test_success_requires_log_and_fresh_binary_and_never_installs(build):
    install, invoke, output, calls = build
    install()
    assert invoke().is_file()
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["installed"] is False
    assert manifest["terminal_restarted"] is False
    assert not any("systemctl" in str(call) or "terminal64" in str(call) for call in calls)


@pytest.mark.parametrize("settings", [
    {"errors": 1}, {"binary": False}, {"with_log": False}, {"returncode": 1},
])
def test_failure_does_not_publish_success_manifest(build, settings):
    install, invoke, output, _ = build
    install(**settings)
    with pytest.raises(ValueError):
        invoke()
    assert not (output / "manifest.json").exists()


def test_existing_build_cannot_be_mistaken_for_new_success(build):
    install, invoke, output, calls = build
    output.mkdir()
    (output / "MolidoBridge.ex5").write_bytes(b"old binary")
    install()
    with pytest.raises(FileExistsError):
        invoke()
    assert (output / "MolidoBridge.ex5").read_bytes() == b"old binary"
    assert calls == []
