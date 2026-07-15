const state = {
  catalog: [],
  steps: [],
  settings: {
    host: "", port: 55555, timeout: 5, input_terminator: "CR",
    output_terminator: "CR", separator: "space", header_separator: false,
    footer_separator: false, checksum: true, input_response: true,
    encoding: "cp932", line_number_digits: 2,
  },
  socket: null,
  running: false,
  nextId: 1,
  logs: [],
  draggingId: null,
};

const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value).replace(
  /[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char])
);

async function initialize() {
  restoreSettings();
  applySettingsToForm();
  const response = await fetch("/api/catalog");
  state.catalog = await response.json();
  $("#catalog-count").textContent = state.catalog.length;
  renderPalette();
  renderSequence();
  bindEvents();
}

function bindEvents() {
  $("#command-search").addEventListener("input", renderPalette);
  document.querySelectorAll("[data-control]").forEach((button) => {
    button.addEventListener("click", () =>
      addControl(button.dataset.control, state.steps)
    );
  });
  $("#settings-button").addEventListener("click", () => $("#settings-dialog").showModal());
  $("#settings-form").addEventListener("submit", saveSettings);
  $("#test-button").addEventListener("click", testConnection);
  $("#run-button").addEventListener("click", runSequence);
  $("#stop-button").addEventListener("click", stopSequence);
  $("#clear-button").addEventListener("click", () => {
    if (!state.running && confirm("すべてのカードを削除しますか？")) {
      state.steps = []; renderSequence();
    }
  });
  $("#clear-log-button").addEventListener("click", clearLog);
  $("#export-log-button").addEventListener("click", openLogExport);
  $("#log-export-form").addEventListener("submit", exportLog);
  $("#save-button").addEventListener("click", saveSequence);
  $("#load-input").addEventListener("change", loadSequence);
  bindDragDropEvents();
}

function renderPalette() {
  const query = $("#command-search")?.value.trim().toLowerCase() || "";
  const filtered = state.catalog.filter((item) =>
    `${item.code} ${item.name} ${item.description} ${item.tool_name || ""}`.toLowerCase().includes(query)
  );
  $("#command-palette").innerHTML = catalogGroups(filtered).map((group) => `
    <section class="command-group">
      <h4>${escapeHtml(group.label)}<span>${group.items.length}</span></h4>
      ${group.items.map((item) => `
        <button class="palette-card palette-command" data-code="${item.code}">
          <span class="command-code">${item.code}</span>
          <span class="command-name">${escapeHtml(item.name)}</span>
        </button>`).join("")}
    </section>`).join("");
  document.querySelectorAll(".palette-command").forEach((button) => {
    button.addEventListener("click", () => addCommand(button.dataset.code, state.steps));
  });
}

function newCommand(code) {
  const definition = state.catalog.find((item) => item.code === code);
  const args = {};
  for (const arg of definition.arguments || []) {
    if (arg.default !== undefined) args[arg.key] = arg.default;
    else if (arg.type === "integer") args[arg.key] = arg.min;
    else if (arg.type === "enum") args[arg.key] = arg.options[0].value;
    else args[arg.key] = "";
  }
  if (definition.raw_arguments) args.raw = "";
  return { id: state.nextId++, type: "command", command: code, arguments: args };
}

function addCommand(code, target) {
  if (state.running) return;
  target.push(newCommand(code));
  renderSequence();
}

function addControl(type, target) {
  if (state.running) return;
  if (type === "delay") target.push({ id: state.nextId++, type, milliseconds: 100 });
  if (type === "break") target.push({ id: state.nextId++, type });
  if (type === "loop") target.push({ id: state.nextId++, type, count: 2, steps: [] });
  if (type === "if") target.push({
    id: state.nextId++, type, source: "status", operator: "equals", value: "AK",
    then_steps: [], else_steps: [],
  });
  renderSequence();
}

function renderSequence() {
  $("#empty-state").classList.toggle("hidden", state.steps.length > 0);
  document.querySelectorAll(".generated-step").forEach((element) => element.remove());
  const html = state.steps.map((step) => stepHtml(step)).join("");
  $("#sequence-list").insertAdjacentHTML("beforeend", html);
  bindStepEvents();
}

