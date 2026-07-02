import io
import socket

import qrcode


def get_lan_ip():
    """Best-effort LAN IP of this machine.

    Uses a UDP "connect" to pick the routable interface -- no packets are
    actually sent, so this works fine even with no real internet access
    (e.g. a Windows Mobile Hotspot with nothing upstream).
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def make_qr_png_bytes(url):
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
