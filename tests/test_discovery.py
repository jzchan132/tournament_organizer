import json

from app.discovery import (
    APP_TAG,
    DiscoveryResponder,
    PROTOCOL_VERSION,
    SessionProber,
    build_probe,
    build_session_response,
    parse_message,
)


def test_probe_roundtrip():
    data = build_probe(token="abc123", instance="inst-1")
    msg = parse_message(data, "probe")
    assert msg is not None
    assert msg["token"] == "abc123"
    assert msg["instance"] == "inst-1"


def test_session_response_roundtrip():
    data = build_session_response(
        token="t", instance="i", name="GAMING-PC", ip="192.168.137.1",
        port=5000, phase="phase2", players=12,
    )
    msg = parse_message(data, "session")
    assert msg is not None
    assert msg["name"] == "GAMING-PC"
    assert msg["port"] == 5000
    assert msg["phase"] == "phase2"


def test_parse_rejects_garbage_and_foreign_messages():
    assert parse_message(b"not json", "probe") is None
    assert parse_message(b'"a string"', "probe") is None
    assert parse_message(b"{}", "probe") is None
    wrong_app = json.dumps({"app": "other", "type": "probe", "v": 1}).encode()
    assert parse_message(wrong_app, "probe") is None
    wrong_version = json.dumps({"app": APP_TAG, "type": "probe", "v": 99}).encode()
    assert parse_message(wrong_version, "probe") is None
    wrong_type = build_probe("t", "i")
    assert parse_message(wrong_type, "session") is None
    assert parse_message(b"x" * 2000, "probe") is None  # oversized


def test_prober_ignores_own_instance():
    prober = SessionProber(own_instance="me")
    msg = json.loads(build_session_response(
        token="t", instance="me", name="SELF", ip="10.0.0.1",
        port=5000, phase="setup", players=0,
    ))
    assert prober.record_response(msg, "10.0.0.1") is False
    assert prober.sessions() == []


def test_prober_records_and_reports_sessions():
    prober = SessionProber(own_instance="me")
    msg = json.loads(build_session_response(
        token="t", instance="other", name="HOST-PC", ip="192.168.137.1",
        port=5000, phase="phase1", players=8,
    ))
    assert prober.record_response(msg, "192.168.137.99") is True
    sessions = prober.sessions()
    assert len(sessions) == 1
    # the datagram source address wins over the advisory ip field
    assert sessions[0]["ip"] == "192.168.137.99"
    assert sessions[0]["url"] == "http://192.168.137.99:5000"
    assert sessions[0]["name"] == "HOST-PC"


def test_prober_rejects_invalid_port():
    prober = SessionProber(own_instance="me")
    msg = json.loads(build_session_response(
        token="t", instance="other", name="X", ip="1.2.3.4",
        port=5000, phase="setup", players=0,
    ))
    msg["port"] = "5000"  # strings are not acceptable
    assert prober.record_response(msg, "1.2.3.4") is False
    msg["port"] = 700000
    assert prober.record_response(msg, "1.2.3.4") is False


def test_prober_expires_stale_sessions(monkeypatch):
    prober = SessionProber(own_instance="me")
    msg = json.loads(build_session_response(
        token="t", instance="other", name="HOST", ip="1.2.3.4",
        port=5000, phase="setup", players=0,
    ))
    prober.record_response(msg, "1.2.3.4")
    assert len(prober.sessions()) == 1

    import app.discovery as discovery_module
    real_monotonic = discovery_module.time.monotonic
    monkeypatch.setattr(
        discovery_module.time, "monotonic", lambda: real_monotonic() + 60
    )
    assert prober.sessions() == []


def test_responder_advertising_toggle():
    responder = DiscoveryResponder(http_port=5000)
    assert responder.advertising
    responder.stop_advertising()
    assert not responder.advertising
    responder.start_advertising()
    assert responder.advertising


def test_protocol_version_constant():
    assert PROTOCOL_VERSION == 1
