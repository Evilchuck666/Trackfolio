"""Shared recoverable errors for audio and sidecar publication."""


class TagWriteError(Exception):
    """A recoverable error suitable for presentation to a user."""


class TagWriteConflict(TagWriteError):
    pass


class TagWriteCancelled(TagWriteError):
    pass


class TagJournalError(TagWriteError):
    pass


class TagPublishedError(TagWriteError):
    """The rename succeeded but a subsequent durability check failed."""
