from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PrinterInfo:
    name: str
    description: str
    location: str
    is_default: bool
    is_shared: bool
    state: str          # "idle", "processing", "stopped"
    state_message: str
    uri: str


@dataclass
class PrintJob:
    job_id: int
    printer_name: str
    title: str
    state: str
    user: str


@dataclass
class ScannerInfo:
    name: str               # Anzeigename (MakeAndModel aus eSCL)
    host: str               # Hostname oder IP
    port: int               # HTTP-Port
    escl_url: str           # Basis-URL (z.B. http://192.168.0.116/eSCL)
    make_model: str         # Hersteller + Modell
    max_width: int          # Max. Breite in eSCL-Einheiten (1/300 Zoll)
    max_height: int         # Max. Höhe in eSCL-Einheiten
    color_modes: list[str]  # ["RGB24", "Grayscale8", "BlackAndWhite1"]
    resolutions: list[int]  # [75, 150, 300, 600]
    document_sources: list[str]   # ["Platen", "AdfSimplex"]
    linked_printer: str | None    # Name des verknüpften CUPS-Druckers
    detect_paper_loaded: bool = False  # AdfOption DetectPaperLoaded unterstützt


@dataclass
class NetworkPrinter:
    name: str           # Anzeigename aus TXT-Record "ty" (z.B. "Canon TS700 series")
    host: str           # mDNS-Hostname (z.B. "E1F4F9000000.local")
    address: str        # IP-Adresse (z.B. "192.168.0.190")
    port: int           # Port (meist 631)
    uri: str            # Fertige IPP-URI (ipp://host:port/rp)
    service_type: str   # "_ipp._tcp" oder "_ipps._tcp"
    txt_records: dict   # TXT-Records: rp, ty, adminurl, Color, Duplex, ...
