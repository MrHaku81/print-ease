# PrintEase

*Find and use printers and scanners instantly — zero config required*

![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)
![GTK 4](https://img.shields.io/badge/GTK-4-green.svg)

> **Source:** https://github.com/MrHaku81/print-ease

---

## How It Works

PrintEase auto-detects compatible devices on your network — no manual
configuration needed for most modern printers and scanners.

**Printers**
- Network printers (AirPrint / IPP Everywhere) appear automatically via
  mDNS discovery
- USB printers detected via CUPS
- Driverless printing for any IPP-compatible device — no vendor drivers
  required

**Scanners**
- eSCL/AirScan-compatible scanners (most modern All-in-One devices)
  appear automatically
- Flatbed and ADF (Automatic Document Feeder) supported out of the box
- No SANE driver configuration required for compatible devices

Just turn on your device — PrintEase finds it within seconds.

---

## Features

- Add, remove, and configure printers via CUPS
- Network printer discovery via Avahi/mDNS
- Scanner / All-in-One support via eSCL (AirScan / IPP Everywhere)
  - Single-page flatbed and ADF scan
  - Multi-page ADF scan
  - Software duplex (two-pass ADF with PDF assembly)
  - ADF paper detection before scan
- Scan settings per device are remembered across sessions
- Manage active print jobs (view, cancel)
- Works on any desktop environment (GNOME, KDE, XFCE, …)
- Multilingual — 33 languages via GNU gettext

---

## Screenshots

---

## Supported languages

Arabic, Bulgarian, Czech, Danish, German, Greek, English, Spanish, Persian,
Finnish, French, Hebrew, Hindi, Croatian, Hungarian, Indonesian, Italian,
Japanese, Norwegian Bokmål, Dutch, Polish, Portuguese, Romanian, Russian,
Slovak, Serbian, Swedish, Thai, Turkish, Ukrainian, Vietnamese,
Chinese (Simplified), Chinese (Traditional)

---

## Requirements

| Dependency | Notes |
|---|---|
| Python 3.11+ | |
| GTK 4 + libadwaita | `python-gobject` |
| pycups | IPP / CUPS API |
| Avahi | `avahi-browse` must be in PATH |
| python-pillow | Optional — needed for duplex PDF assembly |

---

## Installation

```bash
# Clone
git clone https://github.com/MrHaku81/print-ease.git
cd print-ease

# Install in a virtual environment
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Compile translations
make mo

# Run
print-ease
```

---

## What Gets Installed

After installation (via AUR, Flatpak, or `make install`), PrintEase
integrates fully with your desktop:

- **Application menu entry** — appears in GNOME, KDE Plasma, XFCE, and
  any FreeDesktop-compliant environment
- **Desktop icon** in the hicolor theme (scalable SVG)
- **`print-ease` command** in your PATH for terminal launch
- **Translations** for 33 languages (auto-selected based on your locale)
- **Reverse-DNS desktop entry** (`at.printease.PrintEase.desktop`) —
  ready for Flatpak/Flathub

No system service installation required — PrintEase runs entirely as a
user application and uses existing CUPS and Avahi services.

---

## Tested hardware

| Device | Print | Scan (flatbed) | Scan (ADF) | Duplex ADF |
|---|---|---|---|---|
| Canon PIXMA TS705a | ✅ | — | — | — |
| Ricoh M C240FW | ✅ | ✅ | ✅ | ✅ |

---

## Tech stack

- Python 3.11+
- GTK4 + libadwaita
- pycups (CUPS IPP API)
- eSCL / AirScan (HTTP-based scanning)
- Avahi/mDNS (network discovery)
- GNU gettext (i18n)

---

## License

Copyright (C) 2026 MrHaku81

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version. See [LICENSE](LICENSE) for the full text.
