# Recursos de Trackfolio

La GUI carga estos archivos mediante `importlib.resources`, sin depender del
directorio de ejecución, de fuentes instaladas o del tema del escritorio:

- `stylesheet.qss`: colores, espaciado, estados de foco y tamaños compartidos.
- `icons/*.svg`: ilustraciones originales de Trackfolio para la aplicación y sus
  acciones. Se renderizan a varios tamaños para admitir pantallas con escalado.
- `fonts/Inter-Regular.ttf` y `fonts/Inter-SemiBold.ttf`: Inter 4.1, sin modificar,
  distribuida bajo SIL Open Font License 1.1. Véase [licencia](fonts/LICENSE.txt)
  y [procedencia](fonts/README.md).
- `manifest.json`: SHA-256 de los recursos de ejecución. `scripts/doctor.py`
  comprueba que se distribuyen completos y que coinciden con el manifiesto.

Se incluyen en el wheel y la distribución de fuentes. La aplicación no descarga
recursos durante su ejecución.
