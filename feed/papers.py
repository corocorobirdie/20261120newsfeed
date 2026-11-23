"""論文の取得: arXiv / Crossref（ジャーナル）/ OpenAlex（著者別・要旨の補完）。"""
from __future__ import annotations

import re
import time
from datetime import datetime

import feedparser

from .common import (http_get, norm_doi, openalex_headers, strip_tags, days_ago, name_key)

OPENALEX = "https://api.openalex.org"


def make_paper(**kw) -> dict:
    p = {
        "kind": "paper", "title": "", "abstract": "", "authors": [], "venue": "",
        "date": "", "url": "", "doi": None, "arxiv_id": None, "lang": "en",
        "source": "", "openalex_authors": [],
    }
    p.update(kw)
    p["doi"] = norm_doi(p.get("doi"))
    m = re.match(r"10\.48550/arxiv\.(.+)$", p["doi"] or "")
    if m:  # arXiv の DOI は arXiv ID として扱う（arXiv 版と同一視するため）
        p["arxiv_id"], p["doi"] = m.group(1), None
        p["url"] = f"https://arxiv.org/abs/{m.group(1)}"
    if p["venue"].startswith("arXiv (Cornell"):
        p["venue"] = "arXiv"
    if p["doi"]:
        p["id"] = "doi:" + p["doi"]
    elif p.get("arxiv_id"):
        p["id"] = "arxiv:" + p["arxiv_id"]
    else:
        p["id"] = "url:" + p["url"]
    return p


# ---------------------------------------------------------------- arXiv

def _arxiv_query(q: str, max_results: int = 200) -> list[dict]:
    r = http_get("https://export.arxiv.org/api/query", params={
        "search_query": q, "start": 0, "max_results": max_results,
        "sortBy": "submittedDate", "sortOrder": "descending"})
    feed = feedparser.parse(r.content)
    out = []
    for e in feed.entries:
        aid = re.sub(r"v\d+$", "", e.id.rsplit("/abs/", 1)[-1])
        cats = [t["term"] for t in e.get("tags", [])]
        out.append(make_paper(
            title=re.sub(r"\s+", " ", e.title).strip(),
            abstract=re.sub(r"\s+", " ", e.summary).strip(),
            authors=[a.name for a in e.get("authors", [])],
            venue=f"arXiv ({e.get('arxiv_primary_category', {}).get('term', cats[0] if cats else '')})",
            date=e.published[:10], url=f"https://arxiv.org/abs/{aid}",
            doi=e.get("arxiv_doi"), arxiv_id=aid, source="arXiv", categories=cats,
        ))
    time.sleep(3)  # arXiv の利用規約: 連続アクセスは3秒以上あける
    return out


def fetch_arxiv(cfg: dict, today: datetime, lookback: int, status: dict | None = None) -> list[dict]:
    status = status if status is not None else {}
    since = days_ago(today, lookback)
    kws = [k.lower() for k in cfg.get("arxiv_keywords", [])]
    out = []
    for spec in cfg.get("arxiv", []):
        try:
            items = _arxiv_query(f"cat:{spec['category']}", 200)
        except Exception as e:  # noqa: BLE001  1つの情報源の失敗で全体を止めない
            print(f"  arXiv {spec['category']}: 取得失敗 {e}")
            status[f"arXiv {spec['category']}"] = f"取得失敗: {str(e)[:80]}"
            continue
        status[f"arXiv {spec['category']}（期間内/取得）"] = f"{sum(1 for p in items if p['date'] >= since)}/{len(items)}"
        items = [p for p in items if p["date"] >= since]
        if spec.get("keyword_filter"):
            items = [p for p in items if any(k in (p["title"] + " " + p["abstract"]).lower() for k in kws)]
        print(f"  arXiv {spec['category']}: {len(items)}")
        out += items
    return out


ARXIV_AUTHOR_CATS = ("econ.", "cs.GT", "cs.MA", "q-fin.", "physics.soc-ph", "math.", "stat.")


