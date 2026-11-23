"use strict";

// タブの表示名（データにあるタブだけを表示する）
const TAB_LABELS = {
  papers: "論文",
  inequality: "不平等",
  japan: "日本の時事",
  signals: "世界の兆し",
  ruscn: "ロシア・中国",
};
const TAB_ORDER = Object.keys(TAB_LABELS);
const SAVED = "saved";  // 保存済みタブ
const LIB = "library";  // 文献タブ（前提論文）

// ---------------------------------------------------------------- しおり（保存）
// いまは端末の中（localStorage）に保存。記事の中身ごと持つので、日次データが消えても読める。
// 将来 Apps Script で全端末同期にするときは、この bookmarks の読み書きを差し替える。
const bookmarks = {
  all() { return store.get("bookmarks", {}); },
  has(id) { return id in this.all(); },
  toggle(it) {
    const b = this.all();
    if (b[it.id]) delete b[it.id];
    else {
      const { _section, _ref, ...item } = it;
      b[it.id] = { ...item, saved_at: new Date().toISOString() };
    }
    store.set("bookmarks", b);
    return !!b[it.id];
  },
  list() { return Object.values(this.all()).sort((a, b) => (a.saved_at < b.saved_at ? 1 : -1)); },
};

const $ = (s) => document.querySelector(s);
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* 保存できない環境では無視 */ } },
};

let index = { dates: [] };
let siteConfig = { ask_claude_url: "", ask_claude_tabs: {} };
const SECTION_LABELS = { papers: "論文（実証・政策）", articles: "記事・コラム" };
let day = null;
let currentTab = store.get("tab", "papers");
const filter = { q: "", tag: "" };  // 絞り込み（現在のタブ内）

// ---------------------------------------------------------------- テーマ
function applyTheme(t) {
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
}
applyTheme(store.get("theme", null));
$("#theme").addEventListener("click", () => {
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  const cur = document.documentElement.dataset.theme || (dark ? "dark" : "light");
  const next = cur === "dark" ? "light" : "dark";
  applyTheme(next); store.set("theme", next);
});

// ---------------------------------------------------------------- データ
async function getJSON(url) {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}

async function loadDay(date) {
  try {
    day = await getJSON(`data/daily/${date}.json`);
  } catch (e) {
    $("#meta").textContent = navigator.onLine ? "この日のデータを読み込めませんでした" : "オフラインです。この日はまだ読み込んだことがないため表示できません";
    return;
  }
  const i = index.dates.indexOf(date);
  $("#date").textContent = fmtDate(date);
  $("#next").disabled = i <= 0;
  $("#prev").disabled = i < 0 || i >= index.dates.length - 1;
  if (currentTab !== SAVED && currentTab !== LIB && !day.tabs[currentTab]) currentTab = TAB_ORDER.find((t) => day.tabs[t]) || "papers";
  render();
}

function fmtDate(d) {
  const dt = new Date(d + "T00:00:00");
  return `${dt.getMonth() + 1}/${dt.getDate()}（${"日月火水木金土"[dt.getDay()]}）`;
}

// ---------------------------------------------------------------- 描画
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function renderTabs() {
  const nav = $("#tabs");
  nav.replaceChildren();
  for (const t of TAB_ORDER) {
    if (!day.tabs[t]) continue;
    const b = el("button", null, TAB_LABELS[t]);
    b.setAttribute("role", "tab");
    b.setAttribute("aria-selected", String(t === currentTab));
    b.append(el("span", "count", String(day.tabs[t].length)));
    b.addEventListener("click", () => { currentTab = t; filter.tag = ""; store.set("tab", t); render(); window.scrollTo({ top: 0 }); });
    nav.append(b);
  }
  if (canon && canon.items.length) {
    const l = el("button", null, "📚 文献");
    l.setAttribute("role", "tab");
    l.setAttribute("aria-selected", String(currentTab === LIB));
    l.append(el("span", "count", String(canon.items.length)));
    l.addEventListener("click", () => { currentTab = LIB; filter.tag = ""; store.set("tab", LIB); render(); window.scrollTo({ top: 0 }); });
    nav.append(l);
  }
  const s = el("button", null, "🔖 保存済み");
  s.setAttribute("role", "tab");
  s.setAttribute("aria-selected", String(currentTab === SAVED));
  s.append(el("span", "count", String(bookmarks.list().length)));
  s.addEventListener("click", () => { currentTab = SAVED; filter.tag = ""; store.set("tab", SAVED); render(); window.scrollTo({ top: 0 }); });
  nav.append(s);
}

