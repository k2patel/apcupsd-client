// UPS Configuration page (uses apiFetch for CSRF)

function el(tag, attrs, ...children) {
  const e = document.createElement(tag);
  if (attrs) Object.entries(attrs).forEach(([k, v]) => {
    if (k === 'class') e.className = v;
    else if (k === 'dataset') Object.assign(e.dataset, v);
    else if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) e.setAttribute(k, v);
  });
  children.forEach(c => {
    if (c == null) return;
    e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  });
  return e;
}

class ConfigManager {
  constructor() { this.confirmCallback = null; this.init(); }

  init() { this.bindEvents(); this.loadUPSList(); }

  bindEvents() {
    document.getElementById('add-ups-btn').addEventListener('click', () => this.showUPSModal());
    document.querySelectorAll('.close').forEach(close => {
      close.addEventListener('click', (e) => this.closeModal(e.target.closest('.modal')));
    });
    document.getElementById('ups-form').addEventListener('submit', (e) => {
      e.preventDefault(); this.saveUPS();
    });
    document.getElementById('test-connection-btn').addEventListener('click', () => this.testConnection());
    document.getElementById('cancel-btn').addEventListener('click', () => {
      this.closeModal(document.getElementById('ups-modal'));
    });
    document.getElementById('confirm-yes').addEventListener('click', () => {
      if (this.confirmCallback) this.confirmCallback();
      this.closeModal(document.getElementById('confirm-modal'));
    });
    document.getElementById('confirm-no').addEventListener('click', () => {
      this.closeModal(document.getElementById('confirm-modal'));
    });
    window.addEventListener('click', (e) => {
      if (e.target.classList.contains('modal')) this.closeModal(e.target);
    });
  }

  async loadUPSList() {
    try {
      const resp = await window.apiFetch('/api/config/ups');
      const list = await resp.json();
      if (!resp.ok) throw new Error(list.detail || 'Failed to load');
      this.renderUPSList(list);
    } catch (err) { this.showToast('Error: ' + err.message, 'error'); }
  }

  renderUPSList(list) {
    const container = document.getElementById('ups-list');
    container.textContent = '';
    if (list.length === 0) {
      const empty = el('div', { class: 'empty-state' },
        el('h3', null, 'No UPS Configured'),
        el('p', null, 'Click "Add UPS" to configure your first UPS.'));
      container.appendChild(empty);
      return;
    }
    list.forEach(ups => container.appendChild(this.renderUPSItem(ups)));
  }

  renderUPSItem(ups) {
    const alerts = [];
    if (ups.alert_loadpct_high) alerts.push('Load: ' + ups.alert_loadpct_high + '%');
    if (ups.alert_bcharge_low) alerts.push('Battery: ' + ups.alert_bcharge_low + '%');
    if (ups.alert_on_battery) alerts.push('On Battery');
    if (ups.alert_runtime_low_minutes) alerts.push('Runtime: ' + ups.alert_runtime_low_minutes + 'min');
    if (ups.alert_itemp_high) alerts.push('Temp: ' + ups.alert_itemp_high + '°C');
    const testBtn = el('button', { class: 'btn btn-secondary', onclick: () => this.testUPSConnection(ups.name) }, 'Test');
    const editBtn = el('button', { class: 'btn btn-primary', onclick: () => this.editUPS(ups.name) }, 'Edit');
    const delBtn = el('button', { class: 'btn btn-danger', onclick: () => this.confirmDelete(ups.name) }, 'Delete');
    const item = el('div', { class: 'ups-item' },
      el('div', { class: 'ups-item-header' },
        el('div', { class: 'ups-item-title' }, ups.name),
        el('div', { class: 'ups-item-actions' }, testBtn, editBtn, delBtn)),
      el('div', { class: 'ups-item-details' },
        el('div', { class: 'ups-detail' },
          el('div', { class: 'ups-detail-label' }, 'Host'),
          el('div', { class: 'ups-detail-value' }, ups.host + ':' + ups.port)),
        el('div', { class: 'ups-detail' },
          el('div', { class: 'ups-detail-label' }, 'Polling Interval'),
          el('div', { class: 'ups-detail-value' }, ups.interval_seconds + 's')),
        el('div', { class: 'ups-detail' },
          el('div', { class: 'ups-detail-label' }, 'Alerts'),
          el('div', { class: 'ups-detail-value' }, alerts.length ? alerts.join(', ') : 'None'))));
    return item;
  }

  showUPSModal(ups = null) {
    const modal = document.getElementById('ups-modal');
    const title = document.getElementById('modal-title');
    const form = document.getElementById('ups-form');
    form.reset();
    if (ups) {
      title.textContent = 'Edit UPS';
      this.populateForm(ups);
      form.dataset.mode = 'edit';
      form.dataset.upsName = ups.name;
    } else {
      title.textContent = 'Add UPS';
      form.dataset.mode = 'add';
      delete form.dataset.upsName;
    }
    modal.style.display = 'block';
  }

