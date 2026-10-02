"""Release guards reject runtime files without disclosing their contents."""
import importlib.util
from pathlib import Path


def checker():
    path = Path(__file__).resolve().parents[1] / "scripts/check_release_inputs.py"
    spec = importlib.util.spec_from_file_location("release_inputs", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_datasets_and_credentials_are_rejected():
    check = checker().inspect
    for name in ("peers.json", "data/thread.json", ".threaddesk/note.txt", ".env", "copy.sqlite3", "export.tdbundle"):
        assert check(name, "100644", b"synthetic")
    assert check("src/link", "120000", b"/private/workspace")


def test_normal_sources_and_negative_tests_remain_allowed():
    check = checker().inspect
    assert check("src/threaddesk/example.py", "100644", b"print('ordinary source')") == []
    assert check("docs/schemas/example.json", "100644", b'{}') == []
    assert check("tests/test_fake_key.py", "100644", b"ghp_" + b"x" * 40) == []


def test_secret_shaped_value_in_product_file_is_rejected():
    assert checker().inspect("src/leak.txt", "100644", b"ghp_" + b"x" * 40)
