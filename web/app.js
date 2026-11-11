"use strict";

const $ = (id) => document.getElementById(id);
const state = { config: null, job: null, busy: false, keyword: "", itemLimit: 24,
  view: "search", mode: "daily", page: 1, pages: 1, filters: {}, historySequence: 0 };
const statuses = { queued: "等待运行", running: "正在运行", succeeded: "已完成",
  failed: "运行失败", interrupted: "已中断", incomplete: "输出不完整" };
const stages = { queued: "任务已提交", crawling: "正在抓取", saving: "保存数据",
  analyzing: "分析数据", rendering: "生成图片与文案", completed: "抓取和图片生成已完成" };
const nf = new Intl.NumberFormat("zh-CN");
const number = (value) => nf.format(value || 0);
const isRunning = (job) => job && ["queued", "running"].includes(job.status);

function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined && text !== null) item.textContent = text;
  if (className) item.className = className;
  return item;
}

function notice(message = "") {
  $("notice").textContent = message;
  $("notice").hidden = !message;
}

async function api(path, options = {}) {
  const response = await fetch(path, { cache: "no-store", ...options });
  let value;
  try { value = await response.json(); }
  catch { throw new Error("服务未返回有效数据，请确认工作台仍在运行。"); }
  if (!response.ok) throw new Error(value.error || "请求失败，请稍后重试。");
  return value;
}

function keywords() {
  return [...new Set($("keywords").value.split(/[,，\n]/).map((word) => word.trim()).filter(Boolean))];
}

function estimate() {
  const words = keywords();
  const limit = Number($("limit").value);
  $("request-estimate").textContent = words.length && Number.isSafeInteger(limit) && limit > 0
    ? `${words.length} 个关键词 · 合计最多 ${number(words.length * limit)} 条商品记录`
    : "输入关键词和正整数数量后即可开始";
}

function setBusy(busy) {
  state.busy = busy;
  $("start-button").disabled = busy;
  $("start-button").querySelector("span").textContent = busy ? "任务运行中…" : "开始抓取";
  ["keywords", "limit", "record-date"].forEach((id) => { $(id).disabled = busy; });
  $("suggestions").querySelectorAll("button").forEach((button) => { button.disabled = busy; });
}

function statusTag(status) {
  return node("span", statuses[status] || status,
    `status-tag ${["failed", "interrupted", "incomplete"].includes(status) ? "failed" :
      ["queued", "running"].includes(status) ? "running" : ""}`);
}

function itemCard(item) {
  const card = node("article", null, "item-card");
  const title = node("h3", item.title || `商品 ${item.item_id}`);
  title.title = title.textContent;
  card.append(title);
  const bottom = node("div", null, "item-bottom");
  const price = node("span", null, "item-price");
  price.append(node("small", "¥"), document.createTextNode(Number(item.price).toFixed(2)));
  bottom.append(price);
  if (item.url) {
    try {
      const url = new URL(item.url);
      if (url.protocol === "https:" && url.hostname === "www.goofish.com") {
        const link = node("a", "查看商品 ↗", "item-link");
        link.href = url.href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        bottom.append(link);
      }
    } catch { /* Older summaries may not have valid item links. */ }
  }
  card.append(bottom);
  return card;
}

