const WATCH_INTERVAL_MIN_MS = 1;
const WATCH_INTERVAL_MAX_MS = 10_000;
const WATCH_INTERVAL_DEFAULT_MS = 500;

const DEFAULT_FN_STATUS_SIGNALS = [
  { id: "auto", label: "自動運転中", source: "status", bit: 0, eso_port: null, plo_port: null, role: "auto" },
  { id: "busy", label: "BUSY", source: "status", bit: 1, eso_port: null, plo_port: null, role: "busy" },
  { id: "result_valid", label: "結果信号有効", source: "status", bit: 2, eso_port: null, plo_port: null, role: "result_valid" },
  { id: "error", label: "エラー", source: "status", bit: 3, eso_port: null, plo_port: null, role: "error" },
];

function defaultPlcLinkStatusSignals(busyPort = 1) {
  const port = Math.max(1, Math.min(256, Number(busyPort) || 1));
  return [
    { id: "busy", label: "BUSY", source: "plo", bit: null, eso_port: null, plo_port: port, role: "busy" },
  ];
}

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
    pli_address: 0, pli_port_count: 32,
    plo_address: 1024, plo_port_count: 32, busy_port: 1, byte_order: "high_low",
    result_data_enabled: false, result_data_address: 512, result_data_size: 2048,
    result_data_watch_words: 64, result_data_decimals: 3,
    notify_area_enabled: false, notify_address: 2560,
    fn_esi_ports: 32, fn_eso_ports: 32,
    fn_input_size: 612, fn_output_size: 136, fn_rpi_us: 10000,
    fn_connection_path: "20 04 24 01 2C 14 2C 0A",
    fn_o_to_t_header_bytes: 4, fn_eds_name: "",
    fn_status_signals: DEFAULT_FN_STATUS_SIGNALS.map((item) => ({ ...item })),
    plclink_status_signals: defaultPlcLinkStatusSignals(1),
    pli_port_names: {},
    plo_port_names: {},
    esi_port_names: {},
    eso_port_names: {},
  },
  statusSignalDraft: DEFAULT_FN_STATUS_SIGNALS.map((item) => ({ ...item })),
  plclinkStatusSignalDraft: defaultPlcLinkStatusSignals(1),
  portNameDraft: {
    pli: {},
    plo: {},
    esi: {},
    eso: {},
  },
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
  watchRequestItems: [],
  watchValues: {},
  watchRunning: false,
  watchTimer: null,
  watchSocket: null,
  watchMode: "http", // "websocket" | "http"
  watchIntervalMs: WATCH_INTERVAL_DEFAULT_MS,
  watchLastCycleAt: 0,
  watchActualMs: null,
  watchFetchMs: null,
  timingDrawQueued: false,
  timingInfoLastAt: 0,
  watchPeriodLastAt: 0,
  timingSelectedIds: [],
  timingNeedsDefaultChannels: true,
  timingSamples: [],
  timingSampleSeq: 0,
  /** サーバ時刻 → performance.now 系への原点 { serverMs, localMs } */
  timingTimeOrigin: null,
  timingAxisMode: "poll", // "time" | "poll"
  timingShowScale: true,
  timingWindowMs: 5000,
  timingPanMs: 0,
  timingWindowPolls: 500,
  timingPanPolls: 0,
  timingZoomMinMs: 20,
  timingZoomMaxMs: 60000,
  timingZoomMinPolls: 20,
  timingZoomMaxPolls: 20000,
  timingMaxSamples: 60000,
  timingColors: ["#3dd6c6", "#6ea8fe", "#f0b429", "#f07178", "#c3a6ff", "#7ddea2", "#ff9f68", "#8fd3ff"],
  timingCursorA: null,
  timingCursorB: null,
  timingPulse: null,
  timingChartGeom: null,
  timingPointer: null,
  softPlcPollTimer: null,
  softPlcClientCount: 0,
  softPlcListening: false,
  softPlcPort: 0,
  fnLive: false,
  fnLiveHost: "",
  fnLivePort: 0,
  connectionStatus: "disconnected",
  settingsPage: "connection",
  draftReady: false,
  draftTimer: null,
  undoAction: null,
  undoTimer: null,
  sequenceName: "",
  sequenceLibraryId: "",
  favorites: [],
  foldUnsupported: true,
  logFilter: "all",
  watchQuery: "",
  watchChangedOnly: false,
  watchChangedIds: new Set(),
  lastResponse: "",
  runStartedAt: 0,
  runPositionText: "",
  appVersion: "",
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
  restoreTimingPreferences();
  restoreLayoutMode();
  applySettingsToForm();
  applyWatchIntervalToForm();
  applyTimingPreferencesToForm();
  refreshMappedWatchItems();
  const response = await fetch("/api/catalog");
  state.catalog = await response.json();
  $("#catalog-count").textContent = state.catalog.length;
  restoreSequenceDraft();
  restoreWorkshop();
  renderPalette();
  renderSequence();
  renderWatchList();
  renderTimingChannelList();
  bindEvents();
  bindWorkshopEvents();
  startSoftPlcStatusPoll();
  void loadAppVersion();
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
  $("#pli-address")?.addEventListener("input", updateVirtualIoRange);
  $("#pli-port-count")?.addEventListener("input", () => {
    updateVirtualIoRange();
    renderPortNameTables();
  });
  $("#plo-port-count").addEventListener("input", () => {
    updateBusyAddressHint();
    renderPlcLinkStatusSignalTable();
    renderPortNameTables();
  });
  ["pli-address", "pli-port-count", "plo-address", "plo-port-count"].forEach((id) => {
    $(`#${id}`)?.addEventListener("change", () => {
      refreshMappedWatchItems();
      renderWatchList();
      renderTimingChannelList();
    });
  });
  $("#busy-port").addEventListener("input", updateBusyAddressHint);
  $("#result-data-enabled").addEventListener("change", () => {
    syncResultDataUi();
    refreshMappedWatchItems();
    renderWatchList();
    renderTimingChannelList();
  });
  $("#notify-area-enabled").addEventListener("change", () => {
    syncResultDataUi();
    refreshMappedWatchItems();
    renderWatchList();
    renderTimingChannelList();
  });
  ["result-data-address", "result-data-size", "result-data-watch-words", "notify-address"].forEach((id) => {
    $(`#${id}`)?.addEventListener("change", () => {
      refreshMappedWatchItems();
      renderWatchList();
      renderTimingChannelList();
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
  $("#command-watch-words")?.addEventListener("change", onAreaWatchWordsChanged);
  $("#response-watch-words")?.addEventListener("change", onAreaWatchWordsChanged);
  ["command-size", "response-size", "fn-command-size", "fn-response-size"].forEach((id) => {
    $(`#${id}`)?.addEventListener("change", () => {
      refreshMappedWatchItems();
      renderWatchList();
      renderTimingChannelList();
    });
  });
  $("#test-button").addEventListener("click", testConnection);
  $("#start-softplc-button")?.addEventListener("click", startSoftPlc);
  $("#fn-connect-button")?.addEventListener("click", connectFieldNetwork);
  $("#eds-import-input")?.addEventListener("change", onEdsImport);
  ["fn-esi-ports", "fn-eso-ports", "fn-command-size", "fn-response-size", "fn-result-size",
    "fn-input-size", "fn-output-size", "fn-result-watch-words"].forEach((id) => {
    $(`#${id}`)?.addEventListener("change", () => {
      updateFnLayoutHint();
      if (id === "fn-eso-ports") renderStatusSignalTable();
      if (id === "fn-esi-ports" || id === "fn-eso-ports") renderPortNameTables();
      refreshMappedWatchItems();
      renderWatchList();
      renderTimingChannelList();
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
      plo_port: null,
      role: "none",
    });
    renderStatusSignalTable();
    refreshMappedWatchItems();
    renderWatchList();
    renderTimingChannelList();
  });
  $("#fn-status-reset")?.addEventListener("click", () => {
    state.statusSignalDraft = DEFAULT_FN_STATUS_SIGNALS.map((item) => ({ ...item }));
    renderStatusSignalTable();
    refreshMappedWatchItems();
    renderWatchList();
    renderTimingChannelList();
  });
  $("#fn-status-signal-body")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-status-delete]");
    if (!button || button.disabled) return;
    const index = Number(button.dataset.statusDelete);
    syncStatusSignalDraftFromDom();
    if (!Number.isFinite(index) || state.statusSignalDraft.length <= 1) return;
    state.statusSignalDraft.splice(index, 1);
    state.statusSignalDraft = ensureExactlyOneBusy(state.statusSignalDraft);
    renderStatusSignalTable();
    refreshMappedWatchItems();
    renderWatchList();
    renderTimingChannelList();
  });
  $("#fn-status-signal-body")?.addEventListener("change", (event) => {
    const row = event.target.closest("tr[data-status-index]");
    if (!row) return;
    const index = Number(row.dataset.statusIndex);
    const prevId = state.statusSignalDraft[index]?.id;
    const roleValue = event.target.dataset.field === "role" ? event.target.value : null;
    syncStatusSignalDraftFromDom();
    state.statusSignalDraft = ensureExactlyOneBusy(
      state.statusSignalDraft,
      roleValue === "busy" ? prevId : null,
    );
    renderStatusSignalTable();
    refreshMappedWatchItems();
    renderWatchList();
    renderTimingChannelList();
  });
  $("#plclink-status-add")?.addEventListener("click", () => {
    syncPlcLinkStatusSignalDraftFromDom();
    const used = new Set(
      state.plclinkStatusSignalDraft.map((item) => Number(item.plo_port) || 0),
    );
    let nextPort = 1;
    const maxPort = Math.max(1, Number($("#plo-port-count")?.value) || 32);
    while (used.has(nextPort) && nextPort <= maxPort) nextPort += 1;
    state.plclinkStatusSignalDraft.push({
      id: `custom-${state.statusSignalSeq++}`,
      label: "カスタム信号",
      source: "plo",
      bit: null,
      eso_port: null,
      plo_port: Math.min(nextPort, maxPort),
      role: "none",
    });
    renderPlcLinkStatusSignalTable();
    updateBusyAddressHint();
    refreshMappedWatchItems();
    renderWatchList();
    renderTimingChannelList();
  });
  $("#plclink-status-reset")?.addEventListener("click", () => {
    const busyPort = Number($("#busy-port")?.value) || 1;
    state.plclinkStatusSignalDraft = defaultPlcLinkStatusSignals(busyPort);
    renderPlcLinkStatusSignalTable();
    updateBusyAddressHint();
    refreshMappedWatchItems();
    renderWatchList();
    renderTimingChannelList();
  });
  $("#plclink-status-signal-body")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-plclink-status-delete]");
    if (!button || button.disabled) return;
    const index = Number(button.dataset.plclinkStatusDelete);
    syncPlcLinkStatusSignalDraftFromDom();
    if (!Number.isFinite(index) || state.plclinkStatusSignalDraft.length <= 1) return;
    state.plclinkStatusSignalDraft.splice(index, 1);
    state.plclinkStatusSignalDraft = ensureExactlyOneBusy(state.plclinkStatusSignalDraft);
    renderPlcLinkStatusSignalTable();
    updateBusyAddressHint();
    refreshMappedWatchItems();
    renderWatchList();
    renderTimingChannelList();
  });
  $("#plclink-status-signal-body")?.addEventListener("change", (event) => {
    const row = event.target.closest("tr[data-plclink-status-index]");
    if (!row) return;
    const index = Number(row.dataset.plclinkStatusIndex);
    const prevId = state.plclinkStatusSignalDraft[index]?.id;
    const roleValue = event.target.dataset.field === "role" ? event.target.value : null;
    syncPlcLinkStatusSignalDraftFromDom();
    state.plclinkStatusSignalDraft = ensureExactlyOneBusy(
      state.plclinkStatusSignalDraft,
      roleValue === "busy" ? prevId : null,
    );
    renderPlcLinkStatusSignalTable();
    updateBusyAddressHint();
    refreshMappedWatchItems();
    renderWatchList();
    renderTimingChannelList();
  });
  for (const id of ["header-timeout", "timeout"]) {
    $(`#${id}`)?.addEventListener("change", onTimeoutChanged);
  }
  $("#run-button").addEventListener("click", runSequence);
  $("#local-io-on")?.addEventListener("click", () => setLocalIoPorts(1));
  $("#local-io-off")?.addEventListener("click", () => setLocalIoPorts(0));
  $("#stop-button").addEventListener("click", stopSequence);
  $("#clear-button").addEventListener("click", () => {
    if (state.running || !state.steps.length) return;
    if (!confirm("すべてのカードを削除しますか？")) return;
    const snapshot = cloneData(state.steps);
    const nextId = state.nextId;
    state.steps = [];
    renderSequence();
    showToast("シーケンスをクリアしました", () => {
      state.steps = snapshot;
      state.nextId = nextId;
      renderSequence();
    });
  });
  $("#clear-log-button").addEventListener("click", () => clearLog());
  $("#undo-toast-button")?.addEventListener("click", () => {
    const action = state.undoAction;
    hideToast();
    action?.();
  });
  $("#empty-open-settings")?.addEventListener("click", () => {
    openSettingsDialog();
    selectSettingsPage("connection");
  });
  document.querySelectorAll("[data-settings-tab]").forEach((button) => {
    button.addEventListener("click", () => selectSettingsPage(button.dataset.settingsTab));
  });
  window.addEventListener("beforeunload", () => {
    if (state.draftReady) persistSequenceDraft();
  });
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
    renderTimingChannelList();
    setWatchStatus("一覧を再生成しました");
  });
  $("#start-watch-button").addEventListener("click", startWatch);
  $("#stop-watch-button").addEventListener("click", () => stopWatch(false));
  $("#start-timing-button")?.addEventListener("click", startWatch);
  $("#stop-timing-button")?.addEventListener("click", () => stopWatch(false));
  $("#timing-clear-button")?.addEventListener("click", clearTimingSamples);
  $("#timing-measure-clear-button")?.addEventListener("click", clearTimingMeasure);
  $("#timing-zoom-in-button")?.addEventListener("click", () => zoomTimingWindow(0.7));
  $("#timing-zoom-out-button")?.addEventListener("click", () => zoomTimingWindow(1.4));
  $("#timing-zoom-reset-button")?.addEventListener("click", resetTimingView);
  $("#timing-window-ms")?.addEventListener("change", () => {
    state.timingWindowMs = clampTimingWindowMs(Number($("#timing-window-ms").value) || 5000);
    state.timingPanMs = 0;
    localStorage.setItem("vtv-timing-window-ms", String(state.timingWindowMs));
    syncTimingWindowSelect();
    updateTimingViewSpan();
    drawTimingChart();
  });
  $("#timing-window-polls")?.addEventListener("change", () => {
    state.timingWindowPolls = clampTimingWindowPolls(Number($("#timing-window-polls").value) || 500);
    state.timingPanPolls = 0;
    localStorage.setItem("vtv-timing-window-polls", String(state.timingWindowPolls));
    syncTimingWindowSelect();
    updateTimingViewSpan();
    drawTimingChart();
  });
  $("#timing-axis-mode")?.addEventListener("change", () => {
    const nextMode = $("#timing-axis-mode").value === "time" ? "time" : "poll";
    preserveTimingViewAcrossAxisMode(nextMode);
    state.timingAxisMode = nextMode;
    localStorage.setItem("vtv-timing-axis-mode", state.timingAxisMode);
    syncTimingAxisModeUi();
    syncTimingWindowSelect();
    updateTimingViewSpan();
    updateTimingMeasureInfo();
    drawTimingChart();
  });
  $("#timing-show-scale")?.addEventListener("change", () => {
    state.timingShowScale = !!$("#timing-show-scale").checked;
    localStorage.setItem("vtv-timing-show-scale", state.timingShowScale ? "1" : "0");
    drawTimingChart();
  });
  $("#timing-channel-list")?.addEventListener("change", (event) => {
    const input = event.target.closest('input[type="checkbox"][data-timing-id]');
    if (!input) return;
    const id = input.dataset.timingId;
    const selected = new Set(state.timingSelectedIds);
    if (input.checked) selected.add(id);
    else selected.delete(id);
    state.timingSelectedIds = [...selected];
    state.timingNeedsDefaultChannels = false;
    localStorage.setItem("vtv-timing-channels", JSON.stringify(state.timingSelectedIds));
    drawTimingChart();
  });
  bindTimingChartInteractions();
  window.addEventListener("resize", () => {
    if (!$("#monitor-timing-panel")?.classList.contains("hidden")) {
      drawTimingChart();
    }
  });
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

function restoreTimingPreferences() {
  try {
    const raw = localStorage.getItem("vtv-timing-channels");
    if (raw == null) {
      state.timingNeedsDefaultChannels = true;
    } else {
      const channels = JSON.parse(raw);
      if (Array.isArray(channels)) {
        state.timingSelectedIds = channels.filter((id) => typeof id === "string");
        state.timingNeedsDefaultChannels = false;
      }
    }
  } catch (_) {}
  try {
    const windowMs = Number(localStorage.getItem("vtv-timing-window-ms"));
    if (Number.isFinite(windowMs)) {
      state.timingWindowMs = clampTimingWindowMs(windowMs);
    }
  } catch (_) {}
  try {
    const windowPolls = Number(localStorage.getItem("vtv-timing-window-polls"));
    if (Number.isFinite(windowPolls)) {
      state.timingWindowPolls = clampTimingWindowPolls(windowPolls);
    }
  } catch (_) {}
  try {
    const mode = localStorage.getItem("vtv-timing-axis-mode");
    if (mode === "time" || mode === "poll") state.timingAxisMode = mode;
  } catch (_) {}
  try {
    const show = localStorage.getItem("vtv-timing-show-scale");
    if (show === "0" || show === "1") state.timingShowScale = show === "1";
  } catch (_) {}
}

function applyTimingPreferencesToForm() {
  if ($("#timing-axis-mode")) $("#timing-axis-mode").value = state.timingAxisMode;
  if ($("#timing-show-scale")) $("#timing-show-scale").checked = !!state.timingShowScale;
  syncTimingAxisModeUi();
  syncTimingWindowSelect();
  updateTimingViewSpan();
  updateTimingMeasureInfo();
}

function clampTimingWindowMs(value) {
  if (!Number.isFinite(value)) return 5000;
  return Math.min(state.timingZoomMaxMs, Math.max(state.timingZoomMinMs, value));
}

function clampTimingWindowPolls(value) {
  if (!Number.isFinite(value)) return 500;
  return Math.min(
    state.timingZoomMaxPolls,
    Math.max(state.timingZoomMinPolls, Math.round(value)),
  );
}

function syncTimingAxisModeUi() {
  const isPoll = state.timingAxisMode === "poll";
  $("#timing-window-ms")?.classList.toggle("hidden", isPoll);
  $("#timing-window-polls")?.classList.toggle("hidden", !isPoll);
  const hint = $("#timing-measure-info");
  if (hint && !state.timingCursorA && !state.timingPulse) {
    hint.textContent = isPoll
      ? "横軸は実時間線形。目盛りは各 poll の実時刻位置（周期がぶれると間隔が変化）。"
      : "横軸・目盛りとも実時間（等間隔）。poll ごとのばらつき確認には「ポーリング回数」軸を推奨。";
  }
}

function syncNearestSelectValue(select, target) {
  if (!select) return;
  const value = String(Math.round(target));
  const options = [...select.options].map((opt) => opt.value);
  if (options.includes(value)) {
    select.value = value;
    return;
  }
  let best = options[0];
  let bestDiff = Infinity;
  for (const opt of options) {
    const diff = Math.abs(Number(opt) - target);
    if (diff < bestDiff) {
      bestDiff = diff;
      best = opt;
    }
  }
  select.value = best;
}

function syncTimingWindowSelect() {
  syncNearestSelectValue($("#timing-window-ms"), state.timingWindowMs);
  syncNearestSelectValue($("#timing-window-polls"), state.timingWindowPolls);
}

function updateTimingViewSpan() {
  const el = $("#timing-view-span");
  if (!el) return;
  if (state.timingAxisMode === "poll") {
    const live = state.timingPanPolls <= 0;
    const range = timingViewRange();
    const timeSpan = timingVisibleTimeSpan(range.start, range.end);
    const approx = timeSpan && timeSpan.spanMs > 0
      ? ` ≈ ${formatTimingDuration(timeSpan.spanMs)}`
      : "";
    el.textContent = live
      ? `表示 ${state.timingWindowPolls} poll${approx}`
      : `表示 ${state.timingWindowPolls} poll${approx}（過去）`;
    return;
  }
  const ms = state.timingWindowMs;
  const live = state.timingPanMs <= 0.5;
  const span = ms >= 1000 ? `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)} s` : `${Math.round(ms)} ms`;
  el.textContent = live ? `表示 ${span}` : `表示 ${span}（過去）`;
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
  if (state.watchRunning && state.watchMode === "websocket") {
    startWatchSocket();
  }
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
  state.watchPeriodLastAt = 0;
  state.timingTimeOrigin = null;
  updateWatchActualPeriodDisplay();
}

/**
 * 監視サンプルの横軸時刻。
 * WebSocket はサーバの mono_ms（なければ t）を優先し、performance.now 系に線形写像する。
 * 受信時刻に依存しないため、ブラウザ側の処理遅れで間隔が潰れるのを防ぐ。
 */
function resolveWatchSampleTime(message) {
  const localNow = performance.now();
  if (!message || typeof message !== "object") return localNow;
  const serverMs = Number(
    Number.isFinite(Number(message.mono_ms)) ? message.mono_ms : message.t,
  );
  if (!Number.isFinite(serverMs)) return localNow;
  if (!state.timingTimeOrigin) {
    state.timingTimeOrigin = { serverMs, localMs: localNow };
  }
  return state.timingTimeOrigin.localMs + (serverMs - state.timingTimeOrigin.serverMs);
}

