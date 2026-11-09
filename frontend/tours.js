/**
 * Interactive UI tours (Driver.js).
 * - Manual start from the help dialog
 * - Basics tour auto-starts once on first launch
 * - Each tour can be exited mid-way (× / Esc / overlay)
 */
(function (global) {
  "use strict";

  // v2: auto-start is gated only by this flag (not by existing settings data).
  const BASICS_SEEN_KEY = "vtv-tour-basics-seen-v2";

  /** @type {null | { destroy: Function, isActive: Function, refresh: Function }} */
  let activeDriver = null;
  /** @type {string | null} */
  let activeTourId = null;
  let cardDemoPlayed = false;
  /** @type {number | null} */
  let demoAnimTimer = null;

  function t(key, vars) {
    if (typeof global.t === "function") return global.t(key, vars);
    return key;
  }

  function hooks() {
    return global.VtvTourHooks || {};
  }

  function driverFactory() {
    return global.driver && global.driver.js && global.driver.js.driver;
  }

  function hasSeenBasicsTour() {
    try {
      return localStorage.getItem(BASICS_SEEN_KEY) === "1";
    } catch (_) {
      return true;
    }
  }

  function markBasicsTourSeen() {
    try {
      localStorage.setItem(BASICS_SEEN_KEY, "1");
    } catch (_) {
      /* ignore */
    }
  }

  function refreshSoon(ctx) {
    const driverObj = (ctx && ctx.driver) || activeDriver;
    if (!driverObj || typeof driverObj.refresh !== "function") return;
    requestAnimationFrame(() => {
      try { driverObj.refresh(); } catch (_) { /* ignore */ }
    });
  }

  function clearDemoAnimation() {
    if (demoAnimTimer != null) {
      window.clearTimeout(demoAnimTimer);
      demoAnimTimer = null;
    }
    document.querySelectorAll(".tour-drag-ghost").forEach((el) => el.remove());
    document.querySelectorAll(".tour-drop-flash").forEach((el) => {
      el.classList.remove("tour-drop-flash");
    });
  }

  /**
   * Animate a ghost card from the Delay control into the sequence panel,
   * then optionally add a real Delay step.
   */
  function playCardDragDemo() {
    return new Promise((resolve) => {
      clearDemoAnimation();
      const source = document.querySelector('[data-control="delay"]');
      const target = document.querySelector("#sequence-list");
      if (!source || !target) {
        resolve(false);
        return;
      }

      const s = source.getBoundingClientRect();
      const t = target.getBoundingClientRect();
      if (s.width < 4 || t.width < 4) {
        resolve(false);
        return;
      }

      const ghost = source.cloneNode(true);
      ghost.removeAttribute("data-control");
      ghost.removeAttribute("id");
      ghost.setAttribute("aria-hidden", "true");
      ghost.tabIndex = -1;
      ghost.classList.add("tour-drag-ghost");
      ghost.style.width = `${Math.round(s.width)}px`;
      ghost.style.height = `${Math.round(s.height)}px`;
      ghost.style.left = `${s.left}px`;
      ghost.style.top = `${s.top}px`;
      document.body.appendChild(ghost);

      const destX = t.left + Math.min(48, t.width * 0.12) - s.left;
      const destY = t.top + Math.min(72, t.height * 0.22) - s.top;

      // Start slightly lifted, then fly into the sequence area.
      requestAnimationFrame(() => {
        ghost.classList.add("tour-drag-ghost-lift");
        requestAnimationFrame(() => {
          ghost.style.transform = `translate(${destX}px, ${destY}px) scale(1.06) rotate(-2deg)`;
          ghost.classList.add("tour-drag-ghost-fly");
        });
      });

      demoAnimTimer = window.setTimeout(() => {
        ghost.classList.add("tour-drag-ghost-drop");
        target.classList.add("tour-drop-flash");
        const h = hooks();
        const added = h.addTourDemoCard ? h.addTourDemoCard() : null;
        refreshSoon({ driver: activeDriver });
        demoAnimTimer = window.setTimeout(() => {
          ghost.remove();
          target.classList.remove("tour-drop-flash");
          demoAnimTimer = null;
          refreshSoon({ driver: activeDriver });
          resolve(Boolean(added) || true);
        }, 220);
      }, 920);
    });
  }

  function step(element, titleKey, bodyKey, options) {
    const popover = {
      title: t(titleKey),
      description: t(bodyKey),
      side: (options && options.side) || "bottom",
      align: (options && options.align) || "start",
    };
    const entry = { element, popover };
    if (options && typeof options.onHighlightStarted === "function") {
      entry.onHighlightStarted = options.onHighlightStarted;
    }
    if (options && typeof options.onHighlighted === "function") {
      entry.onHighlighted = options.onHighlighted;
    }
    return entry;
  }

  function buildBasicsSteps() {
    return [
      step(".app-header", "tour.basics.s1Title", "tour.basics.s1Body", { side: "bottom", align: "center" }),
      step("#settings-button", "tour.basics.s2Title", "tour.basics.s2Body", { side: "bottom" }),
      step("#local-io-panel", "tour.basics.s2bTitle", "tour.basics.s2bBody", {
        side: "bottom",
        align: "end",
        onHighlightStarted(_el, _step, ctx) {
          hooks().showLocalIoPanelForTour?.();
          refreshSoon(ctx);
        },
      }),
      step(".palette", "tour.basics.s3Title", "tour.basics.s3Body", { side: "right" }),
      step('[data-control="delay"]', "tour.basics.s3bTitle", "tour.basics.s3bBody", {
        side: "right",
        onHighlighted() {
          if (cardDemoPlayed) return;
          cardDemoPlayed = true;
          playCardDragDemo();
        },
      }),
      step("#sequence-list", "tour.basics.s4Title", "tour.basics.s4Body", {
        side: "left",
        onHighlightStarted(_el, _step, ctx) {
          refreshSoon(ctx);
        },
      }),
      step("#run-button", "tour.basics.s5Title", "tour.basics.s5Body", { side: "bottom" }),
      step(".monitor", "tour.basics.s6Title", "tour.basics.s6Body", { side: "left" }),
    ];
  }

  function buildTcpSteps() {
    const h = hooks();
    return [
      step("#settings-button", "tour.tcp.s1Title", "tour.tcp.s1Body", {
        side: "bottom",
        onHighlightStarted() {
          h.closeSettingsFromTour?.();
        },
      }),
      step("#transport", "tour.tcp.s2Title", "tour.tcp.s2Body", {
        side: "bottom",
        onHighlightStarted(_el, _step, ctx) {
          h.openSettingsForTour?.("tcp");
          refreshSoon(ctx);
        },
      }),
      step("#host", "tour.tcp.s3Title", "tour.tcp.s3Body", { side: "bottom" }),
      step("#port", "tour.tcp.s4Title", "tour.tcp.s4Body", { side: "bottom" }),
      step("#test-button", "tour.tcp.s5Title", "tour.tcp.s5Body", { side: "top" }),
      step("#apply-settings", "tour.tcp.s6Title", "tour.tcp.s6Body", { side: "top" }),
      step("#run-button", "tour.tcp.s7Title", "tour.tcp.s7Body", {
        side: "bottom",
        onHighlightStarted(_el, _step, ctx) {
          h.closeSettingsFromTour?.();
          refreshSoon(ctx);
        },
      }),
    ];
  }

  function buildPlclinkSteps() {
    const h = hooks();
    return [
      step("#settings-button", "tour.plclink.s1Title", "tour.plclink.s1Body", {
        side: "bottom",
        onHighlightStarted() {
          h.closeSettingsFromTour?.();
        },
      }),
      step("#transport", "tour.plclink.s2Title", "tour.plclink.s2Body", {
        side: "bottom",
        onHighlightStarted(_el, _step, ctx) {
          h.openSettingsForTour?.("plclink");
          refreshSoon(ctx);
        },
      }),
      step("#host", "tour.plclink.s3Title", "tour.plclink.s3Body", { side: "bottom" }),
      step("#port", "tour.plclink.s4Title", "tour.plclink.s4Body", { side: "bottom" }),
      step("#start-softplc-button", "tour.plclink.s5Title", "tour.plclink.s5Body", { side: "top" }),
      step("#apply-settings", "tour.plclink.s6Title", "tour.plclink.s6Body", { side: "top" }),
      step("#connection-badge", "tour.plclink.s7Title", "tour.plclink.s7Body", {
        side: "bottom",
        onHighlightStarted(_el, _step, ctx) {
          h.closeSettingsFromTour?.();
          refreshSoon(ctx);
        },
      }),
    ];
  }

  function buildFnSteps() {
    const h = hooks();
    return [
      step("#settings-button", "tour.fn.s1Title", "tour.fn.s1Body", {
        side: "bottom",
        onHighlightStarted() {
          h.closeSettingsFromTour?.();
        },
      }),
      step("#transport", "tour.fn.s2Title", "tour.fn.s2Body", {
        side: "bottom",
        onHighlightStarted(_el, _step, ctx) {
          h.openSettingsForTour?.("field_network");
          refreshSoon(ctx);
        },
      }),
      step("#host", "tour.fn.s3Title", "tour.fn.s3Body", { side: "bottom" }),
      step("#eds-import-input", "tour.fn.s4Title", "tour.fn.s4Body", { side: "bottom" }),
      step("#fn-connect-button", "tour.fn.s5Title", "tour.fn.s5Body", { side: "top" }),
      step("#apply-settings", "tour.fn.s6Title", "tour.fn.s6Body", { side: "top" }),
      step("#connection-badge", "tour.fn.s7Title", "tour.fn.s7Body", {
        side: "bottom",
        onHighlightStarted(_el, _step, ctx) {
          h.closeSettingsFromTour?.();
          refreshSoon(ctx);
        },
      }),
    ];
  }

  function buildMonitorSteps() {
    const h = hooks();
    return [
      step(".monitor", "tour.monitor.s1Title", "tour.monitor.s1Body", {
        side: "left",
        onHighlightStarted(_el, _step, ctx) {
          h.closeSettingsFromTour?.();
          h.setLayoutMode?.("workspace");
          h.selectMonitorTabForTour?.("log");
          refreshSoon(ctx);
        },
      }),
      step('[data-monitor-tab="log"]', "tour.monitor.s2Title", "tour.monitor.s2Body", {
        side: "bottom",
        onHighlightStarted() {
          h.selectMonitorTabForTour?.("log");
        },
      }),
      step('[data-monitor-tab="watch"]', "tour.monitor.s3Title", "tour.monitor.s3Body", {
        side: "bottom",
        onHighlightStarted(_el, _step, ctx) {
          h.selectMonitorTabForTour?.("watch");
          refreshSoon(ctx);
        },
      }),
      step("#watch-list", "tour.monitor.s3bTitle", "tour.monitor.s3bBody", {
        side: "left",
        onHighlightStarted(_el, _step, ctx) {
          h.selectMonitorTabForTour?.("watch");
          refreshSoon(ctx);
        },
      }),
      step(".watch-filter-bar", "tour.monitor.s3cTitle", "tour.monitor.s3cBody", {
        side: "bottom",
        onHighlightStarted(_el, _step, ctx) {
          h.selectMonitorTabForTour?.("watch");
          refreshSoon(ctx);
        },
      }),
      step("#start-watch-button", "tour.monitor.s4Title", "tour.monitor.s4Body", {
        side: "bottom",
        onHighlightStarted() {
          h.selectMonitorTabForTour?.("watch");
        },
      }),
      step('[data-monitor-tab="timing"]', "tour.monitor.s5Title", "tour.monitor.s5Body", {
        side: "bottom",
        onHighlightStarted(_el, _step, ctx) {
          h.selectMonitorTabForTour?.("timing");
          refreshSoon(ctx);
        },
      }),
      step("#timing-channel-list", "tour.monitor.s5bTitle", "tour.monitor.s5bBody", {
        side: "right",
        onHighlightStarted(_el, _step, ctx) {
          h.selectMonitorTabForTour?.("timing");
          refreshSoon(ctx);
        },
      }),
      step("#layout-mode-monitor-button", "tour.monitor.s6Title", "tour.monitor.s6Body", {
        side: "bottom",
        onHighlightStarted() {
          h.setLayoutMode?.("workspace");
          h.selectMonitorTabForTour?.("watch");
        },
      }),
      step(".monitor", "tour.monitor.s7Title", "tour.monitor.s7Body", {
        side: "left",
        align: "center",
        onHighlightStarted(_el, _step, ctx) {
          h.setLayoutMode?.("monitor");
          h.selectMonitorTabForTour?.("watch");
          refreshSoon(ctx);
          window.setTimeout(() => refreshSoon(ctx), 120);
        },
      }),
      step("#timing-channel-list", "tour.monitor.s8Title", "tour.monitor.s8Body", {
        side: "right",
        onHighlightStarted(_el, _step, ctx) {
          h.setLayoutMode?.("monitor");
          h.selectMonitorTabForTour?.("timing");
          refreshSoon(ctx);
          window.setTimeout(() => refreshSoon(ctx), 120);
        },
      }),
      step("#layout-mode-button", "tour.monitor.s9Title", "tour.monitor.s9Body", {
        side: "bottom",
        onHighlightStarted(_el, _step, ctx) {
          h.setLayoutMode?.("monitor");
          refreshSoon(ctx);
        },
      }),
    ];
  }

  const TOURS = [
    { id: "basics", titleKey: "tour.basics.title", descKey: "tour.basics.desc", build: buildBasicsSteps },
    { id: "tcp", titleKey: "tour.tcp.title", descKey: "tour.tcp.desc", build: buildTcpSteps },
    { id: "plclink", titleKey: "tour.plclink.title", descKey: "tour.plclink.desc", build: buildPlclinkSteps },
    { id: "field_network", titleKey: "tour.fn.title", descKey: "tour.fn.desc", build: buildFnSteps },
    { id: "monitor", titleKey: "tour.monitor.title", descKey: "tour.monitor.desc", build: buildMonitorSteps },
  ];

  function resolveFnEdsElement(steps) {
    return steps.map((entry) => {
      if (entry.element !== "#eds-import-input") return entry;
      const label = document.querySelector('label[for="eds-import-input"], .file-button-label');
      const input = document.querySelector("#eds-import-input");
      const target = label || (input && input.closest("label")) || input;
      return { ...entry, element: target || entry.element };
    });
  }

  function cleanupTourUi() {
    const h = hooks();
    clearDemoAnimation();
    h.closeSettingsFromTour?.();
    h.restoreMonitorTourUi?.();
    h.restoreLocalIoPanelFromTour?.();
    document.body.classList.remove("tour-active", "tour-settings-open");
  }

  function startTour(id) {
    const factory = driverFactory();
    if (typeof factory !== "function") {
      console.error("Driver.js is not loaded");
      return false;
    }

    const tour = TOURS.find((item) => item.id === id);
    if (!tour) return false;

    if (activeDriver && activeDriver.isActive()) {
      activeDriver.destroy();
      activeDriver = null;
    }

    const h = hooks();
    h.closeHelp?.();
    h.closeSettingsFromTour?.();
    h.setLayoutMode?.("workspace");
    clearDemoAnimation();
    cardDemoPlayed = false;
    activeTourId = id;

    let steps = tour.build();
    if (id === "field_network") steps = resolveFnEdsElement(steps);

    window.setTimeout(() => {
      document.body.classList.add("tour-active");
      const driverObj = factory({
        animate: true,
        allowClose: true,
        overlayClickBehavior: "close",
        overlayOpacity: 0.55,
        stagePadding: 8,
        stageRadius: 8,
        smoothScroll: true,
        disableActiveInteraction: true,
        showProgress: true,
        progressText: t("tour.progress"),
        nextBtnText: t("tour.next"),
        prevBtnText: t("tour.prev"),
        doneBtnText: t("tour.done"),
        popoverClass: "vtv-tour-popover",
        steps,
        onDestroyed() {
          if (activeTourId === "basics") markBasicsTourSeen();
          cleanupTourUi();
          activeDriver = null;
          activeTourId = null;
        },
      });
      activeDriver = driverObj;
      driverObj.drive();
    }, 60);

    return true;
  }

  function stopTour() {
    if (activeDriver && activeDriver.isActive()) {
      activeDriver.destroy();
    }
    activeDriver = null;
    activeTourId = null;
    cleanupTourUi();
  }

  function maybeStartFirstRunTour() {
    if (hasSeenBasicsTour()) return false;
    if (activeDriver && activeDriver.isActive()) return false;
    // Wait for layout / catalog paint, then start basics once.
    // Note: the packaged app shares LocalAppData/.../app-profile with prior runs,
    // so "first launch" means "this profile has never finished/skipped the basics tour".
    window.setTimeout(() => {
      if (hasSeenBasicsTour()) return;
      if (activeDriver && activeDriver.isActive()) return;
      if (!driverFactory()) {
        console.error("Driver.js is not loaded; skipping first-run tour");
        return;
      }
      startTour("basics");
    }, 700);
    return true;
  }

  function listTours() {
    return TOURS.map((tour) => ({
      id: tour.id,
      titleKey: tour.titleKey,
      descKey: tour.descKey,
    }));
  }

  function bindHelpButtons(root) {
    const scope = root || document;
    scope.querySelectorAll("[data-tour]").forEach((button) => {
      if (button.dataset.tourBound === "1") return;
      button.dataset.tourBound = "1";
      button.addEventListener("click", () => {
        const id = button.getAttribute("data-tour");
        if (id) startTour(id);
      });
    });
  }

  global.VtvTours = {
    startTour,
    stopTour,
    listTours,
    bindHelpButtons,
    maybeStartFirstRunTour,
    hasSeenBasicsTour,
    markBasicsTourSeen,
    BASICS_SEEN_KEY,
  };
})(window);
