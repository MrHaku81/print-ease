"""
Scanner-Erkennung und Scan-Funktion via eSCL (AirScan / Mopria Scan).

Primär: HTTP-Probe der eSCL-Endpunkte bekannter Netzwerkgeräte.
Fallback: Avahi-Suche nach _uscan._tcp / _uscans._tcp.
"""
from __future__ import annotations

import io
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Callable

from print_ease._i18n import _
from print_ease._log import get_logger
from print_ease.constants import AVAHI_TIMEOUT, CUPS_TIMEOUT, ESCL_TIMEOUT
from print_ease.printer_model import ScannerInfo

log = get_logger(__name__)

_NS_SCAN = "http://schemas.hp.com/imaging/escl/2011/05/03"
_NS_PWG  = "http://www.pwg.org/schemas/2010/12/sm"
_NS = {"scan": _NS_SCAN, "pwg": _NS_PWG}

_ESCL_PATH = "/eSCL"

# eSCL/AirScan-Standard: lokales Netzwerk, selbstsignierte Certs.
# Apple Print, Mopria und andere Clients deaktivieren ebenfalls
# die Cert-Verifikation für eSCL — keine Sicherheitslücke,
# sondern Industrie-Standardpraxis.
_ESCL_SSL_CONTEXT = ssl.create_default_context()
_ESCL_SSL_CONTEXT.check_hostname = False
_ESCL_SSL_CONTEXT.verify_mode = ssl.CERT_NONE

_SCAN_SETTINGS_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<scan:ScanSettings
    xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <scan:Version>2.6</scan:Version>
  <scan:ScanRegions>
    <scan:ScanRegion>
      <scan:XOffset>0</scan:XOffset>
      <scan:YOffset>0</scan:YOffset>
      <scan:Width>{width}</scan:Width>
      <scan:Height>{height}</scan:Height>
    </scan:ScanRegion>
  </scan:ScanRegions>
  <scan:InputSource>{source}</scan:InputSource>
  <scan:ColorMode>{color_mode}</scan:ColorMode>
  <scan:XResolution>{resolution}</scan:XResolution>
  <scan:YResolution>{resolution}</scan:YResolution>
  <scan:DocumentFormat>image/jpeg</scan:DocumentFormat>
