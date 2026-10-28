const WATCH_INTERVAL_MIN_MS = 1;
const WATCH_INTERVAL_MAX_MS = 10_000;
const WATCH_INTERVAL_DEFAULT_MS = 500;

const DEFAULT_FN_STATUS_SIGNALS = [
  { id: "auto", label: "自動運転中", source: "status", bit: 0, eso_port: null, role: "auto" },
  { id: "busy", label: "BUSY", source: "status", bit: 1, eso_port: null, role: "busy" },
  { id: "result_valid", label: "結果信号有効", source: "status", bit: 2, eso_port: null, role: "result_valid" },
  { id: "error", label: "エラー", source: "status", bit: 3, eso_port: null, role: "error" },
];

const state = {
  catalog: [],
  steps: [],
  settings: {
    transport: "tcp",
    host: "", port: 55555, timeout: 5, input_terminator: "CR",
    output_terminator: "CR", separator: "space", header_separator: false,
    footer_separator: false, checksum: true, input_response: true,
    encoding: "cp932", line_number_digits: 2,
    command_address: 4096, command_size: 64,
    response_address: 8192, response_size: 64,
    plo_address: 1024, plo_port_count: 32, busy_port: 1, byte_order: "high_low",
    result_data_enabled: false, result_data_address: 512, result_data_size: 2048,
    result_data_watch_words: 64, result_data_decimals: 3,
    notify_area_enabled: false, notify_address: 2560,
    fn_esi_ports: 32, fn_eso_ports: 32,
    fn_input_size: 612, fn_output_size: 136, fn_rpi_us: 10000,
    fn_connection_path: "20 04 24 01 2C 14 2C 0A",
    fn_o_to_t_header_bytes: 4, fn_eds_name: "",
    fn_status_signals: DEFAULT_FN_STATUS_SIGNALS.map((item) => ({ ...item })),
  },
  statusSignalDraft: DEFAULT_FN_STATUS_SIGNALS.map((item) => ({ ...item })),
  statusSignalSeq: 1,
  socket: null,
  running: false,
  nextId: 1,
  logs: [],
  draggingId: null,
  connectionVerified: false,
  verifiedSettingsKey: "",
  viewMode: "normal", // "normal" | "compact"
  layoutMode: "workspace", // "workspace" | "monitor"
  watchItems: [],
  watchValues: {},
  watchRunning: false,
  watchTimer: null,
  watchIntervalMs: WATCH_INTERVAL_DEFAULT_MS,
  watchLastCycleAt: 0,
  watchActualMs: null,
  watchFetchMs: null,
  softPlcPollTimer: null,
  softPlcClientCount: 0,
};

const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value).replace(
  /[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char])
);

async function initialize() {
  restoreSettings();
  restoreConnectionState();
  restoreViewMode();
  restoreResultDataDisplayMode();
  restoreWatchInterval();
  restoreLayoutMode();
  applySettingsToForm();
  applyWatchIntervalToForm();
  refreshMappedWatchItems();
  const response = await fetch("/api/catalog");
  state.catalog = await response.json();
  $("#catalog-count").textContent = state.catalog.length;
  renderPalette();
  renderSequence();
  renderWatchList();
  bindEvents();
  startSoftPlcStatusPoll();
}

function bindEvents() {
  $("#command-search").addEventListener("input", renderPalette);
  document.querySelectorAll("[data-control]").forEach((button) => {
    button.addEventListener("click", () =>
      addControl(button.dataset.control, state.steps)
    );
  });
  $("#settings-button").addEventListener("click", () => openSettingsDialog());
  $("#settings-close-button")?.addEventListener("click", () => closeSettingsDialog());
  $("#settings-dialog")?.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeSettingsDialog();
  });
  $("#settings-form").addEventListener("submit", saveSettings);
  $("#transport").addEventListener("change", syncTransportUi);
  $("#plo-address").addEventListener("input", updateBusyAddressHint);
  $("#plo-port-count").addEventListener("input", updateBusyAddressHint);
  $("#busy-port").addEventListener("input", updateBusyAddressHint);
  $("#result-data-enabled").addEventListener("change", () => {
    syncResultDataUi();
    refreshMappedWatchItems();
    renderWatchList();
  });
  $("#notify-area-enabled").addEventListener("change", () => {
    syncResultDataUi();
    refreshMappedWatchItems();
    renderWatchList();
  });
  ["result-data-address", "result-data-size", "result-data-watch-words", "notify-address"].forEach((id) => {
    $(`#${id}`)?.addEventListener("change", () => {
      refreshMappedWatchItems();
      renderWatchList();
    });
  });
  $("#result-data-decimals")?.addEventListener("change", () => {
    refreshMappedWatchItems();
    renderWatchList();
    updateWatchValueDisplays();
  });
  $("#result-data-display-mode")?.addEventListener("change", () => {
    localStorage.setItem("vtv-result-data-display-mode", $("#result-data-display-mode").value);
    updateWatchValueDisplays();
  });
  $("#watch-interval")?.addEventListener("change", onWatchIntervalChanged);
  $("#test-button").addEventListener("click", testConnection);
  $("#start-softplc-button")?.addEventListener("click", startSoftPlc);
  $("#fn-connect-button")?.addEventListener("click", connectFieldNetwork);
  $("#eds-import-input")?.addEventListener("change", onEdsImport);
  ["fn-esi-ports", "fn-eso-ports", "fn-command-size", "fn-response-size", "fn-result-size",
    "fn-input-size", "fn-output-size", "fn-result-watch-words"].forEach((id) => {
    $(`#${id}`)?.addEventListener("change", () => {
      updateFnLayoutHint();
      if (id === "fn-eso-ports") renderStatusSignalTable();
      refreshMappedWatchItems();
      renderWatchList();
    });
  });
  $("#fn-status-add")?.addEventListener("click", () => {
    syncStatusSignalDraftFromDom();
    state.statusSignalDraft.push({
      id: `custom-${state.statusSignalSeq++}`,
      label: "カスタム信号",
      source: "status",
      bit: 4,
      eso_port: null,
      role: "none",
    });
    renderStatusSignalTable();
  });
  $("#fn-status-reset")?.addEventListener("click", () => {
    state.statusSignalDraft = DEFAULT_FN_STATUS_SIGNALS.map((item) => ({ ...item }));
    renderStatusSignalTable();
  });
  $("#fn-status-signal-body")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-status-delete]");
    if (!button) return;
    const index = Number(button.dataset.statusDelete);
    syncStatusSignalDraftFromDom();
    if (!Number.isFinite(index)) return;
    state.statusSignalDraft.splice(index, 1);
    renderStatusSignalTable();
  });
  $("#fn-status-signal-body")?.addEventListener("change", (event) => {
    const row = event.target.closest("tr[data-status-index]");
    if (!row) return;
    syncStatusSignalDraftFromDom();
    renderStatusSignalTable();
  });
  for (const id of ["header-timeout", "timeout"]) {
    $(`#${id}`)?.addEventListener("change", onTimeoutChanged);
  }
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
  $("#view-mode-button").addEventListener("click", toggleViewMode);
  $("#layout-mode-button").addEventListener("click", toggleLayoutMode);
  $("#layout-mode-monitor-button").addEventListener("click", toggleLayoutMode);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.layoutMode === "monitor") {
      setLayoutMode("workspace");
    }
  });
  document.querySelectorAll("[data-monitor-tab]").forEach((button) => {
    button.addEventListener("click", () => selectMonitorTab(button.dataset.monitorTab));
  });
  $("#refresh-map-button").addEventListener("click", () => {
    refreshMappedWatchItems();
    renderWatchList();
    setWatchStatus("一覧を再生成しました");
  });
  $("#start-watch-button").addEventListener("click", startWatch);
  $("#stop-watch-button").addEventListener("click", () => stopWatch(false));
  bindDragDropEvents();
}

function restoreViewMode() {
  try {
    const saved = localStorage.getItem("vtv-view-mode");
    if (saved === "compact" || saved === "normal") state.viewMode = saved;
  } catch (_) {}
  applyViewMode();
}

function restoreWatchInterval() {
  try {
    const saved = Number(localStorage.getItem("vtv-watch-interval-ms"));
    if (Number.isFinite(saved)) {
      state.watchIntervalMs = clampWatchIntervalMs(saved);
    }
  } catch (_) {}
}

function applyWatchIntervalToForm() {
  const input = $("#watch-interval");
  if (input) input.value = String(state.watchIntervalMs);
  updateWatchNote();
}

function clampWatchIntervalMs(value) {
  if (!Number.isFinite(value)) return WATCH_INTERVAL_DEFAULT_MS;
  return Math.min(WATCH_INTERVAL_MAX_MS, Math.max(WATCH_INTERVAL_MIN_MS, Math.round(value)));
}

