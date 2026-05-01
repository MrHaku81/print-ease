import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango

from print_ease._i18n import _
from print_ease.printer_model import PrinterInfo


class PrinterRow(Gtk.ListBoxRow):
    """Stellt einen einzelnen Drucker in der Druckerliste dar."""

    def __init__(self, printer: PrinterInfo):
        super().__init__()
        self.printer = printer

        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        outer.set_margin_start(12)
        outer.set_margin_end(12)
        self.set_child(outer)

        is_network = any(printer.uri.startswith(p) for p in ("ipp://", "ipps://", "socket://"))
        icon_name = "printer-network-symbolic" if is_network else "printer-symbolic"
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_icon_size(Gtk.IconSize.LARGE)
        icon.set_valign(Gtk.Align.CENTER)
        outer.append(icon)

        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info_box.set_valign(Gtk.Align.CENTER)
        info_box.set_hexpand(True)
        outer.append(info_box)

        name_label = Gtk.Label(label=printer.name)
        name_label.set_halign(Gtk.Align.START)
        name_label.set_ellipsize(Pango.EllipsizeMode.END)
        name_label.add_css_class("heading")
        info_box.append(name_label)

        status_text, css_color = _state_display(printer)
        status_label = Gtk.Label(label=status_text)
        status_label.set_halign(Gtk.Align.START)
        status_label.set_ellipsize(Pango.EllipsizeMode.END)
        status_label.add_css_class("caption")
        status_label.add_css_class(css_color)
        info_box.append(status_label)

        if printer.is_default:
            badge = Gtk.Button(label=_("Standard"))
            badge.set_valign(Gtk.Align.CENTER)
            badge.add_css_class("suggested-action")
            badge.add_css_class("pill")
            badge.set_can_target(False)
            badge.set_focusable(False)
            badge.set_margin_start(4)
            outer.append(badge)


def _state_display(printer: PrinterInfo) -> tuple[str, str]:
    match printer.state:
        case "idle":
            return _("Bereit"), "success"
        case "processing":
            return _("Druckt…"), "accent"
        case "stopped":
            return _("Gestoppt"), "error"
        case _:
            text = printer.state_message or printer.state
            return text, "dim-label"
