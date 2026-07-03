from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for

from app.config import PORT
from app.db import get_db
from app.network import get_hostname, get_lan_ip, make_qr_png_bytes
from app.persistence import delete_save, list_saves, load_save, new_tournament, save_current

bp = Blueprint("setup", __name__)


def _base_url(host):
    return f"http://{host}" if PORT == 80 else f"http://{host}:{PORT}"


@bp.route("/")
def landing():
    ip = get_lan_ip()
    db = get_db()
    state = db.execute("SELECT phase FROM tournament_state WHERE id = 1").fetchone()
    player_count = db.execute("SELECT COUNT(*) AS c FROM players").fetchone()["c"]
    return render_template(
        "index.html",
        alias_url=_base_url(get_hostname()),
        dashboard_url=f"{_base_url(ip)}/dashboard",
        phase=state["phase"],
        player_count=player_count,
        saves=list_saves(),
    )


@bp.route("/qr.png")
def qr_png():
    # The QR encodes the raw IP -- it always works even if name resolution
    # doesn't, and nobody has to type it anyway.
    buf = make_qr_png_bytes(f"{_base_url(get_lan_ip())}/dashboard")
    return send_file(buf, mimetype="image/png")


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
