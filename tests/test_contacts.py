import pytest

from threaddesk.core.errors import SecretRejected
from threaddesk.services.contacts import Contact, ContactBook
from threaddesk.storage.json_store import JsonStore


def test_contact_model_preserves_roles_channels_and_work_relations(tmp_path):
    book = ContactBook(JsonStore(tmp_path))
    book.save(Contact(
        id="daniel", name="Daniel", roles=("owner",),
        channels={"email": "daniel@example.test", "github": "landjunge"},
        project_ids=("tollgate",), task_ids=("review-1",), marked=True,
        private={"note": "prefers email"},
    ))
    contact = book.find_channel("email", "DANIEL@example.test")
    assert contact and contact.project_ids == ("tollgate",)
    assert contact.task_ids == ("review-1",)
    assert contact.marked is True


def test_contact_export_never_contains_private_fields(tmp_path):
    book = ContactBook(JsonStore(tmp_path))
    book.save(Contact(id="studio", name="Studio", kind="organization", private={"note": "internal"}))
    exported = book.export()
    assert exported["contacts"] == [{
        "id": "studio", "name": "Studio", "kind": "organization", "roles": (),
        "channels": {}, "project_ids": (), "task_ids": (), "marked": False,
    }]
    assert "internal" not in str(exported)


def test_contact_rejects_credentials_before_writing(tmp_path):
    book = ContactBook(JsonStore(tmp_path))
    with pytest.raises(SecretRejected):
        book.save(Contact(id="bad", name="Bad", private={"API_KEY": "sk-test-12345678901234567890"}))
    assert not (tmp_path / "contacts.json").exists()
