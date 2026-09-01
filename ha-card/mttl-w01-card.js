class MTTLW01Card extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._signature = "";
  }

  static getStubConfig() {
    return { mac: "0000000" };
  }

  static getConfigElement() {
    return document.createElement("mttl-w01-card-editor");
  }

  setConfig(config) {
    const mac = String(config.mac || "").replace(/[^0-9a-f]/gi, "").toLowerCase();
    if (!/^[0-9a-f]{7}$/.test(mac)) {
      throw new Error("mac must contain the last 7 hexadecimal characters of the device MAC");
    }
    this._config = {
      mac,
      name: String(config.name || "").trim(),
      compact: Boolean(config.compact),
      channel_names: Array.isArray(config.channel_names) ? config.channel_names.slice(0, 4) : [],
      channel_icons: Array.isArray(config.channel_icons) ? config.channel_icons.slice(0, 4) : [],
    };
    this._signature = "";
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    const ids = this._entityIds();
    const signature = Object.values(ids)
      .flat()
      .map(id => {
        const entity = hass.states[id];
        const registry = hass.entities?.[id];
        return `${id}:${entity?.state || "missing"}:${registry?.name || ""}:${registry?.original_name || ""}:${entity?.attributes?.friendly_name || ""}`;
      })
      .join("|");
    if (signature !== this._signature) {
      this._signature = signature;
      this._render();
    }
  }

  getCardSize() {
    return 3;
  }

  _entityIds() {
    const base = `mttl_${this._config.mac}`;
    return {
      all: `switch.${base}_all`,
      switches: [1, 2, 3, 4].map(number => `switch.${base}_sw${number}`),
      powerAll: `sensor.${base}_powerall`,
      powers: [1, 2, 3, 4].map(number => `sensor.${base}_power${number}`),
      today: `sensor.${base}_today_usage`,
    };
  }

  _entity(id) {
    return this._hass?.states?.[id];
  }

  _available(entity) {
    return Boolean(entity && !["unknown", "unavailable"].includes(entity.state));
  }

  _format(entity, fallback = "—") {
    if (!this._available(entity)) return fallback;
    const unit = entity.attributes.unit_of_measurement || "";
    return `${entity.state}${unit ? ` ${unit}` : ""}`;
  }

  _channelName(entityId, entity, allEntity, number) {
    const configured = String(this._config.channel_names?.[number - 1] || "").trim();
    if (configured) return configured;
    const registry = this._hass?.entities?.[entityId];
    const registryName = registry?.name || registry?.original_name;
    if (registryName) return registryName;
    let name = entity?.attributes?.friendly_name || `SW ${number}`;
    const allName = allEntity?.attributes?.friendly_name || "";
    const match = allName.match(/^(.*?)(?:SW\s*All|All)$/i);
    const devicePrefix = match?.[1]?.trim();
    if (devicePrefix && name.toLowerCase().startsWith(devicePrefix.toLowerCase())) {
      name = name.slice(devicePrefix.length).replace(/^\s*[-–—:]?\s*/, "");
    }
    return name || `SW ${number}`;
  }

  _escape(value) {
    return String(value ?? "").replace(/[&<>"']/g, character => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[character]);
  }

  _render() {
    if (!this._config || !this.shadowRoot) return;
    const ids = this._entityIds();
    const switches = ids.switches.map(id => this._entity(id));
    const powers = ids.powers.map(id => this._entity(id));
    const all = this._entity(ids.all);
    const available = switches.some(entity => this._available(entity)) || this._available(all);
    const onCount = switches.filter(entity => entity?.state === "on").length;
    const allState = onCount === 4 ? "ON" : onCount ? "PARTIAL" : "OFF";
    const title = this._config.name || `MTTL ${this._config.mac.toUpperCase()}`;
    const channels = switches.map((entity, index) => {
      const usable = this._available(entity);
      const active = entity?.state === "on";
      const name = this._channelName(ids.switches[index], entity, all, index + 1);
      const icon = String(this._config.channel_icons?.[index] || "").trim() || "mdi:power-socket-eu";
      return `<button class="channel ${active ? "active" : ""} ${usable ? "" : "unavailable"}" data-entity="${ids.switches[index]}" ${usable ? "" : "disabled"}>
        <ha-icon class="channel-icon" icon="${this._escape(icon)}"></ha-icon>
        <span class="channel-name">${this._escape(name)}</span>
        <strong>${this._escape(this._format(powers[index], "— W"))}</strong>
      </button>`;
    }).join("");

    this.shadowRoot.innerHTML = `<style>
      :host{display:block}ha-card{padding:16px;color:var(--primary-text-color);overflow:hidden}
      .header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}
      .title{font-size:18px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .availability{display:flex;align-items:center;gap:6px;color:var(--secondary-text-color);font-size:12px;white-space:nowrap}
      .dot{width:9px;height:9px;border-radius:50%;background:var(--error-color,#db4437)}.dot.online{background:var(--success-color,#22c55e)}
      .summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));width:88%;gap:16px;margin:0 auto 12px}
      .summary-item{box-sizing:border-box;min-width:0;height:30px;padding:0 9px;border:1px solid color-mix(in srgb,var(--success-color,#22c55e) 30%,var(--divider-color));border-radius:9px;background:color-mix(in srgb,var(--success-color,#22c55e) 10%,var(--card-background-color));display:flex;align-items:center;justify-content:space-between;gap:6px;color:var(--primary-text-color)}
      .summary-item span{color:var(--secondary-text-color);font-size:12px}.summary-item strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px}
      button{font:inherit}.info{cursor:pointer}.info:hover{background:color-mix(in srgb,var(--success-color,#22c55e) 16%,var(--card-background-color))}.all{cursor:pointer}.all.partial{border-color:var(--primary-color);color:var(--primary-color)}.all.on{border-color:var(--success-color,#22c55e);background:color-mix(in srgb,var(--success-color,#22c55e) 22%,var(--card-background-color));color:var(--success-color,#15803d)}.all:disabled{cursor:not-allowed;opacity:.45}
      .channels{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
      .channel{box-sizing:border-box;min-width:0;min-height:96px;padding:10px 7px;border:1px solid var(--divider-color);border-radius:12px;background:var(--card-background-color);color:var(--primary-text-color);cursor:pointer;display:flex;flex-direction:column;align-items:center;justify-content:space-between;gap:7px;transition:background .15s,border-color .15s,transform .08s}
      .channel:hover{background:var(--secondary-background-color)}.channel:active{transform:scale(.98)}
      .channel.active{border-color:var(--primary-color);background:color-mix(in srgb,var(--primary-color) 12%,var(--card-background-color))}
      .channel-icon{width:20px;height:20px;color:var(--secondary-text-color);flex:0 0 auto}.channel.active .channel-icon{color:var(--primary-color)}
      .channel-name{width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;font-weight:600;transform:translateY(3px)}
      .channel strong{font-size:13px}
      .channel.unavailable{opacity:.45;cursor:not-allowed}
      @media(max-width:600px){.channels:not(.compact){grid-template-columns:repeat(2,minmax(0,1fr))}.summary-item{padding:0 8px}.summary-item span{font-size:11px}.summary-item strong{font-size:12px}}
    </style>
    <ha-card>
      <div class="header"><div class="title">${this._escape(title)}</div><div class="availability"><span class="dot ${available ? "online" : ""}"></span>${available ? "Online" : "Offline"}</div></div>
      <div class="summary">
        <button class="summary-item info" data-more-info="${ids.powerAll}"><span>Total</span><strong>${this._escape(this._format(this._entity(ids.powerAll), "— W"))}</strong></button>
        <button class="summary-item info" data-more-info="${ids.today}"><span>Today</span><strong>${this._escape(this._format(this._entity(ids.today), "— kWh"))}</strong></button>
        <button class="summary-item all ${onCount === 4 ? "on" : onCount ? "partial" : ""}" data-all ${available ? "" : "disabled"}><span>ALL</span><strong>${allState}</strong></button>
      </div>
      <div class="channels ${this._config.compact ? "compact" : ""}">${channels}</div>
    </ha-card>`;

    this.shadowRoot.querySelectorAll(".channel").forEach(button => {
      button.addEventListener("click", () => this._call("toggle", button.dataset.entity));
    });
    this.shadowRoot.querySelectorAll("[data-more-info]").forEach(button => {
      button.addEventListener("click", () => this._moreInfo(button.dataset.moreInfo));
    });
    this.shadowRoot.querySelector("[data-all]")?.addEventListener("click", () => {
      this._call(onCount ? "turn_off" : "turn_on", ids.all);
    });
  }

  _call(service, entityId) {
    if (this._hass && entityId) this._hass.callService("switch", service, { entity_id: entityId });
  }

  _moreInfo(entityId) {
    if (!entityId) return;
    this.dispatchEvent(new CustomEvent("hass-more-info", {
      detail: { entityId },
      bubbles: true,
      composed: true,
    }));
  }
}

class MTTLW01CardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  set hass(hass) {
    const firstUpdate = !this._hass;
    this._hass = hass;
    if (firstUpdate && this._config) this._render();
  }

  setConfig(config) {
    this._config = {
      mac: "", name: "", compact: false, channel_names: [], channel_icons: [], ...config,
      channel_names: Array.isArray(config.channel_names) ? config.channel_names.slice(0, 4) : [],
      channel_icons: Array.isArray(config.channel_icons) ? config.channel_icons.slice(0, 4) : [],
    };
    this._render();
  }

  _render() {
    if (!this._config) return;
    this.shadowRoot.innerHTML = `<style>
      .editor{display:grid;gap:16px;padding:8px 0}
      .field{display:grid;gap:6px}.field-label{color:var(--primary-text-color);font-size:13px;font-weight:500}
      input{box-sizing:border-box;width:100%;height:44px;padding:0 12px;border:1px solid var(--divider-color);border-radius:6px;background:var(--card-background-color);color:var(--primary-text-color);font:inherit;outline:none}
      input:focus{border-color:var(--primary-color);box-shadow:0 0 0 1px var(--primary-color)}
      input.invalid{border-color:var(--error-color)}
      .option{display:flex;align-items:center;justify-content:space-between;gap:16px}
      .channels-editor{display:grid;gap:10px}.channel-editor{display:grid;grid-template-columns:28px minmax(0,1fr) minmax(0,1fr);align-items:end;gap:8px;padding-top:10px;border-top:1px solid var(--divider-color)}
      .channel-number{align-self:center;text-align:center;font-weight:600}.channel-editor .field-label{font-size:12px}
      .description{color:var(--secondary-text-color);font-size:12px;margin-top:4px}
      .error{color:var(--error-color);font-size:12px;min-height:16px}
    </style>
    <div class="editor">
      <label class="field">
        <span class="field-label">MAC suffix (7 hexadecimal characters)</span>
        <input id="mac" type="text" value="${this._escape(this._config.mac || "")}" maxlength="7" placeholder="97C0123" autocomplete="off" required>
        <div class="description">Example: 97C0123</div>
        <div id="macError" class="error"></div>
      </label>
      <label class="field"><span class="field-label">Card name (optional)</span><input id="name" type="text" value="${this._escape(this._config.name || "")}" placeholder="Living Room Power Strip" autocomplete="off"></label>
      <label class="option"><span>Keep four channels in one row on mobile</span><ha-switch id="compact" ${this._config.compact ? "checked" : ""}></ha-switch></label>
      <div class="channels-editor">
        ${[0,1,2,3].map(index => `<div class="channel-editor">
          <span class="channel-number">${index + 1}</span>
          <label class="field"><span class="field-label">Channel name</span><input data-channel-name="${index}" type="text" value="${this._escape(this._config.channel_names[index] || "")}" placeholder="Use HA entity name" autocomplete="off"></label>
          <div class="field"><span class="field-label">Icon</span><div data-channel-icon="${index}"></div></div>
        </div>`).join("")}
      </div>
    </div>`;

    const mac = this.shadowRoot.querySelector("#mac");
    const name = this.shadowRoot.querySelector("#name");
    const compact = this.shadowRoot.querySelector("#compact");
    mac.addEventListener("input", event => this._change("mac", event.target.value));
    name.addEventListener("change", event => this._change("name", event.target.value));
    compact.addEventListener("change", event => this._change("compact", event.target.checked));
    this.shadowRoot.querySelectorAll("[data-channel-name]").forEach(input => {
      input.addEventListener("change", event => this._changeChannel(Number(input.dataset.channelName), "channel_names", event.target.value));
    });
    this.shadowRoot.querySelectorAll("[data-channel-icon]").forEach(container => {
      const index = Number(container.dataset.channelIcon);
      const selector = document.createElement("ha-selector");
      selector.hass = this._hass;
      selector.selector = { icon: { placeholder: "mdi:power-socket-eu" } };
      selector.value = this._config.channel_icons[index] || "";
      selector.label = `Channel ${index + 1} icon`;
      selector.addEventListener("value-changed", event => this._changeChannel(index, "channel_icons", event.detail?.value || ""));
      container.appendChild(selector);
    });
    this._validateMac();
  }

  _change(key, value) {
    if (key === "mac") value = String(value).replace(/[^0-9a-f]/gi, "").slice(0, 7).toUpperCase();
    this._config = { ...this._config, [key]: value };
    if (key === "mac") {
      const field = this.shadowRoot.querySelector("#mac");
      if (field.value !== value) field.value = value;
      this._validateMac();
    }
    const mac = String(this._config.mac || "").replace(/[^0-9a-f]/gi, "");
    if (!/^[0-9a-f]{7}$/i.test(mac)) return;
    this.dispatchEvent(new CustomEvent("config-changed", {
      detail: { config: { ...this._config } },
      bubbles: true,
      composed: true,
    }));
  }

  _validateMac() {
    const field = this.shadowRoot.querySelector("#mac");
    const value = String(field?.value || this._config.mac || "").replace(/[^0-9a-f]/gi, "");
    const valid = /^[0-9a-f]{7}$/i.test(value);
    const error = this.shadowRoot.querySelector("#macError");
    if (field) field.classList.toggle("invalid", Boolean(value) && !valid);
    if (error) error.textContent = value && !valid ? "Enter exactly 7 hexadecimal characters." : "";
  }

  _changeChannel(index, key, value) {
    const values = [...(this._config[key] || [])];
    while (values.length < 4) values.push("");
    values[index] = String(value || "").trim();
    this._config = { ...this._config, [key]: values };
    const mac = String(this._config.mac || "").replace(/[^0-9a-f]/gi, "");
    if (!/^[0-9a-f]{7}$/i.test(mac)) return;
    this.dispatchEvent(new CustomEvent("config-changed", {
      detail: { config: { ...this._config } },
      bubbles: true,
      composed: true,
    }));
  }

  _escape(value) {
    return String(value ?? "").replace(/[&<>"']/g, character => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[character]);
  }
}

if (!customElements.get("mttl-w01-card-editor")) customElements.define("mttl-w01-card-editor", MTTLW01CardEditor);
if (!customElements.get("mttl-w01-card")) customElements.define("mttl-w01-card", MTTLW01Card);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "mttl-w01-card",
  name: "MTTL-W01 Card",
  description: "Four-channel control and live power display for MTTL-W01",
  preview: true,
});
