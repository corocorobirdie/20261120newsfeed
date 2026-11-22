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
  if (currentTab !== SAVED && !day.tabs[currentTab]) currentTab = TAB_ORDER.find((t) => day.tabs[t]) || "papers";
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
  box.hidden = items.length === 0 || !!(filter.q || filter.tag) || currentTab === SAVED;  // 絞り込み中・保存済みタブでは隠す
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
  node.querySelector(".open").href = it.url;
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

(async () => {
  try {
    try { siteConfig = { ...siteConfig, ...(await getJSON("site-config.json")) }; } catch { /* なくても動く */ }
    index = await getJSON("data/index.json");
    if (!index.latest) throw new Error("no data");
    await loadDay(index.latest);
  } catch (e) {
    $("#list").replaceChildren(el("p", "empty", "データを読み込めませんでした"));
    console.error(e);
  }
})();
