import json, subprocess, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))
import app

class CapstoneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): app.seed(); app.run_batch()
    def test_schema_rejects_invalid_output(self):
        with self.assertRaises(ValueError): app.ImageTags.validate({"subject": "fox"})
    def test_fox_ranks_first(self): self.assertEqual(app.suggestions("fox-post")["match"]["image_id"], "fox-01")
    def test_wolf_is_rejected(self):
        result = next(x for x in app.suggestions("fox-post")["suggestions"] if x["image_id"] == "wolf-01")
        self.assertFalse(result["accepted"]); self.assertIn("mismatch", result["reason"])
    def test_wolf_topic_accepts_wolf(self): self.assertEqual(app.suggestions("wolf-post")["match"]["image_id"], "wolf-01")
    def test_no_match(self): self.assertIsNone(app.suggestions("unmatched-post")["match"])
    def test_eval(self): self.assertEqual(app.evaluate()["top1_precision"], 1.0)
    def test_semantic_alias_vulpes(self):
        # "Vulpes vulpes" is the scientific name for red fox; concepts match despite different words.
        result = app.suggestions("vulpes-vulpes")
        self.assertEqual(result["match"]["image_id"], "fox-01")
    def test_guard_rejects_wolf_with_reason(self):
        db = app.connect()
        post = db.execute("SELECT * FROM posts WHERE id='fox-post'").fetchone()
        wolf = db.execute("SELECT * FROM images WHERE id='wolf-01'").fetchone()
        ok, reason = app.guard(post, wolf, 0.5)
        db.close()
        self.assertFalse(ok); self.assertIn("category mismatch", reason); self.assertIn("expected red fox", reason)
    def test_low_confidence_flagged(self):
        db = app.connect(); row = db.execute("SELECT status FROM images WHERE id='uncertain-01'").fetchone(); db.close(); self.assertEqual(row[0], "flagged")
    def test_batch_idempotency(self):
        first = app.run_batch("test-idempotency-key")
        second = app.run_batch("test-idempotency-key")
        self.assertEqual(first["id"], second["id"])
    def test_costs_are_attributed(self):
        db = app.connect(); rows = db.execute("SELECT kind,model FROM costs WHERE job_id=(SELECT id FROM jobs ORDER BY id DESC LIMIT 1)"); db.close()
        self.assertEqual({row["kind"] for row in rows}, {"vision", "embedding"})

if __name__ == "__main__": unittest.main()
