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
  - Multi-page ADF scan (with ADF paper detection before scan)
  - Multi-page flatbed: PDF documents and TIFF archives
  - Duplex: hardware (BETA, scanner-dependent) and software (two-pass)
  - Separate Source and Duplex selectors + Mode dropdown
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

### Flatpak (any distro)

A pre-built bundle that runs on any distribution, with CUPS printing and eSCL scanning included. Download `print-ease.flatpak` from the [latest release](https://github.com/MrHaku81/print-ease/releases/latest), then:

```bash
flatpak install flathub org.gnome.Platform//47
flatpak install --user ./print-ease.flatpak
flatpak run at.printease.PrintEase
```

### Ubuntu / Mint / Pop!_OS / Zorin / Elementary (PPA)

PrintEase is available via [Launchpad PPA](https://launchpad.net/~haku81/+archive/ubuntu/printease).
Supported: Ubuntu 24.04 LTS (noble) and 26.04 LTS (resolute), plus their derivates —
Mint 22.x, Pop!_OS 24.04, Zorin 18.x, Elementary 8.

```bash
sudo add-apt-repository ppa:haku81/printease
sudo apt update
sudo apt install print-ease
```

### Arch Linux / CachyOS / Manjaro (AUR)

PrintEase is available in the [Arch User Repository](https://aur.archlinux.org/packages/print-ease).

Using an AUR helper:

```bash
yay -S print-ease
# or
paru -S print-ease
```

Or manually with makepkg:

```bash
git clone https://aur.archlinux.org/print-ease.git
cd print-ease
makepkg -si
```

### From source (other distros, development)

For contributing, testing unreleased code, or running on distros without a packaged build:

```bash
git clone https://github.com/MrHaku81/print-ease.git
cd print-ease

# Set up a virtual environment
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Compile translations
make mo

# Run from source
print-ease
```

---

## What Gets Installed

After installation, PrintEase integrates fully with your desktop:

- **Application menu entry** — appears in GNOME, KDE Plasma, XFCE, and
  any FreeDesktop-compliant environment
- **Desktop icon** in the hicolor theme (scalable SVG)
- **`print-ease` command** in your PATH for terminal launch
- **Translations** for 33 languages (auto-selected based on your locale)
- **Reverse-DNS desktop entry** (`at.printease.PrintEase.desktop`)

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
