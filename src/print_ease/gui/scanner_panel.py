from __future__ import annotations

import subprocess
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, GLib

from print_ease import scanner_client, settings
from print_ease._i18n import _
from print_ease._log import get_logger
from print_ease.printer_model import ScannerInfo

log = get_logger(__name__)


def _color_labels() -> dict[str, str]:
    return {
        "RGB24":          _("Farbe"),
        "Grayscale8":     _("Graustufen"),
        "BlackAndWhite1": _("Schwarzweiß"),
    }


def _source_labels() -> dict[str, str]:
    return {
        "Platen":     _("Flachbett"),
        "AdfSimplex": _("Einzug"),
    }


def _duplex_labels() -> dict[str, str]:
    return {
        "None":              _("Aus"),
        "AdfDuplex":         _("Hardware (Beta)"),
        "AdfDuplexSoftware": _("Software"),
    }


def _mode_labels() -> dict[str, str]:
    return {
        "single":    _("Einzelseite"),
        "multipage": _("Multi-Page Dokument"),
    }


class ScannerPanel:
    """Baut eine Adw.PreferencesGroup mit Scanner-Bedienelementen."""

    def __init__(self, scanner: ScannerInfo):
        self._scanner = scanner
        self._cancel_event: threading.Event | None = None
        self._last_scan_path: str | None = None
        self._settings_key = f"scan_settings_{scanner.name}"
        self._sources = self._build_source_list(scanner)
        self._duplex_modes = self._build_duplex_list(scanner)
        self._duplex_drop: Gtk.DropDown | None = None
        self._duplex_row: Adw.ActionRow | None = None
        self._mode_options: list[str] = self._build_mode_list()
        self._mode_drop: Gtk.DropDown | None = None
        self._mode_row: Adw.ActionRow | None = None
        self._group = self._build()
        self._restore_scan_settings()

    def get_group(self) -> Adw.PreferencesGroup:
        return self._group

    # ------------------------------------------------------------------

    def _build_source_list(self, s: ScannerInfo) -> list[str]:
        return [src for src in s.document_sources if src in ("Platen", "AdfSimplex")]

    def _build_duplex_list(self, s: ScannerInfo) -> list[str]:
        if not scanner_client.supports_adf(s):
            return []
        modes = ["None"]
        if scanner_client.supports_hardware_duplex(s):
            modes.append("AdfDuplex")
        modes.append("AdfDuplexSoftware")
        return modes

    def _build_mode_list(self) -> list[str]:
        return ["single", "multipage"]

    def _build(self) -> Adw.PreferencesGroup:
        s = self._scanner
        group = Adw.PreferencesGroup(title=_("Scanner"))

        res_strings = [f"{r} dpi" for r in s.resolutions]
        default_res = s.resolutions.index(300) if 300 in s.resolutions else len(s.resolutions) - 1
        self._res_drop = _make_dropdown(res_strings, default_res)
        res_row = Adw.ActionRow(title=_("Auflösung"))
        res_row.set_activatable(False)
        res_row.add_suffix(self._res_drop)
        group.add(res_row)

        color_strings = [_color_labels().get(m, m) for m in s.color_modes]
        self._color_drop = _make_dropdown(color_strings, 0)
        color_row = Adw.ActionRow(title=_("Farbmodus"))
        color_row.set_activatable(False)
        color_row.add_suffix(self._color_drop)
        group.add(color_row)

        if len(self._sources) > 1:
            src_strings = [_source_labels().get(src, src) for src in self._sources]
            self._src_drop = _make_dropdown(src_strings, 0)
            src_row = Adw.ActionRow(title=_("Quelle"))
            src_row.set_activatable(False)
            src_row.add_suffix(self._src_drop)
            group.add(src_row)
        else:
            self._src_drop = None

        if len(self._mode_options) > 1:
            mode_strings = [_mode_labels().get(m, m) for m in self._mode_options]
            self._mode_drop = _make_dropdown(mode_strings, 0)
            self._mode_row = Adw.ActionRow(title=_("Modus"))
            self._mode_row.set_activatable(False)
            self._mode_row.add_suffix(self._mode_drop)
            self._mode_row.set_visible(self._get_selected_source() == "Platen")
            group.add(self._mode_row)

        if len(self._duplex_modes) > 1:
            dup_strings = [_duplex_labels().get(m, m) for m in self._duplex_modes]
            self._duplex_drop = _make_dropdown(dup_strings, 0)
            self._duplex_row = Adw.ActionRow(title=_("Duplex"))
            self._duplex_row.set_activatable(False)
            self._duplex_row.add_suffix(self._duplex_drop)
            self._duplex_row.set_visible(self._get_selected_source() == "AdfSimplex")
            group.add(self._duplex_row)

        if self._src_drop is not None and (self._mode_row is not None or self._duplex_row is not None):
            self._src_drop.connect("notify::selected", self._on_source_changed)

        scan_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        scan_box.set_valign(Gtk.Align.CENTER)
        self._spinner = Gtk.Spinner()
        self._scan_btn = Gtk.Button(label=_("Scan starten"))
        self._scan_btn.add_css_class("suggested-action")
        self._scan_btn.connect("clicked", self._on_scan_clicked)

        self._cancel_btn = Gtk.Button(label=_("Abbrechen"))
        self._cancel_btn.add_css_class("destructive-action")
        self._cancel_btn.set_visible(False)
        self._cancel_btn.connect("clicked", self._on_cancel_clicked)

        scan_box.append(self._spinner)
        scan_box.append(self._scan_btn)
        scan_box.append(self._cancel_btn)
        scan_row = Adw.ActionRow(title=_("Scannen"))
        scan_row.set_activatable(False)
        scan_row.add_suffix(scan_box)
        group.add(scan_row)

        self._saved_row = Adw.ActionRow(title=_("Gespeichert unter"))
        self._saved_row.set_activatable(False)
        self._saved_row.set_subtitle("—")
        self._saved_row.set_subtitle_selectable(True)

        self._open_btn = Gtk.Button(label=_("Öffnen"))
        self._open_btn.add_css_class("flat")
        self._open_btn.set_valign(Gtk.Align.CENTER)
        self._open_btn.set_visible(False)
        self._open_btn.connect("clicked", lambda _: self._open_last_scan())
        self._saved_row.add_suffix(self._open_btn)

        group.add(self._saved_row)

        return group

    # ------------------------------------------------------------------
    # Scan-Einstellungen speichern/wiederherstellen (FIX #37)
    # ------------------------------------------------------------------

    def _get_selected_resolution(self) -> int:
        idx = self._res_drop.get_selected()
        s = self._scanner
        return s.resolutions[idx] if idx < len(s.resolutions) else 300

    def _get_selected_color_mode(self) -> str:
        cidx = self._color_drop.get_selected()
        s = self._scanner
        return s.color_modes[cidx] if cidx < len(s.color_modes) else "RGB24"

    def _get_selected_source(self) -> str:
        if self._src_drop is not None:
            sidx = self._src_drop.get_selected()
            return self._sources[sidx] if sidx < len(self._sources) else "Platen"
        return self._sources[0] if self._sources else "Platen"

    def _get_selected_duplex(self) -> str:
        if self._duplex_drop is not None:
            idx = self._duplex_drop.get_selected()
            return self._duplex_modes[idx] if idx < len(self._duplex_modes) else "None"
        return "None"

    def _get_selected_mode(self) -> str:
        if self._mode_drop is not None:
            idx = self._mode_drop.get_selected()
            return self._mode_options[idx] if idx < len(self._mode_options) else "single"
        return "single"

    def _save_scan_settings(self) -> None:
        settings.set(self._settings_key, {
            "resolution": self._get_selected_resolution(),
            "color_mode": self._get_selected_color_mode(),
            "source":     self._get_selected_source(),
            "duplex":     self._get_selected_duplex(),
            "mode":       self._get_selected_mode(),
        })
        log.debug("Scan-Einstellungen gespeichert für '%s'", self._scanner.name)

    def _restore_scan_settings(self) -> None:
        saved = settings.get(self._settings_key)
        if not saved:
            return
        s = self._scanner

        res = saved.get("resolution", 300)
        if res in s.resolutions:
            self._res_drop.set_selected(s.resolutions.index(res))

        cm = saved.get("color_mode", "RGB24")
        if cm in s.color_modes:
            self._color_drop.set_selected(s.color_modes.index(cm))

        src = saved.get("source", "Platen")
        if self._src_drop is not None and src in self._sources:
            self._src_drop.set_selected(self._sources.index(src))

        dup = saved.get("duplex", "None")
        if self._duplex_drop is not None and dup in self._duplex_modes:
            self._duplex_drop.set_selected(self._duplex_modes.index(dup))

        mode = saved.get("mode", "single")
        if self._mode_drop is not None and mode in self._mode_options:
            self._mode_drop.set_selected(self._mode_options.index(mode))

        log.debug("Scan-Einstellungen wiederhergestellt für '%s'", self._scanner.name)

    # ------------------------------------------------------------------

    def _on_scan_clicked(self, btn: Gtk.Button) -> None:
        color_mode = self._get_selected_color_mode()
        resolution = self._get_selected_resolution()
        source = self._get_selected_source()
        duplex = self._get_selected_duplex()
        mode = self._get_selected_mode()

        self._save_scan_settings()

        if source == "Platen" and mode == "multipage":
            self._run_multipage_platen(btn, color_mode, resolution)
            return
        if source == "AdfSimplex" and duplex == "AdfDuplex":
            self._run_hardware_duplex(btn, color_mode, resolution)
            return
        if source == "AdfSimplex" and duplex == "AdfDuplexSoftware":
            self._run_software_duplex(btn, color_mode, resolution)
            return

        # Strings im Main-Thread vorübersetzen — thread-sicher
        msg_no_paper = _("Kein Papier im Einzug")
        msg_cancelled = _("Scan abgebrochen")

        btn.set_sensitive(False)
        self._cancel_btn.set_visible(True)
        self._spinner.start()
        self._saved_row.set_subtitle(_("Scannt…"))
        self._open_btn.set_visible(False)

        self._cancel_event = threading.Event()
        threading.Thread(
            target=self._scan_thread,
            args=(color_mode, resolution, source, self._cancel_event,
                  msg_no_paper, msg_cancelled),
            daemon=True,
        ).start()

    def _on_cancel_clicked(self, _btn: Gtk.Button) -> None:
        if self._cancel_event:
            self._cancel_event.set()
            log.info("Scan-Abbruch angefordert")
        self._cancel_btn.set_sensitive(False)

    def _on_source_changed(self, _drop: Gtk.DropDown, _pspec) -> None:
        source = self._get_selected_source()
        if self._mode_row is not None:
            self._mode_row.set_visible(source == "Platen")
        if self._duplex_row is not None:
            self._duplex_row.set_visible(source == "AdfSimplex")

    def _scan_thread(
        self,
        color_mode: str,
        resolution: int,
        source: str,
        cancel_event: threading.Event,
        msg_no_paper: str,
        msg_cancelled: str,
    ) -> None:
        if source == "AdfSimplex" and self._scanner.detect_paper_loaded:
            if not cancel_event.is_set():
                adf_state = scanner_client.get_adf_state(self._scanner.escl_url)
                if adf_state == "ScannerAdfEmpty":
                    log.warning("ADF-Einzug leer (AdfState=ScannerAdfEmpty)")
                    GLib.idle_add(self._on_scan_done, False, msg_no_paper)
                    return

        try:
            path = scanner_client.scan_document(
                self._scanner, color_mode, resolution, source,
                cancel_event=cancel_event,
            )
            GLib.idle_add(self._on_scan_done, True, path)
        except InterruptedError:
            log.info("Scan abgebrochen")
            GLib.idle_add(self._on_scan_done, False, msg_cancelled)
        except Exception as exc:
            log.error("Scan fehlgeschlagen: %s", exc)
            GLib.idle_add(self._on_scan_done, False, str(exc))

    def _on_scan_done(self, success: bool, result: str) -> bool:
        self._spinner.stop()
        self._scan_btn.set_sensitive(True)
        self._cancel_btn.set_visible(False)
        self._cancel_btn.set_sensitive(True)

        if success:
            self._last_scan_path = result
            self._saved_row.set_subtitle(result)
            self._open_btn.set_visible(True)
            log.info("Scan abgeschlossen: %s", result)
        else:
            self._saved_row.set_subtitle(_("Fehler: {err}").format(err=result))
            self._open_btn.set_visible(False)

        return GLib.SOURCE_REMOVE

    def _open_last_scan(self) -> None:
        if not self._last_scan_path:
            return
        try:
            subprocess.Popen(["xdg-open", self._last_scan_path])
            log.info("Datei geöffnet: %s", self._last_scan_path)
        except Exception as exc:
            log.error("Datei konnte nicht geöffnet werden: %s", exc)

    # ------------------------------------------------------------------
    # Hardware-Duplex (BETA)
    # ------------------------------------------------------------------

    def _run_hardware_duplex(
        self, btn: Gtk.Button, color_mode: str, resolution: int
    ) -> None:
        msg_no_paper  = _("Kein Papier im Einzug")
        msg_cancelled = _("Hardware-Duplex-Scan abgebrochen")

        btn.set_sensitive(False)
        self._cancel_btn.set_visible(True)
        self._spinner.start()
        self._saved_row.set_subtitle(_("Hardware-Duplex-Scan läuft… (Beta)"))
        self._open_btn.set_visible(False)

        self._cancel_event = threading.Event()
        cancel_event = self._cancel_event

        def _do_scan() -> None:
            if self._scanner.detect_paper_loaded and not cancel_event.is_set():
                adf_state = scanner_client.get_adf_state(self._scanner.escl_url)
                if adf_state == "ScannerAdfEmpty":
                    log.warning("ADF leer für Hardware-Duplex-Scan")
                    GLib.idle_add(self._on_scan_done, False, msg_no_paper)
                    return

            try:
                path = scanner_client.scan_adf_hardware_duplex(
                    self._scanner, color_mode, resolution,
                    cancel_event=cancel_event,
                )
                GLib.idle_add(self._on_scan_done, True, path)
            except InterruptedError:
                log.info("Hardware-Duplex-Scan abgebrochen")
                GLib.idle_add(self._on_scan_done, False, msg_cancelled)
            except Exception as exc:
                log.error("Hardware-Duplex-Scan fehlgeschlagen: %s", exc)
                GLib.idle_add(self._on_scan_done, False, str(exc))

        threading.Thread(target=_do_scan, daemon=True).start()

    # ------------------------------------------------------------------
    # Multi-Page Flachbett
    # ------------------------------------------------------------------

    def _run_multipage_platen(
        self, btn: Gtk.Button, color_mode: str, resolution: int
    ) -> None:
        msg_scanning  = _("Seite wird gescannt…")
        msg_cancelled = _("Multi-Page-Scan abgebrochen")

        btn.set_sensitive(False)
        self._cancel_btn.set_visible(True)
        self._spinner.start()
        self._saved_row.set_subtitle(msg_scanning)
        self._open_btn.set_visible(False)

        self._cancel_event = threading.Event()
        cancel_event = self._cancel_event

        def _next_page_callback(page_num: int) -> str:
            GLib.idle_add(
                self._saved_row.set_subtitle,
                _("Seite {n} gescannt — warte auf Antwort…").format(n=page_num),
            )
            result: list[str] = ["continue"]
            done_event = threading.Event()
            GLib.idle_add(self._show_multipage_dialog, page_num, result, done_event)
            while not done_event.wait(timeout=1.0):
                if cancel_event.is_set():
                    raise InterruptedError("Scan abgebrochen")
            return result[0]

        def _do_scan() -> None:
            try:
                path = scanner_client.scan_platen_multipage(
                    self._scanner, color_mode, resolution,
                    next_page_callback=_next_page_callback,
                    cancel_event=cancel_event,
                )
                GLib.idle_add(self._on_scan_done, True, path)
            except InterruptedError:
                log.info("Multi-Page-Scan abgebrochen")
                GLib.idle_add(self._on_scan_done, False, msg_cancelled)
            except Exception as exc:
                log.error("Multi-Page-Scan fehlgeschlagen: %s", exc)
                GLib.idle_add(self._on_scan_done, False, str(exc))

        threading.Thread(target=_do_scan, daemon=True).start()

    # ------------------------------------------------------------------
    # Software-Duplex
    # ------------------------------------------------------------------

    def _run_software_duplex(
        self, btn: Gtk.Button, color_mode: str, resolution: int
    ) -> None:
        # Strings im Main-Thread vorübersetzen — thread-sicher
        msg_front     = _("Vorderseiten werden gescannt…")
        msg_back      = _("Rückseiten werden gescannt…")
        msg_pdf       = _("PDF wird erstellt…")
        msg_no_paper  = _("Kein Papier im Einzug")
        msg_cancelled = _("Duplex-Scan abgebrochen")

        btn.set_sensitive(False)
        self._cancel_btn.set_visible(True)
        self._spinner.start()
        self._saved_row.set_subtitle(msg_front)
        self._open_btn.set_visible(False)

        self._cancel_event = threading.Event()
        cancel_event = self._cancel_event

        def _flip_callback() -> None:
            flip_confirmed = threading.Event()
            GLib.idle_add(self._show_flip_dialog, flip_confirmed)
            while not flip_confirmed.wait(timeout=1.0):
                if cancel_event.is_set():
                    raise InterruptedError("Scan abgebrochen")

        def _progress(stage: str) -> None:
            labels = {"front": msg_front, "back": msg_back, "pdf": msg_pdf}
            GLib.idle_add(self._saved_row.set_subtitle, labels.get(stage, stage))

        def _do_scan() -> None:
            if self._scanner.detect_paper_loaded and not cancel_event.is_set():
                adf_state = scanner_client.get_adf_state(self._scanner.escl_url)
                if adf_state == "ScannerAdfEmpty":
                    log.warning("ADF leer für Duplex-Scan")
                    GLib.idle_add(self._on_scan_done, False, msg_no_paper)
                    return

            try:
                path = scanner_client.scan_duplex_software(
                    self._scanner, color_mode, resolution,
                    cancel_event=cancel_event,
                    flip_callback=_flip_callback,
                    progress_callback=_progress,
                )
                GLib.idle_add(self._on_scan_done, True, path)
            except InterruptedError:
                log.info("Duplex-Scan abgebrochen")
                GLib.idle_add(self._on_scan_done, False, msg_cancelled)
            except Exception as exc:
                log.error("Duplex-Scan fehlgeschlagen: %s", exc)
                GLib.idle_add(self._on_scan_done, False, str(exc))

        threading.Thread(target=_do_scan, daemon=True).start()

    def _show_flip_dialog(self, confirmed_event: threading.Event) -> bool:
        root = self._group.get_root()
        if root is None:
            log.warning("_show_flip_dialog: get_root() ist None — Dialog übersprungen")
            confirmed_event.set()
            return GLib.SOURCE_REMOVE

        dialog = Adw.AlertDialog(
            heading=_("Stapel umdrehen und erneut einlegen"),
            body=_(
                "Vorderseiten gescannt. Drehe den Stapel um, "
                "lege ihn erneut in den ADF ein und bestätige."
            ),
        )
        dialog.add_response("cancel", _("Abbrechen"))
        dialog.add_response("continue", _("Weiter"))
        dialog.set_response_appearance("continue", Adw.ResponseAppearance.SUGGESTED)

        def _on_response(_dlg, response: str) -> None:
            if response == "cancel" and self._cancel_event:
                self._cancel_event.set()
            confirmed_event.set()

        dialog.connect("response", _on_response)
        dialog.present(root)
        return GLib.SOURCE_REMOVE

    def _show_multipage_dialog(
        self, page_num: int, result: list[str], done_event: threading.Event
    ) -> bool:
        root = self._group.get_root()
        if root is None:
            log.warning("_show_multipage_dialog: get_root() ist None — Dialog übersprungen")
            done_event.set()
            return GLib.SOURCE_REMOVE

        dialog = Adw.AlertDialog(
            heading=_("Seite {n} gescannt").format(n=page_num),
            body=_("Bisher {n} Seiten im Dokument.").format(n=page_num),
        )
        dialog.add_response("cancel",   _("Abbrechen"))
        dialog.add_response("finish",   _("Fertig"))
        dialog.add_response("continue", _("Nächste Seite"))
        dialog.set_response_appearance("continue", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("continue")
        dialog.set_close_response("cancel")

        def _on_response(_dlg, response: str) -> None:
            result[0] = response
            if response == "cancel" and self._cancel_event:
                self._cancel_event.set()
            done_event.set()

        dialog.connect("response", _on_response)
        dialog.present(root)
        return GLib.SOURCE_REMOVE


# ---------------------------------------------------------------------------

def _make_dropdown(items: list[str], selected: int) -> Gtk.DropDown:
    model = Gtk.StringList.new(items)
    dd = Gtk.DropDown.new(model, None)
    dd.set_selected(selected)
    dd.set_valign(Gtk.Align.CENTER)
    return dd
