from dataclasses import dataclass, field
from datetime import date, datetime

from app.radar.rules import RadarRules


@dataclass
class ArtistFacts:
    """Everything the rules need to know about one artist, gathered by facts.py."""

    artist_id: int
    name: str
    archived: bool = False
    debut_year: int | None = None
    has_public_content: bool = False
    last_release_date: date | None = None
    last_update_at: datetime | None = None
    listeners_latest: int | None = None
    listeners_base: int | None = None
    span_days: int | None = None
    entry_status: str | None = None  # 'pick' or 'excluded'
    entry_note: str | None = None


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class Component:
    name: str
    points: int
    detail: str


@dataclass
class Evaluation:
    eligible: bool
    appears: bool
    score: int
    editors_pick: bool
    overridden: bool
    note: str | None
    checks: list = field(default_factory=list)
    components: list = field(default_factory=list)
    growth_pct: float | None = None


def _last_activity(facts):
    dates = []
    if facts.last_release_date is not None:
        dates.append(facts.last_release_date)
    if facts.last_update_at is not None:
        dates.append(facts.last_update_at.date())
    return max(dates) if dates else None


def _run_checks(facts, rules, today, excluded):
    checks = []
    if excluded:
        checks.append(
            Check("editorial_exclusion", False, "An editor marked this artist as not emerging.")
        )
    if facts.archived:
        checks.append(Check("active_artist", False, "The artist is archived."))

    has_content = facts.has_public_content
    checks.append(
        Check("has_content", has_content, "Has public releases." if has_content else "No public releases yet.")
    )

    if facts.listeners_latest is None:
        checks.append(Check("audience_size", True, "No recent audience data (not held against them)."))
    else:
        ok = facts.listeners_latest <= rules.audience_ceiling
        checks.append(
            Check(
                "audience_size",
                ok,
                f"{rules.metric_label}: {facts.listeners_latest:,} (limit {rules.audience_ceiling:,}).",
            )
        )

    if facts.debut_year is None:
        checks.append(Check("career_stage", True, "Debut year unknown (not held against them)."))
    else:
        years = today.year - facts.debut_year
        ok = years <= rules.max_years_since_debut
        checks.append(
            Check(
                "career_stage",
                ok,
                f"Debuted in {facts.debut_year}, {years} years ago (limit {rules.max_years_since_debut}).",
            )
        )

    activity = _last_activity(facts)
    if activity is None:
        checks.append(Check("recent_activity", False, "No release or news story yet."))
    else:
        age = (today - activity).days
        ok = age <= rules.activity_window_days
        checks.append(
            Check(
                "recent_activity",
                ok,
                f"Last release or news {age} days ago (limit {rules.activity_window_days}).",
            )
        )
    return checks


def _score(facts, rules, today, pick):
    components = []
    growth_pct = None

    if (
        facts.listeners_latest is not None
        and facts.listeners_base is not None
        and facts.span_days is not None
        and facts.span_days >= rules.growth_min_span_days
        and facts.listeners_base >= rules.growth_min_base
    ):
        gain = facts.listeners_latest - facts.listeners_base
        growth_pct = gain * 100 / facts.listeners_base
        if gain >= rules.growth_min_gain:
            points = min(rules.growth_max_points, int(growth_pct // rules.growth_pct_per_point))
            if points > 0:
                components.append(
                    Component(
                        "growth",
                        points,
                        f"{rules.metric_label} up {growth_pct:.0f}% in {facts.span_days} days "
                        f"({facts.listeners_base:,} to {facts.listeners_latest:,}).",
                    )
                )

    if facts.last_release_date is not None:
        days = (today - facts.last_release_date).days
        if days >= 0:
            for max_days, points in rules.release_tiers:
                if days <= max_days:
                    detail = "New release today." if days == 0 else f"New release {days} days ago."
                    components.append(Component("new_release", points, detail))
                    break

    if facts.last_update_at is not None:
        age = (today - facts.last_update_at.date()).days
        if 0 <= age <= rules.coverage_days:
            components.append(
                Component(
                    "news_coverage",
                    rules.coverage_points,
                    f"Featured in our news in the last {rules.coverage_days} days.",
                )
            )

    if facts.debut_year is not None:
        years = today.year - facts.debut_year
        for max_years, points in rules.debut_tiers:
            if years <= max_years:
                components.append(Component("new_career", points, f"Debuted in {facts.debut_year}."))
                break

    if pick:
        components.append(
            Component("editors_pick", rules.pick_points, facts.entry_note or "Chosen by our editors.")
        )
    return components, growth_pct


def evaluate(facts, rules, today):
    pick = facts.entry_status == "pick"
    excluded = facts.entry_status == "excluded"

    checks = _run_checks(facts, rules, today, excluded)
    all_passed = all(check.passed for check in checks)
    eligible = (not excluded) and (not facts.archived) and (pick or all_passed)

    components, growth_pct = _score(facts, rules, today, pick)
    score = sum(component.points for component in components)
    appears = eligible and (pick or score >= rules.min_score_to_appear)
    return Evaluation(
        eligible=eligible,
        appears=appears,
        score=score,
        editors_pick=pick,
        overridden=eligible and pick and not all_passed,
        note=facts.entry_note if pick else None,
        checks=checks,
        components=components,
        growth_pct=growth_pct,
    )


def rank_key(facts, evaluation):
    """Highest score first, then editor's picks, then name (so the order never jumps around)."""
    return (-evaluation.score, not evaluation.editors_pick, facts.name.lower(), facts.artist_id)