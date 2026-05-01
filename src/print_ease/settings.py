"""Persistente Einstellungen (~/.config/print-ease/settings.json)."""
from __future__ import annotations

import json
from pathlib import Path


class _Settings:
    def __init__(self) -> None:
        self._path = Path.home() / ".config" / "print-ease" / "settings.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict | None = None

    def _load(self) -> dict:
        if self._cache is not None:
            return self._cache
        try:
            self._cache = json.loads(self._path.read_text(encoding="utf-8"))
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
