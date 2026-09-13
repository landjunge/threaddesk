"""Local, file-only migration services.

This package deliberately contains no Notion client and no network transport.
"""

from threaddesk.services.migration.bundle import (
    BundleLimits,
    BundleValidationError,
    ValidatedBundle,
    validate_bundle,
)
from threaddesk.services.migration.diff import DryRunPlanner
from threaddesk.services.migration.importer import (
    AtomicImportError,
    AtomicImportService,
    ImportBlocked,
    ImportOutcomeUncertain,
)
from threaddesk.services.migration.mapper import NotionMapper

__all__ = [
    "BundleLimits",
    "BundleValidationError",
    "ValidatedBundle",
    "DryRunPlanner",
    "AtomicImportError",
    "AtomicImportService",
    "ImportBlocked",
    "ImportOutcomeUncertain",
    "NotionMapper",
    "validate_bundle",
]
