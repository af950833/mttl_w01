class MTTLW011068Card extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._signature = "";
  }

  static getStubConfig() { return { mac: "0000000" }; }
  static getConfigElement() { return document.createElement("mttl-w01-1-0-68-card-editor"); }

  setConfig(config) {
    const mac = String(config.mac || "").replace(/[^0-9a-f]/gi, "").toLowerCase();
    if (!/^[0-9a-f]{7}$/.test(mac)) throw new Error("mac must contain the last 7 hexadecimal characters of the device MAC");
    this._config = {
      mac,
      name: String(config.name || "").trim(),
      mobile_two_rows: Boolean(config.mobile_two_rows),
      channel_names: Array.isArray(config.channel_names) ? config.channel_names.slice(0, 4) : [],
      channel_icons: Array.isArray(config.channel_icons) ? config.channel_icons.slice(0, 4) : [],
    };
    this._signature = "";
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    const signature = Object.values(this._ids()).flat().map(id => {
      const state = hass.states[id];
      const registry = hass.entities?.[id];
      return `${id}:${state?.state || "missing"}:${state?.attributes?.friendly_name || ""}:${registry?.name || ""}:${registry?.original_name || ""}`;
    }).join("|");
    if (signature !== this._signature) {
      this._signature = signature;
      this._render();
    }
  }

  getCardSize() { return 6; }

  _ids() {
    const base = `mttl_${this._config.mac}`;
    const sensor = suffix => `sensor.${base}_${suffix}`;
    return {
      all: `switch.${base}_all`,
      switches: [1, 2, 3, 4].map(n => `switch.${base}_sw${n}`),
      powerAll: sensor("powerall"), meter: sensor("meter"),
      voltage: sensor("voltage"), current: sensor("current"),
      powers: [1, 2, 3, 4].map(n => sensor(`power${n}`)),
      meters: [1, 2, 3, 4].map(n => sensor(`meter${n}`)),
      currents: [1, 2, 3, 4].map(n => sensor(`current${n}`)),
      temperatures: [1, 2, 3, 4].map(n => sensor(`temperature${n}`)),
    };
  }

  _entity(id) { return this._hass?.states?.[id]; }
  _available(entity) { return Boolean(entity && !["unknown", "unavailable"].includes(entity.state)); }
  _format(id, fallback = "—") {
    const entity = this._entity(id);
    if (!this._available(entity)) return fallback;
    const unit = entity.attributes.unit_of_measurement || "";
    return `${entity.state}${unit ? ` ${unit}` : ""}`;
  }
  _escape(value) {
    return String(value ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" })[c]);
  }
  _channelName(id, entity, all, number) {
    const configured = String(this._config.channel_names?.[number - 1] || "").trim();
    if (configured) return configured;
    const registry = this._hass?.entities?.[id];
    let name = registry?.name || registry?.original_name || entity?.attributes?.friendly_name || `SW ${number}`;
    const allName = all?.attributes?.friendly_name || "";
    const prefix = allName.match(/^(.*?)(?:SW\s*All|All)$/i)?.[1]?.trim();
    if (prefix && name.toLowerCase().startsWith(prefix.toLowerCase())) name = name.slice(prefix.length).replace(/^\s*[-–—:]?\s*/, "");
    return name || `SW ${number}`;
  }

  _render() {
    if (!this._config || !this.shadowRoot) return;
    const ids = this._ids();
    const switches = ids.switches.map(id => this._entity(id));
    const all = this._entity(ids.all);
    const available = this._available(all) || switches.some(entity => this._available(entity));
    const onCount = switches.filter(entity => entity?.state === "on").length;
    const allState = onCount === 4 ? "ON" : onCount ? "PARTIAL" : "OFF";
    const title = this._config.name || `MTTL ${this._config.mac.toUpperCase()}`;
    const summary = [
      ["Total Power", ids.powerAll], ["Meter", ids.meter], ["Voltage", ids.voltage], ["Total Current", ids.current],
    ].map(([label, id]) => `<button class="summary-item" data-more-info="${id}"><span>${label}</span><strong>${this._escape(this._format(id))}</strong></button>`).join("");
    const channels = switches.map((entity, i) => {
      const active = entity?.state === "on";
      const usable = this._available(entity);
      const name = this._channelName(ids.switches[i], entity, all, i + 1);
      const icon = String(this._config.channel_icons?.[i] || "").trim() || "mdi:power-socket-eu";
      const readings = [["Power", ids.powers[i]], ["Meter", ids.meters[i]], ["Current", ids.currents[i]], ["Temp", ids.temperatures[i]]]
        .map(([label, id]) => `<button class="reading" data-more-info="${id}"><span>${label}</span><strong>${this._escape(this._format(id))}</strong></button>`).join("");
      return `<section class="channel ${active ? "active" : ""} ${usable ? "" : "unavailable"}">
        <button class="channel-toggle" data-entity="${ids.switches[i]}" ${usable ? "" : "disabled"}>
          <ha-icon icon="${this._escape(icon)}"></ha-icon><span>${this._escape(name)}</span><b>${active ? "ON" : "OFF"}</b>
        </button><div class="readings">${readings}</div>
      </section>`;
    }).join("");

    this.shadowRoot.innerHTML = `<style>
      :host{display:block}ha-card{padding:16px;color:var(--primary-text-color);overflow:hidden}
      button{font:inherit}.header{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px}.title{font-size:18px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.availability{display:flex;align-items:center;gap:6px;color:var(--secondary-text-color);font-size:12px}.dot{width:9px;height:9px;border-radius:50%;background:var(--error-color,#db4437)}.dot.online{background:var(--success-color,#22c55e)}
      .summary{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin-bottom:12px}.summary-item,.all{min-width:0;min-height:46px;padding:4px 7px;border:1px solid color-mix(in srgb,var(--success-color,#22c55e) 30%,var(--divider-color));border-radius:9px;background:color-mix(in srgb,var(--success-color,#22c55e) 10%,var(--card-background-color));color:var(--primary-text-color);cursor:pointer;display:flex;flex-direction:column;align-items:center;justify-content:center}.summary span,.all span{color:var(--secondary-text-color);font-size:11px}.summary strong,.all strong{font-size:12px;white-space:nowrap}.all.partial{border-color:var(--primary-color);color:var(--primary-color)}.all.on{background:color-mix(in srgb,var(--success-color,#22c55e) 22%,var(--card-background-color));color:var(--success-color,#15803d)}
      .channels{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.channel{min-width:0;padding:10px;border:1px solid var(--divider-color);border-radius:12px;background:var(--card-background-color)}.channel.active{border-color:var(--primary-color);background:color-mix(in srgb,var(--primary-color) 8%,var(--card-background-color))}.channel.unavailable{opacity:.55}
      .channel-toggle{width:100%;display:grid;grid-template-columns:24px minmax(0,1fr) auto;align-items:center;gap:8px;padding:5px;border:0;background:transparent;color:var(--primary-text-color);cursor:pointer;text-align:left}.channel-toggle ha-icon{width:21px;height:21px;color:var(--secondary-text-color)}.channel.active .channel-toggle ha-icon,.channel.active .channel-toggle b{color:var(--primary-color)}.channel-toggle span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600}.channel-toggle b{font-size:11px;color:var(--secondary-text-color)}
      .readings{display:flex;flex-direction:column;margin-top:5px;border-top:1px solid var(--divider-color);padding-top:5px}.reading{display:flex;justify-content:space-between;gap:8px;width:100%;padding:4px 5px;border:0;background:transparent;color:var(--secondary-text-color);cursor:pointer;font-size:12px}.reading strong{color:var(--primary-text-color);white-space:nowrap}.reading:hover{background:var(--secondary-background-color);border-radius:6px}
      @media(max-width:600px){.summary{grid-template-columns:repeat(6,minmax(0,1fr))}.summary-item{grid-column:span 2}.summary-item:nth-child(4),.summary .all{grid-column:span 3}.channels:not(.mobile-two-rows){grid-template-columns:1fr}}
    </style><ha-card>
      <div class="header"><div class="title">${this._escape(title)}</div><div class="availability"><span class="dot ${available ? "online" : ""}"></span>${available ? "Online" : "Offline"}</div></div>
      <div class="summary">${summary}<button class="all ${onCount === 4 ? "on" : onCount ? "partial" : ""}" data-all ${available ? "" : "disabled"}><span>ALL</span><strong>${allState}</strong></button></div>
      <div class="channels ${this._config.mobile_two_rows ? "mobile-two-rows" : ""}">${channels}</div>
    </ha-card>`;
    this.shadowRoot.querySelectorAll("[data-more-info]").forEach(button => button.addEventListener("click", () => this._moreInfo(button.dataset.moreInfo)));
    this.shadowRoot.querySelectorAll(".channel-toggle").forEach(button => button.addEventListener("click", () => this._call("toggle", button.dataset.entity)));
    this.shadowRoot.querySelector("[data-all]")?.addEventListener("click", () => this._call(onCount ? "turn_off" : "turn_on", ids.all));
  }

  _call(service, entityId) { if (this._hass && entityId) this._hass.callService("switch", service, { entity_id: entityId }); }
  _moreInfo(entityId) { if (entityId) this.dispatchEvent(new CustomEvent("hass-more-info", { detail:{ entityId }, bubbles:true, composed:true })); }
}

