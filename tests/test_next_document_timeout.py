"""Wartezeit auf NextDocument.

Ausführen: python3 -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from print_ease import constants
from print_ease import scanner_client as sc


def response(body: bytes = b"page") -> mock.MagicMock:
    resp = mock.MagicMock(status=200, headers={})
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    return resp


class NextDocumentTimeout(unittest.TestCase):
    def test_value_covers_slow_600_dpi_scans(self):
        self.assertEqual(constants.NEXT_DOCUMENT_TIMEOUT, 60)

    def test_simplex_fetch_uses_constant(self):
        with mock.patch.object(sc.urllib.request, "urlopen", return_value=response()) as urlopen:
            self.assertEqual(sc._fetch_next_document("http://h/job"), b"page")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], constants.NEXT_DOCUMENT_TIMEOUT)

    def test_duplex_fetch_uses_constant(self):
        with mock.patch.object(sc.urllib.request, "urlopen", return_value=response()) as urlopen:
            self.assertEqual(sc._fetch_next_duplex_page("http://h/job")[0], b"page")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], constants.NEXT_DOCUMENT_TIMEOUT)

    def test_read_timeout_is_reported_not_retried(self):
        with mock.patch.object(
            sc.urllib.request, "urlopen", side_effect=TimeoutError("timed out")
        ) as urlopen:
            with self.assertRaises(TimeoutError):
                sc._fetch_next_document("http://h/job")
        self.assertEqual(urlopen.call_count, 1)


if __name__ == "__main__":
    unittest.main()
