import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from conference_paper.eccv_catalog import CatalogPaper
from conference_paper.mapping_client import (
    ArxivClient,
    FetchError,
    fingerprint,
    load_checkpoint,
    sample_papers,
)

EMPTY = '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'


class ClientTests(unittest.TestCase):
    def test_cache_and_url_encoding(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            client = ArxivClient(
                Path(directory), fetch=lambda url: calls.append(url) or EMPTY
            )
            self.assertEqual(client.search('ti:"a b"'), [])
            self.assertEqual(client.search('ti:"a b"'), [])
            self.assertEqual(len(calls), 1)
            self.assertIn("search_query=ti%3A%22a+b%22", calls[0])

    def test_bad_feed_not_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            client = ArxivClient(Path(directory), fetch=lambda url: "<html/>")
            with self.assertRaises(ValueError):
                client.search('ti:"x"')
            self.assertEqual(list(Path(directory).glob("*.xml")), [])

    def test_rate_limit_is_serial(self):
        times = []
        clock = [0.0]

        def sleep(seconds):
            clock[0] += seconds

        with tempfile.TemporaryDirectory() as directory:
            client = ArxivClient(
                Path(directory),
                fetch=lambda url: times.append(clock[0]) or EMPTY,
                clock=lambda: clock[0],
                sleep=sleep,
            )
            client.search('ti:"one"')
            client.search('ti:"two"')
        self.assertGreaterEqual(times[1] - times[0], 3.1)

    def test_transport_failure_is_not_not_found(self):
        def fail(url):
            raise FetchError("timeout")

        with tempfile.TemporaryDirectory() as directory:
            client = ArxivClient(
                Path(directory), fetch=fail, sleep=lambda seconds: None
            )
            with self.assertRaises(FetchError):
                client.search('ti:"x"')

    def test_truncated_results_cannot_auto_match(self):
        feed = EMPTY.replace(
            "></feed>",
            ' xmlns:o="http://a9.com/-/spec/opensearch/1.1/"><o:totalResults>100</o:totalResults></feed>',
        )
        with tempfile.TemporaryDirectory() as directory:
            client = ArxivClient(Path(directory), fetch=lambda url: feed)
            with self.assertRaises(ValueError):
                client.search('ti:"x"')

    def test_resume_recovers_only_incomplete_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.jsonl"
            path.write_text('{"fingerprint":"ok"}\n{"fingerprint":', encoding="utf-8")
            self.assertEqual(load_checkpoint(path), {"ok": {"fingerprint": "ok"}})
            self.assertTrue(list(Path(directory).glob("*.interrupted-*")))
            with path.open("a", encoding="utf-8") as handle:
                handle.write('{"fingerprint":"second"}\n')
            self.assertEqual(len(load_checkpoint(path)), 2)

    def test_corrupt_middle_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.jsonl"
            path.write_text('bad\n{"fingerprint":"ok"}\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_checkpoint(path)

    def test_input_changes_invalidate_resume(self):
        first = CatalogPaper(
            "eccv:2026:1",
            "Title",
            ["Alice Smith"],
            "https://eccv.ecva.net/virtual/2026/poster/1",
        )
        second = CatalogPaper(
            "eccv:2026:1", "Changed", ["Alice Smith"], first.detail_url
        )
        self.assertNotEqual(fingerprint(first), fingerprint(second))

    def test_sample_is_deterministic_and_covers_topics(self):
        papers = [
            CatalogPaper(str(i), str(i), [], "url", topic=str(i % 3)) for i in range(12)
        ]
        self.assertEqual(
            sample_papers(papers, 3), sample_papers(list(reversed(papers)), 3)
        )
        self.assertEqual(len({p.topic for p in sample_papers(papers, 3)}), 3)


if __name__ == "__main__":
    unittest.main()
