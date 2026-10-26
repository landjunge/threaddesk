"""A package must identify its actual checkout, including local changes."""
import importlib.util
import json
from pathlib import Path
import subprocess


def test_package_identity_follows_commit_and_dirty_state(tmp_path):
    path = Path(__file__).parents[1] / "scripts/write_build_info.py"
    spec = importlib.util.spec_from_file_location("write_build_info", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    package = tmp_path / "src/threaddesk"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('__version__ = "0.1.2"\n')
    (tmp_path / ".gitignore").write_text('/src/threaddesk/_build_info.json\n')
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)

    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()

    git("add", ".")
    git("-c", "user.name=Build Test", "-c", "user.email=build@example.invalid", "commit", "-qm", "Initial source")
    first = module.write_build_info(tmp_path)
    assert first["source_commit"] == git("rev-parse", "HEAD")
    assert first["version"] == "0.1.2" and first["dirty"] is False
    assert json.loads((package / "_build_info.json").read_text()) == first
    assert module.write_build_info(tmp_path)["dirty"] is False
    (tmp_path / "new-source.py").write_text("# New source\n")
    assert module.write_build_info(tmp_path)["dirty"] is True
    git("add", "new-source.py")
    git("-c", "user.name=Build Test", "-c", "user.email=build@example.invalid", "commit", "-qm", "New source")
    latest = module.write_build_info(tmp_path)
    assert latest["source_commit"] == git("rev-parse", "HEAD") != first["source_commit"]
    assert latest["dirty"] is False
