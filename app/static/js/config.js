// Configuration management JavaScript

class ConfigManager {
  constructor() {
    this.init();
  }

  init() {
    this.bindEvents();
    this.loadUPSList();
  }

  bindEvents() {
    // Add UPS button
    document.getElementById('add-ups-btn').addEventListener('click', () => {
      this.showUPSModal();
    });

    // Modal close buttons
    document.querySelectorAll('.close').forEach(close => {
      close.addEventListener('click', (e) => {
        this.closeModal(e.target.closest('.modal'));
      });
    });

    // UPS form submission
    document.getElementById('ups-form').addEventListener('submit', (e) => {
      e.preventDefault();
      this.saveUPS();
    });

    // Test connection button
    document.getElementById('test-connection-btn').addEventListener('click', () => {
      this.testConnection();
    });

    // Cancel button
    document.getElementById('cancel-btn').addEventListener('click', () => {
      this.closeModal(document.getElementById('ups-modal'));
    });

    // Confirmation modal buttons
    document.getElementById('confirm-yes').addEventListener('click', () => {
      if (this.confirmCallback) {
        this.confirmCallback();
      }
      this.closeModal(document.getElementById('confirm-modal'));
    });

    document.getElementById('confirm-no').addEventListener('click', () => {
      this.closeModal(document.getElementById('confirm-modal'));
    });

    // Click outside modal to close
    window.addEventListener('click', (e) => {
      if (e.target.classList.contains('modal')) {
        this.closeModal(e.target);
      }
    });
  }

  async loadUPSList() {
    try {
      const response = await fetch('/api/config/ups');
      const upsList = await response.json();
      
      if (!response.ok) {
        throw new Error(upsList.detail || 'Failed to load UPS configurations');
      }

      this.renderUPSList(upsList);
    } catch (error) {
      this.showToast('Error loading UPS configurations: ' + error.message, 'error');
    }
  }

