"""Conservative XML album sidecar edits, independent of audio containers."""

from __future__ import annotations

import codecs
import re
from datetime import date
from pathlib import Path
from xml.dom import Node, minidom
from xml.parsers import expat

from trackfolio.application.tag_write_errors import TagWriteConflict, TagWriteError
from trackfolio.domain.tag_write import AlbumNfoSong, AlbumNfoValues

MAX_NFO_BYTES = 16 * 1024 * 1024


def _reject_declaration(*args: object) -> None:
    raise TagWriteError("El NFO contiene DTD o entidades no admitidas.")


def _parse(data: bytes) -> minidom.Document:
    if not data or len(data) > MAX_NFO_BYTES:
        raise TagWriteError("El NFO está vacío o supera el límite de 16 MiB.")
    try:
        # Expat detects declarations even in UTF-16/32, before expanding entities.
        parser = expat.ParserCreate()
        parser.StartDoctypeDeclHandler = _reject_declaration
        parser.EntityDeclHandler = _reject_declaration
        parser.Parse(data, True)
        document = minidom.parseString(data)
    except (expat.ExpatError, ValueError, LookupError) as exc:
        raise TagWriteError(f"El NFO no es XML compatible: {exc}") from exc
    root = document.documentElement
    if root is None or root.tagName != "album" or root.namespaceURI:
        raise TagWriteError("El NFO debe ser un documento XML con raíz <album> sin namespace.")
    return document


def _elements(parent: minidom.Element, name: str) -> list[minidom.Element]:
    return [
        child
        for child in parent.childNodes
        if isinstance(child, minidom.Element) and child.tagName == name and not child.namespaceURI
    ]


def _text(element: minidom.Element) -> str:
    if any(child.nodeType == Node.ELEMENT_NODE for child in element.childNodes):
        raise TagWriteError(f"El elemento NFO {element.tagName} tiene estructura no compatible.")
    return "".join(
        child.data
        for child in element.childNodes
        if isinstance(child, (minidom.Text, minidom.CDATASection))
    )


def _set_text(element: minidom.Element, value: str) -> None:
    assert element.ownerDocument is not None
    # Keep comments, processing instructions and attributes attached to this field.
    for child in list(element.childNodes):
        if isinstance(child, (minidom.Text, minidom.CDATASection)):
            element.removeChild(child)
    element.appendChild(element.ownerDocument.createTextNode(value))


def _set_values(parent: minidom.Element, name: str, values: tuple[str, ...]) -> bool:
    assert parent.ownerDocument is not None
    nodes = _elements(parent, name)
    if tuple(_text(node) for node in nodes) == values:
        return False
    for index, value in enumerate(values):
        if index < len(nodes):
            _set_text(nodes[index], value)
        else:
            node = parent.ownerDocument.createElement(name)
            node.appendChild(parent.ownerDocument.createTextNode(value))
            _insert_value(parent, node)
    for node in nodes[len(values) :]:
        # Removing a managed value removes that element intentionally. Nested fields
        # are rejected by _text, rather than silently dropping unknown structures.
        before, after = node.previousSibling, node.nextSibling
        if (
            isinstance(before, minidom.Text)
            and not before.data.strip()
            and isinstance(after, minidom.Text)
            and re.match(r"[ \t]*\n", after.data)
        ):
            # Remove only this line's prefix; keep intentional blank lines and
            # the following sibling's indentation (including the closing tag).
            before.data = re.sub(r"\n[ \t]*\Z", "", before.data)
            if not before.data:
                parent.removeChild(before)
        parent.removeChild(node)
    return True


def _insert_value(parent: minidom.Element, node: minidom.Element) -> None:
    """Insert beside matching fields, borrowing their existing whitespace."""
    assert parent.ownerDocument is not None
    siblings = _elements(parent, node.tagName)
    if not siblings:
        siblings = [child for child in parent.childNodes if isinstance(child, minidom.Element)]
    if not siblings:
        parent.insertBefore(node, parent.firstChild)
        return
    anchor = siblings[-1]
    following = anchor.nextSibling
    assert following is None or isinstance(
        following, (minidom.Element, minidom.Text, minidom.Comment, minidom.ProcessingInstruction)
    )
    spacing = anchor.previousSibling
    if isinstance(spacing, minidom.Text) and not spacing.data.strip():
        parent.insertBefore(parent.ownerDocument.createTextNode(spacing.data), following)
    parent.insertBefore(node, following)


