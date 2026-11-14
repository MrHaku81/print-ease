APP_ID      = "at.printease.PrintEase"
APP_NAME    = "PrintEase"
APP_VERSION = "0.2.2"
CUPS_HOST   = "localhost"
CUPS_PORT   = 631
LOG_FILE    = "dev.log"   # relativ zum Projektverzeichnis während Entwicklung

# Netzwerk-Timeouts (Sekunden)
AVAHI_TIMEOUT = 5    # avahi-browse Wartezeit
AVAHI_RESOLVE_TIMEOUT = 2    # avahi-resolve-host-name Wartezeit
ESCL_TIMEOUT  = 3    # eSCL HTTP-Anfragen (Status, Capabilities)
SCANNER_SEARCH_TIMEOUT = 5   # gesamte Scanner-Suche für einen Drucker
# mDNS-Suchfenster innerhalb der Scanner-Suche (eSCL-Dienste und Drucker-IPs).
# Der zeroconf-Weg (Flatpak) wartet das Fenster immer ganz ab; gemessen kamen
# mit QM-Fragen alle Namen nach <= 1,9 s. avahi-browse endet meist früher.
SCANNER_MDNS_WINDOW = 3
CUPS_TIMEOUT  = 10   # CUPS-Verbindungsaufbau / ScanJob-Erstellung
# eSCL NextDocument: Das Gerät antwortet erst, wenn die Seite fertig gescannt ist.
# Gemessen am Ricoh: leerer Flachbett-Scan mit 600 dpi in Farbe dauert 12,6 s.
# Mit Inhalt dauert es länger, ein 600-dpi-Farblauf brach an den früheren 15 s ab.
NEXT_DOCUMENT_TIMEOUT = 60