function stepHtml(step, nested = false) {
  if (step.type === "command") {
    const def = state.catalog.find((item) => item.code === step.command);
    const fields = (def.arguments || []).map((arg) => argumentField(step, arg)).join("");
    const raw = def.raw_arguments ? `
      <label>引数文字列<input data-field="raw" value="${escapeHtml(step.arguments.raw || "")}" placeholder="別資料の構文に従って入力"></label>` : "";
    return `<article class="step-card generated-step" data-id="${step.id}">
      ${stepHeader(step, `<strong>${def.code}</strong>${escapeHtml(def.name)}${def.tool_name ? `<small class="tool-badge">${escapeHtml(def.tool_id)} ${escapeHtml(def.tool_name)}</small>` : ""}`, nested)}
      <div class="step-body">${fields}${raw}
        <p class="step-description">${escapeHtml(def.description || "")}${def.example ? `　例: ${escapeHtml(def.example)}` : ""}</p>
      </div>
    </article>`;
  }
  if (step.type === "delay") {
    return `<article class="step-card control-step generated-step" data-id="${step.id}">
      ${stepHeader(step, "<strong>WAIT</strong>待機", nested)}
      <div class="step-body"><label>待機時間（ミリ秒）
        <input data-field="milliseconds" type="number" min="0" max="3600000" value="${step.milliseconds}">
      </label></div>
    </article>`;
  }
  if (step.type === "break") {
    return `<article class="step-card break-step generated-step" data-id="${step.id}">
      ${stepHeader(step, "<strong>BREAK</strong>最寄りのループを抜ける", nested)}
      <div class="step-body">
        <p class="step-description">このカードを実行すると、内側から最も近いループを終了します。</p>
      </div>
    </article>`;
  }
  if (step.type === "loop") {
    return `<article class="step-card control-step generated-step" data-id="${step.id}">
      ${stepHeader(step, "<strong>LOOP</strong>指定回数くり返す", nested)}
      <div class="step-body"><label>回数
        <input data-field="count" type="number" min="1" max="10000" value="${step.count}">
      </label></div>
      ${childArea(step, "steps", "くり返すカード")}
    </article>`;
  }
  return `<article class="step-card control-step generated-step" data-id="${step.id}">
    ${stepHeader(step, "<strong>IF</strong>応答による条件分岐", nested)}
    <div class="step-body">
      <label>判定対象<select data-field="source">
        <option value="status" ${step.source === "status" ? "selected" : ""}>AK / NK / ER</option>
        <option value="response" ${step.source === "response" ? "selected" : ""}>受信内容全体</option>
      </select></label>
      <label>条件<select data-field="operator">
        <option value="equals" ${step.operator === "equals" ? "selected" : ""}>等しい</option>
        <option value="contains" ${step.operator === "contains" ? "selected" : ""}>含む</option>
        <option value="not_contains" ${step.operator === "not_contains" ? "selected" : ""}>含まない</option>
      </select></label>
      <label>比較値<input data-field="value" value="${escapeHtml(step.value)}"></label>
    </div>
    ${childArea(step, "then_steps", "条件に一致")}
    ${childArea(step, "else_steps", "条件に不一致")}
  </article>`;
}

function stepHeader(step, title, nested) {
  return `<div class="step-header">
    <span class="drag-handle" draggable="true" title="ドラッグして移動" aria-label="ドラッグして移動">⠿</span><div class="step-title">${title}</div>
    <div class="step-actions">
      <button data-action="up" title="上へ">↑</button><button data-action="down" title="下へ">↓</button>
      <button data-action="duplicate" title="複製">⧉</button>
      <button data-action="remove" class="remove" title="削除">×</button>
    </div>
  </div>`;
}

function argumentField(step, arg) {
  const value = step.arguments[arg.key] ?? "";
  if (arg.type === "enum") {
    return `<label>${escapeHtml(arg.label)}<select data-arg="${arg.key}">
      ${arg.options.map((option) => `<option value="${escapeHtml(option.value)}" ${String(value) === String(option.value) ? "selected" : ""}>${escapeHtml(option.label)}</option>`).join("")}
    </select></label>`;
  }
  const attrs = arg.type === "integer"
    ? `type="number" min="${arg.min}" max="${arg.max}" step="1"`
    : `type="text" maxlength="${arg.max_length || 1024}"`;
  return `<label>${escapeHtml(arg.label)}<input data-arg="${arg.key}" ${attrs} value="${escapeHtml(value)}"></label>`;
}

