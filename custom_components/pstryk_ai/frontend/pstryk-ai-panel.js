/*
 * Pstryk AI – sidebar panel for Home Assistant.
 * Self-contained web component (no external libraries). Reads the state of the
 * pstryk_ai entities and draws: current price, the 48 h plan (prices, cheapest
 * windows, buffer heating, device schedules), the 7-day forecast with P10–P90,
 * the buffer decision, meter data, forecast quality and data-source status.
 */

const SOURCE = {
  ACTUAL_PSTRYK: { label: "Potwierdzona (Pstryk)", short: "Pstryk", cls: "src-actual" },
  PUBLISHED_TGE: { label: "Giełda – szacunek", short: "Giełda", cls: "src-market" },
  MODEL_FORECAST: { label: "Prognoza", short: "Prognoza", cls: "src-forecast" },
  FALLBACK_FORECAST: { label: "Prognoza bazowa", short: "Prognoza", cls: "src-forecast" },
  UNAVAILABLE: { label: "Brak danych", short: "Brak", cls: "src-none" },
};
const MODE = {
  advisory: { label: "Tryb doradczy", cls: "chip-info" },
  control: { label: "Sterowanie aktywne", cls: "chip-ok" },
  fallback: { label: "Sterowanie lokalne", cls: "chip-warn" },
};
const STATUS = {
  ok: ["OK", "chip-ok"],
  pending: ["Oczekiwanie", "chip-info"],
  error: ["Błąd", "chip-err"],
  auth_error: ["Błąd klucza", "chip-err"],
  rate_limited: ["Limit zapytań", "chip-warn"],
  disabled: ["Wyłączone", "chip-muted"],
  disconnected: ["Rozłączono", "chip-err"],
  not_configured: ["Nieskonfigurowane", "chip-muted"],
};
const DAYS = ["Nd", "Pn", "Wt", "Śr", "Cz", "Pt", "Sb"];

const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const num = (v) => {
  const n = typeof v === "number" ? v : parseFloat(v);
  return Number.isFinite(n) ? n : null;
};
const fmt = (v, d = 3) => (num(v) === null ? "–" : num(v).toFixed(d).replace(".", ","));
const HOUR = 3600 * 1000;

class PstrykAIPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._sig = "";
    this._timer = null;
  }

  set hass(hass) {
    this._hass = hass;
    const sig = this._signature();
    if (sig !== this._sig) {
      this._sig = sig;
      this._render();
    }
    if (this._menu) {
      this._menu.hass = hass;
    }
  }

  set narrow(v) {
    this._narrow = v;
    if (this._menu) this._menu.narrow = v;
  }

  set panel(p) {
    this._panel = p;
  }

  connectedCallback() {
    // the "now" marker and relative times move even without state changes
    this._timer = setInterval(() => this._render(), 60 * 1000);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
  }

  // ------------------------------------------------------------ data access
  _st(key, domain = "sensor") {
    const states = this._hass?.states || {};
    const direct = states[`${domain}.pstryk_ai_${key}`];
    if (direct) return direct;
    // fall back to the entity registry (e.g. a second config entry: *_2)
    const ents = this._hass?.entities || {};
    for (const id in ents) {
      const e = ents[id];
      if (e.platform === "pstryk_ai" && id.startsWith(`${domain}.`) && id.includes(`_${key}`)) return states[id];
    }
    return undefined;
  }
  _val(key, domain) {
    return this._st(key, domain)?.state;
  }
  _attr(key, attr, domain) {
    return this._st(key, domain)?.attributes?.[attr];
  }
  _signature() {
    const keys = ["last_update", "current_buy_price", "buffer_plan_reason", "dhw_plan_reason", "forecast_7d", "average_tomorrow", "cheapest_3h", "avg_daily_cost"];
    return keys.map((k) => this._st(k)?.last_updated || "").join("|") + (this._st("buffer_should_heat", "binary_sensor")?.state || "");
  }

  _tz() {
    return this._hass?.config?.time_zone || "Europe/Warsaw";
  }
  _time(iso) {
    if (!iso) return "–";
    return new Date(iso).toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit", timeZone: this._tz() });
  }
  _dayTime(iso) {
    if (!iso) return "–";
    const d = new Date(iso);
    const today = this._localDate(new Date());
    const day = this._localDate(d);
    const diff = Math.round((Date.parse(day) - Date.parse(today)) / (24 * HOUR));
    const label = diff === 0 ? "dziś" : diff === 1 ? "jutro" : diff === -1 ? "wczoraj" : this._weekday(d);
    return `${label} ${this._time(iso)}`;
  }
  _localDate(d) {
    return d.toLocaleDateString("sv-SE", { timeZone: this._tz() });
  }
  _weekday(d) {
    const name = d.toLocaleDateString("pl-PL", { weekday: "short", timeZone: this._tz() });
    const date = d.toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit", timeZone: this._tz() });
    return `${name.charAt(0).toUpperCase()}${name.slice(1)} ${date}`;
  }
  _hourLocal(d) {
    return parseInt(d.toLocaleTimeString("en-GB", { hour: "2-digit", hour12: false, timeZone: this._tz() }), 10);
  }

  // ------------------------------------------------------------ rendering
  _render() {
    if (!this._hass) return;
    const root = this.shadowRoot;
    const found = !!this._st("current_buy_price");
    root.innerHTML = `<style>${STYLE}</style>
      <div class="toolbar"><span class="menu"></span><h1>Pstryk AI</h1>
        <span class="sub">${found ? `aktualizacja ${esc(this._dayTime(this._val("last_update")))}` : ""}</span>
        <span class="spacer"></span>${found ? this._statusChips() : ""}</div>
      <div class="content">${found ? this._body() : this._empty()}</div>`;
    const slot = root.querySelector(".menu");
    if (!this._menu) {
      this._menu = document.createElement("ha-menu-button");
    }
    this._menu.hass = this._hass;
    this._menu.narrow = this._narrow;
    slot.appendChild(this._menu);
    root.querySelectorAll("[data-more]").forEach((el) =>
      el.addEventListener("click", () => this._moreInfo(el.dataset.more))
    );
  }

  _moreInfo(entityId) {
    this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId }, bubbles: true, composed: true }));
  }

  _empty() {
    return `<div class="card empty"><h2>Brak danych Pstryk AI</h2>
      <p>Nie znaleziono encji integracji <b>pstryk_ai</b>. Dodaj integrację w <i>Ustawienia → Urządzenia i usługi</i>
      lub poczekaj na pierwsze pobranie danych.</p></div>`;
  }

  _statusChips() {
    const chip = (label, key) => {
      const s = this._val(key) || "pending";
      const [txt, cls] = STATUS[s] || [s, "chip-muted"];
      return `<span class="chip ${cls}" title="${esc(label)}: ${esc(txt)}">${esc(label)}: ${esc(txt)}</span>`;
    };
    return `<span class="chips">${chip("Pstryk", "pstryk_api_status")}${chip("Rynek", "market_data_status")}${chip(
      "MQTT",
      "mqtt_status"
    )}</span>`;
  }

  _body() {
    return `
      <div class="grid top">
        ${this._nowCard()}
        ${this._bufferCard()}
        ${this._st("dhw_plan_reason") ? this._storageCard("dhw") : ""}
      </div>
      ${this._planCard()}
      ${this._forecastCard()}
      <div class="grid">
        ${this._windowsCard()}
        ${this._devicesCard()}
      </div>
      ${this._spendsCard()}
      <div class="grid">
        ${this._meterCard()}
        ${this._qualityCard()}
      </div>
      ${this._legend()}`;
  }

  // ------------------------------------------------------------ "now" card
  _level(value) {
    // same reference as "Tania energia teraz": the next 24 hours (not the past hours of today)
    const series = this._attr("forecast_7d", "series") || {};
    let ref = (series.value || []).slice(0, 24).map(num).filter((v) => v !== null);
    if (ref.length < 4) ref = (this._attr("average_today", "prices") || []).map((p) => num(p.value)).filter((v) => v !== null);
    if (value === null || ref.length < 4) return { label: "", cls: "" };
    const sorted = [...ref].sort((a, b) => a - b);
    const q = (p) => sorted[Math.min(sorted.length - 1, Math.floor(p * (sorted.length - 1)))];
    if (value <= q(0.25)) return { label: "Tanio", cls: "lvl-cheap" };
    if (value >= q(0.75)) return { label: "Drogo", cls: "lvl-exp" };
    return { label: "Średnio", cls: "lvl-mid" };
  }

  _nowCard() {
    const cur = this._st("current_buy_price");
    const value = num(cur?.state);
    const src = SOURCE[cur?.attributes?.source] || SOURCE.UNAVAILABLE;
    const lvl = this._level(value);
    const next = this._st("next_hour_price");
    const sell = num(this._val("current_sell_price"));
    const allIn = num(this._val("current_all_in_price"));
    const cheap = this._val("cheap_now", "binary_sensor") === "on";
    const tomorrow = this._val("tomorrow_confirmed", "binary_sensor") === "on";
    const nextVal = num(next?.state);
    const trend = value !== null && nextVal !== null ? (nextVal > value * 1.02 ? "↗" : nextVal < value * 0.98 ? "↘" : "→") : "";
    return `<div class="card now">
      <div class="card-head"><h2>Teraz</h2><span class="badge ${src.cls}">${esc(src.label)}</span></div>
      <div class="price-row" data-more="${esc(cur?.entity_id || "")}">
        <div class="big ${lvl.cls}">${fmt(value)}<span class="unit"> zł/kWh</span></div>
        ${lvl.label ? `<div class="lvl ${lvl.cls}">${lvl.label}</div>` : ""}
      </div>
      <div class="kv">
        <div><span>Następna godzina</span><b>${fmt(nextVal)} ${trend}</b><small>${esc(SOURCE[next?.attributes?.source]?.short || "")}</small></div>
        <div><span>Z dystrybucją</span><b>${fmt(allIn)}</b><small>${
          num(this._attr("current_all_in_price", "distribution_gross")) ? "szacunek" : "brak stawki dystrybucji – ustaw w opcjach"
        }</small></div>
        ${sell !== null ? `<div><span>Sprzedaż</span><b>${fmt(sell)}</b><small>prosument</small></div>` : ""}
      </div>
      <div class="chips">
        <span class="chip ${cheap ? "chip-ok" : "chip-muted"}">${cheap ? "Tania energia teraz" : "Energia nie jest tania"}</span>
        <span class="chip ${tomorrow ? "chip-ok" : "chip-warn"}">${tomorrow ? "Ceny na jutro potwierdzone" : "Jutro: prognoza (Pstryk jeszcze nie opublikował)"}</span>
        ${this._zoneChip()}
      </div>
    </div>`;
  }

  // ------------------------------------------------------------ storage cards
  _zoneChip() {
    const z = this._st("distribution_zone");
    if (!z) return "";
    const label = { flat: "stała", peak: "szczyt / dzienna", offpeak: "pozaszczyt / nocna", peak2: "szczyt popołudniowy" }[z.state] || z.state;
    return `<span class="chip ${z.state === "offpeak" ? "chip-ok" : "chip-info"}">Dystrybucja: ${esc(label)}</span>`;
  }

  _bufferCard() {
    return this._storageCard("buffer");
  }

  _storageCard(kind) {
    const isDhw = kind === "dhw";
    const title = isDhw ? "Ciepła woda (CWU)" : "Bufor ciepła";
    const heat = this._st(isDhw ? "dhw_should_heat" : "buffer_should_heat", "binary_sensor");
    const reason = this._st(isDhw ? "dhw_plan_reason" : "buffer_plan_reason");
    const planSensor = this._st(isDhw ? "dhw_target_temperature" : "buffer_target_temperature");
    const plan = planSensor?.attributes || {};
    if (!heat || heat.state === "unavailable" || heat.state === "unknown" || !reason) {
      return `<div class="card buffer"><div class="card-head"><h2>${title}</h2></div>
        <p class="muted">Optymalizacja jest wyłączona albo brak danych. Włącz ją i wskaż czujniki temperatury w opcjach integracji.</p></div>`;
    }
    const on = heat.state === "on";
    const heaterOn = !!plan.heater_should_run;
    const heaterKw = num(plan.heater_power_kw);
    const mode = MODE[heat.attributes?.mode] || MODE.advisory;
    const steps = reason.attributes?.schedule || [];
    const topS = this._st(isDhw ? "dhw_top_temperature" : "buffer_temperature");
    const botS = this._st(isDhw ? "dhw_bottom_temperature" : "buffer_bottom_temperature");
    const top = num(topS?.state);
    const bottom = num(botS?.state);
    const current = top !== null && bottom !== null ? (top + bottom) / 2 : top ?? (steps.length ? num(steps[0].t_start) : null);
    const src = topS?.attributes?.source ?? topS?.attributes?.top_source;
    const srcLabel = { mqtt: "z MQTT", entity: "z czujnika HA", mqtt_stale: "MQTT – brak świeżego odczytu", none: "brak odczytu" }[src] || "";
    const soc = num(plan.soc_pct ?? this._val(isDhw ? "dhw_soc" : "buffer_soc"));
    const valve = this._st("valve_position");
    const valveLabel = { buffer: "pompa → bufor", dhw: "pompa → CWU", idle: "pompa – postój" }[valve?.state];
    const mod = num(plan.hp_modulation_pct);
    const boost = plan.strategy === "boost";
    let title2 = on ? (mod && mod < 99 ? `Grzej teraz – moc ${mod}%` : "Grzej teraz") : "Nie grzej teraz";
    let icon = on ? "🔥" : "⏸";
    if (boost) {
      title2 = on ? `Doładuj teraz – 100% do ${fmt(plan.boost_target_t, 0)} °C` : "Pompa pracuje samodzielnie";
      icon = on ? "🚀" : "🤖";
    }
    if (heaterOn && on) { title2 = `Pompa + grzałka ${fmt(heaterKw, 1)} kW`; icon = "🔥⚡"; }
    else if (heaterOn) { title2 = `Grzałka teraz ${fmt(heaterKw, 1)} kW`; icon = "⚡"; }
    const leg = isDhw ? this._st("legionella") : null;
    return `<div class="card buffer">
      <div class="card-head"><h2>${title}</h2><span class="chips">
        ${valve && valveLabel ? `<span class="chip chip-info">${esc(valveLabel)}</span>` : ""}
        <span class="chip ${boost ? "chip-ok" : "chip-info"}" title="Strategia sterowania pompą">${boost ? "Tylko doładowanie" : "Pełne sterowanie"}</span>
        <span class="chip ${mode.cls}">${esc(mode.label)}</span></span></div>
      <div class="storage-row">
        ${this._layerBar(top, bottom, soc, isDhw)}
        <div class="storage-main">
          <div class="decision ${on || heaterOn ? "heat" : "idle"}" data-more="${esc(heat.entity_id)}">
            <div class="icon">${icon}</div>
            <div><div class="dec-title">${esc(title2)}</div><div class="dec-sub">${esc(reason.state || "")}</div></div>
          </div>
          <div class="kv">
            <div data-more="${esc(topS?.entity_id || "")}"><span>${bottom !== null ? "Średnio" : "Teraz"}</span><b>${fmt(current, 1)} °C</b><small>${esc(srcLabel)}</small></div>
            <div><span>Cel</span><b>${fmt(planSensor?.state, 1)} °C</b></div>
            <div><span>${boost ? (on ? "Doładowanie" : "Następne doładowanie") : on || heaterOn ? "Grzanie" : "Następne grzanie"}</span><b>${esc(
              plan.recommended_start ? (Date.parse(plan.recommended_start) <= Date.now() ? "teraz" : this._dayTime(plan.recommended_start)) : "–"
            )}</b>
              <small>${plan.recommended_stop ? `do ${esc(this._time(plan.recommended_stop))}` : ""}</small></div>
            <div><span>Koszt 24 h</span><b>${fmt(plan.expected_cost_pln, 2)} zł</b>${num(plan.fuel_cost_pln) ? `<small>w tym gaz ${fmt(plan.fuel_cost_pln, 2)} zł</small>` : ""}</div>
            <div><span>Oszczędność</span><b>${fmt(plan.expected_savings_pln, 2)} zł</b><small>${boost ? "vs sama pompa ciepła" : "vs termostat (to samo minimum)"}</small></div>
            ${plan.heater_next_start ? `<div><span>Grzałka</span><b>${esc(this._dayTime(plan.heater_next_start))}</b></div>` : ""}
            ${leg ? `<div data-more="${esc(leg.entity_id)}"><span>Antylegionella</span><b>${esc(leg.state && leg.state !== "unknown" ? this._dayTime(leg.state) : "–")}</b>
              <small>${leg.attributes?.planned_at ? `plan: ${esc(this._dayTime(leg.attributes.planned_at))}` : ""}</small></div>` : ""}
          </div>
        </div>
      </div>
      ${this._tempChart(steps, isDhw)}
    </div>`;
  }

  _layerBar(top, bottom, soc, isDhw) {
    const color = (t) => {
      if (t === null) return "var(--c-muted)";
      const x = Math.max(0, Math.min(1, (t - 25) / 40));
      const hue = 220 - x * 220; // blue -> red
      return `hsl(${hue} 75% 50%)`;
    };
    const b = bottom ?? top;
    return `<div class="layers" title="${isDhw ? "CWU" : "Bufor"}: góra ${fmt(top, 1)} °C, dół ${fmt(bottom, 1)} °C">
      <div class="tank" style="background: linear-gradient(to bottom, ${color(top)}, ${color(b)})">
        <span class="t-top">${fmt(top, 1)}°</span>
        ${bottom !== null ? `<span class="t-bot">${fmt(bottom, 1)}°</span>` : ""}
      </div>
      <div class="soc">${soc !== null ? `${Math.round(soc)}%` : "–"}</div>
    </div>`;
  }

  _tempChart(steps, isDhw = false) {
    if (!steps.length) return "";
    const W = 560, H = 120, P = { l: 34, r: 8, t: 8, b: 18 };
    const temps = steps.flatMap((s) => [num(s.t_start), num(s.t_end)]).filter((v) => v !== null);
    const plan = this._attr(isDhw ? "dhw_target_temperature" : "buffer_target_temperature") || {};
    const minT = isDhw ? null : num(this._val("buffer_min_t", "number"));
    const maxT = isDhw ? null : num(this._val("buffer_max_t", "number"));
    const lo = Math.floor(Math.min(...temps, minT ?? Infinity) - 2);
    const hi = Math.ceil(Math.max(...temps, maxT ?? -Infinity) + 2);
    const x = (i) => P.l + (i / steps.length) * (W - P.l - P.r);
    const y = (t) => P.t + (1 - (t - lo) / (hi - lo || 1)) * (H - P.t - P.b);
    const heaterBars = steps
      .map((s, i) =>
        num(s.heater_kwh) > 0
          ? `<rect class="heaterbar" x="${x(i)}" y="${P.t}" width="${Math.max(1, x(i + 1) - x(i) - 0.5)}" height="${(H - P.t - P.b) / 3}"><title>${esc(
              this._dayTime(s.start)
            )}: grzałka ${fmt(s.heater_kwh, 1)} kWh</title></rect>`
          : ""
      )
      .join("");
    const bars = heaterBars + steps
      .map((s, i) =>
        s.heat > 0
          ? `<rect class="heatbar" x="${x(i)}" y="${P.t}" width="${Math.max(1, x(i + 1) - x(i) - 0.5)}" height="${H - P.t - P.b}"><title>${esc(
              this._dayTime(s.start)
            )}: grzanie, ${fmt(s.electric_kwh, 2)} kWh, ${fmt(s.cost, 2)} zł</title></rect>`
          : ""
      )
      .join("");
    const pts = steps.map((s, i) => `${x(i)},${y(num(s.t_start))}`).concat(`${x(steps.length)},${y(num(steps.at(-1).t_end))}`);
    const limit = (t, cls, label) =>
      t === null ? "" : `<line class="${cls}" x1="${P.l}" x2="${W - P.r}" y1="${y(t)}" y2="${y(t)}"/><text class="axis" x="${P.l - 4}" y="${y(t) + 3}" text-anchor="end">${t}°</text><title>${label}</title>`;
    const ticks = steps
      .map((s, i) => (i % 6 === 0 ? `<text class="axis" x="${x(i)}" y="${H - 4}">${esc(this._time(s.start))}</text>` : ""))
      .join("");
    void plan;
    return `<div class="chart-title">Temperatura ${isDhw ? "CWU" : "bufora"} i grzanie (plan ${steps.length} h)</div>
      <svg viewBox="0 0 ${W} ${H}" class="chart">${bars}${limit(minT, "lim", "minimum")}${limit(maxT, "lim", "maksimum")}
      <polyline class="templine" points="${pts.join(" ")}"/>${ticks}</svg>`;
  }

  // ------------------------------------------------------------ 48 h plan
  _series48() {
    const today = this._attr("average_today", "prices") || [];
    const tomorrow = this._attr("average_tomorrow", "prices") || [];
    const fc = this._attr("forecast_7d", "series") || {};
    const band = {};
    (fc.start || []).forEach((s, i) => (band[s] = { p10: num(fc.p10?.[i]), p90: num(fc.p90?.[i]) }));
    return [...today, ...tomorrow].map((p) => ({
      start: p.start,
      value: num(p.value),
      source: p.source,
      p10: band[p.start]?.p10 ?? null,
      p90: band[p.start]?.p90 ?? null,
    }));
  }

  _planCard() {
    const data = this._series48();
    if (!data.length) return "";
    const W = 1000, P = { l: 78, r: 10, t: 14, b: 22 }, CH = 190;
    const lanes = this._lanes();
    const laneH = 18;
    const H = CH + lanes.length * (laneH + 6) + 8;
    const vals = data.flatMap((d) => [d.value, d.p90, d.p10]).filter((v) => v !== null);
    const lo = Math.min(0, ...vals);
    const hi = Math.max(...vals) * 1.08 || 1;
    const n = data.length;
    const bw = (W - P.l - P.r) / n;
    const x = (i) => P.l + i * bw;
    const y = (v) => P.t + (1 - (v - lo) / (hi - lo)) * (CH - P.t - P.b);
    const idxOf = (iso) => data.findIndex((d) => d.start === iso);
    const cheapHours = new Set(this._attr("cheapest_3h", "hours") || []);
    const expHours = new Set(this._attr("most_expensive_hour", "hours") || []);
    const now = Date.now();
    const nowIdx = data.findIndex((d) => Date.parse(d.start) <= now && now < Date.parse(d.start) + HOUR);

    let svg = "";
    // grid
    const step = niceStep((hi - lo) / 4);
    for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
      svg += `<line class="grid" x1="${P.l}" x2="${W - P.r}" y1="${y(v)}" y2="${y(v)}"/><text class="axis" x="${P.l - 6}" y="${y(v) + 4}" text-anchor="end">${fmt(v, 2)}</text>`;
    }
    // highlights
    data.forEach((d, i) => {
      if (cheapHours.has(d.start)) svg += `<rect class="hl-cheap" x="${x(i)}" y="${P.t}" width="${bw}" height="${CH - P.t - P.b}"/>`;
      if (expHours.has(d.start)) svg += `<rect class="hl-exp" x="${x(i)}" y="${P.t}" width="${bw}" height="${CH - P.t - P.b}"/>`;
    });
    // midnight separator
    data.forEach((d, i) => {
      if (i > 0 && this._hourLocal(new Date(d.start)) === 0)
        svg += `<line class="midnight" x1="${x(i)}" x2="${x(i)}" y1="${P.t - 8}" y2="${H - 4}"/><text class="daylbl" x="${x(i) + 4}" y="${P.t - 2}">${esc(
          this._weekday(new Date(d.start))
        )}</text>`;
    });
    svg += `<text class="daylbl" x="${P.l + 4}" y="${P.t - 2}">${esc(this._weekday(new Date(data[0].start)))}</text>`;
    // bars
    data.forEach((d, i) => {
      const src = SOURCE[d.source] || SOURCE.UNAVAILABLE;
      const tip = `${this._dayTime(d.start)} – ${fmt(d.value)} zł/kWh (${src.label})${
        d.p10 !== null && d.source?.endsWith("FORECAST") ? `, zakres ${fmt(d.p10)}–${fmt(d.p90)}` : ""
      }`;
      if (d.value === null) {
        svg += `<rect class="bar src-none" x="${x(i) + 1}" y="${y(0) - 3}" width="${bw - 2}" height="3"><title>${esc(tip)}</title></rect>`;
        return;
      }
      const top = y(Math.max(d.value, 0));
      const bottom = y(Math.min(d.value, 0));
      svg += `<rect class="bar ${src.cls}${i < nowIdx ? " past" : ""}" x="${x(i) + 1}" y="${top}" width="${Math.max(1, bw - 2)}" height="${Math.max(1, bottom - top)}"><title>${esc(tip)}</title></rect>`;
      if (d.source?.endsWith("FORECAST") && d.p10 !== null && d.p90 !== null) {
        const cx = x(i) + bw / 2;
        svg += `<line class="whisker" x1="${cx}" x2="${cx}" y1="${y(d.p90)}" y2="${y(d.p10)}"/>`;
      }
    });
    svg += `<line class="zero" x1="${P.l}" x2="${W - P.r}" y1="${y(0)}" y2="${y(0)}"/>`;
    // hour labels
    data.forEach((d, i) => {
      const h = this._hourLocal(new Date(d.start));
      if (h % 3 === 0) svg += `<text class="axis" x="${x(i) + bw / 2}" y="${CH - 6}" text-anchor="middle">${String(h).padStart(2, "0")}</text>`;
    });
    // lanes (Gantt)
    lanes.forEach((lane, li) => {
      const ly = CH + li * (laneH + 6) + 4;
      svg += `<text class="lane-lbl" x="${P.l - 6}" y="${ly + laneH - 5}" text-anchor="end">${esc(lane.short)}</text>`;
      svg += `<rect class="lane-bg" x="${P.l}" y="${ly}" width="${W - P.l - P.r}" height="${laneH}" rx="4"/>`;
      lane.hours.forEach((h) => {
        const i = idxOf(h.start);
        if (i < 0) return;
        svg += `<rect class="lane-on ${lane.cls}" x="${x(i) + 0.5}" y="${ly + 2}" width="${Math.max(2, bw - 1)}" height="${laneH - 4}" rx="3"><title>${esc(
          `${lane.name}: ${this._dayTime(h.start)}${h.note ? " – " + h.note : ""}`
        )}</title></rect>`;
      });
    });
    // now marker
    if (nowIdx >= 0) {
      const frac = (now - Date.parse(data[nowIdx].start)) / HOUR;
      const nx = x(nowIdx) + frac * bw;
      svg += `<line class="now" x1="${nx}" x2="${nx}" y1="${P.t - 8}" y2="${H - 4}"/><text class="nowlbl" x="${nx + 3}" y="${H - 6}">teraz</text>`;
    }
    const best = this._attr("cheapest_3h", "start");
    return `<div class="card">
      <div class="card-head"><h2>Plan na dziś i jutro</h2>
        <span class="muted">${best ? `Najtańsze 3 h: <b>${esc(this._dayTime(best))}–${esc(this._time(this._attr("cheapest_3h", "end")))}</b>` : ""}</span></div>
      <svg viewBox="0 0 ${W} ${H}" class="chart wide">${svg}</svg>
    </div>`;
  }

  _lanes() {
    const lanes = [];
    for (const [key, label] of [["buffer_plan_reason", "bufor"], ["dhw_plan_reason", "CWU"]]) {
      const steps = this._attr(key, "schedule") || [];
      if (!steps.length) continue;
      const boost = this._attr(key === "buffer_plan_reason" ? "buffer_target_temperature" : "dhw_target_temperature", "strategy") === "boost";
      if (boost) {
        const b = steps.filter((s) => num(s.heat) > 0).map((s) => ({ start: s.start, note: `100% · COP ${fmt(s.cop, 1)}` }));
        lanes.push({ name: `Doładowanie 100% → ${label}`, short: `Doład. ${label}`, cls: "lane-heat", hours: b });
      } else {
        const hp = steps.filter((s) => (num(s.hp_kwh) ?? (s.heat > 0 ? 1 : 0)) > 0).map((s) => ({ start: s.start, note: `COP ${fmt(s.cop, 1)}` }));
        lanes.push({ name: `Pompa ciepła → ${label}`, short: `PC→${label}`, cls: "lane-heat", hours: hp });
      }
      const heater = steps.filter((s) => num(s.heater_kwh) > 0).map((s) => ({ start: s.start, note: `${fmt(s.heater_kwh, 1)} kWh` }));
      if (heater.length || this._st(key === "buffer_plan_reason" ? "buffer_heater_power" : "dhw_heater_power"))
        lanes.push({ name: `Grzałka ${label}`, short: `Grzałka ${label}`, cls: "lane-heater", hours: heater });
    }
    const pv = this._attr("pv_production_today", "series") || [];
    if (pv.length)
      lanes.push({
        name: "Nadwyżka PV",
        short: "PV",
        cls: "lane-pv",
        hours: pv.filter((p) => num(p.surplus) > 0.05).map((p) => ({ start: p.start, note: `${fmt(p.surplus, 2)} kWh` })),
      });
    for (const st of this._schedules()) {
      lanes.push({
        name: st.attributes.profile || st.attributes.friendly_name,
        short: (st.attributes.profile || "Urządzenie").slice(0, 12),
        cls: "lane-dev",
        hours: (st.attributes.hours || []).map((h) => ({ start: h })),
      });
    }
    return lanes;
  }

  _schedules() {
    const states = this._hass?.states || {};
    return Object.keys(states)
      .filter((id) => id.startsWith("sensor.pstryk_ai_schedule_"))
      .map((id) => states[id]);
  }

  // ------------------------------------------------------------ 7 days
  _forecastCard() {
    const s = this._attr("forecast_7d", "series");
    if (!s || !s.start?.length) return "";
    const W = 1000, H = 200, P = { l: 78, r: 10, t: 16, b: 22 };
    const n = s.start.length;
    const vals = [...s.value, ...s.p10, ...s.p90].map(num).filter((v) => v !== null);
    const lo = Math.min(0, ...vals);
    const hi = Math.max(...vals) * 1.05 || 1;
    const x = (i) => P.l + (i / Math.max(1, n - 1)) * (W - P.l - P.r);
    const y = (v) => P.t + (1 - (v - lo) / (hi - lo)) * (H - P.t - P.b);
    let svg = "";
    const step = niceStep((hi - lo) / 4);
    for (let v = Math.ceil(lo / step) * step; v <= hi; v += step)
      svg += `<line class="grid" x1="${P.l}" x2="${W - P.r}" y1="${y(v)}" y2="${y(v)}"/><text class="axis" x="${P.l - 6}" y="${y(v) + 4}" text-anchor="end">${fmt(v, 2)}</text>`;
    // band
    const upper = [], lower = [];
    s.start.forEach((_, i) => {
      const p10 = num(s.p10[i]), p90 = num(s.p90[i]);
      if (p10 !== null && p90 !== null) {
        upper.push(`${x(i)},${y(p90)}`);
        lower.unshift(`${x(i)},${y(p10)}`);
      }
    });
    if (upper.length > 1) svg += `<polygon class="band" points="${upper.concat(lower).join(" ")}"><title>Przedział P10–P90</title></polygon>`;
    // segments by source
    for (let i = 1; i < n; i++) {
      const a = num(s.value[i - 1]), b = num(s.value[i]);
      if (a === null || b === null) continue;
      const cls = (SOURCE[s.source[i]] || SOURCE.UNAVAILABLE).cls;
      svg += `<line class="seg ${cls}" x1="${x(i - 1)}" x2="${x(i)}" y1="${y(a)}" y2="${y(b)}"/>`;
    }
    // day separators + labels
    const days = this._dailySummary(s);
    s.start.forEach((iso, i) => {
      const d = new Date(iso);
      if (this._hourLocal(d) === 0) svg += `<line class="midnight" x1="${x(i)}" x2="${x(i)}" y1="${P.t}" y2="${H - P.b}"/>`;
      if (this._hourLocal(d) === 12) svg += `<text class="daylbl" x="${x(i)}" y="${H - 6}" text-anchor="middle">${esc(this._weekday(d))}</text>`;
    });
    const cards = days
      .map(
        (d) => `<div class="day ${d.confirmed === d.n ? "day-conf" : ""}">
          <div class="day-name">${esc(d.label)}</div>
          <div class="day-avg">${fmt(d.avg)}</div>
          <div class="day-range">${fmt(d.min, 2)} – ${fmt(d.max, 2)}</div>
          <div class="day-cheap">najtaniej ${esc(d.cheapest)}</div>
          <div class="day-meta">${d.confirmed === d.n ? "✔ potwierdzone" : d.confirmed ? `${d.confirmed}/${d.n} h potw.` : "prognoza"}${
          d.conf !== null ? ` · pewność ${Math.round(d.conf * 100)}%` : ""
        }</div></div>`
      )
      .join("");
    const conf = num(this._val("forecast_confidence"));
    return `<div class="card">
      <div class="card-head"><h2>Prognoza 7 dni</h2><span class="muted">średnia ${fmt(this._val("average_7d"))} zł/kWh${
      conf !== null ? ` · pewność ${Math.round(conf)}%` : ""
    }</span></div>
      <svg viewBox="0 0 ${W} ${H}" class="chart wide">${svg}</svg>
      <div class="days">${cards}</div>
    </div>`;
  }

  _dailySummary(s) {
    const byDay = new Map();
    s.start.forEach((iso, i) => {
      const v = num(s.value[i]);
      if (v === null) return;
      const d = new Date(iso);
      const key = this._localDate(d);
      const isToday = key === this._localDate(new Date(Date.now()));
      if (!byDay.has(key))
        byDay.set(key, { label: isToday ? "Dziś (od teraz)" : this._weekday(d), vals: [], hours: [], confirmed: 0, confs: [] });
      const e = byDay.get(key);
      e.vals.push(v);
      e.hours.push(iso);
      if (s.source[i] === "ACTUAL_PSTRYK") e.confirmed += 1;
      if (num(s.confidence?.[i]) !== null) e.confs.push(num(s.confidence[i]));
    });
    return [...byDay.values()].map((e) => {
      const minIdx = e.vals.indexOf(Math.min(...e.vals));
      return {
        label: e.label,
        n: e.vals.length,
        avg: e.vals.reduce((a, b) => a + b, 0) / e.vals.length,
        min: Math.min(...e.vals),
        max: Math.max(...e.vals),
        cheapest: this._time(e.hours[minIdx]),
        confirmed: e.confirmed,
        conf: e.confs.length ? e.confs.reduce((a, b) => a + b, 0) / e.confs.length : null,
      };
    });
  }

  // "16–19, 22–01" for a list of hourly slot starts
  _ranges(hours) {
    const t = [...(hours || [])].map((h) => Date.parse(h)).sort((a, b) => a - b);
    const out = [];
    for (let i = 0; i < t.length; i++) {
      let j = i;
      while (j + 1 < t.length && t[j + 1] - t[j] === HOUR) j++;
      const h = (ms) => String(this._hourLocal(new Date(ms))).padStart(2, "0");
      out.push(`${h(t[i])}–${h(t[j] + HOUR)}`);
      i = j;
    }
    return out.join(", ");
  }

  // ------------------------------------------------------------ windows
  _windowsCard() {
    const row = (title, key) => {
      const st = this._st(key);
      const a = st?.attributes || {};
      if (!st || !a.start) return `<tr><td>${esc(title)}</td><td colspan="3" class="muted">brak</td></tr>`;
      const share = num(a.confirmed_share);
      const contiguous = (a.hours || []).length <= 1 || Date.parse(a.end) - Date.parse(a.start) === (a.hours || []).length * HOUR;
      const when = contiguous
        ? `<b>${esc(this._dayTime(a.start))}</b>–${esc(this._time(a.end))}`
        : `<b>${esc(this._ranges(a.hours))}</b><div class="muted small">${(a.hours || []).length} h, nieciągłe</div>`;
      return `<tr data-more="${esc(st.entity_id)}"><td>${esc(title)}</td><td>${when}</td>
        <td class="r">${fmt(a.average_price)}</td><td class="r"><span class="badge ${share === 1 ? "src-actual" : share ? "src-market" : "src-forecast"}">${
        share === 1 ? "pewne" : share ? `${Math.round(share * 100)}% pewne` : "prognoza"
      }</span></td></tr>`;
    };
    const prob = num(this._val("cheap_probability"));
    return `<div class="card">
      <div class="card-head"><h2>Najtańsze okna (24 h)</h2>${prob !== null ? `<span class="muted">szansa na tanią energię ${Math.round(prob)}%</span>` : ""}</div>
      <table><thead><tr><th></th><th>Kiedy</th><th class="r">Śr. zł/kWh</th><th class="r">Pewność</th></tr></thead><tbody>
      ${row("Najtańsze 3 h", "cheapest_3h")}${row("Najtańsze 6 h", "cheapest_6h")}${row("Najtańsze N godzin", "cheapest_n_hours")}${row(
      "Najdroższa godzina",
      "most_expensive_hour"
    )}
      </tbody></table></div>`;
  }

  // ------------------------------------------------------------ devices
  _devicesCard() {
    const list = this._schedules();
    if (!list.length)
      return `<div class="card"><div class="card-head"><h2>Urządzenia</h2></div><p class="muted">Brak profili urządzeń. Dodaj je w opcjach integracji (Optymalizacja → Profile urządzeń).</p></div>`;
    const rows = list
      .map((st) => {
        const a = st.attributes || {};
        const ok = a.feasible !== false;
        const cur = num(a.current_value), target = num(a.target);
        const reading = target !== null
          ? `<div class="small ${cur !== null && cur >= target ? "lvl-cheap" : ""}">${cur !== null ? fmt(cur, 1) : "–"} / cel ${fmt(target, 1)}</div>`
          : "";
        return `<tr data-more="${esc(st.entity_id)}"><td><b>${esc(a.profile || st.entity_id)}</b>${reading}<div class="muted small">${esc(a.reason || "")}</div></td>
          <td>${a.next_start ? `${esc(this._dayTime(a.next_start))}–${esc(this._time(a.next_stop))}` : "–"}<div class="muted small">${(a.hours || []).length} h</div></td>
          <td class="r">${a.expected_cost != null ? `${fmt(a.expected_cost, 2)} zł` : "–"}</td>
          <td class="r"><span class="chip ${ok ? "chip-ok" : "chip-err"}">${ok ? "OK" : "niewykonalne"}</span></td></tr>`;
      })
      .join("");
    return `<div class="card"><div class="card-head"><h2>Urządzenia</h2></div>
      <table><thead><tr><th>Profil</th><th>Start</th><th class="r">Koszt</th><th class="r"></th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  // ------------------------------------------------------------ spends
  _spendsCard() {
    const days = this._attr("avg_daily_cost", "days");
    if (!days) return "";
    const months = this._attr("cost_12_months", "months") || [];
    const proj = this._st("projected_month_cost");
    const tm = proj?.attributes?.this_month || {};
    const breakdown = proj?.attributes?.breakdown_month || {};
    const cell = (label, value, sub = "") => `<div><span>${label}</span><b>${value}</b><small>${sub}</small></div>`;
    const bLabels = { energy_cost_net: "energia (netto)", var_dist_cost_net: "dystrybucja zmienna", fix_dist_cost_net: "dystrybucja stała",
      service_cost_net: "opłata handlowa", power_fee_cost_net: "opłata mocowa", excise: "akcyza", vat: "VAT" };
    const bRows = Object.entries(breakdown).filter(([, v]) => num(v)).map(([k, v]) => `<tr><td>${esc(bLabels[k] || k)}</td><td class="r">${fmt(v, 2)} zł</td></tr>`).join("");
    return `<div class="card">
      <div class="card-head"><h2>Wydatki na energię (Pstryk)</h2><span class="muted">dane rozliczeniowe Pstryk</span></div>
      <div class="kv">
        ${cell("Dziś", `${fmt(this._val("cost_today"), 2)} zł`, `${fmt(this._val("energy_import_today"), 1)} kWh`)}
        ${cell("Wczoraj", `${fmt(this._val("cost_yesterday"), 2)} zł`)}
        ${cell("Ten miesiąc", `${fmt(tm.cost, 2)} zł`, `${fmt(tm.import_kwh, 0)} kWh`)}
        ${cell("Prognoza miesiąca", `${fmt(proj?.state, 2)} zł`, `śr. ${fmt(this._val("avg_daily_cost"), 2)} zł/dzień`)}
        ${cell("Poprzedni miesiąc", `${fmt(this._val("cost_previous_month"), 2)} zł`)}
        ${this._st("cost_12_months") ? cell("12 miesięcy", `${fmt(this._val("cost_12_months"), 0)} zł`) : ""}
        ${this._st("hp_cost_today") ? cell("Pompa ciepła dziś",
          num(this._val("hp_cost_today")) === null ? "–" : `${fmt(this._val("hp_cost_today"), 2)} zł`,
          num(this._val("hp_energy_today")) === null ? "zbieranie pomiaru…" : `${fmt(this._val("hp_energy_today"), 1)} kWh (pomiar)`) : ""}
      </div>
      <div class="cols2">
        <div><div class="chart-title">Koszt dzienny (zł)</div>${this._barChart(days.map((d) => ({ label: d.period.slice(8, 10), title: d.period, value: num(d.cost), live: d.live })))}</div>
        <div><div class="chart-title">Koszt miesięczny (zł)</div>${this._barChart(months.map((m) => ({ label: m.period.slice(5, 7), title: m.period, value: num(m.cost) })))}</div>
      </div>
      ${bRows ? `<details><summary class="muted">Składniki kosztu w tym miesiącu</summary><table class="compact">${bRows}</table></details>` : ""}
    </div>`;
  }

  _barChart(items) {
    const data = items.filter((i) => i.value !== null);
    if (!data.length) return `<p class="muted small">Brak danych</p>`;
    const W = 480, H = 130, P = { l: 34, r: 4, t: 8, b: 18 };
    const hi = Math.max(...data.map((d) => d.value), 0.01) * 1.1;
    const bw = (W - P.l - P.r) / data.length;
    const y = (v) => P.t + (1 - v / hi) * (H - P.t - P.b);
    let svg = "";
    const step = niceStep(hi / 3);
    for (let v = 0; v <= hi; v += step)
      svg += `<line class="grid" x1="${P.l}" x2="${W - P.r}" y1="${y(v)}" y2="${y(v)}"/><text class="axis" x="${P.l - 4}" y="${y(v) + 3}" text-anchor="end">${Math.round(v)}</text>`;
    data.forEach((d, i) => {
      const x = P.l + i * bw;
      svg += `<rect class="bar src-actual${d.live ? " live" : ""}" x="${x + 1}" y="${y(Math.max(d.value, 0))}" width="${Math.max(1, bw - 2)}" height="${Math.max(1, y(0) - y(Math.max(d.value, 0)))}"><title>${esc(d.title)}: ${fmt(d.value, 2)} zł</title></rect>`;
      if (data.length <= 14 || i % Math.ceil(data.length / 12) === 0)
        svg += `<text class="axis" x="${x + bw / 2}" y="${H - 4}" text-anchor="middle">${esc(d.label)}</text>`;
    });
    return `<svg viewBox="0 0 ${W} ${H}" class="chart">${svg}</svg>`;
  }

  // ------------------------------------------------------------ meter
  _meterCard() {
    const cell = (label, key, unit, d = 2) => `<div data-more="${esc(this._st(key)?.entity_id || "")}"><span>${label}</span><b>${fmt(this._val(key), d)} ${unit}</b></div>`;
    return `<div class="card"><div class="card-head"><h2>Licznik i rozliczenie</h2></div>
      <div class="cols2"><div><h3>Dziś</h3><div class="kv col">
        ${cell("Pobór", "energy_import_today", "kWh")}${cell("Oddanie", "energy_export_today", "kWh")}
        ${cell("Koszt", "cost_today", "zł")}${cell("Saldo", "balance_today", "zł")}</div></div>
      <div><h3>Ten miesiąc</h3><div class="kv col">
        ${cell("Pobór", "energy_import_month", "kWh", 1)}${cell("Oddanie", "energy_export_month", "kWh", 1)}
        ${cell("Koszt", "cost_month", "zł")}${cell("Saldo", "balance_month", "zł")}</div></div></div></div>`;
  }

  // ------------------------------------------------------------ quality
  _qualityCard() {
    const acc = this._st("forecast_accuracy");
    const a = acc?.attributes || {};
    const bt = a.backtest_mae || {};
    const model = bt.ensemble ? "ensemble" : "baseline";
    const days = [1, 2, 3, 4, 5, 6, 7];
    const live = a.live_mae || {};
    const row = (label, src) =>
      `<tr><td>${label}</td>${days.map((d) => `<td class="r">${src && src[d] != null ? Math.round(src[d]) : "–"}</td>`).join("")}</tr>`;
    return `<div class="card"><div class="card-head"><h2>Jakość prognozy</h2>
      <span class="muted">źródło: ${esc(a.market_reference || "–")}${a.trained_at ? ` · model z ${esc(this._dayTime(a.trained_at))}` : ""}</span></div>
      <p class="muted small">Średni błąd (MAE) ceny rynkowej w zł/MWh dla dnia 1–7. Mniej = lepiej. „Na żywo” liczony z porównania zapisanych prognoz z późniejszymi cenami.</p>
      <table class="compact"><thead><tr><th>Dzień</th>${days.map((d) => `<th class="r">${d}</th>`).join("")}</tr></thead><tbody>
      ${row("Model (test)", bt[model])}${row("Bazowy (test)", bt.baseline)}${row("Na żywo", live)}
      </tbody></table></div>`;
  }

  _legend() {
    return `<div class="legend">
      <span><i class="sw src-actual"></i>potwierdzona cena Pstryk</span>
      <span><i class="sw src-market"></i>opublikowana cena giełdowa (szacunek z taryfą)</span>
      <span><i class="sw src-forecast"></i>prognoza (kreska = zakres P10–P90)</span>
      <span><i class="sw hl-cheap-sw"></i>najtańsze 3 h</span>
      <span><i class="sw lane-heat"></i>pompa ciepła</span>
      <span><i class="sw lane-heater"></i>grzałka</span>
      <span><i class="sw lane-pv"></i>nadwyżka PV</span>
      <span><i class="sw lane-dev"></i>praca urządzenia</span>
    </div>`;
  }
}

function niceStep(raw) {
  if (!(raw > 0)) return 0.1;
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const m = raw / p;
  return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p;
}

const STYLE = `
:host { display:block; background: var(--primary-background-color); color: var(--primary-text-color); min-height:100vh;
  --c-actual: var(--info-color, #1e88e5); --c-market: #8e24aa; --c-forecast: var(--warning-color, #fb8c00);
  --c-cheap: var(--success-color, #43a047); --c-exp: var(--error-color, #e53935); --c-muted: var(--secondary-text-color);
  font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
.toolbar { display:flex; align-items:center; gap:12px; height:56px; padding:0 16px; background: var(--app-header-background-color, var(--primary-color));
  color: var(--app-header-text-color, #fff); position:sticky; top:0; z-index:2; flex-wrap:wrap; }
.toolbar h1 { font-size:20px; font-weight:400; margin:0; }
.toolbar .sub { opacity:.8; font-size:13px; }
.toolbar .spacer { flex:1; }
.toolbar .chip { background: rgba(255,255,255,.18); color: inherit; border:none; }
.content { padding:16px; max-width:1400px; margin:0 auto; display:flex; flex-direction:column; gap:16px; }
.grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap:16px; }
.card { background: var(--card-background-color, #fff); border-radius: var(--ha-card-border-radius, 12px); padding:16px;
  box-shadow: var(--ha-card-box-shadow, none); border: 1px solid var(--divider-color, rgba(0,0,0,.12)); min-width:0; }
.card-head { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-bottom:8px; flex-wrap:wrap; }
h2 { font-size:18px; font-weight:500; margin:0; }
h3 { font-size:14px; margin:4px 0 8px; color: var(--secondary-text-color); font-weight:500; }
.muted { color: var(--secondary-text-color); font-size:13px; }
.small { font-size:12px; }
.price-row { display:flex; align-items:baseline; gap:16px; cursor:pointer; margin:4px 0 12px; }
.big { font-size:48px; font-weight:300; line-height:1; }
.big .unit { font-size:18px; color: var(--secondary-text-color); }
.lvl { font-size:14px; font-weight:600; padding:4px 10px; border-radius:12px; }
.lvl-cheap { color: var(--c-cheap); } .lvl-exp { color: var(--c-exp); }
.lvl.lvl-cheap { background: color-mix(in srgb, var(--c-cheap) 15%, transparent); }
.lvl.lvl-exp { background: color-mix(in srgb, var(--c-exp) 15%, transparent); }
.lvl.lvl-mid { background: color-mix(in srgb, var(--c-muted) 15%, transparent); }
.kv { display:grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap:10px; margin:8px 0; }
.kv.col { grid-template-columns: 1fr 1fr; }
.kv > div { display:flex; flex-direction:column; gap:2px; cursor:default; }
.kv span { font-size:12px; color: var(--secondary-text-color); }
.kv b { font-size:17px; font-weight:500; }
.kv small { font-size:11px; color: var(--secondary-text-color); }
.chips { display:flex; gap:6px; flex-wrap:wrap; }
.chip { font-size:12px; padding:3px 10px; border-radius:12px; border:1px solid transparent; white-space:nowrap; }
.chip-ok { background: color-mix(in srgb, var(--c-cheap) 16%, transparent); color: var(--c-cheap); }
.chip-warn { background: color-mix(in srgb, var(--c-forecast) 18%, transparent); color: var(--c-forecast); }
.chip-err { background: color-mix(in srgb, var(--c-exp) 16%, transparent); color: var(--c-exp); }
.chip-info { background: color-mix(in srgb, var(--c-actual) 16%, transparent); color: var(--c-actual); }
.chip-muted { background: color-mix(in srgb, var(--c-muted) 14%, transparent); color: var(--secondary-text-color); }
.badge { font-size:11px; padding:2px 8px; border-radius:10px; color:#fff; white-space:nowrap; }
.badge.src-actual { background: var(--c-actual); } .badge.src-market { background: var(--c-market); }
.badge.src-forecast { background: var(--c-forecast); } .badge.src-none { background: var(--c-muted); }
.decision { display:flex; align-items:center; gap:14px; padding:12px; border-radius:10px; margin:6px 0 10px; cursor:pointer; }
.decision.heat { background: color-mix(in srgb, var(--c-exp) 14%, transparent); }
.decision.idle { background: color-mix(in srgb, var(--c-muted) 12%, transparent); }
.decision .icon { font-size:34px; }
.dec-title { font-size:22px; font-weight:500; }
.dec-sub { font-size:13px; color: var(--secondary-text-color); }
.chart { width:100%; height:auto; display:block; }
.chart-title { font-size:12px; color: var(--secondary-text-color); margin-top:8px; }
.grid line, line.grid { stroke: var(--divider-color, #ddd); stroke-width:1; }
.axis { font-size:10px; fill: var(--secondary-text-color); }
.daylbl { font-size:11px; fill: var(--primary-text-color); font-weight:500; }
.zero { stroke: var(--secondary-text-color); stroke-width:1; }
.midnight { stroke: var(--secondary-text-color); stroke-dasharray:3 3; opacity:.6; }
.bar.src-actual { fill: var(--c-actual); } .bar.src-market { fill: var(--c-market); }
.bar.src-forecast { fill: color-mix(in srgb, var(--c-forecast) 45%, transparent); stroke: var(--c-forecast); stroke-width:1; }
.bar.src-none { fill: var(--c-muted); opacity:.4; }
.bar.past { opacity:.45; }
.whisker { stroke: var(--c-forecast); stroke-width:1.2; }
.hl-cheap { fill: color-mix(in srgb, var(--c-cheap) 18%, transparent); }
.hl-exp { fill: color-mix(in srgb, var(--c-exp) 12%, transparent); }
.now { stroke: var(--c-exp); stroke-width:2; }
.nowlbl { font-size:10px; fill: var(--c-exp); }
.lane-bg { fill: color-mix(in srgb, var(--c-muted) 10%, transparent); }
.lane-lbl { font-size:11px; fill: var(--secondary-text-color); }
.lane-on.lane-heat { fill: var(--c-exp); } .lane-on.lane-dev { fill: var(--c-cheap); }
.lane-on.lane-heater { fill: #8e24aa; } .lane-on.lane-pv { fill: #fbc02d; }
.heaterbar { fill: color-mix(in srgb, #8e24aa 30%, transparent); }
.bar.live { opacity: .55; }
.storage-row { display:flex; gap:14px; align-items:stretch; }
.storage-main { flex:1; min-width:0; }
.layers { display:flex; flex-direction:column; align-items:center; gap:6px; }
.tank { width:46px; flex:1; min-height:120px; border-radius:12px; position:relative; border:2px solid var(--divider-color); }
.t-top, .t-bot { position:absolute; left:50%; transform:translateX(-50%); font-size:11px; color:#fff; font-weight:600; text-shadow:0 1px 2px rgba(0,0,0,.6); }
.t-top { top:6px; } .t-bot { bottom:6px; }
.soc { font-size:13px; font-weight:600; }
details { margin-top:8px; } summary { cursor:pointer; }
.band { fill: color-mix(in srgb, var(--c-forecast) 20%, transparent); stroke:none; }
.seg { stroke-width:2.2; fill:none; }
.seg.src-actual { stroke: var(--c-actual); } .seg.src-market { stroke: var(--c-market); }
.seg.src-forecast { stroke: var(--c-forecast); stroke-dasharray:5 3; } .seg.src-none { stroke: var(--c-muted); }
.heatbar { fill: color-mix(in srgb, var(--c-exp) 22%, transparent); }
.templine { fill:none; stroke: var(--primary-color); stroke-width:2; }
.lim { stroke: var(--c-exp); stroke-dasharray:4 3; opacity:.7; }
.days { display:grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap:8px; margin-top:10px; }
.day { border:1px solid var(--divider-color); border-radius:10px; padding:8px 10px; }
.day-conf { border-color: var(--c-actual); }
.day-name { font-size:13px; font-weight:500; }
.day-avg { font-size:20px; font-weight:400; }
.day-range, .day-cheap, .day-meta { font-size:11px; color: var(--secondary-text-color); }
table { width:100%; border-collapse:collapse; font-size:14px; }
th { text-align:left; font-weight:500; font-size:12px; color: var(--secondary-text-color); padding:4px 6px; border-bottom:1px solid var(--divider-color); }
td { padding:6px; border-bottom:1px solid var(--divider-color); vertical-align:top; }
tr[data-more] { cursor:pointer; }
tr[data-more]:hover td { background: color-mix(in srgb, var(--primary-color) 6%, transparent); }
.r { text-align:right; }
table.compact td, table.compact th { padding:3px 4px; font-size:12px; }
.cols2 { display:grid; grid-template-columns: 1fr 1fr; gap:16px; }
.legend { display:flex; flex-wrap:wrap; gap:14px; font-size:12px; color: var(--secondary-text-color); padding:0 4px 24px; }
.sw { display:inline-block; width:12px; height:12px; border-radius:3px; margin-right:6px; vertical-align:-2px; }
.sw.src-actual { background: var(--c-actual); } .sw.src-market { background: var(--c-market); }
.sw.src-forecast { background: color-mix(in srgb, var(--c-forecast) 45%, transparent); border:1px solid var(--c-forecast); }
.sw.hl-cheap-sw { background: color-mix(in srgb, var(--c-cheap) 30%, transparent); }
.sw.lane-heat { background: var(--c-exp); } .sw.lane-dev { background: var(--c-cheap); }
.sw.lane-heater { background: #8e24aa; } .sw.lane-pv { background: #fbc02d; }
.empty { max-width:640px; margin:40px auto; }
@media (max-width: 600px) {
  .content { padding:8px; gap:8px; } .grid { grid-template-columns: 1fr; } .big { font-size:40px; }
  .cols2 { grid-template-columns: 1fr; } .toolbar .chips { display:none; }
}
`;

customElements.define("pstryk-ai-panel", PstrykAIPanel);