function renderItems() {
  const job = state.job;
  const words = job ? job.keywords : [];
  if (!words.includes(state.keyword)) state.keyword = job?.keyword || words[0] || "";
  const tabs = $("result-tabs");
  tabs.replaceChildren();
  words.forEach((word) => {
    const count = job.items[word]?.length || 0;
    const button = node("button", `${word} · ${number(count)}`,
      `chip ${word === state.keyword ? "active" : ""}`);
    button.type = "button";
    button.setAttribute("aria-pressed", String(word === state.keyword));
    button.addEventListener("click", () => {
      state.keyword = word;
      state.itemLimit = 24;
      renderItems();
    });
    tabs.append(button);
  });
  const items = job?.items[state.keyword] || [];
  const total = Object.values(job?.items || {}).reduce((sum, rows) => sum + rows.length, 0);
  $("result-count").textContent = `${number(total)} 条`;
  $("results").replaceChildren(...items.slice(0, state.itemLimit).map(itemCard));
  $("results-empty").hidden = items.length > 0;
  $("more-results").hidden = items.length <= state.itemLimit;
  if (job && !items.length) {
    $("results-empty").querySelector("h3").textContent = isRunning(job) ? "正在等待这一页的结果" : "这个关键词暂无商品预览";
    $("results-empty").querySelector("p").textContent = job.status === "failed"
      ? "请查看本次运行的错误信息，处理后可重新抓取。" : "搜索结果确认后会显示在这里，历史汇总仍可在历史记录中查看。";
  }
}

function artifactLinks(container, outputId, files = []) {
  container.replaceChildren();
  container.hidden = !outputId;
  if (!outputId) return;
  container.append(node("h3", "本次生成结果"));
  const links = node("div", null, "file-links");
  const previews = node("div", null, "image-previews");
  const labels = { "post.txt": "下载发布文案", "records.json": "下载数据 JSON", "抓取数据.txt": "下载数据文档" };
  files.forEach((file) => {
    const href = `/files/${encodeURIComponent(outputId)}/${encodeURIComponent(file)}`;
    if (file.endsWith(".png")) {
      const link = node("a");
      link.href = href;
      link.target = "_blank";
      link.rel = "noopener";
      const image = node("img");
      image.src = href;
      image.alt = file.startsWith("card1") ? "指数卡片" : file.startsWith("card2") ? "每日信号卡片" : "周报卡片";
      image.loading = "lazy";
      link.append(image);
      previews.append(link);
    } else {
      const link = node("a", labels[file] || file, "file-link");
      link.href = href;
      link.download = file;
      links.append(link);
    }
  });
  container.append(previews, links);
}

function renderJob(job) {
  const previousStatus = state.job?.status;
  if (state.job?.id !== job.id) {
    $("keywords").value = job.keywords.join("，");
    $("limit").value = job.limit;
    $("record-date").value = job.date;
    estimate();
  }
  state.job = job;
  setBusy(isRunning(job));
  $("job-status").replaceWith(Object.assign(statusTag(job.status), { id: "job-status" }));
  const records = Object.values(job.records || {});
  const count = records.reduce((sum, record) => sum + record.item_count, 0);
  const target = job.keywords.length * job.limit;
  const percent = job.status === "succeeded" ? 100 : Math.min(99, Math.round(100 * count / target));
  $("live-keywords").textContent = number(job.keywords.length);
  $("live-items").textContent = number(count);
  $("live-target").textContent = number(target);
  $("job-progress").value = percent;
  $("job-percent").textContent = `${percent}%`;
  $("job-message").textContent = job.stage === "crawling" && job.keyword
    ? `正在抓取 ${job.keyword}${job.page ? ` · 第 ${job.page} 页` : " · 等待搜索响应"}`
    : job.error ? "任务已停止，请查看下方信息。" : stages[job.stage] || job.message;
  $("job-error").hidden = !job.error;
  $("job-error").textContent = job.error || "";
  $("last-update").textContent = `更新于 ${formatTime(job.updated_at, false)}`;
  $("keyword-progress").replaceChildren(...job.keywords.map((word) => {
    const row = node("div", null, "keyword-row");
    const name = node("span", null, "keyword-name");
    const record = job.records[word];
    name.append(node("span", null, `keyword-dot ${record ? "done" : ""}`), document.createTextNode(word));
    const detail = record ? `${number(record.item_count)} 条 · ${number(record.seller_count)} 位卖家`
      : job.keyword === word && isRunning(job) ? "正在搜索…" : "尚未返回结果";
    row.append(name, node("span", detail, "keyword-count"));
    return row;
  }));
  renderItems();
  // Avoid reloading all three images on each running-job poll.
  if (job.output_id && previousStatus !== "succeeded") {
    artifactLinks($("current-artifacts"), job.output_id, job.files || []);
  } else if (!job.output_id) {
    $("current-artifacts").hidden = true;
  }
}

