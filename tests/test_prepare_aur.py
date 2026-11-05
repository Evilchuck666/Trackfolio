"""Check that AUR recipes pin every source and reject unsafe release versions."""

import hashlib
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def prepare_aur():
    path = Path(__file__).resolve().parents[1] / "scripts" / "prepare_aur.py"
    spec = importlib.util.spec_from_file_location("prepare_aur", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.prepare


def test_recipe_pins_archive_and_desktop_files(prepare_aur, tmp_path):
    archive = tmp_path / "release.tar.gz"
    archive.write_bytes(b"verified release contents")
    destination = tmp_path / "aur"
    prepare_aur("1.2.3", archive, destination)
    recipe = (destination / "PKGBUILD").read_text()
    assert "pkgver=1.2.3" in recipe
    assert "SKIP" not in recipe
    assert "@DESKTOP_SHA256@" not in recipe
    assert "@ICON_SHA256@" not in recipe
    for source in (archive, destination / "trackfolio.desktop", destination / "trackfolio.svg"):
        assert hashlib.sha256(source.read_bytes()).hexdigest() in recipe
    assert "'!strip'" in recipe


@pytest.mark.parametrize("version", ["v1.2.3", "1.2", "01.2.3", "$(touch injected)", "1.2.3\n"])
def test_invalid_version_cannot_generate_recipe(prepare_aur, tmp_path, version):
    destination = tmp_path / "aur"
    with pytest.raises(ValueError):
        prepare_aur(version, tmp_path / "absent.tar.gz", destination)
    assert not destination.exists()
