"""Testseite: System-Datei (PPA/AUR) vor gebündelter Kopie (Flatpak)."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from print_ease import cups_client


class TestPageFile(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.system = os.path.join(self.root, "usr-share-cups")
        self.bundled = os.path.join(self.root, "app", "testprint")
        mock.patch.object(cups_client, "_SYSTEM_DATADIRS", (self.system,)).start()
        mock.patch.object(cups_client, "_BUNDLED_TESTPAGES", (self.bundled,)).start()
        mock.patch.dict(os.environ).start()
        os.environ.pop("CUPS_DATADIR", None)
        self.addCleanup(mock.patch.stopall)

    def touch(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()

    def test_system_file_keeps_pycups_default(self):
        self.touch(os.path.join(self.system, "data", "testprint"))
        self.touch(self.bundled)
        self.assertIsNone(cups_client._test_page_file())

    def test_cups_datadir_is_respected(self):
        datadir = os.path.join(self.root, "custom")
        self.touch(os.path.join(datadir, "data", "testprint.ps"))
        self.touch(self.bundled)
        os.environ["CUPS_DATADIR"] = datadir
        self.assertIsNone(cups_client._test_page_file())

    def test_flatpak_uses_bundled_copy(self):
        self.touch(self.bundled)
        self.assertEqual(cups_client._test_page_file(), self.bundled)

    def test_nothing_found_leaves_it_to_pycups(self):
        self.assertIsNone(cups_client._test_page_file())

    def test_print_test_page_passes_file_only_when_bundled(self):
        conn = mock.MagicMock()
        conn.printTestPage.return_value = 7
        session = mock.MagicMock()
        session.return_value.__enter__.return_value = conn
        with mock.patch.object(cups_client, "_cups_session", session):
            cups_client.print_test_page("P")
            self.touch(self.bundled)
            cups_client.print_test_page("P")
        self.assertEqual(conn.printTestPage.call_args_list,
                         [mock.call("P"), mock.call("P", file=self.bundled)])


if __name__ == "__main__":
    unittest.main()
