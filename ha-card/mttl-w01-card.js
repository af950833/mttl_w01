class MTTLW01Card extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._signature = "";
  }

  static getStubConfig() {
    return { mac: "0000000" };
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
        return `${id}:${entity?.state || "missing"}:${entity?.attributes?.friendly_name || ""}`;
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
      const name = entity?.attributes?.friendly_name || `SW ${index + 1}`;
      return `<button class="channel ${active ? "active" : ""} ${usable ? "" : "unavailable"}" data-entity="${ids.switches[index]}" ${usable ? "" : "disabled"}>
        <span class="channel-name">${this._escape(name)}</span>
        <strong>${this._escape(this._format(powers[index], "— W"))}</strong>
        <span class="state">${usable ? (active ? "ON" : "OFF") : "UNAVAILABLE"}</span>
      </button>`;
    }).join("");

    this.shadowRoot.innerHTML = `<style>
      :host{display:block}ha-card{padding:16px;color:var(--primary-text-color);overflow:hidden}
      .header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}
      .title{font-size:18px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .availability{display:flex;align-items:center;gap:6px;color:var(--secondary-text-color);font-size:12px;white-space:nowrap}
      .dot{width:9px;height:9px;border-radius:50%;background:var(--error-color,#db4437)}.dot.online{background:var(--success-color,#22c55e)}
      .summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-bottom:10px}
      .summary-item{box-sizing:border-box;min-width:0;height:38px;padding:0 11px;border:1px solid var(--divider-color);border-radius:10px;background:var(--secondary-background-color);display:flex;align-items:center;justify-content:space-between;gap:8px;color:var(--primary-text-color)}
      .summary-item span{color:var(--secondary-text-color);font-size:12px}.summary-item strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px}
      button{font:inherit}.all{cursor:pointer}.all.active{border-color:var(--primary-color);color:var(--primary-color)}.all:disabled{cursor:not-allowed;opacity:.45}
      .channels{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
      .channel{box-sizing:border-box;min-width:0;min-height:88px;padding:10px 7px;border:1px solid var(--divider-color);border-radius:12px;background:var(--card-background-color);color:var(--primary-text-color);cursor:pointer;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;transition:background .15s,border-color .15s,transform .08s}
      .channel:hover{background:var(--secondary-background-color)}.channel:active{transform:scale(.98)}
      .channel.active{border-color:var(--primary-color);background:color-mix(in srgb,var(--primary-color) 12%,var(--card-background-color))}
      .channel-name{width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;font-weight:600}
      .channel strong{font-size:15px}.channel .state{font-size:10px;color:var(--secondary-text-color)}.channel.active .state{color:var(--primary-color);font-weight:700}
      .channel.unavailable{opacity:.45;cursor:not-allowed}
      @media(max-width:600px){.channels:not(.compact){grid-template-columns:repeat(2,minmax(0,1fr))}.summary-item{padding:0 8px}.summary-item span{font-size:11px}.summary-item strong{font-size:12px}}
    </style>
    <ha-card>
      <div class="header"><div class="title">${this._escape(title)}</div><div class="availability"><span class="dot ${available ? "online" : ""}"></span>${available ? "Online" : "Offline"}</div></div>
      <div class="summary">
        <div class="summary-item"><span>Total</span><strong>${this._escape(this._format(this._entity(ids.powerAll), "— W"))}</strong></div>
        <div class="summary-item"><span>Today</span><strong>${this._escape(this._format(this._entity(ids.today), "— kWh"))}</strong></div>
        <button class="summary-item all ${onCount ? "active" : ""}" data-all ${available ? "" : "disabled"}><span>ALL</span><strong>${allState}</strong></button>
      </div>
      <div class="channels ${this._config.compact ? "compact" : ""}">${channels}</div>
    </ha-card>`;

    this.shadowRoot.querySelectorAll(".channel").forEach(button => {
      button.addEventListener("click", () => this._call("toggle", button.dataset.entity));
    });
    this.shadowRoot.querySelector("[data-all]")?.addEventListener("click", () => {
      this._call(onCount ? "turn_off" : "turn_on", ids.all);
    });
  }

  _call(service, entityId) {
    if (this._hass && entityId) this._hass.callService("switch", service, { entity_id: entityId });
  }
}

if (!customElements.get("mttl-w01-card")) customElements.define("mttl-w01-card", MTTLW01Card);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "mttl-w01-card",
  name: "MTTL-W01 Card",
  description: "Four-channel control and live power display for MTTL-W01",
  preview: true,
});
