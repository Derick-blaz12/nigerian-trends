from dataclasses import asdict, dataclass

FOLLOW_VERSION = "2026-11-v1"


@dataclass(frozen=True)
class FollowRules:
    max_follows: int = 500          # artists one person can follow
    notify_window_days: int = 14    # only releases and stories this recent can notify
    digest_max_items: int = 10      # items shown in an email digest preview
    keep_read_days: int = 90        # read notifications are deleted after this long


DEFAULT_RULES = FollowRules()


def rules_as_dict(rules=DEFAULT_RULES):
    return asdict(rules)