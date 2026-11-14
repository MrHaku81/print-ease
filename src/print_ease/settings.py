"""Persistente Einstellungen (<XDG_CONFIG_HOME>/print-ease/settings.json).

Ohne gesetztes XDG_CONFIG_HOME ist das wie bisher ~/.config/print-ease/.
Im Flatpak setzt die Laufzeit XDG_CONFIG_HOME auf
~/.var/app/at.printease.PrintEase/config — dort überleben die Einstellungen
einen Neustart, ~/.config in der Sandbox dagegen nicht.
"""
from __future__ import annotations

import json
from pathlib import Path


def _config_dir() -> Path:
    try:
        from gi.repository import GLib
        config = GLib.get_user_config_dir()
        if isinstance(config, str) and config:
            return Path(config)
    except Exception:
        pass
    return Path.home() / ".config"


def _settings_path() -> Path:
    return _config_dir() / "print-ease" / "settings.json"


# Ort bis 0.2.1. Nur relevant, wenn XDG_CONFIG_HOME auf einen anderen Ordner
# zeigt: Dann wird die alte Datei gelesen, bis zum ersten Speichern am neuen Ort.
_LEGACY_PATH = Path.home() / ".config" / "print-ease" / "settings.json"


class _Settings:
    def __init__(self) -> None:
        self._path = _settings_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict | None = None

    def _source(self) -> Path:
        if not self._path.exists() and _LEGACY_PATH != self._path and _LEGACY_PATH.is_file():
            return _LEGACY_PATH
        return self._path

    def _load(self) -> dict:
        if self._cache is not None:
            return self._cache
        try:
            self._cache = json.loads(self._source().read_text(encoding="utf-8"))
        except Exception:
            self._cache = {}
        return self._cache

    def _save(self) -> None:
        if self._cache is not None:
            self._path.write_text(
                json.dumps(self._cache, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    def get(self, key: str, default=None):
        return self._load().get(key, default)

    def set_value(self, key: str, value) -> None:
        data = self._load()
        data[key] = value
        self._cache = data
        self._save()


_store = _Settings()
get = _store.get
set = _store.set_value  # Alias: Aufrufer bleiben unverändert
