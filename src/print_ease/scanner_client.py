"""
Scanner-Erkennung und Scan-Funktion via eSCL (AirScan / Mopria Scan).

Kaskade je Drucker (find_scanner_for_printer):
  a) eSCL-URL aus der CUPS-Geräte-URI
  b) mDNS-Suche nach _uscan._tcp / _uscans._tcp (Avahi, sonst python-zeroconf)
  c) HTTP-Probe aller bekannten Netzwerkdrucker-IPs

Die gesamte Kaskade ist durch SCANNER_SEARCH_TIMEOUT begrenzt.
"""
from __future__ import annotations

import http.client
import io
import ipaddress
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator, TypeVar

from print_ease import avahi_client, cups_client
from print_ease._i18n import _
from print_ease._log import get_logger
from print_ease.constants import (
    AVAHI_TIMEOUT,
    CUPS_TIMEOUT,
    ESCL_TIMEOUT,
    NEXT_DOCUMENT_TIMEOUT,
    SCANNER_MDNS_WINDOW,
    SCANNER_SEARCH_TIMEOUT,
)
from print_ease.printer_model import NetworkPrinter, PrinterInfo, ScannerInfo

log = get_logger(__name__)

T = TypeVar("T")

_NS_SCAN = "http://schemas.hp.com/imaging/escl/2011/05/03"
_NS_PWG  = "http://www.pwg.org/schemas/2010/12/sm"
_NS = {"scan": _NS_SCAN, "pwg": _NS_PWG}

_ESCL_PATH = "/eSCL"

# URI-Schemata, deren Host-Teil tatsächlich das Gerät im Netz benennt.
# usb://Canon/TS700 hat zwar auch einen "Host", der ist aber der Hersteller.
_HOST_URI_SCHEMES = ("ipp", "ipps", "http", "https", "socket", "lpd")

# NextDocument liefert zwischen zwei ADF-Seiten kurzzeitig 404, während das
# nächste Blatt eingezogen wird. 404 allein beendet den Job deshalb nicht.
_ADF_RETRY_DELAY = 1     # Sekunden zwischen zwei Versuchen
_ADF_EMPTY_RETRIES = 3   # Versuche ohne Papier: letzte Seite kann noch unterwegs sein
_ADF_MAX_MISSES = 30     # 404 in Folge ohne neue Seite, unabhängig von der Stapelgröße

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


def get_scanner_capabilities(
    escl_url: str,
    linked_printer: str | None = None,
    timeout: float = ESCL_TIMEOUT,
) -> ScannerInfo | None:
    """
    Ruft ScannerCapabilities ab und parst die XML-Antwort.
    Gibt None zurück wenn das Gerät kein eSCL unterstützt.
    """
    caps_url = f"{escl_url}/ScannerCapabilities"
    try:
        req = urllib.request.Request(caps_url, headers={"Accept": "application/xml"})
        with urllib.request.urlopen(req, timeout=timeout, context=_ESCL_SSL_CONTEXT) as resp:
            if resp.status != 200:
                return None
            data = resp.read()
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as exc:
        log.warning("Kein eSCL bei %s: %s", caps_url, exc)
        return None

    try:
        return _parse_capabilities(data, escl_url, linked_printer)
    except ET.ParseError as exc:
        log.warning("eSCL XML-Parse-Fehler bei %s: %s", escl_url, exc)
        return None


def discover_scanners(linked_printers: dict[str, str] | None = None) -> list[ScannerInfo]:
    """
    Findet eSCL-Scanner im Netzwerk, jedes Gerät genau einmal.

    Strategie je Gerät, erster Treffer gewinnt:
    1. Avahi nach _uscan._tcp / _uscans._tcp
    2. Bekannte Netzwerkdrucker-IPs proben (http, dann https)

    linked_printers: {ip_adresse: cups_druckername} — aus linked_printers_by_ip()
    """
    return _probe_hosts(_avahi_scanner_urls(), linked_printers or {}, ESCL_TIMEOUT)


