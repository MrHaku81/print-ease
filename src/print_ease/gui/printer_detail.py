from __future__ import annotations

import threading
from typing import Callable

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, GLib

import urllib.parse

from print_ease import cups_client, scanner_client
from print_ease._i18n import _
from print_ease._log import get_logger
from print_ease.gui.scanner_panel import ScannerPanel
from print_ease.printer_model import PrinterInfo

log = get_logger(__name__)

OnAction = Callable[[], None]


class PrinterDetail(Gtk.Box):
    """Rechte Detailansicht für einen ausgewählten Drucker."""

    def __init__(self, on_printer_removed: OnAction | None = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_printer_removed = on_printer_removed

        self._stack = Gtk.Stack()
        self._stack.set_vexpand(True)
        self.append(self._stack)

        empty = Adw.StatusPage()
        empty.set_icon_name("printer-symbolic")
        empty.set_title(_("Kein Drucker ausgewählt"))
        empty.set_description(_("Wähle einen Drucker aus der Liste."))
        self._stack.add_named(empty, "empty")

        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._stack.add_named(self._scroll, "detail")

        self._stack.set_visible_child_name("empty")

    # ------------------------------------------------------------------

    def show_empty(self) -> None:
        self._stack.set_visible_child_name("empty")

    def show_printer(self, printer: PrinterInfo, on_action: OnAction) -> None:
        page = self._build_page(printer, on_action)
        self._scroll.set_child(page)
        self._stack.set_visible_child_name("detail")

    # ------------------------------------------------------------------

    def _build_page(self, printer: PrinterInfo, on_action: OnAction) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage()

        page.add(self._build_info_group(printer))
        page.add(self._build_action_group(printer, on_action))
        page.add(self._build_jobs_group(printer, on_action))

        danger_group = self._build_danger_group(printer)
        escl_url = _escl_url_for(printer)
        if escl_url:
            scanner_placeholder = self._build_scanner_placeholder()
            page.add(scanner_placeholder)
            page.add(danger_group)
            self._load_scanner_async(escl_url, printer.name, scanner_placeholder, page, danger_group)
        else:
            page.add(danger_group)

        return page

    def _build_scanner_placeholder(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title=_("Scanner"))
        spinner = Gtk.Spinner()
        spinner.start()
        spinner.set_valign(Gtk.Align.CENTER)
        row = Adw.ActionRow(title=_("Scanner wird erkannt…"))
        row.set_activatable(False)
        row.add_prefix(spinner)
        group.add(row)
        return group

    def _load_scanner_async(
        self,
        escl_url: str,
        printer_name: str,
        placeholder_group: Adw.PreferencesGroup,
        page: Adw.PreferencesPage,
        danger_group: Adw.PreferencesGroup,
    ) -> None:
        def _fetch():
            scanner = scanner_client.get_scanner_capabilities(
                escl_url, linked_printer=printer_name
            )
            GLib.idle_add(_on_loaded, scanner)

        def _on_loaded(scanner) -> bool:
            page.remove(placeholder_group)
            if scanner:
                page.remove(danger_group)
                page.add(ScannerPanel(scanner).get_group())
                page.add(danger_group)
            return GLib.SOURCE_REMOVE

        threading.Thread(target=_fetch, daemon=True).start()

    def _build_info_group(self, printer: PrinterInfo) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title=_("Druckerinformationen"))

        for title, value in [
            (_("Name"),         printer.name),
            (_("Beschreibung"), printer.description or "—"),
            (_("Standort"),     printer.location or "—"),
            (_("Verbindung"),   printer.uri),
        ]:
            row = Adw.ActionRow(title=title, subtitle=value)
            row.set_activatable(False)
            row.set_subtitle_selectable(True)
            group.add(row)

        status_text, css_class = _state_label(printer)
        status_lbl = Gtk.Label(label=status_text)
        status_lbl.set_valign(Gtk.Align.CENTER)
        status_lbl.add_css_class(css_class)
        status_row = Adw.ActionRow(title=_("Status"))
        status_row.set_activatable(False)
        status_row.add_suffix(status_lbl)
        group.add(status_row)

        return group

    def _build_action_group(self, printer: PrinterInfo, on_action: OnAction) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title=_("Aktionen"))

        default_row = Adw.ActionRow(title=_("Als Standard setzen"))
        default_row.set_activatable(False)
        if printer.is_default:
            check = Gtk.Label(label=_("✓ Ist Standard"))
            check.set_valign(Gtk.Align.CENTER)
            check.add_css_class("success")
            default_row.add_suffix(check)
        else:
            btn = Gtk.Button(label=_("Standard setzen"))
            btn.set_valign(Gtk.Align.CENTER)
            btn.add_css_class("suggested-action")
            btn.connect(
                "clicked",
                lambda b: self._run_cups_action(
                    b, lambda: cups_client.set_default_printer(printer.name),
                    _("Standard setzen"), on_action,
                ),
            )
            default_row.add_suffix(btn)
        group.add(default_row)

        if printer.state == "stopped":
            pause_title = _("Drucker fortsetzen")
            pause_label = _("Fortsetzen")
            pause_fn = lambda: cups_client.resume_printer(printer.name)  # noqa: E731
        else:
            pause_title = _("Drucker pausieren")
            pause_label = _("Pausieren")
            pause_fn = lambda: cups_client.pause_printer(printer.name)  # noqa: E731

        pause_row = Adw.ActionRow(title=pause_title)
        pause_row.set_activatable(False)
        pause_btn = Gtk.Button(label=pause_label)
        pause_btn.set_valign(Gtk.Align.CENTER)
        pause_btn.connect(
            "clicked",
            lambda b: self._run_cups_action(b, pause_fn, pause_label, on_action),
        )
        pause_row.add_suffix(pause_btn)
        group.add(pause_row)

        test_row = Adw.ActionRow(title=_("Testseite drucken"))
        test_row.set_activatable(False)
        test_btn = Gtk.Button(label=_("Drucken"))
        test_btn.set_valign(Gtk.Align.CENTER)
        test_btn.connect(
            "clicked",
            lambda b: self._run_cups_action(
                b, lambda: cups_client.print_test_page(printer.name),
                _("Drucken"), None,
            ),
        )
        test_row.add_suffix(test_btn)
        group.add(test_row)

        return group

    def _build_jobs_group(self, printer: PrinterInfo, on_action: OnAction) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title=_("Aktive Druckjobs"))

        loading_row = Adw.ActionRow(title=_("Jobs werden geladen…"))
        loading_row.set_activatable(False)
        spinner = Gtk.Spinner()
        spinner.start()
        spinner.set_valign(Gtk.Align.CENTER)
        loading_row.add_prefix(spinner)
        group.add(loading_row)

        printer_name = printer.name

        def _fetch_jobs() -> None:
            try:
                jobs = cups_client.get_jobs(printer_name)
                GLib.idle_add(_on_jobs_loaded, jobs, None)
            except Exception as exc:
                log.error("Jobs konnten nicht abgerufen werden: %s", exc)
                GLib.idle_add(_on_jobs_loaded, [], exc)

        def _on_jobs_loaded(jobs: list, error: Exception | None) -> bool:
            group.remove(loading_row)
            if error:
                row = Adw.ActionRow(title=_("Fehler beim Laden der Jobs"))
                row.set_activatable(False)
                group.add(row)
            elif not jobs:
                row = Adw.ActionRow(title=_("Keine aktiven Jobs"))
                row.set_activatable(False)
                group.add(row)
            else:
                for job in jobs:
                    row = Adw.ActionRow(
                        title=job.title,
                        subtitle=f"{_('Job')} {job.job_id} · {job.user}",
                    )
                    row.set_activatable(False)
                    cancel_btn = Gtk.Button(label=_("Abbrechen"))
                    cancel_btn.add_css_class("destructive-action")
                    cancel_btn.add_css_class("flat")
                    cancel_btn.set_valign(Gtk.Align.CENTER)
                    cancel_btn.connect(
                        "clicked",
                        lambda b, jid=job.job_id: self._cancel_job(b, jid, on_action),
                    )
                    row.add_suffix(cancel_btn)
                    group.add(row)
            return GLib.SOURCE_REMOVE

        threading.Thread(target=_fetch_jobs, daemon=True).start()
        return group

    def _cancel_job(self, btn: Gtk.Button, job_id: int, on_success: OnAction) -> None:
        btn.set_sensitive(False)

        def _worker():
            try:
                cups_client.cancel_job(job_id)
                log.info("Job %d storniert", job_id)
                GLib.idle_add(on_success)
            except Exception as exc:
                log.error("Job %d konnte nicht storniert werden: %s", job_id, exc)
                GLib.idle_add(btn.set_sensitive, True)

        threading.Thread(target=_worker, daemon=True).start()

    def _build_danger_group(self, printer: PrinterInfo) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title=_("Gefahrenzone"))

        remove_row = Adw.ActionRow(
            title=_("Drucker entfernen"),
            subtitle=_("Entfernt den Drucker dauerhaft aus CUPS"),
        )
        remove_row.set_activatable(False)

        remove_btn = Gtk.Button(label=_("Entfernen"))
        remove_btn.set_valign(Gtk.Align.CENTER)
        remove_btn.add_css_class("destructive-action")
        remove_btn.add_css_class("pill")
        remove_btn.connect("clicked", lambda b: self._on_remove_clicked(b, printer))
        remove_row.add_suffix(remove_btn)

        group.add(remove_row)
        return group

    # ------------------------------------------------------------------
    # Async CUPS action runner
    # ------------------------------------------------------------------

    def _run_cups_action(
        self,
        button: Gtk.Button,
        action_fn,
        label: str,
        on_success: OnAction | None,
    ) -> None:
        original_label = button.get_label()
        button.set_sensitive(False)
        spinner = Gtk.Spinner()
        spinner.start()
        spinner.set_valign(Gtk.Align.CENTER)
        button.set_child(spinner)

        def _worker():
            try:
                action_fn()
                GLib.idle_add(_on_done, None)
            except Exception as exc:
                GLib.idle_add(_on_done, exc)

        def _on_done(error) -> bool:
            button.set_child(None)
            button.set_label(original_label)
            button.set_sensitive(True)
            if error:
                log.error("%s fehlgeschlagen: %s", label, error)
                toast = Adw.Toast(title=_("Aktion fehlgeschlagen: {err}").format(err=str(error)))
                toast.set_timeout(4)
                root = self.get_root()
                if hasattr(root, "add_toast"):
                    root.add_toast(toast)
            else:
                if on_success:
                    on_success()
            return GLib.SOURCE_REMOVE

        threading.Thread(target=_worker, daemon=True).start()

    # ------------------------------------------------------------------

    def _on_remove_clicked(self, btn: Gtk.Button, printer: PrinterInfo) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Drucker entfernen?"),
            body=f"'{printer.name}' {_('wird dauerhaft aus CUPS entfernt.')}",
        )
        dialog.add_response("cancel", _("Abbrechen"))
        dialog.add_response("delete", _("Entfernen"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_remove_response, printer.name, btn)
        dialog.present(self.get_root())

    def _on_remove_response(
        self, _dialog: Adw.AlertDialog, response: str, name: str, btn: Gtk.Button
    ) -> None:
        if response != "delete":
            return
        self._run_cups_action(
            btn,
            lambda: cups_client.remove_printer(name),
            _("Entfernen"),
            self._on_printer_removed,
        )


def _escl_url_for(printer: PrinterInfo) -> str | None:
    parsed = urllib.parse.urlparse(printer.uri)
    if parsed.scheme not in ("ipp", "ipps", "http", "https"):
        return None
    host = parsed.hostname
    if not host:
        return None
    scheme = "https" if parsed.scheme == "ipps" else "http"
    port = parsed.port
    # Port nur einfügen wenn nicht Standard (80/443) und nicht IPP-Standard (631)
    if port and port not in (80, 443, 631):
        return f"{scheme}://{host}:{port}/eSCL"
    return f"{scheme}://{host}/eSCL"


def _state_label(printer: PrinterInfo) -> tuple[str, str]:
    match printer.state:
        case "idle":
            return _("Bereit"), "success"
        case "processing":
            return _("Druckt…"), "accent"
        case "stopped":
            return _("Gestoppt"), "error"
        case _:
            return printer.state_message or printer.state, "dim-label"
