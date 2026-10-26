"""Read the macOS default application without launching it."""
from __future__ import annotations

import ctypes
from pathlib import Path
import sys

from threaddesk.services.library_files.state import fail


def default_application(path: Path) -> str:
    if sys.platform != "darwin":
        fail("external_open_unavailable", "Öffnen ist nur im lokalen Mac-Desktop verfügbar.")
    core = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    launch = ctypes.CDLL("/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/LaunchServices")
    core.CFURLCreateFromFileSystemRepresentation.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_bool]
    core.CFURLCreateFromFileSystemRepresentation.restype = ctypes.c_void_p
    core.CFURLGetFileSystemRepresentation.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_void_p, ctypes.c_long]
    core.CFURLGetFileSystemRepresentation.restype = ctypes.c_bool
    core.CFRelease.argtypes = [ctypes.c_void_p]
    launch.LSCopyDefaultApplicationURLForURL.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    launch.LSCopyDefaultApplicationURLForURL.restype = ctypes.c_void_p
    raw = bytes(path)
    file_url = core.CFURLCreateFromFileSystemRepresentation(None, raw, len(raw), False)
    if not file_url:
        fail("external_open_unavailable", "Dateipfad kann nicht aufgelöst werden.")
    error = ctypes.c_void_p()
    application = None
    try:
        application = launch.LSCopyDefaultApplicationURLForURL(file_url, 0xFFFFFFFF, ctypes.byref(error))
        if not application:
            fail("no_default_application", "Kein zugeordnetes Standardprogramm gefunden.")
        output = ctypes.create_string_buffer(4096)
        if not core.CFURLGetFileSystemRepresentation(application, True, output, len(output)):
            fail("external_open_unavailable", "Standardprogramm kann nicht aufgelöst werden.")
        return output.value.decode("utf-8")
    finally:
        core.CFRelease(file_url)
        if application:
            core.CFRelease(application)
        if error:
            core.CFRelease(error)
