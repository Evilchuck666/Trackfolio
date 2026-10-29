"""Dispose Qt windows while their QApplication and QObject owners are still alive."""

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QWidget


def dispose_window(window: QWidget) -> None:
    if not window.close():
        # MainWindow can defer closure while an import worker releases its resources.
        timer = QTimer(window)

        def finish() -> None:
            if window.close():
                timer.stop()
                window.deleteLater()

        timer.timeout.connect(finish)
        timer.start(10)
        return
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
