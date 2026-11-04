"""Exclusive backups, verified publication and durable per-operation write journals."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from trackfolio.application.catalog import (
    AUDIO_SUFFIXES,
    prepare_audio_source,
    validate_library_root,
)
from trackfolio.application.write_tags import (
    TagJournalError,
    TagPublishedError,
    TagWriteCancelled,
    TagWriteConflict,
    TagWriteError,
    WriteTarget,
)
from trackfolio.domain.catalog_edit import EditableValues, EditField
from trackfolio.domain.tag_write import (
    AlbumNfoItem,
    AlbumNfoSong,
    AlbumNfoTrack,
    AlbumNfoValues,
    CoverCandidate,
    CoverFolder,
    CoverImage,
    FileFingerprint,
    PendingTagOperation,
    PlannedTags,
    TagCatalogSnapshot,
    TagDifference,
    TagRecoveryState,
    TagWriteItem,
    TagWritePreview,
    TagWriteReport,
    TagWriteRequest,
)


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        try:
            os.fsync(descriptor)
        except OSError as exc:
            if exc.errno not in (errno.EINVAL, errno.ENOTSUP):
                raise
    finally:
        os.close(descriptor)


def _writable(path: Path, *, directory: bool = False) -> None:
    mode = path.stat().st_mode
    if not mode & 0o222 or not os.access(path, os.W_OK | (os.X_OK if directory else 0)):
        raise TagWriteError(f"No write permission: {path}")


def _plain_directory(path: Path) -> None:
    if path.is_symlink() or path.is_junction():
        raise TagWriteError(f"Links are not used as backup directories: {path}")
    path.mkdir(mode=0o700, exist_ok=True)
    if not path.is_dir():
        raise TagWriteError(f"Invalid directory: {path}")
    _sync_directory(path.parent)


def _copy_windows_metadata(source: Path, target: Path) -> None:
    """Copy the security descriptor and named streams using Windows' native APIs."""
    import ctypes
    from ctypes import wintypes

    kernel = cast(Any, ctypes).WinDLL("kernel32", use_last_error=True)
    security = cast(Any, ctypes).WinDLL("advapi32", use_last_error=True)
    required = wintypes.DWORD()
    info = 0x7  # owner, group and DACL; never SACL/privileged audit information.
    security.GetFileSecurityW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    security.GetFileSecurityW(str(source), info, None, 0, ctypes.byref(required))
    if not required.value:
        raise TagWriteError("Could not read Windows file security.")
    descriptor = ctypes.create_string_buffer(required.value)
    if not security.GetFileSecurityW(
        str(source), info, descriptor, required.value, ctypes.byref(required)
    ):
        raise TagWriteError("Could not read the file ACL.")
    security.GetSecurityDescriptorControl.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    control, revision = wintypes.WORD(), wintypes.DWORD()
    if not security.GetSecurityDescriptorControl(
        descriptor, ctypes.byref(control), ctypes.byref(revision)
    ):
        raise TagWriteError("Could not read file permission inheritance.")
    # Keep a protected DACL protected, and inherited permissions inheritable.
    info |= 0x80000000 if control.value & 0x1000 else 0x20000000
    # SetNamedSecurityInfo would merge parent ACEs into an unprotected DACL.
    # This lower-level API applies the original descriptor without that merge.
    security.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    if not security.SetFileSecurityW(str(target), info, descriptor):
        raise TagWriteError("Could not preserve file owner, group and ACL.")

    security.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p

    def security_text(path: Path) -> str:
        length = wintypes.DWORD()
        security.GetFileSecurityW(str(path), 7, None, 0, ctypes.byref(length))
        buffer = ctypes.create_string_buffer(length.value)
        if not length.value or not security.GetFileSecurityW(
            str(path), 7, buffer, length.value, ctypes.byref(length)
        ):
            raise TagWriteError("Could not verify Windows permissions.")
        value = wintypes.LPWSTR()
        if not security.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            buffer, 1, 7, ctypes.byref(value), None
        ):
            raise TagWriteError("Could not compare Windows security.")
        try:
            return value.value or ""
        finally:
            kernel.LocalFree(value)

    original_security, copied_security = security_text(source), security_text(target)

    def permissions(value: str) -> str:
        # Windows may mark auto-inheritance as processed when assigning an identical
        # ACL. These bookkeeping flags do not change any ACE or DACL protection.
        return re.sub(
            r"D:([A-Z]*)",
            lambda match: "D:" + match[1].replace("AI", "").replace("AR", ""),
            value,
        )

    if permissions(original_security) != permissions(copied_security):
        raise TagWriteError(
            "The copy does not preserve the original owner, group and DACL. "
            f"Original: {original_security}; copy: {copied_security}"
        )

    class StreamData(ctypes.Structure):
        _fields_ = [("size", ctypes.c_longlong), ("name", wintypes.WCHAR * 296)]

    data = StreamData()
    kernel.FindFirstStreamW.restype = wintypes.HANDLE
    kernel.FindFirstStreamW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.FindNextStreamW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel.FindClose.argtypes = [wintypes.HANDLE]
    handle = kernel.FindFirstStreamW(str(source), 0, ctypes.byref(data), 0)
    if handle == ctypes.c_void_p(-1).value:
        if cast(Any, ctypes).get_last_error() in (1, 38, 50, 87):
            return
        raise TagWriteError("Could not inspect Windows streams.")
    try:
        while True:
            name = str(data.name)
            if name != "::$DATA":
                if not name.startswith(":") or any(char in name for char in ("/", "\\")):
                    raise TagWriteError("Invalid stream name.")
                with (
                    open(str(source) + name, "rb") as incoming,
                    open(str(target) + name, "wb") as outgoing,
                ):
                    shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
                    outgoing.flush()
                    os.fsync(outgoing.fileno())
                with (
                    open(str(source) + name, "rb") as incoming,
                    open(str(target) + name, "rb") as copied,
                ):
                    if (
                        hashlib.file_digest(incoming, "sha256").digest()
                        != hashlib.file_digest(copied, "sha256").digest()
                    ):
                        raise TagWriteError("Could not verify a Windows stream.")
            if not kernel.FindNextStreamW(handle, ctypes.byref(data)):
                if cast(Any, ctypes).get_last_error() != 38:
                    raise TagWriteError("Could not enumerate all file streams.")
                break
    finally:
        kernel.FindClose(handle)


