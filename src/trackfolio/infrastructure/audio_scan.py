"""Exploración de música recursiva, cancelable y sin atravesar enlaces."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from trackfolio.application.import_catalog import (
    AudioScanError,
    AudioSource,
    ImportIssue,
    ScanResult,
)


class FileSystemAudioScanner:
    def scan(
        self,
        root: Path,
        is_cancelled: Callable[[], bool],
        on_discovered: Callable[[int], None],
    ) -> ScanResult:
        sources: list[AudioSource] = []
        issues: list[ImportIssue] = []
        directories = [root]
        while directories:
            if is_cancelled():
                return ScanResult(tuple(sources), tuple(issues), completed=False)
            directory = directories.pop()
            try:
                # A directory may have changed after its entry was discovered.
                if directory != root and (directory.is_symlink() or directory.is_junction()):
                    continue
                with os.scandir(directory) as iterator:
                    entries = sorted(iterator, key=lambda entry: entry.name)
            except OSError as exc:
                message = f"No se puede explorar la carpeta {directory}: {exc}"
                if directory == root:
                    raise AudioScanError(message) from exc
                issues.append(ImportIssue(directory, "scan", message))
                continue
            children: list[Path] = []
            for entry in entries:
                if is_cancelled():
                    return ScanResult(tuple(sources), tuple(issues), completed=False)
                path = Path(entry.path)
                try:
                    if entry.is_symlink() or path.is_junction():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        children.append(path)
                    elif entry.is_file(follow_symlinks=False) and path.suffix.casefold() in (
                        ".flac",
                        ".mp3",
                    ):
                        sources.append(AudioSource(path, path.relative_to(root).as_posix()))
                        on_discovered(len(sources))
                except OSError as exc:
                    issues.append(
                        ImportIssue(path, "scan", f"No se puede inspeccionar {path}: {exc}")
                    )
            directories.extend(reversed(children))
        sources.sort(key=lambda source: source.relative_path)
        return ScanResult(tuple(sources), tuple(issues))