async function pollJob(id) {
  try {
    const job = await api(`/api/jobs/${encodeURIComponent(id)}`);
    if (state.job && state.job.id !== id) return;
    renderJob(job);
    notice();
    if (isRunning(job)) setTimeout(() => pollJob(id), 1200);
    else if (state.view === "history") loadHistory();
  } catch (error) {
    notice(`实时状态暂时无法更新：${error.message} 保持服务窗口打开，页面会继续重试。`);
    setTimeout(() => pollJob(id), 3000);
  }
}

function formatTime(value, includeDate = true) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai",
    ...(includeDate ? { year: "numeric", month: "2-digit", day: "2-digit" } : {}),
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(d);
}

function switchView(view) {
  state.view = view;
  $("search-view").hidden = view !== "search";
  $("history-view").hidden = view !== "history";
  $("nav-search").classList.toggle("selected", view === "search");
  $("nav-history").classList.toggle("selected", view === "history");
  $("nav-search").setAttribute("aria-current", view === "search" ? "page" : "false");
  $("nav-history").setAttribute("aria-current", view === "history" ? "page" : "false");
  $("breadcrumb").replaceChildren(document.createTextNode("工作空间 "), node("b", "/"), document.createTextNode(view === "search" ? " 搜索抓取" : " 历史记录"));
  if (view === "history") loadHistory();
}

function emptyHistory() {
  const wrapper = node("div", null, "empty-state");
  wrapper.append(node("span", "↺", "empty-icon"), node("h3", "没有符合条件的记录"), node("p", "试试其他关键词或日期，或开始一次新的抓取。"));
  return wrapper;
}

function recordsTable(rows) {
  const wrap = node("div", null, "table-wrap");
  const table = node("table");
  const head = node("thead");
  const headings = node("tr");
  ["记录日期", "关键词", "商品数", "卖家数", "平均价格"].forEach((title, i) => {
    const th = node("th", title, i > 1 ? "table-number" : "");
    th.scope = "col";
    headings.append(th);
  });
  head.append(headings);
  const body = node("tbody");
  rows.forEach((row) => {
    const tr = node("tr");
    tr.append(node("td", row.date), node("td", row.keyword, "keyword-cell"),
      node("td", number(row.item_count), "table-number"), node("td", number(row.seller_count), "table-number"),
      node("td", `¥ ${Number(row.avg_price).toFixed(2)}`, "table-number"));
    body.append(tr);
  });
  table.append(head, body);
  wrap.append(table);
  return wrap;
}

function runsTable(rows) {
  const wrap = node("div", null, "table-wrap");
  const table = node("table");
  const head = node("thead");
  const headings = node("tr");
  ["运行时间 · 北京", "关键词", "状态", "已抓商品", ""].forEach((title) => {
    const th = node("th", title);
    th.scope = "col";
    headings.append(th);
  });
  head.append(headings);
  const body = node("tbody");
  rows.forEach((row) => {
    const tr = node("tr");
    const time = node("td", formatTime(row.created_at), "run-time");
    time.append(node("small", `记录日期 ${row.date}${row.limit ? ` · 每词上限 ${row.limit}` : " · 旧版快照"}`));
    const status = node("td");
    status.append(statusTag(row.status));
    const action = node("td");
    const button = node("button", "查看详情 ↗", "text-button");
    button.type = "button";
    button.addEventListener("click", () => showRun(row));
    action.append(button);
    tr.append(time, node("td", row.keywords.join("、"), "keyword-cell"), status,
      node("td", number(row.total_items), "table-number"), action);
    body.append(tr);
  });
  table.append(head, body);
  wrap.append(table);
  return wrap;
}

