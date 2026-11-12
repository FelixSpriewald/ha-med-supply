/*
 * med-supply-card — dashboard card for the Medication Supply integration.
 *
 * Zero config: `type: custom:med-supply-card` shows every medication.
 * Optional: `device_id: <id>` (one medication), `title: <text>`.
 *
 * No external dependencies (no Lit, no icon font) so it works offline and in
 * the standalone preview (dev/preview.html).
 */

const STATUS = {
  ok: { label: "Ausreichend", color: "var(--success-color, #2e9d5b)" },
  due: { label: "Rezept fällig", color: "var(--warning-color, #e8890c)" },
  requested: { label: "Rezept angefragt", color: "var(--info-color, #2f80d1)" },
  empty: { label: "Leer", color: "var(--error-color, #d33b3b)" },
};

const SLOTS = [
  ["morning", "Morgens"],
  ["noon", "Mittags"],
  ["evening", "Abends"],
  ["night", "Nachts"],
];

const fmtNum = (v, digits = 2) =>
  Number(v).toLocaleString("de-DE", { maximumFractionDigits: digits });

const parseDate = (s) => {
  if (!s || s === "unknown" || s === "unavailable") return null;
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
};

const today = () => {
  const n = new Date();
  return new Date(n.getFullYear(), n.getMonth(), n.getDate());
};

const fmtDate = (d) =>
  d.toLocaleDateString("de-DE", { weekday: "short", day: "2-digit", month: "2-digit" });

const fmtNext = (iso) => {
  if (!iso || iso === "unknown" || iso === "unavailable") return null;
  const d = new Date(iso);
  const day = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diff = Math.round((day - today()) / 86400000);
  const time = d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  if (diff === 0) return `heute ${time}`;
  if (diff === 1) return `morgen ${time}`;
  return `${fmtDate(d)} ${time}`;
};

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

/** One tablet glyph: full (scored round tablet) or half. */
const tabletSvg = (fraction) => {
  if (fraction >= 0.99) {
    return `<svg class="tab" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8.5"/><circle class="shine" cx="7.5" cy="7.5" r="2.4"/></svg>`;
  }
  return `<svg class="tab" viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2 A8 8 0 0 0 10 18 Z"/><path class="ghost" d="M10 2 A8 8 0 0 1 10 18 Z"/></svg>`;
};

const tabletsHtml = (count) => {
  if (count > 6) return `${tabletSvg(1)}<span class="times">× ${fmtNum(count)}</span>`;
  let html = "";
  let rest = count;
  while (rest >= 0.99) {
    html += tabletSvg(1);
    rest -= 1;
  }
  if (rest > 0.01) html += tabletSvg(rest);
  return html;
};

const PILL_ICON = `<svg viewBox="0 0 24 24" aria-hidden="true"><g transform="rotate(-45 12 12)"><rect x="3" y="8" width="18" height="8" rx="4" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 8 h5 a4 4 0 0 1 0 8 h-5 z" fill="currentColor"/></g></svg>`;

class MedSupplyCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._open = {}; // `${deviceId}:${kind}` -> true while an input row is open
    this._drafts = {}; // same key -> typed value
    this._sig = "";
  }

  setConfig(config) {
    this._config = config || {};
    this._sig = "";
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const meds = this._collect();
    const sig = JSON.stringify(
      meds.map((m) => Object.values(m.e).map((id) => {
        const s = hass.states[id];
        return s ? [s.state, s.last_updated] : null;
      }))
    );
    if (sig !== this._sig) {
      this._sig = sig;
      this._render(meds);
    }
  }

  getCardSize() {
    return 5 * Math.max(1, this._collect().length);
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  static getStubConfig() {
    return {};
  }

  /** Group med_supply entities by device, keyed by translation_key. */
  _collect() {
    const hass = this._hass;
    if (!hass || !hass.entities) return [];
    const byDevice = {};
    for (const ent of Object.values(hass.entities)) {
      if (ent.platform !== "med_supply" || !ent.device_id || !ent.translation_key) continue;
      if (this._config?.device_id && ent.device_id !== this._config.device_id) continue;
      (byDevice[ent.device_id] ||= {})[ent.translation_key] = ent.entity_id;
    }
    return Object.entries(byDevice)
      .map(([deviceId, e]) => {
        const dev = hass.devices?.[deviceId];
        return { deviceId, e, name: dev?.name_by_user || dev?.name || "Medikament" };
      })
      .sort((a, b) => a.name.localeCompare(b.name, "de"));
  }

  _st(id) {
    return id ? this._hass.states[id] : undefined;
  }

  _render(meds = this._collect()) {
    const root = this.shadowRoot;
    const title = this._config?.title;
    let body;
    if (!meds.length) {
      body = `<div class="empty-note">Noch kein Medikament eingerichtet.<br>Einstellungen → Geräte &amp; Dienste → „Medication Supply“ hinzufügen.</div>`;
    } else {
      body = meds.map((m) => this._medHtml(m)).join(`<div class="sep"></div>`);
    }
    root.innerHTML = `<style>${CSS}</style><ha-card>${title ? `<div class="title">${esc(title)}</div>` : ""}${body}</ha-card>`;
    this._bind(meds);
  }

  _medHtml(m) {
    const { e, deviceId } = m;
    const stock = this._st(e.stock);
    const days = this._st(e.days_left);
    const status = this._st(e.status)?.state;
    const dose = this._st(e.daily_dose);
    const requested = this._st(e.requested)?.state === "on";
    if (!stock || !days || !dose) {
      return `<div class="med"><div class="head"><span class="name">${esc(m.name)}</span></div><div class="empty-note">Entitäten nicht verfügbar.</div></div>`;
    }

    const st = STATUS[status] || STATUS.ok;
    const tablets = Number(stock.state);
    const strength = stock.attributes.strength_mg;
    const pack = stock.attributes.package_size;
    const lead = Number(days.attributes.lead_days ?? 14);
    const daysLeft = days.state === "unknown" ? null : Number(days.state);
    const emptyOn = parseDate(this._st(e.empty_on)?.state);
    const due = parseDate(this._st(e.prescription_due)?.state);
    const next = fmtNext(this._st(e.next_intake)?.state);

    // Bar: scale shows at least twice the lead time; marker at the lead time.
    const scale = Math.max(lead * 2, 28);
    const fill = daysLeft == null ? 100 : Math.max(0, Math.min(100, (daysLeft / scale) * 100));
    const mark = Math.min(100, (lead / scale) * 100);

    let hint;
    if (status === "empty") hint = "Vorrat ist leer.";
    else if (status === "requested") hint = "Rezept ist angefragt – Packung abholen und buchen.";
    else if (status === "due")
      hint = due && due > today() ? `Rezept bis <b>${fmtDate(due)}</b> besorgen.` : "Rezept <b>jetzt</b> besorgen.";
    else hint = due ? `Rezept erst ab ${fmtDate(due)} nötig.` : "Kein Einnahmeplan hinterlegt.";

    const slots = SLOTS.map(([key, label]) => {
      const s = dose.attributes[key];
      if (!s) return "";
      return `<div class="slot">
          <div class="slot-label">${label}<span class="slot-time">${esc(s.time)}</span></div>
          <div class="slot-tabs" title="${fmtNum(s.tablets)} × ${fmtNum(strength)} mg">${tabletsHtml(s.tablets)}</div>
          <div class="slot-dose">${fmtNum(s.dose_mg)} mg</div>
        </div>`;
    }).join("");

    const k = (kind) => `${deviceId}:${kind}`;
    const inputRow = (kind, label, placeholder) => {
      if (!this._open[k(kind)]) return "";
      const val = this._drafts[k(kind)] ?? placeholder ?? "";
      return `<div class="input-row">
          <label>${label}</label>
          <input type="number" inputmode="decimal" min="0" step="0.5" data-input="${kind}" data-dev="${deviceId}" value="${esc(val)}">
          <span class="unit">Tbl.</span>
          <button class="primary" data-act="book-${kind}" data-dev="${deviceId}">Buchen</button>
          <button class="ghost-btn" data-act="close-${kind}" data-dev="${deviceId}" aria-label="Abbrechen">✕</button>
        </div>`;
    };

    return `<div class="med" style="--accent:${st.color}">
      <div class="head">
        <span class="icon">${PILL_ICON}</span>
        <span class="name">${esc(m.name)}</span>
        <span class="chip">${st.label}</span>
      </div>

      <div class="numbers">
        <div class="big"><span class="value">${daysLeft == null ? "–" : daysLeft}</span><span class="label">${daysLeft === 1 ? "Tag" : "Tage"}</span></div>
        <div class="facts">
          <div><b>${fmtNum(tablets, 1)}</b> Tbl. à ${fmtNum(strength)} mg</div>
          <div>${emptyOn ? `leer am <b>${fmtDate(emptyOn)}</b>` : "&nbsp;"}</div>
        </div>
      </div>

      <div class="bar" role="img" aria-label="Reichweite ${daysLeft ?? "–"} Tage, Vorlauf ${lead} Tage">
        <div class="fill" style="width:${fill}%"></div>
        <div class="mark" style="left:${mark}%"><span>Vorlauf ${lead} T</span></div>
      </div>
      <div class="hint">${hint}</div>

      <div class="plan">${slots || `<div class="empty-note">Kein Einnahmeplan.</div>`}</div>
      <div class="meta">${fmtNum(dose.state)} mg/Tag${next ? ` · nächste Einnahme ${next}` : ""}</div>

      <div class="actions">
        ${e.add_package && pack ? `<button data-act="package" data-dev="${deviceId}">+ Packung (${fmtNum(pack)})</button>` : ""}
        <button data-act="open-addition" data-dev="${deviceId}" class="${this._open[k("addition")] ? "active" : ""}">Zugang…</button>
        <button data-act="open-counted" data-dev="${deviceId}" class="${this._open[k("counted")] ? "active" : ""}">Gezählt…</button>
        ${status !== "ok" || requested ? `<button data-act="requested" data-dev="${deviceId}" class="toggle ${requested ? "on" : ""}" aria-pressed="${requested}">
          ${requested ? "✓ " : ""}Rezept angefragt
        </button>` : ""}
      </div>
      ${inputRow("addition", "Zugang", pack || "")}
      ${inputRow("counted", "Gezählt", "")}
    </div>`;
  }

  _bind(meds) {
    const byId = Object.fromEntries(meds.map((m) => [m.deviceId, m]));
    this.shadowRoot.querySelectorAll("input[data-input]").forEach((input) => {
      input.addEventListener("input", () => {
        this._drafts[`${input.dataset.dev}:${input.dataset.input}`] = input.value;
      });
      input.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") this._act(`book-${input.dataset.input}`, byId[input.dataset.dev]);
        if (ev.key === "Escape") this._act(`close-${input.dataset.input}`, byId[input.dataset.dev]);
      });
    });
    this.shadowRoot.querySelectorAll("button[data-act]").forEach((btn) => {
      btn.addEventListener("click", () => this._act(btn.dataset.act, byId[btn.dataset.dev]));
    });
    const focus = this.shadowRoot.querySelector("input[data-input]");
    if (focus && this._focusNext) {
      focus.focus();
      focus.select();
      this._focusNext = false;
    }
  }

  async _act(act, med) {
    if (!med) return;
    const { e, deviceId } = med;
    const call = (domain, service, data) => this._hass.callService(domain, service, data);
    try {
      if (act === "package") {
        await call("button", "press", { entity_id: e.add_package });
        this._toast("Packung gebucht");
      } else if (act === "requested") {
        await call("switch", "toggle", { entity_id: e.requested });
      } else if (act.startsWith("open-")) {
        const kind = act.slice(5);
        const key = `${deviceId}:${kind}`;
        const wasOpen = this._open[key];
        this._open[`${deviceId}:addition`] = false;
        this._open[`${deviceId}:counted`] = false;
        this._open[key] = !wasOpen;
        this._focusNext = !wasOpen;
        this._render();
      } else if (act.startsWith("close-")) {
        this._open[`${deviceId}:${act.slice(6)}`] = false;
        this._render();
      } else if (act.startsWith("book-")) {
        const kind = act.slice(5);
        const key = `${deviceId}:${kind}`;
        const input = this.shadowRoot.querySelector(`input[data-input="${kind}"][data-dev="${deviceId}"]`);
        const value = Number(String(input?.value ?? "").replace(",", "."));
        if (!Number.isFinite(value) || value < 0 || (kind === "addition" && value === 0)) {
          this._toast("Bitte eine gültige Anzahl eintragen");
          return;
        }
        await call("number", "set_value", { entity_id: e[kind], value });
        await call("button", "press", { entity_id: kind === "addition" ? e.book_addition : e.book_count });
        this._open[key] = false;
        delete this._drafts[key];
        this._render();
        this._toast(kind === "addition" ? `${fmtNum(value)} Tbl. gebucht` : `Vorrat auf ${fmtNum(value)} Tbl. gesetzt`);
      }
    } catch (err) {
      this._toast(err?.message || String(err));
    }
  }

  _toast(message) {
    this.dispatchEvent(new CustomEvent("hass-notification", { detail: { message }, bubbles: true, composed: true }));
  }
}

