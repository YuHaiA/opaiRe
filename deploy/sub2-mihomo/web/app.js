const $ = (id) => document.getElementById(id);

const state = {
  status: null,
  filter: "",
  busy: false,
  timer: null,
  settingsLoaded: false,
};

function apiUrl(path) {
  // Keep working both at "/" (local) and under "/mihomo/" (nginx).
  if (/^https?:/i.test(path)) return path;
  const clean = String(path || "").replace(/^\//, "");
  return new URL(clean, window.location.href).pathname + new URL(clean, window.location.href).search;
}

async function api(path, options = {}) {
  const response = await fetch(apiUrl(path), {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({ ok: false, error: `HTTP ${response.status}` }));
  if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function toast(message, error = false) {
  const el = $("toast");
  el.textContent = message;
  el.classList.toggle("error", error);
  el.classList.add("show");
  window.clearTimeout(el._timer);
  el._timer = window.setTimeout(() => el.classList.remove("show"), 3200);
}

function setBusy(value) {
  state.busy = value;
  document.querySelectorAll("button").forEach((button) => {
    if (!button.classList.contains("copy")) button.disabled = value;
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function delayClass(delay) {
  if (!delay) return "";
  if (delay <= 260) return "good";
  if (delay <= 700) return "warn";
  return "";
}

function renderNodes(status) {
  const query = state.filter.trim().toLowerCase();
  const nodes = (status.nodes || [])
    .filter((node) => {
      if (!query) return true;
      return `${node.name} ${node.type}`.toLowerCase().includes(query);
    })
    .sort((a, b) => {
      const aCurrent = a.name === status.current;
      const bCurrent = b.name === status.current;
      if (aCurrent !== bCurrent) return aCurrent ? -1 : 1;

      const rank = (node) => {
        if (node.alive === true && node.delay > 0) return 0;
        if (node.alive == null) return 1;
        return 2;
      };
      const rankDiff = rank(a) - rank(b);
      if (rankDiff) return rankDiff;
      if (rank(a) === 0 && a.delay !== b.delay) return a.delay - b.delay;
      return String(a.name).localeCompare(String(b.name), "zh-CN");
    });
  if (!nodes.length) {
    $("node-list").innerHTML = `<div class="empty">${status.running ? "没有匹配节点。" : "核心启动后将在这里显示节点。"}</div>`;
    return;
  }
  $("node-list").innerHTML = nodes.map((node) => {
    const current = node.name === status.current;
    const delay = node.delay ? `${node.delay} ms` : node.alive === false ? "不可用" : "未测";
    return `
      <div class="node-row node-item" role="row">
        <span class="node-name" title="${escapeHtml(node.name)}">${escapeHtml(node.name)}</span>
        <span class="node-type">${escapeHtml(node.type || "proxy")}</span>
        <span class="delay ${node.alive === false ? "dead" : delayClass(node.delay)}">${delay}</span>
        <button class="select-node ${current ? "current" : ""}" data-node="${escapeHtml(node.name)}">${current ? "当前" : "切换"}</button>
      </div>`;
  }).join("");
}

function renderEgresses(status) {
  const rows = status.egresses || [];
  if (!rows.length) {
    $("egress-list").innerHTML = '<div class="empty">尚未生成固定出口。</div>';
    return;
  }
  $("egress-list").innerHTML = rows.map((row) => {
    const accounts = (row.accounts || []).map((item) => item.name || `#${item.id}`).join("、") || "等待补位";
    return `<div class="egress-row" role="row">
      <strong>${escapeHtml(row.name)}</strong>
      <code>${escapeHtml(row.port)}</code>
      <span class="egress-node" title="${escapeHtml(row.node || "")}">${escapeHtml(row.node || "未选择")}</span>
      <span><b>${row.account_count || 0}/${row.capacity || 2}</b><small>${escapeHtml(accounts)}</small></span>
    </div>`;
  }).join("");
  $("standby-count").textContent = `${status.standby_accounts || 0} 个候补`;
  $("pool-meta").textContent = `最后轮换 ${status.last_rotated_at || "—"} · 最后补位 ${status.accounts_reconciled_at || "—"}`;
}

function render(status) {
  state.status = status;
  const runtime = $("runtime-state");
  runtime.classList.toggle("online", Boolean(status.running));
  runtime.classList.toggle("offline", !status.running);
  $("runtime-label").textContent = status.running ? "核心运行中" : "核心未运行";
  $("status-title").textContent = status.running ? `代理已就绪 · ${status.node_count || 0} 个节点` : "共享代理当前已停止";
  $("status-copy").textContent = status.running
    ? `本机 ${status.proxy_url}${status.docker_proxy_url ? ` · Docker ${status.docker_proxy_url}` : ""}。出口由 PROXY 策略组控制。`
    : "启动后，本机和 Docker 都可以通过同一套 Mihomo 出站。";
  $("proxy-address").textContent = `127.0.0.1:${status.mixed_port}`;
  $("controller-address").textContent = status.controller.replace(/^https?:\/\//, "");
  $("current-node").textContent = status.current || "—";
  $("core-version").textContent = status.version || "—";
  $("subscription-kind").textContent = status.subscription_kind || "未识别";
  $("node-count").textContent = `${status.node_count || 0} 节点`;
  $("source-summary").textContent = `${status.source_masked || "未配置"}${status.updated_at ? ` · ${status.updated_at}` : ""}`;
  $("start-button").disabled = state.busy || status.running;
  $("stop-button").disabled = state.busy || !status.running;
  $("reload-button").disabled = state.busy || !status.running;
  $("test-button").disabled = state.busy || !status.running;
  $("dashboard-button").hidden = !status.dashboard_url;
  const settings = status.settings || {};
  if (!state.settingsLoaded) {
    $("auto-update-minutes").value = settings.auto_update_minutes ?? 60;
    $("egress-rotate-minutes").value = settings.egress_rotate_minutes ?? 30;
    $("account-reconcile-minutes").value = settings.account_reconcile_minutes ?? 1;
    state.settingsLoaded = true;
  }
  renderEgresses(status);
  renderNodes(status);
  $("last-refresh").textContent = `刷新于 ${new Date().toLocaleTimeString()}`;
}

async function refresh(silent = true) {
  try {
    render(await api("/api/status"));
  } catch (error) {
    if (!silent) toast(error.message, true);
  }
}

async function action(path, body, successMessage) {
  setBusy(true);
  try {
    const result = await api(path, { method: "POST", body: JSON.stringify(body || {}) });
    toast(successMessage || "操作完成");
    await refresh(false);
    return result;
  } catch (error) {
    toast(error.message, true);
  } finally {
    setBusy(false);
  }
}

$("start-button").addEventListener("click", () => action("/api/start", {}, "Mihomo 已启动"));
$("stop-button").addEventListener("click", () => action("/api/stop", {}, "Mihomo 已停止"));
$("test-button").addEventListener("click", async () => {
  setBusy(true);
  try {
    const result = await api("/api/test", { method: "POST", body: "{}" });
    toast(`测活完成：可用 ${result.alive}/${result.total}，最低 ${result.best_delay || "—"}ms`);
    await refresh(false);
  } catch (error) {
    toast(error.message, true);
  } finally {
    setBusy(false);
  }
});
$("reload-button").addEventListener("click", () => action("/api/reload", {}, "配置已重载"));
$("update-button").addEventListener("click", () => action("/api/update", {}, "订阅已更新"));
$("settings-save-button").addEventListener("click", async () => {
  const body = {
    auto_update_minutes: Number($("auto-update-minutes").value || 0),
    egress_rotate_minutes: Number($("egress-rotate-minutes").value || 0),
    account_reconcile_minutes: Number($("account-reconcile-minutes").value || 0),
  };
  const result = await action("/api/settings", body, "自动更新与轮换周期已保存");
  if (result) state.settingsLoaded = false;
});
$("rotate-button").addEventListener("click", () => action("/api/egress/rotate", {}, "10 个固定出口已轮换节点"));
$("reconcile-button").addEventListener("click", () => action("/api/egress/reconcile", {}, "Grok 在线槽位已同步"));
$("save-button").addEventListener("click", async () => {
  const source = $("subscription-source").value.trim();
  if (!source) return toast("请粘贴订阅 URL 或分享链接", true);
  const result = await action("/api/subscription", { source }, "订阅已导入");
  if (result) $("subscription-source").value = "";
});

$("dashboard-button").addEventListener("click", () => {
  if (!state.status?.dashboard_url) return toast("控制器尚未就绪", true);
  window.open(state.status.dashboard_url, "_blank", "noopener");
});

$("node-list").addEventListener("click", (event) => {
  const button = event.target.closest("[data-node]");
  if (button) action("/api/select", { name: button.dataset.node }, `已切换到 ${button.dataset.node}`);
});

$("node-search").addEventListener("input", (event) => {
  state.filter = event.target.value;
  if (state.status) renderNodes(state.status);
});

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) return;
  const target = $(button.dataset.copy);
  await navigator.clipboard.writeText(`http://${target.textContent.trim()}`);
  toast("代理地址已复制");
});

$("logs-toggle").addEventListener("click", async () => {
  const button = $("logs-toggle");
  const output = $("logs-output");
  const expanded = button.getAttribute("aria-expanded") === "true";
  button.setAttribute("aria-expanded", String(!expanded));
  output.hidden = expanded;
  if (!expanded) {
    try {
      const data = await api("/api/logs");
      output.textContent = data.logs || "暂无日志";
      output.scrollTop = output.scrollHeight;
    } catch (error) {
      output.textContent = error.message;
    }
  }
});

refresh(false);
state.timer = window.setInterval(() => refresh(true), 3500);