def fetch_arxiv_authors(authors: list[dict], today: datetime, lookback: int, status: dict | None = None) -> list[dict]:
    """arXiv の著者検索。ジャーナル一覧にない論文や査読前の論文を拾う。"""
    start = today.strftime("%Y%m%d")
    since = days_ago(today, lookback).replace("-", "")
    out = []
    for i in range(0, len(authors), 8):
        chunk = authors[i:i + 8]
        names = " OR ".join(f'au:"{a.get("arxiv") or a["name"]}"' for a in chunk)
        q = f"({names}) AND submittedDate:[{since}0000 TO {start}2359]"
        try:
            items = _arxiv_query(q, 50)
        except Exception as e:  # noqa: BLE001
            print("  arXiv author search failed:", e)
            if status is not None:
                status["arXiv 著者検索"] = f"一部失敗: {str(e)[:80]}"
            continue
        out += [p for p in items if any(c.startswith(ARXIV_AUTHOR_CATS) for c in p.get("categories", []))]
    print(f"  arXiv 著者検索: {len(out)}")
    if status is not None:
        status.setdefault("arXiv 著者検索", len(out))
    return out


# ---------------------------------------------------------------- Crossref

def fetch_crossref_journals(journals: list[dict], today: datetime, lookback: int, status: dict | None = None) -> list[dict]:
    status = status if status is not None else {}
    since = days_ago(today, lookback)
    out = []
    for j in journals:
        try:
            r = http_get(f"https://api.crossref.org/journals/{j['issn']}/works", params={
                "filter": f"from-created-date:{since},type:journal-article",
                "rows": 100, "sort": "created", "order": "desc",
                "select": "DOI,title,abstract,author,created,URL,container-title"})
        except Exception as e:  # noqa: BLE001
            print(f"  Crossref {j['name']}: 失敗 {e}")
            status[j["name"]] = f"取得失敗: {str(e)[:80]}"
            continue
        items = r.json()["message"]["items"]
        status[j["name"]] = len(items)
        for it in items:
            title = strip_tags((it.get("title") or [""])[0])
            if not title:
                continue
            authors = [" ".join(x for x in (a.get("given"), a.get("family")) if x) or a.get("name", "")
                       for a in it.get("author", [])]
            out.append(make_paper(
                title=title, abstract=strip_tags(it.get("abstract")), authors=authors,
                venue=j["name"], date=it["created"]["date-time"][:10],
                url=f"https://doi.org/{it['DOI']}", doi=it["DOI"], source="journal",
            ))
        print(f"  {j['name']}: {len(items)}")
        time.sleep(0.5)
    return out


# ---------------------------------------------------------------- OpenAlex

def _abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    pos = [(i, w) for w, idx in inv.items() for i in idx]
    return " ".join(w for _, w in sorted(pos))


def _from_openalex(w: dict) -> dict:
    loc = w.get("primary_location") or {}
    src = (loc.get("source") or {}).get("display_name") or ""
    ids = w.get("ids") or {}
    arxiv = None
    for l in w.get("locations") or []:
        u = (l.get("landing_page_url") or "")
        m = re.search(r"arxiv\.org/abs/([\w.]+?)(v\d+)?$", u)
        if m:
            arxiv = m.group(1)
    doi = w.get("doi")
    return make_paper(
        title=w.get("title") or "", abstract=_abstract(w.get("abstract_inverted_index")),
        authors=[a["author"]["display_name"] for a in w.get("authorships", [])],
        openalex_authors=[(a["author"].get("id") or "").rsplit("/", 1)[-1] for a in w.get("authorships", [])],
        venue=src, date=w.get("publication_date") or "", url=doi or loc.get("landing_page_url") or ids.get("openalex", ""),
        doi=doi, arxiv_id=arxiv if not doi else None, source="openalex",
        created=(w.get("created_date") or "")[:10],
    )


SELECT = "id,doi,title,publication_date,created_date,primary_location,locations,authorships,abstract_inverted_index,ids,type"


