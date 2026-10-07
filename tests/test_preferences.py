"""Local settings roundtrip and damaged-settings recovery."""

from trackfolio.infrastructure.preferences import CatalogPreferences


def test_preferences_survive_restart_and_use_unicode_paths(tmp_path):
    database = tmp_path / "Música con espacios.sqlite3"
    database.touch()
    configuration = tmp_path / "configuration/settings.json"
    preferences = CatalogPreferences(configuration)
    assert preferences.last_catalog() is None
    preferences.remember(database)
    assert CatalogPreferences(configuration).last_catalog() == database.resolve()
    assert list(configuration.parent.iterdir()) == [configuration]
    database.unlink()
    assert preferences.last_catalog() is None


def test_damaged_or_unexpected_settings_start_with_no_catalog(tmp_path):
    configuration = tmp_path / "settings.json"
    preferences = CatalogPreferences(configuration)
    for value in ("not-json", "[]", '{"last_catalog": 42}', '{"last_catalog": ""}'):
        configuration.write_text(value, encoding="utf-8")
        assert preferences.last_catalog() is None
