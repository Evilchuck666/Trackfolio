"""Bounded JPEG/PNG sources with inventory and identity checks; never writes images."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable
from pathlib import Path

from trackfolio.application.catalog import prepare_audio_source, validate_library_root
from trackfolio.application.tag_write_errors import (
    TagWriteCancelled,
    TagWriteConflict,
    TagWriteError,
)
from trackfolio.domain.tag_write import CoverCandidate, CoverFolder, CoverImage, FileFingerprint
from trackfolio.infrastructure.metadata import _image_info

MAX_COVER_BYTES = 15 * 1024 * 1024
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")


class FileCoverAccess:
    def _paths(self, root: Path, folder: Path) -> tuple[Path, ...]:
        root = validate_library_root(root)
        if folder.resolve(strict=True) != folder or not folder.is_relative_to(root):
            raise TagWriteConflict("The cover folder changed or is outside the library.")
        current = folder
        while current != root:
            if current.is_symlink() or current.is_junction():
                raise TagWriteConflict("Internal links are not followed when searching for covers.")
            current = current.parent
        return tuple(
            sorted(
                path
                for path in folder.iterdir()
                if path.suffix.casefold() in IMAGE_SUFFIXES
                and not stat.S_ISDIR(path.stat(follow_symlinks=False).st_mode)
            )
        )

    def _read(
        self, root: Path, path: Path, cancelled: Callable[[], bool]
    ) -> tuple[bytes, FileFingerprint]:
        prepare_audio_source(path, validate_library_root(root))
        before = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_COVER_BYTES:
            raise TagWriteError("The cover must be a nonempty regular file no larger than 15 MiB.")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise TagWriteConflict("The cover was replaced while opening it.")
            chunks = []
            remaining = MAX_COVER_BYTES + 1
            while remaining:
                if cancelled():
                    raise TagWriteCancelled("Cover read cancelled.")
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
        data = b"".join(chunks)
        after = path.stat(follow_symlinks=False)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) or len(data) != before.st_size:
            raise TagWriteConflict("The cover changed while being read.")
        return data, FileFingerprint(
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            hashlib.sha256(data).hexdigest(),
        )

    def scan(
        self, root: Path, folder: Path, cancelled: Callable[[], bool]
    ) -> tuple[CoverCandidate, ...]:
        candidates = []
        for path in self._paths(root, folder):
            try:
                data, fingerprint = self._read(root, path, cancelled)
                info = _image_info(data)
                if info is None or info[0] not in ("image/jpeg", "image/png"):
                    raise TagWriteError("The cover does not contain a valid JPEG/PNG image.")
                candidates.append(CoverCandidate(path, fingerprint, *info))
            except TagWriteCancelled:
                raise
            except Exception as exc:
                candidates.append(CoverCandidate(path, error=str(exc)))
        return tuple(candidates)

    def read(
        self, root: Path, candidate: CoverCandidate, cancelled: Callable[[], bool]
    ) -> CoverImage:
        if candidate.error or candidate.fingerprint is None:
            raise TagWriteError(candidate.error or "Could not prepare the cover.")
        data, fingerprint = self._read(root, candidate.path, cancelled)
        if fingerprint != candidate.fingerprint:
            raise TagWriteConflict("The cover changed after selection.")
        return CoverImage(
            candidate.path,
            root,
            fingerprint,
            candidate.mime_type,
            candidate.width,
            candidate.height,
            data,
        )

    def check(
        self, folder: CoverFolder, image: CoverImage | None, cancelled: Callable[[], bool]
    ) -> None:
        paths = self._paths(folder.library_root, folder.path)
        if paths != tuple(candidate.path for candidate in folder.candidates):
            raise TagWriteConflict("The folder's images changed; choose the cover again.")
        for candidate in folder.candidates:
            if candidate.fingerprint is not None:
                info = candidate.path.stat(follow_symlinks=False)
                old = candidate.fingerprint
                if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
                    old.device,
                    old.inode,
                    old.size,
                    old.modified_ns,
                ):
                    raise TagWriteConflict("An image changed after the folder was scanned.")
        if image is not None:
            _, fingerprint = self._read(folder.library_root, image.path, cancelled)
            if fingerprint != image.fingerprint:
                raise TagWriteConflict("The selected cover changed before publishing the song.")
