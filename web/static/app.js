/* fuzhu WebUI Phase1 — Job 轮询 + LAN 管理口令（仅内存 + X-Admin-Token） */
const $ = (sel) => document.querySelector(sel);

const POLL_MS = 2500;

const state = {
  roles: [],
  devices: [],
  roleId: null,
  tasks: [],
  logs: [],
  pollTimer: null,
  allowLan: false,
  /** 仅运行时内存；刷新/401 清除；禁止持久化 */
  adminToken: null,
  authed: false,
};

function stopPolling() {
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

function startPolling() {
  stopPolling();
  if (!state.authed) return;
  state.pollTimer = setInterval(softPoll, POLL_MS);
}

function clearAdminAuth() {
  state.adminToken = null;
  state.authed = false;
  stopPolling();
  state.roles = [];
  state.devices = [];
  state.tasks = [];
  state.logs = [];
  state.roleId = null;
}

function showAuthGate(message) {
  const gate = $("#authGate");
  const main = $("#mainPanels");
  if (gate) gate.hidden = false;
  if (main) main.hidden = true;
  const err = $("#authError");
  if (err) {
    err.textContent = message || "";
    err.hidden = !message;
  }
  const input = $("#adminTokenInput");
  if (input) {
    input.value = "";
    input.focus();
  }
}

function showMainPanels() {
  const gate = $("#authGate");
  const main = $("#mainPanels");
  if (gate) gate.hidden = true;
  if (main) main.hidden = false;
  const err = $("#authError");
  if (err) {
    err.textContent = "";
    err.hidden = true;
  }
}

/**
 * 统一 API：allow_lan 时从内存注入 X-Admin-Token；从不拼入 URL。
 * /api/health 由调用方 skipAuth 处理。
 */
async function api(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  const skipAuth = options.skipAuth === true;
  if (!skipAuth && state.allowLan && state.adminToken) {
    headers["X-Admin-Token"] = state.adminToken;
  }
  const { skipAuth: _s, headers: _h, ...rest } = options;
  const res = await fetch(path, {
    ...rest,
    headers,
  });
  if (res.status === 401) {
    clearAdminAuth();
    showAuthGate("鉴权失败，请重新输入管理口令");
    throw new Error("鉴权失败，请重新输入管理口令");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail || JSON.stringify(j);
    } catch (_) {}
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

function fmtTime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function fmtDuration(ms) {
  if (ms == null || ms === "") return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function statusClass(status) {
  if (!status) return "";
  if (status === "succeeded" || status === "OK") return "ok";
  if (status === "running" || status === "queued") return "run";
  if (status === "blocked") return "warn";
  return "bad";
}

function channelClass(label, route) {
  if (!label || label === "不可用") return "channel-na";
  if (route === "vision" || (label && label.includes("识图"))) return "channel-vision";
  if (route === "protocol" || (label && label.includes("mock"))) return "channel-mock";
  return "";
}

async function refreshHealth() {
  const el = $("#healthBadge");
  try {
    const h = await api("/api/health", { skipAuth: true });
    state.allowLan = !!h.allow_lan;
    el.textContent = state.allowLan ? "LAN · 需口令" : "本机 127.0.0.1";
    el.className = "badge ok";
    return h;
  } catch (e) {
    el.textContent = "离线";
    el.className = "badge bad";
    throw e;
  }
}

async function loadDevices() {
  try {
    state.devices = await api("/api/devices");
  } catch {
    state.devices = [];
  }
}

async function loadRoles() {
  state.roles = await api("/api/roles");
  const sel = $("#roleSelect");
  sel.innerHTML = "";
  for (const r of state.roles) {
    const opt = document.createElement("option");
    opt.value = r.role_id;
    opt.textContent = `${r.role_name || r.role_id} (${r.server_name || r.server_id || "-"})`;
    sel.appendChild(opt);
  }
  if (!state.roleId && state.roles.length) {
    state.roleId = state.roles[0].role_id;
  }
  if (state.roleId) sel.value = state.roleId;
  const role = state.roles.find((r) => r.role_id === state.roleId);
  $("#roleMeta").textContent = role
    ? `ID: ${role.role_id} · 区服: ${role.server_name || role.server_id || "—"} · 会话: mock（脱敏）`
    : "无角色";
  const dev =
    role && role.device_id
      ? state.devices.find((d) => d.device_id === role.device_id)
      : null;
  if (!role) {
    $("#deviceMeta").textContent = "设备：—";
  } else if (!role.device_id) {
    $("#deviceMeta").textContent = "设备：未绑定（Vision 将 blocked）";
    $("#deviceMeta").className = "role-meta warn-text";
  } else {
    $("#deviceMeta").textContent = dev
      ? `设备：${dev.name || dev.device_id} · serial ${dev.adb_serial}`
      : `设备：${role.device_id}`;
    $("#deviceMeta").className = "role-meta";
  }
}

function queueBadge(t) {
  if (t.running) {
    return '<span class="tag tag-running">运行中</span>';
  }
  if (t.queued) {
    const pos = t.queue_position != null ? `排队 #${t.queue_position}` : "排队中";
    return `<span class="tag tag-queued">${pos}（未完成）</span>`;
  }
  return "";
}

function renderTasks() {
  const box = $("#taskList");
  box.innerHTML = "";
  const anyRunning = state.tasks.some((t) => t.running);
  const deviceRun = state.tasks.find((t) => t.device_running_job_id);
  if (anyRunning || state.tasks.some((t) => t.queued)) {
    const q = state.tasks
      .filter((t) => t.running || t.queued)
      .map((t) => {
        const st = t.running ? "running" : `queued#${t.queue_position || "?"}`;
        return `${t.key}:${st}`;
      })
      .join(" · ");
    const banner = document.createElement("div");
    banner.className = "queue-banner";
    banner.innerHTML = `<strong>单设备串行队列</strong>：${escapeHtml(q) || "—"}
      ${
        deviceRun && deviceRun.device_running_job_id
          ? ` · 设备 running_job=<code>${deviceRun.device_running_job_id}</code>`
          : ""
      }
      <div class="muted">同一时刻最多 1 个 Vision 在执行；排队 ≠ 已完成</div>`;
    box.appendChild(banner);
  }
  for (const t of state.tasks) {
    const el = document.createElement("div");
    el.className =
      "task" + (t.running ? " is-running" : "") + (t.queued ? " is-queued" : "");
    const liveStatus = t.running
      ? "running"
      : t.queued
        ? "queued"
        : t.last_job_status || t.last_status || "尚未执行";
    const sc = statusClass(liveStatus);
    const chCls = channelClass(t.channel_label, t.resolved_route);
    const busy = t.running || t.queued;
    const runLabel = t.running ? "执行中…" : t.queued ? "排队中…" : "立即执行";
    el.innerHTML = `
      <div>
        <div class="task-title">${t.name}</div>
        <div class="task-desc">${t.description || ""}</div>
        <div class="task-tags">
          <span class="tag">${t.category}</span>
          <span class="tag ${chCls}">${t.channel_label || "—"}</span>
          <span class="tag">每 ${t.interval_minutes} 分钟</span>
          ${queueBadge(t)}
        </div>
        <label class="impl-field">
          <span>执行通道偏好</span>
          <select class="impl-select" data-key="${t.key}" ${busy ? "disabled" : ""}>
            <option value="auto" ${t.impl === "auto" ? "selected" : ""}>auto（自动）</option>
            <option value="vision" ${t.impl === "vision" ? "selected" : ""}>vision → 本地识图执行</option>
            <option value="protocol" ${t.impl === "protocol" ? "selected" : ""}>protocol → 协议模拟（mock）</option>
          </select>
        </label>
      </div>
      <div class="task-actions">
        <label class="switch" title="启用">
          <input type="checkbox" data-key="${t.key}" class="toggle" ${t.enabled ? "checked" : ""} ${busy ? "disabled" : ""} />
          <span class="slider"></span>
        </label>
        <button class="btn small ${busy ? "busy" : ""}" data-run="${t.key}" type="button" ${busy ? "disabled" : ""}>${runLabel}</button>
      </div>
      <div class="task-status">
        <div>
          状态：
          <span class="${sc}">${liveStatus}</span>
          ${t.last_message ? " · " + escapeHtml(t.last_message) : ""}
        </div>
        <div class="job-meta">
          job_id: <code>${t.active_job_id || t.last_job_id || "—"}</code>
          ${t.queue_position != null ? ` · 队列位置: ${t.queue_position}` : ""}
          · 开始/最近: ${fmtTime(t.last_run_at)}
          · 通道: ${t.last_route || t.resolved_route || "—"}
        </div>
      </div>
    `;
    box.appendChild(el);
  }

  box.querySelectorAll(".toggle").forEach((input) => {
    input.addEventListener("change", async (e) => {
      const key = e.target.dataset.key;
      e.target.disabled = true;
      try {
        await api(`/api/roles/${state.roleId}/tasks/${key}/toggle`, {
          method: "POST",
          body: JSON.stringify({ enabled: e.target.checked }),
        });
        await loadTasks();
      } catch (err) {
        if (!state.authed) return;
        alert("切换失败: " + err.message);
        e.target.checked = !e.target.checked;
      } finally {
        e.target.disabled = false;
      }
    });
  });

  box.querySelectorAll(".impl-select").forEach((sel) => {
    sel.addEventListener("change", async (e) => {
      const key = e.target.dataset.key;
      const impl = e.target.value;
      e.target.disabled = true;
      try {
        await api(`/api/roles/${state.roleId}/tasks/${key}`, {
          method: "PATCH",
          body: JSON.stringify({ impl }),
        });
        await loadTasks();
      } catch (err) {
        if (!state.authed) return;
        alert("修改通道失败: " + err.message);
      } finally {
        e.target.disabled = false;
      }
    });
  });

  box.querySelectorAll("[data-run]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      const key = e.currentTarget.dataset.run;
      const task = state.tasks.find((t) => t.key === key);
      if (task && (task.running || task.queued)) {
        alert(
          (task.running ? "该任务正在执行" : "该任务已在队列中") +
            "，不可重复启动。\njob_id=" +
            (task.active_job_id || "")
        );
        return;
      }
      e.currentTarget.disabled = true;
      e.currentTarget.textContent = "已提交…";
      try {
        const data = await api(`/api/roles/${state.roleId}/tasks/${key}/run`, {
          method: "POST",
          body: JSON.stringify({ wait: false }),
        });
        if (data.reused) {
          alert("已复用同任务 Job（非其它任务）：\n" + (data.job && data.job.job_id));
        } else if (data.job && data.job.status === "blocked") {
          alert("任务被阻塞：\n" + (data.job.message || ""));
        }
        await Promise.all([loadTasks(), loadLogs()]);
      } catch (err) {
        if (!state.authed) return;
        alert("执行失败: " + err.message);
      }
    });
  });
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function loadTasks() {
  if (!state.roleId) return;
  state.tasks = await api(`/api/roles/${state.roleId}/tasks`);
  renderTasks();
}

function retryHint(l) {
  if (l.status === "succeeded" || l.status === "running") return "";
  if (l.status === "queued") return "排队中，请等待";
  if (l.retryable === true) return "可稍后手动重试";
  if (l.retryable === false) return "不建议重试（需先调整配置/绑定）";
  return "";
}

function statusLabel(st) {
  if (st === "queued") return "排队中";
  if (st === "running") return "执行中";
  if (st === "succeeded") return "成功";
  if (st === "failed") return "失败";
  if (st === "blocked") return "被阻止";
  if (st === "cancelled") return "已取消";
  return st || "—";
}

async function loadLogs() {
  if (!state.roleId) return;
  state.logs = await api(`/api/roles/${state.roleId}/logs?limit=40`);
  const box = $("#logList");
  if (!state.logs.length) {
    box.textContent = "暂无 Job 记录（保存在 SQLite）";
    return;
  }
  box.innerHTML = state.logs
    .map((l) => {
      const st = l.status || l.code || "";
      const cls = statusClass(st);
      const ch =
        l.route === "vision"
          ? "本地识图执行"
          : l.route === "protocol"
            ? "协议模拟（mock）"
            : l.route || "";
      const um = l.user_message || l.message || "";
      const q =
        st === "queued" && l.queue_position != null
          ? `排队 #${l.queue_position}`
          : st === "running" && l.queue_position === 0
            ? "队列位 0（执行中）"
            : "";
      const rh = retryHint(l);
      return `<div class="log log-${escapeHtml(st)}">
        <div class="ts">
          <span class="${cls}">${statusLabel(st)}</span>
          · ${escapeHtml(l.task_key || "")}
          · ${ch}
          ${l.failure_code ? ` · <span class="fail-code">${escapeHtml(l.failure_code)}</span>` : ""}
          ${q ? ` · <span class="tag-queued">${q}</span>` : ""}
        </div>
        <div class="job-times">
          创建: ${fmtTime(l.created_at || l.ts)}
          · 开始: ${fmtTime(l.started_at)}
          · 结束: ${fmtTime(l.finished_at)}
          · 耗时: ${fmtDuration(l.duration_ms)}
        </div>
        <div class="msg">${escapeHtml(um)}</div>
        ${rh ? `<div class="retry-hint">${escapeHtml(rh)}</div>` : ""}
        <div class="job-meta">job_id: <code>${escapeHtml(l.job_id || "—")}</code></div>
      </div>`;
    })
    .join("");
}

async function refreshAll() {
  if (!state.authed) return;
  await loadDevices();
  await loadRoles();
  await loadTasks();
  await loadLogs();
}

async function softPoll() {
  try {
    if (!state.authed || !state.roleId) return;
    await loadTasks();
    await loadLogs();
  } catch (_) {
    /* 401 已在 api() 中处理 */
  }
}

async function enterApp() {
  state.authed = true;
  showMainPanels();
  await refreshAll();
  startPolling();
}

async function submitAdminAuth() {
  const input = $("#adminTokenInput");
  const value = (input && input.value) || "";
  if (input) input.value = "";
  if (!value) {
    showAuthGate("鉴权失败，请重新输入管理口令");
    return;
  }
  // 仅写入内存，随后清空输入框显示值
  state.adminToken = value;
  try {
    // 用受保护接口验证口令（不把口令写入 URL）
    await api("/api/roles");
    await enterApp();
  } catch (_) {
    clearAdminAuth();
    showAuthGate("鉴权失败，请重新输入管理口令");
  }
}

function bind() {
  const form = $("#authForm");
  if (form) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      submitAdminAuth();
    });
  }
  $("#roleSelect").addEventListener("change", async (e) => {
    if (!state.authed) return;
    state.roleId = e.target.value;
    await loadRoles();
    await loadTasks();
    await loadLogs();
  });
  $("#btnRefresh").addEventListener("click", () => {
    if (state.authed) refreshAll();
  });
  $("#btnRunEnabled").addEventListener("click", async (e) => {
    if (!state.roleId || !state.authed) return;
    e.currentTarget.disabled = true;
    try {
      await api(`/api/roles/${state.roleId}/run-enabled`, {
        method: "POST",
        body: "{}",
      });
      await Promise.all([loadTasks(), loadLogs()]);
    } catch (err) {
      if (!state.authed) return;
      alert("执行失败: " + err.message);
    } finally {
      e.currentTarget.disabled = false;
    }
  });
}

async function boot() {
  bind();
  try {
    await refreshHealth();
  } catch (_) {
    showAuthGate("");
    $("#healthBadge").textContent = "离线";
    return;
  }
  if (!state.allowLan) {
    // 本机：不显示口令区、不发送 X-Admin-Token
    state.adminToken = null;
    await enterApp();
    return;
  }
  // LAN：先鉴权再加载业务数据
  clearAdminAuth();
  showAuthGate("");
}

boot();
