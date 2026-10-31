import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["OSHIDIAG_DB"] = _tmp.name

import app as app_module  # noqa: E402


def make_entry(client, name, label="かわいさ", score=80):
    return client.post(
        "/entries",
        data={"name": name, "category": "キャラ", "comment": "最高",
              "label1": label, "score1": str(score)},
    )


class OshiDiagTest(unittest.TestCase):
    def setUp(self):
        app_module.init_db()
        self.client = app_module.app.test_client()
        with app_module.app.app_context():
            conn = app_module.get_db()
            conn.execute("DELETE FROM entries")
            conn.commit()

    def test_healthz(self):
        res = self.client.get("/healthz")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "ok")

    def test_create_and_detail(self):
        res = make_entry(self.client, "推しA")
        self.assertEqual(res.status_code, 302)
        with app_module.app.app_context():
            conn = app_module.get_db()
            row = conn.execute("SELECT * FROM entries").fetchone()
            stats = json.loads(row["stats"])
            eid = row["id"]
        self.assertEqual(stats, [{"label": "かわいさ", "score": 80}])
        body = self.client.get(f"/entries/{eid}").get_data(as_text=True)
        self.assertIn("推しA", body)
        self.assertIn("かわいさ", body)
        self.assertIn("width:80%", body)

    def test_max_six_stats(self):
        data = {"name": "多項目", "category": "", "comment": ""}
        for i in range(1, 8):
            data[f"label{i}"] = f"項目{i}"
            data[f"score{i}"] = "50"
        self.client.post("/entries", data=data)
        with app_module.app.app_context():
            conn = app_module.get_db()
            stats = json.loads(conn.execute("SELECT stats FROM entries").fetchone()["stats"])
        self.assertLessEqual(len(stats), 6)

    def test_score_clamped(self):
        self.client.post("/entries", data={"name": "過剰", "label1": "力", "score1": "150"})
        with app_module.app.app_context():
            conn = app_module.get_db()
            stats = json.loads(conn.execute("SELECT stats FROM entries").fetchone()["stats"])
        self.assertEqual(stats[0]["score"], 100)

    def test_compare(self):
        make_entry(self.client, "推しA", score=90)
        make_entry(self.client, "推しB", score=40)
        with app_module.app.app_context():
            conn = app_module.get_db()
            ids = [r["id"] for r in conn.execute("SELECT id FROM entries ORDER BY id")]
        body = self.client.get(f"/compare?a={ids[0]}&b={ids[1]}").get_data(as_text=True)
        self.assertIn("推しA", body)
        self.assertIn("推しB", body)

    def test_delete(self):
        make_entry(self.client, "消える推し")
        with app_module.app.app_context():
            conn = app_module.get_db()
            eid = conn.execute("SELECT id FROM entries").fetchone()["id"]
        self.client.post(f"/entries/{eid}/delete")
        self.assertEqual(self.client.get(f"/entries/{eid}").status_code, 404)

    def test_grade(self):
        self.assertEqual(app_module.grade(95), "S")
        self.assertEqual(app_module.grade(10), "D")


if __name__ == "__main__":
    unittest.main()
