const SCENARIOS = [
  { id: "S0", name: "日常波动", detail: "正常波动" },
  { id: "S1", name: "活动缺失", detail: "习惯活动缺失" },
  { id: "S2", name: "活动延迟", detail: "延迟 / 长间隔" },
  { id: "S3", name: "已知外出", detail: "外出抑制提醒" },
  { id: "S4", name: "数据中断", detail: "计量数据缺失" },
  { id: "S5", name: "自动负荷", detail: "仅自动负荷" },
  { id: "S6", name: "负荷重叠", detail: "相似 / 重叠负荷" },
  { id: "S7", name: "通知失败", detail: "通知渠道失败" },
];
const COLORS = {
  kettle: "#b78232", microwave: "#c76870", tv: "#6288ae",
  refrigerator: "#89838f", unknown: "#8b72a1",
};
const ICONS = { kettle: "kettle", microwave: "microwave", tv: "tv", refrigerator: "fridge", unknown: "unknown" };
const APPLIANCE_ZH = { kettle: "电水壶", microwave: "微波炉", tv: "电视", refrigerator: "冰箱", unknown: "未知" };
const STATUS_ZH = { pending: "待确认", confirmed: "已确认平安", followup: "待跟进", accepted: "已接单", done: "已完成" };
const ACTION_ZH = { confirmed: "确认平安", followup: "转跟进", accepted: "接单", done: "完成" };

let state = { power: [], comparison: [], activities: [], events: [], now: 0, playing: false, speed: 1, raf: null, lastTs: 0, scenario: "S1" };

function el(id) { return document.getElementById(id); }
function iconMarkup(name, className = "") {
  const symbol = ICONS[name] || "unknown";
  return `<svg class="${className}" aria-hidden="true"><use href="#icon-${symbol}"></use></svg>`;
}
function setSystemState(kind, label) {
  const box = el("system-state");
  box.classList.toggle("is-ready", kind === "ready");
  box.classList.toggle("is-error", kind === "error");
  el("system-state-label").textContent = label;
}

// ---------- Pyodide Worker ----------
let worker = null;
let workerReady = false;
let msgSeq = 0;
const pending = new Map();

function callWorker(action, payload) {
  if (!worker) return Promise.reject(new Error("仿真引擎未启动。"));
  return new Promise((resolve, reject) => {
    const id = ++msgSeq;
    pending.set(id, { resolve, reject });
    worker.postMessage({ id, action, payload });
  });
}

function initWorker() {
  worker = new Worker("worker.js");
  worker.onmessage = (event) => {
    const data = event.data;
    if (!data) return;
    if (data.type === "status") {
      const msg = el("pyodide-loading-message");
      if (msg) msg.textContent = data.message;
      return;
    }
    if (data.type === "ready") {
      workerReady = true;
      el("pyodide-loading").classList.add("is-hidden");
      setSystemState("", "仿真待启动");
      return;
    }
    if (data.type === "error") {
      const msg = el("pyodide-loading-message");
      if (msg) msg.textContent = "加载失败：" + data.message;
      setSystemState("error", "引擎加载失败");
      return;
    }
    const p = pending.get(data.id);
    if (!p) return;
    pending.delete(data.id);
    if (data.ok) p.resolve(data.result);
    else p.reject(new Error(data.error || "引擎调用失败"));
  };
}

// ---------- 初始化场景按钮 ----------
function initScenarioButtons() {
  const box = el("scenario-buttons");
  SCENARIOS.forEach(s => {
    const b = document.createElement("button");
    b.type = "button";
    b.dataset.scenario = s.id;
    b.title = `${s.id} · ${s.detail}`;
    b.setAttribute("aria-label", `${s.id} ${s.detail}`);
    b.setAttribute("aria-pressed", "false");
    b.innerHTML = `<span class="scene-code">${s.id}</span><span class="scene-name">${s.name}</span>`;
    b.onclick = () => selectScenario(s.id);
    box.appendChild(b);
  });
  selectScenario("S1");
  renderLegend();
}
function selectScenario(id) {
  const scenario = SCENARIOS.find(s => s.id === id);
  if (!scenario) return;
  state.scenario = id;
  document.querySelectorAll("#scenario-buttons button").forEach(b => {
    const active = b.dataset.scenario === id;
    b.classList.toggle("active", active);
    b.setAttribute("aria-pressed", String(active));
  });
  el("metric-scenario").textContent = id;
  el("metric-scenario-name").textContent = scenario.name;
}