def linked_printers_by_ip(prefer: str | None = None) -> dict[str, str]:
    """
    Liefert {ip_adresse: cups_druckername} für alle CUPS-Drucker, deren
    IP sich aus der Geräte-URI oder der Avahi-Suche herleiten lässt.

    Zeigen mehrere Queues auf dasselbe Gerät, gewinnt die Queue `prefer`.
    """
    network = avahi_client.discover_network_printers(timeout=SCANNER_MDNS_WINDOW)
    linked: dict[str, str] = {}
    for printer in sorted(cups_client.get_printers(), key=lambda p: p.name == prefer):
        for ip in _printer_ips(printer, network):
            linked[ip] = printer.name
    return linked


def find_scanner_for_printer(printer: PrinterInfo) -> ScannerInfo | None:
    """
    Sucht den Scanner, der zu genau diesem Drucker gehört.

    Scanner anderer Geräte werden nie zurückgegeben: Ohne bekannte IP
    (USB, Datei, ...) gibt es keine Zuordnung und damit keinen Treffer.
    """
    deadline = time.monotonic() + SCANNER_SEARCH_TIMEOUT

    # Avahi läuft schon während Schritt a, damit die Frist auch für b und c
    # reicht. Das Ergebnis zählt trotzdem erst, wenn Schritt a gescheitert ist.
    pool = ThreadPoolExecutor(max_workers=2)
    linked_job = pool.submit(linked_printers_by_ip, printer.name)
    avahi_job = pool.submit(_avahi_scanner_urls)
    pool.shutdown(wait=False)

    scanner = _probe_printer_uri(printer, deadline)
    if scanner:
        return scanner

    try:
        linked = linked_job.result(timeout=max(deadline - time.monotonic(), 0))
        avahi_urls = avahi_job.result(timeout=max(deadline - time.monotonic(), 0))
    except TimeoutError:
        log.warning("Avahi-Suche für '%s' nicht rechtzeitig fertig", printer.name)
        return None

    if printer.name not in linked.values():
        log.info("Keine IP für '%s' bekannt — kein Scanner zuordenbar", printer.name)
        return None

    remaining = deadline - time.monotonic()
    if remaining > 0:
        for scanner in _probe_hosts(avahi_urls, linked, min(remaining, ESCL_TIMEOUT)):
            if scanner.linked_printer == printer.name:
                return scanner

    log.info("Kein Scanner für '%s' gefunden", printer.name)
    return None


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
    image_data = _scan_single_page(scanner, color_mode, resolution, source, cancel_event)

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
        for data in _adf_documents(
            scanner.escl_url,
            lambda: _fetch_next_document(job_url, cancel_event=cancel_event),
            cancel_event,
        ):
            pages.append(data)
            log.debug("ADF-Seite %d gescannt (%d Bytes)", len(pages), len(data))
    finally:
        _delete_job(job_url)

    log.info("ADF-Scan abgeschlossen: %d Seiten", len(pages))
    return pages


def scan_adf_document(
    scanner: ScannerInfo,
    color_mode: str = "RGB24",
    resolution: int = 300,
    mode: str = "single",
    cancel_event=None,
) -> str:
    """
    Scannt den ganzen Einzug und speichert ihn im Format von `mode`
    (siehe _save_pages). Gibt den Pfad zum Ergebnis zurück.
    """
    pages = scan_adf_all_pages(scanner, color_mode, resolution, cancel_event)
    if not pages:
        raise RuntimeError(_("Keine Seiten im ADF-Einzug gescannt"))
    return _save_pages(pages, mode, resolution=resolution)


