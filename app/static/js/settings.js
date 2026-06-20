// Settings page
(async function () {
  function normalizeEnergyRate(value) {
    const parsed = Number.parseFloat(value);
    if (!Number.isFinite(parsed) || parsed < 0) return '0.0000';
    return parsed.toFixed(4);
  }

  async function loadUi() {
    const r = await window.apiFetch('/api/config/ui');
    if (!r.ok) return;
    const ui = await r.json();
    const form = document.getElementById('ui-form');
    Object.entries(ui).forEach(([k, v]) => {
      const el = form.elements[k];
      if (!el) return;
      if (el.type === 'checkbox') el.checked = !!v;
      else if (k === 'energy_cost_per_kwh') el.value = normalizeEnergyRate(v);
      else el.value = v;
    });
  }

  async function loadSmtp() {
    const r = await window.apiFetch('/api/config/smtp');
    if (!r.ok) return;
    const s = await r.json();
    if (!s) return;
    const form = document.getElementById('smtp-form');
    Object.entries(s).forEach(([k, v]) => {
      const el = form.elements[k];
      if (!el) return;
      if (k === 'to_addrs' && Array.isArray(v)) el.value = v.join(', ');
      else if (el.type === 'checkbox') el.checked = !!v;
      else if (v !== null && v !== undefined) el.value = v;
    });
  }

  document.getElementById('ui-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = e.target;
    const payload = {
      show_events: f.show_events.checked,
      show_energy: f.show_energy.checked,
      color_badges: f.color_badges.checked,
      enable_transfer_burst_alert: f.enable_transfer_burst_alert.checked,
      enable_voltage_deviation_alert: f.enable_voltage_deviation_alert.checked,
      energy_cost_per_kwh: Number.parseFloat(normalizeEnergyRate(f.energy_cost_per_kwh.value)),
    };
    const r = await window.apiFetch('/api/config/ui', {
      method: 'PUT', body: JSON.stringify(payload),
    });
    alert(r.ok ? 'UI settings saved' : 'Save failed');
  });

  document.getElementById('smtp-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = e.target;
    const to = f.to_addrs.value.split(',').map(s => s.trim()).filter(Boolean);
    const payload = {
      host: f.host.value,
      port: parseInt(f.port.value, 10),
      username: f.username.value || null,
      use_tls: f.use_tls.checked,
      use_ssl: f.use_ssl.checked,
      from_addr: f.from_addr.value || null,
      to_addrs: to,
      subject_prefix: f.subject_prefix.value || '[UPS]',
      silent_hours_start: f.silent_hours_start.value ? parseInt(f.silent_hours_start.value, 10) : null,
      silent_hours_end: f.silent_hours_end.value ? parseInt(f.silent_hours_end.value, 10) : null,
      daily_summary_hour: f.daily_summary_hour.value ? parseInt(f.daily_summary_hour.value, 10) : null,
    };
    const r = await window.apiFetch('/api/config/smtp', {
      method: 'PUT', body: JSON.stringify(payload),
    });
    alert(r.ok ? 'SMTP saved' : 'Save failed');
  });

  document.getElementById('test-smtp-btn').addEventListener('click', async () => {
    const r = await window.apiFetch('/api/config/smtp/test', { method: 'POST' });
    const body = await r.json().catch(() => ({}));
    alert(r.ok ? 'Test email sent' : 'Failed: ' + (body.detail || 'unknown'));
  });

  await loadUi();
  await loadSmtp();
})();
