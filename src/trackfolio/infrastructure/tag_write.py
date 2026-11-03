"""Mutagen tag writing on copies, with independent payload and preservation checks."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Any, BinaryIO, cast

from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, Frames, ID3NoHeaderError

from trackfolio.application.write_tags import TagWriteError
from trackfolio.domain.catalog_edit import EditableValues, EditField
from trackfolio.domain.metadata import TrackMetadata
from trackfolio.domain.tag_write import (
    PlannedTags,
    TagCatalogSnapshot,
    TagDifference,
    TagWriteRequest,
)
from trackfolio.infrastructure.metadata import _canonical_key, read_metadata

_ALIASES: dict[EditField, tuple[str, ...]] = {
    "title": ("title", "tit2"),
    "artists": ("artist", "tpe1"),
    "album": ("album", "talb"),
    "album_year": ("date", "year", "tdrc", "tdrl", "tyer"),
    "track_number": ("tracknumber", "trck"),
    "track_total": ("tracktotal", "totaltracks"),
    "disc_number": ("discnumber", "tpos"),
    "disc_total": ("disctotal", "totaldiscs"),
    "genres": ("genre", "tcon"),
    "lyrics": ("lyrics", "unsyncedlyrics", "uslt"),
}
_FLAC = {
    "title": "TITLE",
    "artists": "ARTIST",
    "album": "ALBUM",
    "album_year": "DATE",
    "track_number": "TRACKNUMBER",
    "track_total": "TRACKTOTAL",
    "disc_number": "DISCNUMBER",
    "disc_total": "DISCTOTAL",
    "genres": "GENRE",
    "lyrics": "LYRICS",
}
_ID3 = {
    "title": "TIT2",
    "artists": "TPE1",
    "album": "TALB",
    "album_year": "TDRC",
    "track_number": "TRCK",
    "track_total": "TRCK",
    "disc_number": "TPOS",
    "disc_total": "TPOS",
    "genres": "TCON",
    "lyrics": "USLT",
}


def _hash_stream(stream: BinaryIO, length: int | None = None, prefix: bytes = b"") -> str:
    digest = hashlib.sha256()
    digest.update(prefix)
    while length is None or length > 0:
        chunk = stream.read(1024 * 1024 if length is None else min(length, 1024 * 1024))
        if not chunk:
            if length:
                raise TagWriteError("El archivo terminó antes de lo indicado por su contenedor.")
            break
        digest.update(chunk)
        if length is not None:
            length -= len(chunk)
    return digest.hexdigest()


def _flac_layout(
    path: Path, *, replace_front: bool = False
) -> tuple[str, tuple[tuple[int, str], ...]]:
    blocks = []
    with path.open("rb") as stream:
        if stream.read(4) != b"fLaC":
            raise TagWriteError("No se escribe FLAC con encabezados ajenos al contenedor.")
        for _ in range(10000):
            header = stream.read(4)
            if len(header) != 4:
                raise TagWriteError("Bloques FLAC incompletos.")
            kind, length = header[0] & 0x7F, int.from_bytes(header[1:], "big")
            front = False
            if kind == 6 and replace_front:
                if length < 4:
                    raise TagWriteError("Bloque de imagen FLAC incompleto.")
                prefix = stream.read(4)
                front = int.from_bytes(prefix, "big") == 3
                digest = _hash_stream(stream, length - 4, prefix)
            else:
                digest = _hash_stream(stream, length)
            if kind not in (1, 4) and not front:
                blocks.append((kind, digest))
            if header[0] & 0x80:
                return _hash_stream(stream), tuple(blocks)
    raise TagWriteError("Demasiados bloques FLAC.")


def _mp3_payload(path: Path) -> tuple[str, str]:
    with path.open("rb") as stream:
        size = path.stat().st_size
        start, end = 0, size
        header = stream.read(10)
        if header[:3] == b"ID3":
            if len(header) != 10 or any(value & 0x80 for value in header[6:10]):
                raise TagWriteError("Tamaño ID3 no válido.")
            start = 10 + sum(
                value << shift for value, shift in zip(header[6:10], (21, 14, 7, 0), strict=True)
            )
            # A v2.4 footer immediately following the declared body is also metadata.
            stream.seek(start)
            if header[3] == 4 and header[5] & 0x10 and stream.read(3) == b"3DI":
                start += 10
        if end >= 128:
            stream.seek(end - 128)
            if stream.read(3) == b"TAG":
                raise TagWriteError(
                    "ID3v1 presente: esta entrega conserva ese archivo sin escribir."
                )
        tail_hash = hashlib.sha256().hexdigest()
        if end >= 32:
            stream.seek(end - 32)
            footer = stream.read(32)
            if footer[:8] == b"APETAGEX":
                length = int.from_bytes(footer[12:16], "little")
                if not 32 <= length <= end - start:
                    raise TagWriteError("Etiqueta APEv2 no válida.")
                end -= length
                if end - start >= 32:
                    stream.seek(end - 32)
                    if stream.read(8) == b"APETAGEX":
                        end -= 32
                stream.seek(end)
                tail_hash = _hash_stream(stream, size - end)
        if not 0 <= start <= end:
            raise TagWriteError("Segmentos MP3 no válidos.")
        stream.seek(start)
        return _hash_stream(stream, end - start), tail_hash


def _id3(path: Path) -> Any:
    try:
        return cast(Any, ID3)(str(path), translate=False)
    except ID3NoHeaderError:
        return cast(Any, ID3)()


def _frame_value(frame: Any) -> object:
    def normalize(value: Any) -> object:
        if isinstance(value, bytes):
            return {"bytes": hashlib.sha256(value).hexdigest()}
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, dict):
            return {str(key): normalize(item) for key, item in sorted(value.items())}
        if isinstance(value, (tuple, list)):
            return [normalize(item) for item in value]
        if hasattr(value, "__dict__"):
            return {key: normalize(item) for key, item in vars(value).items() if key != "encoding"}
        return str(value)

    return normalize(frame)


def _physical_date(tags: Any, metadata: TrackMetadata, version: int) -> str | None:
    if version == 3 and "TYER" in tags and "TDAT" in tags:
        year, daymonth = str(tags["TYER"]), str(tags["TDAT"])
        if len(year) == len(daymonth) == 4:
            value = f"{year}-{daymonth[2:]}-{daymonth[:2]}"
            if "TIME" in tags and len(str(tags["TIME"])) == 4:
                time = str(tags["TIME"])
                value += f"T{time[:2]}:{time[2:]}"
            try:
                datetime.fromisoformat(value) if "T" in value else date.fromisoformat(value)
                return value
            except ValueError:
                pass
    return metadata.album_date


def _new_date(value: str | None, year: int | None, allow_loss: bool) -> str | None:
    if year is None:
        if value and not allow_loss:
            raise TagWriteError(
                "Vaciar el año elimina la fecha. Confirma esa pérdida de precisión."
            )
        return None
    replacement = f"{year:04d}"
    if value and len(value) > 4:
        candidate = replacement + value[4:]
        try:
            if len(candidate) == 7:
                date.fromisoformat(candidate + "-01")
            elif "T" in candidate or " " in candidate:
                datetime.fromisoformat(candidate)
            else:
                date.fromisoformat(candidate)
            return candidate
        except ValueError:
            if not allow_loss:
                raise TagWriteError(
                    "La fecha resultante no es válida. Confirma escribir solo el año."
                ) from None
    return replacement


def _fields(plan: PlannedTags) -> set[EditField]:
    fields = {item.field for item in plan.differences}
    for number, total in (("track_number", "track_total"), ("disc_number", "disc_total")):
        if number in fields or total in fields:
            fields.update((cast(EditField, number), cast(EditField, total)))
    return fields


def _owned(key: str, fields: set[EditField], selected_lyrics: str | None) -> bool:
    if key.startswith("USLT"):
        return "lyrics" in fields and key == selected_lyrics
    if key in ("TDAT", "TIME"):
        return "album_year" in fields
    return any(_canonical_key(key) in _ALIASES[field] for field in fields)


class MutagenTagCodec:
    def observed(self, path: Path) -> TrackMetadata:
        metadata = read_metadata(path)
        if metadata.audio_format == "mp3":
            tags = _id3(path)
            version = tags.version[1] if tags.version[0] == 2 else 4
            metadata = replace(metadata, album_date=_physical_date(tags, metadata, version))
        return metadata

    def plan(
        self, path: Path, snapshot: TagCatalogSnapshot, request: TagWriteRequest
    ) -> PlannedTags:
        metadata = self.observed(path)
        before = EditableValues.from_metadata(metadata)
        after = before
        before_date = after_date = metadata.album_date
        keys = tuple(tag.key for tag in metadata.raw_tags)
        candidates: tuple[str, ...] = ()
        selected = None
        version = "Vorbis comments" if metadata.audio_format == "flac" else "MP3"
        mp3_version = 4
        error = None
        try:
            if metadata.audio_format == "flac":
                _flac_layout(path)
            else:
                _mp3_payload(path)
                tags = _id3(path)
                if tags.version[0] == 2:
                    mp3_version = tags.version[1]
                if mp3_version not in (3, 4):
                    raise TagWriteError(
                        "ID3v2.2 requiere una conversión que no se realiza automáticamente."
                    )
                version = f"ID3v2.{mp3_version}"
                keys = tuple(tags.keys())
                candidates = tuple(key for key in keys if key.startswith("USLT:"))
                # The reader skips empty texts when choosing its primary lyrics.
                candidates = tuple(
                    sorted(candidates, key=lambda key: not str(tags[key].text).strip())
                )
                selected = dict(request.lyrics_keys).get(snapshot.file_id)
                if "lyrics" in request.fields:
                    if selected is not None and selected not in candidates:
                        raise TagWriteError("La versión de letras elegida ya no existe.")
                    explicit_lyrics = selected is not None
                    if (
                        len(candidates) > 1
                        and selected is None
                        and before.lyrics != snapshot.values.lyrics
                    ):
                        raise TagWriteError(
                            "Hay varias versiones de letras. Elige idioma y descripción."
                        )
                    selected = selected or (candidates[0] if candidates else "USLT::und")
                    if selected in tags and len(candidates) > 1 and explicit_lyrics:
                        selected_text = str(tags[selected].text)
                        # A matching USLT may still be overridden by an obsolete alias.
                        if (
                            selected_text != snapshot.values.lyrics
                            or before.lyrics == snapshot.values.lyrics
                        ):
                            before = replace(before, lyrics=selected_text)
                        after = before
                if mp3_version == 3 and any(
                    isinstance(getattr(frame, "text", None), list) and len(frame.text) > 1
                    for frame in tags.values()
                ):
                    raise TagWriteError(
                        "ID3v2.3 contiene listas que no se pueden guardar sin unirlas."
                    )
            changes = []
            for field in request.fields:
                value = getattr(snapshot.values, field)
                if value == getattr(before, field):
                    continue
                if field == "album_year":
                    after_date = _new_date(before_date, value, request.allow_date_loss)
                    if (
                        metadata.audio_format == "mp3"
                        and mp3_version == 3
                        and after_date
                        and len(after_date) not in (4, 10, 16)
                    ):
                        if not request.allow_date_loss:
                            raise TagWriteError(
                                "ID3v2.3 no conserva esa precisión de fecha. "
                                "Confirma escribir solo el año o excluye este campo."
                            )
                        after_date = after_date[:4]
                if (
                    metadata.audio_format == "mp3"
                    and mp3_version == 3
                    and isinstance(value, tuple)
                    and len(value) > 1
                ):
                    raise TagWriteError(
                        "ID3v2.3 no admite esta lista sin pérdidas. El archivo no se convertirá."
                    )
                after = replace(after, **{field: value})
                aliases = set(_ALIASES[field])
                if field.startswith("track_"):
                    aliases.update((*_ALIASES["track_number"], *_ALIASES["track_total"]))
                if field.startswith("disc_"):
                    aliases.update((*_ALIASES["disc_number"], *_ALIASES["disc_total"]))
                canonical = [(_FLAC if metadata.audio_format == "flac" else _ID3)[field]]
                if metadata.audio_format == "mp3" and field == "lyrics":
                    canonical = [selected or "USLT::und"]
                if metadata.audio_format == "mp3" and field == "album_year" and mp3_version == 3:
                    canonical = ["TYER", "TDAT", "TIME"]
                touched = tuple(
                    dict.fromkeys(
                        [
                            key
                            for key in keys
                            if _canonical_key(key) in aliases
                            and (not key.startswith("USLT:") or key == selected)
                        ]
                        + canonical
                    )
                )
                changes.append(TagDifference(field, getattr(before, field), value, touched))
        except Exception as exc:
            error = str(exc)
            changes = []
        plan = PlannedTags(
            before,
            after,
            before_date,
            after_date,
            metadata.audio_format or "",
            version,
            tuple(changes),
            candidates,
            selected,
            error,
        )
        cover = dict(request.covers).get(snapshot.file_id)
        if cover is not None and not plan.error:
            fronts = self._fronts(path, plan.audio_format)
            same = len(fronts) == 1 and fronts[0] == (cover.mime_type, cover.data)
            return replace(
                plan,
                cover=cover,
                cover_changed=not same,
                cover_catalog_changed=(
                    snapshot.cover_sha256 != cover.fingerprint.sha256
                    or snapshot.cover_source != "embedded"
                    or snapshot.cover_relative_path is not None
                ),
                cover_action="unchanged" if same else "replaced" if fronts else "embedded",
            )
        return replace(
            plan,
            cover_action="skipped"
            if snapshot.file_id in request.cover_skipped_ids
            else "preserved",
        )

    def _fronts(self, path: Path, audio_format: str) -> tuple[tuple[str, bytes], ...]:
        if audio_format == "flac":
            audio = cast(Any, FLAC)(str(path))
            return tuple(
                (picture.mime, picture.data) for picture in audio.pictures if picture.type == 3
            )
        return tuple(
            (cast(Any, frame).mime, cast(Any, frame).data)
            for frame in _id3(path).values()
            if isinstance(frame, APIC) and cast(Any, frame).type == 3
        )

    def write_verified(self, backup: Path, temporary: Path, plan: PlannedTags) -> TrackMetadata:
        if plan.error:
            raise TagWriteError(plan.error)
        fields = _fields(plan)
        if plan.audio_format == "flac":
            self._write_flac(temporary, plan, fields)
        elif plan.audio_format == "mp3":
            self._write_mp3(temporary, plan, fields)
        else:
            raise TagWriteError("Formato de escritura desconocido.")
        self._verify_preservation(backup, temporary, plan, fields)
        if plan.cover is not None and (
            plan.cover.data is None
            or self._fronts(temporary, plan.audio_format)
            != ((plan.cover.mime_type, plan.cover.data),)
        ):
            raise TagWriteError(
                "La portada no está incrustada correctamente en el archivo musical."
            )
        actual = self.observed(temporary)
        actual_values = EditableValues.from_metadata(actual)
        for field in actual_values.as_dict():
            value = getattr(actual_values, field)
            if field == "lyrics" and "lyrics" in fields and plan.selected_lyrics:
                tags = _id3(temporary)
                frame = tags.get(plan.selected_lyrics)
                value = str(frame.text) if frame is not None else None
            if value != getattr(plan.after, field):
                raise TagWriteError(
                    f"La verificación del campo {field} no coincide; original conservado."
                )
        if actual.album_date != plan.after_date:
            raise TagWriteError("La fecha escrita no coincide con la vista previa.")
        return actual

    def _write_flac(self, path: Path, plan: PlannedTags, fields: set[EditField]) -> None:
        audio = cast(Any, FLAC)(str(path))
        if audio.tags is None:
            audio.add_tags()
        for key in tuple(audio.tags.keys()):
            if _owned(key, fields, None):
                del audio.tags[key]
        for field in fields:
            value = plan.after_date if field == "album_year" else getattr(plan.after, field)
            if value is not None and value != ():
                audio.tags[_FLAC[field]] = list(value) if isinstance(value, tuple) else [str(value)]
        if plan.cover_changed and plan.cover is not None:
            cover = plan.cover
            if cover.data is None:
                raise TagWriteError(
                    "La imagen del plan no está disponible; prepara otra escritura."
                )
            remaining = [picture for picture in audio.pictures if picture.type != 3]
            audio.clear_pictures()
            for picture in remaining:
                audio.add_picture(picture)
            picture = cast(Any, Picture)()
            picture.type, picture.mime, picture.desc = 3, cover.mime_type, "Cover (front)"
            picture.width, picture.height, picture.depth = cover.width, cover.height, 24
            picture.data = cover.data
            audio.add_picture(picture)
        audio.save()

    def _write_mp3(self, path: Path, plan: PlannedTags, fields: set[EditField]) -> None:
        tags = _id3(path)
        version = 3 if plan.version == "ID3v2.3" else 4
        original_lyrics = tags.get(plan.selected_lyrics) if plan.selected_lyrics else None
        for key in tuple(tags.keys()):
            if _owned(key, fields, plan.selected_lyrics):
                del tags[key]
        encoding = 1 if version == 3 else 3

        def put(name: str, value: object) -> None:
            if value is not None and value != ():
                text = list(value) if isinstance(value, tuple) else [str(value)]
                tags.add(cast(Any, Frames)[name](encoding=encoding, text=text))

        for field in fields - {
            "album_year",
            "lyrics",
            "track_number",
            "track_total",
            "disc_number",
            "disc_total",
        }:
            put(_ID3[field], getattr(plan.after, field))
        for number, total, name in (
            ("track_number", "track_total", "TRCK"),
            ("disc_number", "disc_total", "TPOS"),
        ):
            if number in fields or total in fields:
                n, t = getattr(plan.after, number), getattr(plan.after, total)
                put(name, f"{n or 0}/{t}" if t is not None else n)
        if "album_year" in fields:
            if version == 4:
                put("TDRC", plan.after_date)
            elif plan.after_date:
                put("TYER", plan.after_date[:4])
                if len(plan.after_date) >= 10:
                    put("TDAT", plan.after_date[8:10] + plan.after_date[5:7])
                if len(plan.after_date) >= 16:
                    put("TIME", plan.after_date[11:13] + plan.after_date[14:16])
        if "lyrics" in fields and plan.after.lyrics:
            tags.add(
                cast(Any, Frames)["USLT"](
                    encoding=encoding,
                    lang=original_lyrics.lang if original_lyrics else "und",
                    desc=original_lyrics.desc if original_lyrics else "",
                    text=plan.after.lyrics,
                )
            )
        if plan.cover_changed and plan.cover is not None:
            cover = plan.cover
            if cover.data is None:
                raise TagWriteError(
                    "La imagen del plan no está disponible; prepara otra escritura."
                )
            for key, frame in list(tags.items()):
                if isinstance(frame, APIC) and cast(Any, frame).type == 3:
                    del tags[key]
            description = "Cover (front)"
            while f"APIC:{description}" in tags:
                description += " (Trackfolio)"
            tags.add(
                cast(Any, APIC)(
                    encoding=encoding,
                    mime=cover.mime_type,
                    type=3,
                    desc=description,
                    data=cover.data,
                )
            )
        tags.save(str(path), v1=0, v2_version=version)

    def _verify_preservation(
        self, backup: Path, temporary: Path, plan: PlannedTags, fields: set[EditField]
    ) -> None:
        if plan.audio_format == "flac":
            if _flac_layout(backup, replace_front=plan.cover_changed) != _flac_layout(
                temporary, replace_front=plan.cover_changed
            ):
                raise TagWriteError("Cambió el audio o un bloque FLAC no seleccionado.")

            def flac_signature(path: Path) -> object:
                audio = cast(Any, FLAC)(str(path))
                return (
                    audio.tags.vendor if had_comments and audio.tags is not None else None,
                    sorted(
                        (key.casefold(), tuple(values))
                        for key, values in audio.tags.items()
                        if not _owned(key, fields, None)
                    )
                    if audio.tags is not None
                    else [],
                )

            had_comments = cast(Any, FLAC)(str(backup)).tags is not None
            if flac_signature(backup) != flac_signature(temporary):
                raise TagWriteError("Cambió un comentario FLAC no seleccionado.")
        else:
            if _mp3_payload(backup) != _mp3_payload(temporary):
                raise TagWriteError("Cambió el audio MP3 o sus etiquetas finales.")

            def id3_signature(path: Path) -> str:
                tags = _id3(path)
                data = {
                    key: _frame_value(frame)
                    for key, frame in tags.items()
                    if not _owned(key, fields, plan.selected_lyrics)
                    and not (
                        plan.cover_changed
                        and isinstance(frame, APIC)
                        and cast(Any, frame).type == 3
                    )
                }
                data["unknown_frames"] = [
                    hashlib.sha256(frame).hexdigest() for frame in tags.unknown_frames
                ]
                return json.dumps(data, sort_keys=True)

            if id3_signature(backup) != id3_signature(temporary):
                raise TagWriteError("Cambió un frame ID3 no seleccionado.")