def scan_duplex_software(
    scanner: ScannerInfo,
    color_mode: str = "RGB24",
    resolution: int = 300,
    cancel_event=None,
    flip_callback: Callable[[], None] | None = None,
    progress_callback: Callable[[str], None] | None = None,
    mode: str = "multipage",
    rotate_back: bool = False,
) -> str:
    """
    Software-Duplex in zwei ADF-Durchgängen.

    flip_callback() wird zwischen den Durchgängen aufgerufen und blockiert,
    bis der Benutzer den Stapel umgedreht und bestätigt hat (oder abbricht).
    progress_callback(stage) meldet Fortschritt: "front", "back", "pdf".
    rotate_back dreht die Rückseiten um 180°. Nötig nur, wenn der Stapel so
    gewendet wird, dass er Kopf über Fuß im Einzug liegt; beim Wenden laut
    Dialog (als Ganzes umdrehen, wieder in Einzugsrichtung) kommen sie aufrecht.
    Gibt den Pfad zum Ergebnis im Format von `mode` zurück (siehe _save_pages).
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
        # Ohne Papier scannt der Ricoh still das Vorlagenglas, statt zu melden.
        while (
            not (cancel_event and cancel_event.is_set())
            and get_adf_state(scanner.escl_url) == "ScannerAdfEmpty"
        ):
            log.warning("Einzug nach dem Umdrehen leer, frage erneut")
            flip_callback()

    if cancel_event and cancel_event.is_set():
        raise InterruptedError("Scan abgebrochen")

    if progress_callback:
        progress_callback("back")

    back_pages = scan_adf_all_pages(scanner, color_mode, resolution, cancel_event)
    # Rückseiten kommen umgekehrt aus dem Einzug → Reihenfolge umkehren.
    back_pages = list(reversed(back_pages))
    if rotate_back:
        back_pages = [_rotate_jpeg_180(page) for page in back_pages]

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

    output_path = _save_pages(
        all_pages, mode, pdf_path=_default_duplex_output_path, resolution=resolution
    )
    log.info("Duplex-Scan gespeichert: %s (%d Seiten)", output_path, len(all_pages))
    return output_path


def scan_adf_hardware_duplex(
    scanner: ScannerInfo,
    color_mode: str = "RGB24",
    resolution: int = 300,
    cancel_event=None,
    progress_callback: Callable[[int], None] | None = None,
    mode: str = "multipage",
) -> str:
    """Hardware-Duplex-Scan via eSCL.

    BETA — nach eSCL-Spec implementiert, aber mangels Hardware-Duplex-
    fähigem Test-Gerät nicht getestet. Feedback erwünscht.

    Sendet einen einzigen eSCL-Job mit InputSource=AdfDuplex. Sammelt
    alle gelieferten Seiten, sortiert nach SheetNumber + Side wenn
    vorhanden, sonst nach Stream-Reihenfolge (Annahme: Front/Back/...).
    Gibt den Pfad zum Ergebnis im Format von `mode` zurück (siehe _save_pages).
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
    try:
        for page in _adf_documents(
            scanner.escl_url,
            lambda: _fetch_next_duplex_page(job_url, cancel_event),
            cancel_event,
        ):
            pages.append(page)
            log.info(
                "Seite empfangen: page=%d, sheet=%s, side=%s, size=%d bytes",
                len(pages), page[1], page[2], len(page[0]),
            )
            if progress_callback:
                progress_callback(len(pages))
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
    output_path = _save_pages(
        jpeg_pages, mode, pdf_path=_default_duplex_output_path, resolution=resolution
    )
    log.info("Hardware-Duplex-Scan gespeichert: %s (%d Seiten)", output_path, len(pages))
    return output_path


