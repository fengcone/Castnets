import re
from datetime import datetime, timezone

from .feed import ATTRIBUTION, normalized_title
from .models import Content, Context, DomainError, Segment, Source, integer, nonblank


def now():
    return datetime.now(timezone.utc).isoformat()


def segment_from(value: dict) -> Segment:
    return Segment(**{**value, "source": Source(**value["source"])})


def import_public_transcript(episode: dict, doc: dict, url: str) -> Content:
    if doc.get("source_key") != "mianji" or normalized_title(doc.get("title", "")) != normalized_title(episode["title"]):
        raise DomainError("Transcript source/title does not match selected episode")
    markdown = nonblank(doc.get("markdown"), "markdown", 2_000_000)
    source = Source("public_transcript", url, doc.get("attribution_text") or ATTRIBUTION, "unaligned")
    segments = []
    for paragraph in re.split(r"\n\s*\n", markdown):
        paragraph = paragraph.strip()
        if not paragraph or paragraph.startswith("#"):
            continue
        speaker_match = re.match(r"^\[([^\]]+)\]\s*(.*)$", paragraph, re.S)
        speaker, text = (speaker_match[1], speaker_match[2]) if speaker_match else (None, paragraph)
        segments.append(Segment(f"transcript-{len(segments)}", None, None, text, speaker, source))
    if not segments:
        raise DomainError("Transcript contains no paragraphs")
    return Content(episode["id"], "transcript_unaligned", segments, now(),
                   ["公开逐字稿未与音频对齐；说话人标签和文字保留来源原样，尚未人工校正。"])


def import_timed(episode: dict, payload: dict) -> Content:
    if payload.get("episode_id") != episode["id"]:
        raise DomainError("Timed transcript episode_id mismatch")
    rows = payload.get("segments")
    if not isinstance(rows, list) or not rows or len(rows) > 20000:
        raise DomainError("segments must contain 1..20000 items")
    source = Source("timed_transcript", nonblank(payload.get("source_url"), "source_url"),
                    nonblank(payload.get("attribution"), "attribution"), "supplied")
    segments = []
    previous_start = -1
    for row in rows:
        if not isinstance(row, dict):
            raise DomainError("Each segment must be an object")
        start, end = integer(row.get("start_ms"), "start_ms"), integer(row.get("end_ms"), "end_ms")
        if start < previous_start or end <= start or (episode["duration_ms"] is not None and end > episode["duration_ms"]):
            raise DomainError("Segments must be ordered, positive length, within episode duration")
        speaker = row.get("speaker")
        if speaker is not None:
            speaker = nonblank(speaker, "speaker", 200)
        segments.append(Segment(f"timed-{len(segments)}", start, end, nonblank(row.get("text"), "text", 10000), speaker, source))
        previous_start = start
    return Content(episode["id"], "transcript_timed", segments, now(),
                   ["时间戳由导入者提供，M0 未校验与当前音频版本的同步误差。"])


def tokens(text: str) -> set[str]:
    result = set(re.findall(r"[a-z0-9αβ]+", text.lower()))
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        result.update(run[i:i+2] for i in range(len(run)-1))
    return result


def context_at(episode: dict, content: dict | None, anchor_ms: int, question: str) -> Context:
    chapters = [segment_from(s) for s in episode["chapters"]]
    chapter = next((c for c in chapters if c.start_ms <= anchor_ms and (c.end_ms is None or anchor_ms < c.end_ms)), None)
    segments = [segment_from(s) for s in content["segments"]] if content else []
    # Look backward only: never pretend unheard future dialogue is playback context.
    timed = [s for s in segments if s.start_ms is not None and s.start_ms <= anchor_ms and s.end_ms > max(0, anchor_ms - 90_000)]
    query = tokens(question)
    ranked = sorted(((len(query & tokens(s.text)), i, s) for i, s in enumerate(segments) if s.start_ms is None),
                    key=lambda item: (-item[0], item[1]))
    related = [s for score, _, s in ranked[:2] if score > 0]
    warnings = list(content.get("warnings", [])) if content else ["尚未获取逐字稿。"]
    if not timed:
        warnings.append("缺少当前播放位置的逐句内容；章节标题不能证明嘉宾此刻说了什么。")
    if related:
        warnings.append("以下逐字稿片段仅按问题关键词检索，可能来自整期其他位置，不能视为刚刚听到的话。")
    return Context(chapter, timed[-12:], related, "timed" if timed else "chapter" if chapter else "none", warnings)
