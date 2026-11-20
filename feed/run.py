"""毎朝の処理のエントリポイント:  python -m feed.run

  1. 各情報源から新着を取得
  2. 重複除去（URL・DOI・arXiv ID・タイトル、過去に出したものも除外）
  3. Gemini で関連度を採点（20件ずつ一括）
  4. 上位だけ日本語タイトル＋3行要約＋おすすめ理由を生成
  5. data/ に保存 → 静的サイトを生成
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime

from . import papers as P
from .build import build_site
from .common import load_yaml, now_local, title_key
from .gemini import Gemini, keyword_score
from .store import Seen, append_papers, save_daily

SITE_FIELDS = ["id", "title", "title_ja", "summary_ja", "reason_ja", "authors", "venue", "date", "url",
               "doi", "arxiv_id", "abstract", "tags", "score", "author_group", "author_hits", "lang", "source"]


def dedupe(items: list[dict]) -> list[dict]:
    """同じ論文（DOI / arXiv ID / タイトル一致）を1つにまとめる。ジャーナル版を優先し、arXiv ID は引き継ぐ。"""
    pri = {"journal": 0, "openalex": 1, "arXiv": 2}
    items = sorted(items, key=lambda p: pri.get(p["source"], 3))
    out, index = [], {}
    for p in items:
        keys = [k for k in (p.get("doi") and "d:" + p["doi"], p.get("arxiv_id") and "a:" + p["arxiv_id"],
                            "t:" + title_key(p["title"])) if k and k != "t:"]
        hit = next((index[k] for k in keys if k in index), None)
        if hit is None:
            out.append(p)
            hit = p
        else:
            for f in ("abstract", "arxiv_id"):
                if not hit.get(f) and p.get(f):
                    hit[f] = p[f]
            if not hit.get("openalex_authors") and p.get("openalex_authors"):
                hit["openalex_authors"] = p["openalex_authors"]
        for k in keys:
            index.setdefault(k, hit)
    return out


def run_papers(today: datetime, cfg: dict, src: dict, authors: dict, seen: Seen, gem: Gemini) -> list[dict]:
    pc = cfg["papers"]
    ps = src["papers"]
    print("■ 論文の取得")
    first_run = seen.empty
    lb = pc["lookback_days"] + (4 if first_run else 0)
    items = []
    items += P.fetch_arxiv(ps, today, lb)
    items += P.fetch_crossref_journals(ps["journals"], today, lb)
    weekly_c = today.weekday() == pc.get("group_c_weekday", 0) or first_run
    tracked = authors.get("A", []) + authors.get("B", []) + (authors.get("C", []) if weekly_c else [])
    items += P.fetch_openalex_authors(tracked, today, pc["author_lookback_days"])
    items += P.fetch_arxiv_authors(tracked, today, max(lb, 7))

    pats = [re.compile(x, re.I) for x in ps.get("exclude_title_patterns", [])]
    items = [p for p in items if p["title"] and not any(r.search(p["title"].strip()) for r in pats)]
    n0 = len(items)
    items = dedupe(items)
    d = today.strftime("%Y-%m-%d")
    items = [p for p in items if not seen.is_old(p, d)]
    print(f"  取得 {n0} 件 → 重複・既出を除いて {len(items)} 件")

    P.enrich_from_openalex(items)
    P.match_authors(items, authors)

    print(f"■ 採点（{'Gemini ' + gem.model if gem.enabled else 'キーワード簡易採点：GEMINI_API_KEY 未設定'}）")
    if gem.enabled:
        gem.score(items, ps["interest"], ps["tags"])
    missing = [p for p in items if "score" not in p]
    if missing:
        keyword_score(missing)  # キーなし・採点失敗時の代替

    # 表示する論文を選ぶ
    shown = []
    for p in items:
        g = p.get("author_group")
        s = p["score"]
        if g == "B":
            s += pc["group_b_bonus"]
            p["score_adj"] = s
            ok = s >= pc["group_b_min_score"]
        elif g == "A":
            ok = s >= 4 if p.get("author_weak") else True
        else:
            ok = s >= pc["min_score"]
        if ok:
            shown.append(p)
    # ★（グループA）を先頭に、あとは点数順
    shown.sort(key=lambda p: (p.get("author_group") != "A", -p.get("score_adj", p["score"]), p["date"]), reverse=False)
    shown = shown[: pc["max_display"]]

    if gem.enabled:
        print("■ 日本語要約")
        top = shown[: pc["summarize_top"]]
        gem.summarize(top, "paper")
        retry = [p for p in top if not p.get("summary_ja")]
        if retry:  # 抜けた記事だけもう一度（失敗したら要約なしで表示）
            gem.summarize(retry, "paper")

    for p in shown:
        p["tab"] = "papers"
        p.setdefault("tags", [])
    print(f"  表示 {len(shown)} 件（うち★ {sum(1 for p in shown if p.get('author_group') == 'A')} 件）")
    return shown, items


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--date", help="YYYY-MM-DD（テスト用）")
    args = ap.parse_args(argv)

    cfg = load_yaml("config.yaml")
    src = load_yaml("sources.yaml")
    authors = load_yaml("authors.yaml")
    today = now_local(cfg.get("timezone", "Asia/Tokyo"))
    if args.date:
        today = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=today.tzinfo, hour=7)
    d = today.strftime("%Y-%m-%d")
    seen = Seen()
    gem = Gemini(cfg.get("gemini", {}))

    papers, scored = run_papers(today, cfg, src, authors, seen, gem)

    tabs = {"papers": [{k: p.get(k) for k in SITE_FIELDS} for p in papers]}
    allitems = [x for lst in tabs.values() for x in lst]
    hl = sorted(allitems, key=lambda x: -(x.get("score") or 0))[: cfg.get("highlights", 5)]
    payload = {
        "date": d,
        "generated_at": today.now(today.tzinfo).isoformat(timespec="minutes"),
        "model": gem.model if gem.enabled else None,
        "gemini_calls": gem.calls,
        "notes": gem.errors[:10],
        "highlights": [x["id"] for x in hl],
        "tabs": tabs,
    }
    for p in scored:  # 採点済みは表示しなかったものも既出扱い（翌日に再採点しない）
        seen.add(p, d)
    save_daily(d, payload, today, cfg["retention"]["news_days"])
    n = append_papers(papers, d)
    seen.save(today, cfg["retention"]["news_days"])
    print(f"■ 保存: data/daily/{d}.json（論文 {n} 件を papers.jsonl に追記、Gemini 呼び出し {gem.calls} 回）")
    if gem.errors:
        print("  Gemini の警告:", *gem.errors[:5], sep="\n   ")
    if not args.no_build:
        build_site()
    return 0


if __name__ == "__main__":
    sys.exit(main())
