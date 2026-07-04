import argparse
import os
import socket
import sys
import threading
import time
import webbrowser


def parse_args():
    parser = argparse.ArgumentParser(description="Tekken Tournament Organizer")
    parser.add_argument(
        "--no-window",
        action="store_true",
        help="Run headless (no desktop window); prints URLs like a plain server.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="HTTP port to serve on (default 5000).",
    )
    return parser.parse_args()


def setup_frozen_logging(data_dir):
    """In a windowed (console=False) frozen app, stdout/stderr are None and
    werkzeug's request logging would crash on the first request. Send both
    to a log file instead."""
    if getattr(sys, "frozen", False) and (sys.stdout is None or sys.stderr is None):
        log = open(os.path.join(data_dir, "app.log"), "a", buffering=1, encoding="utf-8")
        sys.stdout = log
        sys.stderr = log


def wait_for_port(host, port, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.25):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def main():
    args = parse_args()

    from app import create_app
    from app.config import get_data_dir
    from app.discovery import DiscoveryResponder, SessionProber
    from app.network import get_lan_ip

    setup_frozen_logging(get_data_dir())

    app = create_app()
    app.config["APP_PORT"] = args.port

    responder = DiscoveryResponder(http_port=args.port)
    responder.start()
    prober = SessionProber(own_instance=responder.instance)
    prober.start()
    app.extensions["discovery_responder"] = responder
    app.extensions["session_prober"] = prober

    flask_thread = threading.Thread(
        target=lambda: app.run(
            host="0.0.0.0", port=args.port, use_reloader=False, threaded=True
        ),
        daemon=True,
    )
    flask_thread.start()
    if not wait_for_port("127.0.0.1", args.port):
        print(f"Server failed to start on port {args.port} -- is it already in use?")
        sys.exit(1)

    ip = get_lan_ip()
    local_url = f"http://127.0.0.1:{args.port}/"
    print(f"Hosting session: http://{ip}:{args.port}/dashboard")
    print(f"Organizer:       http://{ip}:{args.port}/organizer")

    if args.no_window:
        try:
            flask_thread.join()
        except KeyboardInterrupt:
            pass
        responder.stop()
        return

    try:
        import webview  # lazy: pulls in pythonnet/clr, only needed for the window

        window = webview.create_window(
            "Tekken Tournament Organizer", local_url, width=1150, height=780
        )
        window.events.closed += responder.stop
        webview.start()
    except Exception as exc:  # WebView2 runtime missing, pythonnet failure, ...
        print(f"Desktop window unavailable ({exc!r}); falling back to the browser.")
        webbrowser.open(local_url)
        try:
            flask_thread.join()
        except KeyboardInterrupt:
            pass
    responder.stop()


if __name__ == "__main__":
    main()
