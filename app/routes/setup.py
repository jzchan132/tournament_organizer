import re

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from app.config import PORT
from app.db import get_db
from app.network import get_lan_ip, make_qr_png_bytes
from app.persistence import delete_save, list_saves, load_save, new_tournament, save_current

bp = Blueprint("setup", __name__)


def _port():
    # run.py records the actual serving port (it can differ from the default
    # when launched with --port); fall back to the config constant otherwise.
    return current_app.config.get("APP_PORT", PORT)


@bp.route("/")
def landing():
    ip = get_lan_ip()
    dashboard_url = f"http://{ip}:{_port()}/dashboard"
    db = get_db()
    state = db.execute("SELECT phase FROM tournament_state WHERE id = 1").fetchone()
    player_count = db.execute("SELECT COUNT(*) AS c FROM players").fetchone()["c"]
    return render_template(
        "index.html",
        ip=ip,
        port=_port(),
        dashboard_url=dashboard_url,
        phase=state["phase"],
        player_count=player_count,
        saves=list_saves(),
    )


@bp.route("/qr.png")
def qr_png():
    ip = get_lan_ip()
    url = f"http://{ip}:{_port()}/dashboard"
    buf = make_qr_png_bytes(url)
    return send_file(buf, mimetype="image/png")


@bp.route("/api/sessions")
def api_sessions():
    prober = current_app.extensions.get("session_prober")
    return jsonify(prober.sessions() if prober else [])


@bp.route("/session/join", methods=["POST"])
def session_join():
    url = request.form.get("url", "")
    if not re.fullmatch(r"http://\d{1,3}(\.\d{1,3}){3}:\d{1,5}", url):
        flash("That session address doesn't look right.")
        return redirect(url_for("setup.landing"))
    responder = current_app.extensions.get("discovery_responder")
    if responder:
        # Joining someone else's session -- stop advertising our own so it
        # disappears from other lobbies.
        responder.stop_advertising()
    return redirect(f"{url}/dashboard")


@bp.route("/tournament/new", methods=["POST"])
def tournament_new():
    archive = new_tournament()
    flash(f"New tournament started. The previous state was archived as {archive}.")
    return redirect(url_for("organizer.index"))


@bp.route("/tournament/save", methods=["POST"])
def tournament_save():
    filename = save_current(request.form.get("name", ""))
    flash(f"Tournament saved as {filename}.")
    return redirect(url_for("setup.landing"))


@bp.route("/tournament/delete", methods=["POST"])
def tournament_delete():
    error = delete_save(request.form.get("filename", ""))
    flash(error or "Save deleted.")
    return redirect(url_for("setup.landing"))


@bp.route("/tournament/load", methods=["POST"])
def tournament_load():
    error = load_save(request.form.get("filename", ""))
    if error:
        flash(error)
        return redirect(url_for("setup.landing"))
    flash("Save loaded.")
    return redirect(url_for("dashboard.dashboard"))
