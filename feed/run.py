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
from .common import days_ago, load_yaml, now_local, title_key
from .news import fetch_feed
from .gemini import Gemini, keyword_score
from .store import Seen, append_papers, save_daily

SITE_FIELDS = ["id", "kind", "tab", "section", "title", "title_ja", "summary_ja", "reason_ja", "authors", "venue",
               "date", "url", "doi", "arxiv_id", "abstract", "tags", "score", "author_group", "author_hits", "lang",
               "source", "label", "headline_only", "pinned"]


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


def summarize_with_retry(summ: Gemini, items: list[dict], kind: str, reader: str | None = None):
    kw = {"reader": reader} if reader else {}
    summ.summarize(items, kind, **kw)
    retry = [p for p in items if not p.get("summary_ja")]
    if retry:  # 抜けた記事だけもう一度（失敗したら要約なしで表示）
        summ.summarize(retry, kind, **kw)


def run_news_tab(name: str, tc: dict, today: datetime, seen: Seen, gem: Gemini, summ: Gemini,
                 status: dict, papers_shown: list[dict]):
    """ニュース系タブ1つ分: 取得 → 重複・既出除去 → 採点 → 選択 → 要約。"""
    print(f"■ {name} の取得")
    d = today.strftime("%Y-%m-%d")
    items = []
    for f in tc.get("feeds", []):
        since = days_ago(today, f.get("lookback_days", tc.get("lookback_days", 2)))
        items += fetch_feed(f, today, since, status)
    for it in items:
        if not it.get("section") and tc.get("journals"):
            it["section"] = "articles"
    # 重複除去（同じURL・同じタイトル）
    out, keys = [], set()
    for it in items:
        k1, k2 = it["id"], "t:" + title_key(it["title"])
        if k1 in keys or k2 in keys:
            continue
        keys |= {k1, k2}
        out.append(it)
    items = [it for it in out if not seen.is_old(it, d)]

    jpapers = []
    if tc.get("journals"):
        jpapers = P.fetch_crossref_journals(tc["journals"], today, tc.get("lookback_days", 3) + (4 if seen.empty else 0))
        for j in tc["journals"]:
            status[j["name"]] = sum(1 for p in jpapers if p["venue"] == j["name"])
        pats = [re.compile(x, re.I) for x in tc.get("exclude_title_patterns", [r"^correction", r"^erratum", r"^retraction", r"^publisher correction"])]
        jpapers = [p for p in dedupe(jpapers) if not any(r.search(p["title"]) for r in pats) and not seen.is_old(p, d)]
        P.enrich_from_openalex(jpapers)
        for p in jpapers:
            p["section"] = "papers"
    print(f"  記事 {len(items)} 件、論文 {len(jpapers)} 件を採点")

    tags = tc.get("tags", ["その他"])
    if gem.enabled:
        gem.score(items, tc["interest"], tags, what="記事")
        if jpapers:
            gem.score(jpapers, tc["interest"], tags, what="論文")
    for it in items + jpapers:  # 採点できなかったものは中位扱い（ピン留め以外は表示されにくい）
        it.setdefault("score", 4)
        it.setdefault("tags", [])
        it["tab"] = name

    minimum = tc.get("min_score", 5)
    pinned = [it for it in items if it.get("pinned")]
    rest = sorted((it for it in items if not it.get("pinned") and it["score"] >= minimum),
                  key=lambda x: (-x["score"], x["date"]), reverse=False)
    cap = tc.get("max_per_source")
    if cap:  # 媒体の偏りを防ぐ
        per, capped = {}, []
        for it in rest:
            per[it["venue"]] = per.get(it["venue"], 0) + 1
            if per[it["venue"]] <= cap:
                capped.append(it)
        rest = capped
    shown = pinned + rest[: tc.get("show", 10)]
    shown_papers = sorted((p for p in jpapers if p["score"] >= minimum), key=lambda x: -x["score"])[: tc.get("papers_show", 10)]

    if summ.enabled:
        print(f"■ {name} の日本語要約")
        targets = [it for it in shown if not (it.get("headline_only") and it["lang"] == "ja")][: tc.get("summarize", 10) + len(pinned)]
        summarize_with_retry(summ, targets, "article", tc.get("reader"))
        for it in targets:
            if it.get("headline_only"):  # 有料記事は見出しの翻訳だけ（本文は取得・要約しない）
                it["summary_ja"] = []
        if shown_papers:
            summarize_with_retry(summ, shown_papers, "paper", tc.get("reader"))

    result = shown_papers + shown
    # 不平等タブ: 論文タブの「不平等・貧困の測定」タグの論文も表示（データは二重に持たず参照だけ）
    if tc.get("journals"):
        refs = [{"ref": p["id"], "section": "papers"} for p in papers_shown if "不平等・貧困の測定" in (p.get("tags") or [])]
        result = refs + result
    print(f"  表示 {len(shown_papers) + len(shown)} 件")
    return result, items + jpapers, shown_papers


