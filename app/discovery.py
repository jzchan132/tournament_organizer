"""LAN session discovery -- lets a second laptop find this one like a LAN game.

Protocol: single JSON datagrams on UDP port 50505.
- A prober broadcasts {"app": "tekken-to", "type": "probe", "v": 1, ...}
- Hosts reply unicast with {"type": "session", "name": ..., "port": ..., ...}

The reply datagram's SOURCE ADDRESS is the host's reachable IP -- the "ip"
field inside the JSON is advisory only (a host can't reliably know which of
its interfaces the client can reach).

Every process carries a random instance id so it can ignore its own
broadcasts, which Windows loops back to local listeners.
"""

import json
import secrets
import select
import socket
import sqlite3
import threading
import time
import uuid

from app import db as db_module

DISCOVERY_PORT = 50505
APP_TAG = "tekken-to"
PROTOCOL_VERSION = 1
MAX_DATAGRAM = 1024


def build_probe(token, instance):
    return json.dumps(
        {"app": APP_TAG, "type": "probe", "v": PROTOCOL_VERSION, "token": token,
         "instance": instance}
    ).encode("utf-8")


def build_session_response(token, instance, name, ip, port, phase, players):
    return json.dumps(
        {"app": APP_TAG, "type": "session", "v": PROTOCOL_VERSION, "token": token,
         "instance": instance, "name": name, "ip": ip, "port": port,
         "phase": phase, "players": players}
    ).encode("utf-8")


def parse_message(data, expected_type):
    """Decode and validate a datagram; returns the dict or None if invalid."""
    if len(data) > MAX_DATAGRAM:
        return None
    try:
        msg = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(msg, dict):
        return None
    if msg.get("app") != APP_TAG or msg.get("v") != PROTOCOL_VERSION:
        return None
    if msg.get("type") != expected_type:
        return None
    return msg


def _session_status():
    """Phase and player count for advertising. Opens its own connection --
    this runs on the responder thread, which has no Flask request context."""
    try:
        conn = sqlite3.connect(db_module.DB_PATH)
        try:
            phase = conn.execute(
                "SELECT phase FROM tournament_state WHERE id = 1"
            ).fetchone()
            players = conn.execute("SELECT COUNT(*) FROM players").fetchone()
        finally:
            conn.close()
        return (phase[0] if phase else "setup"), (players[0] if players else 0)
    except sqlite3.Error:
        return "setup", 0


def _local_ipv4_addresses():
    addrs = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addrs.add(info[4][0])
    except OSError:
        pass
    return addrs


class DiscoveryResponder(threading.Thread):
    """Answers discovery probes while this app is hosting a session."""

    def __init__(self, http_port):
        super().__init__(daemon=True, name="discovery-responder")
        self.http_port = http_port
        self.instance = str(uuid.uuid4())
        self._advertising = threading.Event()
        self._advertising.set()
        self._stopped = threading.Event()

    @property
    def advertising(self):
        return self._advertising.is_set()

    def stop_advertising(self):
        self._advertising.clear()

    def start_advertising(self):
        self._advertising.set()

    def stop(self, *_args):
        self._stopped.set()

    def run(self):
        from app.network import get_lan_ip

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", DISCOVERY_PORT))
            sock.settimeout(1.0)
        except OSError:
            return  # port unavailable; hosting still works, just not discoverable

        hostname = socket.gethostname().split(".")[0]
        while not self._stopped.is_set():
            try:
                data, addr = sock.recvfrom(MAX_DATAGRAM)
            except socket.timeout:
                continue
            except OSError:
                break
            if not self._advertising.is_set():
                continue
            probe = parse_message(data, "probe")
            if not probe or probe.get("instance") == self.instance:
                continue
            phase, players = _session_status()
            response = build_session_response(
                token=probe.get("token", ""),
                instance=self.instance,
                name=hostname,
                ip=get_lan_ip(),
                port=self.http_port,
                phase=phase,
                players=players,
            )
            try:
                sock.sendto(response, addr)
            except OSError:
                continue
        sock.close()


class SessionProber(threading.Thread):
    """Broadcasts probes and keeps a short-lived cache of sessions heard."""

    PROBE_INTERVAL = 3.0
    SESSION_TTL = 10.0

    def __init__(self, own_instance):
        super().__init__(daemon=True, name="session-prober")
        self.own_instance = own_instance
        self._stopped = threading.Event()
        self._lock = threading.Lock()
        self._sessions = {}  # host ip -> {session fields, "seen": monotonic}

    def stop(self, *_args):
        self._stopped.set()

    def sessions(self):
        """Currently-known sessions, freshest data, stale entries dropped."""
        now = time.monotonic()
        with self._lock:
            self._sessions = {
                ip: s for ip, s in self._sessions.items()
                if now - s["seen"] <= self.SESSION_TTL
            }
            return [
                {"name": s["name"], "ip": ip, "port": s["port"],
                 "phase": s["phase"], "players": s["players"],
                 "url": f"http://{ip}:{s['port']}"}
                for ip, s in sorted(self._sessions.items())
            ]

    def record_response(self, msg, source_ip):
        """Validate + store one session response. Pure enough to unit test."""
        if msg.get("instance") == self.own_instance:
            return False
        port = msg.get("port")
        if not isinstance(port, int) or not (0 < port < 65536):
            return False
        with self._lock:
            self._sessions[source_ip] = {
                "name": str(msg.get("name", source_ip)),
                "port": port,
                "phase": str(msg.get("phase", "?")),
                "players": msg.get("players", 0),
                "seen": time.monotonic(),
            }
        return True

    def _make_sockets(self):
        """One long-lived socket per local IPv4 (so the limited broadcast
        leaves every interface -- Windows routes it out just one otherwise),
        plus an unbound fallback. Replies come back to these same sockets,
        so they must stay open between probe cycles."""
        socks = []
        for local_ip in _local_ipv4_addresses():
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.bind((local_ip, 0))
                s.setblocking(False)
                socks.append(s)
            except OSError:
                continue
        try:
            fallback = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            fallback.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            fallback.setblocking(False)
            socks.append(fallback)
        except OSError:
            pass
        return socks

    def _send_probe(self, socks, token):
        probe = build_probe(token, self.own_instance)
        for s in socks:
            try:
                s.sendto(probe, ("255.255.255.255", DISCOVERY_PORT))
            except OSError:
                continue

    def run(self):
        socks = self._make_sockets()
        if not socks:
            return

        last_probe = 0.0
        while not self._stopped.is_set():
            now = time.monotonic()
            if now - last_probe >= self.PROBE_INTERVAL:
                self._send_probe(socks, secrets.token_hex(4))
                last_probe = now
            try:
                readable, _, _ = select.select(socks, [], [], 0.5)
            except OSError:
                break
            for s in readable:
                try:
                    data, addr = s.recvfrom(MAX_DATAGRAM)
                except OSError:
                    continue
                msg = parse_message(data, "session")
                if msg:
                    self.record_response(msg, addr[0])
        for s in socks:
            s.close()
