"""Voreinstellung des Modus je Quelle, ohne grafische Sitzung.

Ausführen: python3 -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from gui_import import import_scanner_panel  # noqa: E402

sp = import_scanner_panel()   # läuft auch ohne PyGObject/GTK


class FakeDrop:
    """Dropdown, das wie GTK nur bei einer echten Änderung benachrichtigt."""

    def __init__(self, selected=0):
        self.selected = selected
        self.on_change = None

    def get_selected(self):
        return self.selected

    def set_selected(self, index):
        if index != self.selected:
            self.selected = index
            if self.on_change:
                self.on_change(self, None)


class FakeSwitch:
    def __init__(self):
        self.active, self.visible = False, True

    def get_active(self):
        return self.active

    def set_active(self, value):
        self.active = value

    def set_visible(self, value):
        self.visible = value


def panel(sources=("Platen", "AdfSimplex"), saved=None):
    """Durchläuft dieselbe Reihenfolge wie ScannerPanel.__init__ ohne Widgets."""
    p = sp.ScannerPanel.__new__(sp.ScannerPanel)
    p._scanner = mock.Mock(resolutions=[300], color_modes=["RGB24"], name="S")
    p._settings_key = "scan_settings_S"
    p._sources = list(sources)
    p._duplex_modes = ["None", "AdfDuplexSoftware"]
    p._mode_options = p._build_mode_list()
    p._modes_by_source = dict(sp._DEFAULT_MODES)
    p._res_drop = FakeDrop()
    p._color_drop = FakeDrop()
    p._duplex_row = mock.Mock()
    p._duplex_drop = FakeDrop()
    p._duplex_drop.on_change = p._on_duplex_changed
    p._rotate_row = p._rotate_switch = FakeSwitch()
    p._mode_drop = FakeDrop()
    p._mode_drop.on_change = p._on_mode_changed
    p._src_drop = None
    if len(sources) > 1:
        p._src_drop = FakeDrop()
        p._src_drop.on_change = p._on_source_changed
    p._update_duplex_rows()
    with mock.patch.object(sp.settings, "get", return_value=saved):
        p._restore_scan_settings()
    p._apply_source_mode()
    return p


def choose_source(p, source):
    p._src_drop.set_selected(p._sources.index(source))


def choose_mode(p, mode):
    p._mode_drop.set_selected(p._mode_options.index(mode))


class Defaults(unittest.TestCase):
    def test_flatbed_keeps_single(self):
        self.assertEqual(panel()._get_selected_mode(), "single")

    def test_feeder_defaults_to_pdf(self):
        p = panel()
        choose_source(p, "AdfSimplex")
        self.assertEqual(p._get_selected_mode(), "multipage")

    def test_back_to_flatbed_restores_single(self):
        p = panel()
        choose_source(p, "AdfSimplex")
        choose_source(p, "Platen")
        self.assertEqual(p._get_selected_mode(), "single")

    def test_feeder_only_scanner_defaults_to_pdf(self):
        self.assertEqual(panel(sources=("AdfSimplex",))._get_selected_mode(), "multipage")


class ChosenModeWins(unittest.TestCase):
    def test_every_mode_stays_selectable_on_feeder(self):
        for mode in ("single", "multipage", "archive"):
            with self.subTest(mode=mode):
                p = panel()
                choose_source(p, "AdfSimplex")
                choose_mode(p, mode)
                self.assertEqual(p._get_selected_mode(), mode)

    def test_choice_survives_switching_source(self):
        p = panel()
        choose_mode(p, "archive")
        choose_source(p, "AdfSimplex")
        choose_mode(p, "single")
        choose_source(p, "Platen")
        self.assertEqual(p._get_selected_mode(), "archive")
        choose_source(p, "AdfSimplex")
        self.assertEqual(p._get_selected_mode(), "single")


class SavedSettings(unittest.TestCase):
    def test_saved_feeder_choice_is_restored(self):
        saved = {"source": "AdfSimplex", "modes": {"Platen": "archive", "AdfSimplex": "single"}}
        p = panel(saved=saved)
        self.assertEqual(p._get_selected_mode(), "single")
        choose_source(p, "Platen")
        self.assertEqual(p._get_selected_mode(), "archive")

    def test_old_format_does_not_override_feeder_default(self):
        p = panel(saved={"source": "AdfSimplex", "mode": "single"})
        self.assertEqual(p._get_selected_mode(), "multipage")

    def test_old_format_still_applies_to_flatbed(self):
        p = panel(saved={"source": "Platen", "mode": "archive"})
        self.assertEqual(p._get_selected_mode(), "archive")
        choose_source(p, "AdfSimplex")
        self.assertEqual(p._get_selected_mode(), "multipage")

    def test_unknown_saved_mode_is_ignored(self):
        p = panel(saved={"source": "Platen", "modes": {"Platen": "kaputt"}})
        self.assertEqual(p._get_selected_mode(), "single")

    def test_save_round_trip(self):
        p = panel()
        choose_source(p, "AdfSimplex")
        choose_mode(p, "archive")
        with mock.patch.object(sp.settings, "set") as save:
            p._save_scan_settings()
        stored = save.call_args.args[1]
        self.assertNotIn("mode", stored)
        self.assertEqual(sp._modes_from_saved(stored)["AdfSimplex"], "archive")


if __name__ == "__main__":
    unittest.main()
