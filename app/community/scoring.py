from app.community.rules import DEFAULT_RULES


def popularity_score(likes, recommends, commenters, rules=DEFAULT_RULES):
    """Community popularity. `commenters` counts people, not comments."""
    return (
        likes * rules.like_points
        + recommends * rules.recommend_points
        + commenters * rules.commenter_points
    )