"""TD-NM8: sichtbare Migration muss als echte Seite abnehmbar sein."""

from fastapi.testclient import TestClient
from pathlib import Path

from threaddesk.ui.server import create_app


def test_migration_page_is_a_real_bilingual_surface(monkeypatch, tmp_path):
    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    client = TestClient(create_app())

    german = client.get("/migration?lang=de")
    english = client.get("/migration?lang=en")

    assert german.status_code == 200
    assert english.status_code == 200
    assert 'data-testid="migration-center"' in german.text
    assert 'data-testid="bundle-file"' in german.text
    assert 'data-testid="dry-run"' in german.text
    assert 'data-testid="import-confirm"' in german.text
    assert 'data-testid="migration-center"' in english.text
    assert 'data-testid="bundle-file"' in english.text
    assert 'data-testid="dry-run"' in english.text
    assert 'data-testid="import-confirm"' in english.text


def test_bundle_selection_cannot_start_import_implicitly():
    script = (Path(__file__).parents[1] / "src/threaddesk/ui/static/migration.js").read_text()
    assert "addEventListener('submit'" not in script
    assert "fetch(" not in script
    assert "confirm.disabled = !valid" in script