def _release_date(previous: str, year: int) -> str:
    suffix = previous[4:] if re.fullmatch(r"\d{4}(?:-\d{2}(?:-\d{2})?)?", previous) else ""
    result = f"{year:04d}{suffix}"
    try:
        date.fromisoformat(
            result + ("-01-01" if len(result) == 4 else "-01" if len(result) == 7 else "")
        )
    except ValueError:
        return f"{year:04d}"
    return result


def _rich_credit(credit: minidom.Element) -> bool:
    if credit.attributes.length:
        return True
    for child in credit.childNodes:
        if child.nodeType in (Node.COMMENT_NODE, Node.PROCESSING_INSTRUCTION_NODE):
            return True
        if isinstance(child, minidom.Element):
            if child.tagName == "artist":
                if child.attributes.length or any(
                    nested.nodeType in (Node.COMMENT_NODE, Node.PROCESSING_INSTRUCTION_NODE)
                    for nested in child.childNodes
                ):
                    return True
            elif (
                child.tagName != "musicBrainzArtistID"
                or child.attributes.length
                or child.childNodes
            ):
                return True
    return False


def _artists(root: minidom.Element, artists: tuple[str, ...]) -> bool:
    assert root.ownerDocument is not None
    credits = _elements(root, "albumArtistCredits")
    names: list[str] = []
    for credit in credits:
        nodes = _elements(credit, "artist")
        if len(nodes) != 1:
            raise TagWriteError("Crédito NFO sin un único nombre de artista.")
        names.append(_text(nodes[0]))
    direct = _elements(root, "artist")
    changed = False
    # Prefer the existing direct artist representation over simple credit blocks.
    # Rich credits (IDs, attributes or annotations) retain their representation.
    if direct and credits and not any(_rich_credit(credit) for credit in credits):
        for credit in credits:
            root.removeChild(credit)
        credits = []
        changed = True
    if direct:
        changed = _set_values(root, "artist", artists) or changed
    if credits and tuple(names) != artists:
        changed = True
        available = list(zip(names, credits, strict=True))
        ordered: list[minidom.Element] = []
        for name in artists:
            match = next((index for index, (old, _) in enumerate(available) if old == name), None)
            if match is not None:
                _, credit = available.pop(match)
            else:
                credit = root.ownerDocument.createElement("albumArtistCredits")
                _set_values(credit, "artist", (name,))
            ordered.append(credit)
        if any(_rich_credit(credit) for _, credit in available):
            raise TagWriteConflict(
                "Cambiar los artistas reasignaría o eliminaría créditos NFO enriquecidos."
            )
        for credit in credits:
            root.removeChild(credit)
        for credit in ordered:
            root.appendChild(credit)
    if _elements(root, "artistdesc"):
        changed = (
            _set_values(root, "artistdesc", (" / ".join(artists),) if artists else ()) or changed
        )
    return changed


def _number(parent: minidom.Element, name: str) -> int | None:
    nodes = _elements(parent, name)
    if not nodes:
        return None
    if len(nodes) != 1:
        raise TagWriteConflict(
            f"El NFO tiene varios elementos {name}; no se puede asociar la pista."
        )
    value = _text(nodes[0]).strip()
    if not re.fullmatch(r"[0-9]{1,9}", value) or int(value) <= 0:
        raise TagWriteConflict(f"El NFO tiene un {name} no válido para asociar la pista.")
    return int(value)


def _same_disc(first: int | None, second: int | None) -> bool:
    return first is None or second is None or first == second


def _song_titles(root: minidom.Element, songs: tuple[AlbumNfoSong, ...]) -> bool:
    nodes = _elements(root, "track")
    if not nodes or not any(song.update_title for song in songs):
        return False  # A sidecar without a track list does not acquire one.
    album_disc = _number(root, "discnumber")
    positions = [
        (_number(node, "position"), _number(node, "discnumber") or album_disc, node)
        for node in nodes
    ]
    changed = False
    for song in songs:
        if not song.update_title:
            continue
        if song.track_number is None or song.track_number <= 0:
            raise TagWriteConflict(
                "La canción no tiene número de pista para asociar su título NFO."
            )
        candidates = [
            (disc, node)
            for number, disc, node in positions
            if number == song.track_number and _same_disc(disc, song.disc_number)
        ]
        if len(candidates) != 1:
            raise TagWriteConflict(
                f"No hay una única pista NFO para la posición {song.track_number} "
                f"y disco {song.disc_number or 'sin indicar'}."
            )
        disc, node = candidates[0]
        sources = [
            source
            for source in songs
            if source.track_number == song.track_number and _same_disc(disc, source.disc_number)
        ]
        if len(sources) != 1:
            raise TagWriteConflict("Varias canciones corresponden a la misma posición NFO.")
        changed = _set_values(node, "title", (song.title,) if song.title else ()) or changed
    return changed