  populateForm(ups) {
    document.getElementById('ups-name').value = ups.name || '';
    document.getElementById('ups-host').value = ups.host || '';
    document.getElementById('ups-port').value = ups.port || 3551;
    document.getElementById('ups-interval').value = ups.interval_seconds || 30;
    document.getElementById('ups-loadpct').value = ups.alert_loadpct_high || '';
    document.getElementById('ups-bcharge').value = ups.alert_bcharge_low || '';
    document.getElementById('ups-onbattery').checked = !!ups.alert_on_battery;
    document.getElementById('ups-runtime').value = ups.alert_runtime_low_minutes || '';
    const itemp = document.getElementById('ups-itemp');
    if (itemp) itemp.value = ups.alert_itemp_high || '';
  }

  closeModal(modal) { modal.style.display = 'none'; }

  async saveUPS() {
    const form = document.getElementById('ups-form');
    const fd = new FormData(form);
    const mode = form.dataset.mode;
    const name = form.dataset.upsName;
    const data = {
      name: fd.get('name'),
      host: fd.get('host'),
      port: parseInt(fd.get('port')) || 3551,
      interval_seconds: parseInt(fd.get('interval_seconds')) || 30,
      alert_on_battery: fd.has('alert_on_battery'),
    };
    const num = (k) => { const v = fd.get(k); if (v) data[k] = parseFloat(v); };
    num('alert_loadpct_high'); num('alert_bcharge_low');
    num('alert_runtime_low_minutes'); num('alert_itemp_high');
    try {
      const url = mode === 'edit' ? '/api/config/ups/' + name : '/api/config/ups';
      const method = mode === 'edit' ? 'PUT' : 'POST';
      const resp = await window.apiFetch(url, { method, body: JSON.stringify(data) });
      const result = await resp.json();
      if (!resp.ok) throw new Error(result.detail || 'Save failed');
      this.showToast(result.message, 'success');
      this.closeModal(document.getElementById('ups-modal'));
      this.loadUPSList();
    } catch (err) { this.showToast('Error: ' + err.message, 'error'); }
  }

  async editUPS(name) {
    try {
      const resp = await window.apiFetch('/api/config/ups/' + name);
      const ups = await resp.json();
      if (!resp.ok) throw new Error(ups.detail || 'Load failed');
      this.showUPSModal(ups);
    } catch (err) { this.showToast('Error: ' + err.message, 'error'); }
  }

  confirmDelete(name) {
    document.getElementById('confirm-message').textContent =
      'Delete UPS "' + name + '"? This cannot be undone.';
    this.confirmCallback = () => this.deleteUPS(name);
    document.getElementById('confirm-modal').style.display = 'block';
  }

  async deleteUPS(name) {
    try {
      const resp = await window.apiFetch('/api/config/ups/' + name, { method: 'DELETE' });
      const result = await resp.json();
      if (!resp.ok) throw new Error(result.detail || 'Delete failed');
      this.showToast(result.message, 'success');
      this.loadUPSList();
    } catch (err) { this.showToast('Error: ' + err.message, 'error'); }
  }

  async testConnection() {
    const form = document.getElementById('ups-form');
    const fd = new FormData(form);
    const data = {
      name: fd.get('name') || 'test',
      host: fd.get('host'),
      port: parseInt(fd.get('port')) || 3551,
      interval_seconds: 30,
      alert_on_battery: false,
    };
    if (!data.host) { this.showToast('Host required', 'error'); return; }
    const btn = document.getElementById('test-connection-btn');
    const orig = btn.textContent;
    btn.textContent = 'Testing...'; btn.disabled = true;
    try {
      const resp = await window.apiFetch('/api/config/ups/test', {
        method: 'POST', body: JSON.stringify(data),
      });
      const r = await resp.json();
      this.showToast(r.message || (r.success ? 'OK' : 'Failed'),
        r.success ? 'success' : 'error');
    } catch (err) { this.showToast('Test failed: ' + err.message, 'error'); }
    finally { btn.textContent = orig; btn.disabled = false; }
  }

  async testUPSConnection(name) {
    try {
      const resp = await window.apiFetch('/api/config/ups/' + name + '/test', { method: 'POST' });
      const r = await resp.json();
      this.showToast(r.message || (r.success ? 'OK' : 'Failed'),
        r.success ? 'success' : 'error');
    } catch (err) { this.showToast('Test failed: ' + err.message, 'error'); }
  }

  showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = el('div', { class: 'toast ' + type }, message);
    container.appendChild(toast);
    setTimeout(() => { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 5000);
  }
}

document.addEventListener('DOMContentLoaded', () => { new ConfigManager(); });
