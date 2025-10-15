// Clean UPS Dashboard - Simplified but Functional
const DEBUG_ENABLED = localStorage.getItem('ups_debug') === 'true' || 
                     new URLSearchParams(window.location.search).get('debug') === 'true';

function debugLog(...args) {
  if (DEBUG_ENABLED) console.log('[UPS Debug]', ...args);
}

function debugError(...args) {
  console.error('[UPS Error]', ...args);
}

// Debug control functions
window.upsDebug = {
  enable: () => {
    localStorage.setItem('ups_debug', 'true');
    location.reload();
  },
  disable: () => {
    localStorage.removeItem('ups_debug');
    location.reload();
  }
};

const evtSource = new EventSource('/api/stream');
const charts = {};

// Core tile definitions
const TILE_REGISTRY = [
  { id: 'load_pct', metric: 'LOADPCT', label: 'Load %', type: 'gauge' },
  { id: 'battery_pct', metric: 'BCHARGE', label: 'Battery %', type: 'gauge' },
  { id: 'watts_usage', metric: 'DERIVED_WATTS', label: 'Watts', type: 'line' },
  { id: 'volt_line', metric: 'LINEV', label: 'Line V', type: 'value' },
  { id: 'volt_output', metric: 'OUTPUTV', label: 'Output V', type: 'value', fallback: 'LINEV' }
];

// Storage for tile positions and card sizes
const TILE_POS_KEY = 'upsTilePos.v1';
const CARD_SIZE_KEY = 'upsCardSizes.v1';
let savedTilePos = {};
let savedCardSizes = {};

function loadFromStorage(key, defaultValue = {}) {
  try { return JSON.parse(localStorage.getItem(key) || '{}'); } catch(_) { return defaultValue; }
}

function saveToStorage(key, data) {
  try { localStorage.setItem(key, JSON.stringify(data)); } catch(_) {}
}

// Initialize storage
savedTilePos = loadFromStorage(TILE_POS_KEY);
savedCardSizes = loadFromStorage(CARD_SIZE_KEY);

// Initialize tiles for a UPS
function initTilesFor(name, grid) {
  if (!grid) return;
  debugLog('Creating tiles for UPS:', name);
  
  TILE_REGISTRY.forEach((tileDef, idx) => {
    const tile = document.createElement('div');
    tile.className = 'tile';
    tile.dataset.tile = tileDef.id;
    
    // Default positioning
    tile.style.left = (10 + (idx % 3) * 220) + 'px';
    tile.style.top = (10 + Math.floor(idx / 3) * 180) + 'px';
    tile.style.width = '200px';
    tile.style.height = '160px';
    
    tile.innerHTML = `
      <h4>${tileDef.label}</h4>
      <div class="tile-body">
        ${createTileContent(name, tileDef)}
      </div>
    `;
    
    grid.appendChild(tile);
    attachTileBehavior(name, tile, tileDef);
  });
  
  applyStoredPositions(name, grid);
}

function createTileContent(name, tileDef) {
  if (tileDef.type === 'gauge') {
    return `<div class="gauge" data-gauge="${tileDef.metric}">
      <svg viewBox="0 0 120 70">
        <path d="M10 60 A50 50 0 0 1 110 60" class="gauge-bg" />
        <path d="M10 60 A50 50 0 0 1 110 60" class="gauge-fill" stroke-dasharray="0 157" />
        <text x="60" y="45" class="gauge-text" text-anchor="middle">--%</text>
      </svg>
    </div>`;
  } else if (tileDef.type === 'value') {
    const unit = tileDef.metric.includes('V') ? 'V' : 'W';
    return `<div class="big-value-container">
      <span class="big-value" data-value="${tileDef.metric}">--</span>
      <span class="value-unit">${unit}</span>
    </div>`;
  } else if (tileDef.type === 'line') {
    const canvasId = `chart-${name}-${tileDef.id}`;
    return `<canvas id="${canvasId}" height="90"></canvas>`;
  }
  return '<div>--</div>';
}

function attachTileBehavior(name, tile, tileDef) {
  // Make tiles draggable
  let isDragging = false;
  let startX, startY, initialLeft, initialTop;
  
  tile.addEventListener('mousedown', (e) => {
    if (e.target.tagName === 'CANVAS') return; // Don't drag on charts
    isDragging = true;
    startX = e.clientX;
    startY = e.clientY;
    initialLeft = parseInt(tile.style.left) || 0;
    initialTop = parseInt(tile.style.top) || 0;
    tile.style.zIndex = 1000;
    e.preventDefault();
  });
  
  document.addEventListener('mousemove', (e) => {
    if (!isDragging) return;
    const deltaX = e.clientX - startX;
    const deltaY = e.clientY - startY;
    tile.style.left = (initialLeft + deltaX) + 'px';
    tile.style.top = (initialTop + deltaY) + 'px';
  });
  
  document.addEventListener('mouseup', () => {
    if (isDragging) {
      isDragging = false;
      tile.style.zIndex = '';
      savePositions(name);
    }
  });
  
  // Initialize chart if needed
  if (tileDef.type === 'line') {
    setTimeout(() => initChart(name, tileDef), 100);
  }
}