function initDatasetFilters() {
  document.querySelectorAll("[data-country-filter]").forEach(button => {
    button.onclick = () => {
      const country = button.dataset.countryFilter;
      document.querySelectorAll("[data-country-filter]").forEach(option => {
        const active = option === button;
        option.classList.toggle("is-active", active);
        option.setAttribute("aria-pressed", String(active));
      });
      document.querySelectorAll("[data-country-group]").forEach(group => {
        group.hidden = country !== "all" && group.dataset.countryGroup !== country;
      });
    };
  });
}

let datasetDrawerOpener = null;
function openDatasetDrawer(opener) {
  const drawer = el("datasets");
  datasetDrawerOpener = opener;
  drawer.classList.add("is-open");
  drawer.setAttribute("aria-hidden", "false");
  drawer.inert = false;
  document.body.classList.add("drawer-open");
  el("dataset-drawer-scrim").hidden = false;
  document.querySelectorAll("[data-open-dataset-drawer]").forEach(button => button.setAttribute("aria-expanded", "true"));
  el("dataset-drawer-close").focus();
}

function closeDatasetDrawer() {
  const drawer = el("datasets");
  if (!drawer.classList.contains("is-open")) return;
  drawer.classList.remove("is-open");
  drawer.setAttribute("aria-hidden", "true");
  drawer.inert = true;
  document.body.classList.remove("drawer-open");
  el("dataset-drawer-scrim").hidden = true;
  document.querySelectorAll("[data-open-dataset-drawer]").forEach(button => button.setAttribute("aria-expanded", "false"));
  if (datasetDrawerOpener?.isConnected) datasetDrawerOpener.focus();
}

function initDatasetDrawer() {
  document.querySelectorAll("[data-open-dataset-drawer]").forEach(button => {
    button.setAttribute("aria-expanded", "false");
    button.onclick = event => {
      event.preventDefault();
      openDatasetDrawer(button);
    };
  });
  el("dataset-drawer-close").onclick = closeDatasetDrawer;
  el("dataset-drawer-scrim").onclick = closeDatasetDrawer;
  document.addEventListener("keydown", event => {
    const drawer = el("datasets");
    if (!drawer.classList.contains("is-open")) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeDatasetDrawer();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [...drawer.querySelectorAll("a[href], button:not(:disabled)")].filter(node => node.getClientRects().length > 0);
    if (!focusable.length) return;
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (event.shiftKey && (document.activeElement === first || !drawer.contains(document.activeElement))) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || !drawer.contains(document.activeElement))) {
      event.preventDefault(); first.focus();
    }
  });
}

// ---------- 运行 ----------
async function run() {
  if (!workerReady) { el("run-info").textContent = "仿真引擎仍在加载，请稍候。"; return; }
  const button = el("run-btn");
  const seed = el("seed").value;
  const history = el("history-days").value;
  const away = el("away").checked;
  const payload = { scenario: state.scenario, seed, history_days: history };
  if (away) payload.away = true;
  button.disabled = true;
  el("run-info").textContent = "正在计算活动规律与关怀判定…";
  setSystemState("", "仿真运行中");
  try {
    const data = await callWorker("run", payload);
    if (data.error) throw new Error(data.error);

    el("channel-label").textContent = data.notify_channel || "mock";
    el("channel-label-footer").textContent = data.notify_channel || "mock";
    el("run-info").textContent = `${data.scenario} · ${data.description} · 种子 ${data.seed}`;
    el("metric-scenario").textContent = data.scenario;
    el("metric-scenario-name").textContent = scenarioName(data.scenario);
    const activityCount = data.test_activities.filter(a => !a.is_auto).length;
    const stableWindows = Object.values(data.windows).flat().filter(w => w.stable).length;
    el("metric-activities").textContent = activityCount;
    el("metric-windows").textContent = stableWindows;
    renderWindows(data.windows);
    renderDecisions(data.decisions);
    renderActivities(data.test_activities);
    renderPowerComparison(data.power_comparison);
    state.events = Array.isArray(data.events) ? data.events : [];
    await loadPower();
    renderEvents();
    setSystemState("ready", "仿真已完成");
  } catch (error) {
    el("run-info").textContent = error.message || "仿真运行失败，请重试。";
    setSystemState("error", "运行失败");
  } finally {
    button.disabled = false;
  }
}

