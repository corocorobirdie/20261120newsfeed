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

const $ = (s) => document.querySelector(s);
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* 保存できない環境では無視 */ } },
};

let index = { dates: [] };
let day = null;
let currentTab = store.get("tab", "papers");

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
  day = await getJSON(`data/daily/${date}.json`);
  const i = index.dates.indexOf(date);
  $("#date").textContent = fmtDate(date);
  $("#next").disabled = i <= 0;
  $("#prev").disabled = i < 0 || i >= index.dates.length - 1;
  if (!day.tabs[currentTab]) currentTab = TAB_ORDER.find((t) => day.tabs[t]) || "papers";
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
    b.addEventListener("click", () => { currentTab = t; store.set("tab", t); render(); window.scrollTo({ top: 0 }); });
    nav.append(b);
  }
}

function renderHighlights() {
  const all = Object.values(day.tabs).flat();
  const byId = new Map(all.map((x) => [x.id, x]));
  const items = (day.highlights || []).map((id) => byId.get(id)).filter(Boolean);
  const box = $("#highlights");
  box.hidden = items.length === 0;
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
  node.id = "c-" + it.id;
  const star = it.author_group === "A";
  if (star) node.classList.add("starred");

  const badges = node.querySelector(".badges");
  if (star) badges.append(el("span", "badge star", "★ " + (it.author_hits || []).join(", ")));
  else if (it.author_hits && it.author_hits.length) badges.append(el("span", "badge", "著者: " + it.author_hits.join(", ")));
  if (it.score != null) badges.append(el("span", "badge score", `関連度 ${it.score}`));

  const a = node.querySelector(".title-ja a");
  a.textContent = it.title_ja || it.title;
  a.href = it.url;
  const ul = node.querySelector(".summary");
  for (const s of it.summary_ja || []) ul.append(el("li", null, s));
  node.querySelector(".reason").textContent = it.reason_ja || "";
  node.querySelector(".orig-title").textContent = it.title_ja ? it.title : "";
  const authors = it.authors || [];
  node.querySelector(".byline").textContent = authors.slice(0, 6).join(", ") + (authors.length > 6 ? ` ほか${authors.length - 6}名` : "");
  node.querySelector(".src").textContent = [it.venue, (it.lang || "").toUpperCase(), it.date].filter(Boolean).join(" · ");
  const tags = node.querySelector(".tags");
  for (const t of it.tags || []) tags.append(el("span", null, t));
  node.querySelector(".open").href = it.url;

  const btn = node.querySelector(".toggle-orig");
  const orig = node.querySelector(".orig");
  if (!it.abstract) btn.remove();
  btn.addEventListener("click", () => {
    if (!orig.childElementCount) {
      orig.append(el("span", "label", "原文（要旨）"), el("div", null, it.abstract));
    }
    orig.hidden = !orig.hidden;
    btn.textContent = orig.hidden ? "原文を表示" : "原文を隠す";
  });
  return node;
}

function render() {
  renderTabs();
  renderHighlights();
  const items = day.tabs[currentTab] || [];
  const list = $("#list");
  list.replaceChildren(...items.map(card));
  if (!items.length) list.append(el("p", "empty", "この日の新着はありません"));
  const notes = [];
  if (day.generated_at) notes.push(`更新 ${day.generated_at.slice(11, 16)}`);
  if (!day.model) notes.push("要約なし（Gemini未設定）");
  $("#meta").textContent = notes.join(" · ");
}

// ---------------------------------------------------------------- 起動
$("#prev").addEventListener("click", () => { const i = index.dates.indexOf(day.date); if (i < index.dates.length - 1) loadDay(index.dates[i + 1]); });
$("#next").addEventListener("click", () => { const i = index.dates.indexOf(day.date); if (i > 0) loadDay(index.dates[i - 1]); });

(async () => {
  try {
    index = await getJSON("data/index.json");
    if (!index.latest) throw new Error("no data");
    await loadDay(index.latest);
  } catch (e) {
    $("#list").replaceChildren(el("p", "empty", "データを読み込めませんでした"));
    console.error(e);
  }
})();