def _copy_macos_metadata(source: Path, target: Path) -> None:
    """Darwin's Python lacks os.getxattr; copy ACLs and xattrs with libSystem."""
    import ctypes

    system = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    system.copyfile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_uint32]
    if system.copyfile(os.fsencode(source), os.fsencode(target), None, 7):
        raise OSError(ctypes.get_errno(), "Could not preserve macOS metadata.")
    system.listxattr.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
    system.listxattr.restype = ctypes.c_ssize_t
    system.getxattr.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint32,
        ctypes.c_int,
    ]
    system.getxattr.restype = ctypes.c_ssize_t

    def attributes(path: Path) -> dict[bytes, bytes]:
        filename = os.fsencode(path)
        length = system.listxattr(filename, None, 0, 1)
        if length < 0:
            raise OSError(ctypes.get_errno(), "Could not read macOS attributes.")
        names = ctypes.create_string_buffer(length)
        if system.listxattr(filename, names, length, 1) != length:
            raise TagWriteError("The attributes changed during verification.")
        values = {}
        for name in names.raw.split(b"\0"):
            if not name:
                continue
            size = system.getxattr(filename, name, None, 0, 0, 1)
            if size < 0:
                raise OSError(ctypes.get_errno(), "Could not read a macOS attribute.")
            # Resource forks can be large: compare bounded chunks via their file stream.
            if name == b"com.apple.ResourceFork":
                with (path / "..namedfork" / "rsrc").open("rb") as fork:
                    values[name] = hashlib.file_digest(fork, "sha256").digest()
                continue
            if size > 16 * 1024 * 1024:
                raise TagWriteError("macOS attribute too large to verify.")
            buffer = ctypes.create_string_buffer(size)
            if system.getxattr(filename, name, buffer, size, 0, 1) != size:
                raise TagWriteError("A macOS attribute changed during verification.")
            values[name] = buffer.raw
        return values

    system.acl_get_file.argtypes = [ctypes.c_char_p, ctypes.c_int]
    system.acl_get_file.restype = ctypes.c_void_p
    system.acl_to_text.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    system.acl_to_text.restype = ctypes.c_void_p
    system.acl_free.argtypes = [ctypes.c_void_p]

    def permissions(path: Path) -> bytes:
        acl = system.acl_get_file(os.fsencode(path), 0x100)
        if not acl:
            if ctypes.get_errno() == errno.ENOENT:
                # Darwin also returns ENOENT when an existing file has no ACL.
                path.stat()
                return b""
            raise OSError(ctypes.get_errno(), "Could not verify the macOS ACL.")
        text = None
        try:
            text = system.acl_to_text(acl, None)
            if not text:
                raise OSError(ctypes.get_errno(), "Could not compare the macOS ACL.")
            return ctypes.string_at(text)
        finally:
            if text:
                system.acl_free(text)
            system.acl_free(acl)

    if attributes(source) != attributes(target) or permissions(source) != permissions(target):
        raise TagWriteError("The copy does not preserve macOS attributes and ACL.")