function scenarioName(id) {
  return (SCENARIOS.find(s => s.id === id) || {}).name || id;
}

async function loadPower() {
  const power = await callWorker("power", { resample_min: 1 });
  if (!Array.isArray(power)) throw new Error((power && power.error) || "功率数据加载失败。");
  state.power = power;
  state.now = 0;
  state.playing = false;
  el("chart-empty").classList.toggle("is-hidden", power.length > 0);
  el("power-record-count").textContent = `${power.length.toLocaleString("zh-CN")} 个分钟点`;
  const missing = power.reduce((sum, p) => sum + (p.missing || 0), 0);
  el("quality-note").textContent = missing ? `功率单位：W · 缺失采样 ${missing} 点` : "功率单位：W · 全天分钟采样";
  setPlayButton(false);
  drawChart();
}

function renderPowerComparison(comparison) {
  state.comparison = Array.isArray(comparison) ? comparison : [];
  const count = state.comparison.reduce((sum, item) => sum + (item.activity_count || 0), 0);
  el("comparison-record-count").textContent = `${state.comparison.length} 类电器 · ${count} 段活动`;
  el("comparison-empty").classList.toggle("is-hidden", state.comparison.length > 0);
  drawPowerComparison();
}

function drawPowerComparison() {
  const canvas = el("power-comparison-chart");
  const ctx = canvas.getContext("2d");
  const ratio = window.devicePixelRatio || 1;
  const W = canvas.clientWidth;
  const H = canvas.clientHeight || 220;
  canvas.width = Math.round(W * ratio);
  canvas.height = Math.round(H * ratio);
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, W, H);
  if (!state.comparison.length) return;

  const padL = 39, padR = 10, padT = 18, padB = 40;
  const values = state.comparison.flatMap(item => [item.regular_w, item.day_w]).filter(Number.isFinite);
  const maxP = Math.max(100, ...values) * 1.16;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const yOf = value => padT + plotH - (value / maxP) * plotH;
  const groupW = plotW / state.comparison.length;
  const barGap = 5;
  const barW = Math.min(24, Math.max(10, (groupW - 22 - barGap) / 2));

  ctx.font = "9px -apple-system, BlinkMacSystemFont, sans-serif";
  ctx.textBaseline = "middle";
  ctx.textAlign = "right";
  for (let i = 0; i <= 3; i++) {
    const value = maxP * i / 3;
    const y = yOf(value);
    ctx.strokeStyle = i === 0 ? "#cfc4d8" : "#eee9f1";
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
    ctx.fillStyle = "#897f90";
    ctx.fillText(`${Math.round(value)}`, padL - 6, y);
  }

  state.comparison.forEach((item, index) => {
    const center = padL + groupW * (index + 0.5);
    const startX = center - (barW * 2 + barGap) / 2;
    const bars = [
      { value: item.regular_w, color: "#c8b4d4", x: startX },
      { value: item.day_w, color: "#806296", x: startX + barW + barGap },
    ];
    bars.forEach(bar => {
      if (!Number.isFinite(bar.value)) return;
      const y = yOf(bar.value);
      ctx.fillStyle = bar.color;
      ctx.beginPath();
      ctx.roundRect(bar.x, y, barW, Math.max(1, padT + plotH - y), 2);
      ctx.fill();
      ctx.fillStyle = "#63566d";
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      ctx.font = "9px -apple-system, BlinkMacSystemFont, sans-serif";
      ctx.fillText(`${Math.round(bar.value)}`, bar.x + barW / 2, Math.max(9, y - 3));
    });

    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.font = "10px -apple-system, BlinkMacSystemFont, sans-serif";
    ctx.fillStyle = "#554b60";
    ctx.fillText(APPLIANCE_ZH[item.appliance] || item.appliance, center, H - 23);
    if (!Number.isFinite(item.day_w)) {
      ctx.fillStyle = "#998ea0";
      ctx.font = "8px -apple-system, BlinkMacSystemFont, sans-serif";
      ctx.fillText("无活动", center, H - 9);
    }
  });
}

