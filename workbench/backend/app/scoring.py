from dataclasses import dataclass
from datetime import UTC, datetime
from math import log1p


@dataclass(frozen=True)
class PaperSignals:
    title: str
    topic: str | None
    likes: float | None
    year: int


@dataclass(frozen=True)
class PreferenceSignals:
    interests: list[str]
    keywords: list[str]
    recent_work_terms: list[str]
    weights: dict[str, float]


@dataclass(frozen=True)
class ExplainableScore:
    total: float
    components: dict[str, float]


def _contains_any(text: str, terms: list[str]) -> float:
    lowered = text.casefold()
    return 1.0 if any(term.casefold() in lowered for term in terms if term.strip()) else 0.0


def score_paper(paper: PaperSignals, preferences: PreferenceSignals) -> ExplainableScore:
    text = f"{paper.title} {paper.topic or ''}"
    raw = {
        "recent_work": _contains_any(text, preferences.recent_work_terms),
        "interest": _contains_any(text, preferences.interests),
        "keyword": _contains_any(text, preferences.keywords),
        "impact": min(log1p(max(paper.likes or 0, 0)) / log1p(1000), 1.0),
        "freshness": max(0.0, 1.0 - max(datetime.now(UTC).year - paper.year, 0) / 5),
    }
    components = {
        name: round(value * preferences.weights.get(name, 0), 6)
        for name, value in raw.items()
    }
    return ExplainableScore(total=sum(components.values()), components=components)