def _copy_metadata(source: Path, target: Path) -> None:
    shutil.copystat(source, target, follow_symlinks=False)
    original, copied = source.stat(), target.stat()
    if sys.platform != "win32":
        if (original.st_uid, original.st_gid) != (copied.st_uid, copied.st_gid):
            os.chown(target, original.st_uid, original.st_gid)
        if sys.platform == "darwin":
            _copy_macos_metadata(source, target)
        elif hasattr(os, "listxattr"):
            for key in os.listxattr(source):
                value = os.getxattr(source, key)
                if os.getxattr(target, key) != value:
                    raise TagWriteError(f"Could not preserve attribute {key}.")
    elif os.name == "nt":
        # Compression/encryption require additional native operations, not a plain copy.
        if getattr(original, "st_file_attributes", 0) & (0x800 | 0x4000):
            raise TagWriteError(
                "Compressed or encrypted NTFS files are not replaced in this release."
            )
        _copy_windows_metadata(source, target)
    if stat.S_IMODE(source.stat().st_mode) != stat.S_IMODE(target.stat().st_mode):
        raise TagWriteError("Could not preserve file permissions.")


def _copy(
    source: Path,
    target: Path,
    cancelled: Callable[[], bool],
    created: Callable[[os.stat_result], None] | None = None,
) -> None:
    with source.open("rb") as incoming, target.open("xb") as outgoing:
        owned = os.fstat(outgoing.fileno())
        if created is not None:
            created(owned)
        while chunk := incoming.read(1024 * 1024):
            if cancelled():
                raise TagWriteCancelled("Copy cancelled; original preserved.")
            outgoing.write(chunk)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    current = target.stat(follow_symlinks=False)
    if (current.st_dev, current.st_ino) != (owned.st_dev, owned.st_ino):
        raise TagWriteConflict("The copy was replaced before verification.")
    _copy_metadata(source, target)
    # Persist metadata too, after copystat/chown/xattrs have finished.
    with target.open("r+b") as completed:
        os.fsync(completed.fileno())


def _values(data: dict[str, Any]) -> EditableValues:
    return EditableValues(
        **{
            **data,
            "artists": tuple(data["artists"]),
            "genres": tuple(data["genres"]),
            "album_artists": tuple(data.get("album_artists", ())),
        }
    )