// ---------- 规律与解释 ----------
function renderWindows(windows) {
  const box = el("windows");
  box.innerHTML = "<h3>学习到的使用时间窗</h3>";
  const apps = Object.keys(windows);
  if (!apps.length) { box.innerHTML += "<div class='empty-state'>暂无足够历史活动</div>"; return; }
  apps.forEach(app => {
    const ws = windows[app];
    const card = document.createElement("div");
    card.className = "window-card";
    const stableAll = ws.every(w => w.stable);
    const title = document.createElement("div");
    title.className = "window-title";
    title.innerHTML = `<span class="appliance-icon ${app}">${iconMarkup(app)}</span><span><span class="app">${APPLIANCE_ZH[app] || app}</span><br><span class="stability-label">${stableAll ? "规律稳定" : "部分不稳定"}</span></span>`;
    const entries = document.createElement("div");
    entries.className = "window-entries";
    ws.forEach(w => {
      const entry = document.createElement("div");
      entry.className = "window-entry";
      const range = document.createElement("span");
      range.className = "window-range";
      range.textContent = `${fmtH(w.span_min / 60)}–${fmtH(w.span_max / 60)}`;
      const meter = document.createElement("span");
      meter.className = "window-meter";
      const fill = document.createElement("span");
      fill.style.width = `${Math.max(0, Math.min(100, w.appearance_ratio * 100))}%`;
      meter.appendChild(fill);
      const meta = document.createElement("span");
      meta.className = "window-percent";
      meta.textContent = `${(w.appearance_ratio * 100).toFixed(0)}% · ${w.valid_days}日`;
      entry.append(range, meter, meta);
      entries.appendChild(entry);
    });
    card.append(title, entries);
    box.appendChild(card);
  });
}

function renderDecisions(decisions) {
  const box = el("decisions");
  box.innerHTML = "<h3>关怀判定</h3>";
  if (!decisions.length) {
    box.innerHTML += "<div class='empty-state'>本场景没有可提醒的偏离，或活动处于正常范围。</div>";
    return;
  }
  const zh = { alert: "需要确认", insufficient: "证据不足", away: "外出抑制", unstable: "历史不足" };
  decisions.forEach(d => {
    const c = document.createElement("div");
    c.className = `decision-card ${d.outcome}`;
    const title = document.createElement("div");
    title.className = "decision-title";
    title.textContent = `${APPLIANCE_ZH[d.appliance] || d.appliance} · ${zh[d.outcome] || d.outcome}`;
    const reason = document.createElement("span");
    reason.className = "hint";
    reason.textContent = d.reason;
    c.append(title, reason);
    box.appendChild(c);
  });
}

// ---------- 功率曲线 ----------
function renderActivities(activities) {
  state.activities = activities.filter(a => !a.is_auto);
}

function renderLegend() {
  const box = el("legend");
  const items = ["kettle", "microwave", "tv", "refrigerator", "unknown"];
  box.innerHTML = items.map(app => `<span class="legend-item ${app}">${iconMarkup(app)}<span>${APPLIANCE_ZH[app]}</span></span>`).join("");
}

function xOf(t) {
  const d = new Date(t.replace(" ", "T"));
  const h = d.getHours() + d.getMinutes() / 60 + d.getSeconds() / 3600;
  return h / 24;
}

