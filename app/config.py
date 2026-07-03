import os
import socket
import sys


def get_base_dir():
    """Directory the app's writable data lives next to.

    When frozen by PyInstaller, sys._MEIPASS is a read-only temp extraction
    dir for bundled resources (templates, schema.sql) -- never use it for
    the live database, or it gets wiped every run. Use the exe's own
    directory instead, which persists across runs.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_resource_dir():
    """Directory bundled read-only resources (templates, schema.sql) live in."""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def get_data_dir():
    data_dir = os.path.join(get_base_dir(), "data")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def _pick_port():
    """Prefer port 80 so joining is just http://<name> with no port to type.

    A PORT env var pins it explicitly (used by dev tooling); if 80 is taken
    or blocked, fall back to 5000.
    """
    env = os.environ.get("PORT")
    if env:
        return int(env)
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("0.0.0.0", 80))
        probe.close()
        return 80
    except OSError:
        return 5000


DB_PATH = os.path.join(get_data_dir(), "tournament.db")
SCHEMA_PATH = os.path.join(get_resource_dir(), "schema.sql")
PORT = _pick_port()
