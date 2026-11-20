# Morning Feed

社会選択理論・意思決定理論の新着論文と関心のあるニュースを、毎朝自動で集めて日本語要約付きで読む個人用サイト。
仕様は [SPEC.md](SPEC.md)。

## しくみ

```
GitHub Actions（毎朝 7:00 JST）
  python -m feed.run
    1. 取得   arXiv API / Crossref API（ジャーナル） / OpenAlex API（著者別・要旨補完）
    2. 重複除去  DOI・arXiv ID・タイトル、過去に出したもの（data/seen.json）
    3. 採点   Gemini で 1〜10 点（20件ずつ一括）
    4. 要約   上位だけ 日本語タイトル＋3行要約＋おすすめ理由
    5. 保存   data/daily/YYYY-MM-DD.json, data/papers.jsonl → _site/ を生成
GitHub Pages で公開
```

## 設定ファイル（自分で編集してOK）

| ファイル | 内容 |
|---|---|
| `config.yaml` | Gemini のモデル名・件数・しきい値・保存期間 |
| `sources.yaml` | 情報源（arXiv カテゴリ、ジャーナルの ISSN）、関心の説明、タグ |
| `authors.yaml` | 注目著者（OpenAlex 著者ID、グループ A/B/C） |

著者を追加するときは https://openalex.org で名前を検索し、URL の `A50…` の部分を `openalex:` に書きます。

## 手元で動かす

```bash
pip install -r requirements.txt
```

```bash
GEMINI_API_KEY=... OPENALEX_API_KEY=... python -m feed.run
```

```bash
python -m http.server -d _site 8000
```

`GEMINI_API_KEY` がなくても動きます（キーワードによる簡易採点、要約なし）。

## GitHub Secrets

| 名前 | 取得先 |
|---|---|
| `GEMINI_API_KEY` | Google AI Studio（aistudio.google.com）→ Get API key |
| `OPENALEX_API_KEY` | openalex.org にサインアップ → Settings → API key（無料） |

OpenAlex はキーなしだと同じ IP の利用者全員で 1 日の無料枠を共有するため、GitHub Actions ではすぐ枠切れになります。キーの登録を推奨します。

## データ

- `data/papers.jsonl` … 表示した論文を1行1本で累積（DOI / arXiv ID / タイトル / 著者 / 掲載先 / 日付 / 要旨 / 日本語要約 / タグ）。将来の過去論文データベース用。
- `data/daily/` … 日ごとの全タブの結果（60日分）
- `data/seen.json` … 表示済み・採点済みID

Gemini の無料枠では送信内容が Google の製品改善に使われるため、公開されている論文・記事のタイトルと要旨だけを送っています。
