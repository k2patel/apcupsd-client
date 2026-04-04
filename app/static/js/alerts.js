// Alerts page (DOM-safe)
(async function () {
  function cell(text, cls) {
    const td = document.createElement('td');
    td.textContent = text;
    if (cls) td.className = cls;
    return td;
  }

  async function loadUps() {
    const r = await window.apiFetch('/api/ups');
    if (!r.ok) return;
    const list = await r.json();
    const sel = document.getElementById('filter-ups');
    list.forEach(u => {
      const o = document.createElement('option');
      o.value = u.name; o.textContent = u.name;
      sel.appendChild(o);
    });
  }

  async function loadAlerts() {
    const severity = document.getElementById('filter-severity').value;
    const ups = document.getElementById('filter-ups').value;
    const view = document.getElementById('filter-view').value;
    const path = view === 'active' ? '/api/alerts/active' : '/api/alerts';
    const params = new URLSearchParams();
    if (severity) params.set('severity', severity);
    if (ups) params.set('ups', ups);
    if (view === 'history') params.set('days', '30');
    const url = path + (params.toString() ? '?' + params.toString() : '');
    const r = await window.apiFetch(url);
    const tbody = document.getElementById('alerts-tbody');
    tbody.textContent = '';
    if (!r.ok) {
      const tr = document.createElement('tr');
      tr.appendChild(cell('Failed to load')); tbody.appendChild(tr); return;
    }
    const rows = await r.json();
    if (!rows.length) {
      const tr = document.createElement('tr');
      tr.appendChild(cell('No alerts')); tbody.appendChild(tr); return;
    }
    rows.forEach(a => {
      const tr = document.createElement('tr');
      tr.appendChild(cell(new Date(a.ts * 1000).toLocaleString()));
      const sevCell = document.createElement('td');
      const sevSpan = document.createElement('span');
      sevSpan.className = 'sev ' + a.severity;
      sevSpan.textContent = a.severity;
      sevCell.appendChild(sevSpan);
      tr.appendChild(sevCell);
      tr.appendChild(cell(a.ups));
      tr.appendChild(cell(a.code || ''));
      tr.appendChild(cell(a.message));
      tr.appendChild(cell(a.acked_ts ? new Date(a.acked_ts * 1000).toLocaleString() : ''));
      const actionCell = document.createElement('td');
      if (!a.acked_ts) {
        const btn = document.createElement('button');
        btn.className = 'btn btn-secondary ack-btn';
        btn.textContent = 'Ack';
        btn.dataset.id = a.id;
        btn.addEventListener('click', async () => {
          await window.apiFetch('/api/alerts/' + btn.dataset.id + '/ack', { method: 'POST' });
          loadAlerts();
        });
        actionCell.appendChild(btn);
      }
      tr.appendChild(actionCell);
      tbody.appendChild(tr);
    });
  }

  document.getElementById('refresh-btn').addEventListener('click', loadAlerts);
  ['filter-severity', 'filter-ups', 'filter-view'].forEach(id => {
    document.getElementById(id).addEventListener('change', loadAlerts);
  });
  await loadUps();
  await loadAlerts();
})();