def _load_cover(data: dict[str, Any]) -> CoverImage:
    return CoverImage(
        Path(data["path"]),
        Path(data["library_root"]),
        FileFingerprint(**data["fingerprint"]),
        data["mime_type"],
        data["width"],
        data["height"],
    )


def _load_cover_folder(data: dict[str, Any]) -> CoverFolder:
    return CoverFolder(
        Path(data["path"]),
        Path(data["library_root"]),
        tuple(data["file_ids"]),
        tuple(
            CoverCandidate(
                **{
                    **candidate,
                    "path": Path(candidate["path"]),
                    "fingerprint": FileFingerprint(**candidate["fingerprint"])
                    if candidate["fingerprint"]
                    else None,
                }
            )
            for candidate in data["candidates"]
        ),
        data["error"],
    )


def _preview_data(preview: TagWritePreview) -> dict[str, Any]:
    data = asdict(preview)
    # Source pixels are frozen in memory for publishing, never serialized in journals.
    for _, cover in data["request"]["covers"]:
        cover.pop("data", None)
    for item in data["items"]:
        if item["tags"] and item["tags"].get("cover"):
            item["tags"]["cover"].pop("data", None)
    return data


def _load_preview(data: dict[str, Any]) -> TagWritePreview:
    request = data["request"]
    items = []
    for value in data["items"]:
        snapshot = value["snapshot"]
        if snapshot:
            snapshot = TagCatalogSnapshot(
                **{
                    **snapshot,
                    "library_root": Path(snapshot["library_root"]),
                    "values": _values(snapshot["values"]),
                }
            )
        tags = value["tags"]
        if tags:
            tags = PlannedTags(
                **{
                    **tags,
                    "before": _values(tags["before"]),
                    "after": _values(tags["after"]),
                    "lyrics_keys": tuple(tags["lyrics_keys"]),
                    "cover": _load_cover(tags["cover"]) if tags.get("cover") else None,
                    "differences": tuple(
                        TagDifference(
                            **{
                                **diff,
                                "physical_tags": tuple(diff["physical_tags"]),
                                "before": tuple(diff["before"])
                                if isinstance(diff["before"], list)
                                else diff["before"],
                                "after": tuple(diff["after"])
                                if isinstance(diff["after"], list)
                                else diff["after"],
                            }
                        )
                        for diff in tags["differences"]
                    ),
                }
            )
        items.append(
            TagWriteItem(
                **{
                    **value,
                    "path": Path(value["path"]),
                    "snapshot": snapshot,
                    "tags": tags,
                    "fingerprint": FileFingerprint(**value["fingerprint"])
                    if value["fingerprint"]
                    else None,
                }
            )
        )
    return TagWritePreview(
        data["operation_id"],
        TagWriteRequest(
            Path(request["database_path"]),
            tuple(request["file_ids"]),
            cast(tuple[EditField, ...], tuple(request["fields"])),
            request["allow_date_loss"],
            tuple(tuple(pair) for pair in request["lyrics_keys"]),
            tuple((file_id, _load_cover(cover)) for file_id, cover in request.get("covers", [])),
            tuple(request.get("cover_skipped_ids", [])),
        ),
        tuple(data["catalog_identity"]),
        tuple(items),
        tuple(_load_nfo(value) for value in data.get("nfo_items", [])),
        tuple(_load_cover_folder(value) for value in data.get("cover_folders", [])),
    )


def _load_nfo(value: dict[str, Any]) -> AlbumNfoItem:
    values = value["values"]
    return AlbumNfoItem(
        path=Path(value["path"]),
        library_root=Path(value["library_root"]),
        file_ids=tuple(value["file_ids"]),
        tracks=tuple(
            AlbumNfoTrack(
                **{
                    **track,
                    "album_artists": tuple(track["album_artists"]),
                    "artists": tuple(track["artists"]),
                    "genres": tuple(track["genres"]),
                }
            )
            for track in value["tracks"]
        ),
        members=tuple(value["members"]),
        values=AlbumNfoValues(
            **{
                **values,
                "songs": tuple(AlbumNfoSong(**song) for song in values.get("songs", [])),
                "genres": tuple(values["genres"]),
                "artists": tuple(values["artists"]) if values["artists"] is not None else None,
            }
        )
        if values is not None
        else None,
        fingerprint=FileFingerprint(**value["fingerprint"]) if value["fingerprint"] else None,
        state=value["state"],
        message=value["message"],
    )