const CSS = `
  :host { display: block; }
  ha-card {
    display: block;
    padding: 16px;
    background: var(--ha-card-background, var(--card-background-color, #fff));
    color: var(--primary-text-color, #1c1c1c);
    border-radius: var(--ha-card-border-radius, 12px);
    border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color, #e0e0e0));
    box-shadow: var(--ha-card-box-shadow, none);
    font-family: var(--ha-font-family-body, var(--paper-font-body1_-_font-family, system-ui, sans-serif));
  }
  .title { font-size: 1.15rem; font-weight: 500; margin: -2px 0 12px; }
  .sep { height: 1px; background: var(--divider-color, #e0e0e0); margin: 18px -16px; }
  .head { display: flex; align-items: center; gap: 10px; }
  .icon {
    width: 36px; height: 36px; border-radius: 50%; flex: none;
    display: grid; place-items: center;
    color: var(--accent);
    background: color-mix(in srgb, var(--accent) 16%, transparent);
  }
  .icon svg { width: 22px; height: 22px; }
  .name { font-size: 1.1rem; font-weight: 500; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .chip {
    font-size: 0.8rem; font-weight: 500; padding: 4px 10px; border-radius: 999px; white-space: nowrap;
    color: var(--accent);
    background: color-mix(in srgb, var(--accent) 14%, transparent);
  }
  .numbers { display: flex; align-items: center; gap: 16px; margin: 14px 0 10px; }
  .big { display: flex; align-items: baseline; gap: 6px; }
  .big .value { font-size: 2.6rem; font-weight: 600; line-height: 1; color: var(--accent); font-variant-numeric: tabular-nums; }
  .big .label { font-size: 1rem; color: var(--secondary-text-color, #6b6b6b); }
  .facts { font-size: 0.9rem; color: var(--secondary-text-color, #6b6b6b); line-height: 1.5; }
  .facts b { color: var(--primary-text-color, #1c1c1c); font-weight: 500; }
  .bar {
    position: relative; height: 10px; border-radius: 999px; margin: 4px 0 6px;
    background: color-mix(in srgb, var(--secondary-text-color, #888) 18%, transparent);
  }
  .fill { position: absolute; inset: 0 auto 0 0; border-radius: 999px; background: var(--accent); transition: width .4s ease; }
  .mark { position: absolute; top: -3px; bottom: -3px; width: 2px; margin-left: -1px; background: var(--primary-text-color, #1c1c1c); opacity: .55; border-radius: 1px; }
  .mark span {
    position: absolute; top: 17px; left: 50%; transform: translateX(-50%);
    font-size: 0.7rem; color: var(--secondary-text-color, #6b6b6b); white-space: nowrap;
  }
  .hint { font-size: 0.9rem; margin: 18px 0 14px; }
  .hint b { font-weight: 600; }
  .plan { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 8px; }
  .slot {
    border-radius: 10px; padding: 10px 12px;
    background: color-mix(in srgb, var(--secondary-text-color, #888) 8%, transparent);
  }
  .slot-label { font-size: 0.8rem; color: var(--secondary-text-color, #6b6b6b); display: flex; justify-content: space-between; gap: 6px; }
  .slot-time { font-variant-numeric: tabular-nums; }
  .slot-tabs { display: flex; align-items: center; gap: 4px; margin: 8px 0 4px; min-height: 22px; color: var(--accent); }
  .tab { width: 22px; height: 22px; flex: none; }
  .tab circle, .tab path { fill: currentColor; }
  .tab .ghost { fill: none; stroke: currentColor; stroke-width: 1.2; stroke-dasharray: 2 2; opacity: .6; }
  .tab .shine { fill: #fff; opacity: .35; }
  .times { font-size: 0.85rem; color: var(--primary-text-color, #1c1c1c); }
  .slot-dose { font-size: 0.95rem; font-weight: 500; }
  .meta { font-size: 0.8rem; color: var(--secondary-text-color, #6b6b6b); margin: 8px 0 14px; }
  .actions { display: flex; flex-wrap: wrap; gap: 8px; }
  button {
    font: inherit; font-size: 0.875rem; font-weight: 500; cursor: pointer;
    padding: 8px 14px; border-radius: 999px; min-height: 36px;
    color: var(--primary-text-color, #1c1c1c);
    background: transparent;
    border: 1px solid var(--divider-color, #d0d0d0);
    transition: background .15s, border-color .15s;
  }
  button:hover { background: color-mix(in srgb, var(--primary-text-color, #000) 6%, transparent); }
  button:focus-visible, input:focus-visible { outline: 2px solid var(--primary-color, #03a9f4); outline-offset: 2px; }
  button.active { border-color: var(--primary-color, #03a9f4); color: var(--primary-color, #03a9f4); }
  button.toggle.on { border-color: transparent; color: var(--info-color, #2f80d1); background: color-mix(in srgb, var(--info-color, #2f80d1) 14%, transparent); }
  button.primary { border-color: transparent; color: var(--text-primary-color, #fff); background: var(--primary-color, #03a9f4); }
  button.primary:hover { filter: brightness(1.08); }
  .ghost-btn { border-color: transparent; padding: 8px 10px; color: var(--secondary-text-color, #6b6b6b); }
  .input-row { display: flex; align-items: center; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
  .input-row label { font-size: 0.875rem; color: var(--secondary-text-color, #6b6b6b); }
  .input-row input {
    font: inherit; width: 90px; padding: 8px 10px; border-radius: 8px;
    color: var(--primary-text-color, #1c1c1c);
    background: var(--input-fill-color, color-mix(in srgb, var(--secondary-text-color, #888) 10%, transparent));
    border: 1px solid var(--divider-color, #d0d0d0);
  }
  .unit { font-size: 0.875rem; color: var(--secondary-text-color, #6b6b6b); }
  .empty-note { font-size: 0.9rem; color: var(--secondary-text-color, #6b6b6b); padding: 8px 0; }
`;

if (!customElements.get("med-supply-card")) {
  customElements.define("med-supply-card", MedSupplyCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "med-supply-card",
    name: "Medikamentenvorrat",
    description: "Vorrat, Reichweite, Einnahmeplan und Buchen für Medication Supply.",
    preview: true,
  });
}