def _apply(document: minidom.Document, values: AlbumNfoValues) -> bool:
    if values.year is not None and not 1 <= values.year <= 9999:
        raise TagWriteError("El año NFO debe estar entre 1 y 9999.")
    root = document.documentElement
    assert root is not None
    changed = _set_values(root, "title", (values.title,) if values.title else ())
    changed = _set_values(root, "genre", values.genres) or changed
    if values.thumb is not None:
        changed = _set_values(root, "thumb", (values.thumb,)) or changed
    changed = _set_values(root, "year", (f"{values.year:04d}",) if values.year else ()) or changed
    dates = _elements(root, "releasedate")
    if dates:
        target = (_release_date(_text(dates[0]), values.year),) if values.year else ()
        changed = _set_values(root, "releasedate", target) or changed
    if values.artists is not None:
        changed = _artists(root, values.artists) or changed
    changed = _song_titles(root, values.songs) or changed
    return changed


def _declaration(text: str) -> re.Match[str] | None:
    return re.match(r"\ufeff?(<\?xml\s.*?\?>)([ \t\r\n]*)", text, re.DOTALL)


def _needs_header_break(document: minidom.Document, original: bytes) -> bool:
    encoding = document.encoding or (
        "utf-16" if original.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8"
    )
    header = _declaration(original.decode(encoding))
    return header is not None and not any(char in header[2] for char in "\r\n")


def _serialize(document: minidom.Document, original: bytes) -> bytes:
    encoding = document.encoding or (
        "utf-16" if original.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8"
    )
    try:
        codecs.lookup(encoding)
        text = document.toxml(encoding=encoding, standalone=document.standalone).decode(encoding)
        # XML parsers normalize source line endings; preserve the original convention.
        original_text = original.decode(encoding)
        previous_header = _declaration(original_text)
        generated_header = _declaration(text)
        assert generated_header is not None
        gap = previous_header[2] if previous_header else ""
        if not any(char in gap for char in "\r\n"):
            gap = "\n"
        # Keep the declaration spelling and the whitespace discarded by minidom.
        gap = gap.replace("\r\n", "\n").replace("\r", "\n")
        declaration = previous_header[1] if previous_header else generated_header[1]
        text = declaration + gap + text[generated_header.end() :]
        trailing = re.search(r"[ \t\r\n]*\Z", original_text)
        assert trailing is not None
        text += trailing[0].replace("\r\n", "\n").replace("\r", "\n")
        if "\r\n" in original_text:
            text = text.replace("\n", "\r\n")
        result = text.encode(encoding)
        if original.startswith(codecs.BOM_UTF8) and not result.startswith(codecs.BOM_UTF8):
            result = codecs.BOM_UTF8 + result
        return result
    except (LookupError, UnicodeError, ValueError) as exc:
        raise TagWriteError(f"No se puede conservar la codificación NFO: {exc}") from exc


def _semantic(node: minidom.Node) -> object:
    attributes = tuple(sorted(node.attributes.items())) if isinstance(node, minidom.Element) else ()
    return (
        node.nodeType,
        node.nodeName,
        getattr(node, "data", None),
        attributes,
        tuple(_semantic(child) for child in node.childNodes),
    )


class XmlAlbumNfoCodec:
    def _read(self, path: Path) -> bytes:
        with path.open("rb") as stream:
            data = stream.read(MAX_NFO_BYTES + 1)
        return data

    def plan(self, path: Path, values: AlbumNfoValues) -> bool:
        original = self._read(path)
        document = _parse(original)
        try:
            return _apply(document, values) or _needs_header_break(document, original)
        finally:
            document.unlink()

    def write_verified(self, backup: Path, temporary: Path, values: AlbumNfoValues) -> None:
        original = self._read(backup)
        document = _parse(original)
        try:
            _apply(document, values)
            document.normalize()
            output = _serialize(document, original)
            # Check the complete tree, including unmanaged XML and prolog/epilog.
            expected = _semantic(document)
            verified = _parse(output)
            try:
                if _semantic(verified) != expected or _apply(verified, values):
                    raise TagWriteError("No se pudo verificar la conservación del XML NFO.")
            finally:
                verified.unlink()
            temporary.write_bytes(output)
            reopened = _parse(self._read(temporary))
            try:
                if _semantic(reopened) != expected:
                    raise TagWriteError("El NFO temporal no coincide con el documento verificado.")
            finally:
                reopened.unlink()
        finally:
            document.unlink()
