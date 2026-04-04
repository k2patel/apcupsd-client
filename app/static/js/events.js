// Events log page (DOM-safe)
(async function () {
  function setCell(row, text) {
    const td = document.createElement('td');
    td.textContent = text;
    row.appendChild(td);
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

  async function loadEvents() {
    const ups = document.getElementById('filter-ups').value;
    const kind = document.getElementById('filter-kind').value;
    const params = new URLSearchParams();
    if (ups) params.set('ups', ups);
    if (kind) params.set('kind', kind);
    params.set('limit', '300');
    const r = await window.apiFetch('/api/events?' + params.toString());
    const tbody = document.getElementById('events-tbody');
    tbody.textContent = '';
    if (!r.ok) {
      const tr = document.createElement('tr');
      setCell(tr, 'Failed to load'); tbody.appendChild(tr); return;
    }
    const rows = await r.json();
    if (!rows.length) {
      const tr = document.createElement('tr');
      setCell(tr, 'No events'); tbody.appendChild(tr); return;
    }
    rows.forEach(e => {
      const tr = document.createElement('tr');
      setCell(tr, new Date(e.ts * 1000).toLocaleString());
      setCell(tr, e.ups);
      setCell(tr, e.type);
      setCell(tr, e.detail);
      tbody.appendChild(tr);
    });
  }

  document.getElementById('refresh-btn').addEventListener('click', loadEvents);
  document.getElementById('filter-ups').addEventListener('change', loadEvents);
  document.getElementById('filter-kind').addEventListener('change', loadEvents);

  await loadUps();
  await loadEvents();
})();
