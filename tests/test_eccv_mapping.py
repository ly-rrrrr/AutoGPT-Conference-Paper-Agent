import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from conference_paper.arxiv_mapping import Candidate, decide, parse_feed, queries
from conference_paper.eccv_catalog import parse_catalog

HTML = """<table id="event-list-2026-poster-nodates-filter-vslinks-table">
<tr><th>Title</th></tr><tr><td><a href="/virtual/2026/poster/42">A New Method</a>
<a href="https://example.org">Project Page</a><div><i>Alice Smith ⋅ Bob Jones</i></div></td>
<td class="elc-keywords">Vision</td><td class="elc-where">Poster Session 1</td></tr></table>"""


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.paper = parse_catalog(HTML)[0]
        self.candidate = Candidate(
            "2601.12345", "A New Method", ["Alice Smith", "Bob Jones"]
        )

    def test_catalog_keeps_metadata(self):
        self.assertEqual(self.paper.paper_id, "eccv:2026:42")
        self.assertEqual(self.paper.authors, ["Alice Smith", "Bob Jones"])
        self.assertEqual(self.paper.title, "A New Method")
        self.assertEqual(self.paper.topic, "Vision")
        self.assertEqual(self.paper.project_urls, ["https://example.org"])

    def test_missing_authors_preserved(self):
        paper = parse_catalog(HTML.replace("Alice Smith ⋅ Bob Jones", ""))[0]
        self.assertEqual(paper.authors, [])
        self.assertEqual(decide(paper, [self.candidate])["status"], "needs_review")

    def test_empty_catalog_fails(self):
        with self.assertRaises(ValueError):
            parse_catalog("<html>Service unavailable</html>")

    def test_duplicate_rows_deduplicate(self):
        statistics = {}
        self.assertEqual(len(parse_catalog(HTML + HTML, statistics)), 1)
        self.assertEqual(statistics["official_row_count"], 2)
        self.assertEqual(statistics["duplicate_row_count"], 1)

    def test_conflicting_duplicate_fails(self):
        with self.assertRaises(ValueError):
            parse_catalog(HTML + HTML.replace("A New Method", "Different"))

    def test_external_poster_is_not_official(self):
        with self.assertRaises(ValueError):
            parse_catalog(
                HTML.replace(
                    "/virtual/2026/poster/42",
                    "https://evil.example/virtual/2026/poster/42",
                )
            )

    def test_unique_exact_title_and_authors_match(self):
        result = decide(self.paper, [self.candidate])
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["arxiv_id"], "2601.12345")

    def test_case_punctuation_and_order(self):
        candidate = Candidate(
            "2601.12345", "A NEW: Method!", ["Bob Jones", "Alice Smith"]
        )
        self.assertEqual(decide(self.paper, [candidate])["status"], "matched")

    def test_wrong_first_name_is_not_a_match(self):
        candidate = Candidate("2601.12345", "A New Method", ["Alan Smith", "Ben Jones"])
        self.assertEqual(decide(self.paper, [candidate])["status"], "needs_review")

    def test_initials_require_review(self):
        candidate = Candidate("2601.12345", "A New Method", ["A. Smith", "B. Jones"])
        self.assertEqual(decide(self.paper, [candidate])["status"], "needs_review")

    def test_two_ids_require_review(self):
        second = Candidate("2601.99999", "A New Method", ["Alice Smith", "Bob Jones"])
        result = decide(self.paper, [self.candidate, second])
        self.assertEqual(result["status"], "needs_review")
        self.assertIsNone(result["arxiv_id"])

    def test_changed_title_requires_review(self):
        candidate = Candidate(
            "2601.12345", "A Better New Method", ["Alice Smith", "Bob Jones"]
        )
        self.assertEqual(decide(self.paper, [candidate])["status"], "needs_review")

    def test_no_candidates_not_found(self):
        self.assertEqual(decide(self.paper, [])["status"], "not_found")

    def test_query_is_title_scoped(self):
        query = queries(self.paper)
        self.assertTrue(query[0].startswith('ti:"'))
        self.assertIn('au:"smith"', query[1])

    def test_atom_versions_deduplicate(self):
        entries = "".join(
            f"""<entry><id>http://arxiv.org/abs/2601.12345v{v}</id>
        <title>A New Method</title><author><name>Alice Smith</name></author>
        <author><name>Bob Jones</name></author><summary>Evidence</summary></entry>"""
            for v in [1, 2]
        )
        candidates = parse_feed(
            f'<feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].arxiv_id, "2601.12345")

    def test_error_feed_is_not_empty_success(self):
        with self.assertRaises(ValueError):
            parse_feed(
                '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/api/errors#x</id><title>Error</title></entry></feed>'
            )

    def test_html_is_not_empty_feed(self):
        with self.assertRaises(ValueError):
            parse_feed("<html><body>Unavailable</body></html>")


if __name__ == "__main__":
    unittest.main()
