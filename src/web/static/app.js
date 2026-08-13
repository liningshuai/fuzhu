const $ = (id) => document.getElementById(id);

// 状态轮询会整页重绘任务列表；编辑许愿道具时标记 dirty，避免「清空」被刷回服务器配置
let lastTasksFingerprint = "";
let wishPickDirty = false;
// 奖励目录改版后强制整表刷新一次，避免旧勾选残留在界面
let forceTasksRerender = true;
let taskCache = [];
const WAREHOUSE_TERMINAL_STATUSES = new Set(["success", "partial", "failed", "stopped"]);
const WAREHOUSE_STATUS_LABELS = {
  idle: "未开始",
  running: "扫描中",
  stopping: "停止中",
  success: "已完成",
  partial: "部分完成",
  failed: "扫描失败",
  stopped: "已停止",
};
const WAREHOUSE_CATEGORY_LABELS = {
  items: "道具",
  skill_fragments: "技能碎片",
  arms_fragments: "军械碎片",
  treasure_fragments: "宝物碎片",
  specialties: "特产",
};
let warehouseActionPending = false;
let warehouseSnapshotCache = {
  status: "idle",
  category: null,
  page: null,
  categories_completed: 0,
  items_found: 0,
  low_confidence_count: 0,
  message: "仓库扫描未开始。",
};

function tasksFingerprint(tasks) {
  try {
    return JSON.stringify(
      (tasks || []).map((t) => ({
        id: t.id,
        implemented: t.implemented,
        enabled: t.enabled,
        options: t.options || {},
      }))
    );
  } catch {
    return String(Date.now());
  }
}

function setMsg(text, isError = false) {
  const el = $("action-msg");
  if (!el) return;
  el.textContent = text || "";
  el.style.color = isError ? "#dc5a5a" : "#3b82c4";
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data?.detail;
    const message =
      (detail && typeof detail === "object" ? detail.message : detail) ||
      data?.message ||
      res.statusText ||
      `HTTP ${res.status}`;
    const error = new Error(String(message));
    error.status = res.status;
    error.payload = data;
    error.detail = detail;
    throw error;
  }
  return data;
}

async function setTaskOption(taskId, key, value) {
  return api("/api/tasks/option", {
    method: "POST",
    body: JSON.stringify({ task_id: taskId, key, value }),
  });
}

function setWarehouseMsg(text, isError = false) {
  const el = $("warehouse-action-msg");
  if (!el) return;
  el.textContent = text || "";
  el.style.color = isError ? "#dc5a5a" : "#3b82c4";
}

