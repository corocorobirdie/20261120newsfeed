"""共通の小物: HTTP、ID・タイトルの正規化、日付。"""
from __future__ import annotations

import hashlib
import html
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

UA = "morning-feed/0.1 (personal news reader; +https://github.com/)"

_session = requests.Session()
_session.headers["User-Agent"] = UA


def load_yaml(name: str) -> dict:
    with open(ROOT / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def http_get(url: str, *, params=None, headers=None, timeout=40, tries=3) -> requests.Response:
    last = None
    for i in range(tries):
        try:
            r = _session.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504):
                wait = min(int(r.headers.get("retry-after", "0") or 0), 60) or 5 * (i + 1)
                last = RuntimeError(f"HTTP {r.status_code} {url}")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last = e
            time.sleep(3 * (i + 1))
    raise last  # type: ignore[misc]


def openalex_headers() -> dict:
    key = os.environ.get("OPENALEX_API_KEY", "").strip()
    return {"Authorization": f"Bearer {key}"} if key else {}


def now_local(tz: str) -> datetime:
    return datetime.now(ZoneInfo(tz))


def days_ago(today: datetime, n: int) -> str:
    return (today - timedelta(days=n)).strftime("%Y-%m-%d")


def strip_tags(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"^\s*(abstract|summary)\s*[:.]?\s*", "", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()


def norm_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = doi.strip().lower()
    d = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", d)
    return d or None


def title_key(title: str) -> str:
    t = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", t)[:120]


def url_id(url: str) -> str:
    return "url:" + hashlib.sha1(url.encode()).hexdigest()[:16]


def ascii_fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def name_key(name: str) -> tuple[str, str]:
    """(姓, 名の頭文字) を返す。'Bossert, Walter' と 'Walter Bossert' を同一視する。"""
    n = ascii_fold(name).replace("‐", "-")
    if "," in n:
        last, first = [x.strip() for x in n.split(",", 1)]
    else:
        parts = n.split()
        if not parts:
            return ("", "")
        last, first = parts[-1], " ".join(parts[:-1])
    last = re.sub(r"[^a-z-]", "", last)
    first = re.sub(r"[^a-z ]", "", first).strip()
    return (last, first[:1])
