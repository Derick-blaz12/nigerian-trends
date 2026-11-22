from dataclasses import asdict, dataclass

COMMUNITY_VERSION = "2026-11-v1"


@dataclass(frozen=True)
class CommunityRules:
    # Popularity: likes x 1 + recommendations x 3 + commenters x 2
    like_points: int = 1
    recommend_points: int = 3
    commenter_points: int = 2
    min_engaged_users: int = 3   # different people needed before a song is ranked
    trending_days: int = 7

    # Comments
    comment_max_length: int = 2000
    edit_window_hours: int = 24
    max_links_per_comment: int = 2
    duplicate_window_minutes: int = 10
    max_thread_replies: int = 100

    # Moderation
    auto_hide_reports: int = 3
    max_mute_days: int = 365


DEFAULT_RULES = CommunityRules()


def rules_as_dict(rules=DEFAULT_RULES):
    return asdict(rules)