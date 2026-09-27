import argparse
import json
import sys
from pathlib import Path
from urllib.error import URLError

from .api import make_server
from .content import import_public_transcript, import_timed, now
from .contract import openapi
from .feed import MIANJI_RSS, TRANSCRIPT_BASE, match_transcript, parse_feed, parse_podcast, timestamp_ms
from .models import Content, DomainError, data
from .network import fetch
from .service import Service
from .storage import Store


def output(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_feed(store, raw, feed_url=MIANJI_RSS):
    synced_at = now()
    podcast = parse_podcast(raw, feed_url, synced_at)
    episodes = parse_feed(raw, feed_url)
    with store.connection() as db:
        store.put("podcasts", podcast.id, data(podcast), db)
        for episode in episodes:
            store.put("episodes", episode.id, data(episode), db)
            try:
                store.get("content", episode.id, db)
            except DomainError:
                store.put("content", episode.id, data(Content(episode.id, "chapters_only", [], now(),
                          ["只有 RSS 章节，尚无逐句时间戳。"])), db)
    return episodes


def select_podcast(store, selector):
    podcasts = store.all("podcasts")
    exact = [p for p in podcasts if selector in (p["id"], p["feed_url"], p["title"])]
    matches = exact or [p for p in podcasts if selector.casefold() in p["title"].casefold()]
    if len(matches) != 1:
        raise DomainError(f"Podcast selector matched {len(matches)} podcasts; use a unique id/title")
    return matches[0]


def select_episode(store, selector):
    episodes = store.all("episodes")
    exact = [e for e in episodes if selector == e["id"] or selector == e["guid"] or selector == e["title"]]
    matches = exact or [e for e in episodes if selector.casefold() in e["title"].casefold()]
    if len(matches) != 1:
        raise DomainError(f"Episode selector matched {len(matches)} episodes; use a unique id/title")
    return matches[0]


def parser():
    root = argparse.ArgumentParser(description="Castnets M0 · 带播客上下文的可插话播放器后端原型")
    root.add_argument("--db", default="data/castnets.sqlite3", help="SQLite file (default: data/castnets.sqlite3)")
    commands = root.add_subparsers(dest="command", required=True)
    sync = commands.add_parser("sync", help="Fetch a public RSS feed; retain audio URLs and chapter timestamps")
    sync.add_argument("--url", default=MIANJI_RSS, help=f"RSS URL (default: {MIANJI_RSS})")
    sync.add_argument("--file", help="Read cached RSS instead of network")
    commands.add_parser("podcasts", help="List imported podcast feeds")
    listing = commands.add_parser("episodes", help="List imported episodes")
    listing.add_argument("--podcast", help="Filter by a unique podcast id/title/feed URL")
    listing.add_argument("--contains", default="")
    listing.add_argument("--limit", type=int, default=20)
    prepare = commands.add_parser("prepare", help="Match and fetch an existing public transcript by exact normalized title")
    prepare.add_argument("episode")
    prepare.add_argument("--catalog-file")
    prepare.add_argument("--transcript-file")
    prepare.add_argument("--chapters-only", action="store_true")
    imported = commands.add_parser("import-timed", help="Import externally aligned JSON; no custom ASR")
    imported.add_argument("episode")
    imported.add_argument("file")
    content = commands.add_parser("content", help="Inspect canonical content representation")
    content.add_argument("episode")
    ask = commands.add_parser("ask", help="Create a saved branch with a structured offline answer draft")
    ask.add_argument("episode")
    ask.add_argument("--at", required=True, help="Seconds or HH:MM:SS / MM:SS")
    ask.add_argument("--question", required=True)
    ask.add_argument("--rewind", default="5", help="Seconds, 0..30")
    turn = commands.add_parser("turn", help="Append a question to an active branch")
    turn.add_argument("branch_id")
    turn.add_argument("--question", required=True)
    resume = commands.add_parser("resume", help="Simulate the explicit 继续 intent; no microphone access")
    resume.add_argument("branch_id")
    commands.add_parser("branches", help="List saved branches")
    commands.add_parser("demo", help="Run the real-source offline excerpt demo (no key, network or audio download)")
    serve = commands.add_parser("serve", help="Start loopback-only HTTP API")
    serve.add_argument("--port", type=int, default=8765)
    commands.add_parser("contract", help="Print OpenAPI 3.1 contract")
    return root


def main(argv=None):
    root = parser()
    args = root.parse_args(argv)
    try:
        if args.command == "contract":
            return output(openapi())
        store = Store(args.db)
        service = Service(store)
        if args.command == "sync":
            episodes = save_feed(store, Path(args.file).read_bytes() if args.file else fetch(args.url), args.url)
            output({"count": len(episodes), "feed_url": args.url})
        elif args.command == "podcasts":
            output(store.all("podcasts"))
        elif args.command == "episodes":
            if args.limit < 1:
                raise DomainError("limit must be positive")
            feed_url = select_podcast(store, args.podcast)["feed_url"] if args.podcast else None
            output([{k: e[k] for k in ("id", "title", "duration_ms", "audio_url")}
                    for e in store.all("episodes")
                    if (feed_url is None or e["feed_url"] == feed_url)
                    and args.contains.casefold() in e["title"].casefold()][:args.limit])
        elif args.command == "prepare":
            episode = select_episode(store, args.episode)
            if args.chapters_only:
                content = Content(episode["id"], "chapters_only", [], now(), ["未导入逐字稿。"])
            else:
                catalog = read_json(args.catalog_file) if args.catalog_file else json.loads(fetch(TRANSCRIPT_BASE + "api/documents.json"))
                try:
                    match = match_transcript(episode, catalog)
                except DomainError as error:
                    if error.code != "transcript_not_matched":
                        raise
                    # Do not replace a previous successful import when a newer catalog has a gap.
                    output({"episode_id": episode["id"], "status": "transcript_not_matched", "message": str(error),
                            "existing_content": store.get("content", episode["id"])["status"]})
                    return
                path = match["api_path"]
                if not isinstance(path, str) or not path.startswith("api/documents/") or ".." in path:
                    raise DomainError("Unexpected catalog document path")
                url = TRANSCRIPT_BASE + path
                doc = read_json(args.transcript_file) if args.transcript_file else json.loads(fetch(url))
                content = import_public_transcript(episode, doc, url)
            store.put("content", episode["id"], data(content))
            output({"episode_id": episode["id"], "status": content.status,
                    "segment_count": len(content.segments), "chapter_count": len(episode["chapters"]), "warnings": content.warnings})
        elif args.command == "import-timed":
            episode = select_episode(store, args.episode)
            content = import_timed(episode, read_json(args.file))
            store.put("content", episode["id"], data(content))
            output({"episode_id": episode["id"], "status": content.status, "segment_count": len(content.segments)})
        elif args.command == "content":
            output(store.get("content", select_episode(store, args.episode)["id"]))
        elif args.command == "ask":
            output(service.create_branch(select_episode(store, args.episode)["id"], timestamp_ms(args.at),
                                         args.question, timestamp_ms(args.rewind)))
        elif args.command == "turn":
            output(service.add_turn(args.branch_id, args.question))
        elif args.command == "resume":
            output(service.resume(args.branch_id))
        elif args.command == "branches":
            output(store.all("branches"))
        elif args.command == "demo":
            sample = Path(__file__).parent / "sample"
            sample_episode = parse_feed((sample / "episode.xml").read_bytes())[0]
            try:
                episode = store.get("episodes", sample_episode.id)
            except DomainError:
                episode = data(save_feed(store, (sample / "episode.xml").read_bytes())[0])
            doc = read_json(sample / "transcript-excerpt.json")
            content = import_public_transcript(episode, doc, TRANSCRIPT_BASE + doc["api_path"])
            content.warnings.append("离线样本仅含公开逐字稿的一小段节选；完整文本需 prepare 在线获取。")
            # Demo should not overwrite an already prepared full transcript or aligned import.
            if store.get("content", episode["id"])["status"] == "chapters_only":
                store.put("content", episode["id"], data(content))
            branch = service.create_branch(episode["id"], 675000, "RWA 是什么意思？")
            output(service.resume(branch["id"]))
        elif args.command == "serve":
            if not 0 <= args.port <= 65535:
                raise DomainError("port must be in [0, 65535]")
            server = make_server(service, args.port)
            print(f"Castnets M0 http://127.0.0.1:{server.server_port} · mock · loopback only", file=sys.stderr)
            try:
                server.serve_forever()
            finally:
                server.server_close()
    except (DomainError, OSError, URLError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"error": {"code": getattr(error, "code", "input_or_network_error"), "message": str(error)}}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        pass
