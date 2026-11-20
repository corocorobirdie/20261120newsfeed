# 毎朝のニュースフィードサイト 指示書（Claude Code向け）

## 1. 目的
研究（社会選択理論・意思決定理論）の新着論文と、興味のあるニュースを毎朝自動で集め、日本語の要約付きで1つのサイトで読めるようにする。スマホのホーム画面に追加してアプリのように使う。

将来は別に作る「過去論文データベース」と組み合わせる予定なので、論文データは再利用しやすい形で保存する。

## 2. 全体構成（すべて無料枠で運用）

```
GitHub Actions（毎朝 7:00 JST = cron "0 22 * * *" UTC）
  1. 各情報源から新着を取得（RSS / arXiv API / OpenAlex API）
  2. 重複除去（URL・DOI・arXiv ID、過去に出したものも除外）
  3. Gemini API で関連度を 1〜10 点で採点（まとめて一括で送り、回数を節約）
  4. 上位だけ Gemini で「日本語タイトル＋3行要約＋おすすめ理由1行」を生成
  5. data/ に JSON で保存 → 静的サイトを生成
GitHub Pages で公開（PWA対応：ホーム画面に追加できる）
```

- 言語：Python（取得・処理）＋ 素のHTML/CSS/JS（表示）。フレームワークは必要最小限に。
- Claude（Proプラン）の使用量は、作るときと直すときだけ。毎日の処理はGeminiで行う。

## 3. タブ構成と情報源
各情報源のURLは実在するか確認してから使うこと。RSSがない媒体は、OpenAlex APIで代替するか、見送って報告すること。情報源は `sources.yaml` にまとめ、後から自分で追加・削除できるようにする。

### タブ1：論文（社会選択理論・意思決定理論）
- arXiv：`econ.TH`、`cs.GT`（キーワードで絞り込み）
- ジャーナル（RSS、なければ OpenAlex で掲載誌IDと掲載日で取得）：
  - 専門誌：Social Choice and Welfare / Theory and Decision / Economics & Philosophy / Mathematical Social Sciences / Journal of Public Economic Theory
  - 理論系：Journal of Economic Theory / Games and Economic Behavior / Journal of Mathematical Economics / Economic Theory / Theoretical Economics
- キーワード（採点の基準）： social choice, preference aggregation, Arrow's theorem, welfare economics, fairness, decision theory, expected utility, ambiguity / uncertainty, rationality, population ethics, axiomatization, inequality measurement, poverty measurement, polarization measurement
  - キーワードに完全一致しなくても、意味が近ければ高く評価する（例：公理的特徴づけ、社会厚生関数、選好の集計など）
  - 注目している著者は下の「著者リスト」を参照
- タグ：各論文に「社会選択」「意思決定」「不平等・貧困の測定」などのタグを自動で付ける
- 表示：日本語タイトル、日本語の要旨（アブストを翻訳・要約）、原題、著者、掲載先、リンク

#### 著者リスト（`authors.yaml` で管理）
- 同姓同名の取り違えを防ぐため、名前ではなく OpenAlex の著者ID で登録する。候補が複数あるときは、所属や代表論文を並べてユーザーに確認すること
- 論文の取得元：OpenAlex の著者別の新着＋arXiv の著者検索（ジャーナル一覧にない雑誌の論文も拾う）

グループA：必ず表示（点数に関係なく★付きで目立たせる）
- Kohei Kamaga / Satoshi Nakada / Norihito Sakamoto / Walter Bossert / Susumu Cato
- Yves Sprumont / John A. Weymark / Fabio Maccheroni / Massimo Marinacci
- Rolf Aaberge / Claudio Zoli / Leandro Nascimento / Gil Riella / James E. Foster
- Valentino Dardanoni / Oriol Carbonell-Nicolau / Frank Cowell / Dino Borie
- Shiri Alon / Ehud Lehrer
- Efe A. Ok / Özgür Evren / Juan Dubra / Tsogbadral Galaabaatar / Edi Karni
- Marc Fleurbaey / Stéphane Zuber / Eric Danan / Thibault Gajdos / Brian Hill / Jean-Marc Tallon
- Marcus Pivato / Kensei Nakamura / Hun Chung / Kaname Miyagishima / Koichi Tadenuma
- David McCarthy / Kalle Mikkola / Teruji Thomas / Matthew D. Adler / Ole F. Norheim