function renderHighlights() {
  const all = Object.values(day.tabs).flat();
  const byId = new Map(all.map((x) => [x.id, x]));
  const items = (day.highlights || []).map((id) => byId.get(id)).filter(Boolean);
  const box = $("#highlights");
  box.hidden = items.length === 0 || !!(filter.q || filter.tag) || currentTab === SAVED || currentTab === LIB;  // 絞り込み中・保存済みタブでは隠す
  const ol = $("#hl-list");
  ol.replaceChildren();
  for (const it of items) {
    const li = el("li");
    const a = el("a", null, it.title_ja || it.title);
    a.href = "#" + encodeURIComponent(it.id);
    a.addEventListener("click", (e) => { e.preventDefault(); jumpTo(it); });
    li.append(a, el("span", "hl-src", [it.venue, it.author_group === "A" ? "★ " + (it.author_hits || []).join(", ") : ""].filter(Boolean).join(" · ")));
    ol.append(li);
  }
}

function jumpTo(it) {
  const tab = Object.keys(day.tabs).find((t) => day.tabs[t].some((x) => x.id === it.id));
  if (tab && tab !== currentTab) { currentTab = tab; render(); }
  const node = document.getElementById("c-" + it.id);
  if (node) { node.scrollIntoView({ behavior: "smooth", block: "start" }); node.animate([{ outline: "2px solid var(--accent)" }, { outline: "2px solid transparent" }], 1600); }
}

function card(it) {
  const node = $("#card-tpl").content.firstElementChild.cloneNode(true);
  node.id = "c-" + it.id + (it._ref ? "-ref" : "");
  const star = it.author_group === "A";
  if (star) node.classList.add("starred");

  const badges = node.querySelector(".badges");
  if (star) badges.append(el("span", "badge star", "★ " + (it.author_hits || []).join(", ")));
  else if (it.author_hits && it.author_hits.length) badges.append(el("span", "badge", "著者: " + it.author_hits.join(", ")));
  if (it.pinned) badges.append(el("span", "badge pin", "新しい号"));
  if (it.label) badges.append(el("span", "badge label", it.label));
  if (it._ref) badges.append(el("span", "badge", "論文タブから"));
  if (it.score != null && !it.pinned) badges.append(el("span", "badge score", `関連度 ${it.score}`));

  const a = node.querySelector(".title-ja a");
  a.textContent = it.title_ja || it.title;
  a.href = it.url;
  const ul = node.querySelector(".summary");
  for (const s of it.summary_ja || []) ul.append(el("li", null, s));
  node.querySelector(".reason").textContent = it.reason_ja || "";
  node.querySelector(".orig-title").textContent = it.title_ja ? it.title : "";
  const authors = it.authors || [];
  node.querySelector(".byline").textContent = authors.slice(0, 6).join(", ") + (authors.length > 6 ? ` ほか${authors.length - 6}名` : "");
  node.querySelector(".src").textContent = [it.venue, (it.lang || "").toUpperCase(), it.date,
    it.saved_at ? `保存 ${it.saved_at.slice(5, 10).replace("-", "/")}` : ""].filter(Boolean).join(" · ");
  const tags = node.querySelector(".tags");
  for (const t of it.tags || []) {
    const b = el("button", t === filter.tag ? "on" : null, t);
    b.type = "button";
    b.addEventListener("click", () => setTag(t === filter.tag ? "" : t));
    tags.append(b);
  }
  const open = node.querySelector(".open");
  const via = viaProxy(it);
  open.href = via || it.url;
  if (via) open.textContent = "大学経由で開く ↗";
  const ask = node.querySelector(".ask");
  ask.href = askClaudeUrl(it);
  ask.addEventListener("click", () => {
    // 飛び先で入力されなかったときのために、質問文をクリップボードにもコピー
    try { navigator.clipboard && navigator.clipboard.writeText(askPrompt(it)).catch(() => {}); } catch { /* 無視 */ }
  });

  const bm = node.querySelector(".bookmark");
  const setBm = (on) => { bm.setAttribute("aria-pressed", String(on)); bm.setAttribute("aria-label", on ? "保存を解除" : "保存"); };
  setBm(bookmarks.has(it.id));
  bm.addEventListener("click", () => {
    const on = bookmarks.toggle(it);
    setBm(on);
    renderTabs();  // 件数を更新
    if (currentTab === SAVED && !on) render();
  });

  const btn = node.querySelector(".toggle-orig");
  const orig = node.querySelector(".orig");
  if (!it.abstract) btn.remove();
  btn.addEventListener("click", () => {
    if (!orig.childElementCount) {
      orig.append(el("span", "label", it.kind === "news" ? "原文（本文の冒頭）" : "原文（要旨）"), el("div", null, it.abstract));
    }
    orig.hidden = !orig.hidden;
    btn.textContent = orig.hidden ? "原文を表示" : "原文を隠す";
  });
  return node;
}

