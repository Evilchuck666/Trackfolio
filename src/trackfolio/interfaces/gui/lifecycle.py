"""Dispose Qt windows while their QApplication and QObject owners are still alive."""

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QWidget


def dispose_window(window: QWidget) -> None:
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
