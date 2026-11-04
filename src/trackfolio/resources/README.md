# Trackfolio resources

The GUI loads these files through `importlib.resources`, independently of the
working directory, installed fonts or desktop theme:

- `stylesheet.qss`: shared colors, spacing, focus states and sizes.
- `icons/*.svg`: original Trackfolio illustrations for the application and its
  actions. Rendered at several sizes to support scaled displays.
- `fonts/Inter-Regular.ttf` and `fonts/Inter-SemiBold.ttf`: unmodified Inter 4.1,
  distributed under the SIL Open Font License 1.1. See the [license](fonts/LICENSE.txt)
  and [provenance](fonts/README.md).
- `manifest.json`: SHA-256 hashes of runtime resources. `scripts/doctor.py`
  checks that they are distributed in full and match the manifest.

These files are included in the wheel and source distribution. The application
does not download resources at runtime.