// Claude を開いて、この記事についての質問を入力済みにする
function askClaudeUrl(it) {
  const base = (siteConfig.ask_claude_tabs || {})[it.tab] || siteConfig.ask_claude_url || "https://claude.ai/new";
  return base + (base.includes("?") ? "&" : "?") + "q=" + encodeURIComponent(askPrompt(it));
}

function askPrompt(it) {
  const lines = [
    it.kind === "news"
      ? "次の記事について、日本語で解説してください。背景、要点、論点、今後の見通しを教えてください。"
      : "次の論文について、日本語で解説してください。主な結果、使われている公理や手法、先行研究との関係、意義と限界を教えてください。",
    "",
    `タイトル: ${it.title}`,
  ];
  if (it.authors && it.authors.length) lines.push(`著者: ${it.authors.slice(0, 10).join(", ")}`);
  if (it.venue) lines.push(`掲載先: ${it.venue}（${it.date || ""}）`);
  lines.push(`リンク: ${it.url}`);
  if (it.abstract) lines.push("", it.kind === "news" ? "本文の冒頭:" : "要旨:", it.abstract.slice(0, 2500));
  return lines.join("\n");
}

// 他のタブの記事への参照（{ref: id}）を実体に置き換える。欄（section）ごとにまとめる
function resolve(lst) {
  const byId = new Map(Object.values(day.tabs).flat().filter((x) => !x.ref).map((x) => [x.id, x]));
  const out = lst.map((x) => (x.ref ? (byId.has(x.ref) ? { ...byId.get(x.ref), _section: x.section, _ref: true } : null) : { ...x, _section: x.section }))
    .filter(Boolean);
  const order = Object.keys(SECTION_LABELS);
  return out.sort((a, b) => (order.indexOf(a._section) + 1 || 99) - (order.indexOf(b._section) + 1 || 99));
}

// ---------------------------------------------------------------- 絞り込み
function norm(s) { return (s || "").normalize("NFKC").toLowerCase(); }

function matches(it) {
  if (filter.tag && !(it.tags || []).includes(filter.tag)) return false;
  if (!filter.q) return true;
  const hay = norm([it.title, it.title_ja, (it.summary_ja || []).join(" "), it.reason_ja, (it.authors || []).join(" "),
    it.venue, it.abstract, (it.tags || []).join(" ")].join(" "));
  return norm(filter.q).split(/\s+/).filter(Boolean).every((w) => hay.includes(w));
}

