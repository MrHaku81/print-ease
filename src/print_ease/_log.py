import logging
import logging.handlers
from pathlib import Path


def _get_log_path() -> Path:
    """XDG-konformer Log-Pfad: ~/.local/share/print-ease/print-ease.log"""
    try:
        from gi.repository import GLib
        data_dir = Path(GLib.get_user_data_dir()) / "print-ease"
    except Exception:
        data_dir = Path.home() / ".local" / "share" / "print-ease"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "print-ease.log"


def _setup_logging() -> None:
    root = logging.getLogger("print_ease")
    if root.handlers:
        return

    root.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    root.addHandler(console)

    fh = logging.handlers.RotatingFileHandler(
        _get_log_path(), maxBytes=5 * 1024 * 1024, backupCount=3,
        encoding="utf-8", mode="a",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Dev-Log im Projektverzeichnis (nur wenn vorhanden)
    dev_log = Path(__file__).resolve().parent.parent.parent / "dev.log"
    if dev_log.exists():
        dh = logging.FileHandler(dev_log, encoding="utf-8", mode="a")
        dh.setLevel(logging.DEBUG)
        dh.setFormatter(fmt)
        root.addHandler(dh)


_setup_logging()


def get_logger(name: str) -> logging.Logger:
    if name.startswith("print_ease"):
        return logging.getLogger(name)
    return logging.getLogger(f"print_ease.{name}")