function drawChart() {
  const canvas = el("power-chart");
  const ctx = canvas.getContext("2d");
  const ratio = window.devicePixelRatio || 1;
  const W = canvas.clientWidth;
  const H = canvas.clientHeight || 310;
  canvas.width = Math.round(W * ratio);
  canvas.height = Math.round(H * ratio);
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, W, H);
  if (!state.power.length) return;

  const padL = 46, padR = 13, padT = 14, padB = 61;
  const maxP = Math.max(120, ...state.power.map(p => p.power || 0)) * 1.12;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const yOf = v => padT + plotH - (v / maxP) * plotH;
  const xOfIdx = i => padL + (i / Math.max(1, state.power.length - 1)) * plotW;

  ctx.font = "10px -apple-system, BlinkMacSystemFont, sans-serif";
  ctx.textBaseline = "middle";
  for (let i = 0; i <= 4; i++) {
    const value = maxP * i / 4;
    const y = yOf(value);
    ctx.strokeStyle = i === 0 ? "#cbd7d1" : "#e9efec";
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
    ctx.fillStyle = "#87948e";
    ctx.textAlign = "right";
    ctx.fillText(`${Math.round(value)}`, padL - 8, y);
  }
  for (let h = 0; h <= 24; h += 4) {
    const x = padL + (h / 24) * plotW;
    ctx.strokeStyle = "#edf1ef";
    ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, padT + plotH); ctx.stroke();
    ctx.fillStyle = "#87948e";
    ctx.textAlign = h === 24 ? "right" : "center";
    ctx.fillText(`${String(h).padStart(2, "0")}:00`, x, padT + plotH + 13);
  }
  drawSeries(ctx, 0, state.power.length, "#ddd3e3", 1.25, xOfIdx, yOf);
  const upto = Math.max(1, Math.floor(state.now * state.power.length));
  drawSeries(ctx, 0, upto, "#8b72a1", 2, xOfIdx, yOf);

  const bandTop = padT + plotH + 29;
  const bandH = 11;
  state.activities.forEach(a => {
    const x0 = padL + Math.max(0, Math.min(1, xOf(a.start))) * plotW;
    const x1 = padL + Math.max(0, Math.min(1, xOf(a.end))) * plotW;
    ctx.fillStyle = COLORS[a.appliance] || "#788984";
    ctx.fillRect(x0, bandTop, Math.max(3, x1 - x0), bandH);
  });
  ctx.fillStyle = "#84928c";
  ctx.textAlign = "left";
  ctx.font = "9px -apple-system, BlinkMacSystemFont, sans-serif";
  ctx.fillText("识别活动", padL, bandTop + bandH + 13);

  const nx = padL + state.now * plotW;
  ctx.strokeStyle = "#b95560";
  ctx.lineWidth = 1.25;
  ctx.beginPath(); ctx.moveTo(nx, padT); ctx.lineTo(nx, padT + plotH); ctx.stroke();
  ctx.fillStyle = "#b95560";
  ctx.beginPath(); ctx.arc(nx, padT, 3, 0, Math.PI * 2); ctx.fill();
  el("clock").textContent = `数据时间 ${fmtH(state.now * 24)} · ${state.speed}×`;
}

function drawSeries(ctx, i0, i1, color, width, xOfIdx, yOf) {
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.beginPath();
  let pen = false;
  for (let i = i0; i < i1; i++) {
    const p = state.power[i];
    if (p.power == null) { pen = false; continue; }
    const x = xOfIdx(i), y = yOf(p.power);
    if (!pen) { ctx.moveTo(x, y); pen = true; } else ctx.lineTo(x, y);
  }
  ctx.stroke();
}

// ---------- 播放控制 ----------
function setPlayButton(playing) {
  const button = el("play-btn");
  button.innerHTML = `${iconMarkup(playing ? "unknown" : "unknown", "button-icon")}<span>${playing ? "暂停" : "播放"}</span>`;
  button.querySelector("use").setAttribute("href", playing ? "#icon-pause" : "#icon-play");
  button.setAttribute("aria-label", playing ? "暂停仿真回放" : "播放仿真回放");
}

function tick(ts) {
  if (state.playing) {
    const dt = (ts - state.lastTs) / 1000;
    state.now += (dt * state.speed) / 20;
    if (state.now >= 1) { state.now = 1; state.playing = false; setPlayButton(false); }
    drawChart();
  }
  state.lastTs = ts;
  state.raf = requestAnimationFrame(tick);
}
function play() {
  if (state.power.length === 0) return;
  if (state.now >= 1) state.now = 0;
  state.playing = !state.playing;
  setPlayButton(state.playing);
}
function cycleSpeed() {
  const speeds = [1, 4, 16];
  const i = speeds.indexOf(state.speed);
  state.speed = speeds[(i + 1) % speeds.length];
  el("speed-btn").textContent = state.speed + "×";
  el("speed-btn").setAttribute("aria-label", `播放速度 ${state.speed} 倍，点击切换`);
  drawChart();
}
function rewind() {
  state.now = 0;
  state.playing = false;
  setPlayButton(false);
  drawChart();
}

