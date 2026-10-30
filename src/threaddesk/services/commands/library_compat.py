"""Expose existing package/journal import paths without a second importer."""
from pathlib import Path
import tempfile

from threaddesk.services.commands.model import CommandSpec
from threaddesk.services.commands.schemas import TEXT, PAGE, array, choice, obj, page


def specifications():
    yield CommandSpec("library.journal_status", "library", "Read paginated historical import journal details",
                      obj({"collection": choice("failures", "pending", "outstanding"), **PAGE}), _journal_status)
    yield CommandSpec("library.folder_import", "library", "Import the existing relative-path folder format",
                      obj({"path": TEXT}, ("path",)), _folder, effect="external", scope="workspace.write",
                      affects_index=True)
    item = obj({"name": TEXT, "path": TEXT, "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"}},
               ("name", "path", "sha256"))
    yield CommandSpec("library.selected_import", "library", "Import explicitly selected named originals",
                      obj({"files": {**array(item, 2000), "minItems": 1}}, ("files",)), _selected,
                      effect="external", scope="workspace.write", affects_index=True)
    yield CommandSpec("library.package_import", "library", "Import the existing bounded ZIP package format",
                      obj({"path": TEXT, "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"}}, ("path", "sha256")),
                      _package, effect="external", scope="workspace.write",
                      affects_index=True)
    yield CommandSpec("library.journal_resume", "library", "Resume the existing historical import journal",
                      obj(), _resume, effect="external", scope="workspace.write", affects_index=True)


def _package(service, arguments):
    from threaddesk.services.library_import import LibraryImporter
    from threaddesk.services.commands.artifacts import read_verified_file
    body = read_verified_file(arguments["path"], limit=256 * 1024 * 1024, sha256=arguments["sha256"])
    with tempfile.TemporaryDirectory(prefix="threaddesk-package-command-") as directory:
        path = Path(directory) / "package.zip"
        path.write_bytes(body)
        return LibraryImporter(service.store).import_zip_package(path)


def _resume(service, _arguments):
    from threaddesk.services.library_import import LibraryImporter
    return LibraryImporter(service.store).resume()


def _journal_status(service, arguments):
    from threaddesk.services.library_import import LibraryImporter
    catalog = LibraryImporter(service.store).catalog()
    collection = arguments.get("collection", "failures")
    return {"schema": "threaddesk.library.journal.v1", "collection": collection,
            **{key: catalog[key] for key in ("counts", "source", "complete")},
            **page(catalog[collection], arguments)}


def _folder(service, arguments):
    from threaddesk.services.library_import import LibraryImporter
    return LibraryImporter(service.store).import_tree(Path(arguments["path"]))


def _selected(service, arguments):
    from threaddesk.services.library_import import LibraryImporter, MAX_FILE_BYTES, MAX_BATCH_BYTES
    from threaddesk.services.commands.artifacts import read_verified_file
    from threaddesk.core.errors import ManagementError
    with tempfile.TemporaryDirectory(prefix="threaddesk-selected-command-") as directory:
        named, total = [], 0
        for index, item in enumerate(arguments["files"]):
            body = read_verified_file(item["path"], limit=MAX_FILE_BYTES, sha256=item["sha256"])
            total += len(body)
            if total > MAX_BATCH_BYTES:
                raise ManagementError("import_limit", "Selected originals exceed the batch budget")
            path = Path(directory) / str(index)
            path.write_bytes(body)
            named.append((item["name"], path))
        return LibraryImporter(service.store).import_files(named)