function formatWatchActualPeriodText() {
  if (!state.watchRunning || state.watchActualMs == null) return "実測 —";
  const cycle = state.watchActualMs < 10
    ? state.watchActualMs.toFixed(1)
    : String(Math.max(1, Math.round(state.watchActualMs)));
  const fetchMs = state.watchFetchMs == null
    ? null
    : (state.watchFetchMs < 10
      ? state.watchFetchMs.toFixed(2)
      : String(Math.max(0, Math.round(state.watchFetchMs))));
  const mode = state.watchMode === "websocket" ? "読取" : "取得";
  return fetchMs == null
    ? `実測 ${cycle} ms`
    : `実測 ${cycle} ms（${mode} ${fetchMs} ms）`;
}

function updateWatchActualPeriodDisplay() {
  const text = formatWatchActualPeriodText();
  const watchEl = $("#watch-actual-period");
  if (watchEl) watchEl.textContent = text;
  const timingEl = $("#timing-actual-period");
  if (timingEl) timingEl.textContent = text;
}

function rebuildWatchRequestItems() {
  state.watchRequestItems = state.watchItems.map(
    ({ id, device, address, format, length, decimals }) => ({
      id,
      device,
      address,
      format,
      length: length ?? 8,
      decimals: decimals ?? 3,
    }),
  );
}

function updateWatchNote() {
  const note = $("#watch-note");
  if (!note) return;
  const transport = $("#transport")?.value || state.settings.transport;
  if (transport === "plclink") {
    note.textContent =
      `接続設定のコマンド／レスポンス／PLO／PLI から自動生成。`
      + `コマンド表示とレスポンス表示で、見るワード数を変えられます。`
      + `更新周期 ${readWatchIntervalMs()} ms。`
      + `高速監視は WebSocket 配信（目標 1 ms）。項目数を減らすほど安定します。`;
    return;
  }
  if (transport === "field_network") {
    note.textContent =
      `「結果データ」は VTV と同じく「出力値」(生DWORD) と「データ」(解釈値) を表示します。`
      + `更新周期 ${readWatchIntervalMs()} ms（WebSocket）。`
      + `I/O の鮮度は RPI が上限です。1 ms 分解能を狙う場合は RPI=1000μs も試せます。`;
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
  // 拡大時は監視 / タイミングを全幅優先（ログは通常画面のタブで確認）
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
  if (focused && watchEnabled) {
    const active = document.querySelector("[data-monitor-tab].active")?.dataset?.monitorTab;
    selectMonitorTab(active === "timing" ? "timing" : "watch");
  }
  if (focused) {
    requestAnimationFrame(() => {
      if (!$("#monitor-timing-panel")?.classList.contains("hidden")) drawTimingChart();
    });
  }
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
  if ((tab === "watch" || tab === "timing") && $("#watch-tab-button").disabled) return;
  document.querySelectorAll("[data-monitor-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.monitorTab === tab);
  });
  $("#monitor-log-panel").classList.toggle("hidden", tab !== "log");
  $("#monitor-watch-panel").classList.toggle("hidden", tab !== "watch");
  $("#monitor-timing-panel")?.classList.toggle("hidden", tab !== "timing");
  if (tab === "timing") {
    renderTimingChannelList();
    requestAnimationFrame(() => drawTimingChart());
  }
}

function buildMappedWatchItems(settings) {
  if (settings.transport === "field_network") {
    return buildFnMappedWatchItems(settings);
  }
  const command = Number(settings.command_address) || 0;
  const response = Number(settings.response_address) || 0;
  const plo = Number(settings.plo_address) || 0;
  const pli = Number(settings.pli_address) || 0;
  const portCount = Math.max(1, Number(settings.plo_port_count) || 32);
  const pliCount = Math.max(1, Number(settings.pli_port_count) || 32);
  const busyPort = Number(settings.busy_port) || 1;
  const items = [
    { id: "cmd-trigger", label: "トリガ (+0000)", group: "コマンド領域", device: "D", address: command, format: "int32", relAddress: 0 },
    { id: "cmd-code", label: "コマンドコード (+0002)", group: "コマンド領域", device: "D", address: command + 2, format: "int32", relAddress: 2 },
  ];
  appendDwordSpan(items, {
    idPrefix: "cmd-data", group: "コマンド領域", device: "D", base: command,
    start: 4, stop: areaWatchWords("command", settings), labelWidth: 4,
  });
  items.push(
    { id: "rsp-result", label: "実行結果 (+0000)", group: "レスポンス領域", device: "D", address: response, format: "int32", relAddress: 0 },
    { id: "rsp-error", label: "エラーコード (+0002)", group: "レスポンス領域", device: "D", address: response + 2, format: "int32", relAddress: 2 },
    { id: "rsp-echo", label: "コマンドエコー (+0004)", group: "レスポンス領域", device: "D", address: response + 4, format: "int32", relAddress: 4 },
    { id: "rsp-param-size", label: "パラメータ総サイズ (+0006)", group: "レスポンス領域", device: "D", address: response + 6, format: "int32", relAddress: 6 },
  );
  appendDwordSpan(items, {
    idPrefix: "rsp-data", group: "レスポンス領域", device: "D", base: response,
    start: 8, stop: areaWatchWords("response", settings), labelWidth: 4,
  });
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
  // ステータス割付は PLO 一覧のラベルに反映（同一ポートの二重表示を避ける）
  // PLO を PLI より上に出す（出力を先、入力を後）
  const statusSignals = normalizePlcLinkStatusSignals(
    settings.plclink_status_signals,
    busyPort,
  );
  const portLabels = {};
  for (const signal of statusSignals) {
    const port = Number(signal.plo_port) || 1;
    if (portLabels[port] && signal.role !== "busy") continue;
    portLabels[port] = `${signal.label} (Port ${port})`;
  }
  const ploNames = normalizePortNames(settings.plo_port_names);
  for (let port = 1; port <= portCount; port += 1) {
    const custom = portDisplayLabel(port, ploNames, `Port ${port}`);
    items.push({
      id: `plo-port-${port}`,
      label: custom !== `Port ${port}` ? custom : (portLabels[port] || `Port ${port}`),
      group: "PLO出力",
      device: "M",
      address: plo + port - 1,
      format: "bit",
      busy: port === busyPort,
    });
  }
  const pliNames = normalizePortNames(settings.pli_port_names);
  for (let port = 1; port <= pliCount; port += 1) {
    items.push({
      id: `pli-port-${port}`,
      label: portDisplayLabel(port, pliNames, `PLI-${port}`),
      group: "PLI入力",
      device: "M",
      address: pli + port - 1,
      format: "bit",
    });
  }
  return items;
}

function normalizePortNames(raw) {
  if (!raw || typeof raw !== "object") return {};
  const result = {};
  for (const [key, value] of Object.entries(raw)) {
    const port = Number(key);
    if (!Number.isFinite(port) || port < 1 || port > 256) continue;
    const text = String(value || "").trim().slice(0, 40);
    if (text) result[String(port)] = text;
  }
  return result;
}

function portDisplayLabel(port, names, fallback) {
  const custom = (names && names[String(port)]) ? String(names[String(port)]).trim() : "";
  if (custom) return `${fallback}: ${custom}`;
  return fallback;
}

function syncPortNameDraftFromSettings(settings = state.settings) {
  state.portNameDraft = {
    pli: normalizePortNames(settings.pli_port_names),
    plo: normalizePortNames(settings.plo_port_names),
    esi: normalizePortNames(settings.esi_port_names),
    eso: normalizePortNames(settings.eso_port_names),
  };
}

function capturePortNameDraftFromForm() {
  for (const kind of ["pli", "plo", "esi", "eso"]) {
    const body = $(`#${kind}-port-name-body`);
    if (!body) continue;
    const names = {};
    body.querySelectorAll("tr[data-port]").forEach((row) => {
      const port = row.dataset.port;
      const value = row.querySelector("input")?.value?.trim() || "";
      if (value) names[port] = value.slice(0, 40);
    });
    state.portNameDraft[kind] = names;
  }
}

function renderPortNameTables({ capture = true } = {}) {
  if (capture) capturePortNameDraftFromForm();
  const pliCount = Math.max(1, Number($("#pli-port-count")?.value) || Number(state.settings.pli_port_count) || 32);
  const ploCount = Math.max(1, Number($("#plo-port-count")?.value) || Number(state.settings.plo_port_count) || 32);
  const esiCount = Number($("#fn-esi-ports")?.value ?? state.settings.fn_esi_ports) || 0;
  const esoCount = Number($("#fn-eso-ports")?.value ?? state.settings.fn_eso_ports) || 0;
  renderPortNameTable("pli", pliCount);
  renderPortNameTable("plo", ploCount);
  renderPortNameTable("esi", esiCount);
  renderPortNameTable("eso", esoCount);
}

function renderPortNameTable(kind, count) {
  const body = $(`#${kind}-port-name-body`);
  if (!body) return;
  const names = state.portNameDraft[kind] || {};
  if (!count) {
    body.innerHTML = '<tr><td colspan="2" class="port-name-empty">ポート数 0</td></tr>';
    return;
  }
  const rows = [];
  for (let port = 1; port <= count; port += 1) {
    const value = names[String(port)] || "";
    rows.push(`<tr data-port="${port}">
      <td>${port}</td>
      <td><input type="text" maxlength="40" value="${escapeHtml(value)}" placeholder="名称（任意）" aria-label="${kind.toUpperCase()} ${port} 名称"></td>
    </tr>`);
  }
  body.innerHTML = rows.join("");
  body.querySelectorAll("input").forEach((input) => {
    input.addEventListener("input", () => {
      const row = input.closest("tr[data-port]");
      if (!row) return;
      const port = row.dataset.port;
      const text = input.value.trim().slice(0, 40);
      if (text) state.portNameDraft[kind][port] = text;
      else delete state.portNameDraft[kind][port];
    });
  });
}

function readPortNamesFromForm() {
  capturePortNameDraftFromForm();
  return {
    pli_port_names: { ...(state.portNameDraft.pli || {}) },
    plo_port_names: { ...(state.portNameDraft.plo || {}) },
    esi_port_names: { ...(state.portNameDraft.esi || {}) },
    eso_port_names: { ...(state.portNameDraft.eso || {}) },
  };
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
      plo_port: null,
      role,
    };
  });
}

