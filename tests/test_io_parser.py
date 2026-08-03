import tempfile
import unittest
from pathlib import Path

from io_parser import (
    _is_safe_url,
    _truncate,
    format_attachments_for_prompt,
    ingest_folder,
    parse_uploaded_file,
)


class IOParserTests(unittest.TestCase):
    def test_truncate(self):
        short_text = "hello world"
        self.assertEqual(_truncate(short_text, 20), short_text)

        long_text = "a" * 100
        truncated = _truncate(long_text, 10)
        self.assertTrue(truncated.endswith("\n...[truncated]"))
        self.assertTrue(truncated.startswith("aaaaaaaaaa"))

    def test_parse_uploaded_file_text_and_json(self):
        # Markdown / Code
        parsed_md = parse_uploaded_file("notes.md", "text/markdown", b"# Title\nContent")
        self.assertEqual(parsed_md["kind"], "text")
        self.assertIn("# Title", parsed_md["text"])

        # Pretty JSON
        parsed_json = parse_uploaded_file("data.json", "application/json", b'{"key": "value"}')
        self.assertEqual(parsed_json["kind"], "text")
        self.assertIn('"key": "value"', parsed_json["text"])

        # Image metadata
        parsed_img = parse_uploaded_file("diagram.png", "image/png", b"fake_bytes")
        self.assertEqual(parsed_img["kind"], "image")
        self.assertIn("diagram.png", parsed_img["summary"])

    def test_format_attachments_for_prompt(self):
        attachments = [
            {"kind": "text", "filename": "doc.txt", "content_type": "text/plain", "text": "Sample text"},
            {"kind": "image", "filename": "shot.png", "content_type": "image/png"},
            {"kind": "unsupported", "filename": "bin.dat", "summary": "Binary data"},
        ]
        formatted = format_attachments_for_prompt(attachments)
        self.assertIn("[Uploaded Attachments]", formatted)
        self.assertIn("--- FILE: doc.txt (text/plain) ---", formatted)
        self.assertIn("--- IMAGE: shot.png (image/png) ---", formatted)
        self.assertIn("--- ATTACHMENT: Binary data ---", formatted)

    def test_proportional_attachment_budgeting(self):
        attachments = [
            {"kind": "text", "filename": "large1.txt", "content_type": "text/plain", "text": "A" * 10000},
            {"kind": "text", "filename": "large2.txt", "content_type": "text/plain", "text": "B" * 10000},
        ]
        formatted = format_attachments_for_prompt(attachments, max_total_chars=1000)
        self.assertIn("...[proportionally budget-truncated]", formatted)
        self.assertLess(len(formatted), 1500)

    def test_ingest_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "doc1.md").write_text("# Doc 1", encoding="utf-8")
            (root / "config.json").write_text('{"a": 1}', encoding="utf-8")

            # Subdir to ignore
            git_dir = root / ".git"
            git_dir.mkdir()
            (git_dir / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")

            attachments = ingest_folder(str(root))
            self.assertEqual(len(attachments), 2)
            filenames = [a["filename"] for a in attachments]
            self.assertIn("doc1.md", filenames)
            self.assertIn("config.json", filenames)
            self.assertNotIn(".git/HEAD", filenames)

    def test_is_safe_url(self):
        self.assertFalse(_is_safe_url("ftp://example.com"))
        self.assertFalse(_is_safe_url("http://localhost:8000"))
        self.assertFalse(_is_safe_url("http://127.0.0.1/admin"))


if __name__ == "__main__":
    unittest.main()
