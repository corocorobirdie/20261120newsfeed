"""Gemini API（無料枠）: 一括採点と日本語要約。

- APIキーは環境変数 GEMINI_API_KEY（GitHub Secrets）から読む。コードには書かない。
- 無料枠では送信内容が Google の製品改善に使われるため、公開されている記事・論文の
  タイトル・要旨だけを送る。
- キーがない場合は、キーワードによる簡易採点で動く（要約なし）。
"""
from __future__ import annotations

import json
import os
import re
import time

import requests

API = "https://generativelanguage.googleapis.com/v1beta/openai"


class Gemini:
    def __init__(self, cfg: dict, models_key: str = "models"):
        self.cfg = cfg
        self.key = os.environ.get("GEMINI_API_KEY", "").strip()
        models = cfg.get(models_key) or cfg.get("models") or ["gemini-flash-latest"]
        self.model, self._queue = models[0], list(models[1:])
        self.dead = False
        self._last = 0.0
        self.calls = 0
        self.errors: list[str] = []

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    # ------------------------------------------------------------ 低レベル
    # Gemini の OpenAI 互換エンドポイントを使う（キーを Authorization: Bearer で渡せる）
    def _headers(self):
        return {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}

    def _next_model(self, why: str) -> bool:
        """今のモデルが使えないとき、設定の候補リストの次のモデルに切り替える。"""
        print(f"  Gemini: {self.model} が使えません（{why}）")
        self.errors.append(f"{self.model}: {why}")
        if self._queue:
            self.model = self._queue.pop(0)
            print(f"  Gemini: {self.model} に切り替え")
            return True
        self.errors.append(f"使えるモデルがありません（最後: {why}）")
        self.dead = True
        return False

    def generate_json(self, prompt: str, schema: dict):
        if self.dead:
            return None
        tries = self.cfg.get("max_retries", 4)
        attempt = 0
        while attempt <= tries:
            body = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": self.cfg.get("temperature", 0.2),
                "response_format": {"type": "json_schema",
                                    "json_schema": {"name": "result", "schema": {
                                        "type": "object", "properties": {"items": schema},
                                        "required": ["items"]}}},
            }
            wait = self.cfg.get("min_interval_sec", 7) - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            attempt += 1
            try:
                r = requests.post(f"{API}/chat/completions", headers=self._headers(), json=body,
                                  timeout=self.cfg.get("timeout_sec", 150))
            except requests.Timeout:
                # 応答しないモデルは次の候補へ
                if self._next_model("タイムアウト"):
                    attempt = 0
                    continue
                return None
            except requests.RequestException as e:
                self.errors.append(str(e)[:200])
                time.sleep(10 * attempt)
                continue
            self.calls += 1
            if r.status_code in (400, 404) and "model" in r.text.lower():
                if self._next_model(f"HTTP {r.status_code}"):
                    attempt = 0
                    continue
                return None
            if r.status_code in (429, 500, 503):
                # 制限エラー: 指示された時間（なければ段階的に）待ってやり直す
                if r.status_code == 429 and re.search(r"PerDay|per day", r.text, re.I):
                    if self._next_model("1日の無料枠を使い切り"):  # モデルごとに枠が別なので次へ
                        attempt = 0
                        continue
                    return None
                delay = 20 * attempt
                m = re.search(r'retry in ([\d.]+)s|"retryDelay":\s*"(\d+)', r.text)
                if m:
                    delay = int(float(m.group(1) or m.group(2))) + 2
                print(f"  Gemini: {r.status_code}、{min(delay, 120)}秒待って再試行")
                time.sleep(min(delay, 120))
                continue
            if not r.ok:
                self.errors.append(f"HTTP {r.status_code}: {r.text[:300]}")
                return None
            try:
                text = r.json()["choices"][0]["message"]["content"]
                text = re.sub(r"^```(json)?|```$", "", text.strip()).strip()
                data = json.loads(text)
                return data.get("items", data) if isinstance(data, dict) else data
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
                self.errors.append(f"応答の解析に失敗: {e}")
                continue
        return None

    # ------------------------------------------------------------ 採点
    def score(self, items: list[dict], interest: str, tags: list[str], what: str = "論文") -> None:
        """items に score(1-10) と tags を付ける。score_batch_size 件ずつまとめて1回で送る。"""
        n = self.cfg.get("score_batch_size", 20)
        schema = {"type": "array", "items": {"type": "object", "properties": {
            "i": {"type": "integer"}, "score": {"type": "integer"},
            "tags": {"type": "array", "items": {"type": "string", "enum": tags}}},
            "required": ["i", "score", "tags"]}}
        for k in range(0, len(items), n):
            batch = items[k:k + n]
            lines = []
            for i, it in enumerate(batch):
                ab = (it.get("abstract") or "")[:900]
                lines.append(f"[{i}] {it['title']}\n  掲載: {it.get('venue','')}\n  内容: {ab or '（なし）'}")
            prompt = (
                f"あなたは個人向けの{what}推薦アシスタントです。読者の関心と選ぶ基準は次の通り:\n"
                f"{interest}\n"
                f"以下の各{what}について、読者にとっての関連度を1〜10の整数で採点し、"
                f"該当するタグを次の中から1〜3個選んでください: {', '.join(tags)}。\n"
                "10=まさに関心の中心、7=強く関連、5=周辺的に関連、3以下=ほぼ無関係。\n"
                "出力は各項目の番号 i、score、tags の配列。\n\n" + "\n\n".join(lines))
            res = self.generate_json(prompt, schema)
            for r in res or []:
                if isinstance(r, dict) and 0 <= r.get("i", -1) < len(batch):
                    batch[r["i"]]["score"] = max(1, min(10, int(r["score"])))
                    batch[r["i"]]["tags"] = [t for t in r.get("tags", []) if t in tags][:3]

    # ------------------------------------------------------------ 要約
    def summarize(self, items: list[dict], kind: str = "paper",
                  reader: str = "読者は社会選択理論・意思決定理論の研究者です。") -> None:
        """日本語タイトル＋3行要約＋おすすめ理由1行。失敗した記事は要約なしのまま。"""
        n = self.cfg.get("summary_batch_size", 5)
        schema = {"type": "array", "items": {"type": "object", "properties": {
            "i": {"type": "integer"}, "title_ja": {"type": "string"},
            "summary_ja": {"type": "array", "items": {"type": "string"}},
            "reason_ja": {"type": "string"}},
            "required": ["i", "title_ja", "summary_ja", "reason_ja"]}}
        for k in range(0, len(items), n):
            batch = items[k:k + n]
            lines = []
            for i, it in enumerate(batch):
                ab = (it.get("abstract") or "")[:2500]
                who = f"\n  著者: {', '.join(it.get('authors', [])[:8])}" if it.get("authors") else ""
                lines.append(f"[{i}] {it['title']}{who}\n  掲載: {it.get('venue','')}\n  本文/要旨: {ab or '（要旨なし：タイトルから推測できる範囲で、推測であることがわかる書き方で）'}")
            what = "論文" if kind == "paper" else "記事"
            prompt = (
                f"以下の各{what}について、日本語で次を作ってください。\n"
                "- title_ja: 自然な日本語タイトル\n"
                f"- summary_ja: {what}の内容を3行（3つの文字列、各60字程度まで）で要約。"
                "専門用語は日本の研究者が使う訳語を使い、必要なら英語を括弧で添える\n"
                "- reason_ja: この読者におすすめする理由を1行（40字程度）\n"
                "原文が日本語の場合、title_ja は原題をそのまま使う。\n"
                f"{reader}誇張せず、与えられた本文・要旨に書かれていないことは書かないこと。\n\n"
                + "\n\n".join(lines))
            res = self.generate_json(prompt, schema)
            for r in res or []:
                if isinstance(r, dict) and 0 <= r.get("i", -1) < len(batch):
                    it = batch[r["i"]]
                    it["title_ja"] = r.get("title_ja", "").strip()
                    it["summary_ja"] = [s.strip() for s in r.get("summary_ja", []) if s.strip()][:3]
                    it["reason_ja"] = r.get("reason_ja", "").strip()


