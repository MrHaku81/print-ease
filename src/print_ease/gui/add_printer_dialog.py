from __future__ import annotations

import re
import threading
from typing import Callable

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, GLib

from print_ease import avahi_client, cups_client
from print_ease._i18n import _
from print_ease._log import get_logger
from print_ease.printer_model import NetworkPrinter

log = get_logger(__name__)

OnPrinterAdded = Callable[[], None]

# CUPS erlaubt: A-Z, a-z, 0-9, _, -, .  (kein Leerzeichen, kein Slash)
_NAME_RE = re.compile(r"[^A-Za-z0-9_\-.]")


def _sanitize_printer_name(name: str) -> str:
    """Ersetzt CUPS-ungültige Zeichen durch Unterstriche, max 128 Zeichen."""
    sanitized = _NAME_RE.sub("_", name)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return sanitized[:128]


class AddPrinterDialog(Adw.Dialog):
    """Dialog zum manuellen oder Netzwerk-basierten Hinzufügen eines Druckers."""

    def __init__(self, on_printer_added: OnPrinterAdded):
        super().__init__()
        self._on_printer_added = on_printer_added
        self._discovery_running = False

        self.set_title(_("Drucker hinzufügen"))
        self.set_content_width(520)
        self.set_content_height(460)

        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        header = Adw.HeaderBar()
        cancel_btn = Gtk.Button(label=_("Abbrechen"))
        cancel_btn.connect("clicked", lambda _b: self.close())
        header.pack_start(cancel_btn)
        toolbar_view.add_top_bar(header)

        self._error_banner = Adw.Banner(title="")
        self._error_banner.set_revealed(False)

        self._tab_stack = Gtk.Stack()
        self._tab_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self._tab_stack.set_vexpand(True)

        switcher = Gtk.StackSwitcher()
        switcher.set_stack(self._tab_stack)
        switcher.set_halign(Gtk.Align.CENTER)

        self._tab_stack.add_titled(self._build_manual_tab(), "manual", _("Manuell"))
        self._tab_stack.add_titled(self._build_network_tab(), "network", _("Netzwerk"))
        self._tab_stack.connect("notify::visible-child-name", self._on_tab_switched)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(12)
        content_box.set_margin_start(12)
        content_box.set_margin_end(12)
        content_box.append(self._error_banner)
        content_box.append(switcher)
        content_box.append(self._tab_stack)
        toolbar_view.set_content(content_box)

    # ------------------------------------------------------------------

    def _build_manual_tab(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)

        group = Adw.PreferencesGroup(title=_("Drucker hinzufügen"))

        self._name_row = Adw.EntryRow(title=_("Name"))
        self._name_row.set_input_hints(Gtk.InputHints.NO_SPELLCHECK)
        group.add(self._name_row)

        self._uri_row = Adw.EntryRow(title="URI")
        self._uri_row.set_input_hints(
            Gtk.InputHints.NO_SPELLCHECK | Gtk.InputHints.LOWERCASE
        )
        # FIX #40: Hinweis auf das erwartete Format
        self._uri_row.set_tooltip_text("ipp://192.168.1.100:631/ipp/print")
        group.add(self._uri_row)

        self._desc_row = Adw.EntryRow(title=_("Beschreibung"))
        group.add(self._desc_row)

        self._loc_row = Adw.EntryRow(title=_("Standort"))
        group.add(self._loc_row)

        self._name_row.connect("notify::text", lambda *_: self._on_name_changed())
        self._uri_row.connect("notify::text", lambda *_: self._update_add_btn())

        self._add_btn = Gtk.Button(label=_("Hinzufügen"))
        self._add_btn.add_css_class("suggested-action")
        self._add_btn.add_css_class("pill")
        self._add_btn.set_sensitive(False)
        self._add_btn.set_halign(Gtk.Align.END)
        self._add_btn.connect("clicked", self._on_add_manual)

        box.append(group)
        box.append(self._add_btn)
        return box

    def _on_name_changed(self) -> None:
        """Validiert den Namen live und zeigt Fehlermarkierung."""
        name = self._name_row.get_text()
        if name and _NAME_RE.search(name):
            self._name_row.add_css_class("error")
        else:
            self._name_row.remove_css_class("error")
        self._update_add_btn()

    def _update_add_btn(self) -> None:
        name = self._name_row.get_text().strip()
        uri = self._uri_row.get_text().strip()
        name_ok = bool(name) and not _NAME_RE.search(name)
        self._add_btn.set_sensitive(name_ok and bool(uri))

    def _on_add_manual(self, btn: Gtk.Button) -> None:
        name = self._name_row.get_text().strip()
        uri = self._uri_row.get_text().strip()
        description = self._desc_row.get_text().strip()
        location = self._loc_row.get_text().strip()

        # FIX #38: Nochmals validieren bevor CUPS-Aufruf
        if _NAME_RE.search(name):
            self._name_row.add_css_class("error")
            return

        self._error_banner.set_revealed(False)

        # FIX #41: Spinner im Button während CUPS-Aufruf
        original_label = btn.get_label()
        btn.set_sensitive(False)
        spinner = Gtk.Spinner()
        spinner.start()
        spinner.set_valign(Gtk.Align.CENTER)
        btn.set_child(spinner)

        def _worker():
            try:
                cups_client.add_printer(name, uri, description, location)
                GLib.idle_add(_on_done, None)
            except Exception as exc:
                GLib.idle_add(_on_done, exc)

        def _on_done(error) -> bool:
            btn.set_child(None)
            btn.set_label(original_label)
            btn.set_sensitive(True)
            if error:
                log.error("Drucker hinzufügen fehlgeschlagen: %s", error)
                self._error_banner.set_title(_("Fehler: {err}").format(err=str(error)))
                self._error_banner.set_revealed(True)
            else:
                log.info("Drucker '%s' hinzugefügt", name)
                self._on_printer_added()
                self.close()
            return GLib.SOURCE_REMOVE

        threading.Thread(target=_worker, daemon=True).start()

    # ------------------------------------------------------------------

    def _build_network_tab(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_vexpand(True)

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        net_label = Gtk.Label(label=_("Netzwerkdrucker suchen"))
        net_label.add_css_class("heading")
        net_label.set_hexpand(True)
        net_label.set_halign(Gtk.Align.START)
        self._rescan_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        self._rescan_btn.set_tooltip_text(_("Erneut suchen"))
        self._rescan_btn.connect("clicked", lambda _b: self._start_discovery())
        header_box.append(net_label)
        header_box.append(self._rescan_btn)

        spinner_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        spinner_box.set_halign(Gtk.Align.CENTER)
        self._net_spinner = Gtk.Spinner()
        self._net_status_label = Gtk.Label(label="")
        self._net_status_label.add_css_class("dim-label")
        spinner_box.append(self._net_spinner)
        spinner_box.append(self._net_status_label)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._net_list = Gtk.ListBox()
        self._net_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._net_list.add_css_class("boxed-list")
        self._net_list.set_visible(False)
        scroll.set_child(self._net_list)

        self._net_empty = Adw.StatusPage()
        self._net_empty.set_icon_name("network-wireless-symbolic")
        self._net_empty.set_title(_("Keine Netzwerkdrucker gefunden"))
        self._net_empty.set_description(
            _("Stelle sicher dass Avahi läuft und Drucker im Netzwerk sind.")
        )
        self._net_empty.set_vexpand(True)
        self._net_empty.set_visible(False)

        box.append(header_box)
        box.append(spinner_box)
        box.append(scroll)
        box.append(self._net_empty)
        return box

    def _on_tab_switched(self, stack: Gtk.Stack, _param) -> None:
        if stack.get_visible_child_name() == "network" and not self._discovery_running:
            self._start_discovery()

    def _start_discovery(self) -> None:
        if self._discovery_running:
            return
        self._discovery_running = True
        self._rescan_btn.set_sensitive(False)
        self._net_spinner.start()
        self._net_status_label.set_text(_("Drucker werden geladen…"))
        self._net_list.set_visible(False)
        self._net_empty.set_visible(False)

        threading.Thread(target=self._discovery_thread, daemon=True).start()

    def _discovery_thread(self) -> None:
        try:
            printers = avahi_client.discover_network_printers(timeout=5)
        except Exception as exc:
            log.error("Netzwerksuche fehlgeschlagen: %s", exc)
            printers = []
        GLib.idle_add(self._on_discovery_done, printers)

    def _on_discovery_done(self, printers: list[NetworkPrinter]) -> bool:
        self._net_spinner.stop()
        self._net_status_label.set_text("")
        self._rescan_btn.set_sensitive(True)
        self._discovery_running = False

        while (child := self._net_list.get_first_child()) is not None:
            self._net_list.remove(child)

        if not printers:
            self._net_list.set_visible(False)
            self._net_empty.set_visible(True)
            return GLib.SOURCE_REMOVE

        self._net_empty.set_visible(False)
        for printer in printers:
            scheme_badge = "IPPS" if printer.service_type == "_ipps._tcp" else "IPP"
            subtitle = f"{printer.address}:{printer.port}  ·  {scheme_badge}"
            row = Adw.ActionRow(title=printer.name, subtitle=subtitle)
            row.set_activatable(False)

            use_btn = Gtk.Button(label=_("Übernehmen"))
            use_btn.set_valign(Gtk.Align.CENTER)
            use_btn.add_css_class("suggested-action")
            use_btn.connect("clicked", lambda _b, p=printer: self._fill_manual_tab(p))
            row.add_suffix(use_btn)
            self._net_list.append(row)

        self._net_list.set_visible(True)
        log.info("Netzwerk-Tab: %d Drucker angezeigt", len(printers))
        return GLib.SOURCE_REMOVE

    def _fill_manual_tab(self, printer: NetworkPrinter) -> None:
        # FIX #42: mDNS-Namen mit Leerzeichen/Sonderzeichen bereinigen
        safe_name = _sanitize_printer_name(printer.name)
        self._name_row.set_text(safe_name)
        self._uri_row.set_text(printer.uri)
        desc = printer.txt_records.get("ty") or printer.name
        self._desc_row.set_text(desc)
        self._loc_row.set_text(printer.txt_records.get("note", ""))
        self._tab_stack.set_visible_child_name("manual")
        log.debug("Netzwerkdrucker '%s' → Name '%s' in Manuell-Tab übernommen",
                  printer.name, safe_name)
