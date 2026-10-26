"""Explicit format registry; adding an adapter never enables execution."""

from __future__ import annotations

from pathlib import PurePath

# suffix -> family, MIME, extraction adapter, preview kind, external opening
FORMATS: dict[str, tuple[str, str, str, str, bool]] = {}


def _register(
    suffixes, family, mime, adapter="metadata", preview="metadata", external=True
):
    for suffix in suffixes.split():
        FORMATS[suffix] = (
            family,
            mime if isinstance(mime, str) else mime[suffix],
            adapter,
            preview,
            external,
        )


_register(".txt .md .markdown .rst", "document", "text/plain", "text", "text")
_register(".html .htm", "document", "text/html", "html")
_register(".pdf", "document", "application/pdf", "pdf", "pdf")
_register(".doc", "document", "application/msword")
_register(
    ".docx",
    "document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "office",
    "text",
)
_register(
    ".odt", "document", "application/vnd.oasis.opendocument.text", "office", "text"
)
_register(".rtf", "document", "application/rtf", "rtf", "text")
_register(".epub", "document", "application/epub+zip", "epub", "text")
_register(".csv .tsv", "spreadsheet", "text/plain", "text", "text")
_register(".xls", "spreadsheet", "application/vnd.ms-excel")
_register(
    ".xlsx",
    "spreadsheet",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "office",
    "text",
)
_register(
    ".ods",
    "spreadsheet",
    "application/vnd.oasis.opendocument.spreadsheet",
    "office",
    "text",
)
_register(".ppt", "presentation", "application/vnd.ms-powerpoint")
_register(
    ".pptx",
    "presentation",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "office",
    "text",
)
_register(
    ".odp",
    "presentation",
    "application/vnd.oasis.opendocument.presentation",
    "office",
    "text",
)
_register(".key", "presentation", "application/vnd.apple.keynote")
for _suffix, _mime in {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".heic": "image/heic",
    ".svg": "image/svg+xml",
}.items():
    _register(
        _suffix,
        "image",
        _mime,
        preview="image"
        if _suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp"}
        else "metadata",
    )
for _suffix, _mime in {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".aac": "audio/aac",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
}.items():
    _register(_suffix, "audio", _mime, preview="audio")
for _suffix, _mime in {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
}.items():
    _register(
        _suffix,
        "video",
        _mime,
        preview="video" if _suffix in {".mp4", ".mov", ".webm"} else "metadata",
    )
_register(
    ".py .js .ts .jsx .tsx .sh .bash .zsh .bat .cmd .ps1 .rb .php .pl",
    "source",
    "text/plain",
    "text",
    "text",
    False,
)
_register(
    ".json .xml .yaml .yml .toml .sql .log .ini .cfg",
    "source",
    "text/plain",
    "text",
    "text",
)
_register(
    ".css .c .h .cpp .rs .go .java .swift .kt",
    "source",
    "text/plain",
    "text",
    "text",
    False,
)
_register(".zip .tar .gz .tgz", "archive", "application/octet-stream", "archive")
_register(".7z", "archive", "application/x-7z-compressed")
_register(
    ".exe .com .command .app .dmg .pkg .msi .dll .so .dylib .jar .scpt .workflow",
    "executable",
    "application/octet-stream",
    external=False,
)


def descriptor(filename: str) -> dict:
    suffix = PurePath(str(filename)).suffix.casefold()
    family, mime, adapter, preview, external = FORMATS.get(
        suffix, ("unknown", "application/octet-stream", "metadata", "metadata", False)
    )
    return {
        "suffix": suffix,
        "format": family,
        "media_type": mime,
        "manage": True,
        "index": adapter != "metadata",
        "preview": preview != "metadata",
        "preview_kind": preview,
        "external_open": external,
        "adapter": adapter,
        "index_reason": "" if adapter != "metadata" else "metadata_only",
    }

# Preserve previously accepted library suffixes alongside the shared registry.
_register(".bmp", "image", "image/bmp", preview="image")
_register(".heif", "image", "image/heif")
_register(".aiff", "audio", "audio/aiff", preview="audio")
_register(".m4v", "video", "video/mp4", preview="video")
