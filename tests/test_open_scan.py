"""„Öffnen“ und „Ordner öffnen“ für den letzten Scan (Gtk.FileLauncher gemockt).

Läuft auch ohne PyGObject/GTK (siehe gui_import).

Ausführen: python3 -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from gui_import import import_scanner_panel  # noqa: E402

sp = import_scanner_panel()

SCAN = "/home/u/Bilder/Scans/scan_20261114_080440.jpg"


class FakeGLibError(Exception):
    """Wie GLib.Error: domain, code, message."""

    def __init__(self, domain, code, message):
        super().__init__(message)
        self.domain, self.code, self.message = domain, code, message


class FakeLauncher:
    """Ruft den Callback sofort auf; *_finish liefert True oder wirft `error`."""

    instances = []

    def __init__(self, file, error=None):
        self.file, self.error = file, error
        self.calls = []
        FakeLauncher.instances.append(self)

    def _start(self, name, parent, cancellable, callback, data):
        self.calls.append((name, parent, cancellable))
        callback(self, f"result-{name}", data)

    def launch(self, *args):
        self._start("launch", *args)

    def open_containing_folder(self, *args):
        self._start("open_containing_folder", *args)

    def _finish(self, result):
        if self.error is not None:
            raise self.error
        return True

    launch_finish = open_containing_folder_finish = _finish


def make_panel(last=SCAN, root="window"):
    p = sp.ScannerPanel.__new__(sp.ScannerPanel)
    p._last_scan_path = last
    p._group = mock.Mock()
    p._group.get_root.return_value = root
    p._saved_row = mock.Mock()
    return p


class OpenLastScan(unittest.TestCase):
    def setUp(self):
        FakeLauncher.instances.clear()
        self.error = None
        new = lambda file: FakeLauncher(file, self.error)  # noqa: E731
        for target, name, value in (
            (sp.Gtk, "FileLauncher", mock.Mock(new=new)),
            (sp.Gio, "File", mock.Mock(new_for_path=lambda path: f"file:{path}")),
            (sp.Adw, "AlertDialog", mock.Mock()),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.dialog = sp.Adw.AlertDialog

    def run_open(self, folder, **panel_kwargs):
        p = make_panel(**panel_kwargs)
        with self.assertLogs("print_ease.gui.scanner_panel", "INFO") as logs:
            (p._open_last_scan_folder if folder else p._open_last_scan)()
        return p, logs.output

    def test_open_file_success_is_logged(self):
        _p, logs = self.run_open(folder=False)
        launcher, = FakeLauncher.instances
        self.assertEqual(launcher.file, f"file:{SCAN}")
        self.assertEqual(launcher.calls, [("launch", "window", None)])
        self.assertTrue(any(f"Datei geöffnet: {SCAN}" in line for line in logs))
        self.dialog.assert_not_called()

    def test_open_folder_success_is_logged(self):
        _p, logs = self.run_open(folder=True)
        launcher, = FakeLauncher.instances
        self.assertEqual(launcher.calls, [("open_containing_folder", "window", None)])
        self.assertTrue(any(f"Ordner geöffnet: {SCAN}" in line for line in logs))
        self.dialog.assert_not_called()

    def test_failure_shows_message_and_never_logs_success(self):
        for folder, heading in ((False, "Datei konnte nicht geöffnet werden"),
                                (True, "Ordner konnte nicht geöffnet werden")):
            with self.subTest(folder=folder):
                self.dialog.reset_mock()
                self.error = FakeGLibError("g-io-error-quark", 1, "No such file or directory")
                _p, logs = self.run_open(folder=folder)
                self.assertFalse(any("geöffnet:" in line and "nicht" not in line for line in logs), logs)
                self.assertTrue(any("ERROR" in line and "No such file" in line for line in logs))
                kwargs = self.dialog.call_args.kwargs
                self.assertEqual(kwargs["heading"], heading)
                self.assertIn(SCAN, kwargs["body"])
                self.assertIn("No such file or directory", kwargs["body"])
                self.dialog.return_value.present.assert_called_once_with("window")

    def test_false_without_exception_is_a_failure(self):
        with mock.patch.object(FakeLauncher, "_finish", lambda self, result: False), \
             mock.patch.object(FakeLauncher, "launch_finish", lambda self, result: False):
            _p, logs = self.run_open(folder=False)
        self.assertTrue(any("ERROR" in line for line in logs))
        self.dialog.assert_called_once()

    def test_user_cancel_is_no_error(self):
        for domain, code in (("gtk-dialog-error-quark", 1), ("gtk-dialog-error-quark", 2),
                             ("g-io-error-quark", 19)):
            with self.subTest(domain=domain, code=code):
                self.dialog.reset_mock()
                self.error = FakeGLibError(domain, code, "dismissed")
                _p, logs = self.run_open(folder=False)
                self.assertFalse(any("ERROR" in line for line in logs))
                self.dialog.assert_not_called()

    def test_without_window_the_error_goes_to_the_row(self):
        self.error = FakeGLibError("g-io-error-quark", 1, "kaputt")
        p, _logs = self.run_open(folder=True, root=None)
        self.dialog.assert_not_called()
        p._saved_row.set_subtitle.assert_called_once_with("Ordner konnte nicht geöffnet werden")

    def test_nothing_happens_without_last_scan(self):
        p = make_panel(last=None)
        p._open_last_scan()
        p._open_last_scan_folder()
        self.assertEqual(FakeLauncher.instances, [])


class FolderButtonState(unittest.TestCase):
    def test_enabled_after_successful_scan_only(self):
        p = sp.ScannerPanel.__new__(sp.ScannerPanel)
        p._last_scan_path = None
        for name in ("_spinner", "_scan_btn", "_cancel_btn", "_saved_row", "_open_btn", "_folder_btn"):
            setattr(p, name, mock.Mock())
        p._on_scan_done(False, "Fehler")
        p._folder_btn.set_sensitive.assert_not_called()
        p._on_scan_done(True, SCAN)
        p._folder_btn.set_sensitive.assert_called_once_with(True)
        self.assertEqual(p._last_scan_path, SCAN)


if __name__ == "__main__":
    unittest.main()
