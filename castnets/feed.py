import hashlib
import re
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import urlsplit

from .models import DomainError, Episode, Podcast, Segment, Source

MIANJI_RSS = "https://feed.xyzfm.space/6hpdgggtxpxb"
TRANSCRIPT_BASE = "https://laoqianritan-create.github.io/"
ATTRIBUTION = "这段内容引用自播客《面基》。"


def timestamp_ms(value: str) -> int:
    """CLI seconds / MM:SS / HH:MM:SS; fractional seconds supported."""
    try:
        fields = value.split(":")
        if not 1 <= len(fields) <= 3 or any(not re.fullmatch(r"\d+(?:\.\d{1,3})?", f) for f in fields):
            raise ValueError()
        if any("." in f for f in fields[:-1]):
            raise ValueError()
        values = [Decimal(f) for f in fields]
        if len(values) > 1 and any(v >= 60 for v in values[1:]):
            raise ValueError()
        result = sum(v * (60 ** i) for i, v in enumerate(reversed(values))) * 1000
        if result > 86_400_000:
            raise ValueError()
        return int(result)
    except (ValueError, InvalidOperation):
        raise DomainError("Time must be seconds, MM:SS or HH:MM:SS (at most 24 hours)") from None


class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"p", "br", "li", "div", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"p", "li", "div"}:
            self.parts.append("\n")

    def handle_data(self, value):
        self.parts.append(value)


def chapter_segments(description: str, duration_ms: int | None, source_url: str) -> list[Segment]:
    parser = TextHTML()
    parser.feed(description)
    chapters = []
    for line in "".join(parser.parts).splitlines():
        match = re.match(r"^\s*(\d{1,3}:\d{2}(?::\d{2})?)\s+(.+)$", line)
        if not match:
            continue
        try:
            start = timestamp_ms(match[1])
        except DomainError:
            continue
        # Strictly increasing first sequence; duplicate resource references aren't chapters.
        if (chapters and start <= chapters[-1].start_ms) or (duration_ms is not None and start >= duration_ms):
            continue
        chapters.append(Segment(f"chapter-{start}", start, None, match[2].strip(), None,
                                Source("rss_chapter", source_url, ATTRIBUTION, "chapter")))
    for i, chapter in enumerate(chapters):
        chapter.end_ms = chapters[i + 1].start_ms if i + 1 < len(chapters) else duration_ms
    return chapters


def parse_root(raw: bytes):
    # No DTD/entity processing for untrusted feeds (including UTF-16 XML).
    if b"<!DOCTYPE" in raw.upper().replace(b"\x00", b"") or b"<!ENTITY" in raw.upper().replace(b"\x00", b""):
        raise DomainError("RSS DTD/entities are not supported")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise DomainError(f"Invalid RSS: {exc}") from exc
    if root.tag != "rss" or root.find("channel") is None:
        raise DomainError("Expected RSS 2.0 channel")
    return root


def plain_text(value: str) -> str:
    parser = TextHTML()
    parser.feed(value)
    return " ".join("".join(parser.parts).split())


def parse_podcast(raw: bytes, feed_url: str, synced_at: str) -> Podcast:
    parsed_url = urlsplit(feed_url)
    if parsed_url.scheme != "https" or not parsed_url.hostname or parsed_url.username or parsed_url.password:
        raise DomainError("feed_url must be a public HTTPS URL without credentials")
    channel = parse_root(raw).find("channel")
    image = channel.find("{http://www.itunes.com/dtds/podcast-1.0.dtd}image")
    rss_image = channel.find("image")
    image_url = image.get("href") if image is not None else None
    if not image_url and rss_image is not None:
        image_url = rss_image.findtext("url")
    return Podcast(
        hashlib.sha256(feed_url.encode()).hexdigest()[:24],
        (channel.findtext("title") or "Untitled podcast").strip(),
        feed_url,
        plain_text(channel.findtext("description") or ""),
        channel.findtext("link"),
        channel.findtext("{http://www.itunes.com/dtds/podcast-1.0.dtd}author"),
        image_url,
        synced_at,
    )


def parse_feed(raw: bytes, feed_url=MIANJI_RSS) -> list[Episode]:
    root = parse_root(raw)
    episodes = []
    for item in root.findall("./channel/item"):
        enclosure = item.find("enclosure")
        if enclosure is None or not enclosure.get("url"):
            continue
        guid = item.findtext("guid") or enclosure.get("url")
        episode_id = hashlib.sha256((feed_url + "\n" + guid).encode()).hexdigest()[:24]
        duration = item.findtext("{http://www.itunes.com/dtds/podcast-1.0.dtd}duration")
        try:
            duration_ms = timestamp_ms(duration.strip()) if duration else None
        except DomainError:
            duration_ms = None
        page = item.findtext("link") or feed_url
        description = item.findtext("description") or item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or ""
        episodes.append(Episode(episode_id, guid, item.findtext("title") or "Untitled", feed_url,
                                enclosure.get("url"), enclosure.get("type", "audio/mpeg"), duration_ms,
                                item.findtext("pubDate"), page,
                                chapter_segments(description, duration_ms, page)))
    return episodes


def normalized_title(title: str) -> str:
    title = re.sub(r"^\d+_", "", title.strip())
    title = re.sub(r"^[Ee]\d+[.．、\s]*", "", title)
    return "".join(c.lower() for c in title if c.isalnum())


def match_transcript(episode: dict, catalog: dict) -> dict:
    matches = [doc for doc in catalog.get("documents", [])
               if doc.get("source_key") == "mianji"
               and normalized_title(doc.get("title", "")) == normalized_title(episode["title"])]
    if len(matches) != 1:
        raise DomainError(f"Expected one exact title match, found {len(matches)}; no transcript guessed", "transcript_not_matched", 409)
    return matches[0]
