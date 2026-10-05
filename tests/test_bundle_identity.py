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
    assert 'version=_bundle["version"]' in spec
    assert module.package_version(ROOT) == "0.1.1rc1"
    assert module.package_version(ROOT) in (ROOT / "src" / "threaddesk" / "__init__.py").read_text(encoding="utf-8")