function childArea(step, key, label) {
  const controlOptions = `
    <optgroup label="制御カード">
      <option value="control:delay">WAIT｜待機</option>
      <option value="control:if">IF｜条件分岐</option>
      <option value="control:loop">LOOP｜くり返し</option>
      <option value="control:break">BREAK｜ループを抜ける</option>
    </optgroup>`;
  const commandOptions = catalogGroups(state.catalog).map((group) =>
    `<optgroup label="${escapeHtml(group.label)}">${group.items.map(
      (item) => `<option value="command:${item.code}">${item.code}｜${escapeHtml(item.name)}</option>`
    ).join("")}</optgroup>`
  ).join("");
  return `<div class="nested-area" data-child="${key}">
    <h3>${label}</h3>
    <div class="nested-cards drop-list" data-parent-id="${step.id}" data-child-key="${key}">${(step[key] || []).map((child) => stepHtml(child, true)).join("")}</div>
    <div class="nested-add"><select data-child-select="${key}">${controlOptions}${commandOptions}</select>
      <button data-add-child="${key}" class="icon-button">＋ カード追加</button>
    </div>
  </div>`;
}

function catalogGroups(items) {
  const groups = [];
  const system = items.filter((item) => item.category === "system");
  if (system.length) groups.push({ key: "system", label: "システム", items: system });
  const tools = new Map();
  items.filter((item) => item.category === "tool").forEach((item) => {
    const key = item.tool_id || "tool";
    if (!tools.has(key)) {
      tools.set(key, { key, label: `${key} ${item.tool_name || "ツール"}`, items: [] });
    }
    tools.get(key).items.push(item);
  });
  groups.push(...tools.values());
  return groups;
}

function bindStepEvents() {
  document.querySelectorAll(".step-card").forEach((card) => {
    const id = Number(card.dataset.id);
    const located = locateStep(id);
    if (!located) return;
    card.querySelectorAll(":scope > .step-body [data-arg]").forEach((input) => {
      input.addEventListener("input", () => { located.step.arguments[input.dataset.arg] = input.value; });
    });
    card.querySelectorAll(":scope > .step-body [data-field]").forEach((input) => {
      input.addEventListener("input", () => {
        located.step[input.dataset.field] = input.type === "number" ? Number(input.value) : input.value;
      });
    });
    card.querySelectorAll(":scope > .step-header [data-action]").forEach((button) => {
      button.addEventListener("click", () => stepAction(id, button.dataset.action));
    });
    card.querySelectorAll(":scope > .nested-area > .nested-add [data-add-child]").forEach((button) => {
      button.addEventListener("click", () => {
        const key = button.dataset.addChild;
        const select = button.parentElement.querySelector(`[data-child-select="${key}"]`);
        const [kind, value] = select.value.split(":", 2);
        if (kind === "control") addControl(value, located.step[key]);
        else addCommand(value, located.step[key]);
      });
    });
  });
}

