"""推し診断票メーカー oshidiag

好きな対象（キャラ・選手・作品など）のステータスを入力すると、
健康診断票風のサマリーを生成するツール。2件の比較もできる。
単一ファイル Flask + SQLite（ステータスは JSON で保存）。
"""
import json
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, g, jsonify, redirect, render_template_string, request, url_for, abort

app = Flask(__name__)
JST = ZoneInfo("Asia/Tokyo")
DB_PATH = os.environ.get("OSHIDIAG_DB", os.path.join(os.path.dirname(__file__), "oshidiag.db"))
MAX_STATS = 6


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '',
            comment TEXT NOT NULL DEFAULT '',
            stats TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL
        );
        """
    )
    db.commit()
    db.close()


def load_stats(row):
    try:
        return json.loads(row["stats"])
    except (ValueError, TypeError):
        return []


def overall(stats):
    if not stats:
        return 0
    return round(sum(s["score"] for s in stats) / len(stats))


def grade(avg):
    if avg >= 90:
        return "S"
    if avg >= 75:
        return "A"
    if avg >= 60:
        return "B"
    if avg >= 40:
        return "C"
    return "D"


INDEX = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>推し診断票メーカー</title>
<style>body{font-family:sans-serif;max-width:680px;margin:2em auto;padding:0 1em}
input{padding:.3em}</style>
</head><body>
<h1>推し診断票メーカー</h1>
<h2>診断票を作る</h2>
<form method="post" action="{{ url_for('create_entry') }}">
  <label>対象名 <input type="text" name="name" required></label>
  <label>カテゴリ <input type="text" name="category" placeholder="例：キャラ、選手、作品"></label><br>
  <label>総合コメント <input type="text" name="comment" size="50"></label>
  <h3>ステータス（最大6項目、0〜100）</h3>
  {% for i in range(1, max_stats + 1) %}
  <div><input type="text" name="label{{ i }}" placeholder="項目名 {{ i }}">
  <input type="number" name="score{{ i }}" min="0" max="100" placeholder="0-100"></div>
  {% endfor %}
  <button type="submit">診断票を作る</button>
</form>

<h2>診断票の一覧</h2>
<ul>
{% for e in entries %}
<li><a href="{{ url_for('detail', eid=e.id) }}">{{ e.name }}</a>（{{ e.category }}）
  <form method="post" action="{{ url_for('delete_entry', eid=e.id) }}" style="display:inline"><button>削除</button></form></li>
{% else %}<li>まだ診断票がありません</li>{% endfor %}
</ul>

{% if entries|length >= 2 %}
<h2>2件を比較する</h2>
<form method="get" action="{{ url_for('compare') }}">
  <select name="a">{% for e in entries %}<option value="{{ e.id }}">{{ e.name }}</option>{% endfor %}</select>
  <select name="b">{% for e in entries %}<option value="{{ e.id }}">{{ e.name }}</option>{% endfor %}</select>
  <button type="submit">比較する</button>
</form>
{% endif %}
</body></html>"""

CARD = """
<div class="card">
  <h2>診断票：{{ e.name }}</h2>
  <p>カテゴリ：{{ e.category }} ／ 総合評価：<strong>{{ g }}</strong>（平均 {{ avg }}）</p>
  {% for s in stats %}
  <div class="row"><span class="label">{{ s.label }}</span>
    <span class="barwrap"><span class="bar" style="width:{{ s.score }}%"></span></span>
    <span>{{ s.score }}</span></div>
  {% else %}<p>ステータス未入力</p>{% endfor %}
  <p>総合コメント：{{ e.comment }}</p>
  <p class="small">発行日：{{ e.created_at }}</p>
</div>"""