function readWatchIntervalMs() {
  const value = Number($("#watch-interval")?.value);
  return clampWatchIntervalMs(Number.isFinite(value) ? value : state.watchIntervalMs);
}

function onWatchIntervalChanged() {
  state.watchIntervalMs = readWatchIntervalMs();
  applyWatchIntervalToForm();
  localStorage.setItem("vtv-watch-interval-ms", String(state.watchIntervalMs));
}

function scheduleNextWatchPoll(elapsedMs = 0) {
  if (!state.watchRunning) return;
  const delay = Math.max(0, readWatchIntervalMs() - elapsedMs);
  state.watchTimer = setTimeout(pollWatchValues, delay);
}

function resetWatchActualPeriod() {
  state.watchLastCycleAt = 0;
  state.watchActualMs = null;
  state.watchFetchMs = null;
  updateWatchActualPeriodDisplay();
}

function updateWatchActualPeriodDisplay() {
  const el = $("#watch-actual-period");
  if (!el) return;
  if (!state.watchRunning || state.watchActualMs == null) {
    el.textContent = "実測 —";
    return;
  }
  const cycle = Math.max(1, Math.round(state.watchActualMs));
  const fetchMs = state.watchFetchMs == null ? null : Math.max(0, Math.round(state.watchFetchMs));
  el.textContent = fetchMs == null
    ? `実測 ${cycle} ms`
    : `実測 ${cycle} ms（取得 ${fetchMs} ms）`;
}

function updateWatchNote() {
  const note = $("#watch-note");
  if (!note) return;
  const transport = $("#transport")?.value || state.settings.transport;
  if (transport === "plclink") {
    note.textContent =
      `接続設定のコマンド／レスポンス／PLO から自動生成。`
      + `更新周期 ${readWatchIntervalMs()} ms（HTTP 取得時間を除く）。`;
    return;
  }
  if (transport === "field_network") {
    note.textContent =
      `「結果データ」は VTV と同じく「出力値」(生DWORD) と「データ」(解釈値) を表示します。`
      + `処理時間などの倍精度は表記を「浮動小数点」にしてください。更新周期 ${readWatchIntervalMs()} ms。`;
    return;
  }
  note.textContent = "PLCLINK / Field Network 接続時に監視が利用できます。";
}

function restoreResultDataDisplayMode() {
  const select = $("#result-data-display-mode");
  if (!select) return;
  try {
    const saved = localStorage.getItem("vtv-result-data-display-mode");
    if (saved === "fixed" || saved === "dec" || saved === "hex" || saved === "float") {
      select.value = saved;
    } else {
      select.value = "dec";
    }
  } catch (_) {
    select.value = "dec";
  }
}

function applyViewMode() {
  const sequenceList = $("#sequence-list");
  sequenceList?.classList.toggle("compact-mode", state.viewMode === "compact");

  const btn = $("#view-mode-button");
  if (btn) btn.textContent = state.viewMode === "compact" ? "標準" : "コンパクト";
}

function toggleViewMode() {
  if (state.running) return;
  const next = state.viewMode === "compact" ? "normal" : "compact";
  state.viewMode = next;
  localStorage.setItem("vtv-view-mode", next);
  applyViewMode();
  renderSequence();
}

function restoreLayoutMode() {
  try {
    const saved = localStorage.getItem("vtv-layout-mode");
    if (saved === "monitor" || saved === "workspace") state.layoutMode = saved;
  } catch (_) {}
  applyLayoutMode();
}

function applyLayoutMode() {
  const focused = state.layoutMode === "monitor";
  const watchEnabled = !$("#watch-tab-button")?.disabled;
  document.body.classList.toggle("layout-monitor-focus", focused);
  // 拡大時は監視を全幅優先（ログは通常画面のタブで確認）
  document.body.classList.toggle("layout-monitor-split", false);
  const headerBtn = $("#layout-mode-button");
  const panelBtn = $("#layout-mode-monitor-button");
  if (headerBtn) {
    headerBtn.textContent = focused ? "通常画面" : "モニター拡大";
    headerBtn.title = focused ? "シーケンス編集画面に戻る" : "モニター専用表示に切替";
  }
  if (panelBtn) {
    panelBtn.textContent = focused ? "通常へ" : "拡大";
    panelBtn.title = focused ? "シーケンス編集画面に戻る" : "モニター専用表示に切替";
  }
  if (focused && watchEnabled) selectMonitorTab("watch");
}

function setLayoutMode(mode) {
  state.layoutMode = mode === "monitor" ? "monitor" : "workspace";
  localStorage.setItem("vtv-layout-mode", state.layoutMode);
  applyLayoutMode();
}

function toggleLayoutMode() {
  setLayoutMode(state.layoutMode === "monitor" ? "workspace" : "monitor");
}

function selectMonitorTab(tab) {
  if (tab === "watch" && $("#watch-tab-button").disabled) return;
  document.querySelectorAll("[data-monitor-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.monitorTab === tab);
  });
  $("#monitor-log-panel").classList.toggle("hidden", tab !== "log");
  $("#monitor-watch-panel").classList.toggle("hidden", tab !== "watch");
}

function buildMappedWatchItems(settings) {
  if (settings.transport === "field_network") {
    return buildFnMappedWatchItems(settings);
  }
  const command = Number(settings.command_address) || 0;
  const response = Number(settings.response_address) || 0;
  const plo = Number(settings.plo_address) || 0;
  const portCount = Math.max(1, Number(settings.plo_port_count) || 32);
  const busyPort = Number(settings.busy_port) || 1;
  const items = [
    { id: "cmd-trigger", label: "トリガ", group: "コマンド領域", device: "D", address: command, format: "int32" },
    { id: "cmd-code", label: "コマンドコード", group: "コマンド領域", device: "D", address: command + 2, format: "int32" },
    { id: "rsp-result", label: "実行結果", group: "レスポンス領域", device: "D", address: response, format: "int32" },
    { id: "rsp-error", label: "エラーコード", group: "レスポンス領域", device: "D", address: response + 2, format: "int32" },
    { id: "rsp-echo", label: "コマンドエコー", group: "レスポンス領域", device: "D", address: response + 4, format: "int32" },
    { id: "rsp-param-size", label: "パラメータ総サイズ", group: "レスポンス領域", device: "D", address: response + 6, format: "int32" },
  ];
  // 結果データ領域は監視用に常時表示（有効フラグは VTV 設定整合用）
  {
    const base = Number(settings.result_data_address) || 0;
    const size = Number(settings.result_data_size) || 0;
    const watchLimit = Number(settings.result_data_watch_words) || 64;
    let watchWords = Math.min(size, watchLimit);
    watchWords -= watchWords % 2;
    for (let offset = 0; offset < watchWords; offset += 2) {
      items.push({
        id: `result-data-${offset}`,
        label: `+${String(offset).padStart(4, "0")}`,
        group: "結果データ",
        device: "D",
        address: base + offset,
        format: "int32",
        decimals: Number(settings.result_data_decimals) || 3,
        valueKind: "result_data",
      });
    }
  }
  if (settings.notify_area_enabled) {
    const notify = Number(settings.notify_address) || 0;
    items.push(
      { id: "notify-status", label: "書込ステータス", group: "結果通知エリア", device: "D", address: notify, format: "int32", valueKind: "notify_status" },
      { id: "notify-error", label: "エラーコード", group: "結果通知エリア", device: "D", address: notify + 2, format: "int32", valueKind: "notify_error" },
      { id: "notify-data-address", label: "結果データ先頭", group: "結果通知エリア", device: "D", address: notify + 4, format: "int32" },
      { id: "notify-data-size", label: "結果データサイズ", group: "結果通知エリア", device: "D", address: notify + 6, format: "int32" },
    );
  }
  for (let port = 1; port <= portCount; port += 1) {
    items.push({
      id: `plo-port-${port}`,
      label: port === busyPort ? `BUSY (Port ${port})` : `Port ${port}`,
      group: "PLO出力",
      device: "M",
      address: plo + port - 1,
      format: "bit",
      busy: port === busyPort,
    });
  }
  return items;
}

function normalizeStatusSignals(raw) {
  const list = Array.isArray(raw) && raw.length
    ? raw
    : DEFAULT_FN_STATUS_SIGNALS;
  return list.map((item, index) => {
    const source = item.source === "eso" ? "eso" : "status";
    const role = ["busy", "auto", "result_valid", "error"].includes(item.role)
      ? item.role
      : "none";
    return {
      id: String(item.id || `signal-${index + 1}`).slice(0, 40),
      label: String(item.label || item.id || `信号${index + 1}`).slice(0, 40),
      source,
      bit: source === "status" ? Number(item.bit ?? 0) : null,
      eso_port: source === "eso" ? Number(item.eso_port ?? 1) : null,
      role,
    };
  });
}

