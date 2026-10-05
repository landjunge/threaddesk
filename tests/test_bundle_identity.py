"""The Mac package version comes from threaddesk.__version__ and names its commit."""

from __future__ import annotations

import importlib.util
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def provenance():
    path = ROOT / "scripts" / "package_provenance.py"
    spec = importlib.util.spec_from_file_location("package_provenance", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_bundle_version_comes_from_the_single_source() -> None:
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    spec = (ROOT / "packaging" / "ThreadDesk.spec").read_text(encoding="utf-8")
    module = provenance()
    assert 'version = {attr = "threaddesk.__version__"}' in project
    assert 'version = "0.1.1rc1"' not in project
    assert "0.1.1rc1" not in spec
    assert 'version=_bundle["macos_version"]' in spec
    assert module.package_version(ROOT) == "0.1.1rc1"
    assert module.package_version(ROOT) in (ROOT / "src" / "threaddesk" / "__init__.py").read_text(
        encoding="utf-8"
    )


def test_bundle_names_the_source_commit() -> None:
    module = provenance()
    settings = module.bundle_settings(ROOT)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    assert settings["version"] == module.package_version(ROOT)
    assert settings["source_commit"] == commit
    assert settings["info_plist"]["CFBundleVersion"] == settings["macos_version"]
    assert settings["info_plist"]["ThreadDeskSourceCommit"] == commit


def test_written_info_plist_keeps_version_and_commit(tmp_path: Path) -> None:
    if sys.platform != "darwin":
        pytest.skip("macOS Info.plist")
    module = provenance()
    settings = module.bundle_settings(ROOT)
    path = tmp_path / "ThreadDesk.app" / "Contents" / "Info.plist"
    module.write_macos_info_plist(path, settings)
    lint = subprocess.run(["/usr/bin/plutil", "-lint", str(path)], capture_output=True, text=True)
    assert lint.returncode == 0, lint.stderr
    plist = plistlib.loads(path.read_bytes())
    assert plist["CFBundleShortVersionString"] == settings["macos_version"]
    assert plist["CFBundleVersion"] == settings["macos_version"]
    assert plist["ThreadDeskSourceCommit"] == settings["source_commit"]
    assert plist["CFBundleIdentifier"] == "de.netzwerkpunkt.threaddesk"
    assert plist["CFBundleShortVersionString"] != "0.0.0"


@pytest.mark.parametrize("label, expected", [
    ("0.1.1rc1", "0.1.1"), ("1.2.3", "1.2.3"), ("2.3.4b2", "2.3.4"),
    ("3.4.5a1", "3.4.5"),
])
def test_macos_numeric_version_and_full_product_label(label, expected):
    module = provenance()
    assert module.macos_release_version(label) == expected
    settings = module.bundle_settings(ROOT)
    assert settings["info_plist"]["ThreadDeskProductVersion"] == module.package_version(ROOT)
    assert settings["macos_version"].split(".") == ["0", "1", "1"]


@pytest.mark.parametrize("label", ["", "1.2", "1.2.3.4", "1.2.3garbage", "rc1", "1.2.3\n"])
def test_invalid_macos_product_versions_fail_closed(label):
    with pytest.raises(ValueError):
        provenance().macos_release_version(label)
