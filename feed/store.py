"""data/ への保存: daily JSON, papers.jsonl, seen.json, index.json。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from .common import DATA, title_key

PAPER_FIELDS = ["id", "doi", "arxiv_id", "title", "title_ja", "authors", "venue", "date",
                "url", "abstract", "summary_ja", "reason_ja", "tags", "score", "author_hits", "first_seen"]


def _read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    tmp.replace(path)


class Seen:
    """表示済みID（重複防止）。同じ日に再実行した場合は同じ結果を出せるよう、当日分は除外しない。"""

    def __init__(self):
        self.path = DATA / "seen.json"
        d = _read(self.path, {})
        self.ids: dict[str, str] = d.get("ids", {})
        self.titles: dict[str, str] = d.get("titles", {})

    @property
    def empty(self) -> bool:
        return not self.ids

    def keys(self, it: dict) -> list[str]:
        ks = [it["id"]]
        if it.get("doi"):
            ks.append("doi:" + it["doi"])
        if it.get("arxiv_id"):
            ks.append("arxiv:" + it["arxiv_id"])
        return ks

    def is_old(self, it: dict, today: str) -> bool:
        for k in self.keys(it):
            if k in self.ids and self.ids[k] < today:
                return True
        tk = title_key(it["title"])
        return bool(tk) and tk in self.titles and self.titles[tk] < today

    def add(self, it: dict, today: str):
        for k in self.keys(it):
            self.ids.setdefault(k, today)
        tk = title_key(it["title"])
        if tk:
            self.titles.setdefault(tk, today)

    def save(self, today: datetime, news_days: int):
        # 論文IDは永久に保持、それ以外（ニュース）は保存期間+30日で削除
        cutoff = (today - timedelta(days=news_days + 30)).strftime("%Y-%m-%d")
        ids = {k: v for k, v in self.ids.items() if v >= cutoff or k.startswith(("doi:", "arxiv:"))}
        _write(self.path, {"ids": ids, "titles": self.titles})


def append_papers(items: list[dict], today: str):
    """論文を1行1本で累積保存（将来の過去論文データベース用）。既存IDは追記しない。"""
    path = DATA / "papers.jsonl"
    have = set()
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    have.add(json.loads(line)["id"])
                except (json.JSONDecodeError, KeyError):
                    pass
    n = 0
    with open(path, "a", encoding="utf-8") as f:
        for it in items:
            if it["id"] in have:
                continue
            rec = {k: it.get(k) for k in PAPER_FIELDS}
            rec["first_seen"] = today
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    return n


def save_daily(date: str, payload: dict, today: datetime, news_days: int):
    _write(DATA / "daily" / f"{date}.json", payload)
    # 古い日次ファイルを削除（論文は papers.jsonl に残っている）
    cutoff = (today - timedelta(days=news_days)).strftime("%Y-%m-%d")
    files = sorted((DATA / "daily").glob("*.json"))
    for p in files:
        if p.stem < cutoff:
            p.unlink()
    dates = sorted((p.stem for p in (DATA / "daily").glob("*.json")), reverse=True)
    _write(DATA / "index.json", {"dates": dates, "latest": dates[0] if dates else None})