function resolveFnStatusBit(signal, esoByte = 4) {
  if (signal.source === "eso") {
    const port = Number(signal.eso_port) || 1;
    return esoByte * 8 + (port - 1);
  }
  return Number(signal.bit) || 0;
}

function renderStatusSignalTable() {
  const body = $("#fn-status-signal-body");
  if (!body) return;
  const rows = state.statusSignalDraft.length
    ? state.statusSignalDraft
    : DEFAULT_FN_STATUS_SIGNALS.map((item) => ({ ...item }));
  body.innerHTML = rows.map((signal, index) => {
    const source = signal.source === "eso" ? "eso" : "status";
    const value = source === "eso"
      ? (Number(signal.eso_port) || 1)
      : (Number(signal.bit) || 0);
    return `<tr data-status-index="${index}">
      <td><input type="text" data-field="label" value="${escapeHtml(signal.label)}" maxlength="40"></td>
      <td>
        <select data-field="source">
          <option value="status"${source === "status" ? " selected" : ""}>ステータス bit</option>
          <option value="eso"${source === "eso" ? " selected" : ""}>ESO ポート</option>
        </select>
      </td>
      <td><input type="number" data-field="index" min="0" max="128" step="1" value="${value}"></td>
      <td>
        <select data-field="role">
          <option value="none"${signal.role === "none" ? " selected" : ""}>なし</option>
          <option value="busy"${signal.role === "busy" ? " selected" : ""}>BUSY</option>
          <option value="auto"${signal.role === "auto" ? " selected" : ""}>自動運転中</option>
          <option value="result_valid"${signal.role === "result_valid" ? " selected" : ""}>結果信号有効</option>
          <option value="error"${signal.role === "error" ? " selected" : ""}>エラー</option>
        </select>
      </td>
      <td><button type="button" class="status-signal-delete" data-status-delete="${index}" title="削除">×</button></td>
    </tr>`;
  }).join("");
}

function syncStatusSignalDraftFromDom() {
  const body = $("#fn-status-signal-body");
  if (!body) return;
  const next = [];
  body.querySelectorAll("tr[data-status-index]").forEach((row, index) => {
    const prev = state.statusSignalDraft[index] || {};
    const label = row.querySelector('[data-field="label"]')?.value?.trim() || `信号${index + 1}`;
    const source = row.querySelector('[data-field="source"]')?.value === "eso" ? "eso" : "status";
    const role = row.querySelector('[data-field="role"]')?.value || "none";
    const rawIndex = Number(row.querySelector('[data-field="index"]')?.value);
    const id = prev.id || `custom-${state.statusSignalSeq++}`;
    next.push({
      id,
      label,
      source,
      bit: source === "status" ? (Number.isFinite(rawIndex) ? rawIndex : 0) : null,
      eso_port: source === "eso" ? (Number.isFinite(rawIndex) && rawIndex >= 1 ? rawIndex : 1) : null,
      role: ["busy", "auto", "result_valid", "error", "none"].includes(role) ? role : "none",
    });
  });
  state.statusSignalDraft = next;
}

function readStatusSignalsFromForm() {
  syncStatusSignalDraftFromDom();
  const signals = normalizeStatusSignals(state.statusSignalDraft);
  const busyCount = signals.filter((item) => item.role === "busy").length;
  if (busyCount !== 1) {
    throw new Error(`ステータス信号の role=BUSY はちょうど 1 つ必要です（現在 ${busyCount} 件）`);
  }
  const esoPorts = Number($("#fn-eso-ports")?.value) || 0;
  for (const signal of signals) {
    if (signal.source === "eso") {
      if (esoPorts <= 0) {
        throw new Error(`信号「${signal.label}」: ESO ポート数が 0 のため ESO に割付できません`);
      }
      if (signal.eso_port > esoPorts) {
        throw new Error(
          `信号「${signal.label}」: ESO-${signal.eso_port} は設定ポート数 ${esoPorts} を超えています`
        );
      }
    }
  }
  return signals;
}

function buildFnMappedWatchItems(settings) {
  const esiPorts = Number(settings.fn_esi_ports) || 0;
  const esoPorts = Number(settings.fn_eso_ports) || 0;
  const responseWords = Number(settings.response_size) || 64;
  let resultWords = Number(settings.result_data_size) || 0;
  // PLCLINK 既定 2048 が混入すると割付が壊れるため、Assem10 に収まるよう制限
  const inputBytes = Number(settings.fn_input_size) || 612;
  const maxResultWords = Math.max(0, Math.floor(inputBytes / 2) - 2 - Math.floor(esoPorts / 16) - responseWords);
  if (resultWords > maxResultWords && maxResultWords >= 0) {
    resultWords = maxResultWords;
  }
  const esiWords = Math.floor(esiPorts / 16);
  const esoWords = Math.floor(esoPorts / 16);
  const cmd = 2 + esiWords;
  const rsp = 2 + esoWords + resultWords;
  const resultWord = 2 + esoWords;
  const esoByte = 4;
  const esiByte = 4;
  const watchLimit = Number(settings.result_data_watch_words) || 64;
  const statusSignals = normalizeStatusSignals(settings.fn_status_signals);
  const items = statusSignals.map((signal) => ({
    id: `fn-status-${signal.id}`,
    label: signal.label,
    group: "ステータス",
    device: "IN",
    address: resolveFnStatusBit(signal, esoByte),
    format: "bit",
    busy: signal.role === "busy",
  }));
  // VTV「結果データ出力モニタ」相当を先頭側に配置
  let watchWords = Math.min(resultWords, watchLimit);
  watchWords -= watchWords % 2;
  for (let offset = 0; offset < watchWords; offset += 2) {
    items.push({
      id: `result-data-${offset}`,
      label: `+${String(offset).padStart(5, "0")}`,
      group: "結果データ (Assem10)",
      device: "IN",
      address: resultWord + offset,
      relAddress: offset,
      format: "int32",
      decimals: Number(settings.result_data_decimals) || 3,
      valueKind: "result_data",
    });
  }
  items.push(
    { id: "rsp-result", label: "実行結果 (+0000)", group: "レスポンス領域 (Assem10)", device: "IN", address: rsp, format: "int32" },
    { id: "rsp-error", label: "エラーコード (+0002)", group: "レスポンス領域 (Assem10)", device: "IN", address: rsp + 2, format: "int32" },
    { id: "rsp-echo", label: "コマンドエコー (+0004)", group: "レスポンス領域 (Assem10)", device: "IN", address: rsp + 4, format: "int32" },
    { id: "rsp-param-size", label: "パラメータ総サイズ (+0006)", group: "レスポンス領域 (Assem10)", device: "IN", address: rsp + 6, format: "int32" },
    { id: "cmd-trigger", label: "トリガ (+0000)", group: "コマンド領域 (Assem20)", device: "OUT", address: cmd, format: "int32" },
    { id: "cmd-code", label: "コマンドコード (+0002)", group: "コマンド領域 (Assem20)", device: "OUT", address: cmd + 2, format: "int32" },
  );
  for (let port = 1; port <= esoPorts; port += 1) {
    items.push({
      id: `eso-port-${port}`,
      label: `ESO-${port}`,
      group: "ESO出力 (Assem10)",
      device: "IN",
      address: esoByte * 8 + (port - 1),
      format: "bit",
    });
  }
  const esiShow = Math.min(esiPorts, 32);
  for (let port = 1; port <= esiShow; port += 1) {
    items.push({
      id: `esi-port-${port}`,
      label: `ESI-${port}`,
      group: "ESI入力 (Assem20)",
      device: "OUT",
      address: esiByte * 8 + (port - 1),
      format: "bit",
    });
  }
  return items;
}

function refreshMappedWatchItems() {
  const settings = {
    ...state.settings,
    ...(($("#transport") && readSettingsForm()) || {}),
  };
  const watchable = settings.transport === "plclink" || settings.transport === "field_network";
  state.watchItems = buildMappedWatchItems(watchable ? settings : state.settings);
  const keep = new Set(state.watchItems.map((item) => item.id));
  for (const id of Object.keys(state.watchValues)) {
    if (!keep.has(id)) delete state.watchValues[id];
  }
}

