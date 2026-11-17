from flask import jsonify
from app.main import bp


@bp.route("/")
def index():
    return jsonify(message="Nigerian Trends & Discovery Platform", status="running")


@bp.route("/health")
def health():
    return jsonify(status="ok")