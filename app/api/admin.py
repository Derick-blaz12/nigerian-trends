from flask import jsonify, request

from app.api import bp
from app.api.auth import serialize_user
from app.security import admin_required
from app.services import user_service
from app.utils.pagination import get_pagination


@bp.get("/admin/users")
@admin_required
def list_users():
    page, per_page = get_pagination(request.args)
    items, total = user_service.list_users(page, per_page)
    return jsonify(
        data=[serialize_user(u) for u in items],
        meta={"page": page, "per_page": per_page, "total": total},
    )