function renderWatchList(changed = new Set()) {
  const list = $("#watch-list");
  if (!list) return;
  if (!state.watchItems.length) {
    list.innerHTML = '<div class="watch-empty">接続設定から監視アドレスを生成できません。</div>';
    return;
  }
  const groups = [];
  for (const item of state.watchItems) {
    const last = groups[groups.length - 1];
    if (!last || last.name !== item.group) groups.push({ name: item.group, items: [item] });
    else last.items.push(item);
  }
  const renderGroup = (group) => {
    const title = watchGroupTitle(group.name, group.items);
    const dense = group.items.length >= 8;
    const rows = group.items.map((item) => {
      const snapshot = state.watchValues[item.id];
      const value = snapshot === undefined
        ? "—"
        : snapshot.valid === false
          ? "無効"
          : formatWatchValue(snapshot.value, item);
      const valueClass = watchValueClass(snapshot, item, changed.has(item.id));
      return `<div class="watch-map-row${item.busy ? " busy" : ""}">
        <span class="watch-map-label">${escapeHtml(item.label)}</span>
        <span class="watch-map-address">${formatWatchAddress(item)}</span>
        <div class="watch-value ${valueClass}" data-watch-value="${item.id}">${escapeHtml(value)}</div>
      </div>`;
    }).join("");
    return `<section class="watch-group${dense ? " watch-group-dense" : ""}">
      <div class="watch-group-title">${escapeHtml(title)}</div>
      <div class="watch-group-body">${rows}</div>
    </section>`;
  };
  const summary = groups.filter((group) => group.items.length < 8);
  const dense = groups.filter((group) => group.items.length >= 8);
  list.innerHTML = [
    summary.length ? `<div class="watch-summary-row">${summary.map(renderGroup).join("")}</div>` : "",
    ...dense.map(renderGroup),
  ].join("");
}

function watchGroupTitle(name, items) {
  if (!items.length) return name;
  if (name.startsWith("結果データ")) {
    const first = typeof items[0].relAddress === "number" ? items[0].relAddress : items[0].address;
    const lastItem = items[items.length - 1];
    const last = typeof lastItem.relAddress === "number"
      ? lastItem.relAddress + 1
      : lastItem.address + 1;
    return `${name}（+${String(first).padStart(5, "0")}–+${String(last).padStart(5, "0")}）`;
  }
  if (name === "結果通知エリア") {
    return `${name}（D${items[0].address}–D${items[0].address + 7}）`;
  }
  return name;
}

function formatWatchValue(value, item) {
  if (item.format === "bit") return value ? "ON" : "OFF";
  if (item.format === "fixed" && typeof value === "number") {
    return value.toFixed(item.decimals);
  }
  if (item.valueKind === "notify_status") {
    const labels = {
      1: "書込許可",
      2: "書込完了",
      3: "分割先頭完了",
      4: "分割中間完了",
      5: "分割末尾完了",
    };
    return labels[value] ? `${value} (${labels[value]})` : String(value);
  }
  if (item.valueKind === "notify_error") {
    const labels = { 0: "なし", 100: "オーバーフロー", 101: "書込許可TO" };
    return labels[value] !== undefined ? `${value} (${labels[value]})` : String(value);
  }
  if (item.valueKind === "result_data" && typeof value === "number") {
    return formatResultDataValue(value, item);
  }
  return String(value);
}

/** VTV 結果データ「No Data」センチネル (0x7FFFFFFE) */
const RESULT_NO_DATA = 2147483646;

function formatResultDataValue(value, item) {
  const decimals = Number(
    item.decimals ?? $("#fn-result-decimals")?.value ?? $("#result-data-decimals")?.value ?? 3,
  );
  const mode = $("#result-data-display-mode")?.value || "dec";
  const raw = value | 0;
  const unsigned = raw >>> 0;
  const outputText = mode === "hex"
    ? `0x${unsigned.toString(16).toUpperCase().padStart(8, "0")}`
    : String(raw);

  // 直前が double の下位ワードなら VTV 同様「>」
  if (mode === "float" && isResultFloatContinuation(item)) {
    return `出力値 ${outputText}\nデータ >`;
  }

  let dataText;
  if (raw === RESULT_NO_DATA) {
    dataText = "No Data";
  } else if (mode === "hex") {
    dataText = outputText;
  } else if (mode === "fixed") {
    dataText = (raw / (10 ** decimals)).toFixed(decimals);
  } else if (mode === "float") {
    const paired = readResultFloatPair(item);
    dataText = paired == null ? String(raw) : formatFloatData(paired);
  } else {
    // Dec: VTV と同様、整数項目は出力値＝データ
    dataText = String(raw);
  }

  // VTV モニタ列順: 出力値 → データ
  return `出力値 ${outputText}\nデータ ${dataText}`;
}

function readResultFloatPair(item) {
  if (typeof item.relAddress !== "number") return null;
  const current = state.watchValues[item.id];
  const next = state.watchValues[`result-data-${item.relAddress + 2}`];
  if (!current || current.valid === false || typeof current.value !== "number") return null;
  if (!next || next.valid === false || typeof next.value !== "number") return null;
  if (current.value === RESULT_NO_DATA || next.value === RESULT_NO_DATA) return null;
  // LE double: 低位 dword = 当ワード, 高位 dword = 次ワード（VTV 倍精度）
  const buffer = new ArrayBuffer(8);
  const view = new DataView(buffer);
  view.setInt32(0, current.value | 0, true);
  view.setInt32(4, next.value | 0, true);
  const f = view.getFloat64(0, true);
  if (!Number.isFinite(f)) return null;
  const abs = Math.abs(f);
  // 整数ペアの誤検知（サブノーマル等）を除外。処理時間 ~62 などは通す。
  if (abs < 1e-6 || abs > 1e15) return null;
  return f;
}

function isResultFloatContinuation(item) {
  if (typeof item.relAddress !== "number" || item.relAddress < 2) return false;
  const prev = state.watchItems.find(
    (candidate) => candidate.id === `result-data-${item.relAddress - 2}`,
  );
  if (!prev) return false;
  const mode = $("#result-data-display-mode")?.value || "dec";
  if (mode !== "float") return false;
  return readResultFloatPair(prev) != null;
}

function formatFloatData(value) {
  const abs = Math.abs(value);
  if (abs !== 0 && (abs < 1e-4 || abs >= 1e7)) return value.toExponential(6);
  // VTV 表示に近い桁（余分な 0 は削る）
  return String(parseFloat(value.toPrecision(12)));
}

function watchValueClass(snapshot, item, changed) {
  const classes = [];
  if (changed) classes.push("changed");
  if (snapshot === undefined || snapshot.valid === false) return classes.join(" ");
  if (item.format === "bit") classes.push(snapshot.value ? "on" : "off");
  return classes.join(" ");
}

function updateWatchValueDisplays(changed = new Set()) {
  for (const item of state.watchItems) {
    const element = document.querySelector(`[data-watch-value="${item.id}"]`);
    if (!element) continue;
    const snapshot = state.watchValues[item.id];
    element.textContent = snapshot === undefined
      ? "—"
      : snapshot.valid === false
        ? "無効"
        : formatWatchValue(snapshot.value, item);
    element.className = `watch-value ${watchValueClass(snapshot, item, changed.has(item.id))}`.trim();
  }
}

function setWatchStatus(text, status = "") {
  const element = $("#watch-status");
  element.textContent = text;
  element.className = `watch-status ${status}`.trim();
}

function formatWatchAddress(item) {
  if (item.device === "IN" || item.device === "OUT") {
    if (item.format === "bit") return `${item.device} bit${item.address}`;
    // 結果データは VTV Rel. と同じ領域先頭からの相対オフセットを優先表示
    if (typeof item.relAddress === "number") {
      return `+${String(item.relAddress).padStart(5, "0")}`;
    }
    return `${item.device} +${String(item.address).padStart(4, "0")}`;
  }
  return `${item.device}${item.address}`;
}

function startWatch() {
  const settings = readSettingsForm();
  if (settings.transport !== "plclink" && settings.transport !== "field_network") {
    setWatchStatus("PLCLINK / Field Network を選択してください", "error");
    return;
  }
  refreshMappedWatchItems();
  renderWatchList();
  if (!state.watchItems.length) {
    setWatchStatus("監視アドレスがありません", "error");
    return;
  }
  state.watchRunning = true;
  resetWatchActualPeriod();
  $("#start-watch-button").disabled = true;
  $("#stop-watch-button").disabled = false;
  setWatchStatus("監視中", "running");
  pollWatchValues();
}

function stopWatch(resetValues = false) {
  state.watchRunning = false;
  clearTimeout(state.watchTimer);
  state.watchTimer = null;
  resetWatchActualPeriod();
  if (resetValues) {
    state.watchValues = {};
    renderWatchList();
  }
  $("#start-watch-button").disabled = false;
  $("#stop-watch-button").disabled = true;
  setWatchStatus("停止中");
}