# ---------------------------------------------------------------- キーなし時の簡易採点

KEYWORD_TAGS = {
    "社会選択": ["social choice", "arrow", "social welfare function", "preference aggregation", "aggregation of preferences", "impossibility"],
    "投票": ["voting", "vote", "election", "majority", "condorcet", "apportionment", "plurality"],
    "意思決定": ["decision theory", "expected utility", "ambiguity", "uncertainty", "rational", "choice function", "subjective", "risk", "belief"],
    "不平等・貧困の測定": ["inequality", "poverty", "polarization", "gini", "deprivation", "lorenz", "dominance"],
    "厚生経済学": ["welfare", "utilitarian", "egalitarian", "prioritarian", "well-being"],
    "公理化": ["axiom", "characteriz"],
    "人口倫理": ["population ethics", "intergenerational", "repugnant", "future generations"],
    "公正・配分": ["fair", "envy", "allocation", "division", "bankruptcy", "claims"],
    "メカニズムデザイン": ["mechanism", "strategy-proof", "strategyproof", "matching", "auction", "incentive"],
    "ゲーム理論": ["game", "equilibrium", "nash", "bargaining"],
}
CORE = {"社会選択": 3, "意思決定": 2, "不平等・貧困の測定": 3, "厚生経済学": 2, "公理化": 2, "人口倫理": 3, "投票": 2, "公正・配分": 1, "メカニズムデザイン": 1, "ゲーム理論": 0}


def keyword_score(items: list[dict]) -> None:
    for it in items:
        text = (it["title"] + " " + (it.get("abstract") or "")).lower()
        tags = [t for t, kws in KEYWORD_TAGS.items() if any(k in text for k in kws)]
        s = 2 + sum(CORE[t] for t in tags)
        it["score"] = max(1, min(9, s))
        it["tags"] = sorted(tags, key=lambda t: -CORE[t])[:3] or ["その他"]