// ---------- 事件与反馈 ----------
function renderEvents() {
  const events = state.events;
  const box = el("event-list");
  box.innerHTML = "";
  const pendingCount = events.filter(e => e.status === "pending").length;
  el("metric-events").textContent = pendingCount;
  if (!events.length) { box.innerHTML = "<div class='empty-state'>暂无事件</div>"; return; }
  events.forEach(e => {
    const c = document.createElement("div");
    c.className = "event-card";
    const next = nextActions(e.status);
    const btns = next.map(s => `<button type="button" data-id="${e.event_id}" data-status="${s}">${ACTION_ZH[s] || s}</button>`).join("");
    const kind = e.kind === "missing" ? "习惯活动缺失" : "活动延迟";
    c.innerHTML = `<div class="row"><span class="event-main"><span class="appliance-icon ${e.appliance}">${iconMarkup(e.appliance)}</span><span class="event-title"><strong>${APPLIANCE_ZH[e.appliance] || e.appliance}</strong><br>${kind} · ${e.evidence_window}</span></span><span class="status ${e.status}">${STATUS_ZH[e.status] || e.status}</span></div><div class="reason">${e.reason}</div><div class="actions">${btns}</div>`;
    box.appendChild(c);
  });
  box.querySelectorAll("button[data-id]").forEach(b => {
    b.onclick = () => transitionEvent(b.dataset.id, b.dataset.status);
  });
}
function transitionEvent(id, status) {
  const ev = state.events.find(e => e.event_id === id);
  if (!ev) return;
  ev.status = status;
  renderEvents();
}
function nextActions(status) {
  return { pending: ["confirmed", "followup"], followup: ["accepted"], accepted: ["done"] }[status] || [];
}

function fmtH(h) {
  const hh = Math.floor(h), mm = Math.floor((h - hh) * 60);
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
}

// ---------- 手动输入检测 ----------
function parseTimes(s) {
  return s.split(",").map(x => x.trim()).filter(Boolean);
}
const DETECT_ZH = { kettle: "电水壶", microwave: "微波炉", tv: "电视" };
const KIND_ZH = { missing: "缺失", delay: "延迟" };

function renderDetectResult(data) {
  const box = el("detect-result");
  box.innerHTML = "";
  const groups = [
    { title: "规则基线（时间窗）", key: "rule" },
    { title: "学习模型（GMM）", key: "ml" },
  ];
  groups.forEach(g => {
    const div = document.createElement("div");
    div.className = "detect-group";
    const heading = document.createElement("h3");
    heading.textContent = g.title;
    div.appendChild(heading);
    const list = data[g.key];
    if (!list.length) {
      const ok = document.createElement("span");
      ok.className = "detect-ok";
      ok.textContent = "未发现异常";
      div.appendChild(ok);
    } else {
      list.forEach(a => {
        const c = document.createElement("div");
        c.className = `detect-card ${a.kind}`;
        const label = document.createElement("span");
        label.className = `kind ${a.kind}`;
        label.textContent = KIND_ZH[a.kind] || a.kind;
        const appliance = document.createElement("strong");
        appliance.textContent = DETECT_ZH[a.appliance] || a.appliance;
        const reason = document.createElement("div");
        reason.className = "reason";
        reason.textContent = a.reason;
        c.append(label, appliance, reason);
        div.appendChild(c);
      });
    }
    box.appendChild(div);
  });
}

async function detect() {
  const button = el("detect-btn");
  const box = el("detect-result");
  box.innerHTML = "<div class='empty-state'>正在计算…</div>";
  button.disabled = true;
  const payload = {
    kettle: parseTimes(el("in-kettle").value),
    microwave: parseTimes(el("in-microwave").value),
    tv: parseTimes(el("in-tv").value),
  };
  try {
    const data = await callWorker("detect", payload);
    if (data.error) throw new Error(data.error);
    renderDetectResult(data);
  } catch (error) {
    const message = document.createElement("div");
    message.className = "empty-state";
    message.textContent = error.message || "检测失败，请重试。";
    box.replaceChildren(message);
  } finally {
    button.disabled = false;
  }
}

// ---------- 绑定 ----------
window.addEventListener("resize", () => { drawChart(); drawPowerComparison(); });
window.addEventListener("DOMContentLoaded", () => {
  initWorker();
  initScenarioButtons();
  initDatasetFilters();
  initDatasetDrawer();
  el("run-btn").onclick = run;
  el("reset-btn").onclick = () => location.reload();
  el("play-btn").onclick = play;
  el("speed-btn").onclick = cycleSpeed;
  el("rewind-btn").onclick = rewind;
  el("detect-btn").onclick = detect;
  state.lastTs = performance.now();
  drawChart();
  drawPowerComparison();
  requestAnimationFrame(tick);
});
