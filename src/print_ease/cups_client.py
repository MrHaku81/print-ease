from __future__ import annotations

import cups
from contextlib import contextmanager

from print_ease._log import get_logger
from print_ease.printer_model import PrinterInfo, PrintJob

log = get_logger(__name__)

_CUPS_STATE_MAP = {
    3: "idle",
    4: "processing",
    5: "stopped",
}


def _connect() -> cups.Connection:
    try:
        conn = cups.Connection()
        log.debug("CUPS-Verbindung aufgebaut (localhost:631)")
        return conn
    except RuntimeError as exc:
        log.error("CUPS nicht erreichbar: %s", exc)
        raise ConnectionError("CUPS-Daemon nicht erreichbar") from exc


@contextmanager
def _cups_session():
    """Context manager für CUPS-Verbindungen.

    Heute ein dünner Wrapper um _connect(). Mit libcups3 könnte hier
    später explizites Cleanup nötig werden — dann reicht eine Änderung
    an dieser einen Stelle.
    """
    conn = _connect()
    try:
        yield conn
    finally:
        pass


def get_printers() -> list[PrinterInfo]:
    with _cups_session() as conn:
        try:
            raw = conn.getPrinters()
        except cups.IPPError as exc:
            log.error("IPP-Fehler beim Abrufen der Drucker: %s", exc)
            raise

        default_name = conn.getDefault()
        printers: list[PrinterInfo] = []

        for name, attrs in raw.items():
            state_code = attrs.get("printer-state", 3)
            printers.append(PrinterInfo(
                name=name,
                description=attrs.get("printer-info", ""),
                location=attrs.get("printer-location", ""),
                is_default=(name == default_name),
                is_shared=attrs.get("printer-is-shared", False),
                state=_CUPS_STATE_MAP.get(state_code, "unknown"),
                state_message=attrs.get("printer-state-message", ""),
                uri=attrs.get("device-uri", ""),
            ))

        log.info("%d Drucker gefunden", len(printers))
        return printers


def set_default_printer(printer_name: str) -> None:
    with _cups_session() as conn:
        try:
            conn.setDefault(printer_name)
            log.info("Standarddrucker gesetzt: '%s'", printer_name)
        except cups.IPPError as exc:
            log.error("Fehler beim Setzen des Standarddruckers '%s': %s", printer_name, exc)
            raise


def pause_printer(printer_name: str) -> None:
    """
    Pausiert den Drucker (disablePrinter + rejectJobs).

    HINWEIS: CUPS bietet keine atomare Pause-Operation. Schlägt rejectJobs
    nach disablePrinter fehl, ist der Drucker deaktiviert aber akzeptiert
    noch Jobs — der inkonsistente Zustand wird als Warnung geloggt.
    """
    with _cups_session() as conn:
        try:
            conn.disablePrinter(printer_name)
            log.info("Drucker deaktiviert: '%s'", printer_name)
        except cups.IPPError as exc:
            log.error("Fehler beim Deaktivieren von '%s': %s", printer_name, exc)
            raise
        try:
            conn.rejectJobs(printer_name)
            log.info("Drucker akzeptiert keine Jobs mehr: '%s'", printer_name)
        except cups.IPPError as exc:
            log.warning(
                "Drucker '%s' deaktiviert, aber rejectJobs fehlgeschlagen: %s "
                "— inkonsistenter Zustand!", printer_name, exc,
            )
            raise


def resume_printer(printer_name: str) -> None:
    """
    Setzt den Drucker fort (enablePrinter + acceptJobs).

    HINWEIS: CUPS bietet keine atomare Resume-Operation. Schlägt acceptJobs
    nach enablePrinter fehl, ist der Drucker aktiv aber lehnt Jobs ab —
    der inkonsistente Zustand wird als Warnung geloggt.
    """
    with _cups_session() as conn:
        try:
            conn.enablePrinter(printer_name)
            log.info("Drucker aktiviert: '%s'", printer_name)
        except cups.IPPError as exc:
            log.error("Fehler beim Aktivieren von '%s': %s", printer_name, exc)
            raise
        try:
            conn.acceptJobs(printer_name)
            log.info("Drucker akzeptiert wieder Jobs: '%s'", printer_name)
        except cups.IPPError as exc:
            log.warning(
                "Drucker '%s' aktiviert, aber acceptJobs fehlgeschlagen: %s "
                "— inkonsistenter Zustand!", printer_name, exc,
            )
            raise


