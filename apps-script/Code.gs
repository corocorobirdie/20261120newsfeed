/**
 * Morning Feed の補助（Google Apps Script）
 *
 *  1. 端末間の同期: しおり・文献の把握度・設定を、自分の Google ドライブの1ファイルにまとめて保存する
 *  2. 毎朝の確実な起動: 毎朝 GitHub Actions のフィード作成を起動し、遅れていれば再度起動する
 *  3. フィードの中継: GitHub から読めないフィード（Substack）を代わりに取得して渡す
 *
 * 設定はすべて「プロジェクトの設定 → スクリプト プロパティ」に置く（コードには書かない）:
 *   TOKEN      合言葉。setup() を実行すると自動で作られる
 *   GH_TOKEN   GitHub の fine-grained token（このリポジトリの Actions: Read and write だけ）
 *   GH_REPO    例: corocorobirdie/20261120newsfeed
 *   SITE_URL   例: https://corocorobirdie.github.io/20261120newsfeed/
 */

const FILE_NAME = "morning-feed-sync.json";
const PROXY_HOSTS = [/(^|\.)substack\.com$/];  // 中継してよいフィードの置き場所

function props() { return PropertiesService.getScriptProperties(); }

// ------------------------------------------------------------------ 初回だけ実行
function setup() {
  const p = props();
  if (!p.getProperty("TOKEN")) p.setProperty("TOKEN", Utilities.getUuid().replace(/-/g, ""));
  // 毎朝の起動（6:40）と、遅れていないかの確認（8:20・10:20）
  for (const t of ScriptApp.getProjectTriggers()) ScriptApp.deleteTrigger(t);
  ScriptApp.newTrigger("morningRun").timeBased().atHour(6).nearMinute(40).everyDays(1).inTimezone("Asia/Tokyo").create();
  ScriptApp.newTrigger("morningCheck").timeBased().atHour(8).nearMinute(20).everyDays(1).inTimezone("Asia/Tokyo").create();
  ScriptApp.newTrigger("morningCheck").timeBased().atHour(10).nearMinute(20).everyDays(1).inTimezone("Asia/Tokyo").create();
  syncFile_();
  console.log("合言葉（TOKEN）: " + p.getProperty("TOKEN"));
  console.log("トリガーを作りました: " + ScriptApp.getProjectTriggers().length + " 件");
}

// ------------------------------------------------------------------ Web アプリの入口
function doGet(e) {
  const q = e.parameter || {};
  if (!authorized_(q.token)) return json_({ error: "unauthorized" });
  if (q.action === "feed") return feed_(q.url);
  if (q.action === "get") return json_(readState_());
  return json_({ ok: true });
}

function doPost(e) {
  let body;
  try { body = JSON.parse(e.postData.contents); } catch (err) { return json_({ error: "bad request" }); }
  if (!authorized_(body.token)) return json_({ error: "unauthorized" });
  if (body.action === "sync") return json_(sync_(body.state || {}));
  return json_({ error: "unknown action" });
}

function authorized_(token) {
  const t = props().getProperty("TOKEN");
  return !!t && token === t;
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

// ------------------------------------------------------------------ 1. 同期
function syncFile_() {
  const p = props();
  const id = p.getProperty("FILE_ID");
  if (id) {
    try { return DriveApp.getFileById(id); } catch (err) { /* 消されていたら作り直す */ }
  }
  const f = DriveApp.createFile(FILE_NAME, JSON.stringify({ bookmarks: {}, canon_status: {}, prefs: {} }), "application/json");
  p.setProperty("FILE_ID", f.getId());
  return f;
}

function readState_() {
  try { return JSON.parse(syncFile_().getBlob().getDataAsString()); } catch (err) { return { bookmarks: {}, canon_status: {}, prefs: {} }; }
}

// 各項目の更新時刻（削除も記録として残し、新しいほうを採る）
function ts_(e) { return (e && (e.deleted_at || e.updated || e.saved_at || e.t)) || ""; }

function mergeSection_(a, b) {
  const out = Object.assign({}, a || {});
  for (const [k, v] of Object.entries(b || {})) {
    if (!out[k] || ts_(v) > ts_(out[k])) out[k] = v;
  }
  return out;
}

function sync_(local) {
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const cur = readState_();
    const merged = {};
    for (const s of ["bookmarks", "canon_status", "prefs"]) merged[s] = mergeSection_(cur[s], local[s]);
    merged.updated = new Date().toISOString();
    syncFile_().setContent(JSON.stringify(merged));
    return merged;
  } finally {
    lock.releaseLock();
  }
}

// ------------------------------------------------------------------ 2. 毎朝の起動
function todayJst_() { return Utilities.formatDate(new Date(), "Asia/Tokyo", "yyyy-MM-dd"); }

function gh_(method, path, payload) {
  const p = props();
  const res = UrlFetchApp.fetch("https://api.github.com/repos/" + p.getProperty("GH_REPO") + path, {
    method: method,
    headers: { Authorization: "Bearer " + p.getProperty("GH_TOKEN"), Accept: "application/vnd.github+json" },
    contentType: "application/json",
    payload: payload ? JSON.stringify(payload) : undefined,
    muteHttpExceptions: true,
  });
  return res;
}

function morningRun() {
  const res = gh_("post", "/actions/workflows/daily.yml/dispatches", { ref: "main", inputs: { site_only: "false" } });
  console.log("起動: " + res.getResponseCode() + " " + res.getContentText().slice(0, 200));
}

// 今日の分が公開されておらず、実行中・待機中のものもなければもう一度起動する
function morningCheck() {
  const site = props().getProperty("SITE_URL");
  try {
    const idx = JSON.parse(UrlFetchApp.fetch(site.replace(/\/?$/, "/") + "data/index.json?t=" + Date.now()).getContentText());
    if (idx.latest === todayJst_()) { console.log("今日の分は公開済み"); return; }
  } catch (err) { console.log("index.json を読めませんでした: " + err); }
  for (const st of ["in_progress", "queued"]) {
    const r = JSON.parse(gh_("get", "/actions/workflows/daily.yml/runs?status=" + st + "&per_page=1").getContentText());
    if (r.total_count > 0) { console.log("実行中のものがあるので待つ"); return; }
  }
  morningRun();
}

// ------------------------------------------------------------------ 3. フィードの中継
function feed_(url) {
  let host = "";
  try { host = url.match(/^https:\/\/([^/?#]+)/)[1].toLowerCase(); } catch (err) { /* 不正なアドレス */ }
  if (!PROXY_HOSTS.some((re) => re.test(host))) return json_({ error: "host not allowed" });
  const res = UrlFetchApp.fetch(url, { muteHttpExceptions: true, followRedirects: true });
  if (res.getResponseCode() !== 200) return json_({ error: "upstream " + res.getResponseCode() });
  return ContentService.createTextOutput(res.getContentText()).setMimeType(ContentService.MimeType.RSS);
}
