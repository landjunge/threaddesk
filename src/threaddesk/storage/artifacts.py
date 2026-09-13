"""Content-addressed files published before an atomic database commit."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path


class ArtifactError(RuntimeError):
    pass


@dataclass(frozen=True)
class PublishedArtifact:
    sha256: str
    size: int
    relative_path: str
    path: Path
    created: bool

    def to_record(self) -> dict:
        return {
            "sha256": self.sha256,
            "size": self.size,
            "relative_path": self.relative_path,
            "media_type": "text/markdown",
        }


class ContentAddressedArtifacts:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = Path(workspace_root)
        self.root = self.workspace_root / "artifacts"

    @staticmethod
    def digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def stage(self, data: bytes, staging_root: Path) -> Path:
        digest = self.digest(data)
        staging_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = staging_root / digest
        path.write_bytes(data)
        path.chmod(0o600)
        return path

    def publish(self, staged: Path) -> PublishedArtifact:
        digest = staged.name
        data = staged.read_bytes()
        if self.digest(data) != digest:
            raise ArtifactError("artifact_stage_checksum")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = self.root / digest
        created = not target.exists()
        if created:
            staged.replace(target)
            target.chmod(0o600)
        elif self.digest(target.read_bytes()) != digest:
            raise ArtifactError("artifact_existing_checksum")
        return PublishedArtifact(
            sha256=digest,
            size=len(data),
            relative_path=f"artifacts/{digest}",
            path=target,
            created=created,
        )

    @staticmethod
    def cleanup_if_created(artifact: PublishedArtifact) -> None:
        if artifact.created and artifact.path.exists():
            artifact.path.unlink()
