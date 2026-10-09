"""Load Trackfolio's shared style and artwork from installed package resources."""

from __future__ import annotations

from importlib.resources import files

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QStyleFactory

FONT_FILES = ("Inter-Regular.ttf", "Inter-SemiBold.ttf")
ICON_NAMES = frozenset(
    {"app", "open", "import", "refresh", "close", "minimize", "maximize", "restore"}
)
_font_family: str | None = None


def _load_font_family() -> str:
    global _font_family
    if _font_family is not None:
        return _font_family
    resources = files("trackfolio.resources")
    families: set[str] = set()
    for name in FONT_FILES:
        identifier = QFontDatabase.addApplicationFontFromData(
            QByteArray(resources.joinpath("fonts", name).read_bytes())
        )
        if identifier < 0:
            raise RuntimeError(f"No se pudo cargar la fuente empaquetada {name}.")
        families.update(QFontDatabase.applicationFontFamilies(identifier))
    if "Inter" not in families:
        raise RuntimeError("La fuente empaquetada no contiene la familia Inter.")
    _font_family = "Inter"
    return _font_family


def apply_theme(app: QApplication) -> None:
    """Apply Fusion, the packaged fonts, palette and stylesheet consistently."""
    available_styles = QStyleFactory.keys()
    if "Fusion" not in available_styles:
        raise RuntimeError("El estilo Fusion no está disponible.")
    app.setStyle("Fusion")
    font = QFont(_load_font_family())
    font.setPixelSize(13)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#10121b",
        QPalette.ColorRole.WindowText: "#eef0fa",
        QPalette.ColorRole.Base: "#181c29",
        QPalette.ColorRole.AlternateBase: "#1a1e2c",
        QPalette.ColorRole.ToolTipBase: "#252b41",
        QPalette.ColorRole.ToolTipText: "#eef0fa",
        QPalette.ColorRole.Text: "#eef0fa",
        QPalette.ColorRole.Button: "#252b41",
        QPalette.ColorRole.ButtonText: "#eef0fa",
        QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Highlight: "#343c64",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.Link: "#a5abff",
        QPalette.ColorRole.PlaceholderText: "#8994b0",
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#6f7891"))
    app.setPalette(palette)
    app.setStyleSheet(
        files("trackfolio.resources").joinpath("stylesheet.qss").read_text(encoding="utf-8")
    )
    # QSS wraps the selected Fusion style; retain its diagnostic identity.
    app.style().setObjectName("fusion")
    app.setWindowIcon(icon("app"))
    app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, True)


def icon(name: str) -> QIcon:
    """Render packaged SVG artwork at several resolutions without filesystem paths."""
    if name not in ICON_NAMES:
        raise ValueError(f"Icono desconocido: {name}.")
    data = files("trackfolio.resources").joinpath("icons", f"{name}.svg").read_bytes()
    renderer = QSvgRenderer(QByteArray(data))
    if not renderer.isValid():
        raise RuntimeError(f"El icono empaquetado {name} no es un SVG válido.")
    result = QIcon()
    for size in (16, 24, 32, 48, 64, 96, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        result.addPixmap(pixmap)
    return result