function renderFilters(total, shown) {
  const box = $("#active-filters");
  box.replaceChildren();
  const on = filter.q || filter.tag;
  if (filter.tag) {
    const chip = el("button", "chip on", `#${filter.tag} ×`);
    chip.addEventListener("click", () => setTag(""));
    box.append(chip);
  }
  if (on) {
    box.append(el("span", "count-note", `${shown} / ${total} 件`));
    const clear = el("button", "chip", "解除");
    clear.addEventListener("click", () => { filter.q = ""; $("#q").value = ""; setTag(""); });
    box.append(clear);
  }
  if (filter.tag) showFilterbar(true);
}

function setTag(t) { filter.tag = t; render(); if (t) window.scrollTo({ top: 0 }); }

function showFilterbar(show) {
  $("#filterbar").hidden = !show;
  $("#search-toggle").setAttribute("aria-expanded", String(show));
}

$("#search-toggle").addEventListener("click", () => {
  const show = $("#filterbar").hidden;
  showFilterbar(show);
  if (show) $("#q").focus();
  else if (filter.q || filter.tag) { filter.q = ""; $("#q").value = ""; filter.tag = ""; render(); }
});
let qTimer;
$("#q").addEventListener("input", (e) => {
  clearTimeout(qTimer);
  qTimer = setTimeout(() => { filter.q = e.target.value.trim(); render(); }, 150);
});

function render() {
  renderTabs();
  renderHighlights();
  renderTodayCanon();
  if (currentTab === LIB) { renderLibrary(); return; }
  const saved = currentTab === SAVED;
  const all = saved ? bookmarks.list() : resolve(day.tabs[currentTab] || []);
  const items = all.filter(matches);
  renderFilters(all.length, items.length);
  const list = $("#list");
  const nodes = [];
  let lastSection;
  for (const it of items) {
    if (it._section && it._section !== lastSection && SECTION_LABELS[it._section]) {
      nodes.push(el("h2", "section-title", SECTION_LABELS[it._section]));
      lastSection = it._section;
    }
    nodes.push(card(it));
  }
  list.replaceChildren(...nodes);
  if (!items.length) list.append(el("p", "empty", all.length ? "条件に合う記事はありません"
    : saved ? "保存した記事はまだありません。カードの 🔖 で保存できます" : "この日の新着はありません"));
  const notes = [];
  if (day.generated_at) notes.push(`更新 ${day.generated_at.slice(11, 16)}`);
  if (!day.model) notes.push("要約なし（Gemini未設定）");
  if (!navigator.onLine) notes.push("オフライン（保存済みの内容を表示）");
  $("#meta").textContent = notes.join(" · ");
}

// ---------------------------------------------------------------- 起動
$("#prev").addEventListener("click", () => { const i = index.dates.indexOf(day.date); if (i < index.dates.length - 1) loadDay(index.dates[i + 1]); });
$("#next").addEventListener("click", () => { const i = index.dates.indexOf(day.date); if (i > 0) loadDay(index.dates[i - 1]); });

// ホーム画面に追加したとき・オフラインで読めるようにする
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
}
window.addEventListener("online", () => day && render());
window.addEventListener("offline", () => day && render());

// ---------------------------------------------------------------- 文献タブ（前提論文）
// 前提論文リストとカードの下書きは公開データから毎朝作る（data/canon.json, data/canon_cards.json）。
// 把握度はいまは端末の中に保存（将来 Apps Script で全端末同期）。
let canon = null;          // { updated, basis, items: [...] }
let canonCards = {};       // { W123: { title_ja, aliases, one_line, ... } }
let libStatusFilter = -1;  // -1 = すべて
const LEVELS = ["未把握", "概要は把握", "読んだ", "しっかり読んだ"];