グループB：関連度で絞る（論文数が多く、分野外の論文や論説も多い著者）
- Joseph E. Stiglitz / Eric Maskin / Paola Giuliano
- → 著者リストに入っていることを加点要素にしつつ、採点が一定以上のものだけ表示

グループC：新着はまれ（名誉教授・退職）
- Udo Ebert / Michael Rothschild / Menahem Yaari / Tony Shorrocks
- → 論文が出たら表示するが、毎日の取得頻度は低くてよい（週1回など）

### タブ2：不平等
2つの欄に分ける。

(a) 実証・政策系の論文（理論ではないもの）
- ジャーナル：Social Indicators Research / Journal of Economic Inequality
- 掲載本数が多いので、全件ではなく「不平等」タグで採点して上位だけを載せる
- 論文タブの「不平等・貧困の測定」タグの論文は、こちらにも表示する（同じ論文を二重に保存はしない）

(b) インフォーマルな記事
- 候補：World Inequality Lab、Branko Milanovic の Substack、VoxEU/CEPR コラム、Project Syndicate、Our World in Data、LSE International Inequalities Institute のブログ、Brookings、Equitable Growth

どちらも英語が中心なので、日本語要約を必ず付ける

### タブ3：日本の時事
- 日経：有料記事のため、見出しとリンクだけを載せる（本文の取得・要約はしない）。日本語版のRSSが見つからない場合は Nikkei Asia（英語）のRSSを使う
- NHKニュースのRSSで補完
- 1日10件程度に絞る（重要度を Gemini で採点）

### タブ4：世界の兆し（Lobsterr風）
- Lobsterr Letter は週1回の、人が厳選してコメントを付けるニュースレター。新しい号が出たら、タイトルとリンクと簡単な要約を載せる。
- 同じ雰囲気の記事を、次のような媒体から Gemini に選ばせる：Rest of World、Aeon、Noema、Works in Progress、Monocle、The Browser など
- 選ぶ基準：「カルチャー・テック・ビジネスの変化の兆し」「読み物として面白い」

### タブ5：ロシア・中国
- ロシア語・中国語の記事で、特にハルビン、アムール沿岸、サハ共和国に関するものを日本語で要約し、原文タイトルも併記する
- 立場の偏りを避けるため、独立系と国営系の両方を入れ、カードに媒体の種類のラベル（独立系／国営 など）を付ける
  - ロシア：Meduza、The Bell、Kommersant、RBC、TASS（国営）、Re: Russia
  - 中国：Caixin Global、澎湃新聞、BBC中文、聯合早報、Sixth Tone、新華社（国営）

### 共通：今日のハイライト
- トップに、全タブの中から点数の高い5件を表示

## 4. 表示（UI）
- 各記事カード：日本語タイトル / 3行要約 / おすすめ理由1行 / 原題 / 媒体名・言語・日付 / リンク
- 「原文を表示」の切り替え
- ★で保存（ブラウザの localStorage に保存。読み書きは try/catch で囲む）。「保存済み」タブで一覧表示
- タグ・キーワードでの絞り込み
- スマホ優先のデザイン。ダークモード対応
- PWA（manifest と service worker）でホーム画面に追加できるようにする

## 5. Gemini の使い方
- APIキーは GitHub Secrets の `GEMINI_API_KEY` から読む（コードに書かない）
- モデル名は設定ファイルに書く（無料枠で使える Flash 系を既定にする。モデル名は AI Studio で最新を確認）
- 無料枠の回数制限を守る：
  - 採点は20件ずつまとめて1回で送る
  - 要約は各タブの上位だけ（論文15件、ほかのタブは各10件程度。設定で変更可）
  - 制限エラーのときは待ってやり直す。失敗した記事は要約なしで表示する
- 無料枠では、送った内容がGoogleの製品改善に使われる。送ってよいのは公開されている記事・論文だけ

## 6. データの保存
- `data/daily/YYYY-MM-DD.json`：その日の全タブの結果
- `data/papers.jsonl`：論文を1行1本で累積保存（DOI / arXiv ID / タイトル / 著者 / 掲載先 / 日付 / 要旨 / 日本語要約 / タグ）→ 将来の過去論文データベースにそのまま取り込める形にする
- `data/seen.json`：表示済みのID（重複防止）
- ニュースは60日分だけ残す。論文は全部残す