async function pollWatchValues() {
  if (!state.watchRunning) return;
  const started = performance.now();
  if (state.watchLastCycleAt > 0) {
    const cycleMs = started - state.watchLastCycleAt;
    state.watchActualMs = state.watchActualMs == null
      ? cycleMs
      : (state.watchActualMs * 0.7) + (cycleMs * 0.3);
  }
  state.watchLastCycleAt = started;

  const liveSettings = ($("#transport") && readSettingsForm()) || state.settings;
  const transport = liveSettings.transport || state.settings.transport;
  const endpoint = transport === "field_network"
    ? "/api/field-network/memory/read"
    : "/api/plclink/memory/read";
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        items: state.watchItems.map(({ id, label, group, device, address, format, length, decimals }) => ({
          id,
          label: label || "",
          group: group || "",
          device,
          address,
          format,
          length: length ?? 8,
          decimals: decimals ?? 3,
        })),
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "監視データを取得できません");
    const changed = new Set();
    const nextValues = {};
    for (const snapshot of data.values) {
      nextValues[snapshot.id] = snapshot;
      if (
        state.watchValues[snapshot.id] !== undefined
        && JSON.stringify(state.watchValues[snapshot.id]) !== JSON.stringify(snapshot)
      ) changed.add(snapshot.id);
    }
    state.watchValues = nextValues;
    setWatchStatus("監視中", "running");
    updateWatchValueDisplays(changed);
  } catch (error) {
    state.watchValues = {};
    updateWatchValueDisplays();
    setWatchStatus(`再接続待ち: ${error.message}`, "error");
  } finally {
    const fetchMs = performance.now() - started;
    state.watchFetchMs = state.watchFetchMs == null
      ? fetchMs
      : (state.watchFetchMs * 0.7) + (fetchMs * 0.3);
    updateWatchActualPeriodDisplay();
    scheduleNextWatchPoll(fetchMs);
  }
}