function initChart(name, tileDef) {
  const canvasId = `chart-${name}-${tileDef.id}`;
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  
  debugLog('Creating chart:', canvasId);
  
  try {
    charts[canvasId] = new Chart(canvas, {
      type: 'line',
      data: {
        labels: [],
        datasets: [{
          label: tileDef.label,
          data: [],
          borderColor: '#ff6b35',
          backgroundColor: 'rgba(255,107,53,0.15)',
          tension: 0.3,
          fill: true,
          pointRadius: 0
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: { beginAtZero: false },
          x: { display: false }
        },
        plugins: { legend: { display: false } }
      }
    });
  } catch (error) {
    debugError('Chart creation failed:', canvasId, error);
  }
}

function savePositions(name) {
  const grid = document.querySelector(`#card-${name} [data-tile-grid]`);
  if (!grid) return;
  
  savedTilePos[name] = {};
  grid.querySelectorAll('.tile').forEach(tile => {
    const id = tile.dataset.tile;
    savedTilePos[name][id] = {
      left: parseInt(tile.style.left) || 0,
      top: parseInt(tile.style.top) || 0,
      width: parseInt(tile.style.width) || 200,
      height: parseInt(tile.style.height) || 160
    };
  });
  
  saveToStorage(TILE_POS_KEY, savedTilePos);
}

function applyStoredPositions(name, grid) {
  const positions = savedTilePos[name];
  if (!positions) return;
  
  grid.querySelectorAll('.tile').forEach(tile => {
    const id = tile.dataset.tile;
    const pos = positions[id];
    if (pos) {
      tile.style.left = pos.left + 'px';
      tile.style.top = pos.top + 'px';
      tile.style.width = pos.width + 'px';
      tile.style.height = pos.height + 'px';
    }
  });
}

// Reset layout function
function resetLayout(name) {
  debugLog('Resetting layout for:', name);
  const grid = document.querySelector(`#card-${name} [data-tile-grid]`);
  if (!grid) return;
  
  // Clear existing tiles and charts
  Object.keys(charts).forEach(chartId => {
    if (chartId.includes(name)) {
      try { charts[chartId].destroy(); } catch(_) {}
      delete charts[chartId];
    }
  });
  
  grid.innerHTML = '';
  
  // Clear saved positions
  delete savedTilePos[name];
  saveToStorage(TILE_POS_KEY, savedTilePos);
  
  // Recreate tiles
  initTilesFor(name, grid);
  
  // Auto-arrange with proper spacing
  autoArrangeTiles(name);
}

function autoArrangeTiles(name) {
  const grid = document.querySelector(`#card-${name} [data-tile-grid]`);
  if (!grid) return;
  
  const tiles = Array.from(grid.querySelectorAll('.tile'));
  const cols = 3;
  const tileWidth = 200;
  const tileHeight = 160;
  const gap = 20;
  
  tiles.forEach((tile, idx) => {
    const col = idx % cols;
    const row = Math.floor(idx / cols);
    tile.style.left = (10 + col * (tileWidth + gap)) + 'px';
    tile.style.top = (10 + row * (tileHeight + gap)) + 'px';
    tile.style.width = tileWidth + 'px';
    tile.style.height = tileHeight + 'px';
  });
  
  savePositions(name);
}

// Update functions
function updateUPSData(name, data) {
  const card = document.getElementById(`card-${name}`);
  if (!card) return;
  
  // Ensure tiles exist
  const grid = card.querySelector('[data-tile-grid]');
  if (grid && grid.children.length === 0) {
    initTilesFor(name, grid);
  }
  
  // Update status and badges
  updateBadges(card, data);
  
  // Update tiles
  TILE_REGISTRY.forEach(tileDef => {
    updateTile(name, tileDef, data);
  });
}

function updateBadges(card, data) {
  // Update status
  const status = card.querySelector('[data-field="STATUS"]');
  if (status) {
    status.textContent = data.STATUS || 'UNKNOWN';
    status.className = 'ups-status ' + (data.STATUS === 'ONLINE' ? 'online' : 'unknown');
  }
  
  // Update model/serial
  const modelSerial = card.querySelector('[data-model-serial]');
  if (modelSerial && (data.MODEL || data.SERIALNO)) {
    const parts = [];
    if (data.MODEL) parts.push(data.MODEL);
    if (data.SERIALNO) parts.push(`S/N: ${data.SERIALNO}`);
    modelSerial.textContent = parts.join(' • ');
  }
  
  // Update other badges
  ['RUNTIME_MINUTES', 'DERIVED_WATTS', 'HEADROOM_PCT'].forEach(field => {
    const badge = card.querySelector(`[data-field="${field}"]`);
    if (badge && data[field]) {
      const value = parseFloat(data[field]) || 0;
      const unit = field === 'RUNTIME_MINUTES' ? ' m' : 
                   field === 'DERIVED_WATTS' ? ' W' : ' headroom';
      badge.textContent = value.toFixed(0) + unit;
    }
  });
}

function updateTile(name, tileDef, data) {
  const rawValue = data[tileDef.metric] || (tileDef.fallback ? data[tileDef.fallback] : null);
  if (!rawValue) return;
  
  const value = parseFloat(rawValue) || 0;
  
  if (tileDef.type === 'gauge') {
    updateGauge(name, tileDef.metric, value);
  } else if (tileDef.type === 'value') {
    updateValueDisplay(name, tileDef.metric, value);
  } else if (tileDef.type === 'line') {
    updateChart(name, tileDef, value);
  }
}

function updateGauge(name, metric, value) {
  const gauge = document.querySelector(`#card-${name} [data-gauge="${metric}"]`);
  if (!gauge) return;
  
  const fill = gauge.querySelector('.gauge-fill');
  const text = gauge.querySelector('.gauge-text');
  
  if (fill && text) {
    const total = 157;
    const filled = (value / 100) * total;
    fill.setAttribute('stroke-dasharray', `${filled} ${total - filled}`);
    text.textContent = value.toFixed(0) + '%';
    
    gauge.className = 'gauge ' + (value < 15 ? 'critical' : value < 35 ? 'low' : 'good');
  }
}

function updateValueDisplay(name, metric, value) {
  const element = document.querySelector(`#card-${name} [data-value="${metric}"]`);
  if (!element) return;
  
  element.textContent = value.toFixed(1);
  
  if (metric.includes('V')) {
    element.className = 'big-value ' + (value >= 114 && value <= 126 ? 'voltage-good' : 'voltage-bad');
  }
}

function updateChart(name, tileDef, value) {
  const chartId = `chart-${name}-${tileDef.id}`;
  const chart = charts[chartId];
  if (!chart) return;
  
  const now = new Date().toLocaleTimeString();
  chart.data.labels.push(now);
  chart.data.datasets[0].data.push(value);
  
  // Keep last 60 points
  if (chart.data.labels.length > 60) {
    chart.data.labels.shift();
    chart.data.datasets[0].data.shift();
  }
  
  // Smart scaling for watts
  if (tileDef.id === 'watts_usage') {
    const values = chart.data.datasets[0].data;
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min;
    
    if (range <= 50) {
      chart.options.scales.y.min = Math.max(0, min - 10);
      chart.options.scales.y.max = max + 10;
    }
  }
  
  chart.update('none');
}

// SSE event handling
evtSource.onmessage = (e) => {
  try {
    const payload = JSON.parse(e.data);
    const snapshots = payload.snapshots || {};
    
    Object.entries(snapshots).forEach(([name, snap]) => {
      updateUPSData(name, snap);
    });
  } catch (err) {
    debugError('SSE Error:', err);
  }
};

// Card resize functionality
function persistCardSize(name, width, height) {
  savedCardSizes[name] = { width, height };
  saveToStorage(CARD_SIZE_KEY, savedCardSizes);
}

function restoreCardSize(name) {
  const card = document.getElementById(`card-${name}`);
  const saved = savedCardSizes[name];
  if (card && saved) {
    card.style.width = saved.width + 'px';
    card.style.height = saved.height + 'px';
  }
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  debugLog('Dashboard initializing...');
  
  // Initialize existing cards
  document.querySelectorAll('.card').forEach(card => {
    const name = card.id.replace('card-', '');
    const grid = card.querySelector('[data-tile-grid]');
    if (grid) {
      initTilesFor(name, grid);
      restoreCardSize(name);
    }
  });
  
  // Attach reset button listeners
  document.addEventListener('click', (e) => {
    if (e.target.matches('[data-reset-layout]')) {
      const card = e.target.closest('.card');
      const name = card.id.replace('card-', '');
      resetLayout(name);
    }
  });
  
  // Watch for new cards added dynamically
  const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      mutation.addedNodes.forEach((node) => {
        if (node.nodeType === Node.ELEMENT_NODE && node.classList?.contains('card')) {
          const name = node.id.replace('card-', '');
          const grid = node.querySelector('[data-tile-grid]');
          if (grid) {
            debugLog('New UPS card detected:', name);
            initTilesFor(name, grid);
          }
        }
      });
    });
  });
  
  const upsCards = document.getElementById('ups-cards');
  if (upsCards) {
    observer.observe(upsCards, { childList: true });
  }
});