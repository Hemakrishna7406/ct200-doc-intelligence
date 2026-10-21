"""Filesystem safety for ingestion.

The ingestion endpoint takes a *server-side path*. Left unguarded that is an
arbitrary-file-read primitive: a caller could ask the service to open any file
on the host. ``resolve_document_path`` confines every read to a single
configured root (``CT200_DOCUMENT_ROOT``) and rejects anything that escapes it,
including via ``..`` or a symlink.
"""

from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.errors import IngestError


def document_root() -> Path:
    return Path(settings.document_root).resolve()


def resolve_document_path(path: str) -> Path:
    """Resolve ``path`` and guarantee it is a real file inside the root.

    Raises ``IngestError`` (HTTP 400) for anything that is not.
    """
    if not path or not path.strip():
        raise IngestError("path must be a non-empty string")

    root = document_root()
    # Relative paths resolve against the working directory (matching how the
    # CLI/scripts refer to "data/ct200_manual.pdf"); absolute paths are used
    # as given. Either way the result must land inside the root.
    resolved = Path(path).resolve()

    # resolve() collapses '..' and follows symlinks, so this single check
    # rejects traversal *and* symlinks that point outside the root
    if resolved != root and root not in resolved.parents:
        raise IngestError(
            f"path is outside the permitted document root ({root}); "
            "ingestion is restricted to files under that directory"
        )
    if resolved == root:
        raise IngestError("path refers to the document root, not a file")
    if not resolved.is_file():
        raise IngestError(f"not a regular file: {path}")
    if resolved.suffix.lower() != ".pdf":
        raise IngestError("only .pdf files can be ingested")

    return resolved