async function loadHistory() {
  const sequence = ++state.historySequence;
  $("history-error").hidden = true;
  $("history-total").textContent = "正在读取…";
  $("previous-page").disabled = true;
  $("next-page").disabled = true;
  const query = new URLSearchParams({ ...state.filters, page: state.page });
  try {
    const data = await api(`/api/${state.mode === "daily" ? "history" : "runs"}?${query}`);
    if (sequence !== state.historySequence) return;
    state.page = data.page;
    state.pages = data.pages;
    $("history-content").replaceChildren(data.rows.length
      ? state.mode === "daily" ? recordsTable(data.rows) : runsTable(data.rows)
      : emptyHistory());
    $("history-total").textContent = `共 ${number(data.total)} 条${state.mode === "daily" ? "汇总记录" : "运行记录"}`;
    $("page-label").textContent = `${data.page} / ${data.pages}`;
    $("previous-page").disabled = data.page <= 1;
    $("next-page").disabled = data.page >= data.pages;
    $("history-summary").replaceChildren();
    if (data.summary) {
      [[data.summary.keywords, "个关键词"], [data.summary.days, "天观测"],
        [data.summary.items, "条商品记录"]].forEach(([value, label]) => {
        const metric = node("span");
        metric.append(node("strong", number(value)), document.createTextNode(label));
        $("history-summary").append(metric);
      });
    }
  } catch (error) {
    if (sequence !== state.historySequence) return;
    $("history-error").textContent = error.message;
    $("history-error").hidden = false;
    $("history-content").replaceChildren();
    $("history-summary").replaceChildren();
    $("history-total").textContent = "读取失败，请修改筛选条件或重试";
  }
}

async function showRun(row) {
  const dialog = $("run-dialog");
  const content = $("dialog-content");
  content.replaceChildren(node("p", "正在读取运行详情…", "detail-note"));
  dialog.showModal();
  try {
    const data = await api(`/api/${row.kind === "job" ? "jobs" : "snapshots"}/${encodeURIComponent(row.id)}`);
    content.replaceChildren(node("p", `${formatTime(data.created_at)} · ${statuses[data.status] || data.status} · 记录日期 ${data.date}`, "detail-meta"));
    if (data.error) content.append(node("div", data.error, "error-box"));
    const records = Array.isArray(data.records) ? data.records : Object.values(data.records || {});
    content.append(records.length ? recordsTable(records) : node("p", "还没有返回汇总数据。", "detail-note"));
    const outputs = node("div", null, "artifacts");
    artifactLinks(outputs, data.output_id, data.files || []);
    content.append(outputs);
    const items = Object.entries(data.items || {});
    if (items.length) {
      content.append(node("p", "商品预览（每个关键词最多展示前 24 条）", "detail-note"));
      items.forEach(([word, products]) => {
        content.append(node("h3", `${word} · ${number(products.length)} 条`));
        const grid = node("div", null, "item-grid");
        grid.append(...products.slice(0, 24).map(itemCard));
        content.append(grid);
      });
    } else content.append(node("p", row.kind === "snapshot"
      ? "这次运行只保存了汇总数据，没有商品明细。新网页任务会保存商品预览。"
      : "这次任务尚未取得商品预览。", "detail-note"));
  } catch (error) { content.replaceChildren(node("div", error.message, "error-box")); }
}

function setHistoryMode(mode) {
  state.mode = mode;
  state.page = 1;
  $("mode-daily").classList.toggle("active", mode === "daily");
  $("mode-runs").classList.toggle("active", mode === "runs");
  $("history-mode-hint").textContent = mode === "daily"
    ? "同日同词保留最新结果 · 按记录日期筛选" : "保留每次尝试 · 按运行日期筛选（北京时间）";
  loadHistory();
}

