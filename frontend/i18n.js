/**
 * Frontend i18n (ja / en).
 * Loads /locales/{lang}.json, applies data-i18n* attributes, exposes t()/setLocale().
 */
(function (global) {
  "use strict";

  const STORAGE_KEY = "vtv-locale";
  const SUPPORTED = ["ja", "en"];
  const DEFAULT_LANG = "ja";

  /** @type {Record<string, Record<string, string>>} */
  const catalogs = Object.create(null);
  /** @type {string} */
  let currentLang = DEFAULT_LANG;
  /** @type {Set<(lang: string) => void>} */
  const listeners = new Set();

  function normalizeLang(lang) {
    if (!lang) return DEFAULT_LANG;
    const primary = String(lang).trim().toLowerCase().replace("_", "-").split("-")[0];
    return SUPPORTED.includes(primary) ? primary : DEFAULT_LANG;
  }

  function detectBrowserLang() {
    const candidates = [];
    if (typeof navigator !== "undefined") {
      if (Array.isArray(navigator.languages)) candidates.push(...navigator.languages);
      if (navigator.language) candidates.push(navigator.language);
    }
    for (const tag of candidates) {
      const lang = normalizeLang(tag);
      if (lang === "en") return "en";
    }
    return DEFAULT_LANG;
  }

  function readStoredLang() {
    try {
      return normalizeLang(localStorage.getItem(STORAGE_KEY));
    } catch (_) {
      return DEFAULT_LANG;
    }
  }

  function writeStoredLang(lang) {
    try {
      localStorage.setItem(STORAGE_KEY, lang);
    } catch (_) {
      /* ignore quota / private mode */
    }
  }

  async function loadCatalog(lang, { force = false } = {}) {
    lang = normalizeLang(lang);
    if (!force && catalogs[lang]) return catalogs[lang];
    // Bust browser HTTP cache for locale JSON (middleware also sets no-cache).
    const response = await fetch(`/locales/${lang}.json?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Failed to load locale ${lang}: HTTP ${response.status}`);
    }
    const data = await response.json();
    catalogs[lang] = data && typeof data === "object" ? data : {};
    return catalogs[lang];
  }

  function format(template, vars) {
    if (!vars || typeof template !== "string") return template;
    return template.replace(/\{(\w+)\}/g, (match, name) => {
      if (Object.prototype.hasOwnProperty.call(vars, name)) {
        const value = vars[name];
        return value == null ? "" : String(value);
      }
      return match;
    });
  }

  function t(key, vars) {
    if (!key) return "";
    const primary = catalogs[currentLang] || {};
    const fallback = catalogs[DEFAULT_LANG] || {};
    const template = primary[key] ?? fallback[key] ?? key;
    return format(template, vars);
  }

  function applyAttr(el, attrName, key) {
    if (!key) return;
    const value = t(key);
    if (attrName === "text") {
      el.textContent = value;
      return;
    }
    if (attrName === "html") {
      el.innerHTML = value;
      return;
    }
    el.setAttribute(attrName, value);
  }

  /**
   * Apply data-i18n / data-i18n-title / data-i18n-placeholder / data-i18n-aria-label
   * / data-i18n-html on elements under root.
   */
  function applyStaticI18n(root) {
    const scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll("[data-i18n]").forEach((el) => {
      applyAttr(el, "text", el.getAttribute("data-i18n"));
    });
    scope.querySelectorAll("[data-i18n-html]").forEach((el) => {
      applyAttr(el, "html", el.getAttribute("data-i18n-html"));
    });
    ["title", "placeholder", "aria-label", "aria-description"].forEach((attr) => {
      const dataAttr = `data-i18n-${attr}`;
      scope.querySelectorAll(`[${dataAttr}]`).forEach((el) => {
        applyAttr(el, attr, el.getAttribute(dataAttr));
      });
    });
    // Checkbox / radio labels that wrap input: data-i18n-label on the label element
    // updates only the trailing text node after the input.
    scope.querySelectorAll("[data-i18n-label]").forEach((el) => {
      const key = el.getAttribute("data-i18n-label");
      const text = t(key);
      const nodes = [...el.childNodes].filter(
        (n) => n.nodeType === Node.TEXT_NODE && n.textContent.trim() !== ""
      );
      if (nodes.length) {
        nodes[nodes.length - 1].textContent = ` ${text}`;
      } else {
        el.appendChild(document.createTextNode(` ${text}`));
      }
    });
  }

  function getLocale() {
    return currentLang;
  }

  async function setLocale(lang, { persist = true, notify = true } = {}) {
    lang = normalizeLang(lang);
    await loadCatalog(lang, { force: true });
    if (lang !== DEFAULT_LANG) {
      await loadCatalog(DEFAULT_LANG, { force: true });
    }
    currentLang = lang;
    if (persist) writeStoredLang(lang);
    if (document.documentElement) {
      document.documentElement.lang = lang;
    }
    applyStaticI18n(document);
    const select = document.getElementById("locale-select");
    if (select && select.value !== lang) select.value = lang;
    if (notify) {
      listeners.forEach((fn) => {
        try {
          fn(lang);
        } catch (err) {
          console.error("i18n listener failed", err);
        }
      });
    }
    return lang;
  }

  function onLocaleChange(fn) {
    if (typeof fn === "function") listeners.add(fn);
    return () => listeners.delete(fn);
  }

  function acceptLanguageHeader() {
    return currentLang;
  }

  async function init() {
    let lang = DEFAULT_LANG;
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      lang = stored ? normalizeLang(stored) : detectBrowserLang();
    } catch (_) {
      lang = detectBrowserLang();
    }
    await loadCatalog(DEFAULT_LANG, { force: true });
    if (lang !== DEFAULT_LANG) await loadCatalog(lang, { force: true });
    currentLang = lang;
    if (document.documentElement) document.documentElement.lang = lang;
    applyStaticI18n(document);
    const select = document.getElementById("locale-select");
    if (select) {
      select.value = lang;
      select.addEventListener("change", () => {
        setLocale(select.value).catch((err) => console.error(err));
      });
    }
    return lang;
  }

  const api = {
    SUPPORTED,
    DEFAULT_LANG,
    STORAGE_KEY,
    t,
    getLocale,
    setLocale,
    applyStaticI18n,
    onLocaleChange,
    acceptLanguageHeader,
    init,
    normalizeLang,
    loadCatalog,
  };

  global.VtvI18n = api;
  global.t = t;
})(typeof window !== "undefined" ? window : globalThis);
