"""Optionale Rückseiten-Drehung beim Software-Duplex und PDF-Seitengröße nach Scan-Auflösung.

Ausführen: python3 -m unittest discover -s tests -v
"""
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from PIL import Image
except ImportError:  # z. B. im Debian-Paketbau ohne python3-pil
    Image = None

NEEDS_PIL = "braucht Pillow, um echte JPEG-/PDF-Dateien zu erzeugen und zu prüfen"

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from print_ease import scanner_client as sc
from print_ease.printer_model import ScannerInfo

INFO = ScannerInfo("S", "h", 80, "http://h/eSCL", "S", 1, 1, [], [], [], None)


def marked_jpeg(dpi=None) -> bytes:
    """Weiße Seite mit schwarzem Block oben links — zeigt die Ausrichtung."""
    im = Image.new("L", (40, 60), 255)
    im.paste(0, (0, 0, 10, 10))
    buffer = io.BytesIO()
    im.save(buffer, "JPEG", **({"dpi": dpi} if dpi else {}))
    return buffer.getvalue()


def corner_is_dark(data: bytes, corner: str) -> bool:
    im = Image.open(io.BytesIO(data)).convert("L")
    w, h = im.size
    x, y = {"top-left": (2, 2), "bottom-right": (w - 3, h - 3)}[corner]
    return im.getpixel((x, y)) < 128


def pdf_page_sizes(path: str) -> list[tuple[float, float]]:
    import re
    data = Path(path).read_bytes()
    return [(float(a), float(b)) for a, b in
            re.findall(rb"/MediaBox \[ ?0 0 ([\d.]+) ([\d.]+) ?\]", data)]


class RotateBackPages(unittest.TestCase):
    @unittest.skipUnless(Image, NEEDS_PIL)
    def test_rotation_turns_the_page_and_keeps_dpi(self):
        rotated = sc._rotate_jpeg_180(marked_jpeg(dpi=(300, 300)))
        self.assertTrue(corner_is_dark(rotated, "bottom-right"))
        self.assertFalse(corner_is_dark(rotated, "top-left"))
        self.assertEqual(round(Image.open(io.BytesIO(rotated)).info["dpi"][0]), 300)

    def test_unreadable_data_stays_unchanged(self):
        self.assertEqual(sc._rotate_jpeg_180(b"kein jpeg"), b"kein jpeg")

    def test_without_pillow_the_page_stays_unchanged(self):
        with mock.patch.dict(sys.modules, {"PIL": None}):
            self.assertEqual(sc._rotate_jpeg_180(b"\xff\xd8seite"), b"\xff\xd8seite")

    def run_duplex(self, **kwargs):
        """Software-Duplex mit erkennbarer Drehung; liefert die gespeicherten Seiten.

        Die Drehung ist gemockt, die Seiten bleiben undurchsichtige Bytes –
        dafür ist kein Pillow nötig.
        """
        self.fronts = [b"F1", b"F2"]
        self.backs = [b"B2", b"B1"]  # kommen umgekehrt
        saved = {}

        def save(pages, mode, pdf_path=None, resolution=None):
            saved.update(pages=pages, resolution=resolution)
            return "/out"

        with mock.patch.object(sc, "scan_adf_all_pages", side_effect=[self.fronts, self.backs]), \
             mock.patch.object(sc, "get_adf_state", return_value="ScannerAdfLoaded"), \
             mock.patch.object(sc, "_rotate_jpeg_180", side_effect=lambda d: b"R:" + d), \
             mock.patch.object(sc, "_save_pages", side_effect=save):
            sc.scan_duplex_software(INFO, resolution=300, flip_callback=lambda: None, **kwargs)
        self.assertEqual(saved["resolution"], 300)
        return saved["pages"]

    def test_default_keeps_back_pages_unrotated_in_order(self):
        # run3 am Ricoh: Stapel als Ganzes gewendet → Rückseiten kommen aufrecht.
        pages = self.run_duplex()
        self.assertEqual(pages, [self.fronts[0], self.backs[1], self.fronts[1], self.backs[0]])

    def test_switch_on_rotates_only_second_pass_and_keeps_order(self):
        pages = self.run_duplex(rotate_back=True)
        self.assertEqual(pages, [self.fronts[0], b"R:" + self.backs[1],
                                 self.fronts[1], b"R:" + self.backs[0]])

    @unittest.skipUnless(Image, NEEDS_PIL)
    def test_switch_on_turns_real_back_page_upside_down(self):
        results = []

        def save(pages, *_a, **_k):
            results.append(pages)
            return "/out"

        with mock.patch.object(sc, "get_adf_state", return_value="ScannerAdfLoaded"), \
             mock.patch.object(sc, "_save_pages", side_effect=save):
            for rotate in (False, True):
                with mock.patch.object(sc, "scan_adf_all_pages",
                                       side_effect=[[marked_jpeg()], [marked_jpeg()]]):
                    sc.scan_duplex_software(INFO, flip_callback=lambda: None, rotate_back=rotate)
        off, on = results
        self.assertTrue(corner_is_dark(off[1], "top-left"))
        self.assertTrue(corner_is_dark(on[1], "bottom-right"))
        self.assertTrue(corner_is_dark(on[0], "top-left"))  # Vorderseite bleibt


@unittest.skipUnless(Image, NEEDS_PIL)
class PdfResolution(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = str(Path(tmp.name) / "x.pdf")

    def a4_jpeg(self, dpi=None) -> bytes:
        buffer = io.BytesIO()
        Image.new("RGB", (2550, 3508), "white").save(buffer, "JPEG", **({"dpi": dpi} if dpi else {}))
        return buffer.getvalue()

    def test_page_size_follows_scan_resolution(self):
        sc._create_pdf([self.a4_jpeg()], self.out, resolution=300)
        (w, h), = pdf_page_sizes(self.out)
        self.assertAlmostEqual(w, 612, delta=1)    # 8,5 Zoll
        self.assertAlmostEqual(h, 842, delta=1)    # 297 mm

    def test_without_resolution_the_jpeg_dpi_is_used(self):
        sc._create_pdf([self.a4_jpeg(dpi=(300, 300))], self.out)
        (w, _h), = pdf_page_sizes(self.out)
        self.assertAlmostEqual(w, 612, delta=1)

    def test_without_any_hint_200_dpi_as_before(self):
        sc._create_pdf([self.a4_jpeg()], self.out)
        (w, _h), = pdf_page_sizes(self.out)
        self.assertAlmostEqual(w, 918, delta=1)


class SavePagesResolution(unittest.TestCase):
    def test_save_pages_passes_resolution_to_pdf(self):
        out = "/nirgends/x.pdf"   # _create_pdf ist gemockt, es wird nichts geschrieben
        with mock.patch.object(sc, "_create_pdf") as create:
            sc._save_pages([b"a"], "multipage", pdf_path=lambda: out, resolution=600)
        create.assert_called_once_with([b"a"], out, resolution=600)


if __name__ == "__main__":
    unittest.main()
