"""A configured system alias binds the database and its owner files together."""
import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.services.commands.model import workspace_identity
from threaddesk.services.graph_read import GraphReadService
from threaddesk.services.graph_view_control import GraphViewControlService
from threaddesk.services.graph_views import GraphViewService
from threaddesk.storage.sqlite_store import SQLiteStore


def test_sqlite_alias_is_bound_once_and_internal_link_guards_remain(tmp_path):
    original, other = tmp_path / "original", tmp_path / "other"
    original.mkdir();other.mkdir()
    alias = tmp_path / "configured-alias"
    alias.symlink_to(original, target_is_directory=True)
    store = SQLiteStore(alias)
    try:
        thread = ThreadService(store).create("Bound original")
        control = GraphViewControlService(store)
        control.reset_runtime()
        identity = workspace_identity(store)
        assert store.workspace_path == original.resolve()
        alias.unlink();alias.symlink_to(other, target_is_directory=True)
        control.register()
        assert workspace_identity(store) == identity
        assert store.get_thread(thread.id).title == "Bound original"
        assert (original / "graph-view-control.json").is_file()
        assert not (other / "graph-view-control.json").exists()
        assert GraphReadService(store).change_status(workspace_id=identity)["status"] == "ready"
        outside = other / "foreign-view.json"
        outside.write_text('{"schema_version":1,"views":{},"operations":{}}')
        (original / "graph-views.json").symlink_to(outside)
        with pytest.raises(ManagementError) as denied:
            GraphViewService(store).list()
        assert denied.value.code == "file_integrity"
        assert outside.read_text() == '{"schema_version":1,"views":{},"operations":{}}'
    finally:
        store.connection.close()