function normalizePlcLinkStatusSignals(raw, busyPort = 1) {
  const list = Array.isArray(raw) && raw.length
    ? raw
    : defaultPlcLinkStatusSignals(busyPort);
  return list.map((item, index) => {
    const role = ["busy", "auto", "result_valid", "error"].includes(item.role)
      ? item.role
      : "none";
    const port = Number(item.plo_port ?? item.bit ?? busyPort);
    return {
      id: String(item.id || `signal-${index + 1}`).slice(0, 40),
      label: String(item.label || item.id || `信号${index + 1}`).slice(0, 40),
      source: "plo",
      bit: null,
      eso_port: null,
      plo_port: Number.isFinite(port) && port >= 1 ? port : 1,
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

function statusRoleOptionsHtml(signal, signals) {
  const busyCount = signals.filter((item) => item.role === "busy").length;
  const soleBusy = signal.role === "busy" && busyCount === 1;
  const soleSignal = signals.length <= 1;
  const lockBusy = soleBusy || soleSignal;
  const option = (value, label) => {
    const selected = signal.role === value ? " selected" : "";
    // BUSY は必ず 1 つ残す。唯一の BUSY / 唯一の信号からは外さない
    const disabled = lockBusy && value !== "busy" ? " disabled" : "";
    return `<option value="${value}"${selected}${disabled}>${label}</option>`;
  };
  return [
    option("none", "なし"),
    option("busy", "BUSY"),
    option("auto", "自動運転中"),
    option("result_valid", "結果信号有効"),
    option("error", "エラー"),
  ].join("");
}

function ensureExactlyOneBusy(signals, preferredBusyId = null) {
  if (!signals.length) return signals;
  const busyIndexes = signals
    .map((item, index) => (item.role === "busy" ? index : -1))
    .filter((index) => index >= 0);
  if (busyIndexes.length === 0) {
    const preferred = preferredBusyId
      ? signals.findIndex((item) => item.id === preferredBusyId)
      : 0;
    signals[preferred >= 0 ? preferred : 0].role = "busy";
    return signals;
  }
  if (busyIndexes.length > 1) {
    let keep = busyIndexes[0];
    if (preferredBusyId) {
      const preferred = signals.findIndex(
        (item) => item.id === preferredBusyId && item.role === "busy",
      );
      if (preferred >= 0) keep = preferred;
    } else {
      keep = busyIndexes[busyIndexes.length - 1];
    }
    signals.forEach((item, index) => {
      if (index !== keep && item.role === "busy") item.role = "none";
    });
  }
  return signals;
}

function renderStatusSignalTable() {
  const body = $("#fn-status-signal-body");
  if (!body) return;
  state.statusSignalDraft = ensureExactlyOneBusy(
    state.statusSignalDraft.length
      ? state.statusSignalDraft
      : DEFAULT_FN_STATUS_SIGNALS.map((item) => ({ ...item })),
  );
  const rows = state.statusSignalDraft;
  const canDelete = rows.length > 1;
  body.innerHTML = rows.map((signal, index) => {
    const source = signal.source === "eso" ? "eso" : "status";
    const value = source === "eso"
      ? (Number(signal.eso_port) || 1)
      : (Number(signal.bit) || 0);
    const deleteDisabled = canDelete ? "" : " disabled";
    const deleteTitle = canDelete ? "削除" : "BUSY 用に最低 1 信号必要";
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
        <select data-field="role">${statusRoleOptionsHtml(signal, rows)}</select>
      </td>
      <td><button type="button" class="status-signal-delete" data-status-delete="${index}" title="${deleteTitle}"${deleteDisabled}>×</button></td>
    </tr>`;
  }).join("");
}

function renderPlcLinkStatusSignalTable() {
  const body = $("#plclink-status-signal-body");
  if (!body) return;
  state.plclinkStatusSignalDraft = ensureExactlyOneBusy(
    state.plclinkStatusSignalDraft.length
      ? state.plclinkStatusSignalDraft
      : defaultPlcLinkStatusSignals(Number($("#busy-port")?.value) || 1),
  );
  const rows = state.plclinkStatusSignalDraft;
  const maxPort = Math.max(1, Number($("#plo-port-count")?.value) || 32);
  const canDelete = rows.length > 1;
  body.innerHTML = rows.map((signal, index) => {
    const port = Number(signal.plo_port) || 1;
    const deleteDisabled = canDelete ? "" : " disabled";
    const deleteTitle = canDelete ? "削除" : "BUSY 用に最低 1 信号必要";
    return `<tr data-plclink-status-index="${index}">
      <td><input type="text" data-field="label" value="${escapeHtml(signal.label)}" maxlength="40"></td>
      <td><input type="number" data-field="plo-port" min="1" max="${maxPort}" step="1" value="${port}"></td>
      <td>
        <select data-field="role">${statusRoleOptionsHtml(signal, rows)}</select>
      </td>
      <td><button type="button" class="status-signal-delete" data-plclink-status-delete="${index}" title="${deleteTitle}"${deleteDisabled}>×</button></td>
    </tr>`;
  }).join("");
  syncBusyPortFromPlcLinkDraft();
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
      plo_port: null,
      role: ["busy", "auto", "result_valid", "error", "none"].includes(role) ? role : "none",
    });
  });
  state.statusSignalDraft = ensureExactlyOneBusy(next);
}

function syncPlcLinkStatusSignalDraftFromDom() {
  const body = $("#plclink-status-signal-body");
  if (!body) return;
  const next = [];
  const maxPort = Math.max(1, Number($("#plo-port-count")?.value) || 32);
  body.querySelectorAll("tr[data-plclink-status-index]").forEach((row, index) => {
    const prev = state.plclinkStatusSignalDraft[index] || {};
    const label = row.querySelector('[data-field="label"]')?.value?.trim() || `信号${index + 1}`;
    const role = row.querySelector('[data-field="role"]')?.value || "none";
    const rawPort = Number(row.querySelector('[data-field="plo-port"]')?.value);
    const id = prev.id || `custom-${state.statusSignalSeq++}`;
    const port = Number.isFinite(rawPort) && rawPort >= 1 ? Math.min(rawPort, maxPort) : 1;
    next.push({
      id,
      label,
      source: "plo",
      bit: null,
      eso_port: null,
      plo_port: port,
      role: ["busy", "auto", "result_valid", "error", "none"].includes(role) ? role : "none",
    });
  });
  state.plclinkStatusSignalDraft = ensureExactlyOneBusy(next);
  syncBusyPortFromPlcLinkDraft();
}

function syncBusyPortFromPlcLinkDraft() {
  const busy = state.plclinkStatusSignalDraft.find((item) => item.role === "busy");
  if (busy && $("#busy-port")) {
    $("#busy-port").value = String(Number(busy.plo_port) || 1);
  }
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

function readPlcLinkStatusSignalsFromForm() {
  syncPlcLinkStatusSignalDraftFromDom();
  const signals = normalizePlcLinkStatusSignals(
    state.plclinkStatusSignalDraft,
    Number($("#busy-port")?.value) || 1,
  );
  const busyCount = signals.filter((item) => item.role === "busy").length;
  if (busyCount !== 1) {
    throw new Error(`ステータス信号の role=BUSY はちょうど 1 つ必要です（現在 ${busyCount} 件）`);
  }
  const portCount = Math.max(1, Number($("#plo-port-count")?.value) || 32);
  for (const signal of signals) {
    if (signal.plo_port > portCount) {
      throw new Error(
        `信号「${signal.label}」: PLO-${signal.plo_port} は仮想出力ポート数 ${portCount} を超えています`
      );
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
    { id: "rsp-result", label: "実行結果 (+0000)", group: "レスポンス領域 (Assem10)", device: "IN", address: rsp, format: "int32", relAddress: 0 },
    { id: "rsp-error", label: "エラーコード (+0002)", group: "レスポンス領域 (Assem10)", device: "IN", address: rsp + 2, format: "int32", relAddress: 2 },
    { id: "rsp-echo", label: "コマンドエコー (+0004)", group: "レスポンス領域 (Assem10)", device: "IN", address: rsp + 4, format: "int32", relAddress: 4 },
    { id: "rsp-param-size", label: "パラメータ総サイズ (+0006)", group: "レスポンス領域 (Assem10)", device: "IN", address: rsp + 6, format: "int32", relAddress: 6 },
  );
  appendDwordSpan(items, {
    idPrefix: "rsp-data", group: "レスポンス領域 (Assem10)", device: "IN", base: rsp,
    start: 8, stop: areaWatchWords("response", settings), labelWidth: 5,
  });
  items.push(
    { id: "cmd-trigger", label: "トリガ (+0000)", group: "コマンド領域 (Assem20)", device: "OUT", address: cmd, format: "int32", relAddress: 0 },
    { id: "cmd-code", label: "コマンドコード (+0002)", group: "コマンド領域 (Assem20)", device: "OUT", address: cmd + 2, format: "int32", relAddress: 2 },
  );
  appendDwordSpan(items, {
    idPrefix: "cmd-data", group: "コマンド領域 (Assem20)", device: "OUT", base: cmd,
    start: 4, stop: areaWatchWords("command", settings), labelWidth: 5,
  });
  const esoNames = normalizePortNames(settings.eso_port_names);
  const esiNames = normalizePortNames(settings.esi_port_names);
  for (let port = 1; port <= esoPorts; port += 1) {
    items.push({
      id: `eso-port-${port}`,
      label: portDisplayLabel(port, esoNames, `ESO-${port}`),
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
      label: portDisplayLabel(port, esiNames, `ESI-${port}`),
      group: "ESI入力 (Assem20)",
      device: "OUT",
      address: esiByte * 8 + (port - 1),
      format: "bit",
    });
  }
  return items;
}

function appendDwordSpan(items, options) {
  const start = Number(options.start) || 0;
  const stop = Number(options.stop) || 0;
  let offset = start + (start % 2);
  const end = stop - (stop % 2);
  const width = options.labelWidth || 4;
  for (; offset + 2 <= end; offset += 2) {
    items.push({
      id: `${options.idPrefix}-${offset}`,
      label: `+${String(offset).padStart(width, "0")}`,
      group: options.group,
      device: options.device,
      address: options.base + offset,
      format: "int32",
      relAddress: offset,
    });
  }
}

function areaWatchLimit(kind, settings) {
  const raw = kind === "command" ? settings.command_size : settings.response_size;
  const size = Number(raw) || 0;
  const even = size - (size % 2);
  const min = kind === "command" ? 4 : 8;
  return Math.max(min, even);
}

function areaWatchInput(kind) {
  return $(kind === "command" ? "#command-watch-words" : "#response-watch-words");
}

function areaWatchStorageKey(kind) {
  return kind === "command" ? "vtv-command-watch-words" : "vtv-response-watch-words";
}

function clampAreaWatchWords(kind, settings, value) {
  const limit = areaWatchLimit(kind, settings);
  const min = kind === "command" ? 4 : 8;
  let number = Number(value);
  if (!Number.isFinite(number)) number = limit;
  number = Math.min(limit, Math.max(min, Math.round(number)));
  if (number % 2) number -= 1;
  if (number < min) number = min;
  return number;
}

function syncAreaWatchInputs(settings) {
  for (const kind of ["command", "response"]) {
    const input = areaWatchInput(kind);
    if (!input) continue;
    const limit = areaWatchLimit(kind, settings);
    const min = kind === "command" ? 4 : 8;
    input.min = String(min);
    input.max = String(limit);
    let saved = null;
    try { saved = localStorage.getItem(areaWatchStorageKey(kind)); } catch (_) {}
    const followArea = saved == null || saved === "";
    input.value = String(clampAreaWatchWords(kind, settings, followArea ? limit : saved));
  }
}

function areaWatchWords(kind, settings) {
  const input = areaWatchInput(kind);
  return clampAreaWatchWords(kind, settings, input ? input.value : undefined);
}

function onAreaWatchWordsChanged() {
  let settings = state.settings;
  try {
    settings = { ...state.settings, ...readSettingsForm() };
  } catch (_) {}
  for (const kind of ["command", "response"]) {
    const value = clampAreaWatchWords(kind, settings, areaWatchInput(kind)?.value);
    const input = areaWatchInput(kind);
    if (input) input.value = String(value);
    try {
      if (value >= areaWatchLimit(kind, settings)) localStorage.removeItem(areaWatchStorageKey(kind));
      else localStorage.setItem(areaWatchStorageKey(kind), String(value));
    } catch (_) {}
  }
  refreshMappedWatchItems();
  renderWatchList();
  renderTimingChannelList();
  if (state.watchRunning && state.watchMode === "websocket") startWatchSocket();
}

function refreshMappedWatchItems() {
  const settings = {
    ...state.settings,
    ...(($("#transport") && readSettingsForm()) || {}),
  };
  syncAreaWatchInputs(settings);
  const watchable = settings.transport === "plclink" || settings.transport === "field_network";
  state.watchItems = buildMappedWatchItems(watchable ? settings : state.settings);
  rebuildWatchRequestItems();
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
  const query = (state.watchQuery || "").trim().toLowerCase();
  const visibleItems = state.watchItems.filter((item) => {
    if (state.watchChangedOnly && !state.watchChangedIds.has(item.id)) return false;
    if (!query) return true;
    const haystack = `${item.label || ""} ${item.group || ""} ${formatWatchAddress(item)}`.toLowerCase();
    return haystack.includes(query);
  });
  if (!visibleItems.length) {
    const message = state.watchChangedOnly && !query
      ? "変化した信号はまだありません。"
      : "条件に合う信号がありません。";
    list.innerHTML = `<div class="watch-empty">${message}</div>`;
    return;
  }
  const groups = [];
  for (const item of visibleItems) {
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
        <span class="watch-map-label" title="${escapeHtml(item.label)}">${escapeHtml(item.label)}</span>
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
  if (name.startsWith("コマンド領域") || name.startsWith("レスポンス領域")) {
    const width = name.includes("Assem") ? 5 : 4;
    const first = typeof items[0].relAddress === "number" ? items[0].relAddress : 0;
    const lastItem = items[items.length - 1];
    const last = (typeof lastItem.relAddress === "number" ? lastItem.relAddress : first) + 2;
    return `${name}（+${String(first).padStart(width, "0")}–+${String(last).padStart(width, "0")}）`;
  }
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
  let reveal = false;
  for (const id of changed) {
    if (!state.watchChangedIds.has(id)) {
      state.watchChangedIds.add(id);
      reveal = true;
    }
  }
  if (reveal && state.watchChangedOnly) {
    renderWatchList(changed);
    return;
  }
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
  let settings = state.settings;
  try {
    settings = readSettingsForm();
    state.settings = { ...state.settings, ...settings };
  } catch (_) {
    settings = state.settings;
  }
  if (settings.transport !== "plclink" && settings.transport !== "field_network") {
    setWatchStatus("PLCLINK / Field Network を選択してください", "error");
    return;
  }
  state.watchChangedIds = new Set();
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
  $("#start-timing-button") && ($("#start-timing-button").disabled = true);
  $("#stop-timing-button") && ($("#stop-timing-button").disabled = false);
  setWatchStatus("監視接続中…", "running");
  setTimingStatus("記録中", "running");
  startWatchSocket();
}

function stopWatch(resetValues = false) {
  state.watchRunning = false;
  clearTimeout(state.watchTimer);
  state.watchTimer = null;
  closeWatchSocket();
  resetWatchActualPeriod();
  if (resetValues) {
    state.watchValues = {};
    renderWatchList();
    clearTimingSamples();
  }
  $("#start-watch-button").disabled = false;
  $("#stop-watch-button").disabled = true;
  $("#start-timing-button") && ($("#start-timing-button").disabled = false);
  $("#stop-timing-button") && ($("#stop-timing-button").disabled = true);
  setWatchStatus("停止中");
  setTimingStatus(state.timingSamples.length ? "停止（波形は保持）" : "監視開始後に記録します");
}

function closeWatchSocket() {
  const socket = state.watchSocket;
  state.watchSocket = null;
  if (!socket) return;
  try {
    if (socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "stop" }));
    }
  } catch (_) {}
  try { socket.close(); } catch (_) {}
}

function watchSocketUrl() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${location.host}/ws/watch`;
}

function startWatchSocket() {
  closeWatchSocket();
  if (!state.watchRequestItems.length) rebuildWatchRequestItems();
  const transport = state.settings.transport || $("#transport")?.value;
  const intervalMs = readWatchIntervalMs();
  let socket;
  try {
    socket = new WebSocket(watchSocketUrl());
  } catch (error) {
    setWatchStatus(`WS接続失敗: ${error.message}（HTTPへ切替）`, "error");
    state.watchMode = "http";
    pollWatchValues();
    return;
  }
  state.watchSocket = socket;
  state.watchMode = "websocket";
  socket.addEventListener("open", () => {
    if (!state.watchRunning || state.watchSocket !== socket) return;
    socket.send(JSON.stringify({
      type: "start",
      transport,
      interval_ms: intervalMs,
      items: state.watchRequestItems,
    }));
  });
  socket.addEventListener("message", (event) => {
    if (!state.watchRunning || state.watchSocket !== socket) return;
    let message;
    try { message = JSON.parse(event.data); } catch (_) { return; }
    handleWatchSocketMessage(message);
  });
  socket.addEventListener("error", () => {
    if (state.watchSocket !== socket) return;
    setWatchStatus("WSエラー — HTTPポールへ切替", "error");
    closeWatchSocket();
    if (state.watchRunning) {
      state.watchMode = "http";
      pollWatchValues();
    }
  });
  socket.addEventListener("close", () => {
    if (state.watchSocket !== socket) return;
    state.watchSocket = null;
    if (state.watchRunning && state.watchMode === "websocket") {
      setWatchStatus("WS切断 — 再接続待ち", "error");
      state.watchTimer = setTimeout(() => {
        if (state.watchRunning) startWatchSocket();
      }, 500);
    }
  });
}

function handleWatchSocketMessage(message) {
  if (!message || typeof message !== "object") return;
  if (message.type === "ready") {
    setWatchStatus(`監視中 (WS ${Math.round(message.interval_ms)} ms)`, "running");
    return;
  }
  if (message.type === "error") {
    setWatchStatus(`監視エラー: ${message.message || "不明"}`, "error");
    setTimingStatus(`監視エラー: ${message.message || "不明"}`, "error");
    return;
  }
  if (message.type !== "sample") return;

  const sampleAt = resolveWatchSampleTime(message);
  if (state.watchLastCycleAt > 0) {
    const cycleMs = sampleAt - state.watchLastCycleAt;
    // サーバ時刻の逆行・重複は無視（表示が壊れないように）
    if (cycleMs >= 0) {
      state.watchActualMs = state.watchActualMs == null
        ? cycleMs
        : (state.watchActualMs * 0.7) + (cycleMs * 0.3);
    }
  }
  state.watchLastCycleAt = sampleAt;
  const serverDt = Number(message.dt_ms);
  state.watchFetchMs = Number.isFinite(serverDt)
    ? (state.watchFetchMs == null ? serverDt : (state.watchFetchMs * 0.7) + (serverDt * 0.3))
    : state.watchFetchMs;

  const changed = new Set();
  const incoming = Array.isArray(message.values) ? message.values : [];
  if (message.full) {
    const nextValues = {};
    for (const snapshot of incoming) {
      nextValues[snapshot.id] = snapshot;
      if (watchSnapshotChanged(state.watchValues[snapshot.id], snapshot)) {
        changed.add(snapshot.id);
      }
    }
    state.watchValues = nextValues;
  } else {
    for (const snapshot of incoming) {
      const prev = state.watchValues[snapshot.id];
      state.watchValues[snapshot.id] = snapshot;
      if (watchSnapshotChanged(prev, snapshot) || prev === undefined) {
        changed.add(snapshot.id);
      }
    }
  }
  if (changed.size) updateWatchValueDisplays(changed);
  // 値が変わらなくてもサンプルを積む（時間軸はサーバ時刻）
  recordTimingSample(sampleAt, state.watchValues);
  const uiNow = performance.now();
  if (uiNow - (state.watchPeriodLastAt || 0) > 100) {
    state.watchPeriodLastAt = uiNow;
    updateWatchActualPeriodDisplay();
  }
}

function watchSnapshotChanged(prev, next) {
  if (prev === undefined) return false;
  if (prev.valid !== next.valid) return true;
  if (prev.value !== next.value) return true;
  // float などは number 比較で足りる。オブジェクト値は稀なので文字列化は避ける
  return false;
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

  const transport = state.settings.transport || $("#transport")?.value;
  const endpoint = transport === "field_network"
    ? "/api/field-network/memory/read"
    : "/api/plclink/memory/read";
  if (!state.watchRequestItems.length) rebuildWatchRequestItems();
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: state.watchRequestItems }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "監視データを取得できません");
    const changed = new Set();
    const nextValues = {};
    for (const snapshot of data.values) {
      nextValues[snapshot.id] = snapshot;
      if (watchSnapshotChanged(state.watchValues[snapshot.id], snapshot)) {
        changed.add(snapshot.id);
      }
    }
    state.watchValues = nextValues;
    setWatchStatus("監視中", "running");
    updateWatchValueDisplays(changed);
    recordTimingSample(started, nextValues);
  } catch (error) {
    state.watchValues = {};
    updateWatchValueDisplays();
    setWatchStatus(`再接続待ち: ${error.message}`, "error");
    setTimingStatus(`再接続待ち: ${error.message}`, "error");
  } finally {
    const fetchMs = performance.now() - started;
    state.watchFetchMs = state.watchFetchMs == null
      ? fetchMs
      : (state.watchFetchMs * 0.7) + (fetchMs * 0.3);
    updateWatchActualPeriodDisplay();
    scheduleNextWatchPoll(fetchMs);
  }
}

function timingBitItems() {
  return state.watchItems.filter((item) => item.format === "bit");
}

function setTimingStatus(text, status = "") {
  const element = $("#timing-status");
  if (!element) return;
  element.textContent = text;
  element.className = `watch-status ${status}`.trim();
}

function updateTimingSampleInfo() {
  const element = $("#timing-sample-info");
  if (!element) return;
  const count = state.timingSamples.length;
  if (!count) {
    element.textContent = "サンプル —";
    return;
  }
  const spanMs = state.timingSamples[count - 1].t - state.timingSamples[0].t;
  element.textContent = `サンプル ${count}（${(spanMs / 1000).toFixed(1)} s）`;
}

function formatTimingDuration(ms) {
  if (!Number.isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 10000) return `${(ms / 1000).toFixed(3)} s`;
  return `${(ms / 1000).toFixed(2)} s`;
}

function formatTimingPolls(polls) {
  if (!Number.isFinite(polls) || polls < 0) return "—";
  const n = Math.round(polls);
  return `${n} poll`;
}

function timingIsPollAxis() {
  return state.timingAxisMode === "poll";
}

function timingSampleDomain(sample) {
  if (!sample) return 0;
  return timingIsPollAxis() ? (sample.n ?? 0) : sample.t;
}

function clearTimingMeasure() {
  state.timingCursorA = null;
  state.timingCursorB = null;
  state.timingPulse = null;
  updateTimingMeasureInfo();
  drawTimingChart();
}

function clearTimingSamples() {
  state.timingSamples = [];
  state.timingSampleSeq = 0;
  state.timingTimeOrigin = null;
  clearTimingMeasure();
  updateTimingSampleInfo();
  drawTimingChart();
}

function resetTimingView() {
  if (timingIsPollAxis()) {
    state.timingWindowPolls = clampTimingWindowPolls(
      Number($("#timing-window-polls")?.value) || state.timingWindowPolls || 500,
    );
    state.timingPanPolls = 0;
  } else {
    state.timingWindowMs = clampTimingWindowMs(
      Number($("#timing-window-ms")?.value) || state.timingWindowMs || 5000,
    );
    state.timingPanMs = 0;
  }
  syncTimingWindowSelect();
  updateTimingViewSpan();
  drawTimingChart();
}

function timingLatestT() {
  if (state.timingSamples.length) return state.timingSamples[state.timingSamples.length - 1].t;
  return performance.now();
}

function timingLatestN() {
  if (state.timingSamples.length) return state.timingSamples[state.timingSamples.length - 1].n ?? 0;
  return state.timingSampleSeq;
}

function timingLatestDomain() {
  return timingIsPollAxis() ? timingLatestN() : timingLatestT();
}

function timingViewRange() {
  if (timingIsPollAxis()) {
    const span = clampTimingWindowPolls(state.timingWindowPolls);
    const latest = timingLatestN();
    const pan = Math.max(0, state.timingPanPolls || 0);
    const end = latest - pan;
    const start = end - span;
    const visible = timingVisibleTimeSpan(start, end);
    const latestT = timingLatestT();
    const plotStart = visible?.tStart ?? latestT;
    const plotEnd = visible?.tEnd ?? latestT;
    const plotSpan = Math.max(1e-3, plotEnd - plotStart);
    return {
      start, end, span, latest, live: pan <= 0,
      plotStart, plotEnd, plotSpan,
      samples: visible?.samples || [],
      tStart: plotStart, tEnd: plotEnd, windowMs: span,
    };
  }
  const span = clampTimingWindowMs(state.timingWindowMs);
  const latest = timingLatestT();
  const pan = Math.max(0, state.timingPanMs || 0);
  const end = latest - pan;
  const start = end - span;
  return {
    start, end, span, latest, live: pan <= 0.5,
    plotStart: start, plotEnd: end, plotSpan: Math.max(1e-3, span),
    samples: null,
    tStart: start, tEnd: end, windowMs: span,
  };
}

function zoomTimingWindow(factor, anchor = null) {
  const before = timingViewRange();
  const pivot = anchor == null ? (before.start + before.end) / 2 : anchor;
  const ratio = before.span <= 0 ? 0.5 : (pivot - before.start) / before.span;
  if (timingIsPollAxis()) {
    const nextSpan = clampTimingWindowPolls(before.span * factor);
    const nextStart = pivot - ratio * nextSpan;
    const nextEnd = nextStart + nextSpan;
    state.timingWindowPolls = nextSpan;
    state.timingPanPolls = Math.max(0, Math.round(before.latest - nextEnd));
    localStorage.setItem("vtv-timing-window-polls", String(nextSpan));
  } else {
    const nextSpan = clampTimingWindowMs(before.span * factor);
    const nextStart = pivot - ratio * nextSpan;
    const nextEnd = nextStart + nextSpan;
    state.timingWindowMs = nextSpan;
    state.timingPanMs = Math.max(0, before.latest - nextEnd);
    localStorage.setItem("vtv-timing-window-ms", String(Math.round(nextSpan)));
  }
  syncTimingWindowSelect();
  updateTimingViewSpan();
  drawTimingChart();
}

function formatTimingTimeAge(ageMs, live, { precise = false } = {}) {
  if (!Number.isFinite(ageMs)) return "—";
  if (ageMs <= 0.05) return live ? "0" : (precise ? "0.0 ms" : formatTimingDuration(0));
  // 1 poll 刻みでは整数 ms だとラベルが潰れるため、短い区間は小数表示
  if (precise && ageMs < 1000) {
    const digits = ageMs < 10 ? 2 : 1;
    return `-${ageMs.toFixed(digits)} ms`;
  }
  return `-${formatTimingDuration(ageMs)}`;
}

function formatTimingDelta(delta) {
  return timingIsPollAxis() ? `Δ ${formatTimingPolls(delta)}` : `Δt ${formatTimingDuration(delta)}`;
}

function timingNiceTimeStep(spanMs) {
  const niceSteps = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 30000, 60000];
  let step = niceSteps[0];
  for (const candidate of niceSteps) {
    if (spanMs / candidate <= 8) {
      step = candidate;
      break;
    }
    step = candidate;
  }
  return step;
}

/** ポーリング軸の目盛り間隔（拡大時は 1 poll 刻みにして回数と一致させる） */
function timingNicePollStep(spanPolls) {
  const niceSteps = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000];
  let step = niceSteps[0];
  for (const candidate of niceSteps) {
    // 最大おおよそ 20 本まで許可（十分拡大すれば 1 poll = 1 目盛り）
    if (spanPolls / candidate <= 20) {
      step = candidate;
      break;
    }
    step = candidate;
  }
  return step;
}

function timingSamplesAroundPollRange(startN, endN) {
  const pad = 2;
  const out = [];
  for (const sample of state.timingSamples) {
    const n = sample.n ?? 0;
    if (n < startN - pad) continue;
    if (n > endN + pad) break;
    out.push(sample);
  }
  return out;
}

/** ポーリング番号 → 実時刻（近傍サンプルから線形補間） */
function timingTimeAtPoll(pollN, samples = null) {
  const list = samples || state.timingSamples;
  if (!list.length || !Number.isFinite(pollN)) return null;
  let lo = null;
  let hi = null;
  for (const sample of list) {
    const n = sample.n ?? 0;
    if (n <= pollN) lo = sample;
    if (n >= pollN) {
      hi = sample;
      break;
    }
  }
  if (lo && hi) {
    const n0 = lo.n ?? 0;
    const n1 = hi.n ?? 0;
    if (n1 === n0) return lo.t;
    const r = (pollN - n0) / (n1 - n0);
    return lo.t + r * (hi.t - lo.t);
  }
  if (lo) return lo.t;
  if (hi) return hi.t;
  return null;
}

/** 実時刻 → ポーリング番号（近傍サンプルから線形補間） */
function timingPollAtTime(targetT, samples = null) {
  const list = samples || state.timingSamples;
  if (!list.length || !Number.isFinite(targetT)) return null;
  if (targetT <= list[0].t) return list[0].n ?? 0;
  const last = list[list.length - 1];
  if (targetT >= last.t) return last.n ?? 0;
  for (let i = 1; i < list.length; i += 1) {
    const a = list[i - 1];
    const b = list[i];
    if (targetT > b.t) continue;
    const dt = b.t - a.t;
    if (dt <= 0) return a.n ?? 0;
    const r = (targetT - a.t) / dt;
    return (a.n ?? 0) + r * ((b.n ?? 0) - (a.n ?? 0));
  }
  return last.n ?? 0;
}

/** 時間軸モード切替時に、いま見ている区間・カーソルをできるだけ維持する */
function preserveTimingViewAcrossAxisMode(nextMode) {
  const prevMode = state.timingAxisMode;
  if (prevMode === nextMode) return;
  if (!state.timingSamples.length) return;

  const before = timingViewRange();
  const samples = state.timingSamples;

  if (nextMode === "time") {
    const tStart = timingTimeAtPoll(before.start, samples);
    const tEnd = timingTimeAtPoll(before.end, samples);
    if (tStart != null && tEnd != null && tEnd > tStart) {
      state.timingWindowMs = clampTimingWindowMs(tEnd - tStart);
      state.timingPanMs = Math.max(0, timingLatestT() - tEnd);
      localStorage.setItem("vtv-timing-window-ms", String(Math.round(state.timingWindowMs)));
    }
    state.timingCursorA = state.timingCursorA != null
      ? timingTimeAtPoll(state.timingCursorA, samples)
      : null;
    state.timingCursorB = state.timingCursorB != null
      ? timingTimeAtPoll(state.timingCursorB, samples)
      : null;
  } else {
    const nStart = timingPollAtTime(before.start, samples);
    const nEnd = timingPollAtTime(before.end, samples);
    if (nStart != null && nEnd != null && nEnd > nStart) {
      state.timingWindowPolls = clampTimingWindowPolls(nEnd - nStart);
      state.timingPanPolls = Math.max(0, Math.round(timingLatestN() - nEnd));
      localStorage.setItem("vtv-timing-window-polls", String(state.timingWindowPolls));
    }
    state.timingCursorA = state.timingCursorA != null
      ? timingPollAtTime(state.timingCursorA, samples)
      : null;
    state.timingCursorB = state.timingCursorB != null
      ? timingPollAtTime(state.timingCursorB, samples)
      : null;
  }

  if (state.timingPulse && state.timingCursorA == null && state.timingCursorB == null) {
    state.timingPulse = null;
  }
}

function timingVisibleTimeSpan(startN, endN) {
  const samples = timingSamplesAroundPollRange(startN, endN);
  if (samples.length < 2) {
    const t0 = timingTimeAtPoll(startN, samples);
    const t1 = timingTimeAtPoll(endN, samples);
    if (t0 == null || t1 == null) return null;
    return { tStart: t0, tEnd: t1, spanMs: Math.max(0, t1 - t0), samples };
  }
  const tStart = timingTimeAtPoll(startN, samples) ?? samples[0].t;
  const tEnd = timingTimeAtPoll(endN, samples) ?? samples[samples.length - 1].t;
  return { tStart, tEnd, spanMs: Math.max(0, tEnd - tStart), samples };
}

function formatTimingPulseLength(pulse) {
  if (!pulse) return "—";
  if (timingIsPollAxis()) {
    const polls = Math.max(0, (pulse.nEnd ?? 0) - (pulse.nStart ?? 0));
    const ms = Math.max(0, pulse.tEnd - pulse.tStart);
    return `${formatTimingPolls(polls)} (${formatTimingDuration(ms)})`;
  }
  return formatTimingDuration(pulse.tEnd - pulse.tStart);
}

function updateTimingMeasureInfo() {
  const el = $("#timing-measure-info");
  if (!el) return;
  const parts = [];
  const latest = timingLatestDomain();
  if (state.timingCursorA != null) {
    if (timingIsPollAxis()) {
      const agePolls = latest - state.timingCursorA;
      const tLatest = timingTimeAtPoll(latest);
      const tA = timingTimeAtPoll(state.timingCursorA);
      const ageMs = tLatest != null && tA != null ? tLatest - tA : null;
      parts.push(
        ageMs != null
          ? `A=${formatTimingPolls(agePolls)}前（${formatTimingDuration(ageMs)}）`
          : `A=${formatTimingPolls(agePolls)}前`,
      );
    } else {
      parts.push(`A=${formatTimingDuration(latest - state.timingCursorA)}前`);
    }
  }
  if (state.timingCursorA != null && state.timingCursorB != null) {
    const delta = Math.abs(state.timingCursorB - state.timingCursorA);
    if (timingIsPollAxis()) {
      const tA = timingTimeAtPoll(state.timingCursorA);
      const tB = timingTimeAtPoll(state.timingCursorB);
      const dt = tA != null && tB != null ? Math.abs(tB - tA) : null;
      parts.push(
        dt != null
          ? `${formatTimingDelta(delta)} / Δt ${formatTimingDuration(dt)}`
          : formatTimingDelta(delta),
      );
    } else {
      parts.push(formatTimingDelta(delta));
    }
  } else if (state.timingCursorA != null && state.timingCursorB == null) {
    parts.push("B をクリックで区間測定");
  }
  if (state.timingPulse) {
    const pulse = state.timingPulse;
    const label = state.watchItems.find((item) => item.id === pulse.id)?.label || pulse.id;
    parts.push(`${label} ${pulse.value ? "ON" : "OFF"} ${formatTimingPulseLength(pulse)}`);
  }
  if (!parts.length) {
    el.textContent = timingIsPollAxis()
      ? "横軸は実時間線形。目盛りは各 poll の実時刻（周期がぶれると間隔が変化）。クリックで A/B。"
      : "横軸・目盛りとも実時間。クリックでカーソル A/B（Δt と信号長）。";
    return;
  }
  el.textContent = parts.join(" ｜ ");
}

function renderTimingChannelList() {
  const list = $("#timing-channel-list");
  if (!list) return;
  const bits = timingBitItems();
  const available = new Set(bits.map((item) => item.id));
  state.timingSelectedIds = state.timingSelectedIds.filter((id) => available.has(id));
  if (!bits.length) {
    list.innerHTML = '<div class="watch-empty">bit 信号がありません</div>';
    return;
  }
  if (!state.timingSelectedIds.length && state.timingNeedsDefaultChannels) {
    state.timingSelectedIds = bits.slice(0, Math.min(4, bits.length)).map((item) => item.id);
    state.timingNeedsDefaultChannels = false;
    localStorage.setItem("vtv-timing-channels", JSON.stringify(state.timingSelectedIds));
  }
  list.innerHTML = bits.map((item, index) => {
    const checked = state.timingSelectedIds.includes(item.id) ? " checked" : "";
    const color = state.timingColors[index % state.timingColors.length];
    return `<label class="timing-channel-item">
      <input type="checkbox" data-timing-id="${escapeHtml(item.id)}"${checked}>
      <span class="timing-channel-label">
        <span style="color:${color}">●</span> ${escapeHtml(item.label)}
        <span class="timing-channel-addr">${escapeHtml(formatWatchAddress(item))}</span>
      </span>
    </label>`;
  }).join("");
}

function bitValueFromSnapshot(snapshot) {
  if (!snapshot || snapshot.valid === false) return null;
  return snapshot.value ? 1 : 0;
}

function recordTimingSample(t, values) {
  const bits = {};
  for (const item of timingBitItems()) {
    bits[item.id] = bitValueFromSnapshot(values[item.id]);
  }
  if (!Object.keys(bits).length) {
    updateTimingSampleInfo();
    return;
  }
  state.timingSampleSeq += 1;
  const n = state.timingSampleSeq;
  state.timingSamples.push({ t, n, bits });
  const keepFromT = t - Math.max(
    clampTimingWindowMs(state.timingWindowMs) * 4,
    (state.timingPanMs || 0) + clampTimingWindowMs(state.timingWindowMs) * 2,
    60000,
  );
  const keepFromN = n - Math.max(
    clampTimingWindowPolls(state.timingWindowPolls) * 4,
    (state.timingPanPolls || 0) + clampTimingWindowPolls(state.timingWindowPolls) * 2,
    20000,
  );
  while (state.timingSamples.length > state.timingMaxSamples) state.timingSamples.shift();
  while (
    state.timingSamples.length
    && state.timingSamples[0].t < keepFromT
    && (state.timingSamples[0].n ?? 0) < keepFromN
  ) {
    state.timingSamples.shift();
  }
  const now = performance.now();
  if (now - state.timingInfoLastAt > 200) {
    state.timingInfoLastAt = now;
    updateTimingSampleInfo();
    updateTimingViewSpan();
  }
  if (state.watchRunning) setTimingStatus("記録中", "running");
  queueTimingChartDraw();
}

function queueTimingChartDraw() {
  if ($("#monitor-timing-panel")?.classList.contains("hidden")) return;
  if (state.timingDrawQueued) return;
  state.timingDrawQueued = true;
  requestAnimationFrame(() => {
    state.timingDrawQueued = false;
    if (!$("#monitor-timing-panel")?.classList.contains("hidden")) {
      drawTimingChart();
    }
  });
}

function timingChannelPoints(itemId, start, end) {
  const points = [];
  if (timingIsPollAxis()) {
    // 窓は poll 番号、描画座標 d は実時間（時間線形）
    const pad = 2;
    for (const sample of state.timingSamples) {
      const n = sample.n ?? 0;
      if (n < start - pad) continue;
      if (n > end + pad) break;
      const v = sample.bits[itemId];
      if (v == null) continue;
      points.push({ t: sample.t, n, d: sample.t, v });
    }
    return points;
  }
  const pad = 50;
  for (const sample of state.timingSamples) {
    if (sample.t < start - pad) continue;
    if (sample.t > end + pad) break;
    const v = sample.bits[itemId];
    if (v == null) continue;
    points.push({ t: sample.t, n: sample.n, d: sample.t, v });
  }
  return points;
}

function findTimingPulseAt(itemId, domainPos) {
  if (!state.timingSamples.length) return null;
  let idx = -1;
  for (let i = 0; i < state.timingSamples.length; i += 1) {
    const v = state.timingSamples[i].bits[itemId];
    if (v == null) continue;
    if (timingSampleDomain(state.timingSamples[i]) <= domainPos) idx = i;
    else break;
  }
  if (idx < 0) return null;
  const value = state.timingSamples[idx].bits[itemId];
  let startIdx = idx;
  while (startIdx > 0) {
    const prev = state.timingSamples[startIdx - 1].bits[itemId];
    if (prev == null || prev !== value) break;
    startIdx -= 1;
  }
  let endIdx = idx;
  while (endIdx < state.timingSamples.length - 1) {
    const next = state.timingSamples[endIdx + 1].bits[itemId];
    if (next == null || next !== value) break;
    endIdx += 1;
  }
  const startSample = state.timingSamples[startIdx];
  let tEnd;
  let nEnd;
  if (endIdx < state.timingSamples.length - 1) {
    // 次サンプルがエッジ
    tEnd = state.timingSamples[endIdx + 1].t;
    nEnd = state.timingSamples[endIdx + 1].n ?? (endIdx + 2);
  } else {
    tEnd = timingLatestT();
    nEnd = timingLatestN();
  }
  return {
    id: itemId,
    value: value ? 1 : 0,
    tStart: startSample.t,
    tEnd,
    nStart: startSample.n ?? (startIdx + 1),
    nEnd,
  };
}

function bindTimingChartInteractions() {
  const canvas = $("#timing-chart");
  if (!canvas || canvas.dataset.timingBound === "1") return;
  canvas.dataset.timingBound = "1";
  canvas.style.cursor = "crosshair";

  const pointerPos = (event) => {
    const rect = canvas.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };

  canvas.addEventListener("wheel", (event) => {
    if ($("#monitor-timing-panel")?.classList.contains("hidden")) return;
    event.preventDefault();
    const geom = state.timingChartGeom;
    if (!geom) return;
    const { x } = pointerPos(event);
    const ratio = Math.min(1, Math.max(0, (x - geom.padL) / geom.chartW));
    const plotPos = geom.plotStart + ratio * geom.plotSpan;
    let anchor = plotPos;
    if (timingIsPollAxis()) {
      const poll = timingPollAtTime(plotPos, geom.samples);
      anchor = poll == null ? (geom.start + geom.end) / 2 : poll;
    }
    zoomTimingWindow(event.deltaY > 0 ? 1.25 : 0.8, anchor);
  }, { passive: false });

  canvas.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    const { x, y } = pointerPos(event);
    const geom = state.timingChartGeom;
    state.timingPointer = {
      x,
      y,
      startX: x,
      startY: y,
      startPan: timingIsPollAxis() ? state.timingPanPolls : state.timingPanMs,
      startPlotEnd: geom?.plotEnd ?? 0,
      startPlotSpan: geom?.plotSpan ?? 1,
      startLatest: timingLatestN(),
      startSpan: geom?.span ?? 1,
      dragged: false,
      pointerId: event.pointerId,
    };
    canvas.setPointerCapture(event.pointerId);
  });

  canvas.addEventListener("pointermove", (event) => {
    const ptr = state.timingPointer;
    if (!ptr || ptr.pointerId !== event.pointerId) return;
    const geom = state.timingChartGeom;
    if (!geom || geom.chartW <= 0) return;
    const { x, y } = pointerPos(event);
    const dx = x - ptr.startX;
    const dy = y - ptr.startY;
    if (!ptr.dragged && Math.hypot(dx, dy) > 4) ptr.dragged = true;
    if (!ptr.dragged) return;
    if (timingIsPollAxis()) {
      // 横軸は実時間線形なので、ドラッグ量も時刻→poll に変換する
      const dt = (-dx / geom.chartW) * (ptr.startPlotSpan || geom.plotSpan);
      const nextEndT = ptr.startPlotEnd + dt;
      const nextEndPoll = timingPollAtTime(nextEndT);
      if (nextEndPoll != null) {
        state.timingPanPolls = Math.max(0, Math.round(ptr.startLatest - nextEndPoll));
      } else {
        const deltaPolls = (-dx / geom.chartW) * (ptr.startSpan || geom.span);
        state.timingPanPolls = Math.max(0, Math.round(ptr.startPan + deltaPolls));
      }
    } else {
      const delta = (-dx / geom.chartW) * geom.span;
      state.timingPanMs = Math.max(0, ptr.startPan + delta);
    }
    ptr.x = x;
    ptr.y = y;
    updateTimingViewSpan();
    drawTimingChart();
  });

  const endPointer = (event) => {
    const ptr = state.timingPointer;
    if (!ptr || ptr.pointerId !== event.pointerId) return;
    const geom = state.timingChartGeom;
    const { x, y } = pointerPos(event);
    if (!ptr.dragged && geom && geom.chartW > 0) {
      const plotPos = geom.plotStart + ((x - geom.padL) / geom.chartW) * geom.plotSpan;
      let clamped;
      if (timingIsPollAxis()) {
        const poll = timingPollAtTime(plotPos, geom.samples);
        clamped = Math.min(geom.end, Math.max(geom.start, poll ?? geom.end));
      } else {
        clamped = Math.min(geom.end, Math.max(geom.start, plotPos));
      }
      if (state.timingCursorA == null || (state.timingCursorA != null && state.timingCursorB != null)) {
        state.timingCursorA = clamped;
        state.timingCursorB = null;
      } else {
        state.timingCursorB = clamped;
      }
      const lane = geom.lanes.find((item) => y >= item.top && y <= item.bottom);
      if (lane) {
        state.timingPulse = findTimingPulseAt(lane.id, clamped);
      } else if (state.timingSelectedIds[0]) {
        state.timingPulse = findTimingPulseAt(state.timingSelectedIds[0], clamped);
      }
      updateTimingMeasureInfo();
      drawTimingChart();
    }
    state.timingPointer = null;
  };
  canvas.addEventListener("pointerup", endPointer);
  canvas.addEventListener("pointercancel", () => { state.timingPointer = null; });
}