DETAIL = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>診断票 - {{ e.name }}</title>
<style>body{font-family:sans-serif;max-width:680px;margin:2em auto;padding:0 1em}
.card{border:2px solid #333;padding:1em;border-radius:6px;background:#fffef5}
.row{display:flex;align-items:center;gap:.5em;margin:.3em 0}
.label{width:8em}.barwrap{flex:1;background:#eee;height:1em}
.bar{display:block;height:100%;background:#4a9}.small{color:#666}</style>
</head><body>
""" + CARD + """
<p><a href="{{ url_for('index') }}">一覧へ戻る</a></p>
</body></html>"""

COMPARE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>比較 - 推し診断票</title>
<style>body{font-family:sans-serif;max-width:900px;margin:2em auto;padding:0 1em}
.wrap{display:flex;gap:1em}.card{flex:1;border:2px solid #333;padding:1em;border-radius:6px;background:#fffef5}
.row{display:flex;align-items:center;gap:.5em;margin:.3em 0}
.label{width:7em}.barwrap{flex:1;background:#eee;height:1em}
.bar{display:block;height:100%;background:#4a9}.small{color:#666}</style>
</head><body>
<h1>比較</h1>
<div class="wrap">
""" + CARD.replace("e.name", "a.name").replace("{{ e.", "{{ a.").replace("stats }}", "stats_a }}").replace("{{ g }}", "{{ ga }}").replace("{{ avg }}", "{{ avga }}") + CARD.replace("e.name", "b.name").replace("{{ e.", "{{ b.").replace("stats }}", "stats_b }}").replace("{{ g }}", "{{ gb }}").replace("{{ avg }}", "{{ avgb }}") + """
</div>
<p><a href="{{ url_for('index') }}">一覧へ戻る</a></p>
</body></html>"""


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/")
def index():
    db = get_db()
    entries = db.execute("SELECT * FROM entries ORDER BY id DESC").fetchall()
    return render_template_string(INDEX, entries=entries, max_stats=MAX_STATS)


@app.route("/entries", methods=["POST"])
def create_entry():
    name = (request.form.get("name") or "").strip()
    if not name:
        return redirect(url_for("index"))
    stats = []
    for i in range(1, MAX_STATS + 1):
        label = (request.form.get(f"label{i}") or "").strip()
        raw = request.form.get(f"score{i}")
        if label and raw not in (None, ""):
            try:
                score = int(raw)
            except ValueError:
                continue
            stats.append({"label": label, "score": min(max(score, 0), 100)})
    db = get_db()
    cur = db.execute(
        "INSERT INTO entries(name, category, comment, stats, created_at) VALUES(?, ?, ?, ?, ?)",
        (
            name,
            (request.form.get("category") or "").strip(),
            (request.form.get("comment") or "").strip(),
            json.dumps(stats, ensure_ascii=False),
            datetime.now(JST).strftime("%Y-%m-%d %H:%M"),
        ),
    )
    db.commit()
    return redirect(url_for("detail", eid=cur.lastrowid))


@app.route("/entries/<int:eid>")
def detail(eid):
    db = get_db()
    row = db.execute("SELECT * FROM entries WHERE id = ?", (eid,)).fetchone()
    if row is None:
        abort(404)
    stats = load_stats(row)
    avg = overall(stats)
    return render_template_string(DETAIL, e=row, stats=stats, avg=avg, g=grade(avg))


@app.route("/compare")
def compare():
    db = get_db()
    try:
        a_id = int(request.args.get("a", "0"))
        b_id = int(request.args.get("b", "0"))
    except ValueError:
        return redirect(url_for("index"))
    a = db.execute("SELECT * FROM entries WHERE id = ?", (a_id,)).fetchone()
    b = db.execute("SELECT * FROM entries WHERE id = ?", (b_id,)).fetchone()
    if a is None or b is None:
        return redirect(url_for("index"))
    stats_a, stats_b = load_stats(a), load_stats(b)
    avga, avgb = overall(stats_a), overall(stats_b)
    return render_template_string(
        COMPARE, a=a, b=b, stats_a=stats_a, stats_b=stats_b,
        avga=avga, avgb=avgb, ga=grade(avga), gb=grade(avgb),
    )


@app.route("/entries/<int:eid>/delete", methods=["POST"])
def delete_entry(eid):
    db = get_db()
    db.execute("DELETE FROM entries WHERE id = ?", (eid,))
    db.commit()
    return redirect(url_for("index"))


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
