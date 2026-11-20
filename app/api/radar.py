from flask import current_app, jsonify, request

from app.api import bp
from app.api.serializers import serialize_artist_summary
from app.radar.rules import DEFAULT_RULES, RULES_VERSION, rules_as_dict
from app.services import radar_service
from app.utils.validation import parse_int


@bp.get("/radar")
def get_radar():
    limit = parse_int(request.args.get("limit"), "limit", default=12, minimum=1, maximum=50)
    items, total = radar_service.build_radar(limit, genre=request.args.get("genre"))

    data = []
    for rank, (artist, facts, evaluation) in enumerate(items, start=1):
        audience = None
        if facts.listeners_latest is not None:
            audience = {
                "listeners": facts.listeners_latest,
                "growth_pct": (
                    round(evaluation.growth_pct, 1) if evaluation.growth_pct is not None else None
                ),
                "span_days": facts.span_days,
            }
        data.append(
            {
                "rank": rank,
                "artist": serialize_artist_summary(artist),
                "score": evaluation.score,
                "editors_pick": evaluation.editors_pick,
                "reasons": [{"label": c.detail, "points": c.points} for c in evaluation.components],
                "audience": audience,
            }
        )

    meta = {"total": total, "limit": limit, "rules_version": RULES_VERSION}
    if any(facts.listeners_latest is not None for _, facts, _ in items):
        meta["attribution"] = f"Audience figures from {DEFAULT_RULES.metric_source}."
    response = jsonify(data=data, meta=meta)
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


@bp.get("/radar/rules")
def radar_rules():
    return jsonify(
        data={
            "version": RULES_VERSION,
            "rules": rules_as_dict(DEFAULT_RULES),
            "commercial_mode": current_app.config["PLATFORM_COMMERCIAL"],
        }
    )