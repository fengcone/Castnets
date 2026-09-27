import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from castnets.cli import save_feed, select_episode
from castnets.content import context_at, import_public_transcript, import_timed
from castnets.feed import chapter_segments, match_transcript, parse_feed, timestamp_ms
from castnets.models import DomainError, data
from castnets.network import fetch
from castnets.service import Service
from castnets.storage import Store

SAMPLE = Path(__file__).parents[1] / "castnets" / "sample"


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "test.sqlite3")
        self.episode = data(save_feed(self.store, (SAMPLE / "episode.xml").read_bytes())[0])
        self.doc = json.loads((SAMPLE / "transcript-excerpt.json").read_text())
        self.service = Service(self.store)

    def import_public(self):
        content = import_public_transcript(self.episode, self.doc, "https://example.org/transcript")
        self.store.put("content", self.episode["id"], data(content))
        return data(content)

    def test_rss_reimport_is_idempotent_and_keeps_full_transcript(self):
        self.import_public()
        save_feed(self.store, (SAMPLE / "episode.xml").read_bytes())
        self.assertEqual(len(self.store.all("episodes")), 1)
        self.assertEqual(self.store.get("content", self.episode["id"])["status"], "transcript_unaligned")
        self.assertEqual(self.episode["duration_ms"], 5511000)
        self.assertTrue(self.episode["audio_url"].startswith("https://"))

    def test_xml_entities_and_bad_rss_rejected(self):
        for raw in [b'<rss><broken>', b'<feed/>', b'<!DOCTYPE rss [<!ENTITY x "hello">]><rss/>', '<!DOCTYPE rss><rss/>'.encode('utf-16')]:
            with self.subTest(raw=raw), self.assertRaises(DomainError):
                parse_feed(raw)

    def test_chapter_hour_split_across_html_and_duplicate_references(self):
        chapters = chapter_segments('<p>00:15 intro</p><p>1:<a>03:35</a> topic</p><p>1:<a>03:35</a> resource link</p>', 4000000, 'https://example.org')
        self.assertEqual([s.start_ms for s in chapters], [15000, 3815000])
        self.assertEqual(chapters[0].end_ms, 3815000)

    def test_timestamps(self):
        for value, expected in [('11:15', 675000), ('1:03:35', 3815000), ('0.125', 125), ('0', 0)]:
            self.assertEqual(timestamp_ms(value), expected)
        for value in ['NaN', '-1', '1:60', '1:2:3:4', '100000', '1.2:30', '1e2']:
            with self.subTest(value=value), self.assertRaises(DomainError):
                timestamp_ms(value)

    def test_match_by_title_not_archive_ordinal(self):
        self.assertIn('E146.', self.episode['title'])
        self.assertTrue(self.doc['title'].startswith('145_'))
        self.assertEqual(match_transcript(self.episode, {'documents': [self.doc]}), self.doc)
        for docs in [[], [self.doc, self.doc], [{**self.doc, 'title': '145_别的节目'}]]:
            with self.assertRaises(DomainError):
                match_transcript(self.episode, {'documents': docs})

    def test_wrong_transcript_cannot_attach_to_episode(self):
        with self.assertRaises(DomainError):
            import_public_transcript(self.episode, {**self.doc, 'title': 'wrong'}, 'https://example.org')

    def test_unaligned_is_never_fabricated_as_timed(self):
        content = self.import_public()
        context = context_at(self.episode, content, 675000, 'RWA 是什么意思？')
        self.assertEqual(context.precision, 'chapter')
        self.assertEqual(context.chapter.start_ms, 675000)
        self.assertFalse(context.timed_segments)
        self.assertTrue(context.related_unaligned)
        self.assertTrue(all(s.start_ms is None and s.end_ms is None for s in context.related_unaligned))
        self.assertIn('面基', context.related_unaligned[0].source.attribution)

    def test_context_before_first_chapter_and_unknown_question(self):
        branch = self.service.create_branch(self.episode['id'], 0, '这个完全未知的专有词是什么意思？')
        turn = branch['turns'][0]
        self.assertEqual(turn['context']['precision'], 'none')
        self.assertEqual(turn['answer']['confidence'], 'insufficient_context')

    def test_timed_context_does_not_include_future_segments(self):
        payload = {'episode_id': self.episode['id'], 'source_url': 'https://example.org/aligned', 'attribution': 'Synthetic test',
                   'segments': [{'start_ms': 1000, 'end_ms': 2000, 'text': 'past'},
                                {'start_ms': 3000, 'end_ms': 4000, 'text': 'future'}]}
        content = data(import_timed(self.episode, payload))
        context = context_at(self.episode, content, 1500, 'what?')
        self.assertEqual(context.precision, 'timed')
        self.assertEqual([s.text for s in context.timed_segments], ['past'])
        for bad in [{**payload, 'episode_id': 'wrong'}, {**payload, 'segments': [{'start_ms': 2, 'end_ms': 1, 'text': 'bad'}]},
                    {**payload, 'segments': [{'start_ms': True, 'end_ms': 3, 'text': 'bad'}]}]:
            with self.assertRaises(DomainError):
                import_timed(self.episode, bad)

    def test_branch_persistence_multi_turn_resume_and_closed_guard(self):
        self.import_public()
        branch = self.service.create_branch(self.episode['id'], 675000, 'RWA 是什么意思？')
        answer = branch['turns'][0]['answer']
        self.assertEqual(answer['mode'], 'mock')
        self.assertIn('demo_glossary', answer['source_types'])
        self.assertEqual(len(answer['visual_summary']), 2)
        fresh_service = Service(Store(self.store.path))
        branch = fresh_service.add_turn(branch['id'], '还有未知概念呢？')
        self.assertEqual(len(branch['turns']), 2)
        resumed = fresh_service.resume(branch['id'])
        self.assertEqual(resumed['resume_position_ms'], 670000)
        self.assertEqual(fresh_service.resume(branch['id']), resumed)
        with self.assertRaises(DomainError) as error:
            fresh_service.add_turn(branch['id'], 'another question')
        self.assertEqual(error.exception.status, 409)

    def test_rewind_clamped_at_start(self):
        self.assertEqual(self.service.create_branch(self.episode['id'], 2000, 'RWA')['resume_position_ms'], 0)

    def test_invalid_anchor_and_question(self):
        for anchor in [-1, True, 1.5, float('nan'), self.episode['duration_ms'] + 1]:
            with self.subTest(anchor=anchor), self.assertRaises(DomainError):
                self.service.create_branch(self.episode['id'], anchor, 'RWA')
        for question in ['', '  ', None, 'x' * 2001]:
            with self.assertRaises(DomainError):
                self.service.create_branch(self.episode['id'], 0, question)
        with self.assertRaises(DomainError):
            self.service.create_branch(self.episode['id'], 0, 'RWA', 30001)

    def test_concurrent_turn_appends_not_lost(self):
        branch = self.service.create_branch(self.episode['id'], 1000, 'RWA')
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i: self.service.add_turn(branch['id'], f'问题 {i}'), range(8)))
        self.assertEqual(len(self.store.get('branches', branch['id'])['turns']), 9)

    def test_select_unique_episode(self):
        self.assertEqual(select_episode(self.store, '财富在β中')['id'], self.episode['id'])
        with self.assertRaises(DomainError):
            select_episode(self.store, 'not here')

    def test_non_https_sources_refused(self):
        for url in ['file:///etc/passwd', 'http://example.org', 'ftp://example.org']:
            with self.assertRaises(DomainError):
                fetch(url)


if __name__ == '__main__':
    unittest.main()