def scan_platen_multipage(
    scanner: ScannerInfo,
    color_mode: str = "RGB24",
    resolution: int = 300,
    next_page_callback: Callable[[int], str] | None = None,
    progress_callback: Callable[[int], None] | None = None,
    cancel_event=None,
) -> str:
    """Multi-Page-Scan vom Flachbett. Beliebige Anzahl Seiten.

    Scannt einzelne Seiten vom Flachbett, fragt den User nach jeder
    Seite via next_page_callback. Baut am Ende ein PDF.

    next_page_callback(page_num) muss einen der folgenden Strings
    zurückgeben:
        "continue" — weitere Seite scannen
        "finish"   — PDF jetzt erstellen und beenden
        "cancel"   — Abbrechen (raises InterruptedError)

    progress_callback(page_num) wird vor jedem Scan aufgerufen.

    Raises:
        RuntimeError: Wenn next_page_callback fehlt oder 0 Seiten.
        InterruptedError: Bei Abbruch durch User oder cancel_event.
        ValueError: Bei ungültigem next_page_callback-Return.
    """
    if next_page_callback is None:
        raise RuntimeError("next_page_callback ist erforderlich")

    log.info(
        "Multi-Page-Flachbett-Scan starten: %s, %s, %d dpi",
        scanner.name, color_mode, resolution,
    )

    page_num = 1
    jpeg_pages: list[bytes] = []

    while True:
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Vom Benutzer abgebrochen")

        if progress_callback:
            progress_callback(page_num)

        log.info("Seite %d wird gescannt...", page_num)
        jpeg = _scan_single_page(scanner, color_mode, resolution, "Platen", cancel_event)
        jpeg_pages.append(jpeg)
        log.info("Seite %d gescannt: %d bytes", page_num, len(jpeg))

        answer = next_page_callback(page_num)

        if answer == "continue":
            page_num += 1
            continue
        elif answer == "finish":
            break
        elif answer == "cancel":
            raise InterruptedError("Vom Benutzer abgebrochen")
        else:
            raise ValueError(f"Unerwarteter next_page_callback-Return: {answer!r}")

    if not jpeg_pages:
        raise RuntimeError(_("Keine Seiten gescannt"))

    output_path = _default_platen_multipage_output_path()
    _create_pdf(jpeg_pages, output_path, resolution=resolution)
    log.info("Multi-Page-PDF erstellt: %s (%d Seiten)", output_path, len(jpeg_pages))
    return output_path


def scan_platen_archive(
    scanner: ScannerInfo,
    color_mode: str = "RGB24",
    resolution: int = 300,
    next_page_callback: Callable[[int], str] | None = None,
    progress_callback: Callable[[int], None] | None = None,
    cancel_event=None,
) -> str:
    """Archiv-Scan vom Flachbett als Multi-Page-TIFF. Beliebige Anzahl Seiten.

    Scannt einzelne Seiten vom Flachbett, fragt den User nach jeder
    Seite via next_page_callback. Baut am Ende ein TIFF (LZW-komprimiert).

    next_page_callback(page_num) muss einen der folgenden Strings
    zurückgeben:
        "continue" — weitere Seite scannen
        "finish"   — TIFF jetzt erstellen und beenden
        "cancel"   — Abbrechen (raises InterruptedError)

    progress_callback(page_num) wird vor jedem Scan aufgerufen.

    Raises:
        RuntimeError: Wenn next_page_callback fehlt oder 0 Seiten.
        InterruptedError: Bei Abbruch durch User oder cancel_event.
        ValueError: Bei ungültigem next_page_callback-Return.
    """
    if next_page_callback is None:
        raise RuntimeError("next_page_callback ist erforderlich")

    log.info(
        "Archiv-Flachbett-Scan starten: %s, %s, %d dpi",
        scanner.name, color_mode, resolution,
    )

    page_num = 1
    jpeg_pages: list[bytes] = []

    while True:
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Vom Benutzer abgebrochen")

        if progress_callback:
            progress_callback(page_num)

        log.info("Seite %d wird gescannt...", page_num)
        jpeg = _scan_single_page(scanner, color_mode, resolution, "Platen", cancel_event)
        jpeg_pages.append(jpeg)
        log.info("Seite %d gescannt: %d bytes", page_num, len(jpeg))

        answer = next_page_callback(page_num)

        if answer == "continue":
            page_num += 1
            continue
        elif answer == "finish":
            break
        elif answer == "cancel":
            raise InterruptedError("Vom Benutzer abgebrochen")
        else:
            raise ValueError(f"Unerwarteter next_page_callback-Return: {answer!r}")

    if not jpeg_pages:
        raise RuntimeError(_("Keine Seiten gescannt"))

    output_path = _default_platen_archive_output_path()
    _create_tiff(jpeg_pages, output_path)
    log.info("Archiv-TIFF erstellt: %s (%d Seiten)", output_path, len(jpeg_pages))
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
            with urllib.request.urlopen(
                doc_url, timeout=NEXT_DOCUMENT_TIMEOUT, context=_ESCL_SSL_CONTEXT
            ) as resp:
                if resp.status == 200:
                    return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 503:
                log.debug("Scanner verarbeitet noch (Versuch %d)...", attempt + 1)
                time.sleep(1)
                continue
            raise
    raise TimeoutError("Scanner hat nicht innerhalb der erwarteten Zeit geantwortet")


