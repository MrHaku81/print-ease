from __future__ import annotations

import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk, GLib

from print_ease import cups_client, settings
from print_ease._i18n import _, get_current_lang, setup_i18n, SUPPORTED_LANGS, LANG_NAMES
from print_ease._log import get_logger
from print_ease.gui.add_printer_dialog import AddPrinterDialog
from print_ease.gui.printer_detail import PrinterDetail
from print_ease.gui.printer_row import PrinterRow

log = get_logger(__name__)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, selected_printer: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self.set_title("PrintEase")

        self._selected_printer_name: str | None = selected_printer

        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        # --- Headerbar ---
        self._header = Adw.HeaderBar()

        self._add_btn = Gtk.Button.new_from_icon_name("list-add-symbolic")
        self._add_btn.set_tooltip_text(_("Drucker hinzufügen") + " (Ctrl+N)")
        self._add_btn.connect("clicked", self._on_add_printer)
        self._header.pack_start(self._add_btn)

        self._refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        self._refresh_btn.set_tooltip_text(_("Drucker aktualisieren") + " (Ctrl+R / F5)")
        self._refresh_btn.connect("clicked", lambda _b: self._load_printers())
        self._header.pack_end(self._refresh_btn)

        self._header.pack_end(self._build_lang_dropdown())
        self._header.pack_end(self._build_menu_button())

        toolbar_view.add_top_bar(self._header)

        # --- Hauptinhalt ---
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        toolbar_view.set_content(main_box)

        self._error_banner = Adw.Banner(title="")
        self._error_banner.set_revealed(False)
        main_box.append(self._error_banner)

        self._paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self._paned.set_vexpand(True)
        self._paned.set_shrink_start_child(False)
        self._paned.set_shrink_end_child(False)
        main_box.append(self._paned)

        # --- Linke Seite ---
        self._stack = Gtk.Stack()
        self._paned.set_start_child(self._stack)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._list_box.add_css_class("boxed-list")
        self._list_box.set_margin_top(8)
        self._list_box.set_margin_bottom(8)
        self._list_box.set_margin_start(8)
        self._list_box.set_margin_end(8)
        self._list_box.connect("row-selected", self._on_printer_selected)
        scroll.set_child(self._list_box)
        self._stack.add_named(scroll, "list")

        loading_page = Adw.StatusPage()
        loading_page.set_icon_name("printer-symbolic")
        loading_page.set_title(_("Drucker werden geladen…"))
        self._stack.add_named(loading_page, "loading")

        empty_page = Adw.StatusPage()
        empty_page.set_icon_name("printer-symbolic")
        empty_page.set_title(_("Keine Drucker gefunden"))
        empty_page.set_description(_("Drucker hinzufügen oder CUPS-Verbindung prüfen."))
        self._stack.add_named(empty_page, "empty")

        # --- Rechte Seite ---
        self._detail = PrinterDetail(on_printer_removed=self._load_printers)
        self._paned.set_end_child(self._detail)

        # FIX #46: Fenstergröße + Split-Position wiederherstellen
        self._restore_window_state()

        self._setup_shortcuts()
        self.connect("close-request", lambda _: self._save_window_state() or False)
        GLib.idle_add(self._load_printers)

    # ------------------------------------------------------------------
    # Hamburger-Menü (TEIL 1)
    # ------------------------------------------------------------------

    def _build_menu_button(self) -> Gtk.MenuButton:
        menu = Gio.Menu()
        menu.append(_("Über PrintEase"), "app.about")
        menu.append(_("Tastaturkürzel"), "app.shortcuts")
        menu.append(_("Beenden"), "app.quit")

        btn = Gtk.MenuButton()
        btn.set_icon_name("open-menu-symbolic")
        btn.set_menu_model(menu)
        btn.set_tooltip_text(_("Menü"))
        return btn

    # ------------------------------------------------------------------
    # Tastaturkürzel (FIX #44)
    # ------------------------------------------------------------------

    def _setup_shortcuts(self) -> None:
        controller = Gtk.ShortcutController()
        controller.set_scope(Gtk.ShortcutScope.GLOBAL)

        def _add(trigger: str, cb):
            controller.add_shortcut(Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string(trigger),
                Gtk.CallbackAction.new(cb),
            ))

        _add("<Control>r", lambda *_: self._load_printers() or True)
        _add("F5",         lambda *_: self._load_printers() or True)
        _add("<Control>n", lambda *_: self._on_add_printer(None) or True)

        self.add_controller(controller)

    # ------------------------------------------------------------------
    # Fenster-State (FIX #46)
    # ------------------------------------------------------------------

    def _restore_window_state(self) -> None:
        w = settings.get("window_width", 800)
        h = settings.get("window_height", 600)
        pos = settings.get("paned_position", 300)
        self.set_default_size(w, h)
        self._paned.set_position(pos)

    def _save_window_state(self) -> None:
        settings.set("window_width", self.get_width())
        settings.set("window_height", self.get_height())
        settings.set("paned_position", self._paned.get_position())
        log.debug("Fensterzustand gespeichert: %dx%d, paned=%d",
                  self.get_width(), self.get_height(), self._paned.get_position())

    # ------------------------------------------------------------------
    # Sprachauswahl
    # ------------------------------------------------------------------

    def _build_lang_dropdown(self) -> Gtk.DropDown:
        self._lang_codes = SUPPORTED_LANGS[:]
        names = [LANG_NAMES.get(code, code) for code in self._lang_codes]

        current = get_current_lang()
        try:
            selected = self._lang_codes.index(current)
        except ValueError:
            selected = 0

        model = Gtk.StringList.new(names)
        drop = Gtk.DropDown.new(model, None)
        drop.set_valign(Gtk.Align.CENTER)
        drop.set_selected(selected)
        drop.connect("notify::selected", self._on_lang_changed)
        return drop

    def _on_lang_changed(self, dropdown: Gtk.DropDown, _param) -> None:
        idx = dropdown.get_selected()
        if idx >= len(self._lang_codes):
            return

        lang = self._lang_codes[idx]
        if lang == get_current_lang():
            return

        log.info("Sprache gewechselt → %s", lang)
        settings.set("language", lang)
        setup_i18n(lang)

        app = self.get_application()
        new_win = MainWindow(
            application=app,
            selected_printer=self._selected_printer_name,
        )
        new_win.present()
        self.close()

    # ------------------------------------------------------------------
    # Druckerliste
    # ------------------------------------------------------------------

    def _clear_list(self) -> None:
        while (child := self._list_box.get_first_child()) is not None:
            self._list_box.remove(child)

    def _load_printers(self) -> bool:
        self._error_banner.set_revealed(False)
        self._refresh_btn.set_sensitive(False)
        self._stack.set_visible_child_name("loading")

        def _fetch():
            try:
                printers = cups_client.get_printers()
                GLib.idle_add(self._on_printers_loaded, printers, None)
            except Exception as exc:
                GLib.idle_add(self._on_printers_loaded, [], exc)

        threading.Thread(target=_fetch, daemon=True).start()
        return GLib.SOURCE_REMOVE

    def _on_printers_loaded(
        self, printers: list, error: Exception | None
    ) -> bool:
        self._refresh_btn.set_sensitive(True)

        if error:
            self._error_banner.set_title(
                _("Verbindung zu CUPS fehlgeschlagen. Bitte prüfe ob der CUPS-Dienst läuft.")
            )
            self._error_banner.set_revealed(True)
            self._stack.set_visible_child_name("empty")
            self._detail.show_empty()
            log.error("CUPS-Fehler: %s", error)
            return GLib.SOURCE_REMOVE

        self._clear_list()

        if not printers:
            self._stack.set_visible_child_name("empty")
            self._detail.show_empty()
            log.info("Keine Drucker gefunden")
            return GLib.SOURCE_REMOVE

        selected = self._selected_printer_name
        for printer in printers:
            row = PrinterRow(printer)
            self._list_box.append(row)
            if printer.name == selected:
                self._list_box.select_row(row)

        self._stack.set_visible_child_name("list")
        log.info("Druckerliste aktualisiert: %d Drucker", len(printers))
        return GLib.SOURCE_REMOVE

    def _on_add_printer(self, _btn) -> None:
        AddPrinterDialog(on_printer_added=self._load_printers).present(self)

    def _on_printer_selected(self, _list_box: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            self._selected_printer_name = None
            self._detail.show_empty()
        else:
            self._selected_printer_name = row.printer.name
            self._detail.show_printer(row.printer, on_action=self._load_printers)
