"""StudentHub application factory.

Gunicorn loads ``wsgi:app``; tests call ``create_app("testing")``.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request, session
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from config import get_config
from studenthub import assignments, auth, db, main, study, subjects, utils

csrf = CSRFProtect()

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


def configure_logging(level: str) -> None:
    root = logging.getLogger()
    if any(getattr(h, "_studenthub", False) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "time=%(asctime)s level=%(levelname)s logger=%(name)s msg=\"%(message)s\"", "%Y-%m-%dT%H:%M:%S%z"))
    handler._studenthub = True
    root.addHandler(handler)
    root.setLevel(level)


def create_app(config_name: str | None = None, overrides: dict | None = None) -> Flask:
    config_class = get_config(config_name)
    app = Flask(__name__)
    app.config.from_object(config_class)
    if overrides:
        app.config.update(overrides)
    config_class.validate(app.config)

    configure_logging(app.config["LOG_LEVEL"])
    if app.config["TRUST_PROXY"]:
        # Caddy sets X-Forwarded-For/Proto so url_for and secure cookies see https.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    csrf.init_app(app)
    auth.login_manager.init_app(app)
    for blueprint in (auth.bp, main.bp, subjects.bp, assignments.bp, study.bp):
        app.register_blueprint(blueprint)

    register_template_helpers(app)
    register_error_handlers(app)
    register_health(app)

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Content-Security-Policy", CSP)
        if session.get("_user_id"):  # never cache pages with personal data
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    logging.getLogger("studenthub").info(
        "app created env=%s version=%s db_host=%s db_name=%s tz=%s",
        app.config["APP_ENV"], app.config["APP_VERSION"], app.config["DB_HOST"],
        app.config["MYSQL_DATABASE"], app.config["APP_TIMEZONE"])
    return app


def register_template_helpers(app: Flask) -> None:
    @app.template_filter("localtime")
    def localtime(value, fmt="%d %b %Y, %H:%M"):
        local = utils.utc_to_local(value)
        return local.strftime(fmt) if local else "—"

    @app.template_filter("datefmt")
    def datefmt(value, fmt="%a, %d %b %Y"):
        return value.strftime(fmt) if value else "—"

    @app.template_filter("timefmt")
    def timefmt(value):
        return value.strftime("%H:%M") if value else ""

    @app.template_filter("minutes")
    def minutes(value):
        return utils.minutes_label(value)

    @app.context_processor
    def inject_globals():
        return {
            "app_version": app.config["APP_VERSION"],
            "STATUSES": utils.STATUSES,
            "PRIORITIES": utils.PRIORITIES,
            "url_with": utils.url_with,
            "today": utils.today(),
            "active_section": (request.endpoint or "").split(".")[0],
        }


def _wants_json() -> bool:
    return request.path.startswith("/api/") or request.path.startswith("/health")


def register_error_handlers(app: Flask) -> None:
    log = logging.getLogger("studenthub.errors")

    def page(code: int, title: str, message: str):
        if _wants_json():
            return jsonify(error=title), code
        # session check instead of current_user: no database lookup while rendering errors
        return render_template("errors/error.html", code=code, title=title, message=message,
                               signed_in=bool(session.get("_user_id"))), code

    @app.errorhandler(400)
    def bad_request(_e):
        return page(400, "Bad request", "The request could not be understood. Please check the form and try again.")

    @app.errorhandler(CSRFError)
    def csrf_error(_e):
        return page(400, "Form expired", "Your form session expired or was invalid. Go back, reload the page "
                                         "and try again.")

    @app.errorhandler(403)
    def forbidden(_e):
        return page(403, "Access denied", "You do not have permission to view this page.")

    @app.errorhandler(404)
    def not_found(_e):
        return page(404, "Page not found", "The page you are looking for does not exist or is not yours.")

    @app.errorhandler(405)
    def method_not_allowed(_e):
        return page(405, "Method not allowed", "That action is not available here.")

    @app.errorhandler(413)
    def too_large(_e):
        return page(413, "Request too large", "The submitted data is too large.")

    @app.errorhandler(db.DatabaseUnavailable)
    def database_unavailable(exc):
        log.error("database unavailable path=%s reason=%s", request.path, exc)
        return page(503, "Temporarily unavailable",
                    "StudentHub cannot reach its database right now. Please try again in a moment.")

    @app.errorhandler(500)
    def server_error(exc):
        original = getattr(exc, "original_exception", exc)
        log.exception("unhandled error path=%s", request.path, exc_info=original)
        return page(500, "Something went wrong", "An unexpected error occurred. It has been logged.")


def register_health(app: Flask) -> None:
    @app.route("/health")
    @csrf.exempt
    def health():
        result = db.check_health()
        healthy = result.get("database") == "ok" and result.get("migrations_applied", 0) > 0
        body = {"status": "ok" if healthy else "degraded", "version": app.config["APP_VERSION"],
                "time": datetime.now(timezone.utc).isoformat(timespec="seconds"), **result}
        return jsonify(body), 200 if healthy else 503

    @app.route("/health/live")
    def liveness():
        return jsonify(status="alive", version=app.config["APP_VERSION"])
