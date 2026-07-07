import os

from flask import Flask

from app import db
from app.config import get_resource_dir


def create_app():
    base_path = get_resource_dir()
    app = Flask(
        __name__,
        template_folder=os.path.join(base_path, "templates"),
        static_folder=os.path.join(base_path, "static"),
    )

    app.secret_key = "tekken-tournament-organizer"

    # Display names for internal phase values ('phase2' predates the Gauntlet).
    app.jinja_env.globals["phase_label"] = lambda phase: {
        "setup": "Phase 1",
        "phase2": "Gauntlet",
        "complete": "Complete",
    }.get(phase, phase)

    db.register(app)

    from app.persistence import autosave_after_request

    app.after_request(autosave_after_request)

    from app.routes.setup import bp as setup_bp
    from app.routes.organizer import bp as organizer_bp
    from app.routes.dashboard import bp as dashboard_bp

    app.register_blueprint(setup_bp)
    app.register_blueprint(organizer_bp)
    app.register_blueprint(dashboard_bp)

    return app
