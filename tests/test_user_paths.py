"""Pfade für Scans, Einstellungen und Log über die XDG-Verzeichnisse (GLib gemockt).

Läuft auch ohne PyGObject: gi.repository wird für jeden Test ersetzt.

Ausführen: python3 -m unittest discover -s tests -v
"""
import json
import re
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from print_ease import _log, settings  # noqa: E402
from print_ease import scanner_client as sc  # noqa: E402


def fake_glib(pictures=None, config=None, data=None):
    """gi + gi.repository mit einem GLib-Ersatz für sys.modules."""
    glib = types.SimpleNamespace(
        UserDirectory=types.SimpleNamespace(DIRECTORY_PICTURES="PICTURES"),
        get_user_special_dir=mock.Mock(return_value=pictures),
        get_user_config_dir=mock.Mock(return_value=config),
        get_user_data_dir=mock.Mock(return_value=data),
    )
    repository = types.ModuleType("gi.repository")
    repository.GLib = glib
    gi = types.ModuleType("gi")
    gi.repository = repository
    return {"gi": gi, "gi.repository": repository}


NO_GI = {"gi": None, "gi.repository": None}   # Import schlägt fehl


class TempDirTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.home = self.tmp / "home"
        self.home.mkdir()
        patcher = mock.patch.object(Path, "home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)


class ScanOutputPaths(TempDirTest):
    FUNCTIONS = {
        "_default_output_path": r"scan_\d{8}_\d{6}\.jpg",
        "_default_duplex_output_path": r"scan_duplex_\d{8}_\d{6}\.pdf",
        "_default_platen_multipage_output_path": r"scan_multipage_\d{8}_\d{6}\.pdf",
        "_default_platen_archive_output_path": r"scan_archive_\d{8}_\d{6}\.tif",
    }

    def test_scans_go_to_pictures_scans(self):
        pictures = self.tmp / "Bilder"
        for name, pattern in self.FUNCTIONS.items():
            with self.subTest(function=name), \
                 mock.patch.dict(sys.modules, fake_glib(pictures=str(pictures))), \
                 self.assertNoLogs("print_ease.scanner_client", "WARNING"):
                path = Path(getattr(sc, name)())
            self.assertEqual(path.parent, pictures / "Scans")
            self.assertTrue(path.parent.is_dir())
            self.assertRegex(path.name, f"^{pattern}$")

    def test_unknown_pictures_dir_falls_back_to_home_and_warns(self):
        for label, modules in (("GLib liefert None", fake_glib(pictures=None)),
                               ("GLib liefert ''", fake_glib(pictures="")),
                               ("kein gi", NO_GI)):
            with self.subTest(label), self.flatpak(False), mock.patch.dict(sys.modules, modules), \
                 self.assertLogs("print_ease.scanner_client", "WARNING") as logs:
                path = Path(sc._default_output_path())
            self.assertEqual(path.parent, self.home / "Scans")
            self.assertTrue(any("Bilder-Ordner" in line for line in logs.output))

    def flatpak(self, present: bool):
        info = self.tmp / ".flatpak-info"
        if present:
            info.write_text("[Application]\nname=at.printease.PrintEase\n")
        return mock.patch.object(sc, "_FLATPAK_INFO", info)

    def test_in_flatpak_without_pictures_uses_persistent_data_dir(self):
        data = self.tmp / "var-app" / "data"
        with self.flatpak(True), \
             mock.patch.dict(sys.modules, fake_glib(pictures=None, data=str(data))), \
             self.assertLogs("print_ease.scanner_client", "WARNING") as logs:
            path = Path(sc._default_duplex_output_path())
        self.assertEqual(path.parent, data / "Scans")
        self.assertTrue(path.parent.is_dir())
        self.assertIn(str(data / "Scans"), logs.output[0])

    def test_in_flatpak_pictures_still_win(self):
        pictures = self.tmp / "Bilder"
        data = self.tmp / "var-app" / "data"
        with self.flatpak(True), \
             mock.patch.dict(sys.modules, fake_glib(pictures=str(pictures), data=str(data))):
            self.assertEqual(Path(sc._default_output_path()).parent, pictures / "Scans")

    def test_outside_flatpak_fallback_stays_home(self):
        data = self.tmp / "local-share"
        with self.flatpak(False), \
             mock.patch.dict(sys.modules, fake_glib(pictures=None, data=str(data))), \
             self.assertLogs("print_ease.scanner_client", "WARNING"):
            self.assertEqual(Path(sc._default_output_path()).parent, self.home / "Scans")

    def test_in_flatpak_without_any_glib_falls_back_to_home(self):
        with self.flatpak(True), mock.patch.dict(sys.modules, NO_GI), \
             self.assertLogs("print_ease.scanner_client", "WARNING"):
            self.assertEqual(Path(sc._default_output_path()).parent, self.home / "Scans")


class SettingsPath(TempDirTest):
    def test_uses_glib_config_dir(self):
        config = self.tmp / "var-app-config"
        with mock.patch.dict(sys.modules, fake_glib(config=str(config))):
            self.assertEqual(settings._settings_path(), config / "print-ease" / "settings.json")

    def test_without_glib_falls_back_to_dot_config(self):
        for modules in (NO_GI, fake_glib(config=None)):
            with self.subTest(modules=modules), mock.patch.dict(sys.modules, modules):
                self.assertEqual(settings._settings_path(),
                                 self.home / ".config" / "print-ease" / "settings.json")

    def store(self, config: Path, legacy: Path):
        with mock.patch.dict(sys.modules, fake_glib(config=str(config))), \
             mock.patch.object(settings, "_LEGACY_PATH", legacy):
            return settings._Settings()

    def test_round_trip_in_new_location(self):
        config = self.tmp / "cfg"
        legacy = self.home / ".config" / "print-ease" / "settings.json"
        with mock.patch.object(settings, "_LEGACY_PATH", legacy):
            self.store(config, legacy).set_value("language", "de")
            self.assertEqual(self.store(config, legacy).get("language"), "de")
        self.assertFalse(legacy.exists())

    def test_old_file_is_read_until_first_save(self):
        config = self.tmp / "cfg"
        legacy = self.home / ".config" / "print-ease" / "settings.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text(json.dumps({"language": "fr"}), encoding="utf-8")
        with mock.patch.object(settings, "_LEGACY_PATH", legacy):
            store = self.store(config, legacy)
            self.assertEqual(store.get("language"), "fr")
            store.set_value("theme", "dark")
        new = json.loads((config / "print-ease" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(new, {"language": "fr", "theme": "dark"})

    def test_new_file_wins_over_old_file(self):
        config = self.tmp / "cfg"
        legacy = self.home / ".config" / "print-ease" / "settings.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text(json.dumps({"language": "fr"}), encoding="utf-8")
        new = config / "print-ease" / "settings.json"
        new.parent.mkdir(parents=True)
        new.write_text(json.dumps({"language": "it"}), encoding="utf-8")
        with mock.patch.object(settings, "_LEGACY_PATH", legacy):
            self.assertEqual(self.store(config, legacy).get("language"), "it")


class LogPath(TempDirTest):
    def test_uses_glib_data_dir(self):
        data = self.tmp / "var-app-data"
        with mock.patch.dict(sys.modules, fake_glib(data=str(data))):
            self.assertEqual(_log._get_log_path(), data / "print-ease" / "print-ease.log")
        self.assertTrue((data / "print-ease").is_dir())

    def test_without_glib_falls_back_to_local_share(self):
        for modules in (NO_GI, fake_glib(data=None)):
            with self.subTest(modules=modules), mock.patch.dict(sys.modules, modules):
                self.assertEqual(_log._get_log_path(),
                                 self.home / ".local" / "share" / "print-ease" / "print-ease.log")


class ManifestGrantsPictures(unittest.TestCase):
    def test_flatpak_has_pictures_access_but_not_home(self):
        manifest = Path(__file__).resolve().parents[1] / "flatpak" / "at.printease.PrintEase.yml"
        if not manifest.exists():   # pybuild kopiert nur tests/, nicht flatpak/
            self.skipTest("Flatpak-Manifest nicht im Testverzeichnis vorhanden")
        args = re.findall(r"^\s*-\s*(--filesystem=\S+)", manifest.read_text(encoding="utf-8"), re.M)
        self.assertEqual(args, ["--filesystem=xdg-pictures"])


if __name__ == "__main__":
    unittest.main()