function renderPalette() {
  const query = $("#command-search")?.value.trim().toLowerCase() || "";
  const transport = $("#transport")?.value || state.settings.transport;
  const isMapped = transport === "plclink" || transport === "field_network";
  const available = state.catalog.filter((item) => !isMapped || item.plclink_supported);
  const filtered = available.filter((item) =>
    `${item.code} ${item.name} ${item.description} ${item.tool_name || ""}`.toLowerCase().includes(query)
  );
  if ($("#catalog-count")) $("#catalog-count").textContent = available.length;
  $("#command-palette").innerHTML = catalogGroups(filtered).map((group) => `
    <section class="command-group">
      <h4>${escapeHtml(group.label)}<span>${group.items.length}</span></h4>
      ${group.items.map((item) => `
        <button class="palette-card palette-command" data-code="${item.code}">
          <span class="command-code">${isMapped ? `${item.plclink_code}：` : item.code}</span>
          <span class="command-name">${escapeHtml(item.name)}</span>
          ${isMapped ? `<small class="plclink-code">${transport === "field_network" ? "FNコマンド" : "PLCLINKコマンド"}</small>` : ""}
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
  const isCompact = state.viewMode === "compact";
  if (step.type === "command") {
    const def = state.catalog.find((item) => item.code === step.command);
    const transport = $("#transport")?.value || state.settings.transport;
    const isMapped = transport === "plclink" || transport === "field_network";
    const unsupported = isMapped && !def.plclink_supported;
    const modeLabel = transport === "field_network" ? "FNコマンド" : "PLCLINKコマンド";
    const fields = (def.arguments || []).map((arg) => argumentField(step, arg)).join("");
    const raw = def.raw_arguments ? `
      <label>引数文字列<input data-field="raw" value="${escapeHtml(step.arguments.raw || "")}" placeholder="別資料の構文に従って入力"></label>` : "";
    const compactSummary = commandCompactSummary(step, def);
    const displayCode = isMapped && def.plclink_code ? `${def.plclink_code}：` : def.code;
    return `<article class="step-card generated-step${unsupported ? " unsupported-step" : ""}" data-id="${step.id}">
      ${stepHeader(step, `<strong>${displayCode}</strong>${escapeHtml(def.name)}${isMapped ? `<small class="plclink-code">${modeLabel}</small>` : ""}${def.tool_name ? `<small class="tool-badge">${escapeHtml(def.tool_id)} ${escapeHtml(def.tool_name)}</small>` : ""}`, nested)}
      ${isCompact
    ? (compactSummary ? `<div class="step-compact-row">${compactSummary}</div>` : "")
    : `<div class="step-body">${fields}${raw}
        ${unsupported ? `<p class="step-warning">${escapeHtml(def.plclink_reason || "この通信方式では使用できません")}</p>` : ""}
        <p class="step-description">${escapeHtml(def.description || "")}${!isMapped && def.example ? `　例: ${escapeHtml(def.example)}` : ""}</p>
      </div>`}
    </article>`;
  }
  if (step.type === "delay") {
    const title = isCompact
      ? `<strong>WAIT</strong>待機 ${step.milliseconds}ms`
      : "<strong>WAIT</strong>待機";
    return `<article class="step-card control-step generated-step" data-id="${step.id}">
      ${stepHeader(step, title, nested)}
      ${isCompact ? "" : `<div class="step-body"><label>待機時間（ミリ秒）
        <input data-field="milliseconds" type="number" min="0" max="3600000" value="${step.milliseconds}">
      </label></div>`}
    </article>`;
  }
  if (step.type === "break") {
    return `<article class="step-card break-step generated-step" data-id="${step.id}">
      ${stepHeader(step, "<strong>BREAK</strong>最寄りのループを抜ける", nested)}
      ${isCompact ? "" : `<div class="step-body">
        <p class="step-description">このカードを実行すると、内側から最も近いループを終了します。</p>
      </div>`}
    </article>`;
  }
  if (step.type === "loop") {
    const title = isCompact
      ? `<strong>LOOP</strong>×${step.count}`
      : "<strong>LOOP</strong>指定回数くり返す";
    return `<article class="step-card control-step generated-step" data-id="${step.id}">
      ${stepHeader(step, title, nested)}
      ${isCompact ? "" : `<div class="step-body"><label>回数
        <input data-field="count" type="number" min="1" max="10000" value="${step.count}">
      </label></div>`}
      ${childArea(step, "steps", "くり返すカード")}
    </article>`;
  }
  return `<article class="step-card control-step generated-step" data-id="${step.id}">
    ${stepHeader(step, (() => {
      if (!isCompact) return "<strong>IF</strong>応答による条件分岐";
      const sourceLabel = step.source === "status" ? "AK/NK/ER" : "受信全体";
      const opLabel = step.operator === "equals" ? "等しい"
        : step.operator === "contains" ? "含む"
          : "含まない";
      return `<strong>IF</strong>${sourceLabel} ${opLabel} ${escapeHtml(step.value)}`;
    })(), nested)}
    ${isCompact ? "" : `<div class="step-body">
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
    </div>`}
    ${childArea(step, "then_steps", "条件に一致")}
    ${childArea(step, "else_steps", "条件に不一致")}
  </article>`;
}

function commandCompactSummary(step, def) {
  const parts = [];
  for (const arg of def.arguments || []) {
    const value = step.arguments[arg.key];
    if (value === undefined || value === null || value === "") continue;
    parts.push(`${arg.label}:${value}`);
    if (parts.length >= 3) break;
  }
  if (def.raw_arguments && step.arguments.raw) parts.push(`raw:${step.arguments.raw}`);
  return parts.map((part) => `<span>${escapeHtml(part)}</span>`).join("");
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
  const isCompact = state.viewMode === "compact";
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
    ${isCompact ? "" : `<div class="nested-add"><select data-child-select="${key}">${controlOptions}${commandOptions}</select>
      <button data-add-child="${key}" class="icon-button">＋ カード追加</button>
    </div>`}
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

function syncTimeoutInputs(value) {
  const text = String(value);
  for (const id of ["header-timeout", "timeout"]) {
    const input = $(`#${id}`);
    if (input) input.value = text;
  }
}

function readTimeoutValue() {
  const header = Number($("#header-timeout")?.value);
  if (Number.isFinite(header) && header > 0) return header;
  const settings = Number($("#timeout")?.value);
  if (Number.isFinite(settings) && settings > 0) return settings;
  return state.settings.timeout || 5;
}

function onTimeoutChanged() {
  const timeout = readTimeoutValue();
  syncTimeoutInputs(timeout);
  state.settings.timeout = timeout;
  localStorage.setItem("vtv-settings", JSON.stringify(state.settings));
}

function readSettingsForm() {
  const transport = $("#transport").value;
  const encoding = transport === "plclink"
    ? $("#plclink-encoding").value
    : transport === "field_network"
      ? ($("#fn-encoding")?.value || "cp932")
      : $("#encoding").value;
  const lineDigits = transport === "plclink"
    ? Number($("#plclink-line-digits").value)
    : Number($("#line-digits").value);
  const isFn = transport === "field_network";
  return {
    transport,
    host: $("#host").value.trim(),
    port: Number($("#port").value),
    timeout: readTimeoutValue(),
    input_terminator: $("#input-terminator").value,
    output_terminator: $("#output-terminator").value,
    separator: $("#separator").value,
    header_separator: $("#header-separator").checked,
    footer_separator: $("#footer-separator").checked,
    checksum: $("#checksum").checked,
    input_response: $("#input-response").checked,
    encoding,
    line_number_digits: lineDigits,
    command_address: Number($("#command-address").value),
    command_size: isFn
      ? Number($("#fn-command-size")?.value)
      : Number($("#command-size").value),
    response_address: Number($("#response-address").value),
    response_size: isFn
      ? Number($("#fn-response-size")?.value)
      : Number($("#response-size").value),
    plo_address: Number($("#plo-address").value),
    plo_port_count: Number($("#plo-port-count").value),
    busy_port: Number($("#busy-port").value),
    byte_order: isFn
      ? ($("#fn-byte-order")?.value || "high_low")
      : $("#byte-order").value,
    result_data_enabled: $("#result-data-enabled").checked,
    result_data_address: Number($("#result-data-address").value),
    result_data_size: isFn
      ? (() => {
          const n = Number($("#fn-result-size")?.value);
          // Assem10 に収まる範囲（異常な PLCLINK 残存値を除外）
          return Number.isFinite(n) && n >= 0 && n <= 512 ? n : 238;
        })()
      : Number($("#result-data-size").value),
    result_data_watch_words: isFn
      ? Number($("#fn-result-watch-words")?.value)
      : Number($("#result-data-watch-words").value),
    result_data_decimals: isFn
      ? Number($("#fn-result-decimals")?.value)
      : Number($("#result-data-decimals").value),
    notify_area_enabled: $("#notify-area-enabled").checked,
    notify_address: Number($("#notify-address").value),
    fn_esi_ports: Number($("#fn-esi-ports")?.value || 0),
    fn_eso_ports: Number($("#fn-eso-ports")?.value || 0),
    fn_input_size: Number($("#fn-input-size")?.value || 612),
    fn_output_size: Number($("#fn-output-size")?.value || 132),
    fn_rpi_us: Number($("#fn-rpi-us")?.value || 10000),
    fn_connection_path: ($("#fn-connection-path")?.value || "20 04 24 01 2C 14 2C 0A").trim(),
    fn_o_to_t_header_bytes: Number($("#fn-o-to-t-header")?.value || 4),
    fn_eds_name: state.settings.fn_eds_name || "",
    fn_status_signals: isFn
      ? readStatusSignalsFromForm()
      : normalizeStatusSignals(state.settings.fn_status_signals),
  };
}

function openSettingsDialog() {
  const dialog = $("#settings-dialog");
  if (!dialog) return;
  applySettingsToForm();
  syncTransportUi();
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
}

function closeSettingsDialog() {
  const dialog = $("#settings-dialog");
  if (!dialog) return;
  if (typeof dialog.close === "function" && dialog.open) dialog.close();
  else dialog.removeAttribute("open");
}

async function syncPlcLinkPortFromServer() {
  try {
    const response = await fetch("/api/plclink/status");
    if (!response.ok) return;
    const data = await response.json();
    if (data.status !== "listening" || !data.bind) return;
    const port = Number(String(data.bind).split(":").pop());
    if (!port) return;
    state.settings.port = port;
    localStorage.setItem("vtv-settings", JSON.stringify(state.settings));
  } catch (_) {}
}

async function saveSettings(event) {
  event.preventDefault();
  try {
    state.settings = readSettingsForm();
    localStorage.setItem("vtv-settings", JSON.stringify(state.settings));
    refreshMappedWatchItems();
    renderWatchList();
    closeSettingsDialog();
    void applySavedConnectionSettings();
  } catch (error) {
    console.error(error);
    const resultEl = $("#connection-test-result");
    if (resultEl) {
      resultEl.className = "test-result error";
      resultEl.textContent = error.message || String(error);
    } else {
      alert(error.message || String(error));
    }
  }
}

async function applySavedConnectionSettings() {
  const resultEl = $("#connection-test-result");
  if (state.settings.transport === "plclink") {
    const data = await startSoftPlc({ updateBadge: true });
    if (!data) {
      await syncPlcLinkPortFromServer();
      refreshConnectionBadge();
      return;
    }
    if (resultEl) {
      resultEl.className = "test-result success";
      resultEl.textContent =
        `${resultEl.textContent}\n設定を保存しました（既存の VTV 接続は維持します）。`;
    }
    return;
  }
  if (state.settings.transport === "field_network") {
    await connectFieldNetwork();
    return;
  }
  await verifyConnectionSettings({
    showMessage: true,
    resultEl,
  });
}

function restoreSettings() {
  try {
    const saved = { ...state.settings, ...JSON.parse(localStorage.getItem("vtv-settings")) };
    if (saved.plo_address === undefined && saved.busy_address !== undefined) {
      saved.plo_address = saved.busy_address;
      saved.busy_port = saved.busy_port || 1;
    }
    delete saved.busy_address;
    state.settings = { ...state.settings, ...saved };
    state.settings.fn_status_signals = normalizeStatusSignals(
      state.settings.fn_status_signals,
    );
    state.statusSignalDraft = state.settings.fn_status_signals.map((item) => ({ ...item }));
  } catch (_) {}
}

function applySettingsToForm() {
  const s = state.settings;
  $("#transport").value = s.transport || "tcp";
  $("#host").value = s.host;
  $("#port").value = s.port;
  syncTimeoutInputs(s.timeout ?? 5);
  $("#input-terminator").value = s.input_terminator;
  $("#output-terminator").value = s.output_terminator;
  $("#separator").value = s.separator;
  $("#encoding").value = s.encoding;
  $("#plclink-encoding").value = s.encoding;
  $("#line-digits").value = String(s.line_number_digits);
  $("#plclink-line-digits").value = String(s.line_number_digits);
  $("#header-separator").checked = s.header_separator;
  $("#footer-separator").checked = s.footer_separator;
  $("#checksum").checked = s.checksum;
  $("#input-response").checked = s.input_response;
  $("#command-address").value = s.command_address ?? 4096;
  $("#command-size").value = s.command_size ?? 64;
  $("#response-address").value = s.response_address ?? 8192;
  $("#response-size").value = s.response_size ?? 64;
  $("#plo-address").value = s.plo_address ?? s.busy_address ?? 1024;
  $("#plo-port-count").value = s.plo_port_count ?? 32;
  $("#busy-port").value = s.busy_port ?? 1;
  $("#byte-order").value = s.byte_order || "high_low";
  $("#result-data-enabled").checked = !!s.result_data_enabled;
  $("#result-data-address").value = s.result_data_address ?? 512;
  $("#result-data-size").value = s.result_data_size ?? 2048;
  $("#result-data-watch-words").value = s.result_data_watch_words ?? 64;
  $("#result-data-decimals").value = s.result_data_decimals ?? 3;
  $("#notify-area-enabled").checked = !!s.notify_area_enabled;
  $("#notify-address").value = s.notify_address ?? 2560;
  if ($("#fn-input-size")) {
    $("#fn-input-size").value = s.fn_input_size ?? 612;
    $("#fn-output-size").value = s.fn_output_size ?? 132;
    $("#fn-rpi-us").value = s.fn_rpi_us ?? 10000;
    $("#fn-esi-ports").value = String(s.fn_esi_ports ?? 0);
    $("#fn-eso-ports").value = String(s.fn_eso_ports ?? 0);
    $("#fn-o-to-t-header").value = String(s.fn_o_to_t_header_bytes ?? 4);
    $("#fn-command-size").value = s.command_size ?? 64;
    $("#fn-response-size").value = s.response_size ?? 64;
    {
      // PLCLINK の 2048 などが残っていると Assem10 割付が壊れる
      let fnResult = Number(s.result_data_size);
      if (!Number.isFinite(fnResult) || fnResult <= 0 || fnResult > 512) {
        fnResult = 238;
      }
      $("#fn-result-size").value = fnResult;
    }
    $("#fn-result-watch-words").value = s.result_data_watch_words ?? 64;
    $("#fn-result-decimals").value = s.result_data_decimals ?? 3;
    $("#fn-byte-order").value = s.byte_order || "high_low";
    $("#fn-encoding").value = s.encoding || "cp932";
    $("#fn-connection-path").value = s.fn_connection_path || "20 04 24 01 2C 14 2C 0A";
  }
  state.statusSignalDraft = normalizeStatusSignals(s.fn_status_signals);
  renderStatusSignalTable();
  syncTransportUi();
  syncResultDataUi();
  updateBusyAddressHint();
  updateFnLayoutHint();
  restoreResultDataDisplayMode();
}

let lastTransport = null;

function syncTransportUi() {
  const transport = $("#transport").value;
  const isPlc = transport === "plclink";
  const isFn = transport === "field_network";
  const isMapped = isPlc || isFn;
  const prev = lastTransport;

  $("#tcp-settings").classList.toggle("hidden", isMapped);
  $("#plclink-settings").classList.toggle("hidden", !isPlc);
  $("#field-network-settings")?.classList.toggle("hidden", !isFn);

  const hint = $("#transport-hint");
  if (isPlc) {
    $("#host-label-text").textContent = "待受アドレス";
    $("#host").placeholder = "0.0.0.0";
    if (!$("#host").value || prev === "tcp" || prev === "field_network") {
      $("#host").value = "0.0.0.0";
    }
    if ([55555, 44818].includes(Number($("#port").value)) || prev !== "plclink") {
      $("#port").value = 5000;
    }
    $("#port-label-text").textContent = "待受ポート";
    hint.textContent =
      "アプリが疑似 PLC（MC 3E）として全 NIC で待ち受けます。"
      + " 先に「疑似PLC待受開始」を押し、VTV 側の接続先を"
      + " この PC の LAN IP:待受ポート にしてください。";
  } else if (isFn) {
    $("#host-label-text").textContent = "装置 IP";
    $("#host").placeholder = "192.168.0.10";
    if ($("#host").value === "0.0.0.0" || prev === "plclink") $("#host").value = "";
    if ([5000, 55555].includes(Number($("#port").value)) || prev !== "field_network") {
      $("#port").value = 44818;
    }
    $("#port-label-text").textContent = "EIP ポート";
    hint.textContent =
      "アプリが EtherNet/IP Scanner として VTV（Adapter）へ接続します。"
      + " 接続先は VTV 本体の IP（LAN1/LAN2、ポート 44818）。"
      + " VTV で「フィールドネットワーク（通常）を有効にする」を ON にし、"
      + " 作成した EDS を両方にインポートしてサイズを一致させてください。";
    if (prev !== null && prev !== "field_network") {
      applyFieldNetworkDefaultsToForm();
    }
    updateFnLayoutHint();
  } else {
    $("#host-label-text").textContent = "装置 IP";
    $("#host").placeholder = "192.168.0.10";
    if ($("#host").value === "0.0.0.0" || prev === "plclink") $("#host").value = "";
    if ([5000, 44818].includes(Number($("#port").value)) || prev !== "tcp") {
      $("#port").value = 55555;
    }
    $("#port-label-text").textContent = "ポート";
    hint.textContent = "装置の Network I/O（TCP）へクライアント接続します。";
  }

  $("#start-softplc-button")?.classList.toggle("hidden", !isPlc);
  $("#fn-connect-button")?.classList.toggle("hidden", !isFn);
  lastTransport = transport;
  $("#watch-tab-button").disabled = !isMapped;
  updateWatchNote();
  if (!isMapped) {
    stopWatch(true);
    selectMonitorTab("log");
  } else {
    refreshMappedWatchItems();
    renderWatchList();
  }
  applyLayoutMode();
  renderPalette();
  renderSequence();
}

function applyFieldNetworkDefaultsToForm() {
  if (!$("#fn-input-size")) return;
  $("#fn-input-size").value = 612;
  $("#fn-output-size").value = 136;
  $("#fn-rpi-us").value = 10000;
  $("#fn-esi-ports").value = "32";
  $("#fn-eso-ports").value = "32";
  $("#fn-command-size").value = 64;
  $("#fn-response-size").value = 64;
  $("#fn-result-size").value = 238;
  $("#fn-result-watch-words").value = 64;
  $("#fn-connection-path").value = "20 04 24 01 2C 14 2C 0A";
  $("#fn-o-to-t-header").value = "4";
  state.statusSignalDraft = DEFAULT_FN_STATUS_SIGNALS.map((item) => ({ ...item }));
  renderStatusSignalTable();
}

function updateFnLayoutHint() {
  const hint = $("#fn-layout-hint");
  if (!hint) return;
  const esi = Number($("#fn-esi-ports")?.value) || 0;
  const eso = Number($("#fn-eso-ports")?.value) || 0;
  const cmd = Number($("#fn-command-size")?.value) || 0;
  const rsp = Number($("#fn-response-size")?.value) || 0;
  const result = Number($("#fn-result-size")?.value) || 0;
  const inSize = Number($("#fn-input-size")?.value) || 0;
  const outSize = Number($("#fn-output-size")?.value) || 0;
  const esiW = Math.floor(esi / 16);
  const esoW = Math.floor(eso / 16);
  const calcIn = (2 + esoW + result + rsp) * 2;
  const calcOut = (2 + esiW + cmd) * 2;
  const okIn = calcIn === inSize;
  const okOut = calcOut === outSize;
  hint.textContent =
    `割付計算: 入力 ${calcIn} byte / 出力 ${calcOut} byte`
    + `（EDS: 入力 ${inSize} / 出力 ${outSize}）`
    + (okIn && okOut ? " — 一致" : " — 不一致。ESI/ESO・語数または EDS を調整してください");
  hint.classList.toggle("error-note", !(okIn && okOut));
}

async function onEdsImport(event) {
  const input = event.target;
  const file = input.files?.[0];
  const status = $("#eds-import-status");
  if (!file) return;
  const body = new FormData();
  body.append("file", file);
  if (status) status.textContent = "EDS を解析中…";
  try {
    const response = await fetch("/api/field-network/eds/import", {
      method: "POST",
      body,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "EDS を読み込めません");
    const s = data.suggested || {};
    if (s.fn_input_size != null) $("#fn-input-size").value = s.fn_input_size;
    if (s.fn_output_size != null) $("#fn-output-size").value = s.fn_output_size;
    if (s.fn_rpi_us != null) $("#fn-rpi-us").value = s.fn_rpi_us;
    if (s.fn_connection_path) $("#fn-connection-path").value = s.fn_connection_path;
    if (s.fn_o_to_t_header_bytes != null) $("#fn-o-to-t-header").value = s.fn_o_to_t_header_bytes;
    if (s.command_size != null) $("#fn-command-size").value = s.command_size;
    if (s.response_size != null) $("#fn-response-size").value = s.response_size;
    if (s.result_data_size != null) $("#fn-result-size").value = s.result_data_size;
    if (s.fn_esi_ports != null) $("#fn-esi-ports").value = String(s.fn_esi_ports);
    if (s.fn_eso_ports != null) $("#fn-eso-ports").value = String(s.fn_eso_ports);
    if (s.port != null) $("#port").value = s.port;
    updateFnLayoutHint();
    refreshMappedWatchItems();
    renderWatchList();
    const name = data.eds?.catalog || data.eds?.product_name || file.name;
    const warnings = (data.eds?.warnings || []).join(" / ");
    if (status) {
      status.textContent =
        `取り込み完了: ${name}`
        + `（IN ${s.fn_input_size} / OUT ${s.fn_output_size}`
        + ` / ESI ${s.fn_esi_ports ?? "-"} / ESO ${s.fn_eso_ports ?? "-"}`
        + ` / CMD ${s.command_size ?? "-"} / RPI ${s.fn_rpi_us}μs）`
        + (warnings ? ` ※${warnings}` : "");
    }
  } catch (error) {
    if (status) status.textContent = error.message;
  } finally {
    input.value = "";
  }
}

async function connectFieldNetwork() {
  const settings = readSettingsForm();
  const resultEl = $("#connection-test-result");
  if (settings.transport !== "field_network") {
    resultEl.className = "test-result error";
    resultEl.textContent = "Field Network モードで実行してください。";
    return null;
  }
  if (!settings.host) {
    resultEl.className = "test-result error";
    resultEl.textContent = "装置 IP を入力してください。";
    return null;
  }
  resultEl.className = "test-result";
  resultEl.textContent = "EtherNet/IP 接続中…";
  try {
    const response = await fetch("/api/field-network/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "接続できません");
    resultEl.className = "test-result success";
    resultEl.textContent = data.message || "接続しました";
    markConnectionVerified(true, settings);
    state.settings = settings;
    localStorage.setItem("vtv-settings", JSON.stringify(settings));
    refreshMappedWatchItems();
    renderWatchList();
    refreshConnectionBadge();
    return data;
  } catch (error) {
    resultEl.className = "test-result error";
    resultEl.textContent = error.message;
    markConnectionVerified(false, settings);
    refreshConnectionBadge();
    return null;
  }
}

function updateBusyAddressHint() {
  const hint = $("#busy-address-hint");
  if (!hint) return;
  const plo = Number($("#plo-address").value) || 0;
  const portCount = Number($("#plo-port-count")?.value) || 32;
  const port = Number($("#busy-port").value) || 1;
  const busy = plo + port - 1;
  hint.textContent = `BUSY 実アドレス: M${busy}（PLO先頭 M${plo} + Port ${port} - 1 / ポート数 ${portCount}）。`
    + "VTV の「ステータス信号」割付と一致させてください。";
}

function syncResultDataUi() {
  const notifyOn = $("#notify-area-enabled")?.checked;
  // 結果データアドレスは常に編集可（監視一覧は常時この値を参照）
  $("#result-data-address").disabled = false;
  $("#result-data-size").disabled = false;
  $("#result-data-watch-words").disabled = false;
  $("#notify-address").disabled = !notifyOn;
}

function settingsKey(settings) {
  return [
    settings.transport || "tcp",
    settings.host,
    settings.port,
    settings.command_address,
    settings.response_address,
    settings.plo_address ?? settings.busy_address,
    settings.plo_port_count ?? 32,
    settings.busy_port ?? 1,
    settings.result_data_enabled ? 1 : 0,
    settings.result_data_address ?? 512,
    settings.result_data_size ?? 2048,
    settings.result_data_watch_words ?? 64,
    settings.result_data_decimals ?? 3,
    settings.notify_area_enabled ? 1 : 0,
    settings.notify_address ?? 2560,
    settings.fn_input_size ?? 612,
    settings.fn_output_size ?? 132,
    settings.fn_rpi_us ?? 10000,
    settings.fn_esi_ports ?? 0,
    settings.fn_eso_ports ?? 0,
    settings.fn_connection_path || "",
  ].join(":");
}

function markConnectionVerified(verified, settings) {
  state.connectionVerified = verified;
  state.verifiedSettingsKey = verified ? settingsKey(settings) : "";
  localStorage.setItem(
    "vtv-connection-verified",
    JSON.stringify({
      verified,
      key: state.verifiedSettingsKey,
    })
  );
}

function restoreConnectionState() {
  try {
    const saved = JSON.parse(localStorage.getItem("vtv-connection-verified"));
    const key = settingsKey(state.settings);
    if (saved?.verified && saved?.key === key && state.settings.host) {
      state.connectionVerified = true;
      state.verifiedSettingsKey = key;
      setConnection("connected");
    }
  } catch (_) {}
}

function refreshConnectionBadge() {
  if (state.running) return;
  const settingsMatch =
    state.connectionVerified
    && state.verifiedSettingsKey === settingsKey(state.settings);
  if (state.settings.transport === "plclink") {
    // PLCLINK は実際の VTV TCP 接続数を優先する。
    if (state.softPlcClientCount > 0) {
      setConnection("connected");
      return;
    }
    if (settingsMatch) {
      setConnection("connecting");
      return;
    }
    setConnection("disconnected");
    return;
  }
  if (state.settings.transport === "field_network") {
    if (settingsMatch) {
      setConnection("connected");
      return;
    }
    setConnection("disconnected");
    return;
  }
  if (settingsMatch) {
    setConnection("connected");
    return;
  }
  setConnection("disconnected");
}

function startSoftPlcStatusPoll() {
  if (state.softPlcPollTimer) return;
  state.softPlcPollTimer = setInterval(() => {
    pollSoftPlcStatus();
  }, 1500);
  pollSoftPlcStatus();
}

async function pollSoftPlcStatus() {
  if (state.settings.transport !== "plclink" || state.running) return;
  try {
    const response = await fetch("/api/plclink/status");
    if (!response.ok) return;
    const data = await response.json();
    state.softPlcClientCount = Number(data.client_count) || 0;
    refreshConnectionBadge();
  } catch (_) {}
}

async function startSoftPlc({ updateBadge = true } = {}) {
  const settings = readSettingsForm();
  const resultEl = $("#connection-test-result");
  if (settings.transport !== "plclink") {
    resultEl.className = "test-result error";
    resultEl.textContent = "PLCLINK モードで実行してください。";
    return null;
  }
  if (!settings.host) {
    resultEl.className = "test-result error";
    resultEl.textContent = "待受アドレスを入力してください。";
    return null;
  }
  resultEl.className = "test-result";
  resultEl.textContent = "疑似 PLC を起動しています…";
  try {
    const response = await fetch("/api/plclink/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "待受を開始できません");
    const targets = (data.connect_targets || []).join(" / ") || data.preferred_target;
    resultEl.className = "test-result success";
    resultEl.textContent =
      `${data.message || "待受を開始しました。"}\n`
      + `VTV に設定する接続先: ${targets}`;
    if (updateBadge) {
      state.softPlcClientCount = Number(data.client_count) || 0;
      const live = state.softPlcClientCount > 0;
      if (live) {
        markConnectionVerified(true, settings);
      }
      refreshConnectionBadge();
    }
    return data;
  } catch (error) {
    resultEl.className = "test-result error";
    resultEl.textContent = error.message;
    return null;
  }
}

async function verifyConnectionSettings({ showMessage = false, resultEl = null } = {}) {
  const settings = readSettingsForm();
  if (!settings.host) {
    markConnectionVerified(false, settings);
    refreshConnectionBadge();
    if (showMessage && resultEl) {
      resultEl.className = "test-result error";
      resultEl.textContent = settings.transport === "plclink"
        ? "待受アドレスを入力してください。"
        : "装置 IP を入力してください。";
    }
    return false;
  }
  if (settings.transport === "plclink") {
    const started = await startSoftPlc({ updateBadge: false });
    if (!started) return false;
    if (showMessage && resultEl) {
      resultEl.className = "test-result";
      resultEl.textContent =
        `${resultEl.textContent}\nVTV からの接続・MC 3E 通信を待っています…`;
    }
  } else if (showMessage && resultEl) {
    resultEl.className = "test-result";
    resultEl.textContent = "接続しています…";
  }
  setConnection("connecting");
  try {
    const response = await fetch("/api/test-connection", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "接続できません");
    markConnectionVerified(true, settings);
    state.settings = settings;
    localStorage.setItem("vtv-settings", JSON.stringify(settings));
    refreshMappedWatchItems();
    renderWatchList();
    setConnection("connected");
    if (showMessage && resultEl) {
      resultEl.className = "test-result success";
      resultEl.textContent = data.message || "接続に成功しました。";
    }
    return true;
  } catch (error) {
    markConnectionVerified(false, settings);
    refreshConnectionBadge();
    if (showMessage && resultEl) {
      resultEl.className = "test-result error";
      resultEl.textContent = error.message;
    }
    return false;
  }
}

async function testConnection() {
  await verifyConnectionSettings({
    showMessage: true,
    resultEl: $("#connection-test-result"),
  });
}

function runSequence() {
  state.settings = readSettingsForm();
  if (!state.settings.host) {
    openSettingsDialog();
    $("#connection-test-result").className = "test-result error";
    $("#connection-test-result").textContent = state.settings.transport === "plclink"
      ? "待受アドレスを入力してください。"
      : "装置 IP を入力してください。";
    return;
  }
  if (!state.steps.length) { alert("実行するカードを追加してください。"); return; }
  if (state.settings.transport === "plclink" || state.settings.transport === "field_network") {
    const unsupported = findUnsupportedPlcLinkCommand(state.steps);
    if (unsupported) {
      alert(`${unsupported.command}: ${unsupported.reason}`);
      return;
    }
  }
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

function findUnsupportedPlcLinkCommand(steps) {
  for (const step of steps) {
    if (step.type === "command") {
      const definition = state.catalog.find((item) => item.code === step.command);
      if (!definition?.plclink_supported) {
        return {
          command: step.command,
          reason: definition?.plclink_reason || "PLCLINKでは使用できません",
        };
      }
    }
    for (const key of ["steps", "then_steps", "else_steps"]) {
      if (step[key]) {
        const nested = findUnsupportedPlcLinkCommand(step[key]);
        if (nested) return nested;
      }
    }
  }
  return null;
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
    if (event.state === "connecting") {
      setConnection("connecting");
      addLog("info", "SYS", `${event.message} に接続中`);
    } else if (event.state === "connected") {
      setConnection("connected");
    } else if (event.state === "disconnected") {
      refreshConnectionBadge();
    }
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
  if (status === "disconnected") stopWatch(true);
}

function setRunning(running) {
  state.running = running;
  $("#run-button").disabled = running;
  $("#stop-button").disabled = !running;
  if (!running) refreshConnectionBadge();
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