function formatWarehouseValue(value, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function formatWarehouseCategory(category) {
  return formatWarehouseValue(
    category ? (WAREHOUSE_CATEGORY_LABELS[category] || category) : null
  );
}

function formatWarehousePage(page) {
  return Number.isFinite(Number(page)) ? String(Number(page)) : "—";
}

function warehouseButtonState(status, requestPending = false) {
  const normalized = WAREHOUSE_STATUS_LABELS[status] ? status : "idle";
  const isIdle = status === "idle" && normalized === "idle";
  return {
    scan: requestPending || normalized === "running" || normalized === "stopping",
    stop: requestPending || isIdle || WAREHOUSE_TERMINAL_STATUSES.has(normalized),
  };
}

function warehouseBadgeTone(status) {
  if (status === "success") return "ok";
  if (status === "failed" || status === "stopped") return "bad";
  if (status === "running" || status === "stopping" || status === "partial") return "warn";
  return "";
}

function normalizeWarehouseSnapshot(snapshot = {}) {
  return {
    status: snapshot.status || "idle",
    category: snapshot.category ?? null,
    page: snapshot.page ?? null,
    categories_completed: Number(snapshot.categories_completed || 0),
    items_found: Number(snapshot.items_found || 0),
    low_confidence_count: Number(snapshot.low_confidence_count || 0),
    message: snapshot.message || "仓库扫描未开始。",
  };
}

function renderWarehouseStatus(snapshot) {
  warehouseSnapshotCache = normalizeWarehouseSnapshot(snapshot || warehouseSnapshotCache);
  const status = warehouseSnapshotCache.status;
  const buttons = warehouseButtonState(status, warehouseActionPending);
  const badge = $("warehouse-status-badge");
  if (badge) {
    badge.textContent = WAREHOUSE_STATUS_LABELS[status] || status;
    badge.className = "pill warehouse-status-badge " + warehouseBadgeTone(status);
  }
  $("warehouse-status").textContent = WAREHOUSE_STATUS_LABELS[status] || status;
  $("warehouse-category").textContent = formatWarehouseCategory(warehouseSnapshotCache.category);
  $("warehouse-page").textContent = formatWarehousePage(warehouseSnapshotCache.page);
  $("warehouse-categories-completed").textContent = String(warehouseSnapshotCache.categories_completed);
  $("warehouse-items-found").textContent = String(warehouseSnapshotCache.items_found);
  $("warehouse-low-confidence").textContent = String(warehouseSnapshotCache.low_confidence_count);
  $("warehouse-message").textContent = formatWarehouseValue(warehouseSnapshotCache.message);
  $("btn-warehouse-scan").disabled = buttons.scan;
  $("btn-warehouse-stop").disabled = buttons.stop;
}

function applyWarehouseError(error) {
  const snapshot =
    error?.detail && typeof error.detail === "object" ? error.detail.snapshot : null;
  if (snapshot) {
    renderWarehouseStatus(snapshot);
  } else {
    renderWarehouseStatus(warehouseSnapshotCache);
  }
  setWarehouseMsg(String(error?.message || error), true);
}

function bindEnableToggle(input, t) {
  input.addEventListener("change", async () => {
    try {
      await api("/api/tasks/toggle", {
        method: "POST",
        body: JSON.stringify({ task_id: t.id, enabled: input.checked }),
      });
      setMsg(
        t.id === "guoguan"
          ? input.checked
            ? "过关斩将：将打每天免费 2 次"
            : "过关斩将：不打免费次数"
          : `已${input.checked ? "开启" : "关闭"}：${t.name}`
      );
    } catch (e) {
      input.checked = !input.checked;
      setMsg(String(e.message || e), true);
    }
  });
}

function renderGuoguanBlock(t, root) {
  /** 过关斩将：大开关=打免费2次；小开关=花元宝买第3次（互不混淆） */
  const block = document.createElement("div");
  block.className = "task-block guoguan-block";

  const main = document.createElement("div");
  main.className = "task-item implemented";
  main.innerHTML = `
    <span class="dot impl" title="已实现"></span>
    <div class="task-meta">
      <div class="task-name">过关斩将设置</div>
      <div class="task-desc">大开关：是否打每天赠送的免费 2 次</div>
    </div>
    <label class="switch" title="是否打免费2次">
      <input type="checkbox" data-id="guoguan" data-role="enable" ${t.enabled ? "checked" : ""} />
      <span class="slider"></span>
    </label>
  `;
  bindEnableToggle(main.querySelector('input[data-role="enable"]'), t);
  block.appendChild(main);

  const sub = document.createElement("div");
  sub.className = "task-sub-options";
  const buyOn = !!(t.options && t.options.buy_extra);
  sub.innerHTML = `
    <div class="task-option-row">
      <div class="task-option-text">
        <div class="task-option-label">花元宝买第 3 次</div>
        <div class="task-option-hint">免费用完后，是否再花 200 元宝买 1 次并打（与上方大开关无关）</div>
      </div>
      <label class="switch sm" title="是否购买第3次">
        <input type="checkbox" data-opt="buy_extra" ${buyOn ? "checked" : ""} />
        <span class="slider"></span>
      </label>
    </div>
  `;
  const buyInput = sub.querySelector('input[data-opt="buy_extra"]');
  buyInput.addEventListener("change", async () => {
    try {
      await setTaskOption("guoguan", "buy_extra", buyInput.checked);
      setMsg(
        buyInput.checked
          ? "已开：免费用完后会再买第 3 次（200 元宝）"
          : "已关：免费用完后不买次数"
      );
    } catch (e) {
      buyInput.checked = !buyInput.checked;
      setMsg(String(e.message || e), true);
    }
  });
  block.appendChild(sub);
  root.appendChild(block);
}

function renderWishBlock(t, root) {
  /** 每日许愿：主开关 + 4 个奖励多选 + 七日宝箱 */
  const block = document.createElement("div");
  block.className = "task-block wish-block";

  const main = document.createElement("div");
  main.className = "task-item implemented";
  main.innerHTML = `
    <span class="dot impl" title="已实现"></span>
    <div class="task-meta">
      <div class="task-name">每日许愿</div>
      <div class="task-desc">精彩活动 → 自选 4 奖励 → 许愿 → 七日宝箱</div>
    </div>
    <label class="switch" title="是否执行每日许愿">
      <input type="checkbox" data-id="daily_wish" data-role="enable" ${t.enabled ? "checked" : ""} />
      <span class="slider"></span>
    </label>
  `;
  bindEnableToggle(main.querySelector('input[data-role="enable"]'), t);
  block.appendChild(main);

  const opts = t.options || {};
  const catalog = opts.reward_catalog || [];
  // 编辑中用本地草稿，避免轮询把清空/改选刷回服务器旧值
  const selected = new Set(
    wishPickDirty && window.__wishLocalSel
      ? window.__wishLocalSel
      : opts.selected_rewards || []
  );
  const chestOn = opts.claim_login_chest !== false;

  const sub = document.createElement("div");
  sub.className = "task-sub-options";

  // 七日宝箱开关
  const chestRow = document.createElement("div");
  chestRow.className = "task-option-row";
  chestRow.innerHTML = `
    <div class="task-option-text">
      <div class="task-option-label">领取七日登录宝箱</div>
      <div class="task-option-hint">连续登录 7/7 时点紫宝箱（不够天数一般无事）</div>
    </div>
    <label class="switch sm">
      <input type="checkbox" data-opt="claim_login_chest" ${chestOn ? "checked" : ""} />
      <span class="slider"></span>
    </label>
  `;
  chestRow.querySelector("input").addEventListener("change", async (e) => {
    const input = e.target;
    try {
      await setTaskOption("daily_wish", "claim_login_chest", input.checked);
      setMsg(input.checked ? "已开：尝试领七日宝箱" : "已关：不领七日宝箱");
    } catch (err) {
      input.checked = !input.checked;
      setMsg(String(err.message || err), true);
    }
  });
  sub.appendChild(chestRow);

  // 奖励多选
  const pick = document.createElement("div");
  pick.className = "wish-pick";
  pick.innerHTML = `
    <div class="wish-pick-head">
      <span class="task-option-label">许愿指定道具（恰好 4 个）</span>
      <span class="wish-pick-count" data-role="count">${selected.size}/4</span>
      <button type="button" class="btn ghost sm" data-role="clear">清空</button>
      <button type="button" class="btn sm" data-role="save">确认保存</button>
    </div>
    <div class="wish-pick-grid" data-role="grid"></div>
    <div class="wish-pick-hint">勾选后须点「确认保存」才会写入配置；清空只清界面，需重新选 4 个再保存</div>
  `;
  const grid = pick.querySelector('[data-role="grid"]');
  const countEl = pick.querySelector('[data-role="count"]');
  const localSel = selected;
  window.__wishLocalSel = Array.from(localSel);

  function markDirty() {
    wishPickDirty = true;
    window.__wishLocalSel = Array.from(localSel);
  }

  function refreshCount() {
    countEl.textContent = `${localSel.size}/4`;
    countEl.classList.toggle("ok", localSel.size === 4);
    countEl.classList.toggle("bad", localSel.size !== 4);
  }

  for (const r of catalog) {
    const lab = document.createElement("label");
    lab.className = "wish-chip" + (localSel.has(r.id) ? " on" : "");
    lab.innerHTML = `
      <input type="checkbox" value="${r.id}" ${localSel.has(r.id) ? "checked" : ""} />
      <span>${r.name}</span>
    `;
    const cb = lab.querySelector("input");
    cb.addEventListener("change", () => {
      if (cb.checked) {
        if (localSel.size >= 4) {
          cb.checked = false;
          setMsg("最多选择 4 个奖励", true);
          return;
        }
        localSel.add(r.id);
        lab.classList.add("on");
      } else {
        localSel.delete(r.id);
        lab.classList.remove("on");
      }
      markDirty();
      refreshCount();
    });
    grid.appendChild(lab);
  }
  refreshCount();

  pick.querySelector('[data-role="clear"]').onclick = () => {
    localSel.clear();
    grid.querySelectorAll("input").forEach((el) => {
      el.checked = false;
      el.closest("label").classList.remove("on");
    });
    markDirty();
    refreshCount();
    setMsg("已清空勾选，请重新选 4 个后点「确认保存」");
  };

  pick.querySelector('[data-role="save"]').onclick = async () => {
    if (localSel.size !== 4) {
      setMsg("请恰好选择 4 个奖励后再保存", true);
      return;
    }
    try {
      // 保持 catalog 顺序
      const ordered = catalog.map((r) => r.id).filter((id) => localSel.has(id));
      await setTaskOption("daily_wish", "selected_rewards", ordered);
      wishPickDirty = false;
      window.__wishLocalSel = ordered.slice();
      lastTasksFingerprint = ""; // 允许下次轮询同步服务端
      setMsg("每日许愿奖励已保存：" + ordered.map((id) => {
        const hit = catalog.find((c) => c.id === id);
        return hit ? hit.name : id;
      }).join("、"));
    } catch (err) {
      setMsg(String(err.message || err), true);
    }
  };

  sub.appendChild(pick);
  block.appendChild(sub);
  root.appendChild(block);
}

function renderZizhongBlock(t, root) {
  /** 辎重站：主开关 + 四类资源单选；免费次数在任务内固定共享为 3 次 */
  const block = document.createElement("div");
  block.className = "task-block zizhong-block";

  const main = document.createElement("div");
  main.className = "task-item implemented task-item-featured";
  const opts = t.options || {};
  const selectedResource = (opts.resource_catalog || []).find((r) => r.id === opts.resource);
  const purchased = Number.isFinite(Number(opts.purchased_count)) ? Number(opts.purchased_count) : 0;
  const maxPurchases = Number.isFinite(Number(opts.max_free_purchases)) ? Number(opts.max_free_purchases) : 3;
  main.innerHTML = `
    <span class="task-status status-live"><span class="dot impl"></span>已实现</span>
    <div class="task-meta">
      <div class="task-name">辎重站</div>
      <div class="task-desc">封地 → 辎重站 → 指定资源免费购买 3 次 → 世界回主城</div>
    </div>
    <div class="task-live-state">
      <span class="task-live-label">今日进度</span>
      <strong>${Math.min(purchased, maxPurchases)}/${maxPurchases}</strong>
    </div>
    <label class="switch" title="是否执行辎重站">
      <input type="checkbox" data-id="zizhong_station" data-role="enable" ${t.enabled ? "checked" : ""} />
      <span class="slider"></span>
    </label>
  `;
  bindEnableToggle(main.querySelector('input[data-role="enable"]'), t);
  block.appendChild(main);

  const catalog = opts.resource_catalog || [];
  const sub = document.createElement("div");
  sub.className = "task-sub-options";
  sub.innerHTML = `
    <div class="task-option-row">
      <div class="task-option-text">
        <div class="task-option-label">免费购买资源</div>
        <div class="task-option-hint">共享免费次数 · 当前选择：${selectedResource ? selectedResource.name : "粮草"}</div>
      </div>
      <select class="zizhong-resource" title="选择辎重站资源"></select>
    </div>
  `;
  const select = sub.querySelector("select");
  for (const r of catalog) {
    const option = document.createElement("option");
    option.value = r.id;
    option.textContent = r.name;
    option.selected = r.id === (opts.resource || "food");
    select.appendChild(option);
  }
  select.addEventListener("change", async () => {
    try {
      await setTaskOption("zizhong_station", "resource", select.value);
      setMsg(`辎重站资源已设为：${select.options[select.selectedIndex].text}`);
    } catch (e) {
      setMsg(String(e.message || e), true);
    }
  });
  block.appendChild(sub);
  root.appendChild(block);
}

function renderHeroesArenaBlock(t, root) {
  const block = document.createElement("div");
  block.className = "task-block arena-block";
  const opts = t.options || {};
  const completed = !!opts.completed_today;
  const main = document.createElement("div");
  main.className = "task-item implemented task-item-featured";
  main.innerHTML = `
    <span class="task-status status-live"><span class="dot impl"></span>已实现</span>
    <div class="task-meta">
      <div class="task-name">比武大会</div>
      <div class="task-desc">征战 → 武馆 → 比武大会 → 冠军点赞 → 报名</div>
    </div>
    <div class="task-live-state arena-state">
      <span class="task-live-label">今日状态</span>
      <strong>${completed ? "已完成" : "待执行"}</strong>
    </div>
    <label class="switch" title="是否执行比武大会">
      <input type="checkbox" data-id="heroes_arena" data-role="enable" ${t.enabled ? "checked" : ""} />
      <span class="slider"></span>
    </label>
  `;
  bindEnableToggle(main.querySelector('input[data-role="enable"]'), t);
  block.appendChild(main);

  const sub = document.createElement("div");
  sub.className = "task-sub-options";
  sub.innerHTML = `
    <div class="task-option-row arena-flow-row">
      <div class="task-option-text">
        <div class="task-option-label">执行内容</div>
        <div class="task-option-hint">仅在点赞、报名按钮高亮时操作；报名成功后当天不重复执行</div>
      </div>
      <div class="arena-flow-badges">
        <span>冠军点赞</span><span>报名</span>
      </div>
    </div>
  `;
  block.appendChild(sub);
  root.appendChild(block);
}

function renderLegendBlock(t, root) {
  const block = document.createElement("div");
  block.className = "task-block legend-block";
  const opts = t.options || {};
  const selected = (opts.hero_catalog || []).find((h) => h.id === opts.hero);
  const completed = Number(opts.completed_count || 0);
  const total = Number(opts.total_chances || 2);
  const purchased = Number(opts.purchased_count || 0);

  const main = document.createElement("div");
  main.className = "task-item implemented task-item-featured";
  main.innerHTML = `
    <span class="task-status status-live"><span class="dot impl"></span>已实现</span>
    <div class="task-meta">
      <div class="task-name">见证传奇</div>
      <div class="task-desc">征战 → 探险 → 见证传奇 → 选择英雄 → 挑战</div>
    </div>
    <div class="task-live-state legend-state">
      <span class="task-live-label">今日进度</span>
      <strong>${Math.min(completed, total)}/${total}</strong>
    </div>
    <label class="switch" title="是否执行见证传奇">
      <input type="checkbox" data-id="legend" data-role="enable" ${t.enabled ? "checked" : ""} />
      <span class="slider"></span>
    </label>
  `;
  bindEnableToggle(main.querySelector('input[data-role="enable"]'), t);
  block.appendChild(main);

  const sub = document.createElement("div");
  sub.className = "task-sub-options";
  sub.innerHTML = `
    <div class="task-option-row legend-option-row">
      <div class="task-option-text">
        <div class="task-option-label">见证英雄</div>
        <div class="task-option-hint">目标英雄不在当前屏幕时会自动滚动列表查找</div>
      </div>
      <select class="legend-hero-select" title="选择见证传奇英雄">
        <option value="">不执行</option>
      </select>
    </div>
    <div class="task-option-row legend-option-row">
      <div class="task-option-text">
        <div class="task-option-label">增加次数</div>
        <div class="task-option-hint">免费 2 次；额外购买每次消耗 50 元宝，最多购买 5 次（合计最多 7 次）</div>
      </div>
      <select class="legend-extra-select" title="选择额外购买次数"></select>
    </div>
    <div class="legend-progress-note">已完成 ${Math.min(completed, total)}/${total} 次 · 已购买 ${purchased} 次</div>
  `;
  const heroSelect = sub.querySelector(".legend-hero-select");
  for (const hero of opts.hero_catalog || []) {
    const option = document.createElement("option");
    option.value = hero.id;
    option.textContent = hero.name;
    option.selected = hero.id === opts.hero;
    heroSelect.appendChild(option);
  }
  heroSelect.addEventListener("change", async () => {
    try {
      await setTaskOption("legend", "hero", heroSelect.value);
      setMsg(heroSelect.value ? `见证传奇英雄已设为：${heroSelect.options[heroSelect.selectedIndex].text}` : "见证传奇已设为不执行");
    } catch (e) {
      heroSelect.value = opts.hero || "";
      setMsg(String(e.message || e), true);
    }
  });

  const extraSelect = sub.querySelector(".legend-extra-select");
  for (let i = 0; i <= 5; i += 1) {
    const option = document.createElement("option");
    option.value = String(i);
    option.textContent = `${i} 次（共 ${2 + i} 次）`;
    option.selected = i === Number(opts.extra_purchases || 0);
    extraSelect.appendChild(option);
  }
  extraSelect.addEventListener("change", async () => {
    try {
      await setTaskOption("legend", "extra_purchases", Number(extraSelect.value));
      setMsg(`见证传奇额外购买次数已设为：${extraSelect.value} 次`);
    } catch (e) {
      extraSelect.value = String(opts.extra_purchases || 0);
      setMsg(String(e.message || e), true);
    }
  });
  block.appendChild(sub);
  root.appendChild(block);
}

function renderMingshiBlock(t, root) {
  const block = document.createElement("div");
  block.className = "task-block mingshi-block";
  const opts = t.options || {};
  const completed = !!opts.completed_today;

  const main = document.createElement("div");
  main.className = "task-item implemented task-item-featured";
  main.innerHTML = `
    <span class="task-status status-live"><span class="dot impl"></span>已实现</span>
    <div class="task-meta">
      <div class="task-name">名士拜访</div>
      <div class="task-desc">主城 → 商店 → 名士拜访 → 购买一次铜钱将领碎片 → 返回主城</div>
    </div>
    <div class="task-live-state mingshi-state">
      <span class="task-live-label">今日状态</span>
      <strong>${completed ? "已完成" : "待执行"}</strong>
    </div>
    <label class="switch" title="是否执行名士拜访">
      <input type="checkbox" data-id="mingshi" data-role="enable" ${t.enabled ? "checked" : ""} />
      <span class="slider"></span>
    </label>
  `;
  bindEnableToggle(main.querySelector('input[data-role="enable"]'), t);
  block.appendChild(main);

  const sub = document.createElement("div");
  sub.className = "task-sub-options";
  sub.innerHTML = `
    <div class="task-option-row mingshi-flow-row">
      <div class="task-option-text">
        <div class="task-option-label">购买规则</div>
        <div class="task-option-hint">每日商品随机刷新，只识别并购买任意一个使用铜钱的将领碎片，不购买元宝商品</div>
      </div>
      <div class="arena-flow-badges"><span>${completed ? "今日已购买" : "等待购买"}</span></div>
    </div>
  `;
  block.appendChild(sub);
  root.appendChild(block);
}

function renderTaskSummary(tasks) {
  const summary = $("task-summary");
  if (!summary) return;
  const implemented = tasks.filter((t) => t.implemented).length;
  const enabled = tasks.filter((t) => t.enabled).length;
  summary.innerHTML = `<span>${implemented} 已实现</span><span>${enabled} 已开启</span>`;
}

function taskMatches(t, query, filter) {
  const haystack = `${t.name || ""} ${t.description || ""}`.toLowerCase();
  if (query && !haystack.includes(query.toLowerCase())) return false;
  if (filter === "implemented" && !t.implemented) return false;
  if (filter === "enabled" && !t.enabled) return false;
  if (filter === "placeholder" && t.implemented) return false;
  return true;
}

function renderTasks(tasks) {
  const root = $("task-list");
  root.innerHTML = "";
  const query = $("task-search")?.value.trim() || "";
  const filter = $("task-filter")?.value || "all";
  const visibleTasks = tasks.filter((t) => taskMatches(t, query, filter));
  renderTaskSummary(tasks);

  if (!visibleTasks.length) {
    root.innerHTML = '<div class="empty-state">没有匹配的功能</div>';
    return;
  }

  for (const t of visibleTasks) {
    if (t.id === "guoguan") {
      renderGuoguanBlock(t, root);
      continue;
    }
    if (t.id === "daily_wish") {
      renderWishBlock(t, root);
      continue;
    }
    if (t.id === "zizhong_station" && t.implemented) {
      renderZizhongBlock(t, root);
      continue;
    }
    if (t.id === "heroes_arena" && t.implemented) {
      renderHeroesArenaBlock(t, root);
      continue;
    }
    if (t.id === "legend" && t.implemented) {
      renderLegendBlock(t, root);
      continue;
    }
    if (t.id === "mingshi" && t.implemented) {
      renderMingshiBlock(t, root);
      continue;
    }

    const item = document.createElement("div");
    item.className = "task-item" + (t.implemented ? " implemented" : " placeholder");
    const displayName = t.implemented ? t.name : `${t.name}（开发中）`;
    const dotClass = t.implemented ? "impl" : "off";
    item.innerHTML = `
      <span class="dot ${dotClass}" title="${t.implemented ? "已实现" : "占位"}"></span>
      <div class="task-meta">
        <div class="task-name">${displayName}</div>
        <div class="task-desc">${t.description || ""}</div>
      </div>
      <label class="switch">
        <input type="checkbox" data-id="${t.id}" data-role="enable" ${t.enabled ? "checked" : ""} ${t.implemented ? "" : "disabled"} />
        <span class="slider"></span>
      </label>
    `;
    const enableInput = item.querySelector('input[data-role="enable"]');
    if (t.implemented) {
      bindEnableToggle(enableInput, t);
    }
    root.appendChild(item);
  }
}

function renderLogs(results) {
  const root = $("logs");
  if (!results || !results.length) {
    root.innerHTML = '<div class="log-line skipped">暂无任务日志</div>';
    return;
  }
  root.innerHTML = results
    .slice()
    .reverse()
    .map(
      (r) =>
        `<div class="log-line ${r.status}"><span class="t">${r.time}</span>[${r.name}] ${r.status} - ${r.message || ""}</div>`
    )
    .join("");
}

function renderStatus(data) {
  $("title").textContent = data.web_title || "兵临天下辅助";
  const run = $("pill-run");
  run.textContent = data.running ? "挂机中" : "未挂机";
  run.className = "pill " + (data.running ? "ok" : "");

  const dev = $("pill-device");
  dev.textContent = data.device_online ? `设备在线 ${data.serial}` : `设备离线 ${data.serial || ""}`;
  dev.className = "pill " + (data.device_online ? "ok" : "bad");

  const game = $("pill-game");
  game.textContent = data.game_foreground ? "游戏前台" : "游戏未在前台";
  game.className = "pill " + (data.game_foreground ? "ok" : "warn");

  $("run-info").innerHTML = [
    `循环次数：${data.loop_count}`,
    `启动时间：${data.started_at || "—"}`,
    `最近循环：${data.last_loop_at || "—"}`,
    `状态：${data.last_message || "—"}`,
  ].join("<br/>");

  $("btn-stop").classList.toggle("active", !!data.running);

  // 任务列表：配置未变时不重绘；许愿道具编辑中也不重绘（防止清空被刷回）
  const fp = tasksFingerprint(data.tasks || []);
  taskCache = data.tasks || [];
  if (forceTasksRerender) {
    forceTasksRerender = false;
    wishPickDirty = false;
    lastTasksFingerprint = fp;
    renderTasks(data.tasks || []);
  } else if (!wishPickDirty && fp !== lastTasksFingerprint) {
    lastTasksFingerprint = fp;
    renderTasks(data.tasks || []);
  } else if (!lastTasksFingerprint) {
    lastTasksFingerprint = fp;
    renderTasks(data.tasks || []);
  }

  renderLogs(data.recent_results || []);
}

async function refreshDevices() {
  const data = await api("/api/devices");
  const sel = $("serial-select");
  sel.innerHTML = "";
  const list = data.devices.length ? data.devices : [data.current].filter(Boolean);
  for (const d of list) {
    const opt = document.createElement("option");
    opt.value = d;
    opt.textContent = d;
    if (d === data.current) opt.selected = true;
    sel.appendChild(opt);
  }
}

async function refreshStatus() {
  const [statusResult, warehouseResult] = await Promise.allSettled([
    api("/api/status"),
    api("/api/warehouse/status"),
  ]);

  if (statusResult.status !== "fulfilled") {
    if (warehouseResult.status === "fulfilled") {
      renderWarehouseStatus(warehouseResult.value);
    }
    throw statusResult.reason;
  }

  renderStatus(statusResult.value);
  if (warehouseResult.status === "fulfilled") {
    renderWarehouseStatus(warehouseResult.value);
  } else {
    renderWarehouseStatus(warehouseSnapshotCache);
    setWarehouseMsg(
      "读取仓库状态失败：" + String(warehouseResult.reason?.message || warehouseResult.reason),
      true
    );
  }
  return statusResult.value;
}

function bind() {
  $("task-search").addEventListener("input", () => renderTasks(taskCache));
  $("task-filter").addEventListener("change", () => renderTasks(taskCache));

  $("btn-refresh-devices").onclick = async () => {
    try {
      await refreshDevices();
      setMsg("设备列表已刷新");
    } catch (e) {
      setMsg(String(e.message || e), true);
    }
  };

  $("btn-set-serial").onclick = async () => {
    try {
      const serial = $("serial-select").value;
      await api("/api/device/serial", {
        method: "POST",
        body: JSON.stringify({ serial }),
      });
      await refreshStatus();
      setMsg(`已切换设备：${serial}`);
    } catch (e) {
      setMsg(String(e.message || e), true);
    }
  };

  $("btn-start").onclick = async () => {
    try {
      const r = await api("/api/bot/start", {
        method: "POST",
        body: JSON.stringify({ ensure_game: true }),
      });
      setMsg(r.message, !String(r.message).includes("已启动"));
      await refreshStatus();
    } catch (e) {
      setMsg(String(e.message || e), true);
    }
  };

  $("btn-stop").onclick = async () => {
    try {
      const r = await api("/api/bot/stop", { method: "POST" });
      setMsg(r.message);
      await refreshStatus();
    } catch (e) {
      setMsg(String(e.message || e), true);
    }
  };

  $("btn-save").onclick = async () => {
    try {
      await api("/api/config/reload", { method: "POST" });
      setMsg("配置已保存/重载");
      await refreshStatus();
    } catch (e) {
      setMsg(String(e.message || e), true);
    }
  };

  $("btn-launch").onclick = async () => {
    try {
      const r = await api("/api/game/start", { method: "POST" });
      setMsg(r.message);
      setTimeout(refreshStatus, 3000);
    } catch (e) {
      setMsg(String(e.message || e), true);
    }
  };

  $("btn-shot").onclick = async () => {
    try {
      await api("/api/screenshot", { method: "POST" });
      $("shot").src = "/api/screenshot/file?t=" + Date.now();
      setMsg("截图成功");
    } catch (e) {
      setMsg(String(e.message || e), true);
    }
  };
  $("btn-warehouse-scan").onclick = async () => {
    warehouseActionPending = true;
    renderWarehouseStatus(warehouseSnapshotCache);
    setWarehouseMsg("");
    try {
      const snapshot = await api("/api/warehouse/scan", { method: "POST" });
      renderWarehouseStatus(snapshot);
      setWarehouseMsg(String(snapshot.message || "仓库扫描已启动。"));
      await refreshStatus();
    } catch (e) {
      applyWarehouseError(e);
    } finally {
      warehouseActionPending = false;
      renderWarehouseStatus(warehouseSnapshotCache);
    }
  };

  $("btn-warehouse-stop").onclick = async () => {
    warehouseActionPending = true;
    renderWarehouseStatus(warehouseSnapshotCache);
    setWarehouseMsg("");
    try {
      const snapshot = await api("/api/warehouse/stop", { method: "POST" });
      renderWarehouseStatus(snapshot);
      setWarehouseMsg(String(snapshot.message || "已提交停止请求。"));
      await refreshStatus();
    } catch (e) {
      applyWarehouseError(e);
    } finally {
      warehouseActionPending = false;
      renderWarehouseStatus(warehouseSnapshotCache);
    }
  };
}

async function main() {
  bind();
  renderWarehouseStatus(warehouseSnapshotCache);
  try {
    await refreshDevices();
    await refreshStatus();
  } catch (e) {
    setMsg("初始化失败：" + (e.message || e), true);
  }
  setInterval(() => {
    refreshStatus().catch(() => {});
  }, 2500);
}

main();