def _fetch_next_duplex_page(
    job_url: str, cancel_event=None
) -> tuple[bytes, int | None, str | None]:
    """Wie _fetch_next_document, liefert zusätzlich Blattnummer und Seite."""
    doc_url = f"{job_url}/NextDocument"
    for attempt in range(30):
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Scan abgebrochen")
        try:
            with urllib.request.urlopen(
                urllib.request.Request(doc_url),
                timeout=NEXT_DOCUMENT_TIMEOUT,
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
                return data, sheet, side
        except urllib.error.HTTPError as exc:
            if exc.code == 503:
                log.debug("Scanner verarbeitet noch (Versuch %d)...", attempt + 1)
                time.sleep(1)
                continue
            raise
    raise TimeoutError("Scanner hat nicht innerhalb der erwarteten Zeit geantwortet")


def _adf_documents(escl_url: str, fetch: Callable[[], T], cancel_event=None) -> Iterator[T]:
    """
    Liefert die Ergebnisse von fetch(), bis der ADF-Job wirklich zu Ende ist.

    404 heißt nur "gerade keine Seite": Bei Papier im Einzug wird weiter
    gewartet, sonst noch _ADF_EMPTY_RETRIES-mal, weil AdfState schon leer
    meldet, während die letzte Seite noch übertragen wird. 410 beendet sofort.
    """
    misses = 0
    empty_misses = 0
    while True:
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Scan abgebrochen")
        try:
            document = fetch()
        except urllib.error.HTTPError as exc:
            if exc.code == 410:
                return
            if exc.code != 404:
                raise

            misses += 1
            if misses > _ADF_MAX_MISSES:
                # Kein stilles Ende: Die Seitenzahl wäre falsch, und beim
                # Software-Duplex gerieten Vorder- und Rückseiten durcheinander.
                raise TimeoutError(
                    "Scanner liefert trotz Papier im Einzug keine weiteren Seiten"
                ) from exc

            adf_state = get_adf_state(escl_url)
            log.debug("NextDocument 404 (Versuch %d), AdfState=%s", misses, adf_state)
            if adf_state != "ScannerAdfLoaded":
                empty_misses += 1
                if empty_misses > _ADF_EMPTY_RETRIES:
                    if adf_state not in ("ScannerAdfEmpty", None):
                        log.warning("ADF-Scan beendet mit AdfState=%s", adf_state)
                    return
            time.sleep(_ADF_RETRY_DELAY)
            continue

        misses = empty_misses = 0
        yield document


def _delete_job(job_url: str) -> None:
    try:
        req = urllib.request.Request(job_url, method="DELETE")
        urllib.request.urlopen(req, timeout=5, context=_ESCL_SSL_CONTEXT)
    except Exception as exc:
        log.debug("Scan-Job konnte nicht gelöscht werden: %s", exc)


def _scan_single_page(
    scanner: ScannerInfo,
    color_mode: str,
    resolution: int,
    source: str,
    cancel_event=None,
) -> bytes:
    """Führt einen eSCL-Scan-Job aus und liefert JPEG-Bytes.

    Reine Helper-Funktion: keine Datei-Ausgabe, keine PDF-Erstellung.
    Geeignet als Baustein für Multi-Page-Flows.
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

    return image_data


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

def _probe_printer_uri(printer: PrinterInfo, deadline: float) -> ScannerInfo | None:
    """Schritt a der Kaskade: eSCL unter der Adresse aus der CUPS-URI."""
    escl_url = _escl_url_for(printer)
    if not escl_url:
        return None

    # .local-Namen vorab auflösen: Die libc-Auflösung blockiert bei
    # ausgeschalteten Geräten bis zu 15 s, und kein Timeout greift dort.
    host = _host_from_url(escl_url)
    if host.rstrip(".").endswith(".local"):
        ip = avahi_client.resolve_host(host.rstrip("."))
        if not ip:
            log.info("%s nicht auflösbar", host)
            return None
        escl_url = escl_url.replace(host, ip, 1)

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    return get_scanner_capabilities(
        escl_url, linked_printer=printer.name, timeout=min(remaining, ESCL_TIMEOUT)
    )


def _probe_hosts(
    avahi_urls: list[str], linked: dict[str, str], timeout: float
) -> list[ScannerInfo]:
    """Probt alle Kandidaten gleichzeitig und liefert jedes Gerät einmal."""
    # Ein Gerät meldet sich meist unter mehreren URLs (_uscan, _uscans, IP-Probe).
    candidates: dict[str, list[str]] = {}
    for url in avahi_urls:
        candidates.setdefault(_host_from_url(url), []).append(url)
    for ip in linked:
        candidates.setdefault(ip, []).extend(
            (f"http://{ip}{_ESCL_PATH}", f"https://{ip}{_ESCL_PATH}")
        )

    jobs = [(host, url) for host, urls in candidates.items() for url in dict.fromkeys(urls)]
    if not jobs:
        return []

    def probe(job: tuple[str, str]) -> ScannerInfo | None:
        host, url = job
        return get_scanner_capabilities(url, linked_printer=linked.get(host), timeout=timeout)

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        results = list(pool.map(probe, jobs))

    # Je Gerät gewinnt der erste Treffer in Kandidaten-Reihenfolge: Avahi vor IP-Probe.
    scanners: dict[str, ScannerInfo] = {}
    for (host, _url), scanner in zip(jobs, results):
        if scanner and host not in scanners:
            scanners[host] = scanner
            log.info("Scanner gefunden: %s @ %s", scanner.name, scanner.escl_url)
    return list(scanners.values())


def _escl_url_for(printer: PrinterInfo) -> str | None:
    try:
        parsed = urllib.parse.urlparse(printer.uri)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme not in ("ipp", "ipps", "http", "https"):
        return None
    host = parsed.hostname
    if not host:
        return None
    scheme = "https" if parsed.scheme == "ipps" else "http"
    # Port nur einfügen wenn nicht Standard (80/443) und nicht IPP-Standard (631)
    if port and port not in (80, 443, 631):
        return f"{scheme}://{host}:{port}/eSCL"
    return f"{scheme}://{host}/eSCL"


def _printer_ips(printer: PrinterInfo, network: list[NetworkPrinter]) -> set[str]:
    """Leitet die IPv4-Adressen eines CUPS-Druckers her."""
    try:
        parsed = urllib.parse.urlparse(printer.uri)
        host = (parsed.hostname or "").rstrip(".").lower()
    except ValueError:
        return set()

    if parsed.scheme in _HOST_URI_SCHEMES:
        if _is_ipv4(host):
            return {host}
        return {n.address for n in network if host and n.host.rstrip(".").lower() == host}

    # dnssd://Name._ipp._tcp.local/?uuid=... und implicitclass://Queue_Name/
    # nennen keinen Host, sondern nur den Dienst- bzw. Queue-Namen.
    if parsed.scheme not in ("dnssd", "implicitclass"):
        return set()

    name = urllib.parse.unquote(parsed.netloc)
    name = _normalize_name(re.sub(r"\._[a-z0-9-]+\._tcp\b.*$", "", name, flags=re.IGNORECASE))
    uuid = urllib.parse.parse_qs(parsed.query).get("uuid", [""])[0].lower()

    # Vom eindeutigsten zum unschärfsten Merkmal. Passt ein Merkmal auf
    # mehrere Geräte (zwei gleiche Modelle), lieber keine Zuordnung als die falsche.
    for matches in (
        lambda n: uuid and n.txt_records.get("UUID", "").lower() == uuid,
        lambda n: name and _normalize_name(n.instance_name) == name,
        lambda n: name and _normalize_name(n.name) == name,
    ):
        addresses = {n.address for n in network if matches(n)}
        if addresses:
            return addresses if len(addresses) == 1 else set()
    return set()


def _is_ipv4(host: str) -> bool:
    try:
        ipaddress.IPv4Address(host)
    except ValueError:
        return False
    return True


def _normalize_name(name: str) -> str:
    """'Canon_TS700_series' und 'Canon TS700 series' sollen gleich sein."""
    return re.sub(r"[\W_]+", "", name).casefold()


def _avahi_scanner_urls() -> list[str]:
    """
    Sucht nach _uscan._tcp / _uscans._tcp — via Avahi, ohne Avahi (Flatpak)
    über den zeroconf-Fallback in avahi_client._browse.

    Beide Typen laufen parallel, damit die Suche auch auf dem zeroconf-Weg
    (festes Suchfenster je Aufruf) nur einmal SCANNER_MDNS_WINDOW dauert.
    """
    services = (("_uscan._tcp", "http", 80), ("_uscans._tcp", "https", 443))
    with ThreadPoolExecutor(max_workers=len(services)) as pool:
        browsed = list(pool.map(lambda svc: avahi_client._browse(svc[0], SCANNER_MDNS_WINDOW), services))

    urls: list[str] = []
    for (_svc, scheme, default_port), lines in zip(services, browsed):
        for line in lines:
            if not line.startswith("="):
                continue
            parts = line.split(";", 9)
            if len(parts) < 9 or parts[2] != "IPv4":
                continue
            addr, port_str = parts[7], parts[8]
            port = int(port_str) if port_str.isdigit() else default_port
            netloc = addr if port == default_port else f"{addr}:{port}"
            txt = avahi_client._parse_txt(parts[9]) if len(parts) > 9 else {}
            path = (txt.get("rs") or "eSCL").strip("/")
            urls.append(f"{scheme}://{netloc}/{path}")
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


def _default_platen_multipage_output_path() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        from gi.repository import GLib
        pictures = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
        base = Path(pictures) if pictures else Path.home()
    except Exception:
        base = Path.home()
    scan_dir = base / "Scans"
    scan_dir.mkdir(parents=True, exist_ok=True)
    return str(scan_dir / f"scan_multipage_{ts}.pdf")


def _default_platen_archive_output_path() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        from gi.repository import GLib
        pictures = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
        base = Path(pictures) if pictures else Path.home()
    except Exception:
        base = Path.home()
    scan_dir = base / "Scans"
    scan_dir.mkdir(parents=True, exist_ok=True)
    return str(scan_dir / f"scan_archive_{ts}.tif")


def _save_pages(
    jpeg_pages: list[bytes],
    mode: str,
    pdf_path: Callable[[], str] | None = None,
    resolution: int | None = None,
) -> str:
    """
    Speichert Seiten im Format des Modus und gibt den Pfad zurück
    (resolution = Scan-Auflösung in dpi, bestimmt die PDF-Seitengröße):
      "single"    — JPEG je Seite
      "multipage" — ein PDF
      "archive"   — ein Multi-Page-TIFF
    """
    if mode == "single":
        return _save_jpegs(jpeg_pages)
    if mode == "multipage":
        output_path = (pdf_path or _default_platen_multipage_output_path)()
        _create_pdf(jpeg_pages, output_path, resolution=resolution)
        return output_path
    if mode == "archive":
        output_path = _default_platen_archive_output_path()
        _create_tiff(jpeg_pages, output_path)
        return output_path
    raise ValueError(f"Unbekannter Scan-Modus: {mode!r}")


def _save_jpegs(jpeg_pages: list[bytes]) -> str:
    """Eine Seite wird eine Datei, mehrere landen gemeinsam in einem Ordner."""
    output_path = Path(_default_output_path())
    if len(jpeg_pages) == 1:
        output_path.write_bytes(jpeg_pages[0])
        return str(output_path)

    folder = output_path.with_suffix("")
    folder.mkdir()
    for number, page in enumerate(jpeg_pages, 1):
        (folder / f"{number:03d}.jpg").write_bytes(page)
    return str(folder)


def _create_pdf(
    jpeg_pages: list[bytes], output_path: str, resolution: float | None = None
) -> None:
    """
    Erzeugt eine mehrseitige PDF aus JPEG-Bytes (benötigt Pillow).

    resolution: Scan-Auflösung in dpi. Sie legt die Seitengröße fest
    (2550 px bei 300 dpi = 8,5 Zoll). Ohne Angabe gilt die dpi-Angabe des
    ersten JPEGs, sonst 200.
    """
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            _("Pillow (python-pillow) nicht installiert — bitte installieren: sudo pacman -S python-pillow")
        ) from exc

    if not jpeg_pages:
        raise ValueError("Keine Seiten für PDF-Erstellung")

    opened = [Image.open(io.BytesIO(data)) for data in jpeg_pages]
    if not resolution:
        resolution = _jpeg_dpi(opened[0]) or 200.0
    images = [im.convert("RGB") for im in opened]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    images[0].save(
        output_path,
        format="PDF",
        save_all=True,
        append_images=images[1:],
        resolution=float(resolution),
    )


def _jpeg_dpi(image) -> float | None:
    """dpi aus dem JFIF/EXIF-Kopf, None wenn nicht (sinnvoll) angegeben."""
    dpi = image.info.get("dpi")
    try:
        value = float(dpi[0]) if dpi else 0.0
    except (TypeError, ValueError, IndexError):
        return None
    return value if value > 1 else None


def _rotate_jpeg_180(data: bytes) -> bytes:
    """
    Dreht eine JPEG-Seite um 180° (neu kodiert, Qualität 95, dpi und
    Farbprofil bleiben). Ohne Pillow oder bei nicht lesbaren Daten bleibt
    die Seite unverändert, statt den ganzen Duplex-Scan abzubrechen.
    """
    try:
        from PIL import Image
    except ImportError:
        log.warning("Pillow fehlt — Rückseite wird nicht gedreht")
        return data
    try:
        with Image.open(io.BytesIO(data)) as im:
            rotated = im.transpose(Image.Transpose.ROTATE_180)
            extra = {k: im.info[k] for k in ("dpi", "icc_profile") if im.info.get(k)}
            out = io.BytesIO()
            rotated.save(out, format="JPEG", quality=95, **extra)
    except OSError as exc:  # inkl. UnidentifiedImageError
        log.warning("Rückseite nicht drehbar, bleibt unverändert: %s", exc)
        return data
    return out.getvalue()


def _create_tiff(jpeg_pages: list[bytes], output_path: str) -> None:
    """Erstellt eine TIFF-Multi-Page-Datei aus JPEG-Bytes.

    Verwendet Pillow's nativen TIFF-Support mit LZW-Kompression.
    """
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            _("Pillow (python-pillow) nicht installiert — bitte installieren: sudo pacman -S python-pillow")
        ) from exc

    if not jpeg_pages:
        raise RuntimeError("Keine Seiten für TIFF-Erstellung")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    images = [Image.open(io.BytesIO(jpeg)) for jpeg in jpeg_pages]
    images[0].save(
        output_path,
        format="TIFF",
        save_all=True,
        append_images=images[1:],
        compression="tiff_lzw",
    )
