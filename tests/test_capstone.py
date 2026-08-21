import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))
os.environ.setdefault("VISION_PROVIDER", "local")

import app
from api import GuardRequest, ReviewRequest
from pydantic import ValidationError


class CapstoneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.seed()
        app.run_batch()

    def test_schema_rejects_invalid_output(self):
        with self.assertRaises(ValueError):
            app.ImageTags.validate({"subject": "fox"})

    def test_schema_rejects_extra_fields_and_boolean_confidence(self):
        with self.assertRaises(ValueError):
            app.ImageTags.validate({"subject": "fox", "category": "animal", "attributes": ["wild"], "caption": "A fox", "confidence": True, "extra": "bad"})

    def test_normalized_tags_and_embeddings_are_persisted(self):
        db = app.connect()
        self.assertEqual(db.execute("SELECT COUNT(*) AS count FROM image_tags").fetchone()["count"], len(app.CORPUS))
        self.assertEqual(db.execute("SELECT COUNT(*) AS count FROM image_embeddings").fetchone()["count"], len(app.CORPUS))
        self.assertEqual(db.execute("SELECT COUNT(*) AS count FROM post_embeddings").fetchone()["count"], len(app.POSTS))
        db.close()

    def test_fox_ranks_first(self):
        result = app.suggestions("fox-post")
        self.assertEqual(result["match"]["image_id"], "fox-01")
        self.assertGreater(result["suggestions"][0]["similarity"], next(item["similarity"] for item in result["suggestions"] if item["image_id"] == "wolf-01"))

    def test_wolf_is_rejected(self):
        result = next(item for item in app.suggestions("fox-post")["suggestions"] if item["image_id"] == "wolf-01")
        self.assertFalse(result["accepted"])
        self.assertIn("mismatch", result["reason"])

    def test_wolf_topic_accepts_wolf(self):
        self.assertEqual(app.suggestions("wolf-post")["match"]["image_id"], "wolf-01")

    def test_no_match(self):
        result = app.suggestions("unmatched-post")
        self.assertIsNone(result["match"])
        self.assertEqual(result["message"], "No confident match found")
        self.assertTrue(all(item["reason"] for item in result["suggestions"]))

    def test_eval(self):
        self.assertEqual(app.evaluate()["top1_precision"], 1.0)
        self.assertEqual(app.evaluate()["total"], 3)

    def test_semantic_alias_vulpes(self):
        result = app.suggestions("vulpes-vulpes")
        self.assertEqual(result["match"]["image_id"], "fox-01")

    def test_guard_rejects_wolf_with_reason(self):
        db = app.connect()
        post = db.execute("SELECT * FROM posts WHERE id='fox-post'").fetchone()
        wolf = db.execute("SELECT * FROM images WHERE id='wolf-01'").fetchone()
        ok, reason = app.guard(post, wolf, 0.5)
        db.close()
        self.assertFalse(ok)
        self.assertIn("category mismatch", reason)
        self.assertIn("expected red fox", reason)

    def test_low_confidence_flagged(self):
        db = app.connect()
        row = db.execute("SELECT status FROM images WHERE id='uncertain-01'").fetchone()
        db.close()
        self.assertEqual(row[0], "flagged")

    def test_batch_idempotency(self):
        first = app.run_batch("test-idempotency-key")
        second = app.run_batch("test-idempotency-key")
        self.assertEqual(first["id"], second["id"])

    def test_atomic_batch_claim(self):
        job = app.create_batch_job("claim-test")
        self.assertTrue(app.claim_batch_job(job["id"]))
        self.assertFalse(app.claim_batch_job(job["id"]))

    def test_retry_failure_is_persisted(self):
        job = app.create_batch_job("failure-test")
        with patch("providers.LocalProvider.classify", side_effect=RuntimeError("simulated provider outage")):
            with self.assertRaises(RuntimeError):
                app.run_batch("failure-test", job["id"])
        db = app.connect()
        failed = db.execute("SELECT status,retries,error FROM jobs WHERE id=?", (job["id"],)).fetchone()
        db.close()
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["retries"], 3)
        self.assertIn("simulated provider outage", failed["error"])

    def test_costs_are_attributed(self):
        db = app.connect()
        rows = db.execute("SELECT kind,model FROM costs WHERE job_id=(SELECT id FROM jobs WHERE status='completed' ORDER BY id DESC LIMIT 1)")
        db.close()
        self.assertEqual({row["kind"] for row in rows}, {"vision", "embedding"})
        self.assertTrue(all(row["model"] for row in rows))

    def test_api_boundary_validation(self):
        with self.assertRaises(ValidationError):
            GuardRequest(post_id="", image_id="wolf-01")
        with self.assertRaises(ValidationError):
            ReviewRequest(post_id="fox-post", image_id="fox-01", decision="maybe")


if __name__ == "__main__":
    unittest.main()
