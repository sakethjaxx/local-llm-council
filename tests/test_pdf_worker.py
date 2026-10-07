import io
import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

import fitz

import pdf_worker
from io_parser import parse_uploaded_file
from pdf_worker import PdfExtractionError, extract_pdf_text


def make_pdf(pages: int, text: str = "page {n} text") -> bytes:
    doc = fitz.open()
    for n in range(pages):
        doc.new_page().insert_text((72, 72), text.format(n=n + 1))
    data = doc.tobytes()
    doc.close()
    return data


class PdfWorkerTests(unittest.TestCase):
    def test_extracts_text_in_a_child_process(self):
        text = extract_pdf_text(make_pdf(3), 10_000)
        self.assertEqual([line for line in text.splitlines() if line], ["page 1 text", "page 2 text", "page 3 text"])

    def test_upload_path_uses_the_worker(self):
        parsed = parse_uploaded_file("report.pdf", "application/pdf", make_pdf(1, "quarterly numbers"))
        self.assertEqual(parsed["kind"], "text")
        self.assertIn("quarterly numbers", parsed["text"])

    def test_page_ceiling_and_text_limit(self):
        with patch.object(pdf_worker, "PDF_MAX_PAGES", 2):
            text = extract_pdf_text(make_pdf(5), 10_000)
        self.assertIn("page 2 text", text)
        self.assertNotIn("page 3 text", text)
        self.assertIn("only the first 2 pages were read", text)
        self.assertLessEqual(len(extract_pdf_text(make_pdf(3, "x" * 60), 50)), 51)

    def test_deadline_stops_the_child(self):
        with patch.object(pdf_worker, "PDF_TIMEOUT_S", 0.05):
            with self.assertRaisesRegex(PdfExtractionError, "exceeded"):
                extract_pdf_text(make_pdf(1), 1000)

    def test_broken_or_killed_child_fails_safely(self):
        with self.assertRaisesRegex(PdfExtractionError, "could not be read"):
            extract_pdf_text(b"%PDF-1.4 garbage", 1000)
        killed = subprocess.CompletedProcess([], returncode=-9, stdout=b"", stderr=b"")
        with patch("pdf_worker.subprocess.run", return_value=killed):
            with self.assertRaisesRegex(PdfExtractionError, "memory and safety limits"):
                extract_pdf_text(make_pdf(1), 1000)

    @unittest.skipIf(sys.platform == "darwin", "macOS cannot enforce the ceiling; covered by the refusal test")
    def test_memory_ceiling_is_enforced_on_this_platform(self):
        script = (
            "import sys, pdf_worker\n"
            "assert pdf_worker.apply_memory_limit(200 * 1024 * 1024)\n"
            "try:\n"
            "    block = bytearray(600 * 1024 * 1024)\n"
            "except MemoryError:\n"
            "    sys.exit(3)\n"
            "sys.exit(0)\n"
        )
        env = {**os.environ, "PYTHONPATH": os.path.dirname(pdf_worker.__file__)}
        result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, timeout=60)
        self.assertNotEqual(result.returncode, 0, "allocation above the ceiling succeeded")

    def test_refuses_when_the_ceiling_cannot_be_enforced(self):
        stdout = io.StringIO()
        stdin = io.TextIOWrapper(io.BytesIO(make_pdf(1)))
        with patch("pdf_worker.apply_memory_limit", return_value=False), \
                patch.dict(os.environ, {"COUNCIL_PDF_ALLOW_UNLIMITED_MEMORY": ""}), \
                patch("sys.stdin", stdin), patch("sys.stdout", stdout):
            pdf_worker.main(["pdf_worker.py", "1000", "100", str(1 << 30)])
        self.assertIn("cannot enforce a memory limit", json.loads(stdout.getvalue())["error"])

        stdout = io.StringIO()
        stdin = io.TextIOWrapper(io.BytesIO(make_pdf(1, "allowed")))
        with patch("pdf_worker.apply_memory_limit", return_value=False), \
                patch.dict(os.environ, {"COUNCIL_PDF_ALLOW_UNLIMITED_MEMORY": "true"}), \
                patch("sys.stdin", stdin), patch("sys.stdout", stdout):
            pdf_worker.main(["pdf_worker.py", "1000", "100", str(1 << 30)])
        self.assertIn("allowed", json.loads(stdout.getvalue())["text"])


if __name__ == "__main__":
    unittest.main()
