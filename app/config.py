import os
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


def get_app_version():
    """Release tag stamped into the build by CI (version.txt); 'dev' otherwise."""
    try:
        with open(os.path.join(get_resource_dir(), "version.txt"), encoding="utf-8") as f:
            return f.read().strip() or "dev"
    except OSError:
        return "dev"


DB_PATH = os.path.join(get_data_dir(), "tournament.db")
SCHEMA_PATH = os.path.join(get_resource_dir(), "schema.sql")
PORT = 5000
APP_VERSION = get_app_version()