function bindDragDropEvents() {
  const sequence = $("#sequence-list");
  sequence.addEventListener("dragstart", (event) => {
    const handle = event.target.closest(".drag-handle");
    const card = handle?.closest(".step-card");
    if (!card || state.running) {
      event.preventDefault();
      return;
    }
    state.draggingId = Number(card.dataset.id);
    card.classList.add("dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", String(state.draggingId));
    event.dataTransfer.setDragImage(card, 24, 18);
  });
  sequence.addEventListener("dragover", (event) => {
    if (state.draggingId === null || state.running) return;
    const list = dropListAt(event.target);
    if (!list || !canDropInto(state.draggingId, list)) {
      clearDropIndicator();
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    showDropIndicator(list, event.clientY);
  });
  sequence.addEventListener("drop", (event) => {
    if (state.draggingId === null || state.running) return;
    const list = dropListAt(event.target);
    if (!list || !canDropInto(state.draggingId, list)) return;
    event.preventDefault();
    const beforeId = document.querySelector(".drop-indicator")?.dataset.beforeId;
    moveStep(state.draggingId, list, beforeId ? Number(beforeId) : null);
    clearDragState();
    renderSequence();
  });
  sequence.addEventListener("dragend", clearDragState);
}

function dropListAt(target) {
  if (!(target instanceof Element)) return null;
  const nestedArea = target.closest(".nested-area");
  if (nestedArea) {
    return nestedArea.querySelector(":scope > .nested-cards");
  }
  return target.closest(".drop-list");
}

function targetList(dropList) {
  if (dropList.dataset.dropRoot) return state.steps;
  const parent = locateStep(Number(dropList.dataset.parentId));
  return parent?.step[dropList.dataset.childKey] || null;
}

function stepContainsId(step, id) {
  if (step.id === id) return true;
  return ["steps", "then_steps", "else_steps"].some((key) =>
    (step[key] || []).some((child) => stepContainsId(child, id))
  );
}

function canDropInto(id, dropList) {
  const source = locateStep(id);
  if (!source || !targetList(dropList)) return false;
  if (dropList.dataset.dropRoot) return true;
  return !stepContainsId(source.step, Number(dropList.dataset.parentId));
}

function showDropIndicator(dropList, pointerY) {
  clearDropIndicator();
  const cards = [...dropList.querySelectorAll(":scope > .step-card")]
    .filter((card) => Number(card.dataset.id) !== state.draggingId);
  const before = cards.find((card) =>
    pointerY < card.getBoundingClientRect().top
      + card.getBoundingClientRect().height / 2
  );
  const indicator = document.createElement("div");
  indicator.className = "drop-indicator";
  if (before) {
    indicator.dataset.beforeId = before.dataset.id;
    dropList.insertBefore(indicator, before);
  } else {
    dropList.appendChild(indicator);
  }
  dropList.classList.add("drop-list-active");
}

function moveStep(id, dropList, beforeId) {
  const source = locateStep(id);
  const destination = targetList(dropList);
  if (!source || !destination) return;
  const [step] = source.list.splice(source.index, 1);
  const destinationIndex = beforeId === null
    ? destination.length
    : destination.findIndex((item) => item.id === beforeId);
  destination.splice(
    destinationIndex < 0 ? destination.length : destinationIndex,
    0,
    step
  );
}

function clearDropIndicator() {
  document.querySelector(".drop-indicator")?.remove();
  document.querySelectorAll(".drop-list-active").forEach((list) =>
    list.classList.remove("drop-list-active")
  );
}

function clearDragState() {
  clearDropIndicator();
  document.querySelector(".step-card.dragging")?.classList.remove("dragging");
  state.draggingId = null;
}

function locateStep(id, list = state.steps) {
  for (let index = 0; index < list.length; index++) {
    if (list[index].id === id) return { step: list[index], list, index };
    for (const key of ["steps", "then_steps", "else_steps"]) {
      if (list[index][key]) {
        const found = locateStep(id, list[index][key]);
        if (found) return found;
      }
    }
  }
  return null;
}

function stepAction(id, action) {
  if (state.running) return;
  const found = locateStep(id);
  if (!found) return;
  if (action === "remove") found.list.splice(found.index, 1);
  if (action === "up" && found.index > 0) [found.list[found.index - 1], found.list[found.index]] = [found.list[found.index], found.list[found.index - 1]];
  if (action === "down" && found.index < found.list.length - 1) [found.list[found.index + 1], found.list[found.index]] = [found.list[found.index], found.list[found.index + 1]];
  if (action === "duplicate") {
    const clone = JSON.parse(JSON.stringify(found.step));
    assignIds(clone);
    found.list.splice(found.index + 1, 0, clone);
  }
  renderSequence();
}

function assignIds(step) {
  step.id = state.nextId++;
  for (const key of ["steps", "then_steps", "else_steps"]) (step[key] || []).forEach(assignIds);
}

function readSettingsForm() {
  return {
    host: $("#host").value.trim(), port: Number($("#port").value), timeout: Number($("#timeout").value),
    input_terminator: $("#input-terminator").value, output_terminator: $("#output-terminator").value,
    separator: $("#separator").value, header_separator: $("#header-separator").checked,
    footer_separator: $("#footer-separator").checked, checksum: $("#checksum").checked,
    input_response: $("#input-response").checked, encoding: $("#encoding").value,
    line_number_digits: Number($("#line-digits").value),
  };
}

function saveSettings(event) {
  if (event.submitter?.value === "cancel") return;
  state.settings = readSettingsForm();
  localStorage.setItem("vtv-settings", JSON.stringify(state.settings));
}

function restoreSettings() {
  try { state.settings = { ...state.settings, ...JSON.parse(localStorage.getItem("vtv-settings")) }; } catch (_) {}
}

function applySettingsToForm() {
  const map = {
    host: "host", port: "port", timeout: "timeout", input_terminator: "input-terminator",
    output_terminator: "output-terminator", separator: "separator", encoding: "encoding",
    line_number_digits: "line-digits",
  };
  for (const [key, id] of Object.entries(map)) $(`#${id}`).value = state.settings[key];
  $("#header-separator").checked = state.settings.header_separator;
  $("#footer-separator").checked = state.settings.footer_separator;
  $("#checksum").checked = state.settings.checksum;
  $("#input-response").checked = state.settings.input_response;
}

async function testConnection() {
  const result = $("#connection-test-result");
  result.className = "test-result"; result.textContent = "接続しています…";
  try {
    const response = await fetch("/api/test-connection", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(readSettingsForm()),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "接続できません");
    result.className = "test-result success"; result.textContent = "接続に成功しました。";
  } catch (error) {
    result.className = "test-result error"; result.textContent = error.message;
  }
}

function runSequence() {
  state.settings = readSettingsForm();
  if (!state.settings.host) {
    $("#settings-dialog").showModal();
    $("#connection-test-result").className = "test-result error";
    $("#connection-test-result").textContent = "装置 IP を入力してください。";
    return;
  }
  if (!state.steps.length) { alert("実行するカードを追加してください。"); return; }
  clearExecutionStyles(); clearLog(); setRunning(true);
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  state.socket = new WebSocket(`${protocol}://${location.host}/ws`);
  state.socket.addEventListener("open", () => state.socket.send(JSON.stringify({
    type: "execute", payload: { settings: state.settings, steps: cleanSteps(state.steps) },
  })));
  state.socket.addEventListener("message", (event) => handleEvent(JSON.parse(event.data)));
  state.socket.addEventListener("error", () => { addLog("error", "ERR", "WebSocket接続に失敗しました"); setRunning(false); });
  state.socket.addEventListener("close", () => { if (state.running) setRunning(false); });
}

function cleanSteps(steps) {
  return steps.map(({ id, ...step }) => {
    for (const key of ["steps", "then_steps", "else_steps"]) if (step[key]) step[key] = cleanSteps(step[key]);
    return step;
  });
}

function stopSequence() {
  if (state.socket?.readyState === WebSocket.OPEN) state.socket.send(JSON.stringify({ type: "stop" }));
}

function handleEvent(event) {
  if (event.type === "connection") {
    setConnection(event.state);
    if (event.state === "connecting") addLog("info", "SYS", `${event.message} に接続中`);
    if (event.state === "disconnected" && state.socket?.readyState === WebSocket.OPEN) {
      state.socket.close();
    }
  }
  if (event.type === "step_started") {
    const cards = document.querySelectorAll(".step-card");
    cards.forEach((card) => card.classList.remove("active"));
    cards[event.index - 1]?.classList.add("active");
  }
  if (event.type === "step_completed") {
    const card = document.querySelectorAll(".step-card")[event.index - 1];
    card?.classList.remove("active"); card?.classList.add("done");
  }
  if (event.type === "tx") addLog("tx", "TX", event.display);
  if (event.type === "rx") addLog("rx", "RX", event.response);
  if (event.type === "loop_iteration") addLog("info", "LOOP", `${event.iteration} / ${event.count}`);
  if (event.type === "loop_break") addLog("info", "BREAK", "条件によりループを終了しました");
  if (event.type === "condition") addLog("info", "IF", `${event.matched ? "一致" : "不一致"} (${event.actual || "空"})`);
  if (event.type === "sequence_completed") { addLog("info", "DONE", "シーケンスが完了しました"); setRunning(false); }
  if (event.type === "sequence_stopped") { addLog("info", "STOP", event.message); setRunning(false); }
  if (event.type === "sequence_failed") {
    document.querySelector(".step-card.active")?.classList.add("failed");
    addLog("error", "ERR", event.message); setRunning(false);
  }
}

function setConnection(status) {
  const badge = $("#connection-badge");
  badge.className = `badge ${status}`;
  badge.textContent = status === "connected" ? "接続中" : status === "connecting" ? "接続中…" : "未接続";
}

function setRunning(running) {
  state.running = running;
  $("#run-button").disabled = running;
  $("#stop-button").disabled = !running;
}

function addLog(css, kind, data) {
  $("#log .log-empty")?.remove();
  const now = new Date();
  const timestamp = formatTimestamp(now);
  const time = timestamp.slice(11);
  state.logs.push({ timestamp, kind, data: String(data) });
  $("#log").insertAdjacentHTML("beforeend", `<div class="log-row ${css}">
    <span class="log-time">${time}</span><span class="log-kind">${kind}</span><span class="log-data">${escapeHtml(data)}</span>
  </div>`);
  $("#log").scrollTop = $("#log").scrollHeight;
}

function clearLog() {
  state.logs = [];
  $("#log").innerHTML = '<div class="log-empty">実行すると送受信内容が表示されます。</div>';
}
function clearExecutionStyles() { document.querySelectorAll(".step-card").forEach((card) => card.classList.remove("active", "done", "failed")); }

function openLogExport() {
  if (!state.logs.length) {
    alert("出力できる通信ログがありません。");
    return;
  }
  $("#log-export-dialog").showModal();
}

function exportLog(event) {
  if (event.submitter?.value === "cancel") return;
  const format = $("#log-export-format").value;
  const includeTimestamp = $("#log-export-timestamp").checked;
  const content = format === "csv"
    ? buildCsvLog(includeTimestamp)
    : buildTextLog(includeTimestamp);
  const mime = format === "csv" ? "text/csv;charset=utf-8" : "text/plain;charset=utf-8";
  const blob = new Blob(["\uFEFF", content], { type: mime });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `vtv-communication-${fileTimestamp(new Date())}.${format}`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function buildCsvLog(includeTimestamp) {
  const header = includeTimestamp ? ["通信時刻", "種別", "内容"] : ["種別", "内容"];
  const rows = state.logs.map((entry) =>
    includeTimestamp
      ? [entry.timestamp, entry.kind, entry.data]
      : [entry.kind, entry.data]
  );
  return [header, ...rows]
    .map((row) => row.map(csvCell).join(","))
    .join("\r\n");
}

function buildTextLog(includeTimestamp) {
  return state.logs.map((entry) => {
    const prefix = includeTimestamp ? `[${entry.timestamp}] ` : "";
    return `${prefix}${entry.kind.padEnd(5)} ${entry.data}`;
  }).join("\r\n");
}

function csvCell(value) {
  return `"${String(value).replaceAll('"', '""')}"`;
}

function formatTimestamp(date) {
  const pad = (value, length = 2) => String(value).padStart(length, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} `
    + `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.`
    + `${pad(date.getMilliseconds(), 3)}`;
}

function fileTimestamp(date) {
  const compact = formatTimestamp(date).slice(0, 19).replaceAll(/[-: ]/g, "");
  return `${compact.slice(0, 8)}-${compact.slice(8)}`;
}

function saveSequence() {
  const blob = new Blob([JSON.stringify({ version: 1, steps: cleanSteps(state.steps) }, null, 2)], { type: "application/json" });
  const link = document.createElement("a"); link.href = URL.createObjectURL(blob);
  link.download = "vtv-sequence.json"; link.click(); URL.revokeObjectURL(link.href);
}

async function loadSequence(event) {
  const file = event.target.files[0]; if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    if (!Array.isArray(data.steps)) throw new Error("steps がありません");
    state.steps = data.steps; state.steps.forEach(assignIds); renderSequence();
  } catch (error) { alert(`読み込めません: ${error.message}`); }
  event.target.value = "";
}

initialize().catch((error) => {
  document.body.innerHTML = `<p style="padding:30px">起動エラー: ${escapeHtml(error.message)}</p>`;
});
