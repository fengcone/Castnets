import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from castnets.api import make_server
from castnets.cli import save_feed, select_episode, select_podcast
from castnets.content import import_public_transcript, import_timed
from castnets.contract import openapi
from castnets.feed import MIANJI_RSS, parse_feed, timestamp_ms
from castnets.models import DomainError, data
from castnets.service import Service
from castnets.storage import Store


SAMPLE = Path(__file__).parents[1] / "castnets" / "sample"


class M0CoreTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "castnets.sqlite3"
        self.store = Store(self.db_path)
        self.raw = (SAMPLE / "episode.xml").read_bytes()
        self.episodes = save_feed(self.store, self.raw)
        self.episode = data(self.episodes[0])

    def tearDown(self):
        self.tempdir.cleanup()

    def test_rss_is_persisted_as_podcast_and_selectable_episode(self):
        podcasts = self.store.all("podcasts")
        self.assertEqual(1, len(podcasts))
        self.assertEqual("面基", podcasts[0]["title"])
        self.assertEqual(MIANJI_RSS, podcasts[0]["feed_url"])
        self.assertEqual(podcasts[0], select_podcast(self.store, "面基"))
        self.assertEqual(self.episode["id"], select_episode(self.store, "E146")["id"])
        self.assertEqual(675_000, self.episode["chapters"][2]["start_ms"])
        self.assertEqual(1_279_000, self.episode["chapters"][2]["end_ms"])
        self.assertEqual("chapters_only", self.store.get("content", self.episode["id"])["status"])

    def test_feed_identity_changes_episode_ids(self):
        other = parse_feed(self.raw, "https://example.test/feed.xml")
        self.assertNotEqual(self.episode["id"], other[0].id)
        self.assertEqual("https://example.test/feed.xml", other[0].feed_url)
        with self.assertRaises(DomainError):
            save_feed(self.store, self.raw, "file:///tmp/feed.xml")

    def test_unaligned_and_timed_content_are_explicit(self):
        doc = json.loads((SAMPLE / "transcript-excerpt.json").read_text(encoding="utf-8"))
        unaligned = import_public_transcript(self.episode, doc, "https://example.test/transcript.json")
        self.assertEqual("transcript_unaligned", unaligned.status)
        self.assertIsNone(unaligned.segments[0].start_ms)
        self.assertEqual("unaligned", unaligned.segments[0].source.timing)

        timed = import_timed(self.episode, {
            "episode_id": self.episode["id"],
            "source_url": "https://example.test/alignment.json",
            "attribution": "Test alignment",
            "segments": [{"start_ms": 670_000, "end_ms": 680_000, "text": "RWA 是真实世界资产。", "speaker": "猫曹"}],
        })
        self.assertEqual("transcript_timed", timed.status)
        self.assertEqual("supplied", timed.segments[0].source.timing)
        self.assertIn("未校验", timed.warnings[0])

    def test_branch_persists_followup_and_idempotent_resume(self):
        service = Service(self.store)
        branch = service.create_branch(self.episode["id"], 675_000, "RWA 是什么意思？")
        self.assertEqual("mock", branch["turns"][0]["answer"]["mode"])
        self.assertEqual("chapter", branch["turns"][0]["context"]["precision"])
        self.assertEqual(670_000, branch["resume_position_ms"])

        branch = service.add_turn(branch["id"], "那 alpha 呢？")
        self.assertEqual(2, len(branch["turns"]))
        resumed = service.resume(branch["id"])
        resumed_again = Service(Store(self.db_path)).resume(branch["id"])
        self.assertEqual("resumed", resumed_again["state"])
        self.assertEqual(resumed["resume_position_ms"], resumed_again["resume_position_ms"])
        self.assertEqual(resumed["resumed_at"], resumed_again["resumed_at"])
        with self.assertRaisesRegex(DomainError, "already resumed"):
            service.add_turn(branch["id"], "继续问")

    def test_unknown_question_returns_structured_honest_fallback(self):
        turn = Service(self.store).create_branch(self.episode["id"], 1_000, "这个论证成立吗？")["turns"][0]
        self.assertEqual("insufficient_context", turn["answer"]["confidence"])
        self.assertTrue(turn["answer"]["limitations"])
        self.assertEqual("none", turn["context"]["precision"])

    def test_time_parser_rejects_ambiguous_or_out_of_range_values(self):
        self.assertEqual(5_500, timestamp_ms("5.5"))
        self.assertEqual(3_723_250, timestamp_ms("1:02:03.250"))
        for value in ("1:60", "1.2:03", "25:00:00", "-1"):
            with self.subTest(value=value), self.assertRaises(DomainError):
                timestamp_ms(value)


class M0ApiTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tempdir.name) / "api.sqlite3")
        self.episode = data(save_feed(self.store, (SAMPLE / "episode.xml").read_bytes())[0])
        self.server = None
        self.thread = None
        if self._testMethodName == "test_contract_exposes_android_resources":
            return
        try:
            self.server = make_server(Service(self.store), 0)
        except PermissionError:
            self.skipTest("environment forbids binding a loopback test server")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=2)
        self.tempdir.cleanup()

    def request(self, path, method="GET", payload=None, content_type="application/json"):
        body = json.dumps(payload).encode() if payload is not None else None
        request = Request(self.base + path, data=body, method=method)
        if body is not None:
            request.add_header("Content-Type", content_type)
        try:
            with urlopen(request, timeout=2) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_contract_exposes_android_resources(self):
        contract = openapi()
        for path in ("/v1/podcasts", "/v1/podcasts/{id}/episodes", "/v1/episodes/{id}/content",
                     "/v1/branches", "/v1/branches/{id}/turns", "/v1/branches/{id}/resume"):
            self.assertIn(path, contract["paths"])
        json.dumps(contract, allow_nan=False)

    def test_http_full_branch_flow(self):
        status, podcasts = self.request("/v1/podcasts")
        self.assertEqual(200, status)
        status, episodes = self.request(f"/v1/podcasts/{podcasts[0]['id']}/episodes")
        self.assertEqual([self.episode["id"]], [episode["id"] for episode in episodes])

        status, branch = self.request("/v1/branches", "POST", {
            "episode_id": self.episode["id"], "anchor_ms": 675_000, "question": "RWA 是什么意思？"
        })
        self.assertEqual(201, status)
        status, branch = self.request(f"/v1/branches/{branch['id']}/turns", "POST", {"question": "那 alpha 呢？"})
        self.assertEqual(201, status)
        self.assertEqual(2, len(branch["turns"]))
        status, resumed = self.request(f"/v1/branches/{branch['id']}/resume", "POST")
        self.assertEqual(200, status)
        self.assertEqual(670_000, resumed["resume_position_ms"])
        status, resumed_again = self.request(f"/v1/branches/{branch['id']}/resume", "POST")
        self.assertEqual(resumed["resumed_at"], resumed_again["resumed_at"])

    def test_http_validation_is_structured(self):
        status, result = self.request("/v1/branches", "POST", {"episode_id": self.episode["id"]}, "text/plain")
        self.assertEqual(415, status)
        self.assertEqual("unsupported_media_type", result["error"]["code"])
        status, result = self.request("/missing")
        self.assertEqual(404, status)
        self.assertEqual("not_found", result["error"]["code"])


if __name__ == "__main__":
    unittest.main()