function drawTimingChart() {
  const canvas = $("#timing-chart");
  if (!canvas) return;
  const wrap = canvas.parentElement;
  const dpr = window.devicePixelRatio || 1;
  const cssW = Math.max(1, wrap?.clientWidth || canvas.clientWidth || 800);
  const cssH = Math.max(1, wrap?.clientHeight || canvas.clientHeight || 320);
  if (canvas.width !== Math.floor(cssW * dpr) || canvas.height !== Math.floor(cssH * dpr)) {
    canvas.width = Math.floor(cssW * dpr);
    canvas.height = Math.floor(cssH * dpr);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);
  ctx.fillStyle = "#0f1724";
  ctx.fillRect(0, 0, cssW, cssH);

  const selectedIds = new Set(state.timingSelectedIds);
  const selected = timingBitItems().filter((item) => selectedIds.has(item.id));
  const showScale = !!state.timingShowScale;
  const padL = 8;
  const padR = 12;
  const padT = 10;
  const padB = showScale ? 28 : 10;
  const chartW = cssW - padL - padR;
  const chartH = cssH - padT - padB;
  const range = timingViewRange();
  const { start, end, span, live, plotStart, plotEnd, plotSpan } = range;
  const plotSamples = range.samples;
  const lanes = [];
  const isLive = live;

  state.timingChartGeom = {
    padL, padR, padT, padB, chartW, chartH, cssW, cssH,
    start, end, span,
    plotStart, plotEnd, plotSpan,
    samples: plotSamples,
    tStart: plotStart, tEnd: plotEnd, windowMs: span,
    lanes,
  };

  if (!selected.length) {
    ctx.fillStyle = "#68758d";
    ctx.font = "12px sans-serif";
    ctx.fillText("左の一覧から比較したい bit 信号を選択してください", padL + 8, padT + 24);
    return;
  }

  const laneH = chartH / selected.length;
  const bitItems = timingBitItems();
  // 描画座標は常に実時間線形（ポーリング軸でも plotStart/plotEnd は時刻）
  const xOf = (t) => padL + ((t - plotStart) / plotSpan) * chartW;

  // 横軸グリッド
  // ポーリング軸: 各 poll の実時刻位置に目盛り（周期がぶれると間隔が不均一）
  if (showScale) {
    const drawScaleTick = (x, label) => {
      if (!Number.isFinite(x) || x < padL - 1 || x > padL + chartW + 1) return;
      ctx.strokeStyle = "#1e2a3d";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, padT);
      ctx.lineTo(x, padT + chartH);
      ctx.stroke();
      ctx.fillStyle = "#68758d";
      ctx.font = "10px Consolas, monospace";
      ctx.textAlign = "center";
      ctx.fillText(label, x, cssH - 10);
    };

    if (timingIsPollAxis()) {
      const step = timingNicePollStep(span);
      const samples = plotSamples?.length
        ? plotSamples
        : timingSamplesAroundPollRange(start, end);
      const tEnd = timingTimeAtPoll(end, samples) ?? plotEnd;
      const preciseLabels = step <= 2;
      const firstTick = Math.ceil(start / step) * step;
      for (let tick = firstTick; tick <= end + 0.01; tick += step) {
        const t = timingTimeAtPoll(tick, samples);
        if (t == null) continue;
        let label;
        if (tEnd != null) {
          label = formatTimingTimeAge(tEnd - t, isLive, { precise: preciseLabels });
        } else {
          const agePolls = end - tick;
          label = agePolls <= 0 ? (isLive ? "0" : "0 poll") : `-${formatTimingPolls(agePolls)}`;
        }
        drawScaleTick(xOf(t), label);
      }
    } else {
      const niceSteps = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 30000, 60000];
      let step = niceSteps[0];
      for (const candidate of niceSteps) {
        if (span / candidate <= 8) {
          step = candidate;
          break;
        }
        step = candidate;
      }
      const firstTick = Math.ceil(start / step) * step;
      for (let tick = firstTick; tick <= end + 0.1; tick += step) {
        drawScaleTick(xOf(tick), formatTimingTimeAge(end - tick, isLive));
      }
    }
    ctx.textAlign = "left";
  }

  selected.forEach((item, index) => {
    const top = padT + laneH * index;
    const bottom = top + laneH;
    const mid = top + laneH / 2;
    const highY = top + laneH * 0.22;
    const lowY = top + laneH * 0.78;
    lanes.push({ id: item.id, top, bottom, highY, lowY });
    const colorIndex = Math.max(0, bitItems.findIndex((b) => b.id === item.id));
    const color = state.timingColors[colorIndex % state.timingColors.length];

    if (index % 2 === 0) {
      ctx.fillStyle = "rgba(255,255,255,0.02)";
      ctx.fillRect(padL, top, chartW, laneH);
    }
    ctx.strokeStyle = "#243044";
    ctx.beginPath();
    ctx.moveTo(padL, bottom);
    ctx.lineTo(padL + chartW, bottom);
    ctx.stroke();
    ctx.fillStyle = color;
    ctx.font = "11px sans-serif";
    ctx.fillText(item.label, padL + 6, top + 14);

    ctx.strokeStyle = "#1a2536";
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(padL, highY);
    ctx.lineTo(padL + chartW, highY);
    ctx.moveTo(padL, lowY);
    ctx.lineTo(padL + chartW, lowY);
    ctx.stroke();
    ctx.setLineDash([]);

    // 測定中のパルスを薄くハイライト（描画は実時間）
    if (state.timingPulse && state.timingPulse.id === item.id) {
      const px0 = Math.max(padL, xOf(state.timingPulse.tStart));
      const px1 = Math.min(padL + chartW, xOf(state.timingPulse.tEnd));
      if (px1 > px0) {
        ctx.fillStyle = "rgba(240, 180, 41, 0.16)";
        ctx.fillRect(px0, top + 2, px1 - px0, laneH - 4);
      }
    }

    const points = timingChannelPoints(item.id, start, end);
    if (!points.length) {
      ctx.fillStyle = "#4a5568";
      ctx.font = "10px sans-serif";
      ctx.fillText("データなし", padL + 6, mid + 4);
      return;
    }

    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    let started = false;
    let lastY = points[0].v ? highY : lowY;
    for (let i = 0; i < points.length; i += 1) {
      const p = points[i];
      const x = xOf(Math.min(Math.max(p.d, plotStart), plotEnd));
      const y = p.v ? highY : lowY;
      if (!started) {
        ctx.moveTo(Math.max(padL, x), y);
        started = true;
        lastY = y;
        continue;
      }
      ctx.lineTo(x, lastY);
      if (y !== lastY) ctx.lineTo(x, y);
      lastY = y;
    }
    ctx.lineTo(Math.min(padL + chartW, xOf(Math.min(plotEnd, points[points.length - 1].d))), lastY);
    if (isLive) ctx.lineTo(padL + chartW, lastY);
    ctx.stroke();

    if (isLive) {
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(padL + chartW - 4, lastY, 3.5, 0, Math.PI * 2);
      ctx.fill();
    }

    // 各信号の測定長（カーソル位置のパルス）
    const pulse = state.timingCursorA != null || state.timingCursorB != null
      ? findTimingPulseAt(item.id, state.timingCursorB ?? state.timingCursorA)
      : null;
    if (pulse) {
      const label = `${pulse.value ? "ON" : "OFF"} ${formatTimingPulseLength(pulse)}`;
      ctx.fillStyle = "#d7e0ef";
      ctx.font = "10px Consolas, monospace";
      ctx.textAlign = "right";
      ctx.fillText(label, padL + chartW - 8, top + 14);
      ctx.textAlign = "left";
    }
  });

  const cursorPlotPos = (pos) => {
    if (pos == null) return null;
    if (!timingIsPollAxis()) {
      if (pos < start || pos > end) return null;
      return pos;
    }
    if (pos < start || pos > end) return null;
    return timingTimeAtPoll(pos, plotSamples);
  };

  const drawCursor = (pos, name, color) => {
    const plotPos = cursorPlotPos(pos);
    if (plotPos == null || !Number.isFinite(plotPos)) return;
    const x = xOf(plotPos);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.moveTo(x, padT);
    ctx.lineTo(x, padT + chartH);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = color;
    ctx.font = "10px sans-serif";
    ctx.fillText(name, x + 4, padT + 12);
  };
  drawCursor(state.timingCursorA, "A", "#8fd3ff");
  drawCursor(state.timingCursorB, "B", "#ff9f68");

  if (state.timingCursorA != null && state.timingCursorB != null) {
    const a = Math.min(state.timingCursorA, state.timingCursorB);
    const b = Math.max(state.timingCursorA, state.timingCursorB);
    const plotA = cursorPlotPos(a);
    const plotB = cursorPlotPos(b);
    if (plotA != null && plotB != null) {
      const x0 = Math.max(padL, xOf(Math.min(plotA, plotB)));
      const x1 = Math.min(padL + chartW, xOf(Math.max(plotA, plotB)));
      if (x1 > x0) {
        ctx.fillStyle = "rgba(143, 211, 255, 0.08)";
        ctx.fillRect(x0, padT, x1 - x0, chartH);
        ctx.fillStyle = "#8fd3ff";
        ctx.font = "11px Consolas, monospace";
        ctx.textAlign = "center";
        let deltaLabel = formatTimingDelta(b - a);
        if (timingIsPollAxis()) {
          deltaLabel = `${deltaLabel} / ${formatTimingDuration(Math.abs(plotB - plotA))}`;
        }
        ctx.fillText(deltaLabel, (x0 + x1) / 2, padT + chartH - 8);
        ctx.textAlign = "left";
      }
    }
  }

  updateTimingMeasureInfo();
}

