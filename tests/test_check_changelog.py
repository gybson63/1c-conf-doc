from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
CODE_PREFIX = "src/onec_conf_doc/"
CHANGELOG = "CHANGELOG.md"


def _load_check_changelog() -> ModuleType:
    path = ROOT / "scripts" / "check_changelog.py"
    spec = importlib.util.spec_from_file_location("check_changelog", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_check_changelog_passes_without_code_changes(monkeypatch) -> None:
    mod = _load_check_changelog()
    monkeypatch.setattr(mod, "staged_files", lambda repo_root=ROOT: ["README.md"])
    assert mod.check_changelog() is None


def test_check_changelog_requires_changelog_for_code_changes(monkeypatch) -> None:
    mod = _load_check_changelog()
    monkeypatch.setattr(
        mod,
        "staged_files",
        lambda repo_root=ROOT: [f"{CODE_PREFIX}parser/xml_parser.py"],
    )
    monkeypatch.setattr(mod, "staged_diff", lambda path, repo_root=ROOT: "")

    error = mod.check_changelog()
    assert error is not None
    assert "CHANGELOG.md must be updated" in error


def test_check_changelog_passes_when_changelog_staged(monkeypatch) -> None:
    mod = _load_check_changelog()
    monkeypatch.setattr(
        mod,
        "staged_files",
        lambda repo_root=ROOT: [f"{CODE_PREFIX}parser/xml_parser.py", CHANGELOG],
    )
    monkeypatch.setattr(
        mod,
        "staged_diff",
        lambda path, repo_root=ROOT: "- entry\n" if path == CHANGELOG else "",
    )
    assert mod.check_changelog() is None