def run_papers(today: datetime, cfg: dict, src: dict, authors: dict, seen: Seen, gem: Gemini, summ: Gemini,
               status: dict | None = None):
    status = status if status is not None else {}
    pc = cfg["papers"]
    ps = src["papers"]
    print("■ 論文の取得")
    first_run = seen.empty
    lb = pc["lookback_days"] + (4 if first_run else 0)
    items = []
    items += P.fetch_arxiv(ps, today, lb, status)
    items += P.fetch_crossref_journals(ps["journals"], today, lb, status)
    weekly_c = today.weekday() == pc.get("group_c_weekday", 0) or first_run
    tracked = authors.get("A", []) + authors.get("B", []) + (authors.get("C", []) if weekly_c else [])
    items += P.fetch_openalex_authors(tracked, today, pc["author_lookback_days"], status)
    items += P.fetch_arxiv_authors(tracked, today, max(lb, 7), status)

    pats = [re.compile(x, re.I) for x in ps.get("exclude_title_patterns", [])]
    items = [p for p in items if p["title"] and not any(r.search(p["title"].strip()) for r in pats)]
    n0 = len(items)
    items = dedupe(items)
    d = today.strftime("%Y-%m-%d")
    items = [p for p in items if not seen.is_old(p, d)]
    print(f"  取得 {n0} 件 → 重複・既出を除いて {len(items)} 件")
    status["論文（取得→新着）"] = f"{n0}→{len(items)}"

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

    if summ.enabled:
        print("■ 日本語要約")
        top = shown[: pc["summarize_top"]]
        summarize_with_retry(summ, top, "paper")

    for p in shown:
        p["tab"] = "papers"
        p.setdefault("tags", [])
    print(f"  表示 {len(shown)} 件（うち★ {sum(1 for p in shown if p.get('author_group') == 'A')} 件）")
    return shown, items


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--date", help="YYYY-MM-DD（テスト用）")
    ap.add_argument("--light", action="store_true", help="テスト用: 軽量モデルだけを使う（上位モデルの無料枠を温存）")
    ap.add_argument("--only", help="テスト用: 指定したタブだけ作る（例: ruscn または papers,japan）")
    ap.add_argument("--out", help="テスト用: 結果をこのファイルに書き出し、data/ やサイトは更新しない")
    args = ap.parse_args(argv)

    cfg = load_yaml("config.yaml")
    src = load_yaml("sources.yaml")
    authors = load_yaml("authors.yaml")
    today = now_local(cfg.get("timezone", "Asia/Tokyo"))
    if args.date:
        today = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=today.tzinfo, hour=7)
    d = today.strftime("%Y-%m-%d")
    seen = Seen()
    gcfg = cfg.get("gemini", {})
    if args.light:
        lite = gcfg.get("light_model", "gemini-3.1-flash-lite")
        gcfg = {**gcfg, "score_models": [lite], "summary_models": [lite]}
    gem = Gemini(gcfg, "score_models")      # 採点（件数が多い）: 軽いモデル
    summ = Gemini(gcfg, "summary_models")   # 要約（質が大事）: 上位モデル
    status: dict = {}

    only = set(args.only.split(",")) if args.only else None
    try:
        if only is not None and "papers" not in only:
            papers, scored = [], []
        else:
            papers, scored = run_papers(today, cfg, src, authors, seen, gem, summ, status)
    except Exception as e:  # noqa: BLE001  論文タブが失敗してもほかのタブは作る
        print(f"  論文タブ: 失敗 {e}")
        status["papers"] = f"失敗: {e}"
        papers, scored = [], []
    slim = lambda x: x if "ref" in x else {k: x.get(k) for k in SITE_FIELDS}  # noqa: E731
    tabs = {"papers": [slim(p) for p in papers]}
    extra_papers = []
    for name, tc in (src.get("news_tabs") or {}).items():
        if only is not None and name not in only:
            continue
        try:
            shown, sc, sp = run_news_tab(name, tc, today, seen, gem, summ, status, papers)
        except Exception as e:  # noqa: BLE001  1つのタブの失敗で全体を止めない
            print(f"  {name}: 失敗 {e}")
            status[name] = f"失敗: {e}"
            continue
        tabs[name] = [slim(x) for x in shown]
        scored += sc
        extra_papers += sp

    # 今日のハイライト: 各タブの1位を先に入れ、残りは点数順
    real = {t: [x for x in lst if "ref" not in x] for t, lst in tabs.items()}
    hl = [max(lst, key=lambda x: x.get("score") or 0) for lst in real.values() if lst]
    rest = sorted((x for lst in real.values() for x in lst if x not in hl), key=lambda x: -(x.get("score") or 0))
    hl = (sorted(hl, key=lambda x: -(x.get("score") or 0)) + rest)[: cfg.get("highlights", 5)]
    payload = {
        "date": d,
        "generated_at": today.now(today.tzinfo).isoformat(timespec="minutes"),
        "model": summ.model if summ.enabled else None,
        "score_model": gem.model if gem.enabled else None,
        "gemini_calls": gem.calls + summ.calls,
        "notes": (gem.errors + summ.errors)[:10],
        "sources": status,
        "highlights": [x["id"] for x in hl],
        "tabs": tabs,
    }
    if args.out:  # テスト: 書き出すだけで保存しない
        import json
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        print(f"■ テスト結果: {args.out}（data/ は更新していません）")
        return 0
    for p in scored:  # 採点済みは表示しなかったものも既出扱い（翌日に再採点しない）
        seen.add(p, d)
    save_daily(d, payload, today, cfg["retention"]["news_days"])
    n = append_papers(papers + extra_papers, d)
    seen.save(today, cfg["retention"]["news_days"])
    print(f"■ 保存: data/daily/{d}.json（論文 {n} 件を papers.jsonl に追記、Gemini 呼び出し {gem.calls + summ.calls} 回）")
    if payload["notes"]:
        print("  Gemini の警告:", *payload["notes"], sep="\n   ")
    if not args.no_build:
        build_site()
    return 0


if __name__ == "__main__":
    sys.exit(main())
