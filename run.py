import threading
import webbrowser

from app import create_app
from app.config import PORT
from app.network import get_lan_ip

if __name__ == "__main__":
    app = create_app()
    ip = get_lan_ip()
    print(f"Dashboard: http://{ip}:{PORT}/dashboard")
    print(f"Organizer: http://{ip}:{PORT}/organizer")
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}/")).start()
    app.run(host="0.0.0.0", port=PORT)