def fetch_openalex_authors(authors: list[dict], today: datetime, lookback: int, status: dict | None = None) -> list[dict]:
    """著者IDごとの新着。fields 指定のある著者は分野で絞る。"""
    status = status if status is not None else {}
    since = days_ago(today, lookback)
    stale = days_ago(today, 60)
    out = []
    plain = [a for a in authors if a.get("openalex") and not a.get("fields")]
    special = [a for a in authors if a.get("openalex") and a.get("fields")]
    queries = []
    ids = [i for a in plain for i in a["openalex"]]
    for k in range(0, len(ids), 40):
        queries.append(f"author.id:{'|'.join(ids[k:k+40])}")
    for a in special:
        queries.append(f"author.id:{'|'.join(a['openalex'])},primary_topic.field.id:{'|'.join(map(str, a['fields']))}")
    for a in authors:
        if a.get("name_search"):
            f = f'raw_author_name.search:"{a["name_search"]}"'
            if a.get("fields"):
                f += f",primary_topic.field.id:{'|'.join(map(str, a['fields']))}"
            queries.append(f)
    for f in queries:
        try:
            r = http_get(f"{OPENALEX}/works", params={
                "filter": f"{f},from_publication_date:{since},type:article|preprint|book-chapter",
                "sort": "publication_date:desc", "per_page": 100, "select": SELECT},
                headers=openalex_headers())
        except Exception as e:  # noqa: BLE001
            print("  OpenAlex 著者検索失敗:", e)
            status["OpenAlex 著者別"] = f"一部失敗: {str(e)[:80]}"
            continue
        for w in r.json().get("results", []):
            p = _from_openalex(w)
            # 何年も前に登録された論文が「巻号確定」で日付だけ新しくなるケースを除外
            if p.get("created") and p["created"] < stale:
                continue
            if p["date"] > days_ago(today, -1):  # 未来日付（予定号）は登録日を使う
                p["date"] = p.get("created") or p["date"]
            out.append(p)
    print(f"  OpenAlex 著者別: {len(out)}")
    status.setdefault("OpenAlex 著者別", len(out))
    return out


def enrich_from_openalex(papers: list[dict]) -> None:
    """DOI で OpenAlex を引き、要旨と著者IDを補う（著者リスト照合のため）。"""
    need = [p for p in papers if p.get("doi") and p.get("source") != "openalex"]
    by_doi = {p["doi"]: p for p in need}
    dois = list(by_doi)
    for k in range(0, len(dois), 50):
        chunk = dois[k:k + 50]
        try:
            r = http_get(f"{OPENALEX}/works", params={
                "filter": "doi:" + "|".join(chunk), "per_page": 50,
                "select": "doi,abstract_inverted_index,authorships"}, headers=openalex_headers())
        except Exception as e:  # noqa: BLE001
            print("  OpenAlex 補完失敗:", e)
            continue
        for w in r.json().get("results", []):
            p = by_doi.get(norm_doi(w.get("doi")))
            if not p:
                continue
            if not p["abstract"]:
                p["abstract"] = _abstract(w.get("abstract_inverted_index"))
            p["openalex_authors"] = [(a["author"].get("id") or "").rsplit("/", 1)[-1] for a in w.get("authorships", [])]


# ---------------------------------------------------------------- 著者照合

def match_authors(papers: list[dict], groups: dict[str, list[dict]]) -> None:
    """各論文に author_group（A/B/C）と author_hits（名前）を付ける。
    OpenAlex ID が一致すれば確実、ID のない人や未補完の論文は「姓＋名の頭文字」で照合。"""
    id_map, name_map = {}, {}
    for g, lst in groups.items():
        for a in lst:
            for i in a.get("openalex", []):
                id_map[i] = (g, a)
            name_map.setdefault(name_key(a["name"]), (g, a))
    rank = {"A": 0, "B": 1, "C": 2}
    for p in papers:
        hits = {}
        for i in p.get("openalex_authors", []):
            if i in id_map:
                g, a = id_map[i]
                hits[a["name"]] = (g, "id", a)
        if not p.get("openalex_authors") or any(not i for i in p.get("openalex_authors", [])) or p["source"] in ("arXiv",):
            for n in p.get("authors", []):
                k = name_key(n)
                if k in name_map and name_map[k][1]["name"] not in hits:
                    g, a = name_map[k]
                    hits[a["name"]] = (g, "name", a)
        # ID のない人（name_search）は OpenAlex 名前検索の結果でも名前照合になる
        if hits:
            best = min(hits.values(), key=lambda h: rank[h[0]])
            p["author_group"] = best[0]
            p["author_hits"] = sorted(hits)
            # 名前だけの照合で、その人が「要確認（ID なし）」の場合は弱い一致として扱う
            p["author_weak"] = all(h[1] == "name" and not h[2].get("openalex") for h in hits.values() if h[0] == best[0])
