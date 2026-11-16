import io
import os
import shutil
import tempfile
import unittest

import fitz


TEST_DATA_DIR = tempfile.mkdtemp(prefix="pdfcompleto-tests-")
os.environ["PDFCOMPLETO_DATA_DIR"] = TEST_DATA_DIR
os.environ["SECRET_KEY"] = "test-secret-key"

from app import app  # noqa: E402


class RedactionSessionTestCase(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()

        document = fitz.open()
        document.new_page(width=595, height=842)
        buffer = io.BytesIO()
        document.save(buffer)
        document.close()
        self.pdf_bytes = buffer.getvalue()

        with self.client.session_transaction() as flask_session:
            flask_session["original_pdf_path"] = None
            flask_session["original_pdf_bytes"] = self.pdf_bytes
            flask_session["redactions"] = []

    def tearDown(self):
        with self.client.session_transaction() as flask_session:
            flask_session.clear()

    def session_redactions(self):
        with self.client.session_transaction() as flask_session:
            return list(flask_session.get("redactions") or [])

    def test_undo_after_saving_pdf_keeps_history_and_succeeds(self):
        redaction = {
            "page": 1,
            "x": 0.1,
            "y": 0.2,
            "w": 0.3,
            "h": 0.1,
        }

        sync_response = self.client.post(
            "/apply_redaction_session",
            json={"redactions": [redaction]},
        )
        self.assertEqual(sync_response.status_code, 200)

        save_response = self.client.post(
            "/apply_edits",
            json={
                "edits": {"tarjas": [redaction], "texts": []},
                "page_order": [1],
                "page_rotations": {},
            },
        )
        self.assertEqual(save_response.status_code, 200)
        self.assertEqual(save_response.mimetype, "application/pdf")

        # Salvar não pode apagar o histórico usado pelo botão Desfazer.
        self.assertEqual(len(self.session_redactions()), 1)

        undo_response = self.client.post(
            "/undo_last_redaction",
            json={"redactions": []},
        )
        self.assertEqual(undo_response.status_code, 200)
        self.assertEqual(undo_response.mimetype, "application/pdf")
        self.assertEqual(self.session_redactions(), [])

    def test_undo_without_snapshot_removes_last_server_redaction(self):
        with self.client.session_transaction() as flask_session:
            flask_session["redactions"] = [
                {
                    "page": 1,
                    "xPercent": 0.1,
                    "yPercent": 0.2,
                    "widthPercent": 0.3,
                    "heightPercent": 0.1,
                },
                {
                    "page": 1,
                    "xPercent": 0.4,
                    "yPercent": 0.5,
                    "widthPercent": 0.2,
                    "heightPercent": 0.1,
                },
            ]

        undo_response = self.client.post("/undo_last_redaction")
        self.assertEqual(undo_response.status_code, 200)
        self.assertEqual(len(self.session_redactions()), 1)

    def test_local_pdf_worker_is_served_and_configured(self):
        page_response = self.client.get("/")
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("/static/pdf.worker.min.js", page_response.get_data(as_text=True))
        page_response.close()

        worker_response = self.client.get("/static/pdf.worker.min.js")
        self.assertEqual(worker_response.status_code, 200)
        self.assertIn("javascript", worker_response.content_type)
        worker_response.close()

    def test_redaction_snapshot_replaces_server_history(self):
        first = {
            "page": 1,
            "x": 0.1,
            "y": 0.2,
            "w": 0.3,
            "h": 0.1,
        }
        second = {
            "page": 1,
            "x": 0.4,
            "y": 0.5,
            "w": 0.2,
            "h": 0.1,
        }

        response = self.client.post(
            "/apply_redaction_session",
            json={"redactions": [first, second]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["redactions_len"], 2)

        response = self.client.post(
            "/apply_redaction_session",
            json={"redactions": [second]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["redactions_len"], 1)
        self.assertEqual(len(self.session_redactions()), 1)


def tearDownModule():
    shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
