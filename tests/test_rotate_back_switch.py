"""Schalter „Rückseiten um 180° drehen“ beim Software-Duplex, ohne grafische Sitzung.

Ausführen: python3 -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_panel_mode_default import choose_source, panel, sp  # noqa: E402


def choose_duplex(p, duplex):
    p._duplex_drop.set_selected(p._duplex_modes.index(duplex))


class Visibility(unittest.TestCase):
    def test_off_by_default_and_hidden_on_flatbed(self):
        p = panel()
        self.assertFalse(p._get_rotate_back())
        self.assertFalse(p._rotate_row.visible)

    def test_only_shown_for_software_duplex_on_feeder(self):
        p = panel()
        choose_source(p, "AdfSimplex")
        self.assertFalse(p._rotate_row.visible)          # Duplex aus
        choose_duplex(p, "AdfDuplexSoftware")
        self.assertTrue(p._rotate_row.visible)
        choose_source(p, "Platen")
        self.assertFalse(p._rotate_row.visible)
        self.assertFalse(p._duplex_row.set_visible.call_args.args[0])


class Persistence(unittest.TestCase):
    def test_saved_switch_is_restored(self):
        p = panel(saved={"source": "AdfSimplex", "duplex": "AdfDuplexSoftware", "rotate_back": True})
        self.assertTrue(p._get_rotate_back())
        self.assertTrue(p._rotate_row.visible)

    def test_old_settings_without_key_mean_off(self):
        p = panel(saved={"source": "AdfSimplex", "duplex": "AdfDuplexSoftware"})
        self.assertFalse(p._get_rotate_back())

    def test_save_round_trip(self):
        p = panel()
        p._rotate_switch.set_active(True)
        with mock.patch.object(sp.settings, "set") as save:
            p._save_scan_settings()
        self.assertIs(save.call_args.args[1]["rotate_back"], True)


class PassedToScan(unittest.TestCase):
    def run_scan(self, active):
        p = panel()
        p._rotate_switch.set_active(active)
        p._scanner.detect_paper_loaded = False
        p._cancel_btn = p._spinner = p._saved_row = p._open_btn = mock.Mock()

        class SyncThread:
            def __init__(self, target, daemon=None):
                self.target = target

            def start(self):
                self.target()

        with mock.patch.object(sp.threading, "Thread", SyncThread), \
             mock.patch.object(sp.GLib, "idle_add"), \
             mock.patch.object(sp.scanner_client, "scan_duplex_software",
                               return_value="/out.pdf") as scan:
            p._run_software_duplex(mock.Mock(), "RGB24", 300, "multipage")
        return scan.call_args.kwargs["rotate_back"]

    def test_switch_off_scans_without_rotation(self):
        self.assertIs(self.run_scan(False), False)

    def test_switch_on_scans_with_rotation(self):
        self.assertIs(self.run_scan(True), True)


if __name__ == "__main__":
    unittest.main()
