import hashlib
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import map_eccv_arxiv as cli
from test_eccv_mapping import HTML

from conference_paper.arxiv_mapping import Candidate
from conference_paper.eccv_catalog import parse_catalog
from conference_paper.mapping_client import FetchError


class FakeClient:
    network_requests = 0
    cache_hits = 0

    def __init__(self, *args, **kwargs):
        pass

    def search(self, query):
        self.network_requests += 1
        return [Candidate("2601.12345", "A New Method", ["Alice Smith", "Bob Jones"])]


class CliTests(unittest.TestCase):
    def test_snapshot_checksum_is_stable_across_windows_newlines(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            args = SimpleNamespace(
                output=output, limit=1, refresh_cache=False, retry_unresolved=False
            )
            with patch.object(
                cli, "fetch_text", return_value=HTML.replace("\n", "\r\n")
            ), patch.object(cli, "ArxivClient", FakeClient), redirect_stdout(
                StringIO()
            ):
                self.assertEqual(cli.run(args), 0)
                before = (output / "mapping-checkpoint.jsonl").read_bytes()
                self.assertEqual(cli.run(args), 0)
            self.assertEqual(before, (output / "mapping-checkpoint.jsonl").read_bytes())
            summary = json.loads((output / "summary.json").read_text())
            self.assertEqual(
                summary["snapshot_sha256"],
                hashlib.sha256(
                    (output / "accepted-papers.html").read_bytes()
                ).hexdigest(),
            )

    def test_real_pipeline_exports_and_resumes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            args = SimpleNamespace(
                output=output, limit=1, refresh_cache=False, retry_unresolved=False
            )
            with patch.object(cli, "fetch_text", return_value=HTML), patch.object(
                cli, "ArxivClient", FakeClient
            ), redirect_stdout(StringIO()):
                self.assertEqual(cli.run(args), 0)
            record = json.loads(
                (output / "matched-papers.jsonl").read_text(encoding="utf-8")
            )
            self.assertEqual(record["arxiv_id"], "2601.12345")
            self.assertEqual(len(record["attempts"]), 1)
            before = (output / "mapping-checkpoint.jsonl").read_bytes()
            with patch.object(
                cli, "fetch_text", side_effect=AssertionError("Should reuse snapshot")
            ), patch.object(cli, "ArxivClient", FakeClient), redirect_stdout(
                StringIO()
            ):
                self.assertEqual(cli.run(args), 0)
            self.assertEqual(before, (output / "mapping-checkpoint.jsonl").read_bytes())
            summary = json.loads((output / "summary.json").read_text())
            self.assertEqual(summary["network_requests_this_run"], 0)
            self.assertFalse((output / ".mapping.lock").exists())

    def test_candidate_survives_later_network_error(self):
        client = FakeClient()
        client.search = unittest.mock.Mock(
            side_effect=[
                [
                    Candidate(
                        "2601.12345", "Changed Title", ["Alice Smith", "Bob Jones"]
                    )
                ],
                FetchError("HTTP 503"),
            ]
        )
        result = cli.resolve(parse_catalog(HTML)[0], client)
        self.assertEqual(result["status"], "error")
        self.assertEqual(len(result["candidates"]), 1)
        self.assertIsNone(result["arxiv_id"])

    def test_service_errors_stop_batch_without_marking_unvisited_not_found(self):
        html = "".join(HTML.replace("/poster/42", f"/poster/{i}") for i in range(5))

        class FailedClient(FakeClient):
            def search(self, query):
                raise FetchError("HTTP 503")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            args = SimpleNamespace(
                output=output, limit=0, refresh_cache=False, retry_unresolved=False
            )
            with patch.object(cli, "fetch_text", return_value=html), patch.object(
                cli, "ArxivClient", FailedClient
            ), redirect_stdout(StringIO()):
                self.assertEqual(cli.run(args), 2)
            summary = json.loads((output / "summary.json").read_text())
            self.assertEqual(summary["status_counts"], {"error": 3})
            self.assertEqual(summary["pending_count"], 2)
            self.assertEqual(
                len((output / "catalog.jsonl").read_text().splitlines()), 5
            )
            self.assertEqual((output / "matched-papers.jsonl").read_text(), "")

    def test_existing_lock_prevents_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / ".mapping.lock").touch()
            args = SimpleNamespace(output=output)
            with self.assertRaises(SystemExit):
                cli.run(args)


if __name__ == "__main__":
    unittest.main()
