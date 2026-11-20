"""ニュース・記事の取得（RSS / Atom）。"""
from __future__ import annotations

import calendar
import re
from datetime import datetime, timezone

import feedparser

from .common import UA, http_get, strip_tags, url_id


def _date(e, tz) -> str:
    for k in ("published_parsed", "updated_parsed"):
        t = e.get(k)
        if t:
            return datetime.fromtimestamp(calendar.timegm(t), timezone.utc).astimezone(tz).strftime("%Y-%m-%d")
    return ""


def _text(e) -> str:
    """本文（content:encoded）があれば本文、なければ概要。Gemini には先頭だけ送る。"""
    body = ""
    for c in e.get("content") or []:
        if len(c.get("value", "")) > len(body):
            body = c["value"]
    if not body:
        body = e.get("summary", "") or e.get("description", "")
    return strip_tags(body)[:4000]


def _clean_url(u: str) -> str:
    return re.sub(r"[?&](utm_[^=&]+|rss|ref)=[^&]*", "", u or "").rstrip("?&")


def fetch_feed(feed: dict, today: datetime, since: str, status: dict) -> list[dict]:
    """feed: {name, url, lang, label, headline_only, section, max_items}"""
    try:
        r = http_get(feed["url"], headers={"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"}, tries=2)
        parsed = feedparser.parse(r.content)
    except Exception as e:  # noqa: BLE001
        status[feed["name"]] = f"取得失敗: {str(e)[:80]}"
        print(f"  {feed['name']}: 取得失敗 {e}")
        return []
    out = []
    today_s = today.strftime("%Y-%m-%d")
    for e in parsed.entries[: feed.get("max_items", 60)]:
        url = _clean_url(e.get("link", ""))
        title = strip_tags(e.get("title", ""))
        if not url or not title:
            continue
        date = _date(e, today.tzinfo) or today_s  # 日付のないフィード（Nikkei Asia など）は取得日
        if date < since:
            continue
        out.append({
            "kind": "news", "id": url_id(url), "url": url, "title": title,
            "abstract": "" if feed.get("headline_only") else _text(e),
            "venue": feed["name"], "lang": feed.get("lang", "en"), "date": min(date, today_s),
            "label": feed.get("label", ""), "headline_only": bool(feed.get("headline_only")),
            "section": feed.get("section"), "pinned": bool(feed.get("pinned")),
            "authors": [], "source": "rss",
        })
    status[feed["name"]] = len(out)
    print(f"  {feed['name']}: {len(out)}")
    return out
