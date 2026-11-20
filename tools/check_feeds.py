"""RSS が取得できるかをまとめて確認する（GitHub Actions の check-feeds で実行）。

使い方: python tools/check_feeds.py tools/feeds_to_check.txt > result.txt
入力: 1行1アドレス（# で始まる行は見出しとしてそのまま出力）
"""
import sys
from concurrent.futures import ThreadPoolExecutor

import feedparser
import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; morning-feed/0.1)",
      "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"}


def check(u: str) -> str:
    try:
        r = requests.get(u, headers=UA, timeout=30)
        f = feedparser.parse(r.content)
        e = f.entries
        d = (e[0].get("published") or e[0].get("updated") or "")[:25] if e else ""
        t = e[0].get("title", "")[:60] if e else ""
        ok = "OK " if r.ok and e else "NG "
        return f"{ok}{r.status_code} n={len(e):<3} {d:<25} {u}\n      final={r.url[:100]}\n      feed={f.feed.get('title', '')[:50]} | first={t}"
    except Exception as x:  # noqa: BLE001
        return f"ERR {u} {str(x)[:120]}"


def main(path: str):
    lines = [l.rstrip("\n") for l in open(path, encoding="utf-8")]
    urls = [l.strip() for l in lines if l.strip() and not l.startswith("#")]
    with ThreadPoolExecutor(8) as ex:
        res = dict(zip(urls, ex.map(check, urls)))
    for l in lines:
        if l.startswith("#"):
            print(l)
        elif l.strip():
            print(res[l.strip()])


if __name__ == "__main__":
    main(sys.argv[1])
