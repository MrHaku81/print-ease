"""PWG-Medien-Namen-Mapping für lesbare Anzeige in der UI.

CUPS und IPP nutzen PWG-Namen wie 'iso_a4_210x297mm'. Dieses Mapping
übersetzt sie in für Endnutzer verständliche Bezeichnungen.

Bei nicht gemappten Namen wird in get_media_display_name der Roh-String
zurückgegeben — die App bleibt also funktional, auch wenn ein Drucker
einen ungewöhnlichen Format-Namen meldet.
"""

from print_ease._i18n import _

def _pwg_media_names() -> dict[str, str]:
    return {
        # ISO A-Serie (sprachneutral)
        "iso_a4_210x297mm": "A4",
        "iso_a5_148x210mm": "A5",
        "iso_a6_105x148mm": "A6",
        # B-Serie
        "jis_b5_182x257mm": "B5 (JIS)",
        "iso_b5_176x250mm": "B5 (ISO)",
        # US-Standardformate
        "na_letter_8.5x11in": "Letter",
        "na_legal_8.5x14in": "Legal",
        "na_executive_7.25x10.5in": "Executive",
        "na_invoice_5.5x8.5in": "Invoice",
        "na_foolscap_8.5x13in": "Foolscap",
        "na_oficio_8.5x13.4in": "Oficio",
        # Umschläge
        "iso_dl_110x220mm": f"DL {_('Umschlag')}",
        "iso_c5_162x229mm": f"C5 {_('Umschlag')}",
        "na_number-10_4.125x9.5in": f"#10 {_('Umschlag')}",
        "na_number-9_3.875x8.875in": f"#9 {_('Umschlag')}",
        "na_monarch_3.875x7.5in": f"Monarch {_('Umschlag')}",
        # Foto-Formate
        "na_index-4x6_4x6in": f"{_('Foto')} 4×6 {_('Zoll')}",
        "oe_photo-l_3.5x5in": f"{_('Foto')} 3,5×5 {_('Zoll')}",
        "na_5x7_5x7in": f"{_('Foto')} 5×7 {_('Zoll')}",
        "oe_square-photo_4x4in": f"{_('Foto')} {_('Quadrat')} 4×4",
        "oe_square-photo_5x5in": f"{_('Foto')} {_('Quadrat')} 5×5",
        # Postkarten
        "jpn_hagaki_100x148mm": f"Hagaki {_('Postkarte')}",
        # Custom-Marker (vom Drucker als „eigene Größe" gemeldet)
        "custom_min": f"{_('Benutzerdefiniert')} (min.)",
        "custom_max": f"{_('Benutzerdefiniert')} (max.)",
    }


def get_media_display_name(pwg_name: str) -> str:
    """Mappt einen PWG-Medien-Namen auf einen lesbaren String.

    Bei custom_*-Namen mit Größenangabe (z.B. "custom_min_55x89mm")
    wird die Größe in Klammern angehängt.
    Bei nicht gemappten Namen wird der Roh-String zurückgegeben.
    """
    names = _pwg_media_names()
    if pwg_name in names:
        return names[pwg_name]

    # Custom-Formate mit Größe haben Form "custom_min_55x89mm" oder
    # "custom_max_215.9x676mm" oder "custom_120x120mm_120x120mm"
    if pwg_name.startswith("custom_"):
        parts = pwg_name.split("_")
        if len(parts) >= 3:
            size = parts[-1]  # letzte Komponente ist die Größe
            return f"{_('Benutzerdefiniert')} ({size})"

    return pwg_name
