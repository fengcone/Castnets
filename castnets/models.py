from dataclasses import asdict, dataclass, field
from typing import Literal


class DomainError(ValueError):
    def __init__(self, message: str, code: str = "invalid_request", status: int = 400):
        super().__init__(message)
        self.code, self.status = code, status


def integer(value, name, minimum=0, maximum=86_400_000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise DomainError(f"{name} must be an integer in [{minimum}, {maximum}]")
    return value


def nonblank(value, name, maximum=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise DomainError(f"{name} must be nonempty text, at most {maximum} characters")
    return value.strip()


@dataclass
class Source:
    kind: Literal["rss_chapter", "public_transcript", "timed_transcript", "demo_glossary"]
    url: str
    attribution: str
    timing: Literal["chapter", "unaligned", "supplied", "not_applicable"]


@dataclass
class Segment:
    id: str
    start_ms: int | None
    end_ms: int | None
    text: str
    speaker: str | None
    source: Source


@dataclass
class Podcast:
    id: str
    title: str
    feed_url: str
    description: str
    site_url: str | None
    author: str | None
    image_url: str | None
    synced_at: str


@dataclass
class Episode:
    id: str
    guid: str
    title: str
    feed_url: str
    audio_url: str
    audio_type: str
    duration_ms: int | None
    published_at: str | None
    page_url: str
    chapters: list[Segment]


@dataclass
class Content:
    episode_id: str
    status: Literal["chapters_only", "transcript_unaligned", "transcript_timed"]
    segments: list[Segment]
    imported_at: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class Context:
    chapter: Segment | None
    timed_segments: list[Segment]
    related_unaligned: list[Segment]
    precision: Literal["timed", "chapter", "none"]
    warnings: list[str]


@dataclass
class Answer:
    spoken_answer: str
    visual_summary: list[str]
    key_terms: list[str]
    source_types: list[str]
    sources: list[Source]
    resume_bridge: str
    mode: Literal["mock"]
    confidence: Literal["draft", "insufficient_context"]
    limitations: list[str]


@dataclass
class Turn:
    id: str
    question: str
    answer: Answer
    context: Context
    created_at: str


@dataclass
class Branch:
    schema_version: str
    id: str
    episode_id: str
    anchor_ms: int
    resume_offset_ms: int
    resume_position_ms: int
    state: Literal["active", "resumed"]
    turns: list[Turn]
    created_at: str
    resumed_at: str | None


def data(model):
    return asdict(model)
