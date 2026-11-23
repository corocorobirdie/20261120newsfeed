"""前提論文（みんなが前提にしている論文）の洗い出しと、思い出し用カードの下書き。

  python -m feed.canon            # 前提論文リストを更新し、カードの下書きを補う
  python -m feed.canon --cards 0  # リストだけ更新（カードは作らない）

集計の材料（OpenAlex の referenced_works）:
  ・グループA著者の論文が参考文献に挙げている論文（週1回まとめて更新。data/canon_cache.json に保存）
  ・フィードに出た論文（data/papers.jsonl）が参考文献に挙げている論文（毎日、新しい分だけ）
前提度 = 引用しているグループA著者の人数 ×2 + 引用しているフィード論文の数 ×1.5（A著者3人以上かフィード2本以上のものだけ）

出力（どちらも公開データだけから作るので、公開リポジトリに置いてよい）:
  data/canon.json        … 前提論文のランキング
  data/canon_cards.json  … 論文ごとの思い出し用カード（AI の下書き）
個人の把握度やメモはここには置かない（端末の中、のちに Apps Script 経由で Drive に保存）。
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timedelta

from .common import DATA, http_get, load_yaml, now_local, openalex_headers, title_key
from .gemini import Gemini

OPENALEX = "https://api.openalex.org"
CACHE = DATA / "canon_cache.json"
CANON = DATA / "canon.json"
CARDS = DATA / "canon_cards.json"


def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write(path, obj, indent=None):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=indent, separators=None if indent else (",", ":")), encoding="utf-8")
    tmp.replace(path)


def _wid(url: str) -> str:
    return (url or "").rsplit("/", 1)[-1]


def _get(params: dict) -> dict:
    return http_get(f"{OPENALEX}/works", params=params, headers=openalex_headers(), timeout=60).json()


# ---------------------------------------------------------------- 材料集め

def author_refs(author: dict) -> list[str]:
    """著者の全論文が参考文献に挙げている論文ID（重複なし）。"""
    refs: set[str] = set()
    f = f"author.id:{'|'.join(author['openalex'])}"
    if author.get("fields"):
        f += f",primary_topic.field.id:{'|'.join(map(str, author['fields']))}"
    cursor = "*"
    while cursor:
        d = _get({"filter": f, "select": "id,referenced_works", "per_page": 200, "cursor": cursor})
        for w in d.get("results", []):
            refs.update(_wid(r) for r in w.get("referenced_works") or [])
        cursor = d.get("meta", {}).get("next_cursor")
        time.sleep(0.2)
    return sorted(refs)


def feed_refs(cache: dict) -> None:
    """papers.jsonl の論文のうち、まだ調べていないものの参考文献を取得してキャッシュに足す。"""
    done = cache.setdefault("feed", {})
    todo = []
    path = DATA / "papers.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                p = json.loads(line)
            except json.JSONDecodeError:
                continue
            if p["id"] in done:
                continue
            doi = p.get("doi") or (f"10.48550/arxiv.{p['arxiv_id']}" if p.get("arxiv_id") else None)
            if doi:
                todo.append((p["id"], doi.lower()))
    for k in range(0, len(todo), 50):
        chunk = todo[k:k + 50]
        try:
            d = _get({"filter": "doi:" + "|".join(d for _, d in chunk), "select": "doi,referenced_works", "per_page": 50})
        except Exception as e:  # noqa: BLE001
            print("  フィード論文の参考文献: 取得失敗", e)
            continue
        found = {(w.get("doi") or "").lower().replace("https://doi.org/", ""): [_wid(r) for r in w.get("referenced_works") or []]
                 for w in d.get("results", [])}
        for pid, doi in chunk:
            done[pid] = found.get(doi, [])  # 見つからなかったものも空で記録（毎日聞き直さない）


def update_cache(today: datetime, authors: dict, force: bool = False) -> dict:
    cache = _read(CACHE, {})
    a = cache.setdefault("authors", {})
    stale = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    for g in ("A",):
        for au in authors.get(g, []):
            if not au.get("openalex"):
                continue  # 著者IDのない人（名前検索の人）は集計に使わない
            rec = a.get(au["name"])
            if rec and rec.get("updated", "") > stale and not force:
                continue
            try:
                a[au["name"]] = {"updated": today.strftime("%Y-%m-%d"), "refs": author_refs(au)}
                print(f"  {au['name']}: 参考文献 {len(a[au['name']]['refs'])}")
            except Exception as e:  # noqa: BLE001
                print(f"  {au['name']}: 取得失敗 {e}")
    # 著者リストから外した人は集計からも外す
    names = {au["name"] for au in authors.get("A", [])}
    for n in list(a):
        if n not in names:
            del a[n]
    feed_refs(cache)
    _write(CACHE, cache)
    return cache


# ---------------------------------------------------------------- ランキング

def rank(cache: dict, top: int) -> list[dict]:
    by_author: dict[str, set] = {}
    for name, rec in cache.get("authors", {}).items():
        for w in rec["refs"]:
            by_author.setdefault(w, set()).add(name)
    by_feed: dict[str, int] = {}
    for refs in cache.get("feed", {}).values():
        for w in set(refs):
            by_feed[w] = by_feed.get(w, 0) + 1
    scores = []
    for w in set(by_author) | set(by_feed):
        na, nf = len(by_author.get(w, ())), by_feed.get(w, 0)
        if na < 3 and nf < 2:
            continue
        s = na * 2 + nf * 1.5
        scores.append((s, w, na, nf))
    scores.sort(reverse=True)
    out = []
    for s, w, na, nf in scores[:top]:
        out.append({"id": w, "score": round(s, 1), "n_authors": na, "n_feed": nf,
                    "cited_by_authors": sorted(by_author.get(w, ()))})
    return out


def _abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    pos = [(i, w) for w, idx in inv.items() for i in idx]
    return " ".join(w for _, w in sorted(pos))


def add_metadata(items: list[dict], old: dict) -> None:
    need = [it for it in items if it["id"] not in old]
    meta = dict(old)
    for k in range(0, len(need), 50):
        chunk = need[k:k + 50]
        d = _get({"filter": "openalex:" + "|".join(it["id"] for it in chunk), "per_page": 50,
                  "select": "id,doi,title,publication_year,type,cited_by_count,authorships,primary_location,abstract_inverted_index"})
        for w in d.get("results", []):
            loc = w.get("primary_location") or {}
            meta[_wid(w["id"])] = {
                "title": w.get("title") or "", "year": w.get("publication_year"), "type": w.get("type"),
                "doi": (w.get("doi") or "").replace("https://doi.org/", "") or None,
                "venue": ((loc.get("source") or {}).get("display_name")) or "",
                "authors": [a["author"]["display_name"] for a in w.get("authorships", [])][:12],
                "cited_by_count": w.get("cited_by_count", 0),
                "abstract": _abstract(w.get("abstract_inverted_index"))[:2500],
            }
        time.sleep(0.2)
    for it in items:
        it.update(meta.get(it["id"], {}))
        it["url"] = f"https://doi.org/{it['doi']}" if it.get("doi") else f"https://openalex.org/{it['id']}"


def merge_duplicates(items: list[dict], cache: dict) -> list[dict]:
    """同じ題名の別レコード（再録・書評レコードなど）を1つにまとめる。初出（最も古い年）を代表にする。"""
    feed_sets: dict[str, set] = {}
    for pid, refs in cache.get("feed", {}).items():
        for w in refs:
            feed_sets.setdefault(w, set()).add(pid)
    groups: dict[str, list[dict]] = {}
    for it in items:
        t = re.sub(r"^(the|a|an)\s+", "", (it.get("title") or "").strip().lower())
        groups.setdefault(title_key(t)[:80] or it["id"], []).append(it)
    out = []
    for g in groups.values():
        rep = min(g, key=lambda x: (x.get("year") or 9999, -x["n_authors"]))
        if len(g) > 1:
            authors = set().union(*(x["cited_by_authors"] for x in g))
            feeds = set().union(*(feed_sets.get(x["id"], set()) for x in g))
            rep = {**rep, "cited_by_authors": sorted(authors), "n_authors": len(authors), "n_feed": len(feeds),
                   "merged_ids": [x["id"] for x in g if x["id"] != rep["id"]]}
            rep["score"] = round(rep["n_authors"] * 2 + rep["n_feed"] * 1.5, 1)
        out.append(rep)
    out.sort(key=lambda x: -x["score"])
    return out


# ---------------------------------------------------------------- カード（AI の下書き）

CARD_SCHEMA = {"type": "array", "items": {"type": "object", "properties": {
    "i": {"type": "integer"},
    "title_ja": {"type": "string"},
    "aliases": {"type": "array", "items": {"type": "string"}},
    "one_line": {"type": "string"},
    "main_result": {"type": "string"},
    "setting": {"type": "string"},
    "why": {"type": "string"},
    "confidence": {"type": "string", "enum": ["高", "中", "低"]},
    "authors_fix": {"type": "string"},
    "year_fix": {"type": "integer"}},
    "required": ["i", "title_ja", "aliases", "one_line", "main_result", "setting", "why", "confidence", "authors_fix", "year_fix"]}}


def make_cards(items: list[dict], cards: dict, gem: Gemini, limit: int, batch: int) -> int:
    todo = [it for it in items if it["id"] not in cards and it.get("title")][:limit]
    made = 0
    for k in range(0, len(todo), batch):
        chunk = todo[k:k + batch]
        lines = []
        for i, it in enumerate(chunk):
            lines.append(f"[{i}] {it['title']} ({it.get('year')})\n  著者: {', '.join(it.get('authors', [])[:6])}\n"
                         f"  掲載: {it.get('venue') or '不明'}\n  要旨: {(it.get('abstract') or '（なし）')[:1500]}")
        prompt = (
            "あなたは社会選択理論・意思決定理論・厚生経済学に詳しい研究者です。以下は、この分野の研究者が"
            "よく前提にしている論文です。それぞれについて、研究者が会話の中ですぐ思い出せるような短いカードを日本語で作ってください。\n"
            "- title_ja: 日本語タイトル\n"
            "- aliases: この論文や結果が会話・論文で呼ばれる通称（英語と日本語、例: \"Harsanyi's aggregation theorem\", "
            "\"ハルサニの集計定理\", \"Gibbard–Satterthwaite theorem\"）。思い当たらなければ空配列\n"
            "- one_line: 一言で（60字程度）\n"
            "- main_result: 主結果（定理の内容を正確に、120字程度まで）\n"
            "- setting: 設定・使っている公理や前提（100字程度まで）\n"
            "- why: なぜよく前提にされるのか、何の出発点になっているか（80字程度まで）\n"
            "- confidence: 内容への自信（高/中/低）。有名な論文でよく知っているなら高、要旨だけが頼りなら中、"
            "よく知らず推測が多いなら低\n"
            "- authors_fix / year_fix: 書誌データは自動取得のため、古典的な本などで著者が書評者になっていたり、"
            "年が再版の年になっていることがある。誤っている場合だけ、正しい著者（\"Kenneth J. Arrow\" のように、複数なら \", \" 区切り）"
            "と初出の年を入れる。正しい場合や確かでない場合は authors_fix を空文字、year_fix を 0 にする\n"
            "要旨がなくても、よく知られた論文なら知識に基づいて書いてよい。ただし知らないことを作り上げないこと。"
            "確かでない部分は「（不確か）」と添えること。\n\n" + "\n\n".join(lines))
        res = gem.generate_json(prompt, CARD_SCHEMA)
        for r in res or []:
            if isinstance(r, dict) and 0 <= r.get("i", -1) < len(chunk):
                it = chunk[r["i"]]
                cards[it["id"]] = {k: r.get(k) for k in ("title_ja", "aliases", "one_line", "main_result", "setting", "why", "confidence", "authors_fix", "year_fix")}
                cards[it["id"]].update({"ai": True, "model": gem.model, "made": datetime.now().strftime("%Y-%m-%d")})
                made += 1
    return made


# ---------------------------------------------------------------- 実行

def run(today: datetime, cfg: dict, card_limit: int | None = None, force: bool = False, models: list[str] | None = None) -> dict:
    cc = cfg.get("canon", {})
    authors = load_yaml("authors.yaml")
    print("■ 前提論文の洗い出し")
    cache = update_cache(today, authors, force)
    items = rank(cache, cc.get("top", 200))
    old = {it["id"]: {k: v for k, v in it.items() if k in ("title", "year", "type", "doi", "venue", "authors", "cited_by_count", "abstract")}
           for it in _read(CANON, {}).get("items", [])}
    add_metadata(items, old)
    # 論文以外（データセット・記事の訂正など）や、題名のないものを除く
    items = [it for it in items if it.get("title") and it.get("type") not in ("dataset", "erratum", "paratext", "peer-review")]
    items = merge_duplicates(items, cache)
    for i, it in enumerate(items, 1):
        it["rank"] = i
    basis = {"authors": len(cache.get("authors", {})), "feed_papers": len(cache.get("feed", {}))}
    _write(CANON, {"updated": today.strftime("%Y-%m-%d"), "basis": basis, "items": items}, indent=1)
    print(f"  前提論文 {len(items)} 本（材料: グループA著者 {basis['authors']} 人・フィード論文 {basis['feed_papers']} 本）")

    cards = _read(CARDS, {})
    limit = cc.get("cards_per_day", 16) if card_limit is None else card_limit
    if limit > 0:
        gcfg = dict(cfg.get("gemini", {}))
        gcfg["card_models"] = models or gcfg.get("card_models") or gcfg.get("summary_models")
        gem = Gemini(gcfg, "card_models")
        if gem.enabled:
            n = make_cards(items, cards, gem, limit, cc.get("card_batch_size", 6))
            print(f"  カードの下書き {n} 枚を作成（合計 {len(cards)} 枚）")
            if gem.errors:
                print("  Gemini の警告:", *gem.errors[:5], sep="\n   ")
    _write(CARDS, cards, indent=1)
    return {"canon": len(items), "cards": len(cards)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards", type=int, help="この回に作るカードの最大枚数（0 で作らない）")
    ap.add_argument("--force", action="store_true", help="グループA著者の参考文献を今すぐ全部取り直す")
    ap.add_argument("--models", help="カードに使う Gemini モデル（カンマ区切り）")
    args = ap.parse_args(argv)
    cfg = load_yaml("config.yaml")
    today = now_local(cfg.get("timezone", "Asia/Tokyo"))
    run(today, cfg, args.cards, args.force, args.models.split(",") if args.models else None)


if __name__ == "__main__":
    main()