def print_test_page(printer_name: str) -> None:
    with _cups_session() as conn:
        try:
            job_id = conn.printTestPage(printer_name)
            log.info("Testseite gesendet an '%s', Job-ID: %d", printer_name, job_id)
        except cups.IPPError as exc:
            log.error("Fehler beim Drucken der Testseite auf '%s': %s", printer_name, exc)
            raise


def get_jobs(printer_name: str) -> list[PrintJob]:
    with _cups_session() as conn:
        try:
            raw = conn.getJobs(which_jobs="not-completed", my_jobs=False)
        except cups.IPPError as exc:
            log.error("Fehler beim Abrufen der Jobs für '%s': %s", printer_name, exc)
            raise

        jobs: list[PrintJob] = []
        for job_id, attrs in raw.items():
            # job-printer-uri hat die Form ipp://localhost:631/printers/<name>
            if attrs.get("job-printer-uri", "").endswith("/" + printer_name):
                jobs.append(PrintJob(
                    job_id=job_id,
                    printer_name=printer_name,
                    title=attrs.get("job-name", f"Job {job_id}"),
                    state=str(attrs.get("job-state", "")),
                    user=attrs.get("job-originating-user-name", ""),
                ))

        log.debug("%d aktive Jobs für '%s'", len(jobs), printer_name)
        return jobs


def _resolve_driver_kwargs(uri: str, ppd_file: str | None) -> dict:
    """Liefert die Treiber-spezifischen kwargs für conn.addPrinter().

    libcups2-Verhalten:
      - ppd_file gesetzt   → {"filename": ppd_file}
      - URI ipp/ipps       → {"ppdname": "everywhere"}
      - sonst              → {} (raw queue)

    Bei libcups3-Switch liefert diese Funktion {} für driverless,
    weil CUPS 3 den Treiber direkt aus IPP-Attributen auflöst.
    """
    if ppd_file:
        return {"filename": ppd_file}
    if uri.startswith(("ipp://", "ipps://")):
        return {"ppdname": "everywhere"}
    return {}


def add_printer(
    name: str,
    uri: str,
    description: str = "",
    location: str = "",
    ppd_file: str | None = None,
) -> None:
    with _cups_session() as conn:
        kwargs: dict = {"device": uri}
        if description:
            kwargs["info"] = description
        if location:
            kwargs["location"] = location

        kwargs.update(_resolve_driver_kwargs(uri, ppd_file))

        try:
            conn.addPrinter(name, **kwargs)
            conn.enablePrinter(name)
            conn.acceptJobs(name)
            log.info("Drucker hinzugefügt: '%s' (%s)", name, uri)
        except cups.IPPError as exc:
            log.error("Fehler beim Hinzufügen von '%s': %s", name, exc)
            raise


def cancel_job(job_id: int) -> None:
    with _cups_session() as conn:
        try:
            conn.cancelJob(job_id, purge_job=False)
            log.info("Job %d storniert", job_id)
        except cups.IPPError as exc:
            log.error("Fehler beim Stornieren von Job %d: %s", job_id, exc)
            raise


def remove_printer(printer_name: str) -> None:
    with _cups_session() as conn:
        try:
            conn.deletePrinter(printer_name)
            log.info("Drucker entfernt: '%s'", printer_name)
        except cups.IPPError as exc:
            log.error("Fehler beim Entfernen von '%s': %s", printer_name, exc)
            raise


def get_printer_attributes(printer_name: str) -> dict:
    with _cups_session() as conn:
        try:
            attrs = conn.getPrinterAttributes(printer_name)
            log.debug("Attribute für '%s' abgerufen (%d Einträge)", printer_name, len(attrs))
            return attrs
        except cups.IPPError as exc:
            log.error("Fehler beim Abrufen der Attribute für '%s': %s", printer_name, exc)
            raise