const canonStatus = {
  all() { return store.get("canon_status", {}); },
  get(id) { return (this.all()[id] || {}).level || 0; },
  set(id, level) { const s = this.all(); s[id] = { level, updated: new Date().toISOString() }; store.set("canon_status", s); },
};

async function loadCanon() {
  try {
    canon = await getJSON("data/canon.json");
    try { canonCards = await getJSON("data/canon_cards.json"); } catch { canonCards = {}; }
    if (day) render();
  } catch { canon = null; }
}

// 前提論文を、ほかのタブのカードと同じ形（保存・Claude・大学経由で共通に使える形）にする
function canonView(it) {
  const c = canonCards[it.id] || {};
  const authors = c.authors_fix ? c.authors_fix.split(/,\s*/) : (it.authors || []);
  const year = c.year_fix || it.year;
  return {
    id: it.id, kind: "paper", tab: "papers", title: it.title, title_ja: c.title_ja || "",
    summary_ja: [c.one_line, c.main_result].filter(Boolean), reason_ja: c.why || "",
    authors, venue: it.venue || "", date: year ? String(year) : "", url: it.url, doi: it.doi, abstract: it.abstract || "",
    tags: [], card: c, rank: it.rank, n_authors: it.n_authors, n_feed: it.n_feed, cited_by_authors: it.cited_by_authors || [],
  };
}

function libMatches(v) {
  if (libStatusFilter >= 0 && canonStatus.get(v.id) !== libStatusFilter) return false;
  if (!filter.q) return true;
  const c = v.card;
  const hay = norm([v.title, v.title_ja, (c.aliases || []).join(" "), c.one_line, c.main_result, c.setting, c.why,
    v.authors.join(" "), v.date, v.venue, v.abstract].join(" "));
  return norm(filter.q).split(/\s+/).filter(Boolean).every((w) => hay.includes(w));
}

function renderLibrary() {
  const list = $("#list");
  renderFilters(0, 0);
  const views = canon.items.map(canonView);
  const counts = [0, 0, 0, 0];
  for (const v of views) counts[canonStatus.get(v.id)]++;
  const known = views.length - counts[0];

  const head = el("section", "lib-head");
  head.append(el("p", "lib-title", `前提論文 ${views.length} 本のうち ${known} 本を把握`));
  const bar = el("div", "lib-bar");
  [3, 2, 1].forEach((lv) => { const s = el("span", `lv${lv}`); s.style.width = `${(counts[lv] / views.length) * 100}%`; bar.append(s); });
  head.append(bar);
  const chips = el("div", "lib-chips");
  [[-1, `すべて ${views.length}`], ...LEVELS.map((l, i) => [i, `${l} ${counts[i]}`])].forEach(([lv, label]) => {
    const b = el("button", "chip" + (libStatusFilter === lv ? " on" : ""), label);
    b.addEventListener("click", () => { libStatusFilter = lv; render(); });
    chips.append(b);
  });
  head.append(chips);
  head.append(el("p", "lib-note",
    `グループAの著者 ${canon.basis.authors} 人の論文と、フィードに出た論文 ${canon.basis.feed_papers} 本が参考文献に挙げている論文を、引用の多い順に並べています（${canon.updated} 更新）。カードは AI の下書きです。`));

  const shown = views.filter(libMatches);
  list.replaceChildren(head, ...shown.map(libCard));
  if (!shown.length) list.append(el("p", "empty", "条件に合う論文はありません"));
  const q = filter.q ? `「${filter.q}」で ${shown.length} 本` : "";
  $("#meta").textContent = q;
}