function transportOf() {
  return $("#transport")?.value || state.settings.transport;
}

function isMappedTransport(transport = transportOf()) {
  return transport === "plclink" || transport === "field_network";
}

function commandAvailable(item, transport = transportOf()) {
  if (transport === "plclink") return !!item.plclink_supported;
  if (transport === "field_network") return !!item.field_network_supported;
  return !item.local_io && item.tcp_supported !== false;
}

function visibleArguments(def) {
  if (isMappedTransport() && Array.isArray(def?.plclink_arguments)) return def.plclink_arguments;
  const args = def?.arguments || [];
  return isMappedTransport() ? args : args.filter((arg) => !arg.mapped_only);
}

function usesRaw(def) {
  if (isMappedTransport() && Array.isArray(def?.plclink_arguments)) return false;
  return !!def?.raw_arguments;
}

function argumentVisible(step, arg) {
  const cond = arg.show_if;
  if (!cond) return true;
  const current = String(step.arguments?.[cond.key] ?? "");
  if (Array.isArray(cond.in)) return cond.in.map(String).includes(current);
  return current === String(cond.equals);
}

function argumentValue(step, arg) {
  const value = step.arguments?.[arg.key];
  if ((value === undefined || value === "") && arg.key === "increment" && step.arguments?.raw) {
    return step.arguments.raw;
  }
  return value ?? "";
}

function renderPalette() {
  const query = $("#command-search")?.value.trim().toLowerCase() || "";
  const transport = transportOf();
  const isMapped = isMappedTransport(transport);
  const matches = (item) =>
    `${item.code} ${item.name} ${item.description} ${item.tool_name || ""}`.toLowerCase().includes(query);
  const available = state.catalog.filter((item) => commandAvailable(item, transport));
  const unavailable = state.catalog.filter((item) => !commandAvailable(item, transport));
  const filtered = available.filter(matches);
  const favoriteCodes = new Set(state.favorites || []);
  const favorites = filtered.filter((item) => favoriteCodes.has(item.code));
  if ($("#catalog-count")) $("#catalog-count").textContent = available.length;
  const favoriteHtml = favorites.length ? `
    <section class="command-group">
      <h4>お気に入り<span>${favorites.length}</span></h4>
      ${favorites.map((item) => paletteCommandButton(item, transport, isMapped)).join("")}
    </section>` : "";
  const groups = catalogGroups(filtered).map((group) => `
    <section class="command-group">
      <h4>${escapeHtml(group.label)}<span>${group.items.length}</span></h4>
      ${group.items.map((item) => paletteCommandButton(item, transport, isMapped)).join("")}
    </section>`).join("");
  const hidden = unavailable.filter(matches);
  const folded = hidden.length ? `
    <details class="unsupported-fold" ${state.foldUnsupported === false ? "open" : ""}>
      <summary>この方式では使えない ${hidden.length}</summary>
      ${hidden.map((item) => paletteCommandButton(item, transport, isMapped)).join("")}
    </details>` : "";
  const palette = $("#command-palette");
  if (!palette) return;
  palette.innerHTML = `${favoriteHtml}${groups}${folded}`;
  palette.querySelectorAll(".palette-command").forEach((button) => {
    button.addEventListener("click", () => {
      const code = button.dataset.code;
      const item = state.catalog.find((entry) => entry.code === code);
      if (!item || !commandAvailable(item, transport)) {
        showToast(unsupportedCommandReason(item, transport));
        return;
      }
      addCommand(code, state.steps);
    });
  });
  palette.querySelectorAll("[data-favorite]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleFavorite(button.dataset.favorite);
    });
  });
}

function newCommand(code) {
  const definition = state.catalog.find((item) => item.code === code);
  const args = {};
  for (const arg of visibleArguments(definition)) {
    if (arg.default !== undefined) args[arg.key] = arg.default;
    else if (arg.type === "integer") args[arg.key] = arg.min;
    else if (arg.type === "enum") args[arg.key] = arg.options[0].value;
    else args[arg.key] = "";
  }
  if (usesRaw(definition)) args.raw = "";
  return {
    id: state.nextId++,
    type: "command",
    command: code,
    arguments: args,
    argument_variables: {},
    ignore_response: false,
  };
}

function addCommand(code, target) {
  if (state.running) return;
  target.push(newCommand(code));
  renderSequence();
}

function addControl(type, target) {
  if (state.running) return;
  if (type === "delay") target.push({ id: state.nextId++, type, milliseconds: 100 });
  if (type === "break") {
    if (!listIsInsideLoop(target)) {
      showToast("BREAK はループの中にだけ追加できます。");
      return;
    }
    target.push({ id: state.nextId++, type });
  }
  if (type === "note") target.push({ id: state.nextId++, type, text: "" });
  if (type === "variable") target.push({
    id: state.nextId++, type, name: "", source: "last_response",
    card_id: "", port: 1, offset: 0, result_format: "dec", value: "",
  });
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
  persistSequenceDraft();
}