</scan:ScanSettings>"""


# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------

def supports_adf(scanner: ScannerInfo) -> bool:
    return "AdfSimplex" in scanner.document_sources


def supports_hardware_duplex(scanner: ScannerInfo) -> bool:
    return "AdfDuplex" in scanner.document_sources


def get_adf_state(escl_url: str) -> str | None:
    """
    Gibt den aktuellen AdfState aus ScannerStatus zurück.
    Mögliche Werte: 'ScannerAdfEmpty', 'ScannerAdfLoaded', 'ScannerAdfJam', ...
    Gibt None zurück bei Fehler oder wenn kein AdfState vorhanden.
    """
    try:
        with urllib.request.urlopen(f"{escl_url}/ScannerStatus", timeout=ESCL_TIMEOUT, context=_ESCL_SSL_CONTEXT) as resp:
            root = ET.fromstring(resp.read())
        return root.findtext("scan:AdfState", None, _NS)
    except Exception as exc:
        log.debug("ScannerStatus nicht abrufbar (%s): %s", escl_url, exc)
        return None


def get_scanner_capabilities(escl_url: str, linked_printer: str | None = None) -> ScannerInfo | None:
    """
    Ruft ScannerCapabilities ab und parst die XML-Antwort.
    Gibt None zurück wenn das Gerät kein eSCL unterstützt.
    """
    caps_url = f"{escl_url}/ScannerCapabilities"
    try:
        req = urllib.request.Request(caps_url, headers={"Accept": "application/xml"})
        with urllib.request.urlopen(req, timeout=ESCL_TIMEOUT, context=_ESCL_SSL_CONTEXT) as resp:
            if resp.status != 200:
                return None
            data = resp.read()
    except (urllib.error.URLError, OSError) as exc:
        log.warning("Kein eSCL bei %s: %s", caps_url, exc)
        return None

    try:
        return _parse_capabilities(data, escl_url, linked_printer)
    except ET.ParseError as exc:
        log.warning("eSCL XML-Parse-Fehler bei %s: %s", escl_url, exc)
        return None


def discover_scanners(linked_printers: dict[str, str] | None = None) -> list[ScannerInfo]:
    """
    Findet eSCL-Scanner im Netzwerk.

    Strategie:
    1. Avahi nach _uscan._tcp / _uscans._tcp (falls vorhanden)
    2. Alle bekannten Netzwerkdrucker-IPs zusätzlich proben

    linked_printers: {ip_adresse: cups_druckername} — aus avahi_client
    """
    candidate_urls: set[str] = set()

    # Strategie 1: Avahi _uscan
    candidate_urls.update(_avahi_scanner_urls())

    # Strategie 2: Netzwerkdrucker proben
    if linked_printers:
        for ip in linked_printers:
            candidate_urls.add(f"http://{ip}{_ESCL_PATH}")

    scanners: list[ScannerInfo] = []
    seen: set[str] = set()

    for url in candidate_urls:
        if url in seen:
            continue
        seen.add(url)
        printer_name = (linked_printers or {}).get(_host_from_url(url))
        scanner = get_scanner_capabilities(url, linked_printer=printer_name)
        if scanner:
            scanners.append(scanner)
            log.info("Scanner gefunden: %s @ %s", scanner.name, scanner.escl_url)

    return scanners


def scan_document(
    scanner: ScannerInfo,
    color_mode: str = "RGB24",
    resolution: int = 300,
    source: str = "Platen",
    output_path: str | None = None,
    cancel_event=None,
) -> str:
    """
    Scannt ein Dokument via eSCL und speichert es als JPEG.
    Gibt den Pfad zur gespeicherten Datei zurück.
    """
    xml = _SCAN_SETTINGS_XML.format(
        width=scanner.max_width,
        height=scanner.max_height,
        source=source,
        color_mode=color_mode,
        resolution=resolution,
    ).encode("utf-8")

    log.info("Scan starten: %s, %s, %d dpi, Quelle=%s", scanner.name, color_mode, resolution, source)

    job_url = _create_scan_job(scanner.escl_url, xml)
    log.debug("Scan-Job angelegt: %s", job_url)

    try:
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Scan abgebrochen")
        image_data = _fetch_next_document(job_url, cancel_event=cancel_event)
        log.debug("Scan-Daten erhalten: %d Bytes", len(image_data))
    finally:
        _delete_job(job_url)

    if output_path is None:
        output_path = _default_output_path()

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_bytes(image_data)

    log.info("Scan gespeichert: %s", output_path)
    return output_path


def scan_adf_all_pages(
    scanner: ScannerInfo,
    color_mode: str = "RGB24",
    resolution: int = 300,
    cancel_event=None,
) -> list[bytes]:
    """
    Scannt alle Seiten aus dem ADF-Einzug in einem Job.
    Gibt eine Liste von JPEG-Bytes zurück (eine je Seite).
    """
    xml = _SCAN_SETTINGS_XML.format(
        width=scanner.max_width,
        height=scanner.max_height,
        source="AdfSimplex",
        color_mode=color_mode,
        resolution=resolution,
    ).encode("utf-8")

    log.info("ADF-Scan starten: %s, %s, %d dpi", scanner.name, color_mode, resolution)
    job_url = _create_scan_job(scanner.escl_url, xml)
    log.debug("ADF-Scan-Job angelegt: %s", job_url)

    pages: list[bytes] = []
    try:
        while True:
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("Scan abgebrochen")
            try:
                data = _fetch_next_document(job_url, cancel_event=cancel_event)
                pages.append(data)
                log.debug("ADF-Seite %d gescannt (%d Bytes)", len(pages), len(data))
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    break
                raise
    finally:
        _delete_job(job_url)

    log.info("ADF-Scan abgeschlossen: %d Seiten", len(pages))
    return pages


def scan_duplex_software(
    scanner: ScannerInfo,
    color_mode: str = "RGB24",
    resolution: int = 300,
    cancel_event=None,
    flip_callback: Callable[[], None] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> str:
    """
    Software-Duplex in zwei ADF-Durchgängen.

    flip_callback() wird zwischen den Durchgängen aufgerufen und blockiert,
    bis der Benutzer den Stapel umgedreht und bestätigt hat (oder abbricht).
    progress_callback(stage) meldet Fortschritt: "front", "back", "pdf".
    Gibt den Pfad zur erstellten PDF-Datei zurück.
    """
    if progress_callback:
        progress_callback("front")

    front_pages = scan_adf_all_pages(scanner, color_mode, resolution, cancel_event)
    if not front_pages:
        raise RuntimeError(_("Keine Seiten im ADF-Einzug gescannt"))

    if cancel_event and cancel_event.is_set():
        raise InterruptedError("Scan abgebrochen")

    if flip_callback:
        flip_callback()  # blockiert; kann InterruptedError werfen

    if cancel_event and cancel_event.is_set():
        raise InterruptedError("Scan abgebrochen")

    if progress_callback:
        progress_callback("back")

    back_pages = scan_adf_all_pages(scanner, color_mode, resolution, cancel_event)
    # Rückseiten kommen umgekehrt aus dem Einzug → zurückdrehen
    back_pages = list(reversed(back_pages))

    if cancel_event and cancel_event.is_set():
        raise InterruptedError("Scan abgebrochen")

    if progress_callback:
        progress_callback("pdf")

    # Vorder- und Rückseiten abwechselnd zusammenfügen
    all_pages: list[bytes] = []
    for i, front in enumerate(front_pages):
        all_pages.append(front)
        if i < len(back_pages):
            all_pages.append(back_pages[i])

    output_path = _default_duplex_output_path()
    _create_pdf(all_pages, output_path)

    log.info("Duplex-PDF erstellt: %s (%d Seiten)", output_path, len(all_pages))
    return output_path


def scan_adf_hardware_duplex(
    scanner: ScannerInfo,
    color_mode: str = "RGB24",
    resolution: int = 300,
    cancel_event=None,
    progress_callback: Callable[[int], None] | None = None,
) -> str:
    """Hardware-Duplex-Scan via eSCL.

    BETA — nach eSCL-Spec implementiert, aber mangels Hardware-Duplex-
    fähigem Test-Gerät nicht getestet. Feedback erwünscht.

    Sendet einen einzigen eSCL-Job mit InputSource=AdfDuplex. Sammelt
    alle gelieferten Seiten, sortiert nach SheetNumber + Side wenn
    vorhanden, sonst nach Stream-Reihenfolge (Annahme: Front/Back/...).
    Gibt den Pfad zur erstellten PDF-Datei zurück.
    """
    xml = _SCAN_SETTINGS_XML.format(
        width=scanner.max_width,
        height=scanner.max_height,
        source="AdfDuplex",
        color_mode=color_mode,
        resolution=resolution,
    ).encode("utf-8")

    log.info(
        "Hardware-Duplex-Scan starten (BETA): %s, %s, %d dpi",
        scanner.name, color_mode, resolution,
    )
    job_url = _create_scan_job(scanner.escl_url, xml)
    log.debug("Hardware-Duplex-Job angelegt: %s", job_url)

    pages: list[tuple[bytes, int | None, str | None]] = []
    doc_url = f"{job_url}/NextDocument"
    page_index = 0

    try:
        while True:
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("Scan abgebrochen")

            done = False
            for attempt in range(30):
                if cancel_event and cancel_event.is_set():
                    raise InterruptedError("Scan abgebrochen")
                try:
                    with urllib.request.urlopen(
                        urllib.request.Request(doc_url),
                        timeout=15,
                        context=_ESCL_SSL_CONTEXT,
                    ) as resp:
                        data = resp.read()
                        sheet_str = (
                            resp.headers.get("X-Sheet-Number")
                            or resp.headers.get("X-Page-Number")
                        )
                        side = (
                            resp.headers.get("X-Side")
                            or resp.headers.get("X-Scan-Side")
                        )
                        sheet = int(sheet_str) if sheet_str and sheet_str.isdigit() else None
                        pages.append((data, sheet, side))
                        page_index += 1
                        log.info(
                            "Seite empfangen: page=%d, sheet=%s, side=%s, size=%d bytes",
                            page_index, sheet_str, side, len(data),
                        )
                        if progress_callback:
                            progress_callback(page_index)
                        break
                except urllib.error.HTTPError as exc:
                    if exc.code == 404:
                        done = True
                        break
                    if exc.code == 503:
                        log.debug("Scanner verarbeitet noch (Versuch %d)...", attempt + 1)
                        time.sleep(1)
                        continue
                    raise
            else:
                raise TimeoutError("Scanner hat nicht innerhalb der erwarteten Zeit geantwortet")

            if done:
                break
    finally:
        _delete_job(job_url)

    if not pages:
        raise RuntimeError(_("Keine Seiten vom Scanner empfangen"))

    log.info("Hardware-Duplex-Scan abgeschlossen: %d Seiten", len(pages))

    all_have_meta = all(sheet is not None and side is not None for _, sheet, side in pages)
    if all_have_meta:
        side_order = {"Front": 0, "front": 0, "Back": 1, "back": 1}
        pages.sort(key=lambda p: (p[1] or 0, side_order.get(p[2] or "", 0)))
        log.debug("Seiten nach Metadaten sortiert (SheetNumber + Side)")
    else:
        log.warning(
            "Scanner liefert keine Duplex-Metadaten, vertraue auf "
            "Stream-Reihenfolge (Annahme: Front/Back/Front/Back...)"
        )

    jpeg_pages = [data for data, _, _ in pages]
    output_path = _default_duplex_output_path()
    _create_pdf(jpeg_pages, output_path)
    log.info("Hardware-Duplex-PDF erstellt: %s (%d Seiten)", output_path, len(pages))
    return output_path


# ---------------------------------------------------------------------------
# eSCL HTTP-Ablauf
# ---------------------------------------------------------------------------

def _create_scan_job(escl_url: str, xml_body: bytes) -> str:
    req = urllib.request.Request(
        f"{escl_url}/ScanJobs",
        data=xml_body,
        method="POST",
        headers={"Content-Type": "application/xml"},
    )
    with urllib.request.urlopen(req, timeout=CUPS_TIMEOUT, context=_ESCL_SSL_CONTEXT) as resp:
        if resp.status not in (200, 201):
            raise RuntimeError(f"ScanJob fehlgeschlagen: HTTP {resp.status}")
        location = resp.getheader("Location", "")
        if not location:
            raise RuntimeError("Kein Location-Header in ScanJob-Antwort")
        # Location kann absolut oder relativ sein
        if location.startswith("/"):
            parsed = urllib.parse.urlparse(escl_url)
            return f"{parsed.scheme}://{parsed.netloc}{location}"
        return location


def _fetch_next_document(job_url: str, max_retries: int = 30, cancel_event=None) -> bytes:
    doc_url = f"{job_url}/NextDocument"
    for attempt in range(max_retries):
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Scan abgebrochen")
        try:
            with urllib.request.urlopen(doc_url, timeout=15, context=_ESCL_SSL_CONTEXT) as resp:
                if resp.status == 200:
                    return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 503:
                log.debug("Scanner verarbeitet noch (Versuch %d)...", attempt + 1)
                time.sleep(1)
                continue
            raise
    raise TimeoutError("Scanner hat nicht innerhalb der erwarteten Zeit geantwortet")


def _delete_job(job_url: str) -> None:
    try:
        req = urllib.request.Request(job_url, method="DELETE")
        urllib.request.urlopen(req, timeout=5, context=_ESCL_SSL_CONTEXT)
    except Exception as exc:
        log.debug("Scan-Job konnte nicht gelöscht werden: %s", exc)


# ---------------------------------------------------------------------------
# XML-Parser
# ---------------------------------------------------------------------------

def _parse_capabilities(data: bytes, escl_url: str, linked_printer: str | None) -> ScannerInfo:
    root = ET.fromstring(data)

    make_model = (
        _text(root, "pwg:MakeAndModel")
        or _text(root, "scan:MakeAndModel")
        or "Unbekannter Scanner"
    )
    manufacturer = _text(root, "scan:Manufacturer") or ""
    full_name = f"{manufacturer} {make_model}".strip() if manufacturer else make_model

    parsed = urllib.parse.urlparse(escl_url)
    host = parsed.hostname or escl_url
    port = parsed.port or 80

    # Quellen + ihre Fähigkeiten einlesen
    sources: list[str] = []
    color_modes: list[str] = []
    resolutions: list[int] = []
    max_width = max_height = 0

    for src_tag, src_name, caps_tag in [
        ("scan:Platen", "Platen", "scan:PlatenInputCaps"),
        ("scan:Adf",    "AdfSimplex", "scan:AdfSimplexInputCaps"),
    ]:
        src_el = root.find(src_tag, _NS)
        if src_el is None:
            continue
        caps = src_el.find(caps_tag, _NS)
        if caps is None:
            # Fallback: irgendein InputCaps-Element
            caps = src_el.find(".//{%s}InputCaps" % _NS_SCAN)
        if caps is None:
            sources.append(src_name)
            continue

        sources.append(src_name)

        w = _int(caps, "scan:MaxWidth")
        h = _int(caps, "scan:MaxHeight")
        if w and h and (w * h > max_width * max_height):
            max_width, max_height = w, h

        for cm in caps.findall(".//scan:ColorMode", _NS):
            if cm.text and cm.text not in color_modes:
                color_modes.append(cm.text)

        for dr in caps.findall(".//scan:DiscreteResolution", _NS):
            xr = _int(dr, "scan:XResolution")
            if xr and xr not in resolutions:
                resolutions.append(xr)

    resolutions.sort()

    # AdfOptions: prüfen ob DetectPaperLoaded unterstützt
    adf_el = root.find("scan:Adf", _NS)
    detect_paper_loaded = False
    if adf_el is not None:
        for opt in adf_el.findall(".//scan:AdfOption", _NS):
            if opt.text == "DetectPaperLoaded":
                detect_paper_loaded = True
                break

        # Hardware-Duplex: AdfDuplexInputCaps ODER AdfOption=Duplex
        has_duplex_caps = adf_el.find("scan:AdfDuplexInputCaps", _NS) is not None
        has_duplex_option = any(
            opt.text == "Duplex"
            for opt in adf_el.findall(".//scan:AdfOption", _NS)
        )
        if has_duplex_caps or has_duplex_option:
            sources.append("AdfDuplex")
            log.info("Hardware-Duplex-Capability erkannt für Scanner '%s'", full_name)

    return ScannerInfo(
        name=full_name,
        host=host,
        port=port,
        escl_url=escl_url,
        make_model=make_model,
        max_width=max_width or 2550,
        max_height=max_height or 3508,
        color_modes=color_modes or ["RGB24"],
        resolutions=resolutions or [300],
        document_sources=sources or ["Platen"],
        linked_printer=linked_printer,
        detect_paper_loaded=detect_paper_loaded,
    )


def _text(el: ET.Element, path: str) -> str:
    found = el.find(path, _NS)
    return found.text.strip() if found is not None and found.text else ""


def _int(el: ET.Element, path: str) -> int:
    t = _text(el, path)
    try:
        return int(t)
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _avahi_scanner_urls() -> list[str]:
    """Sucht via Avahi nach _uscan._tcp / _uscans._tcp."""
    import subprocess
    urls: list[str] = []
    for svc in ("_uscan._tcp", "_uscans._tcp"):
        try:
            proc = subprocess.run(
                ["avahi-browse", "-r", "-t", "-p", svc],
                capture_output=True, text=True, timeout=AVAHI_TIMEOUT + 1,
            )
            for line in proc.stdout.splitlines():
                if not line.startswith("="):
                    continue
                parts = line.split(";", 9)
                if len(parts) < 9 or parts[2] != "IPv4":
                    continue
                addr, port_str = parts[7], parts[8]
                port = int(port_str) if port_str.isdigit() else 80
                scheme = "https" if svc == "_uscans._tcp" else "http"
                urls.append(f"{scheme}://{addr}:{port}{_ESCL_PATH}")
        except Exception:
            pass
    return urls


def _host_from_url(url: str) -> str:
    return urllib.parse.urlparse(url).hostname or url


def _default_output_path() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        from gi.repository import GLib
        pictures = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
        base = Path(pictures) if pictures else Path.home()
    except Exception:
        base = Path.home()
    scan_dir = base / "Scans"
    scan_dir.mkdir(parents=True, exist_ok=True)
    return str(scan_dir / f"scan_{ts}.jpg")


def _default_duplex_output_path() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        from gi.repository import GLib
        pictures = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
        base = Path(pictures) if pictures else Path.home()
    except Exception:
        base = Path.home()
    scan_dir = base / "Scans"
    scan_dir.mkdir(parents=True, exist_ok=True)
    return str(scan_dir / f"scan_duplex_{ts}.pdf")


def _create_pdf(jpeg_pages: list[bytes], output_path: str) -> None:
    """Erzeugt eine mehrseitige PDF aus JPEG-Bytes (benötigt Pillow)."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            _("Pillow (python-pillow) nicht installiert — bitte installieren: sudo pacman -S python-pillow")
        ) from exc

    if not jpeg_pages:
        raise ValueError("Keine Seiten für PDF-Erstellung")

    images = [Image.open(io.BytesIO(data)).convert("RGB") for data in jpeg_pages]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    images[0].save(
        output_path,
        format="PDF",
        save_all=True,
        append_images=images[1:],
        resolution=200.0,
    )