$("search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.config || state.busy) return;
  const words = keywords();
  const limit = Number($("limit").value);
  if (!words.length || !Number.isSafeInteger(limit) || limit < 1) {
    notice("请至少输入一个关键词，抓取数量必须为正整数。");
    return;
  }
  setBusy(true);
  notice();
  try {
    const job = await api("/api/jobs", { method: "POST",
      headers: { "Content-Type": "application/json", "X-AI-Index-Token": state.config.token },
      body: JSON.stringify({ keywords: words, limit, date: $("record-date").value }) });
    state.job = null;
    state.keyword = words[0];
    state.itemLimit = 24;
    try { localStorage.setItem("last-job-id", job.id); } catch { /* Storage may be disabled. */ }
    renderJob(job);
    pollJob(job.id);
  } catch (error) {
    notice(error.message);
    setBusy(false);
    // Another tab may have claimed the single worker slot.
    try {
      const { job } = await api("/api/active");
      if (job) { renderJob(job); pollJob(job.id); }
    } catch { /* Keep the original submission error visible. */ }
  }
});
$("keywords").addEventListener("input", estimate);
$("limit").addEventListener("input", estimate);
$("more-results").addEventListener("click", () => { state.itemLimit += 24; renderItems(); });
$("nav-search").addEventListener("click", () => { location.hash = "search"; switchView("search"); });
$("nav-history").addEventListener("click", () => { location.hash = "history"; switchView("history"); });
window.addEventListener("hashchange", () => switchView(location.hash === "#history" ? "history" : "search"));
$("mode-daily").addEventListener("click", () => setHistoryMode("daily"));
$("mode-runs").addEventListener("click", () => setHistoryMode("runs"));
$("refresh-history").addEventListener("click", loadHistory);
$("filter-form").addEventListener("submit", (event) => {
  event.preventDefault();
  state.filters = { keyword: $("filter-keyword").value.trim(), start: $("filter-start").value, end: $("filter-end").value };
  state.page = 1;
  loadHistory();
});
$("reset-filters").addEventListener("click", () => {
  $("filter-form").reset(); state.filters = {}; state.page = 1; loadHistory();
});
$("previous-page").addEventListener("click", () => { if (state.page > 1) { state.page--; loadHistory(); } });
$("next-page").addEventListener("click", () => { if (state.page < state.pages) { state.page++; loadHistory(); } });
$("close-dialog").addEventListener("click", () => $("run-dialog").close());
$("run-dialog").addEventListener("click", (event) => { if (event.target === $("run-dialog")) {
  const rect = $("run-dialog").getBoundingClientRect();
  if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) $("run-dialog").close();
} });

async function boot() {
  setBusy(true);
  try {
    state.config = await api("/api/config");
    document.title = `${state.config.title} · 搜索工作台`;
    $("brand-title").textContent = state.config.title;
    $("author").textContent = state.config.author;
    $("avatar").textContent = state.config.author.slice(0, 1).toUpperCase();
    $("record-date").value = state.config.today;
    $("limit").value = state.config.default_limit;
    state.config.suggestions.slice(0, 4).forEach((word) => {
      const button = node("button", `+ ${word}`, "chip");
      button.type = "button";
      button.addEventListener("click", () => {
        const words = keywords();
        if (!words.includes(word)) words.push(word);
        $("keywords").value = words.join("，");
        estimate();
      });
      $("suggestions").append(button);
    });
    setBusy(false);
    estimate();
    const { job } = await api("/api/active");
    if (job) { renderJob(job); pollJob(job.id); }
    else {
      let last;
      try { last = localStorage.getItem("last-job-id"); } catch { /* Optional convenience only. */ }
      if (last) {
        try { renderJob(await api(`/api/jobs/${encodeURIComponent(last)}`)); }
        catch { try { localStorage.removeItem("last-job-id"); } catch { /* Optional. */ } }
      }
    }
    switchView(location.hash === "#history" ? "history" : "search");
  } catch (error) { setBusy(true); notice(`工作台连接失败：${error.message} 请保持服务窗口打开后刷新。`); }
}
function updateClock() {
  $("clock").textContent = new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai",
    month: "2-digit", day: "2-digit", weekday: "short" }).format(new Date());
}
updateClock();
boot();