function stepHtml(step, nested = false) {
  const isCompact = state.viewMode === "compact";
  if (step.type === "command") {
    const def = state.catalog.find((item) => item.code === step.command);
    if (!def) {
      return `<article class="step-card generated-step unsupported-step" data-id="${step.id}">
        ${stepHeader(step, `<strong>${escapeHtml(step.command || "?")}</strong>不明なコマンド`, nested)}
        ${isCompact ? "" : `<div class="step-body"><p class="step-warning">カタログにないコマンドです。</p></div>`}
      </article>`;
    }
    const transport = $("#transport")?.value || state.settings.transport;
    const isMapped = transport === "plclink" || transport === "field_network";
    const supported = transport === "field_network"
      ? !!def.field_network_supported
      : transport === "plclink"
        ? !!def.plclink_supported
        : !def.local_io && def.tcp_supported !== false;
    const unsupported = !supported;
    const modeLabel = def.local_io
      ? "ローカルI/O"
      : (transport === "field_network" ? "FNコマンド" : "PLCLINKコマンド");
    const fields = visibleArguments(def)
      .filter((arg) => argumentVisible(step, arg))
      .map((arg) => argumentField(step, arg))
      .join("");
    const rawVariable = argumentVariableName(step, "raw");
    const raw = usesRaw(def) ? `
      <label>引数文字列${variableSelect("raw", rawVariable, "引数文字列")}
        <input data-field="raw" value="${rawVariable ? `変数 ${escapeHtml(rawVariable)}` : escapeHtml(step.arguments.raw || "")}" ${rawVariable ? "disabled" : ""} placeholder="別資料の構文に従って入力">
      </label>` : "";
    const ignoreOption = `
      <label class="step-option" title="送信後に装置応答を待たず、すぐ次のカードへ進みます">
        <input data-field="ignore_response" type="checkbox" ${step.ignore_response ? "checked" : ""}>
        応答を待たない
      </label>`;
    const compactSummary = commandCompactSummary(step, def);
    const mappedCode = def.local_io
      ? def.code
      : (transport === "field_network" ? def.field_network_code : def.plclink_code);
    const displayCode = isMapped && mappedCode != null && mappedCode !== ""
      ? `${mappedCode}：`
      : def.code;
    const unsupportedReason = transport === "field_network"
      ? (def.field_network_reason || def.plclink_reason)
      : def.plclink_reason;
    const missing = missingLabels(step);
    const missingNote = missing.length
      ? `<p class="step-warning missing-note">未入力: ${escapeHtml(missing.join("、"))}</p>`
      : "";
    return `<article class="step-card generated-step${unsupported ? " unsupported-step" : ""}${missing.length ? " incomplete-step" : ""}" data-id="${step.id}">
      ${stepHeader(step, `<strong>${displayCode}</strong>${escapeHtml(def.name)}${isMapped ? `<small class="plclink-code">${modeLabel}</small>` : ""}${def.tool_name ? `<small class="tool-badge">${escapeHtml(def.tool_id)} ${escapeHtml(def.tool_name)}</small>` : ""}`, nested)}
      ${isCompact
    ? `${compactSummary ? `<div class="step-compact-row">${compactSummary}</div>` : ""}${missingNote}`
    : `<div class="step-body">${fields}${raw}${ignoreOption}
        ${missingNote}
        ${unsupported ? `<p class="step-warning">${escapeHtml(unsupportedReason || "この通信方式では使用できません")}</p>` : ""}
        <p class="step-description">${escapeHtml(def.description || "")}${!isMapped && def.example ? `　例: ${escapeHtml(def.example)}` : ""}</p>
      </div>`}
    </article>`;
  }
  if (step.type === "variable") {
    const transport = $("#transport")?.value || state.settings.transport;
    const source = step.source || "last_response";
    const cards = collectCommandCards(state.steps);
    const cardOptions = cards.map((item) =>
      `<option value="${escapeHtml(item.id)}" ${String(step.card_id) === item.id ? "selected" : ""}>${escapeHtml(item.label)}</option>`
    ).join("");
    const missingName = !String(step.name || "").trim();
    const title = isCompact
      ? `<strong>VAR</strong>${escapeHtml(step.name || "変数")} ${escapeHtml(variableSourceLabel(source))}`
      : "<strong>VAR</strong>変数";
    const cardField = source === "card_response" || source === "card_status"
      ? `<label>カード<select data-field="card_id"><option value="">選んでください</option>${cardOptions}</select></label>`
      : "";
    const portField = source === "output_port"
      ? `<label>${escapeHtml(outputPortCaption())}<input data-field="port" type="number" min="1" max="256" step="1" value="${Number(step.port) || 1}"></label>`
      : "";
    const literalField = source === "literal"
      ? `<label>入れる文字<input data-field="value" type="text" maxlength="500" value="${escapeHtml(step.value || "")}"></label>`
      : "";
    const resultFormat = step.result_format || "dec";
    const resultMax = Math.max(0, resultDataSize() - 2);
    const resultField = source === "result_data"
      ? `<label>相対アドレス<input data-field="offset" type="number" min="0" max="${resultMax}" step="2" value="${Number(step.offset) || 0}"></label>
        <label>表記<select data-field="result_format">
          <option value="dec" ${resultFormat === "dec" ? "selected" : ""}>整数</option>
          <option value="fixed" ${resultFormat === "fixed" ? "selected" : ""}>固定小数点</option>
          <option value="hex" ${resultFormat === "hex" ? "selected" : ""}>16進</option>
        </select></label>`
      : "";
    const tcpNote = transport === "tcp" && (source === "output_port" || source === "result_data")
      ? `<p class="step-warning">${source === "output_port" ? "TCP では出力ポートを直接読めません。" : "TCP では結果データ出力を直接読めません。"}コマンドの応答を選んでください。</p>`
      : "";
    return `<article class="step-card variable-step generated-step${missingName ? " incomplete-step" : ""}" data-id="${step.id}">
      ${stepHeader(step, title, nested)}
      ${isCompact ? "" : `<div class="step-body">
        <label class="${missingName ? "missing-arg" : ""}">名前
          <input data-field="name" type="text" maxlength="40" value="${escapeHtml(step.name || "")}" placeholder="ロット">
        </label>
        <label>格納する値<select data-field="source">
          <option value="last_response" ${source === "last_response" ? "selected" : ""}>直前のカードの応答</option>
          <option value="last_status" ${source === "last_status" ? "selected" : ""}>直前のカードの結果（AK/NK/ER）</option>
          <option value="card_response" ${source === "card_response" ? "selected" : ""}>指定したカードの応答</option>
          <option value="card_status" ${source === "card_status" ? "selected" : ""}>指定したカードの結果（AK/NK/ER）</option>
          <option value="output_port" ${source === "output_port" ? "selected" : ""}>出力ポート</option>
          <option value="result_data" ${source === "result_data" ? "selected" : ""}>結果データ出力</option>
          <option value="literal" ${source === "literal" ? "selected" : ""}>固定の文字</option>
        </select></label>
        ${cardField}${portField}${resultField}${literalField}${tcpNote}
        <p class="step-description">名前で残します。あとのコマンド引数で、その名前を選べます。装置へは送りません。${source === "card_response" || source === "card_status" ? "指定したカードは、この変数より前に置いてください。" : ""}${source === "result_data" ? "相対アドレスは監視の +0000 と同じ位置です。" : ""}</p>
      </div>`}
    </article>`;
  }
  if (step.type === "note") {
    const title = isCompact
      ? `<strong>MEMO</strong>${escapeHtml(step.text || "メモ")}`
      : "<strong>MEMO</strong>メモ";
    return `<article class="step-card note-step generated-step" data-id="${step.id}">
      ${stepHeader(step, title, nested)}
      ${isCompact ? "" : `<div class="step-body"><label>メモ
        <textarea data-field="text" maxlength="500" rows="2" placeholder="装置には送りません">${escapeHtml(step.text || "")}</textarea>
      </label></div>`}
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
  for (const arg of visibleArguments(def)) {
    if (!argumentVisible(step, arg)) continue;
    const variableName = argumentVariableName(step, arg.key);
    if (variableName) {
      parts.push(`${arg.label}:変数 ${variableName}`);
      if (parts.length >= 3) break;
      continue;
    }
    const value = step.arguments[arg.key];
    if (value === undefined || value === null || value === "") continue;
    parts.push(`${arg.label}:${value}`);
    if (parts.length >= 3) break;
  }
  const rawVariable = argumentVariableName(step, "raw");
  if (rawVariable) parts.push(`raw:変数 ${rawVariable}`);
  else if (usesRaw(def) && step.arguments.raw) parts.push(`raw:${step.arguments.raw}`);
  if (step.ignore_response) parts.push("応答無視");
  return parts.map((part) => `<span>${escapeHtml(part)}</span>`).join("");
}

function stepHeader(step, title, nested) {
  return `<div class="step-header">
    <span class="drag-handle" draggable="true" title="ドラッグして移動" aria-label="ドラッグして移動">⠿</span><div class="step-title">${title}</div>
    <div class="step-actions">
      <button data-action="up" title="上へ" aria-label="上へ">↑</button><button data-action="down" title="下へ" aria-label="下へ">↓</button>
      <button data-action="duplicate" title="複製" aria-label="複製">⧉</button>
      <button data-action="remove" class="remove" title="削除" aria-label="削除">×</button>
    </div>
  </div>`;
}

function variableSourceLabel(source) {
  if (source === "last_status") return "直前の結果";
  if (source === "card_response") return "指定カードの応答";
  if (source === "card_status") return "指定カードの結果";
  if (source === "output_port") return "出力ポート";
  if (source === "result_data") return "結果データ出力";
  if (source === "literal") return "固定の文字";
  return "直前の応答";
}

function resultDataSize() {
  const transport = $("#transport")?.value || state.settings.transport;
  const field = transport === "field_network" ? "#fn-result-size" : "#result-data-size";
  const fromForm = Number($(field)?.value);
  if (Number.isFinite(fromForm) && fromForm > 0) return fromForm;
  return Number(state.settings.result_data_size) || 0;
}

function resultFormatLabel(format) {
  if (format === "fixed") return "固定小数点";
  if (format === "hex") return "16進";
  return "整数";
}

function outputPortCaption() {
  const transport = $("#transport")?.value || state.settings.transport;
  if (transport === "field_network") return "ESO ポート";
  if (transport === "plclink") return "PLO ポート";
  return "出力ポート";
}

function collectCommandCards(steps, prefix = "", found = []) {
  (steps || []).forEach((step, index) => {
    const mark = `${prefix}${index + 1}`;
    if (step.type === "command") {
      const definition = state.catalog.find((item) => item.code === step.command);
      found.push({
        id: String(step.id),
        label: `${mark}. ${step.command} ${definition?.name || ""}`.trim(),
      });
    }
    if (step.type === "if") {
      collectCommandCards(step.then_steps, `${mark}-`, found);
      collectCommandCards(step.else_steps, `${mark}-`, found);
    }
    if (step.type === "loop") collectCommandCards(step.steps, `${mark}-`, found);
  });
  return found;
}

function variableChoices() {
  const names = [];
  const seen = new Set();
  const walk = (steps) => {
    for (const step of steps || []) {
      if (step.type === "variable") {
        const name = String(step.name || "").trim();
        if (name && !seen.has(name)) {
          seen.add(name);
          names.push(name);
        }
      }
      walk(step.steps);
      walk(step.then_steps);
      walk(step.else_steps);
    }
  };
  walk(state.steps);
  return names;
}

function argumentVariableName(step, key) {
  const name = step?.argument_variables?.[key];
  return typeof name === "string" ? name.trim() : "";
}

function argumentCanUseVariable(arg) {
  return arg.type === "string" || arg.type === "integer" || arg.type === "number";
}

function variableSelect(key, selected, label) {
  const names = variableChoices();
  if (selected && !names.includes(selected)) names.unshift(selected);
  if (!names.length) return "";
  const options = names.map((name) =>
    `<option value="${escapeHtml(name)}" ${selected === name ? "selected" : ""}>変数 ${escapeHtml(name)}</option>`
  ).join("");
  return `<select class="arg-bind" data-var="${escapeHtml(key)}" aria-label="${escapeHtml(label)}に使う変数">
    <option value="" ${selected ? "" : "selected"}>入力した値</option>${options}
  </select>`;
}

function argumentField(step, arg) {
  const value = argumentValue(step, arg);
  const variableName = argumentCanUseVariable(arg) ? argumentVariableName(step, arg.key) : "";
  const missingClass = argumentIsMissing(step, arg) ? "missing-arg" : "";
  const source = argumentCanUseVariable(arg) ? variableSelect(arg.key, variableName, arg.label) : "";
  if (arg.type === "enum") {
    return `<label class="${missingClass}">${escapeHtml(arg.label)}<select data-arg="${arg.key}">
      ${arg.options.map((option) => `<option value="${escapeHtml(option.value)}" ${String(value) === String(option.value) ? "selected" : ""}>${escapeHtml(option.label)}</option>`).join("")}
    </select></label>`;
  }
  if (variableName) {
    return `<label class="${missingClass}">${escapeHtml(arg.label)}${source}
      <input data-arg="${arg.key}" type="text" value="変数 ${escapeHtml(variableName)}" disabled></label>`;
  }
  const attrs = arg.type === "integer"
    ? `type="number" min="${arg.min}" max="${arg.max}" step="1"`
    : `type="text" maxlength="${arg.max_length || 1024}"`;
  return `<label class="${missingClass}">${escapeHtml(arg.label)}${source}<input data-arg="${arg.key}" ${attrs} value="${escapeHtml(value)}"></label>`;
}

function childArea(step, key, label) {
  const isCompact = state.viewMode === "compact";
  const controlOptions = `
    <optgroup label="制御カード">
      <option value="control:delay">WAIT｜待機</option>
      <option value="control:if">IF｜条件分岐</option>
      <option value="control:loop">LOOP｜くり返し</option>
      <option value="control:break">BREAK｜ループを抜ける</option>
      <option value="control:note">MEMO｜メモ</option>
      <option value="control:variable">VAR｜変数</option>
    </optgroup>`;
  const commandOptions = catalogGroups(state.catalog.filter((item) => commandAvailable(item))).map((group) =>
    `<optgroup label="${escapeHtml(group.label)}">${group.items.map(
      (item) => `<option value="command:${item.code}">${item.code}｜${escapeHtml(item.name)}</option>`
    ).join("")}</optgroup>`
  ).join("");
  return `<div class="nested-area" data-child="${key}">
    <h3>${label}</h3>
    <div class="nested-cards drop-list" data-parent-id="${step.id}" data-child-key="${key}">${(step[key] || []).map((child) => stepHtml(child, true)).join("")}</div>
    ${isCompact ? "" : `<div class="nested-add"><select data-child-select="${key}">${controlOptions}${commandOptions}</select>
      <button data-add-child="${key}" class="icon-button" aria-label="カードを追加">＋ カード追加</button>
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
      const applyArg = () => {
        if (input.disabled) return;
        located.step.arguments[input.dataset.arg] = input.value;
        const definition = state.catalog.find((item) => item.code === located.step.command);
        const controls = visibleArguments(definition).some((arg) => arg.show_if?.key === input.dataset.arg);
        if (controls && input.tagName === "SELECT") renderSequence();
        else {
          refreshCardMissing(card, located.step);
          scheduleDraftSave();
        }
      };
      input.addEventListener("input", applyArg);
      input.addEventListener("change", applyArg);
    });
    card.querySelectorAll(":scope > .step-body [data-field]").forEach((input) => {
      const applyField = (event) => {
        if (input.disabled) return;
        if (input.type === "checkbox") located.step[input.dataset.field] = input.checked;
        else if (input.type === "number") {
          let number = Number(input.value);
          if (input.dataset.field === "offset") {
            number = Number.isFinite(number) ? Math.max(0, number - (Math.abs(number) % 2)) : 0;
            input.value = String(number);
          }
          located.step[input.dataset.field] = number;
        }
        else if (input.dataset.field === "raw") located.step.arguments.raw = input.value;
        else located.step[input.dataset.field] = input.value;
        if (input.dataset.field === "source" || (input.dataset.field === "name" && event.type === "change")) {
          renderSequence();
          return;
        }
        refreshCardMissing(card, located.step);
        scheduleDraftSave();
      };
      input.addEventListener("input", applyField);
      input.addEventListener("change", applyField);
    });
    card.querySelectorAll(":scope > .step-body [data-var]").forEach((select) => {
      select.addEventListener("change", () => {
        if (!located.step.argument_variables || typeof located.step.argument_variables !== "object") {
          located.step.argument_variables = {};
        }
        const key = select.dataset.var;
        if (select.value) located.step.argument_variables[key] = select.value;
        else delete located.step.argument_variables[key];
        renderSequence();
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
  const destination = targetList(dropList);
  if (!source || !destination) return false;
  if (source.step.type === "break" && !listIsInsideLoop(destination)) return false;
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
  if (action === "remove") {
    const snapshot = cloneData(state.steps);
    const nextId = state.nextId;
    found.list.splice(found.index, 1);
    renderSequence();
    showToast("カードを削除しました", () => {
      state.steps = snapshot;
      state.nextId = nextId;
      renderSequence();
    });
    return;
  }
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

function ensureStepIds(step) {
  const numeric = Number(step.id);
  if (!Number.isFinite(numeric) || numeric <= 0) step.id = state.nextId++;
  else if (numeric >= state.nextId) state.nextId = numeric + 1;
  for (const key of ["steps", "then_steps", "else_steps"]) (step[key] || []).forEach(ensureStepIds);
}

function cloneData(value) {
  return JSON.parse(JSON.stringify(value));
}

function persistSequenceDraft() {
  if (!state.draftReady) return;
  try {
    localStorage.setItem("vtv-sequence-draft", JSON.stringify({
      version: 1,
      nextId: state.nextId,
      steps: state.steps,
      name: state.sequenceName || "",
      libraryId: state.sequenceLibraryId || "",
      trialId: state.trialId || "",
      trialName: $("#trial-name")?.value || state.trialName || "",
    }));
  } catch (_) {}
}

function scheduleDraftSave() {
  if (!state.draftReady) return;
  clearTimeout(state.draftTimer);
  state.draftTimer = setTimeout(persistSequenceDraft, 250);
}

function restoreSequenceDraft() {
  try {
    const data = JSON.parse(localStorage.getItem("vtv-sequence-draft") || "null");
    if (data && Array.isArray(data.steps)) {
      const steps = data.steps;
      const savedNext = Number(data.nextId);
      if (Number.isFinite(savedNext) && savedNext > state.nextId) state.nextId = savedNext;
      steps.forEach(ensureStepIds);
      state.steps = steps;
      state.sequenceName = typeof data.name === "string" ? data.name : "";
      state.sequenceLibraryId = typeof data.libraryId === "string" ? data.libraryId : "";
      state.trialId = typeof data.trialId === "string" ? data.trialId : "";
      state.trialName = typeof data.trialName === "string" ? data.trialName : "";
    }
  } catch (_) {}
  state.draftReady = true;
}

function hideToast() {
  clearTimeout(state.undoTimer);
  state.undoTimer = null;
  state.undoAction = null;
  $("#undo-toast")?.classList.add("hidden");
}

function showToast(message, onUndo = null) {
  state.undoAction = onUndo;
  const toast = $("#undo-toast");
  if (!toast) return;
  $("#undo-toast-message").textContent = message;
  $("#undo-toast-button")?.classList.toggle("hidden", !onUndo);
  toast.classList.remove("hidden");
  clearTimeout(state.undoTimer);
  state.undoTimer = setTimeout(hideToast, onUndo ? 8000 : 4500);
}

function showRunHint(message) {
  const hint = $("#run-hint");
  if (!hint) return;
  hint.textContent = message || "";
  hint.classList.toggle("hidden", !message);
}

function selectSettingsPage(page) {
  const transport = $("#transport")?.value || state.settings.transport || "tcp";
  const advanced = transport === "plclink" || transport === "field_network";
  state.settingsPage = advanced && page ? page : "connection";
  document.querySelectorAll("[data-settings-tab]").forEach((button) => {
    const tab = button.dataset.settingsTab;
    const available = tab === "connection" || advanced;
    button.classList.toggle("hidden", !available);
    const active = tab === state.settingsPage;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll("[data-settings-chunk]").forEach((section) => {
    section.classList.toggle("page-off", section.dataset.settingsChunk !== state.settingsPage);
  });
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
    pli_address: Number($("#pli-address")?.value) || 0,
    pli_port_count: Number($("#pli-port-count")?.value) || 32,
    plo_address: Number($("#plo-address").value),
    plo_port_count: Number($("#plo-port-count").value),
    busy_port: (() => {
      if (isFn) return Number($("#busy-port").value) || 1;
      const signals = readPlcLinkStatusSignalsFromForm();
      const busy = signals.find((item) => item.role === "busy");
      return Number(busy?.plo_port) || 1;
    })(),
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
    plclink_status_signals: isFn
      ? normalizePlcLinkStatusSignals(
        state.settings.plclink_status_signals,
        Number($("#busy-port")?.value) || 1,
      )
      : readPlcLinkStatusSignalsFromForm(),
    ...readPortNamesFromForm(),
  };
}

function openSettingsDialog() {
  const dialog = $("#settings-dialog");
  if (!dialog) return;
  applySettingsToForm();
  syncTransportUi();
  renderProfileSelect();
  openDialog(dialog, "#transport");
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
    syncActiveProfile(state.settings);
    refreshMappedWatchItems();
    renderWatchList();
    renderTimingChannelList();
    closeSettingsDialog();
    void applySavedConnectionSettings();
  } catch (error) {
    console.error(error);
    const resultEl = $("#connection-test-result");
    if (resultEl) {
      resultEl.className = "test-result error";
      resultEl.textContent = error.message || String(error);
    } else {
      showToast(error.message || String(error));
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
    state.settings.plclink_status_signals = normalizePlcLinkStatusSignals(
      state.settings.plclink_status_signals,
      state.settings.busy_port ?? 1,
    );
    state.settings.pli_port_names = normalizePortNames(state.settings.pli_port_names);
    state.settings.plo_port_names = normalizePortNames(state.settings.plo_port_names);
    state.settings.esi_port_names = normalizePortNames(state.settings.esi_port_names);
    state.settings.eso_port_names = normalizePortNames(state.settings.eso_port_names);
    const busy = state.settings.plclink_status_signals.find((item) => item.role === "busy");
    if (busy) state.settings.busy_port = Number(busy.plo_port) || 1;
    state.statusSignalDraft = state.settings.fn_status_signals.map((item) => ({ ...item }));
    state.plclinkStatusSignalDraft = state.settings.plclink_status_signals.map((item) => ({ ...item }));
    syncPortNameDraftFromSettings(state.settings);
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
  $("#pli-address").value = s.pli_address ?? 0;
  $("#pli-port-count").value = s.pli_port_count ?? 32;
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
  state.plclinkStatusSignalDraft = normalizePlcLinkStatusSignals(
    s.plclink_status_signals,
    s.busy_port ?? 1,
  );
  renderStatusSignalTable();
  renderPlcLinkStatusSignalTable();
  syncPortNameDraftFromSettings(s);
  renderPortNameTables({ capture: false });
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
  $("#timing-tab-button") && ($("#timing-tab-button").disabled = !isMapped);
  updateWatchNote();
  if (!isMapped) {
    stopWatch(true);
    selectMonitorTab("log");
  } else {
    refreshMappedWatchItems();
    renderWatchList();
    renderTimingChannelList();
  }
  applyLayoutMode();
  renderPalette();
  renderSequence();
  syncLocalIoPanel();
  selectSettingsPage(state.settingsPage);
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
    state.fnLive = true;
    state.fnLiveHost = settings.host;
    state.fnLivePort = Number(settings.port) || 0;
    localStorage.setItem("vtv-settings", JSON.stringify(settings));
    refreshMappedWatchItems();
    renderWatchList();
    refreshConnectionBadge();
    return data;
  } catch (error) {
    resultEl.className = "test-result error";
    resultEl.textContent = error.message;
    state.fnLive = false;
    markConnectionVerified(false, settings);
    refreshConnectionBadge();
    return null;
  }
}

function updateVirtualIoRange() {
  const hint = $("#virtual-io-range");
  if (!hint) return;
  const pli = Number($("#pli-address")?.value) || 0;
  const pliCount = Math.max(1, Number($("#pli-port-count")?.value) || 32);
  const plo = Number($("#plo-address")?.value) || 0;
  const ploCount = Math.max(1, Number($("#plo-port-count")?.value) || 32);
  hint.textContent = `仮想入力 M${pli}–M${pli + pliCount - 1} / 仮想出力 M${plo}–M${plo + ploCount - 1}。`
    + "VTV の仮想I/Oと同じ先頭にしてください。";
}

function updateBusyAddressHint() {
  const hint = $("#busy-address-hint");
  if (!hint) return;
  const body = $("#plclink-status-signal-body");
  if (body?.querySelector("tr[data-plclink-status-index]")) {
    syncPlcLinkStatusSignalDraftFromDom();
  }
  const plo = Number($("#plo-address").value) || 0;
  const portCount = Number($("#plo-port-count")?.value) || 32;
  const busySignal = state.plclinkStatusSignalDraft.find((item) => item.role === "busy");
  const port = Number(busySignal?.plo_port) || Number($("#busy-port").value) || 1;
  const busy = plo + port - 1;
  const count = state.plclinkStatusSignalDraft.length;
  hint.textContent = `BUSY 実アドレス: M${busy}（PLO先頭 M${plo} + Port ${port} - 1 / ポート数 ${portCount}）。`
    + `監視信号 ${count} 件。VTV の「ステータス信号」割付と一致させてください。`;
  updateVirtualIoRange();
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
    settings.pli_address ?? 0,
    settings.pli_port_count ?? 32,
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

function settingsMatchVerified(settings = state.settings) {
  return Boolean(
    settings?.host
    && state.connectionVerified
    && state.verifiedSettingsKey === settingsKey(settings),
  );
}

function plcLinkListeningHere() {
  return state.softPlcListening
    && Number(state.softPlcPort) === Number(state.settings.port);
}

function fieldNetworkLiveHere() {
  return state.fnLive
    && state.fnLiveHost === state.settings.host
    && Number(state.fnLivePort) === Number(state.settings.port);
}

function restoreConnectionState() {
  try {
    const saved = JSON.parse(localStorage.getItem("vtv-connection-verified"));
    const key = settingsKey(state.settings);
    if (saved?.verified && saved?.key === key && state.settings.host) {
      state.connectionVerified = true;
      state.verifiedSettingsKey = key;
    }
  } catch (_) {}
  refreshConnectionBadge();
}

function refreshConnectionBadge() {
  if (state.running) return;
  const remembered = settingsMatchVerified();
  const transport = state.settings.transport || "tcp";
  if (transport === "plclink") {
    if (plcLinkListeningHere() && state.softPlcClientCount > 0) {
      setConnection("connected");
      return;
    }
    if (plcLinkListeningHere()) {
      setConnection("listening");
      return;
    }
    setConnection(remembered ? "remembered" : "disconnected");
    return;
  }
  if (transport === "field_network") {
    if (fieldNetworkLiveHere()) {
      setConnection("connected");
      return;
    }
    setConnection(remembered ? "remembered" : "disconnected");
    return;
  }
  setConnection(remembered ? "remembered" : "disconnected");
}

function startSoftPlcStatusPoll() {
  if (state.softPlcPollTimer) return;
  state.softPlcPollTimer = setInterval(() => {
    pollLinkStatus();
  }, 1500);
  pollLinkStatus();
}

async function pollLinkStatus() {
  if (state.running) return;
  const transport = state.settings.transport;
  try {
    if (transport === "plclink") {
      const response = await fetch("/api/plclink/status");
      if (!response.ok) return;
      const data = await response.json();
      state.softPlcListening = data.status === "listening";
      state.softPlcClientCount = Number(data.client_count) || 0;
      state.softPlcPort = Number(data.port) || 0;
      refreshConnectionBadge();
      return;
    }
    if (transport === "field_network") {
      const response = await fetch("/api/field-network/status");
      if (!response.ok) return;
      const data = await response.json();
      state.fnLive = data.status === "connected";
      state.fnLiveHost = data.host || "";
      state.fnLivePort = Number(data.port) || 0;
      refreshConnectionBadge();
    }
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
    state.softPlcListening = true;
    state.softPlcPort = Number(data.port) || Number(settings.port) || 0;
    state.softPlcClientCount = Number(data.client_count) || 0;
    if (updateBadge) {
      if (state.softPlcClientCount > 0) markConnectionVerified(true, settings);
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
    if (settings.transport === "field_network") {
      state.fnLive = true;
      state.fnLiveHost = settings.host;
      state.fnLivePort = Number(settings.port) || 0;
    }
    if (settings.transport === "plclink") {
      state.softPlcListening = true;
      state.softPlcPort = Number(settings.port) || 0;
      state.softPlcClientCount = Math.max(state.softPlcClientCount, 1);
    }
    refreshMappedWatchItems();
    renderWatchList();
    refreshConnectionBadge();
    if (showMessage && resultEl) {
      resultEl.className = "test-result success";
      resultEl.textContent = data.message || "接続に成功しました。";
    }
    return true;
  } catch (error) {
    if (settings.transport === "field_network") state.fnLive = false;
    if (settings.transport === "plclink") state.softPlcClientCount = 0;
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

function runBlockReason(settings) {
  if (!settings.host) {
    return settings.transport === "plclink"
      ? "待受アドレスを入力してください。"
      : "装置 IP を入力してください。";
  }
  if (!state.steps.length) return "実行するカードを追加してください。";
  if (findOrphanBreak(state.steps)) return "BREAK はループの中に置いてください。";
  const variableProblem = findVariableProblem(state.steps, settings.transport);
  if (variableProblem) return variableProblem;
  const missing = findMissingArgument(state.steps);
  if (missing) return `${missing.command}: ${missing.label}を入力してください。`;
  if (settings.transport === "plclink" || settings.transport === "field_network") {
    const unsupported = findUnsupportedPlcLinkCommand(state.steps);
    if (unsupported) return `${unsupported.command}: ${unsupported.reason}`;
  }
  if (!settingsMatchVerified(settings)) {
    return "この設定は未確認です。接続設定で接続テストをしてください。";
  }
  return "";
}

function runSequence() {
  if (state.running) {
    showRunHint("実行中です。終わるか停止してから、もう一度実行してください。");
    return;
  }
  let settings;
  try {
    settings = readSettingsForm();
  } catch (error) {
    showRunHint(error.message || "接続設定を確認してください。");
    return;
  }
  state.settings = settings;
  const reason = runBlockReason(settings);
  if (reason) {
    showRunHint(reason);
    if (!settings.host) {
      openSettingsDialog();
      selectSettingsPage("connection");
    }
    return;
  }
  showRunHint("");
  clearExecutionStyles();
  clearLog({ undo: false });
  setRunProgress(null);
  state.lastResponse = "";
  state.runRecorded = false;
  state.runStartedAt = performance.now();
  state.runPositionText = "";
  $("#run-summary")?.classList.add("hidden");
  setRunning(true);
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  state.socket = new WebSocket(`${protocol}://${location.host}/ws`);
  state.socket.addEventListener("open", () => state.socket.send(JSON.stringify({
    type: "execute", payload: { settings: state.settings, steps: cleanSteps(state.steps) },
  })));
  state.socket.addEventListener("message", (event) => handleEvent(JSON.parse(event.data)));
  state.socket.addEventListener("error", () => {
    addLog("error", "ERR", "WebSocket接続に失敗しました");
    showRunHint("WebSocket接続に失敗しました。");
    if (state.running) {
      finishRun("failed", { message: "WebSocket接続に失敗しました", last_response: state.lastResponse });
    }
    setRunning(false);
  });
  state.socket.addEventListener("close", () => {
    if (!state.running) return;
    finishRun("failed", { message: "実行中に通信が切れました", last_response: state.lastResponse });
    showRunHint("実行中に通信が切れました。実行は中断されています。");
    setRunning(false);
  });
}

function findUnsupportedPlcLinkCommand(steps) {
  const transport = state.settings.transport || $("#transport")?.value;
  for (const step of steps) {
    if (step.type === "command") {
      const definition = state.catalog.find((item) => item.code === step.command);
      const supported = transport === "field_network"
        ? !!definition?.field_network_supported
        : !!definition?.plclink_supported;
      if (!supported) {
        return {
          command: step.command,
          reason: transport === "field_network"
            ? (definition?.field_network_reason || definition?.plclink_reason || "Field Networkでは使用できません")
            : (definition?.plclink_reason || "PLCLINKでは使用できません"),
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
  return steps.map((step) => {
    const next = { ...step };
    if (next.id !== undefined && next.id !== null) next.id = String(next.id);
    for (const key of ["steps", "then_steps", "else_steps"]) {
      if (next[key]) next[key] = cleanSteps(next[key]);
    }
    return next;
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
      if (state.settings.transport === "field_network") {
        state.fnLive = true;
        state.fnLiveHost = state.settings.host;
        state.fnLivePort = Number(state.settings.port) || 0;
      }
      if (state.settings.transport === "plclink") {
        state.softPlcListening = true;
        state.softPlcPort = Number(state.settings.port) || 0;
        state.softPlcClientCount = Math.max(state.softPlcClientCount, 1);
      }
      setConnection("connected");
    } else if (event.state === "disconnected") {
      refreshConnectionBadge();
    }
    if (event.state === "disconnected" && state.socket?.readyState === WebSocket.OPEN) {
      state.socket.close();
    }
  }
  if (event.type === "step_started") {
    document.querySelectorAll(".step-card.active").forEach((card) => card.classList.remove("active"));
    const card = stepCardByEvent(event);
    if (card) {
      card.classList.remove("done", "failed");
      card.classList.add("active");
      card.scrollIntoView({ block: "nearest" });
    }
    setRunProgress(event);
  }
  if (event.type === "step_completed") {
    const card = stepCardByEvent(event);
    card?.classList.remove("active");
    card?.classList.add("done");
  }
  if (event.type === "tx") addLog("tx", "TX", event.display, event.id);
  if (event.type === "rx") {
    state.lastResponse = String(event.response ?? "");
    addLog("rx", "RX", event.response, event.id);
  }
  if (event.type === "note") addLog("info", "MEMO", event.message || "メモ", event.id);
  if (event.type === "variable") {
    const shown = event.source === "output_port"
      ? (String(event.value) === "1" ? "ON" : "OFF")
      : (event.value ?? "");
    addLog("info", "VAR", `${event.name} = ${shown}`, event.id);
  }
  if (event.type === "loop_iteration") addLog("info", "LOOP", `${event.iteration} / ${event.count}`, event.id);
  if (event.type === "loop_break") addLog("info", "BREAK", "条件によりループを終了しました", event.id);
  if (event.type === "condition") addLog("info", "IF", `${event.matched ? "一致" : "不一致"} (${event.actual || "空"})`, event.id);
  if (event.type === "sequence_completed") {
    addLog("info", "DONE", "シーケンスが完了しました");
    finishRun("success", event);
    setRunning(false);
  }
  if (event.type === "sequence_stopped") {
    addLog("info", "STOP", event.message);
    finishRun("stopped", event);
    setRunning(false);
  }
  if (event.type === "sequence_failed") {
    const card = document.querySelector(".step-card.active") || stepCardByEvent(event);
    if (card) {
      card.classList.remove("active");
      card.classList.add("failed");
      card.scrollIntoView({ block: "nearest" });
    }
    addLog("error", "ERR", event.message, card?.dataset.id || event.id);
    showRunHint(event.message || "シーケンスが失敗しました");
    finishRun("failed", event);
    setRunning(false);
  }
}

function stepCardByEvent(event) {
  if (event?.id !== undefined && event?.id !== null && event.id !== "") {
    const card = document.querySelector(`.step-card[data-id="${CSS.escape(String(event.id))}"]`);
    if (card) return card;
  }
  if (!event?.index) return null;
  return document.querySelectorAll(".step-card")[event.index - 1] || null;
}

function setRunProgress(event) {
  const el = $("#run-progress");
  if (!el) return;
  if (!event) {
    el.classList.add("hidden");
    el.textContent = "";
    el.removeAttribute("title");
    return;
  }
  const position = event.position || event.index || "?";
  const total = event.total ? `/${event.total}` : "";
  const text = `${position}${total} ${event.label || ""}`.trim();
  state.runPositionText = text;
  el.textContent = text;
  el.title = text;
  el.classList.remove("hidden");
}

const CONNECTION_LABELS = {
  connected: "接続中",
  connecting: "接続中…",
  listening: "待受中",
  remembered: "前回成功",
  disconnected: "未接続",
};

function setConnection(status) {
  state.connectionStatus = status;
  const badge = $("#connection-badge");
  if (badge) {
    badge.className = `badge ${status}`;
    badge.textContent = CONNECTION_LABELS[status] || "未接続";
    if (status === "remembered") {
      badge.title = "この設定で以前接続に成功しています。いまの通信は確認していません。";
    } else if (status === "listening") {
      badge.title = "疑似 PLC は待受中です。VTV からの接続を待っています。";
    } else {
      badge.title = "";
    }
  }
  const transport = state.settings.transport;
  const watchAlive = transport === "plclink"
    ? plcLinkListeningHere()
    : transport === "field_network"
      ? fieldNetworkLiveHere()
      : false;
  if (state.watchRunning && !watchAlive && status !== "connecting") stopWatch(true);
}

function setRunning(running) {
  state.running = running;
  const runButton = $("#run-button");
  const stopButton = $("#stop-button");
  if (runButton) {
    runButton.disabled = running;
    runButton.title = running
      ? "実行中はもう一度実行できません"
      : "実行（Ctrl+Enter）";
  }
  if (stopButton) {
    stopButton.disabled = !running;
    stopButton.title = "停止（Ctrl+.）";
  }
  if (!running) {
    setRunProgress(null);
    refreshConnectionBadge();
  }
}

function localIoCode() {
  const transport = state.settings?.transport || $("#transport")?.value;
  if (transport === "plclink") return "PLI";
  if (transport === "field_network") return "ESI";
  return null;
}

function syncLocalIoPanel() {
  const panel = $("#local-io-panel");
  if (!panel) return;
  const code = localIoCode();
  panel.classList.toggle("hidden", !code);
  if ($("#local-io-label") && code) $("#local-io-label").textContent = code;
  if (!code) return;
  const names = normalizePortNames(
    code === "PLI" ? state.settings.pli_port_names : state.settings.esi_port_names,
  );
  const named = Object.entries(names)
    .sort((a, b) => Number(a[0]) - Number(b[0]))
    .slice(0, 8)
    .map(([port, name]) => `${port}:${name}`);
  panel.title = named.length
    ? `${code} ポートを直接 ON/OFF（例: ${named.join(", ")}）`
    : `${code} ポートを直接 ON/OFF します（タスク実行中も可）`;
}

async function setLocalIoPorts(stateValue) {
  const code = localIoCode();
  if (!code) return;
  const ports = ($("#local-io-ports")?.value || "").trim();
  if (!ports) {
    addLog("error", "ERR", `${code} ポート番号を入力してください`);
    return;
  }
  const settings = (() => {
    try {
      return readSettingsForm();
    } catch (_) {
      return state.settings;
    }
  })();
  if (!settings?.host && code === "ESI") {
    addLog("error", "ERR", "接続設定の装置 IP を確認してください");
    return;
  }
  try {
    const response = await fetch("/api/local-io", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        settings,
        code,
        state: stateValue ? "1" : "0",
        ports,
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = payload.detail || payload.message || response.statusText;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    addLog("tx", "TX", payload.display || `${code}${stateValue ? "ON" : "OFF"}[${ports}]`);
    for (const line of payload.responses || [payload.status || "AK"]) {
      addLog("rx", "RX", line);
    }
  } catch (error) {
    addLog("error", "ERR", `${code} 失敗: ${error.message || error}`);
  }
}

function addLog(_css, kind, data, stepId = "") {
  const now = new Date();
  state.logs.push({
    timestamp: formatTimestamp(now),
    kind,
    data: String(data ?? ""),
    stepId: stepId ? String(stepId) : "",
  });
  paintLog();
}

function logCss(kind) {
  if (kind === "TX") return "tx";
  if (kind === "RX") return "rx";
  if (kind === "ERR") return "error";
  return "info";
}

function paintLog() {
  const log = $("#log");
  if (!log) return;
  const filter = state.logFilter || "all";
  const entries = state.logs
    .map((entry, index) => ({ entry, index }))
    .filter(({ entry }) => logMatches(entry, filter));
  if (!entries.length) {
    log.innerHTML = `<div class="log-empty">${state.logs.length ? "この種別のログはありません。" : "実行すると送受信内容が表示されます。"}</div>`;
    return;
  }
  log.innerHTML = entries.map(({ entry, index }) => {
    const time = String(entry.timestamp || "").slice(11);
    const copy = entry.kind === "ERR"
      ? `<button type="button" class="log-copy" data-log-copy="${index}">コピー</button>`
      : "";
    const jump = entry.stepId
      ? ` log-jump" data-log-step="${escapeHtml(entry.stepId)}" role="button" tabindex="0" title="このカードへ移動"`
      : `"`;
    return `<div class="log-row ${logCss(entry.kind)}${jump}>
      <span class="log-time">${escapeHtml(time)}</span><span class="log-kind">${escapeHtml(entry.kind)}</span><span class="log-data">${escapeHtml(entry.data)}</span>${copy}
    </div>`;
  }).join("");
  log.scrollTop = log.scrollHeight;
}

function clearLog(options = {}) {
  const undo = options.undo !== false && state.logs.length > 0;
  const snapshot = undo ? state.logs.map((entry) => ({ ...entry })) : null;
  state.logs = [];
  paintLog();
  if (snapshot) {
    showToast("通信ログを消去しました", () => {
      state.logs = snapshot;
      paintLog();
    });
  }
}
function clearExecutionStyles() {
  document.querySelectorAll(".step-card").forEach((card) => {
    card.classList.remove("active", "done", "failed", "log-target");
  });
}

function openLogExport() {
  if (!state.logs.length) {
    showToast("出力できる通信ログがありません。");
    return;
  }
  openDialog($("#log-export-dialog"), "#log-export-format");
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
  const blob = new Blob([JSON.stringify({
    version: 1,
    name: state.sequenceName || "",
    steps: cleanSteps(state.steps),
  }, null, 2)], { type: "application/json" });
  const link = document.createElement("a"); link.href = URL.createObjectURL(blob);
  link.download = "vtv-sequence.json"; link.click(); URL.revokeObjectURL(link.href);
}

async function loadSequence(event) {
  const input = event.target;
  const file = input.files?.[0];
  if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    if (!Array.isArray(data.steps)) throw new Error("steps がありません");
    if (state.steps.length && !confirm("現在のシーケンスを読み込んだ内容で置き換えますか？")) return;
    const snapshot = cloneData(state.steps);
    const nextId = state.nextId;
    const previousName = state.sequenceName;
    const previousLibraryId = state.sequenceLibraryId;
    state.steps = data.steps;
    state.steps.forEach(assignIds);
    if (typeof data.name === "string") {
      state.sequenceName = data.name;
      state.sequenceLibraryId = "";
      const nameInput = $("#sequence-name");
      if (nameInput) nameInput.value = data.name;
    }
    renderSequence();
    renderSequenceLibrary();
    showToast("シーケンスを読み込みました", () => {
      state.steps = snapshot;
      state.nextId = nextId;
      state.sequenceName = previousName;
      state.sequenceLibraryId = previousLibraryId;
      const nameInput = $("#sequence-name");
      if (nameInput) nameInput.value = previousName || "";
      renderSequence();
      renderSequenceLibrary();
    });
  } catch (error) {
    showToast(`読み込めません: ${error.message}`);
  } finally {
    input.value = "";
  }
}

function listIsInsideLoop(target, list = state.steps, ancestorLoop = false) {
  if (list === target) return ancestorLoop;
  for (const step of list) {
    const loop = ancestorLoop || step.type === "loop";
    if (step.steps && listIsInsideLoop(target, step.steps, loop)) return true;
    if (step.then_steps && listIsInsideLoop(target, step.then_steps, ancestorLoop)) return true;
    if (step.else_steps && listIsInsideLoop(target, step.else_steps, ancestorLoop)) return true;
  }
  return false;
}

function findOrphanBreak(steps, insideLoop = false) {
  for (const step of steps) {
    if (step.type === "break" && !insideLoop) return true;
    if (step.steps && findOrphanBreak(step.steps, insideLoop || step.type === "loop")) return true;
    if (step.then_steps && findOrphanBreak(step.then_steps, insideLoop)) return true;
    if (step.else_steps && findOrphanBreak(step.else_steps, insideLoop)) return true;
  }
  return false;
}

function conditionEquals(step, condition) {
  if (!condition || condition.equals === undefined) return false;
  return String(step.arguments?.[condition.key] ?? "") === String(condition.equals);
}

function argumentIsRequired(step, arg) {
  if (!arg?.optional) return true;
  return conditionEquals(step, arg.required_if);
}

function argumentIsMissing(step, arg) {
  if (argumentVariableName(step, arg.key)) return false;
  if (!argumentIsRequired(step, arg) || !argumentVisible(step, arg)) return false;
  const value = argumentValue(step, arg);
  return value === undefined || value === null || String(value).trim() === "";
}

function missingLabels(step) {
  if (step?.type !== "command") return [];
  const definition = state.catalog.find((item) => item.code === step.command);
  if (!definition) return [];
  return visibleArguments(definition)
    .filter((arg) => argumentIsMissing(step, arg))
    .map((arg) => arg.label);
}

function findVariableProblem(steps, transport) {
  const names = new Set(variableChoices());
  const walk = (items) => {
    for (const step of items || []) {
      if (step.type === "variable") {
        if (!String(step.name || "").trim()) return "変数カードに名前を入力してください。";
        if ((step.source === "card_response" || step.source === "card_status") && !step.card_id) {
          return "変数カードで、結果を取るカードを選んでください。";
        }
        if (step.source === "output_port" && transport === "tcp") {
          return "TCP では出力ポートを変数に入れられません。コマンドの応答を選んでください。";
        }
        if (step.source === "result_data" && transport === "tcp") {
          return "TCP では結果データ出力を変数に入れられません。コマンドの応答を選んでください。";
        }
      }
      if (step.type === "command" && step.argument_variables) {
        for (const name of Object.values(step.argument_variables)) {
          if (name && !names.has(String(name).trim())) return `変数「${name}」がありません。`;
        }
      }
      for (const key of ["steps", "then_steps", "else_steps"]) {
        if (step[key]) {
          const nested = walk(step[key]);
          if (nested) return nested;
        }
      }
    }
    return "";
  };
  return walk(steps);
}

function findMissingArgument(steps) {
  for (const step of steps) {
    const labels = missingLabels(step);
    if (labels.length) return { command: step.command, label: labels[0] };
    for (const key of ["steps", "then_steps", "else_steps"]) {
      if (step[key]) {
        const nested = findMissingArgument(step[key]);
        if (nested) return nested;
      }
    }
  }
  return null;
}

function refreshCardMissing(card, step) {
  if (!card || step?.type !== "command") return;
  const labels = missingLabels(step);
  card.classList.toggle("incomplete-step", labels.length > 0);
  const definition = state.catalog.find((item) => item.code === step.command);
  card.querySelectorAll("[data-arg]").forEach((input) => {
    const arg = visibleArguments(definition).find((item) => item.key === input.dataset.arg);
    input.closest("label")?.classList.toggle("missing-arg", !!(arg && argumentIsMissing(step, arg)));
  });
  let note = card.querySelector(".missing-note");
  if (!labels.length) {
    note?.remove();
    return;
  }
  if (!note) {
    note = document.createElement("p");
    note.className = "step-warning missing-note";
    const body = card.querySelector(":scope > .step-body");
    if (body) body.prepend(note);
    else card.append(note);
  }
  note.textContent = `未入力: ${labels.join("、")}`;
}

function paletteCommandButton(item, transport, isMapped) {
  const favorite = (state.favorites || []).includes(item.code);
  const codeLabel = isMapped
    ? `${item.local_io ? item.code : (item.plclink_code ?? item.code)}：`
    : item.code;
  const mode = item.local_io
    ? "ローカルI/O"
    : (transport === "field_network" ? "FNコマンド" : "PLCLINKコマンド");
  return `<div class="palette-row">
    <button class="palette-card palette-command${commandAvailable(item, transport) ? "" : " unavailable"}" data-code="${escapeHtml(item.code)}" type="button">
      <span class="command-code">${escapeHtml(String(codeLabel))}</span>
      <span class="command-name">${escapeHtml(item.name)}</span>
      ${isMapped ? `<small class="plclink-code">${mode}</small>` : ""}
    </button>
    <button type="button" class="favorite-toggle" data-favorite="${escapeHtml(item.code)}" aria-pressed="${favorite ? "true" : "false"}" aria-label="${favorite ? "お気に入りを外す" : "お気に入りに追加"}">${favorite ? "★" : "☆"}</button>
  </div>`;
}

function unsupportedCommandReason(item, transport) {
  if (!item) return "この通信方式では使用できません。";
  if (transport === "field_network") {
    return item.field_network_reason || item.plclink_reason || "Field Network では使用できません。";
  }
  if (transport === "plclink") return item.plclink_reason || "PLCLINK では使用できません。";
  return "TCP では使用できません。";
}

function toggleFavorite(code) {
  const list = state.favorites || [];
  state.favorites = list.includes(code) ? list.filter((item) => item !== code) : [...list, code];
  try { localStorage.setItem("vtv-palette-favorites", JSON.stringify(state.favorites)); } catch (_) {}
  renderPalette();
}

function logMatches(entry, filter) {
  if (filter === "tx") return entry.kind === "TX";
  if (filter === "rx") return entry.kind === "RX";
  if (filter === "error") return entry.kind === "ERR";
  if (filter === "info") return !["TX", "RX", "ERR"].includes(entry.kind);
  return true;
}

function onLogClick(event) {
  const button = event.target.closest("[data-log-copy]");
  if (button) {
    const entry = state.logs[Number(button.dataset.logCopy)];
    if (!entry) return;
    const text = `${entry.timestamp} ${entry.kind} ${entry.data}`;
    const done = () => showToast("失敗行をコピーしました。");
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(() => showToast(text));
      return;
    }
    showToast(text);
    return;
  }
  const row = event.target.closest("[data-log-step]");
  if (row) focusStepCard(row.dataset.logStep);
}

function onLogKeydown(event) {
  if (event.key !== "Enter" && event.key !== " ") return;
  const row = event.target.closest("[data-log-step]");
  if (!row) return;
  event.preventDefault();
  focusStepCard(row.dataset.logStep);
}

function focusStepCard(id) {
  const card = document.querySelector(`.step-card[data-id="${CSS.escape(String(id))}"]`);
  if (!card) {
    showToast("対応するカードが見つかりません。");
    return;
  }
  document.querySelectorAll(".step-card.log-target").forEach((item) => item.classList.remove("log-target"));
  card.classList.add("log-target");
  card.scrollIntoView({ block: "center" });
}

function readJsonStore(key, fallback) {
  try {
    const data = JSON.parse(localStorage.getItem(key) || "null");
    return data && typeof data === "object" ? data : fallback;
  } catch (_) {
    return fallback;
  }
}

function newLocalId() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function profileStore() {
  const data = readJsonStore("vtv-connection-profiles", { activeId: "", items: [] });
  if (!Array.isArray(data.items)) data.items = [];
  return data;
}

function saveProfileStore(data) {
  try { localStorage.setItem("vtv-connection-profiles", JSON.stringify(data)); } catch (_) {}
}

function renderProfileSelect() {
  const select = $("#profile-select");
  if (!select) return;
  const data = profileStore();
  select.innerHTML = `<option value="">（プロファイルなし）</option>${data.items.map((item) =>
    `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`
  ).join("")}`;
  select.value = data.items.some((item) => item.id === data.activeId) ? data.activeId : "";
  const active = data.items.find((item) => item.id === select.value);
  const name = $("#profile-name");
  if (name && document.activeElement !== name) name.value = active?.name || "";
}

function syncActiveProfile(settings) {
  const data = profileStore();
  const item = data.items.find((entry) => entry.id === data.activeId);
  if (!item) return;
  item.settings = cloneData(settings);
  item.updatedAt = new Date().toISOString();
  saveProfileStore(data);
}

function saveProfile() {
  let settings;
  try {
    settings = readSettingsForm();
  } catch (error) {
    showToast(error.message || "設定を確認してください。");
    return;
  }
  const name = ($("#profile-name")?.value || "").trim();
  if (!name) {
    showToast("プロファイル名を入力してください。");
    return;
  }
  const data = profileStore();
  const selected = $("#profile-select")?.value || "";
  let item = data.items.find((entry) => entry.id === selected);
  const named = data.items.find((entry) => entry.name === name);
  if (named && (!item || named.id !== item.id)) {
    if (!confirm(`「${name}」を上書きしますか？`)) return;
    item = named;
  }
  if (!item) {
    item = { id: newLocalId(), name, settings: cloneData(settings), updatedAt: new Date().toISOString() };
    data.items.push(item);
  } else {
    item.name = name;
    item.settings = cloneData(settings);
    item.updatedAt = new Date().toISOString();
  }
  data.activeId = item.id;
  saveProfileStore(data);
  state.settings = settings;
  localStorage.setItem("vtv-settings", JSON.stringify(settings));
  renderProfileSelect();
  showToast(`プロファイル「${name}」を保存しました。`);
}

function applySelectedProfile() {
  const id = $("#profile-select")?.value || "";
  const data = profileStore();
  data.activeId = id;
  saveProfileStore(data);
  const item = data.items.find((entry) => entry.id === id);
  const name = $("#profile-name");
  if (name) name.value = item?.name || "";
  if (!item) return;
  state.settings = { ...state.settings, ...cloneData(item.settings) };
  localStorage.setItem("vtv-settings", JSON.stringify(state.settings));
  applySettingsToForm();
  refreshConnectionBadge();
  refreshMappedWatchItems();
  renderWatchList();
  renderTimingChannelList();
  renderPalette();
  syncLocalIoPanel();
}

function deleteProfile() {
  const id = $("#profile-select")?.value || "";
  if (!id) {
    showToast("削除するプロファイルを選んでください。");
    return;
  }
  const data = profileStore();
  const item = data.items.find((entry) => entry.id === id);
  if (!item) return;
  if (!confirm(`プロファイル「${item.name}」を削除しますか？`)) return;
  data.items = data.items.filter((entry) => entry.id !== id);
  if (data.activeId === id) data.activeId = "";
  saveProfileStore(data);
  renderProfileSelect();
  showToast("プロファイルを削除しました。");
}

function libraryStore() {
  const data = readJsonStore("vtv-sequence-library", { recent: [], items: [] });
  if (!Array.isArray(data.items)) data.items = [];
  if (!Array.isArray(data.recent)) data.recent = [];
  return data;
}

function touchRecent(data, id) {
  data.recent = [id, ...data.recent.filter((item) => item !== id)].slice(0, 8);
}

function renderSequenceLibrary() {
  const select = $("#sequence-recent");
  if (!select) return;
  const data = libraryStore();
  const byId = new Map(data.items.map((item) => [item.id, item]));
  const recentIds = new Set(data.recent);
  const options = [
    ...data.recent.map((id) => byId.get(id)).filter(Boolean),
    ...data.items.filter((item) => !recentIds.has(item.id)),
  ];
  select.innerHTML = `<option value="">最近使ったシーケンス</option>${options.map((item) =>
    `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`
  ).join("")}`;
  if (state.sequenceLibraryId && byId.has(state.sequenceLibraryId)) select.value = state.sequenceLibraryId;
}

function saveSequenceLibrary() {
  const name = ($("#sequence-name")?.value || "").trim();
  if (!name) {
    showToast("シーケンス名を入力してください。");
    return;
  }
  state.sequenceName = name;
  const data = libraryStore();
  let item = data.items.find((entry) => entry.id === state.sequenceLibraryId);
  const sameName = data.items.find((entry) => entry.name === name);
  if (sameName && (!item || sameName.id !== item.id)) {
    if (!confirm(`「${name}」を上書きしますか？`)) return;
    item = sameName;
  }
  const payload = {
    name,
    steps: cloneData(state.steps),
    nextId: state.nextId,
    updatedAt: new Date().toISOString(),
  };
  if (!item) {
    item = { id: newLocalId(), ...payload };
    data.items.unshift(item);
  } else {
    Object.assign(item, payload);
  }
  state.sequenceLibraryId = item.id;
  touchRecent(data, item.id);
  try { localStorage.setItem("vtv-sequence-library", JSON.stringify(data)); } catch (_) {}
  persistSequenceDraft();
  renderSequenceLibrary();
  showToast(`「${name}」を残しました。`);
}

function openLibrarySequence(id) {
  if (!id) return;
  const data = libraryStore();
  const item = data.items.find((entry) => entry.id === id);
  if (!item) return;
  if (state.steps.length && !confirm("現在のシーケンスを、選んだ内容で置き換えますか？")) {
    renderSequenceLibrary();
    return;
  }
  const snapshot = cloneData(state.steps);
  const nextId = state.nextId;
  const previousName = state.sequenceName;
  const previousLibraryId = state.sequenceLibraryId;
  state.steps = cloneData(item.steps || []);
  const savedNext = Number(item.nextId);
  if (Number.isFinite(savedNext) && savedNext > state.nextId) state.nextId = savedNext;
  state.steps.forEach(ensureStepIds);
  state.sequenceName = item.name || "";
  state.sequenceLibraryId = item.id;
  const input = $("#sequence-name");
  if (input) input.value = state.sequenceName;
  touchRecent(data, item.id);
  try { localStorage.setItem("vtv-sequence-library", JSON.stringify(data)); } catch (_) {}
  renderSequence();
  renderSequenceLibrary();
  showToast(`「${item.name}」を開きました`, () => {
    state.steps = snapshot;
    state.nextId = nextId;
    state.sequenceName = previousName;
    state.sequenceLibraryId = previousLibraryId;
    if ($("#sequence-name")) $("#sequence-name").value = previousName || "";
    renderSequence();
    renderSequenceLibrary();
  });
}

function readRunHistory() {
  try {
    const data = JSON.parse(localStorage.getItem("vtv-run-history") || "[]");
    return Array.isArray(data) ? data : [];
  } catch (_) {
    return [];
  }
}

function formatDuration(ms) {
  const value = Number(ms);
  const safe = Number.isFinite(value) ? Math.max(0, Math.round(value)) : 0;
  if (safe < 1000) return `${safe} ms`;
  return `${(safe / 1000).toFixed(1)} 秒`;
}

function destinationText(settings) {
  const transport = settings?.transport || "tcp";
  const label = transport === "plclink"
    ? "PLCLINK"
    : transport === "field_network"
      ? "Field Network"
      : "TCP";
  return `${label} ${settings?.host || ""}:${settings?.port ?? ""}`.trim();
}

function showRunSummary(entry) {
  const el = $("#run-summary");
  if (!el) return;
  const outcome = entry.result === "success" ? "成功" : entry.result === "stopped" ? "停止" : "失敗";
  const where = entry.result === "success" ? "" : (entry.stoppedAt ? ` ${entry.stoppedAt}` : "");
  const last = entry.lastResponse ? ` 最後の応答: ${entry.lastResponse}` : "";
  const text = `${outcome}${where} · ${formatDuration(entry.durationMs)}${last}`;
  el.textContent = text;
  el.title = entry.message ? `${text} / ${entry.message}` : text;
  el.className = `run-summary ${entry.result === "failed" ? "failed" : entry.result === "stopped" ? "stopped" : "ok"}`;
}

function finishRun(kind, event = {}) {
  if (state.runRecorded) return;
  state.runRecorded = true;
  const durationMs = Number.isFinite(Number(event.duration_ms))
    ? Number(event.duration_ms)
    : Math.max(0, Math.round(performance.now() - (state.runStartedAt || performance.now())));
  const position = event.position && event.total
    ? `${event.position}/${event.total} ${event.label || ""}`.trim()
    : (state.runPositionText || "");
  const entry = {
    at: new Date().toISOString(),
    destination: destinationText(state.settings),
    result: kind,
    stoppedAt: kind === "success" ? "" : position,
    durationMs,
    lastResponse: event.last_response || state.lastResponse || "",
    message: event.message || "",
    logs: snapshotRunLogs(),
  };
  const history = readRunHistory();
  history.unshift(entry);
  writeRunHistory(history);
  showRunSummary(entry);
  if ($("#help-dialog")?.open) renderRunHistory();
}

function snapshotRunLogs() {
  return state.logs.slice(-200).map((entry) => ({
    timestamp: entry.timestamp,
    kind: entry.kind,
    data: String(entry.data || "").slice(0, 500),
    stepId: entry.stepId || "",
  }));
}

function writeRunHistory(history) {
  const trimmed = history.slice(0, 20);
  try {
    localStorage.setItem("vtv-run-history", JSON.stringify(trimmed));
  } catch (_) {
    const slim = trimmed.slice(0, 8).map((entry) => ({
      ...entry,
      logs: (entry.logs || []).slice(-40),
    }));
    try { localStorage.setItem("vtv-run-history", JSON.stringify(slim)); } catch (_) {}
  }
}

function renderRunHistory() {
  const list = $("#run-history");
  if (!list) return;
  const history = readRunHistory();
  if (!history.length) {
    list.innerHTML = `<p class="export-note">まだ実行記録はありません。</p>`;
    return;
  }
  list.innerHTML = history.slice(0, 12).map((entry, index) => {
    const outcome = entry.result === "success" ? "成功" : entry.result === "stopped" ? "停止" : "失敗";
    const when = String(entry.at || "").replace("T", " ").slice(0, 19);
    const where = entry.stoppedAt ? ` ${entry.stoppedAt}` : "";
    const last = entry.lastResponse ? ` / ${entry.lastResponse}` : "";
    const summary = `${when} ${outcome}${where} ${formatDuration(entry.durationMs)} ${entry.destination || ""}${last}`;
    const lines = (entry.logs || []).map((line) => `${line.kind} ${line.data}`).join("\n");
    const body = lines
      ? `<pre class="run-log">${escapeHtml(lines)}</pre><button type="button" class="icon-button" data-history-log="${index}">この通信を表示</button>`
      : `<p class="export-note">この記録に通信ログはありません。</p>`;
    return `<details class="run-history-item"><summary>${escapeHtml(summary)}</summary>${body}</details>`;
  }).join("");
}

function showHistoryLog(index) {
  const entry = readRunHistory()[index];
  if (!entry?.logs?.length) {
    showToast("この記録に通信はありません。");
    return;
  }
  const snapshot = state.logs.map((item) => ({ ...item }));
  state.logs = entry.logs.map((item) => ({
    timestamp: item.timestamp,
    kind: item.kind,
    data: item.data,
    stepId: item.stepId || "",
  }));
  paintLog();
  showToast("この回の通信を表示しています", () => {
    state.logs = snapshot;
    paintLog();
  });
}

function exportSupportBundle() {
  const payload = {
    app: "VTV Network Sequencer",
    version: state.appVersion || "",
    exportedAt: new Date().toISOString(),
    settings: state.settings,
    sequence: { name: state.sequenceName || "", steps: cleanSteps(state.steps) },
    logs: state.logs,
    runHistory: readRunHistory().slice(0, 20),
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `vtv-support-${fileTimestamp(new Date())}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function exportTimingImage() {
  const canvas = $("#timing-chart");
  if (!canvas || !state.timingSamples.length) {
    showToast("書き出せる波形がありません。");
    return;
  }
  canvas.toBlob((blob) => {
    if (!blob) {
      showToast("画像を書き出せませんでした。");
      return;
    }
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `vtv-timing-${fileTimestamp(new Date())}.png`;
    link.click();
    URL.revokeObjectURL(link.href);
  });
}

function exportTimingCsv() {
  if (!state.timingSamples.length) {
    showToast("書き出せる波形がありません。");
    return;
  }
  const channels = timingBitItems().filter((item) => state.timingSelectedIds.includes(item.id));
  const header = ["時刻ms", "poll", ...channels.map((item) => item.label)];
  const rows = state.timingSamples.map((sample) => [
    sample.t,
    sample.n ?? "",
    ...channels.map((item) => sample.bits?.[item.id] ?? ""),
  ]);
  const content = [header, ...rows].map((row) => row.map(csvCell).join(",")).join("\r\n");
  const blob = new Blob(["\uFEFF", content], { type: "text/csv;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `vtv-timing-${fileTimestamp(new Date())}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function openDialog(dialog, focusSelector) {
  if (!dialog) return;
  if (typeof dialog.showModal === "function") {
    if (!dialog.open) dialog.showModal();
  } else {
    dialog.setAttribute("open", "");
  }
  const focus = (focusSelector && dialog.querySelector(focusSelector))
    || dialog.querySelector("input, select, textarea, button:not(.close-button)");
  focus?.focus();
}

function openHelpDialog() {
  renderRunHistory();
  openDialog($("#help-dialog"), "#help-title");
}

function closeHelpDialog() {
  const dialog = $("#help-dialog");
  if (!dialog) return;
  if (typeof dialog.close === "function" && dialog.open) dialog.close();
  else dialog.removeAttribute("open");
}

async function loadAppVersion() {
  try {
    const response = await fetch("/api/version");
    if (response.ok) {
      const data = await response.json();
      state.appVersion = data.version || "";
    }
  } catch (_) {}
  const el = $("#app-version");
  if (!el) return;
  el.textContent = state.appVersion
    ? `VTV Network Sequencer ${state.appVersion}`
    : "VTV Network Sequencer";
}

function trialStore() {
  const data = readJsonStore("vtv-trial-sets", { items: [] });
  if (!Array.isArray(data.items)) data.items = [];
  return data;
}

function saveTrialStore(data) {
  try { localStorage.setItem("vtv-trial-sets", JSON.stringify(data)); } catch (_) {}
}

function renderTrialSelect() {
  const select = $("#trial-select");
  if (!select) return;
  const data = trialStore();
  select.innerHTML = `<option value="">試験セット</option>${data.items.map((item) =>
    `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`
  ).join("")}`;
  if (state.trialId && data.items.some((item) => item.id === state.trialId)) {
    select.value = state.trialId;
  }
  const name = $("#trial-name");
  if (!name || document.activeElement === name) return;
  const current = data.items.find((item) => item.id === state.trialId);
  if (current) name.value = current.name;
  else if (state.trialName) name.value = state.trialName;
}

function upsertProfile(name, settings, preferredId) {
  const data = profileStore();
  let item = preferredId ? data.items.find((entry) => entry.id === preferredId) : null;
  if (!item) item = data.items.find((entry) => entry.name === name);
  if (!item) {
    item = {
      id: newLocalId(),
      name,
      settings: cloneData(settings),
      updatedAt: new Date().toISOString(),
    };
    data.items.push(item);
  } else {
    item.name = name;
    item.settings = cloneData(settings);
    item.updatedAt = new Date().toISOString();
  }
  data.activeId = item.id;
  saveProfileStore(data);
  state.settings = settings;
  localStorage.setItem("vtv-settings", JSON.stringify(settings));
  const field = $("#profile-name");
  if (field) field.value = name;
  return item.id;
}

function upsertSequence(name, preferredId) {
  const data = libraryStore();
  let item = preferredId ? data.items.find((entry) => entry.id === preferredId) : null;
  if (!item) item = data.items.find((entry) => entry.name === name);
  const payload = {
    name,
    steps: cloneData(state.steps),
    nextId: state.nextId,
    updatedAt: new Date().toISOString(),
  };
  if (!item) {
    item = { id: newLocalId(), ...payload };
    data.items.unshift(item);
  } else {
    Object.assign(item, payload);
  }
  state.sequenceLibraryId = item.id;
  state.sequenceName = name;
  const field = $("#sequence-name");
  if (field) field.value = name;
  touchRecent(data, item.id);
  try { localStorage.setItem("vtv-sequence-library", JSON.stringify(data)); } catch (_) {}
  persistSequenceDraft();
  return item.id;
}

function saveTrialSet() {
  const name = ($("#trial-name")?.value || "").trim();
  if (!name) {
    showToast("試験名を入力してください。");
    return;
  }
  let settings;
  try {
    settings = readSettingsForm();
  } catch (error) {
    showToast(error.message || "設定を確認してください。");
    return;
  }
  const data = trialStore();
  let trial = data.items.find((item) => item.id === state.trialId);
  const sameName = data.items.find((item) => item.name === name);
  if (sameName && (!trial || sameName.id !== trial.id)) {
    if (!confirm(`試験「${name}」を上書きしますか？`)) return;
    trial = sameName;
  }
  const profileId = upsertProfile(name, settings, trial?.profileId);
  const sequenceId = upsertSequence(name, trial?.sequenceId);
  const payload = {
    name,
    profileId,
    sequenceId,
    updatedAt: new Date().toISOString(),
  };
  if (!trial) {
    trial = { id: newLocalId(), ...payload };
    data.items.unshift(trial);
  } else {
    Object.assign(trial, payload);
  }
  data.items = data.items.slice(0, 40);
  state.trialId = trial.id;
  state.trialName = name;
  saveTrialStore(data);
  persistSequenceDraft();
  renderTrialSelect();
  renderProfileSelect();
  renderSequenceLibrary();
  showToast(`試験「${name}」を残しました。接続先とシーケンスを一緒に開けます。`);
}

function openTrial(id) {
  if (!id) return;
  const trial = trialStore().items.find((item) => item.id === id);
  if (!trial) return;
  const profile = profileStore().items.find((item) => item.id === trial.profileId);
  const sequence = libraryStore().items.find((item) => item.id === trial.sequenceId);
  if (!profile || !sequence) {
    showToast("この試験の接続先かシーケンスが見つかりません。もう一度残してください。");
    renderTrialSelect();
    return;
  }
  if (state.steps.length && !confirm("現在のシーケンスと接続先を、この試験で置き換えますか？")) {
    renderTrialSelect();
    return;
  }
  const snapshot = {
    steps: cloneData(state.steps),
    nextId: state.nextId,
    sequenceName: state.sequenceName,
    sequenceLibraryId: state.sequenceLibraryId,
    trialId: state.trialId || "",
    trialName: $("#trial-name")?.value || "",
    settings: cloneData(state.settings),
    activeProfile: profileStore().activeId || "",
  };
  state.settings = { ...state.settings, ...cloneData(profile.settings) };
  localStorage.setItem("vtv-settings", JSON.stringify(state.settings));
  const profiles = profileStore();
  profiles.activeId = profile.id;
  saveProfileStore(profiles);
  const profileName = $("#profile-name");
  if (profileName) profileName.value = profile.name || "";
  applySettingsToForm();
  refreshConnectionBadge();
  refreshMappedWatchItems();
  renderWatchList();
  renderTimingChannelList();
  renderPalette();
  syncLocalIoPanel();
  state.steps = cloneData(sequence.steps || []);
  const savedNext = Number(sequence.nextId);
  if (Number.isFinite(savedNext) && savedNext > state.nextId) state.nextId = savedNext;
  state.steps.forEach(ensureStepIds);
  state.sequenceName = sequence.name || trial.name;
  state.sequenceLibraryId = sequence.id;
  state.trialId = trial.id;
  state.trialName = trial.name;
  const seqName = $("#sequence-name");
  if (seqName) seqName.value = state.sequenceName;
  const trialName = $("#trial-name");
  if (trialName) trialName.value = trial.name;
  const library = libraryStore();
  touchRecent(library, sequence.id);
  try { localStorage.setItem("vtv-sequence-library", JSON.stringify(library)); } catch (_) {}
  renderProfileSelect();
  renderSequenceLibrary();
  renderTrialSelect();
  renderSequence();
  showToast(`試験「${trial.name}」を開きました。`, () => {
    state.steps = snapshot.steps;
    state.nextId = snapshot.nextId;
    state.sequenceName = snapshot.sequenceName;
    state.sequenceLibraryId = snapshot.sequenceLibraryId;
    state.trialId = snapshot.trialId;
    state.trialName = snapshot.trialName;
    state.settings = snapshot.settings;
    localStorage.setItem("vtv-settings", JSON.stringify(state.settings));
    const store = profileStore();
    store.activeId = snapshot.activeProfile;
    saveProfileStore(store);
    applySettingsToForm();
    refreshConnectionBadge();
    refreshMappedWatchItems();
    renderWatchList();
    renderTimingChannelList();
    renderPalette();
    syncLocalIoPanel();
    const name = $("#sequence-name");
    if (name) name.value = state.sequenceName;
    renderProfileSelect();
    renderSequenceLibrary();
    renderTrialSelect();
    renderSequence();
  });
}

function describeSequenceText() {
  const lines = [
    "VTV Network Sequencer",
    `名前: ${state.sequenceName.trim() || "（無名）"}`,
    `接続: ${destinationText(state.settings)}`,
    "",
  ];
  if (!state.steps.length) lines.push("カードはありません。");
  else lines.push(...describeSteps(state.steps, 0));
  return lines.join("\r\n");
}

function describeSteps(steps, depth) {
  const pad = "  ".repeat(depth);
  const lines = [];
  steps.forEach((step, index) => {
    const number = `${index + 1}.`;
    if (step.type === "command") {
      const definition = state.catalog.find((item) => item.code === step.command);
      lines.push(`${pad}${number} ${step.command} ${definition?.name || ""}`.trimEnd());
      for (const arg of visibleArguments(definition || {})) {
        if (!argumentVisible(step, arg)) continue;
        const variableName = argumentVariableName(step, arg.key);
        const value = variableName ? `変数 ${variableName}` : (step.arguments?.[arg.key] ?? "");
        lines.push(`${pad}   ${arg.label}: ${value}`);
      }
      const rawVariable = argumentVariableName(step, "raw");
      if (rawVariable) lines.push(`${pad}   引数文字列: 変数 ${rawVariable}`);
      else if (step.arguments?.raw) lines.push(`${pad}   引数文字列: ${step.arguments.raw}`);
      if (step.ignore_response) lines.push(`${pad}   応答を待たない`);
    } else if (step.type === "delay") {
      lines.push(`${pad}${number} 待機 ${step.milliseconds}ms`);
    } else if (step.type === "note") {
      lines.push(`${pad}${number} メモ`);
      lines.push(`${pad}   ${step.text || "（空）"}`);
    } else if (step.type === "variable") {
      const source = variableSourceLabel(step.source);
      const name = step.name || "（無名）";
      let detail = source;
      if (step.source === "card_response" || step.source === "card_status") {
        const card = collectCommandCards(state.steps).find((item) => item.id === String(step.card_id));
        detail = card ? `${source} / ${card.label}` : source;
      } else if (step.source === "output_port") {
        detail = `${outputPortCaption()} ${step.port}`;
      } else if (step.source === "result_data") {
        const offset = String(Number(step.offset) || 0).padStart(4, "0");
        detail = `結果データ +${offset} ${resultFormatLabel(step.result_format)}`;
      } else if (step.source === "literal") {
        detail = `固定の文字 ${step.value || "（空）"}`;
      }
      lines.push(`${pad}${number} 変数 ${name}`);
      lines.push(`${pad}   ${detail}`);
    } else if (step.type === "break") {
      lines.push(`${pad}${number} BREAK ループを抜ける`);
    } else if (step.type === "if") {
      const source = step.source === "response" ? "応答全文" : "AK/NK/ER";
      const operator = step.operator === "contains"
        ? "含む"
        : step.operator === "not_contains"
          ? "含まない"
          : "等しい";
      lines.push(`${pad}${number} 条件 ${source} ${operator} ${step.value}`);
      lines.push(`${pad}   一致:`);
      lines.push(...(step.then_steps?.length ? describeSteps(step.then_steps, depth + 2) : [`${pad}     （なし）`]));
      lines.push(`${pad}   不一致:`);
      lines.push(...(step.else_steps?.length ? describeSteps(step.else_steps, depth + 2) : [`${pad}     （なし）`]));
    } else if (step.type === "loop") {
      lines.push(`${pad}${number} ループ ×${step.count}`);
      lines.push(...(step.steps?.length ? describeSteps(step.steps, depth + 1) : [`${pad}   （なし）`]));
    }
  });
  return lines;
}

function exportReadableSequence() {
  const blob = new Blob(["\uFEFF", describeSequenceText()], { type: "text/plain;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `vtv-sequence-${fileTimestamp(new Date())}.txt`;
  link.click();
  URL.revokeObjectURL(link.href);
  showToast("一覧を書き出しました。");
}

function restoreWorkshop() {
  try {
    const favorites = JSON.parse(localStorage.getItem("vtv-palette-favorites") || "[]");
    if (Array.isArray(favorites)) {
      state.favorites = favorites.filter((item) => typeof item === "string");
    }
  } catch (_) {}
  state.foldUnsupported = localStorage.getItem("vtv-fold-unsupported") !== "0";
  const filter = localStorage.getItem("vtv-log-filter");
  if (["all", "tx", "rx", "error", "info"].includes(filter)) state.logFilter = filter;
  state.watchChangedOnly = localStorage.getItem("vtv-watch-changed-only") === "1";
  state.watchQuery = localStorage.getItem("vtv-watch-query") || "";
  const fold = $("#fold-unsupported");
  if (fold) fold.checked = state.foldUnsupported;
  const logFilter = $("#log-filter");
  if (logFilter) logFilter.value = state.logFilter;
  const changedOnly = $("#watch-changed-only");
  if (changedOnly) changedOnly.checked = state.watchChangedOnly;
  const watchSearch = $("#watch-search");
  if (watchSearch) watchSearch.value = state.watchQuery;
  const name = $("#sequence-name");
  if (name) name.value = state.sequenceName || "";
  renderSequenceLibrary();
  renderProfileSelect();
  renderTrialSelect();
}

function bindWorkshopEvents() {
  $("#fold-unsupported")?.addEventListener("change", (event) => {
    state.foldUnsupported = event.target.checked;
    localStorage.setItem("vtv-fold-unsupported", state.foldUnsupported ? "1" : "0");
    renderPalette();
  });
  $("#profile-save")?.addEventListener("click", saveProfile);
  $("#profile-delete")?.addEventListener("click", deleteProfile);
  $("#profile-select")?.addEventListener("change", applySelectedProfile);
  $("#sequence-save-library")?.addEventListener("click", saveSequenceLibrary);
  $("#sequence-name")?.addEventListener("input", (event) => {
    state.sequenceName = event.target.value;
    scheduleDraftSave();
  });
  $("#sequence-recent")?.addEventListener("change", (event) => openLibrarySequence(event.target.value));
  $("#sequence-readable")?.addEventListener("click", exportReadableSequence);
  $("#trial-save")?.addEventListener("click", saveTrialSet);
  $("#trial-name")?.addEventListener("input", scheduleDraftSave);
  $("#trial-select")?.addEventListener("change", (event) => openTrial(event.target.value));
  $("#run-history")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-history-log]");
    if (!button) return;
    showHistoryLog(Number(button.dataset.historyLog));
  });
  $("#log-filter")?.addEventListener("change", (event) => {
    state.logFilter = event.target.value;
    localStorage.setItem("vtv-log-filter", state.logFilter);
    paintLog();
  });
  $("#log")?.addEventListener("click", onLogClick);
  $("#log")?.addEventListener("keydown", onLogKeydown);
  $("#watch-search")?.addEventListener("input", (event) => {
    state.watchQuery = event.target.value;
    localStorage.setItem("vtv-watch-query", state.watchQuery);
    renderWatchList();
  });
  $("#watch-changed-only")?.addEventListener("change", (event) => {
    state.watchChangedOnly = event.target.checked;
    localStorage.setItem("vtv-watch-changed-only", state.watchChangedOnly ? "1" : "0");
    renderWatchList();
  });
  $("#timing-export-image")?.addEventListener("click", exportTimingImage);
  $("#timing-export-csv")?.addEventListener("click", exportTimingCsv);
  $("#help-button")?.addEventListener("click", openHelpDialog);
  $("#help-close-button")?.addEventListener("click", closeHelpDialog);
  $("#help-close-action")?.addEventListener("click", closeHelpDialog);
  $("#support-export-button")?.addEventListener("click", exportSupportBundle);
  document.addEventListener("keydown", onWorkshopKeydown);
}

function onWorkshopKeydown(event) {
  if (!(event.ctrlKey || event.metaKey) || event.altKey || event.defaultPrevented) return;
  const key = event.key.toLowerCase();
  const dialogOpen = !!document.querySelector("dialog[open]");
  if (key === "enter") {
    event.preventDefault();
    if (dialogOpen) return;
    runSequence();
    return;
  }
  if (dialogOpen) return;
  if (key === "k") {
    event.preventDefault();
    const search = $("#command-search");
    search?.focus();
    search?.select?.();
    return;
  }
  if (key === ".") {
    event.preventDefault();
    if (state.running) stopSequence();
    else showRunHint("実行中ではありません。");
    return;
  }
  if (key === "s" && event.shiftKey) {
    event.preventDefault();
    saveSequence();
  }
}

initialize().catch((error) => {
  document.body.innerHTML = `<p style="padding:30px">起動エラー: ${escapeHtml(error.message)}</p>`;
});