class FileTagJournal:
    def __init__(self, path: Path, data: dict[str, Any]) -> None:
        self.path, self.data = path, data

    @property
    def preview(self) -> TagWritePreview:
        return _load_preview(self.data["preview"])

    def state(self, file_id: int) -> TagRecoveryState:
        value = self.data["files"][str(file_id)]
        identity = value.get("temporary_identity")
        return TagRecoveryState(
            value["state"], value.get("after_hash"), tuple(identity) if identity else None
        )

    def paths(self, item: TagWriteItem) -> tuple[Path, Path]:
        operation = self.data["preview"]["operation_id"]
        return (
            item.path.parent
            / ".trackfolio-backups"
            / operation
            / f"{item.file_id}-{item.path.name}.tfo-bak",
            item.path.parent / f".trackfolio-{operation}-{item.file_id}.tmp",
        )

    def nfo_state(self, item: AlbumNfoItem) -> TagRecoveryState:
        value = self.data["nfos"][str(item.path)]
        identity = value.get("temporary_identity")
        return TagRecoveryState(
            value["state"], value.get("after_hash"), tuple(identity) if identity else None
        )

    def nfo_paths(self, item: AlbumNfoItem) -> tuple[Path, Path]:
        operation = self.data["preview"]["operation_id"]
        return (
            item.path.parent / ".trackfolio-backups" / operation / "nfo-album.nfo.tfo-bak",
            item.path.parent / f".trackfolio-{operation}-album-nfo.tmp",
        )

    def record_nfo(self, item: AlbumNfoItem, state: str, **details: object) -> None:
        self.data["nfos"][str(item.path)].update(state=state, **details)
        self._save()

    def _save(self) -> None:
        temporary = None
        owned: tuple[int, int] | None = None
        try:
            if self.path.is_symlink() or self.path.parent.is_symlink():
                raise TagJournalError("The operation log was replaced by a link.")
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=".journal-",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                info = os.fstat(stream.fileno())
                owned = info.st_dev, info.st_ino
                json.dump(self.data, stream, ensure_ascii=False, default=str)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            temporary = None
            _sync_directory(self.path.parent)
        except (OSError, TypeError, ValueError) as exc:
            raise TagJournalError(f"Could not persist the write log: {exc}") from exc
        finally:
            if temporary is not None:
                try:
                    info = temporary.stat(follow_symlinks=False)
                    if (info.st_dev, info.st_ino) == owned:
                        temporary.unlink()
                except FileNotFoundError:
                    pass

    def record(self, item: TagWriteItem, state: str, **details: object) -> None:
        self.data["files"][str(item.file_id)].update(state=state, **details)
        self._save()

    def finish(self, report: TagWriteReport) -> None:
        self.data["report"] = asdict(report)
        self.data["closed"] = (
            not report.fatal_error
            and not report.cancelled
            and all(item.state in ("confirmed", "unchanged", "excluded") for item in report.results)
            and all(item.state in ("updated", "unchanged", "absent") for item in report.nfo_results)
        )
        for result in report.results:
            self.data["files"][str(result.file_id)].update(state=result.state, error=result.message)
        for nfo in report.nfo_results:
            self.data["nfos"][str(nfo.path)].update(
                state=nfo.state,
                error=nfo.message,
                published=nfo.published,
            )
        self._save()


