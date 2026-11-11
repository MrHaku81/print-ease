"""Ausgabeformate des Einzug-Scans.

Ausführen: python3 -m unittest discover -s tests -v
"""
import io
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from print_ease import scanner_client as sc
from print_ease.printer_model import ScannerInfo

try:
    from PIL import Image
except ImportError:
    Image = None

INFO = ScannerInfo("S", "h", 80, "http://h/eSCL", "S", 1, 1, [], [], [], None)


def jpeg(shade: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("L", (20, 30), shade).save(buffer, "JPEG")
    return buffer.getvalue()


class TempScanDir(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        for name, filename in (
            ("_default_output_path", "scan_x.jpg"),
            ("_default_duplex_output_path", "scan_duplex_x.pdf"),
            ("_default_platen_multipage_output_path", "scan_multipage_x.pdf"),
            ("_default_platen_archive_output_path", "scan_archive_x.tif"),
        ):
            patcher = mock.patch.object(sc, name, return_value=str(self.dir / filename))
            patcher.start()
            self.addCleanup(patcher.stop)


class SaveJpegs(TempScanDir):
    def test_one_page_is_one_file(self):
        path = sc._save_pages([b"a"], "single")
        self.assertEqual(path, str(self.dir / "scan_x.jpg"))
        self.assertEqual(Path(path).read_bytes(), b"a")

    def test_every_page_is_kept_in_one_folder(self):
        path = Path(sc._save_pages([b"a", b"b", b"c"], "single"))
        self.assertEqual(path, self.dir / "scan_x")
        self.assertEqual(
            [(f.name, f.read_bytes()) for f in sorted(path.iterdir())],
            [("001.jpg", b"a"), ("002.jpg", b"b"), ("003.jpg", b"c")],
        )


class SavePages(TempScanDir):
    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            sc._save_pages([b"a"], "unknown")


@unittest.skipIf(Image is None, "Pillow nicht installiert")
class SaveDocuments(TempScanDir):
    def tiff_frames(self, path):
        with Image.open(path) as image:
            return image.format, image.n_frames

    def pdf_pages(self, path):
        data = Path(path).read_bytes()
        self.assertTrue(data.startswith(b"%PDF"))
        return data.count(b"/Type /Page\n")

    def test_single_page_stays_in_chosen_format(self):
        self.assertEqual(self.pdf_pages(sc._save_pages([jpeg(10)], "multipage")), 1)
        self.assertEqual(self.tiff_frames(sc._save_pages([jpeg(10)], "archive")), ("TIFF", 1))

    def test_archive_keeps_all_pages(self):
        pages = [jpeg(10), jpeg(120), jpeg(240)]
        self.assertEqual(self.tiff_frames(sc._save_pages(pages, "archive")), ("TIFF", 3))

    def test_pdf_keeps_all_pages(self):
        pages = [jpeg(10), jpeg(120), jpeg(240)]
        path = sc._save_pages(pages, "multipage")
        self.assertEqual(path, str(self.dir / "scan_multipage_x.pdf"))
        self.assertEqual(self.pdf_pages(path), 3)

    def test_duplex_keeps_its_own_pdf_name(self):
        path = sc._save_pages([jpeg(10)], "multipage", pdf_path=sc._default_duplex_output_path)
        self.assertEqual(path, str(self.dir / "scan_duplex_x.pdf"))


class ScanAdfDocument(TempScanDir):
    def test_all_pages_reach_the_chosen_format(self):
        with mock.patch.object(sc, "scan_adf_all_pages", return_value=[b"a", b"b"]), \
             mock.patch.object(sc, "_save_pages", return_value="/out") as save:
            self.assertEqual(sc.scan_adf_document(INFO, mode="archive"), "/out")
        save.assert_called_once_with([b"a", b"b"], "archive", resolution=300)

    def test_no_pages_is_an_error(self):
        with mock.patch.object(sc, "scan_adf_all_pages", return_value=[]):
            with self.assertRaises(RuntimeError):
                sc.scan_adf_document(INFO)


class SoftwareDuplexMode(TempScanDir):
    def test_mode_is_followed_and_pages_stay_interleaved(self):
        with mock.patch.object(sc, "scan_adf_all_pages", side_effect=[[b"1", b"3"], [b"4", b"2"]]):
            path = Path(sc.scan_duplex_software(INFO, mode="single"))
        self.assertEqual([f.read_bytes() for f in sorted(path.iterdir())], [b"1", b"2", b"3", b"4"])


class SoftwareDuplexFlip(TempScanDir):
    def scan(self, states, flip):
        with mock.patch.object(sc, "scan_adf_all_pages", side_effect=[[b"1"], [b"2"]]) as all_pages, \
             mock.patch.object(sc, "get_adf_state", side_effect=states):
            self.all_pages = all_pages
            return sc.scan_duplex_software(INFO, flip_callback=flip, mode="single", **self.extra)

    extra = {}

    def test_second_pass_waits_for_flip(self):
        flip = mock.Mock(side_effect=lambda: self.assertEqual(self.all_pages.call_count, 1))
        self.scan(["ScannerAdfLoaded"], flip)
        flip.assert_called_once()
        self.assertEqual(self.all_pages.call_count, 2)

    def test_empty_feeder_asks_again_instead_of_scanning(self):
        flip = mock.Mock()
        self.scan(["ScannerAdfEmpty", "ScannerAdfEmpty", "ScannerAdfLoaded"], flip)
        self.assertEqual(flip.call_count, 3)

    def test_unknown_state_does_not_block_devices_without_sensor(self):
        flip = mock.Mock()
        self.scan([None], flip)
        flip.assert_called_once()

    def test_cancel_in_dialog_stops_without_asking_again(self):
        cancel = threading.Event()
        flip = mock.Mock(side_effect=cancel.set)
        self.extra = {"cancel_event": cancel}
        with self.assertRaises(InterruptedError):
            self.scan(["ScannerAdfEmpty"], flip)
        flip.assert_called_once()
        self.assertEqual(self.all_pages.call_count, 1)


if __name__ == "__main__":
    unittest.main()