function libCard(v) {
  const c = v.card;
  const node = el("article", "card canon");
  node.id = "lib-" + v.id;
  const badges = el("div", "badges");
  badges.append(el("span", "badge rank", `#${v.rank}`));
  badges.append(el("span", "badge", `A著者 ${v.n_authors}人` + (v.n_feed ? `・フィード ${v.n_feed}本` : "") + " が引用"));
  if (c.one_line) badges.append(el("span", "badge label", `AIの下書き（自信: ${c.confidence || "?"}）`));
  node.append(badges);

  const h = el("h3", "title-ja");
  const a = el("a", null, v.title_ja || v.title);
  a.href = v.url; a.target = "_blank"; a.rel = "noopener";
  h.append(a);
  node.append(h);
  if (c.one_line) node.append(el("p", "one-line", c.one_line));
  if (c.main_result || c.setting || c.why) {
    const dl = el("dl", "canon-rows");
    for (const [k, val] of [["主結果", c.main_result], ["設定・公理", c.setting], ["なぜ前提か", c.why]]) {
      if (!val) continue;
      dl.append(el("dt", null, k), el("dd", null, val));
    }
    node.append(dl);
  }
  if ((c.aliases || []).length) {
    const al = el("div", "aliases");
    al.append(el("span", "aliases-label", "通称"));
    for (const x of c.aliases) al.append(el("span", "alias", x));
    node.append(al);
  }
  if (v.title_ja) node.append(el("p", "orig-title", v.title));
  node.append(el("p", "byline", v.authors.slice(0, 6).join(", ") + (v.authors.length > 6 ? ` ほか${v.authors.length - 6}名` : "")));
  node.append(el("p", "src", [v.date, v.venue].filter(Boolean).join(" · ")));

  // 把握度
  const seg = el("div", "levels");
  seg.setAttribute("role", "group");
  seg.setAttribute("aria-label", "把握度");
  const cur = canonStatus.get(v.id);
  LEVELS.forEach((label, lv) => {
    const b = el("button", "lv-btn" + (lv === cur ? " on" : ""), label);
    b.type = "button";
    b.setAttribute("aria-pressed", String(lv === cur));
    b.addEventListener("click", () => {
      canonStatus.set(v.id, lv);
      const y = window.scrollY;
      render();
      window.scrollTo({ top: y });
    });
    seg.append(b);
  });
  node.append(seg);

  // 操作（保存・原文・Claude・開く）
  const actions = el("div", "actions");
  const bm = el("button", "bookmark", "🔖");
  bm.type = "button";
  const setBm = (on) => { bm.setAttribute("aria-pressed", String(on)); bm.setAttribute("aria-label", on ? "保存を解除" : "保存"); };
  setBm(bookmarks.has(v.id));
  bm.addEventListener("click", () => { setBm(bookmarks.toggle({ ...v, card: undefined })); renderTabs(); });
  actions.append(bm);
  const orig = el("div", "orig");
  orig.hidden = true;
  if (v.abstract) {
    const t = el("button", "toggle-orig", "原文を表示");
    t.type = "button";
    t.addEventListener("click", () => {
      if (!orig.childElementCount) orig.append(el("span", "label", "原文（要旨）"), el("div", null, v.abstract));
      orig.hidden = !orig.hidden;
      t.textContent = orig.hidden ? "原文を表示" : "原文を隠す";
    });
    actions.append(t);
  }
  const ask = el("a", "ask", "Claudeに聞く");
  ask.target = "_blank"; ask.rel = "noopener";
  const prompt = canonPrompt(v);
  const base = (siteConfig.ask_claude_tabs || {}).papers || siteConfig.ask_claude_url || "https://claude.ai/new";
  ask.href = base + (base.includes("?") ? "&" : "?") + "q=" + encodeURIComponent(prompt);
  ask.addEventListener("click", () => { try { navigator.clipboard.writeText(prompt).catch(() => {}); } catch { /* 無視 */ } });
  actions.append(ask);
  const open = el("a", "open", "開く ↗");
  open.target = "_blank"; open.rel = "noopener";
  const via = viaProxy(v);
  open.href = via || v.url;
  if (via) open.textContent = "大学経由で開く ↗";
  actions.append(open);
  node.append(actions, orig);
  return node;
}