class MTTLW011068CardEditor extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode:"open" }); }
  set hass(hass) {
    const firstUpdate = !this._hass;
    this._hass = hass;
    if (firstUpdate && this._config) this._render();
  }
  setConfig(config) {
    this._config = { mac:"", name:"", mobile_two_rows:false, channel_names:[], channel_icons:[], ...config,
      channel_names:Array.isArray(config.channel_names) ? config.channel_names.slice(0,4) : [],
      channel_icons:Array.isArray(config.channel_icons) ? config.channel_icons.slice(0,4) : [] };
    this._render();
  }
  _escape(value) { return String(value ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" })[c]); }
  _render() {
    if (!this._config) return;
    this.shadowRoot.innerHTML = `<style>.editor{display:grid;gap:16px;padding:8px 0}.field{display:grid;gap:6px}.label{font-size:13px;font-weight:500}input{box-sizing:border-box;width:100%;height:44px;padding:0 12px;border:1px solid var(--divider-color);border-radius:6px;background:var(--card-background-color);color:var(--primary-text-color);font:inherit}.option{display:flex;align-items:center;justify-content:space-between;gap:16px}.channels{display:grid;gap:10px}.channel{display:grid;grid-template-columns:28px minmax(0,1fr) minmax(0,1fr);align-items:end;gap:8px;padding-top:10px;border-top:1px solid var(--divider-color)}.number{align-self:center;text-align:center;font-weight:600}.hint,.error{font-size:12px}.hint{color:var(--secondary-text-color)}.error{color:var(--error-color);min-height:16px}</style>
      <div class="editor"><label class="field"><span class="label">MAC suffix (7 hexadecimal characters)</span><input id="mac" maxlength="7" value="${this._escape(this._config.mac)}" placeholder="97C0123"><span class="hint">Example: 97C0123</span><span id="error" class="error"></span></label>
      <label class="field"><span class="label">Card name (optional)</span><input id="name" value="${this._escape(this._config.name)}" placeholder="Living Room Power Strip"></label>
      <label class="option"><span>Keep 2×2 channel layout on mobile</span><ha-switch id="mobileTwoRows" ${this._config.mobile_two_rows ? "checked" : ""}></ha-switch></label>
      <div class="channels">${[0,1,2,3].map(i => `<div class="channel"><span class="number">${i+1}</span><label class="field"><span class="label">Channel name</span><input data-name="${i}" value="${this._escape(this._config.channel_names[i] || "")}" placeholder="Use HA entity name"></label><div class="field"><span class="label">Icon</span><div data-icon="${i}"></div></div></div>`).join("")}</div></div>`;
    const mac = this.shadowRoot.querySelector("#mac");
    mac.addEventListener("input", e => { const value=String(e.target.value).replace(/[^0-9a-f]/gi,"").slice(0,7).toUpperCase(); e.target.value=value; this._update("mac",value); this._validate(); });
    this.shadowRoot.querySelector("#name").addEventListener("change", e => this._update("name",e.target.value));
    this.shadowRoot.querySelector("#mobileTwoRows").addEventListener("change", e => this._update("mobile_two_rows",e.target.checked));
    this.shadowRoot.querySelectorAll("[data-name]").forEach(input => input.addEventListener("change", e => this._arrayUpdate("channel_names",Number(input.dataset.name),e.target.value)));
    this.shadowRoot.querySelectorAll("[data-icon]").forEach(container => { const i=Number(container.dataset.icon); const selector=document.createElement("ha-selector"); selector.hass=this._hass; selector.selector={icon:{placeholder:"mdi:power-socket-eu"}}; selector.value=this._config.channel_icons[i] || ""; selector.addEventListener("value-changed",e=>this._arrayUpdate("channel_icons",i,e.detail?.value || "")); container.appendChild(selector); });
    this._validate();
  }
  _valid() { return /^[0-9a-f]{7}$/i.test(String(this._config.mac || "")); }
  _validate() { const error=this.shadowRoot.querySelector("#error"); if(error) error.textContent=this._config.mac && !this._valid() ? "Enter exactly 7 hexadecimal characters." : ""; }
  _emit() { if (this._valid()) this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:{...this._config}},bubbles:true,composed:true})); }
  _update(key,value) { this._config={...this._config,[key]:value}; this._emit(); }
  _arrayUpdate(key,index,value) { const values=[...(this._config[key] || [])]; while(values.length<4) values.push(""); values[index]=String(value || "").trim(); this._config={...this._config,[key]:values}; this._emit(); }
}

if (!customElements.get("mttl-w01-1-0-68-card-editor")) customElements.define("mttl-w01-1-0-68-card-editor", MTTLW011068CardEditor);
if (!customElements.get("mttl-w01-1-0-68-card")) customElements.define("mttl-w01-1-0-68-card", MTTLW011068Card);
window.customCards = window.customCards || [];
window.customCards.push({ type:"mttl-w01-1-0-68-card", name:"MTTL-W01 1.0.68 Card", description:"MTTL-W01 control with extended voltage, current, energy and temperature sensors", preview:true });
