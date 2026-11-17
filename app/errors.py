from flask import current_app, jsonify
from werkzeug.exceptions import HTTPException

from app.extensions import db


class AppError(Exception):
    """Base class for errors we raise on purpose."""

    status_code = 400
    code = "bad_request"

    def __init__(self, message, status_code=None, code=None, details=None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code
        self.details = details


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"

class AuthenticationError(AppError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


def error_response(status, code, message, details=None):
    body = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return jsonify(body), status


def register_error_handlers(app):
    @app.errorhandler(AppError)
    def handle_app_error(err):
        return error_response(err.status_code, err.code, err.message, err.details)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        code = err.name.lower().replace(" ", "_")
        return error_response(err.code, code, err.description)

    @app.errorhandler(Exception)
    def handle_unexpected_error(err):
        db.session.rollback()
        current_app.logger.exception("Unhandled exception")
        return error_response(500, "internal_error", "Something went wrong on our side.")