function canonPrompt(v) {
  const c = v.card;
  const lines = [
    "次の論文は、私の分野（社会選択理論・意思決定理論）でよく前提にされている論文です。日本語で解説してください。"
    + "主結果を正確に述べ、使われている公理や証明のアイデア、その後の研究への影響、よく誤解される点を教えてください。"
    + "下の「カード」は AI の下書きなので、誤りがあれば指摘してください。",
    "",
    `タイトル: ${v.title}`,
    `著者: ${v.authors.slice(0, 8).join(", ")}`,
    `年: ${v.date}  掲載: ${v.venue}`,
    `リンク: ${v.url}`,
  ];
  if (c.one_line) lines.push("", "カード（AIの下書き）:", `一言で: ${c.one_line}`, `主結果: ${c.main_result}`, `設定・公理: ${c.setting}`);
  return lines.join("\n");
}

// 毎朝のフィードの先頭に出す「今日の基本文献」: 未把握のうち前提度が最も高い1本（その日のうちは固定）
function todayKey() { const d = new Date(); return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`; }

function pickToday() {
  if (!canon || !canon.items.length) return null;
  const saved = store.get("canon_today", {});
  const key = todayKey();
  let it = saved.date === key ? canon.items.find((x) => x.id === saved.id) : null;
  if (!it) {
    it = canon.items.find((x) => canonStatus.get(x.id) === 0) || null;
    if (it) store.set("canon_today", { date: key, id: it.id });
  }
  return it;
}

function renderTodayCanon() {
  const box = $("#today-canon");
  const it = currentTab === LIB || currentTab === SAVED || filter.q || filter.tag ? null : pickToday();
  box.hidden = !it;
  if (!it) return;
  const v = canonView(it);
  box.replaceChildren();
  box.append(el("h2", null, "今日の基本文献"));
  const t = el("a", "tc-title", v.title_ja || v.title);
  t.href = "#lib-" + v.id;
  t.addEventListener("click", (e) => { e.preventDefault(); openInLibrary(v.id); });
  box.append(t);
  if (v.card.one_line) box.append(el("p", "tc-line", v.card.one_line));
  box.append(el("p", "tc-src", `${v.authors.slice(0, 3).join(", ")}${v.authors.length > 3 ? " ほか" : ""} (${v.date}) · #${v.rank} · ${LEVELS[canonStatus.get(v.id)]}`));
}

function openInLibrary(id) {
  currentTab = LIB; libStatusFilter = -1; filter.q = ""; filter.tag = ""; $("#q").value = "";
  render();
  const n = document.getElementById("lib-" + id);
  if (n) { n.scrollIntoView({ behavior: "smooth", block: "start" }); n.animate([{ outline: "2px solid var(--accent)" }, { outline: "2px solid transparent" }], 1600); }
}

// ---------------------------------------------------------------- 設定（端末の中だけに保存）
// 大学の EZproxy の入口アドレス。所属がわかるため、コードやリポジトリには書かない。
function proxyPrefix() { return store.get("proxy_prefix", ""); }

function viaProxy(it) {
  const p = proxyPrefix();
  if (!p || !it.doi || it.kind === "news" || /^10\.48550\//.test(it.doi)) return null;  // arXiv・記事は直接
  return p + "https://doi.org/" + encodeURI(it.doi);
}

$("#open-settings").addEventListener("click", () => {
  $("#proxy").value = proxyPrefix();
  $("#settings").showModal();
});
$("#settings").addEventListener("close", () => {
  if ($("#settings").returnValue !== "save") return;
  const v = $("#proxy").value.trim();
  store.set("proxy_prefix", v);
  if (day) render();
});

(async () => {
  try {
    try { siteConfig = { ...siteConfig, ...(await getJSON("site-config.json")) }; } catch { /* なくても動く */ }
    loadCanon();
    index = await getJSON("data/index.json");
    if (!index.latest) throw new Error("no data");
    await loadDay(index.latest);
  } catch (e) {
    $("#list").replaceChildren(el("p", "empty", "データを読み込めませんでした"));
    console.error(e);
  }
})();
