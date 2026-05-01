from print_ease._i18n import setup_i18n, get_current_lang
setup_i18n(get_current_lang())

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk

from print_ease.constants import APP_ID, APP_NAME, APP_VERSION
from print_ease.gui.window import MainWindow
from print_ease._log import get_logger

log = get_logger(__name__)


def main():
    log.info("PrintEase startet")
    app = Adw.Application(application_id=APP_ID)
    app.connect("startup", _on_startup)
    app.connect("activate", lambda a: MainWindow(application=a).present())
    app.run()


def _on_startup(app: Adw.Application) -> None:
    # TEIL 7: Adwaita soll das Farbschema selbst verwalten
    # (unterdrückt die gtk-application-prefer-dark-theme Warnung)
    Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.DEFAULT)
    _setup_actions(app)


def _setup_actions(app: Adw.Application) -> None:
    from print_ease._i18n import _

    about_action = Gio.SimpleAction.new("about", None)
    about_action.connect("activate", lambda *_: _show_about(app))
    app.add_action(about_action)

    shortcuts_action = Gio.SimpleAction.new("shortcuts", None)
    shortcuts_action.connect("activate", lambda *_: _show_shortcuts(app))
    app.add_action(shortcuts_action)

    quit_action = Gio.SimpleAction.new("quit", None)
    quit_action.connect("activate", lambda *_: app.quit())
    app.add_action(quit_action)
    app.set_accels_for_action("app.quit", ["<Control>q"])


def _show_about(app: Adw.Application) -> None:
    from print_ease._i18n import _

    dialog = Adw.AboutDialog()
    dialog.set_application_name(APP_NAME)
    dialog.set_application_icon("printer-symbolic")
    dialog.set_version(APP_VERSION)
    dialog.set_comments(_(
        "Universelle Linux-Druckerverwaltung —\n"
        "ein moderner Ersatz für system-config-printer."
    ))
    dialog.set_website("https://github.com/MrHaku81/print-ease")
    dialog.set_issue_url("https://github.com/MrHaku81/print-ease/issues")
    dialog.set_license_type(Gtk.License.GPL_3_0)
    dialog.set_copyright("© 2026 MrHaku81")
    dialog.set_developers(["MrHaku81 <haku81.kk@gmail.com>"])

    translator_credits = _("translator-credits")
    if translator_credits != "translator-credits":
        dialog.set_translator_credits(translator_credits)

    dialog.present(app.get_active_window())
    log.info("About-Dialog geöffnet")


def _show_shortcuts(app: Adw.Application) -> None:
    from print_ease._i18n import _

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<interface>
  <object class="GtkShortcutsWindow" id="shortcuts">
    <property name="modal">1</property>
    <child>
      <object class="GtkShortcutsSection">
        <property name="section-name">shortcuts</property>
        <child>
          <object class="GtkShortcutsGroup">
            <property name="title">PrintEase</property>
            <child>
              <object class="GtkShortcutsShortcut">
                <property name="title">{_("Drucker aktualisieren")}</property>
                <property name="accelerator">&lt;ctrl&gt;r F5</property>
              </object>
            </child>
            <child>
              <object class="GtkShortcutsShortcut">
                <property name="title">{_("Drucker hinzufügen")}</property>
                <property name="accelerator">&lt;ctrl&gt;n</property>
              </object>
            </child>
            <child>
              <object class="GtkShortcutsShortcut">
                <property name="title">{_("Beenden")}</property>
                <property name="accelerator">&lt;ctrl&gt;q</property>
              </object>
            </child>
          </object>
        </child>
      </object>
    </child>
  </object>
</interface>"""

    builder = Gtk.Builder.new_from_string(xml, -1)
    shortcuts_win = builder.get_object("shortcuts")
    shortcuts_win.set_transient_for(app.get_active_window())
    shortcuts_win.present()
    log.info("Tastaturkürzel-Dialog geöffnet")


if __name__ == "__main__":
    main()