  renderUPSList(upsList) {
    const container = document.getElementById('ups-list');
    
    if (upsList.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <h3>No UPS Configured</h3>
          <p>Get started by clicking "Add UPS" above to configure your first UPS monitoring.</p>
        </div>
      `;
      return;
    }

    container.innerHTML = upsList.map(ups => this.renderUPSItem(ups)).join('');
    
    // Bind action buttons
    container.querySelectorAll('.edit-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const upsName = e.target.dataset.upsName;
        this.editUPS(upsName);
      });
    });

    container.querySelectorAll('.delete-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const upsName = e.target.dataset.upsName;
        this.confirmDelete(upsName);
      });
    });

    container.querySelectorAll('.test-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const upsName = e.target.dataset.upsName;
        this.testUPSConnection(upsName);
      });
    });
  }

  renderUPSItem(ups) {
    const alertsEnabled = [
      ups.alert_loadpct_high && `Load: ${ups.alert_loadpct_high}%`,
      ups.alert_bcharge_low && `Battery: ${ups.alert_bcharge_low}%`,
      ups.alert_on_battery && 'On Battery',
      ups.alert_runtime_low_minutes && `Runtime: ${ups.alert_runtime_low_minutes}min`
    ].filter(Boolean);

    return `
      <div class="ups-item">
        <div class="ups-item-header">
          <div class="ups-item-title">${ups.name}</div>
          <div class="ups-item-actions">
            <button class="btn btn-secondary test-btn" data-ups-name="${ups.name}">Test</button>
            <button class="btn btn-primary edit-btn" data-ups-name="${ups.name}">Edit</button>
            <button class="btn btn-danger delete-btn" data-ups-name="${ups.name}">Delete</button>
          </div>
        </div>
        <div class="ups-item-details">
          <div class="ups-detail">
            <div class="ups-detail-label">Host</div>
            <div class="ups-detail-value">${ups.host}:${ups.port}</div>
          </div>
          <div class="ups-detail">
            <div class="ups-detail-label">Polling Interval</div>
            <div class="ups-detail-value">${ups.interval_seconds}s</div>
          </div>
          <div class="ups-detail">
            <div class="ups-detail-label">Alerts</div>
            <div class="ups-detail-value">${alertsEnabled.length > 0 ? alertsEnabled.join(', ') : 'None'}</div>
          </div>
        </div>
      </div>
    `;
  }

  showUPSModal(ups = null) {
    const modal = document.getElementById('ups-modal');
    const title = document.getElementById('modal-title');
    const form = document.getElementById('ups-form');
    
    // Reset form
    form.reset();
    
    if (ups) {
      // Edit mode
      title.textContent = 'Edit UPS';
      this.populateForm(ups);
      form.dataset.mode = 'edit';
      form.dataset.upsName = ups.name;
    } else {
      // Add mode
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
    document.getElementById('ups-onbattery').checked = ups.alert_on_battery || false;
    document.getElementById('ups-runtime').value = ups.alert_runtime_low_minutes || '';
  }

  closeModal(modal) {
    modal.style.display = 'none';
  }

  async saveUPS() {
    const form = document.getElementById('ups-form');
    const formData = new FormData(form);
    const mode = form.dataset.mode;
    const upsName = form.dataset.upsName;
    
    const data = {
      name: formData.get('name'),
      host: formData.get('host'),
      port: parseInt(formData.get('port')) || 3551,
      interval_seconds: parseInt(formData.get('interval_seconds')) || 30,
      alert_on_battery: formData.has('alert_on_battery')
    };

    // Add optional alert thresholds
    const loadpct = formData.get('alert_loadpct_high');
    if (loadpct) data.alert_loadpct_high = parseFloat(loadpct);
    
    const bcharge = formData.get('alert_bcharge_low');
    if (bcharge) data.alert_bcharge_low = parseFloat(bcharge);
    
    const runtime = formData.get('alert_runtime_low_minutes');
    if (runtime) data.alert_runtime_low_minutes = parseFloat(runtime);

    try {
      let response;
      if (mode === 'edit') {
        response = await fetch(`/api/config/ups/${upsName}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });
      } else {
        response = await fetch('/api/config/ups', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });
      }

      const result = await response.json();
      
      if (!response.ok) {
        throw new Error(result.detail || 'Failed to save UPS configuration');
      }

      this.showToast(result.message, 'success');
      this.closeModal(document.getElementById('ups-modal'));
      this.loadUPSList();
    } catch (error) {
      this.showToast('Error saving UPS: ' + error.message, 'error');
    }
  }

  async editUPS(upsName) {
    try {
      const response = await fetch(`/api/config/ups/${upsName}`);
      const ups = await response.json();
      
      if (!response.ok) {
        throw new Error(ups.detail || 'Failed to load UPS configuration');
      }

      this.showUPSModal(ups);
    } catch (error) {
      this.showToast('Error loading UPS configuration: ' + error.message, 'error');
    }
  }

  confirmDelete(upsName) {
    const modal = document.getElementById('confirm-modal');
    const message = document.getElementById('confirm-message');
    
    message.textContent = `Are you sure you want to delete the UPS configuration "${upsName}"? This action cannot be undone.`;
    
    this.confirmCallback = () => this.deleteUPS(upsName);
    modal.style.display = 'block';
  }

  async deleteUPS(upsName) {
    try {
      const response = await fetch(`/api/config/ups/${upsName}`, {
        method: 'DELETE'
      });

      const result = await response.json();
      
      if (!response.ok) {
        throw new Error(result.detail || 'Failed to delete UPS configuration');
      }

      this.showToast(result.message, 'success');
      this.loadUPSList();
    } catch (error) {
      this.showToast('Error deleting UPS: ' + error.message, 'error');
    }
  }

  async testConnection() {
    const form = document.getElementById('ups-form');
    const formData = new FormData(form);
    
    const data = {
      name: formData.get('name') || 'test',
      host: formData.get('host'),
      port: parseInt(formData.get('port')) || 3551,
      interval_seconds: 30,
      alert_on_battery: false
    };

    if (!data.host) {
      this.showToast('Host is required for connection test', 'error');
      return;
    }

    const testBtn = document.getElementById('test-connection-btn');
    const originalText = testBtn.textContent;
    testBtn.textContent = 'Testing...';
    testBtn.disabled = true;

    try {
      const response = await fetch('/api/config/ups/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });

      const result = await response.json();
      let msg;
      if (result.success) {
        msg = 'Connection successful';
        if (result.data && result.data.STATUS) {
          msg += ` (STATUS=${result.data.STATUS})`;
        }
        this.showToast(msg, 'success');
      } else {
        if (result.connectivity && !result.connectivity.ok) {
          msg = 'TCP connectivity failed: ' + (result.connectivity.error || 'unknown error');
        } else if (result.protocol && !result.protocol.ok) {
          msg = 'Protocol error after TCP success: ' + (result.protocol.error || 'unknown error');
        } else {
          msg = result.message || 'Connection failed';
        }
        this.showToast(msg, 'error');
      }
    } catch (error) {
      this.showToast('Connection test failed: ' + error.message, 'error');
    } finally {
      testBtn.textContent = originalText;
      testBtn.disabled = false;
    }
  }

  async testUPSConnection(upsName) {
    const testBtn = document.querySelector(`[data-ups-name="${upsName}"].test-btn`);
    const originalText = testBtn.textContent;
    testBtn.textContent = 'Testing...';
    testBtn.disabled = true;

    try {
      const response = await fetch(`/api/config/ups/${upsName}/test`, {
        method: 'POST'
      });

      const result = await response.json();
      let msg;
      if (result.success) {
        msg = `Connection to ${upsName} successful`;
        if (result.data && result.data.STATUS) {
          msg += ` (STATUS=${result.data.STATUS})`;
        }
        this.showToast(msg, 'success');
      } else {
        if (result.connectivity && !result.connectivity.ok) {
          msg = `TCP connectivity failed: ${result.connectivity.error}`;
        } else if (result.protocol && !result.protocol.ok) {
          msg = `Protocol error: ${result.protocol.error}`;
        } else {
          msg = result.message || 'Connection failed';
        }
        this.showToast(`Connection to ${upsName} failed: ${msg}`, 'error');
      }
    } catch (error) {
      this.showToast(`Connection test failed: ${error.message}`, 'error');
    } finally {
      testBtn.textContent = originalText;
      testBtn.disabled = false;
    }
  }

  showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    
    container.appendChild(toast);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
    }, 5000);
  }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
  new ConfigManager();
});