class FileTagAccess:
    def __init__(self, journal_root: Path) -> None:
        self.journal_root = journal_root.expanduser().resolve()
        self._temporaries: dict[Path, tuple[int, int]] = {}
        self._backup_directories: dict[Path, tuple[int, int]] = {}

    def identity(self, path: Path) -> tuple[int, int]:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise TagWriteError("The catalog is not a regular file.")
        return info.st_dev, info.st_ino

    def resolve(self, snapshot: TagCatalogSnapshot) -> Path:
        return self.resolve_target(
            snapshot.library_root, snapshot.library_root / snapshot.relative_path
        )

    def resolve_target(self, root: Path, path: Path) -> Path:
        root = validate_library_root(root)
        path, _ = prepare_audio_source(path, root)
        info = path.stat()
        if info.st_nlink != 1:
            raise TagWriteError("The file has hard links; it will not be replaced.")
        _writable(path)
        _writable(path.parent, directory=True)
        return path

    def folder_members(self, root: Path, folder: Path) -> tuple[str, ...]:
        root = validate_library_root(root)
        if folder.resolve(strict=True) != folder or not folder.is_relative_to(root):
            raise TagWriteConflict("The NFO folder changed or is outside the library.")
        candidate = folder
        while candidate != root:
            if candidate.is_symlink() or candidate.is_junction():
                raise TagWriteConflict("The NFO folder contains links or junctions.")
            candidate = candidate.parent
        members = []
        for path in folder.iterdir():
            if path.suffix.casefold() not in AUDIO_SUFFIXES:
                continue
            if path.is_symlink() or path.is_junction():
                raise TagWriteConflict("The NFO folder contains linked audio.")
            if path.is_file():
                members.append(path.name)
        return tuple(sorted(members))

    def reserve(self, items: tuple[WriteTarget, ...]) -> None:
        volumes: dict[int, tuple[Path, int, int]] = {}
        for item in items:
            if item.fingerprint is None:
                continue
            device = item.path.parent.stat().st_dev
            path, total, largest = volumes.get(device, (item.path.parent, 0, 0))
            size = item.fingerprint.size
            growth = (
                item.tags.cover.fingerprint.size
                if isinstance(item, TagWriteItem)
                and item.tags
                and item.tags.cover_changed
                and item.tags.cover is not None
                else 0
            )
            volumes[device] = path, total + size + growth, max(largest, size + growth)
        for path, total, largest in volumes.values():
            if shutil.disk_usage(path).free < total + largest + 1024 * 1024:
                raise OSError(
                    errno.ENOSPC,
                    "Insufficient space for backups and the temporary file.",
                    str(path),
                )

    def fingerprint(self, path: Path, cancelled: Callable[[], bool]) -> FileFingerprint:
        before = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise TagWriteConflict("The file is no longer a regular file.")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise TagWriteConflict("The file was replaced while opening it.")
            while chunk := stream.read(1024 * 1024):
                if cancelled():
                    raise TagWriteCancelled("Read cancelled.")
                digest.update(chunk)
        after = path.stat(follow_symlinks=False)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise TagWriteConflict("The file changed while being read.")
        return FileFingerprint(
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, digest.hexdigest()
        )

    def check(self, item: TagWriteItem, cancelled: Callable[[], bool]) -> None:
        if item.snapshot is None or self.resolve(item.snapshot) != item.path:
            raise TagWriteConflict("The music path changed.")
        if self.fingerprint(item.path, cancelled) != item.fingerprint:
            raise TagWriteConflict("The file changed after the preview. Review it again.")

    def journal(self, preview: TagWritePreview) -> FileTagJournal:
        if not re.fullmatch(r"[0-9a-f]{32}", preview.operation_id):
            raise TagJournalError("Invalid operation identifier.")
        self.journal_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        _plain_directory(self.journal_root)
        operation = self.journal_root / preview.operation_id
        try:
            operation.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise TagJournalError(
                "This preview has already been used. Prepare another before retrying."
            ) from exc
        _sync_directory(self.journal_root)
        journal = FileTagJournal(
            operation / "journal.json",
            {
                "schema": 3 if preview.cover_folders or preview.request.covers else 2,
                "preview": _preview_data(preview),
                "closed": False,
                "files": {str(item.file_id): {"state": "pending"} for item in preview.items},
                "nfos": {str(item.path): {"state": "pending"} for item in preview.nfo_items},
            },
        )
        journal._save()
        self._backup_directories.clear()
        return journal

    def backup(self, item: WriteTarget, path: Path, cancelled: Callable[[], bool]) -> None:
        directory = path.parent.parent
        _plain_directory(directory)
        info = directory.stat(follow_symlinks=False)
        identity = info.st_dev, info.st_ino
        if self._backup_directories.setdefault(directory, identity) != identity:
            raise TagWriteConflict("The backup directory was replaced.")
        _plain_directory(path.parent)
        _copy(item.path, path, cancelled)
        if (
            item.fingerprint is None
            or self.fingerprint(path, cancelled).sha256 != item.fingerprint.sha256
        ):
            raise TagWriteConflict("The backup does not match the confirmed original.")
        _sync_directory(path.parent)

    def discard_backups(self, directory: Path) -> None:
        """Remove the entire backup directory only after a fully confirmed batch."""
        if not directory.exists() and not directory.is_symlink():
            return
        info = directory.stat(follow_symlinks=False)
        if (
            directory.name != ".trackfolio-backups"
            or directory.is_symlink()
            or directory.is_junction()
            or not stat.S_ISDIR(info.st_mode)
            or directory.parent.resolve() != directory.parent
            or self._backup_directories.get(directory) != (info.st_dev, info.st_ino)
        ):
            raise TagWriteConflict("The backup directory changed; it has not been removed.")
        shutil.rmtree(directory)
        self._backup_directories.pop(directory, None)
        _sync_directory(directory.parent)

    def temporary(self, backup: Path, temporary: Path, cancelled: Callable[[], bool]) -> None:
        def claim(info: os.stat_result) -> None:
            self._temporaries[temporary] = info.st_dev, info.st_ino

        _copy(backup, temporary, cancelled, claim)

    def publish(self, item: WriteTarget, temporary: Path) -> None:
        info = temporary.stat(follow_symlinks=False)
        if self._temporaries.get(temporary) != (info.st_dev, info.st_ino):
            raise TagWriteConflict("The verified temporary file was replaced.")
        modified = info.st_mtime_ns
        _copy_metadata(item.path, temporary)
        os.utime(temporary, ns=(temporary.stat().st_atime_ns, modified))
        with temporary.open("r+b") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, item.path)
        try:
            _sync_directory(item.path.parent)
        except OSError as exc:
            raise TagPublishedError(f"File replaced; could not sync its directory: {exc}") from exc

    def discard_temporary(self, path: Path) -> None:
        owned = self._temporaries.pop(path, None)
        if owned is None:
            return
        try:
            current = path.stat(follow_symlinks=False)
        except FileNotFoundError:
            return
        if (current.st_dev, current.st_ino) != owned:
            raise OSError(
                "The temporary file was replaced; the unrelated file has not been removed."
            )
        path.unlink()

    def discard_recovery_temporary(self, path: Path, state: TagRecoveryState) -> None:
        if not path.exists() and not path.is_symlink():
            return
        if state.temporary_identity is None or state.after_hash is None:
            return  # An unverified partial copy requires manual review, not deletion.
        info = path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(info.st_mode)
            or (info.st_dev, info.st_ino) != state.temporary_identity
            or self.fingerprint(path, lambda: False).sha256 != state.after_hash
        ):
            raise TagWriteConflict("The temporary file changed; it is retained for manual review.")
        path.unlink()
        _sync_directory(path.parent)

    def load_journal(self, path: Path) -> FileTagJournal:
        if (
            path.parent.parent != self.journal_root
            or path.name != "journal.json"
            or path.is_symlink()
            or path.parent.is_symlink()
            or not path.is_file()
        ):
            raise TagJournalError("The log path does not belong to Trackfolio.")
        data = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(data, dict)
            or data.get("schema") not in (1, 2, 3)
            or not isinstance(data.get("preview"), dict)
            or data["preview"].get("operation_id") != path.parent.name
            or not isinstance(data.get("files"), dict)
            or not isinstance(data.get("closed"), bool)
        ):
            raise TagJournalError("Invalid log format.")
        if data["schema"] >= 2 and not isinstance(data.get("nfos"), dict):
            raise TagJournalError("Invalid NFO log.")
        if data["schema"] == 1 and data["preview"].get("nfo_items"):
            raise TagJournalError("An older log cannot contain NFO jobs.")
        if not re.fullmatch(r"[0-9a-f]{32}", path.parent.name):
            raise TagJournalError("Invalid log identifier.")
        preview = _load_preview(data["preview"])
        if data["schema"] < 3 and (preview.cover_folders or preview.request.covers):
            raise TagJournalError("An older log cannot contain cover plans.")
        for item in preview.items:
            if item.snapshot is not None:
                root = item.snapshot.library_root.resolve()
                candidate = root / item.snapshot.relative_path
                resolved = candidate.resolve()
                if not resolved.is_relative_to(root) or item.path != resolved:
                    raise TagJournalError("The log path does not match its library.")
        selected = {item.file_id: item for item in preview.items}
        for folder in preview.cover_folders:
            if folder.path.resolve() != folder.path or not folder.path.is_relative_to(
                folder.library_root.resolve()
            ):
                raise TagJournalError("The log's cover folder is outside its library.")
            if any(candidate.path.parent != folder.path for candidate in folder.candidates):
                raise TagJournalError("A logged cover is outside its folder.")
        for item in preview.items:
            if item.tags is not None and item.tags.cover is not None:
                cover = item.tags.cover
                if (
                    item.snapshot is None
                    or cover.library_root.resolve() != item.snapshot.library_root.resolve()
                    or (
                        cover.path.parent != item.path.parent
                        or not cover.path.is_relative_to(cover.library_root.resolve())
                    )
                ):
                    raise TagJournalError("The logged cover does not match its song.")
        for nfo in preview.nfo_items:
            root = nfo.library_root.resolve()
            if (
                not nfo.path.is_absolute()
                or nfo.path.name != "album.nfo"
                or not nfo.path.is_relative_to(root)
                or nfo.path.parent.resolve() != nfo.path.parent
                or not nfo.file_ids
                or str(nfo.path) not in data.get("nfos", {})
            ):
                raise TagJournalError("The logged NFO path does not belong to its library.")
            for file_id in nfo.file_ids:
                audio = selected.get(file_id)
                if (
                    audio is None
                    or audio.snapshot is None
                    or (
                        audio.snapshot.library_root != nfo.library_root
                        or audio.path.parent != nfo.path.parent
                    )
                ):
                    raise TagJournalError("The NFO does not match its target songs.")
        return FileTagJournal(path, data)

    def pending(self) -> tuple[PendingTagOperation, ...]:
        operations = []
        for path in sorted(self.journal_root.glob("*/journal.json")):
            try:
                if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
                    raise TagJournalError("The log is not a regular file without links.")
                # Completed operations remain historical even if their music is later moved.
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise TagJournalError("Invalid log format.")
                if data.get("closed") is True:
                    continue
                journal = self.load_journal(path)
                if not journal.data["closed"]:
                    preview = _load_preview(journal.data["preview"])
                    operations.append(
                        PendingTagOperation(
                            path,
                            preview.request.database_path,
                            "Incomplete operation. Review its files and backups.",
                        )
                    )
            except (OSError, ValueError, TypeError, KeyError, TagWriteError) as exc:
                operations.append(PendingTagOperation(path, None, f"Log cannot be reviewed: {exc}"))
        return tuple(operations)
