% PRINT-EASE(1) print-ease 0.1.3 | User Commands
% MrHaku81
% May 2026

# NAME

print-ease - universal Linux printer and scanner management

# SYNOPSIS

**print-ease**

# DESCRIPTION

**print-ease** is a modern GTK4 application for managing printers and
scanners on Linux desktops. It auto-detects compatible network devices
via mDNS/Avahi and works with any IPP Everywhere or AirPrint capable
printer without requiring vendor-specific drivers.

The application provides a graphical interface to add, remove, and
configure printers via CUPS, and to scan documents from networked
scanners using the eSCL/AirScan protocol.

# OPTIONS

**print-ease** does not accept command-line options. All configuration
is done through the graphical interface.

# FILES

*~/.config/print-ease/*
:   User-specific configuration directory.

*/usr/share/applications/at.printease.PrintEase.desktop*
:   Desktop entry installed by the package.

# ENVIRONMENT

**LANG**, **LC_ALL**
:   Standard locale variables; PrintEase uses them to select among 33
    available translations.

# SEE ALSO

**cups**(1), **cupsd**(8), **avahi-daemon**(8), **system-config-printer**(1)

# BUGS

Bug reports and feature requests are tracked on GitHub:
<https://github.com/MrHaku81/print-ease/issues>

# AUTHOR

MrHaku81 <haku81.kk@gmail.com>

# LICENSE

PrintEase is licensed under the GNU General Public License, version 3
or later. See */usr/share/common-licenses/GPL-3* for the full text.
