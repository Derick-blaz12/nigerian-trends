from dataclasses import asdict, dataclass

RULES_VERSION = "2026-11-v1"


@dataclass(frozen=True)
class RadarRules:
    # Where the audience number comes from
    metric: str = "lastfm_listeners"
    metric_label: str = "Last.fm listeners"
    metric_source: str = "Last.fm"
    metric_max_age_days: int = 14

    # Eligibility
    audience_ceiling: int = 300_000
    max_years_since_debut: int = 5
    activity_window_days: int = 730
    min_score_to_appear: int = 10

    # Audience momentum
    growth_window_days: int = 30
    growth_min_span_days: int = 7
    growth_min_base: int = 100
    growth_min_gain: int = 50
    growth_pct_per_point: float = 2.0
    growth_max_points: int = 40

    # Recency (pairs of: within this many days or years, earn this many points)
    release_tiers: tuple = ((30, 25), (90, 15), (180, 5))
    coverage_days: int = 30
    coverage_points: int = 10
    debut_tiers: tuple = ((2, 10), (5, 5))

    # Editorial
    pick_points: int = 30


DEFAULT_RULES = RadarRules()


def rules_as_dict(rules=DEFAULT_RULES):
    return asdict(rules)