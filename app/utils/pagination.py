from flask import current_app

from app.utils.validation import parse_int


def get_pagination(args):
    """Read and validate ?page= and ?per_page= from a request."""
    page = parse_int(args.get("page"), "page", default=1, minimum=1)
    per_page = parse_int(
        args.get("per_page"),
        "per_page",
        default=current_app.config["DEFAULT_PAGE_SIZE"],
        minimum=1,
        maximum=current_app.config["MAX_PAGE_SIZE"],
    )
    return page, per_page