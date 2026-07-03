import os
import sys

# Pin the port before app.config resolves it (dev tooling passes --port).
if "--port" in sys.argv:
    os.environ["PORT"] = sys.argv[sys.argv.index("--port") + 1]

import threading
import webbrowser

from app import create_app
from app.config import PORT
from app.network import get_hostname, get_lan_ip

if __name__ == "__main__":
    app = create_app()
    ip = get_lan_ip()
    suffix = "" if PORT == 80 else f":{PORT}"
    print(f"Join (easy):  http://{get_hostname()}{suffix}/dashboard")
    print(f"Join (IP):    http://{ip}{suffix}/dashboard")
    print(f"Organizer:    http://{ip}{suffix}/organizer")
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1{suffix}/")).start()
    app.run(host="0.0.0.0", port=PORT)