## 7. 利用ルール
- サイトは自分用。公開範囲に注意する（GitHub Pagesは基本的に誰でも見られる。気になる場合はリポジトリを非公開にして、別の公開方法を相談する）

## 8. 作る順番（段階的に）
1. 論文タブだけで最小版を作り、手動で実行して確認
2. GitHub Actions で毎朝自動実行 → GitHub Pages で公開
3. 不平等・時事・世界の兆しのタブを追加
4. ロシア・中国タブ（多言語の要約）を追加
5. ★保存、絞り込み、PWA などの機能を追加

各段階が終わるたびに、動いている状態を見せてから次へ進むこと。

## 9. 自分でやること（Claude Code が手順を案内する）
1. GitHub アカウント：あり
   - 匿名性を保つ設定：Git のコミット名はニックネーム、メールは GitHub の noreply アドレス（`〜@users.noreply.github.com`）にする。最初のコミットの前に設定すること
   - 本名や所属がコードやコミット、サイトに入らないようにする
2. Google AI Studio（aistudio.google.com）で Gemini の APIキーを作る
3. GitHub のリポジトリ設定 → Secrets に `GEMINI_API_KEY` を登録
4. GitHub Pages を有効にする

---

## 追加仕様（案）：論文を Google Drive に保存

しっかり読む論文を、できるだけ少ない操作で Drive の決まったフォルダに入れ、iPad の GoodNotes や PC で開けるようにする。実装は段階3のあと。

- PDF の保存先：Drive 直下の `03_temp`（GoodNotes で開く予定のものを入れる作業用フォルダ）
- 記録の保存先：Drive 直下の `references.bib`（`03_temp` は読み終わると整理するため、記録は別の場所に置く。場所は設定で変更可）

### 保存ルート
- **ルートA（どの端末でも）**：カードの「Driveに保存」→ Google Apps Script（自分の Google アカウントで動く）が PDF を取得して Drive の指定フォルダに保存。対象は arXiv とオープンアクセス版がある論文（OpenAlex の無料版 PDF）。
- **ルートB（iPad・ショートカットアプリ）**：カードのボタンまたは共有メニューから「論文を保存」ショートカットを実行し、PDF のダウンロード → Drive に保存 → `references.bib` に追記 → GoodNotes で開く、までを一括で行う。GoodNotes まで自動で開けない場合は、Drive に保存してフォルダを開くまでにする。
- **有料ジャーナル**：カードの「大学経由で開く」（大学の EZproxy の入口 + `https://doi.org/<DOI>`）で出版社ページを開き、PDF を表示して共有 →「論文を保存」。ショートカットが PDF の1ページ目から DOI を読み取り、書誌情報を取得する。DOI が見つからない場合は DOI かタイトルを入力して検索。フィード外の論文（Scholar で見つけた基本文献など）も同じ方法で保存できる。
- 大学の EZproxy の入口アドレスは所属がわかるため、リポジトリやサイトのコードには書かない。サイトの設定画面で入力し、端末の localStorage にだけ保存する。

### ファイル名
`著者姓1,著者姓2,著者姓3年号_論文タイトル.pdf`
- 著者は姓のみ。3人までは全員、4人以上は `第一著者姓,etal`
- タイトルは原文の大文字・小文字のまま、スペースを削除
- ファイル名に使えない記号（`: / \ ? * " < > |` など）は削除
- 例：`Wang,Tsui2000_PolarizationOrderingsandNewClassesofPolarizationIndices.pdf`

### 記録
- 1つの大きな `references.bib`（Drive 直下）に、保存のたびに BibTeX で1件追記する（論文ごとにファイルは作らない）
- 同じ論文（同じ DOI / arXiv ID）を再度保存したときは追記しない
- 書誌情報は Crossref の正式なデータ（DOI）から作る。arXiv は `eprint` / `archivePrefix = {arXiv}` を付ける
- PDF のファイル名（`file`）と保存日も記録する
- 将来の過去論文データベースで「読んだ論文」として `papers.jsonl` と DOI / arXiv ID でつなげられるようにする
