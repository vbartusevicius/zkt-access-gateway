// Frontend Logic for ZKAccess Gateway

const API_BASE = '/api';

// Navigation Manager
class AppNavigation {
  constructor() {
    this.navItems = document.querySelectorAll('.nav-item');
    this.sections = document.querySelectorAll('.view-section');
    this.init();
  }

  init() {
    this.navItems.forEach(item => {
      item.addEventListener('click', (e) => {
        const targetId = e.currentTarget.dataset.target;
        this.switchView(targetId);
      });
    });
  }

  switchView(targetId) {
    // Update nav classes
    this.navItems.forEach(btn => btn.classList.remove('active'));
    document.querySelector(`[data-target="${targetId}"]`).classList.add('active');

    // Update section visibility
    this.sections.forEach(sec => {
      sec.classList.remove('active');
      setTimeout(() => sec.classList.add('hidden'), 300); // Wait for fade out
    });
    
    const activeSection = document.getElementById(targetId);
    activeSection.classList.remove('hidden');
    // Force reflow
    void activeSection.offsetWidth;
    activeSection.classList.add('active');

    // Trigger section-specific refreshes
    if (targetId === 'dashboard') appState.fetchStatus();
    if (targetId === 'doors') appState.fetchEvents();
  }
}

// State & API Manager
class AppState {
  constructor() {
    this.statusInterval = null;
    this.init();
  }

  init() {
    this.fetchSettings();
    this.fetchStatus();
    this.fetchEvents();

    // Setup periodic refresh
    this.statusInterval = setInterval(() => this.fetchStatus(), 10000);

    // Bind event listeners
    document.getElementById('save-settings-btn').addEventListener('click', () => this.saveSettings());
    document.getElementById('test-conn-btn').addEventListener('click', () => this.testConnection());
    document.getElementById('refresh-doors-btn').addEventListener('click', () => this.fetchEvents());
  }

  async fetchStatus() {
    try {
      const res = await fetch(`${API_BASE}/status`);
      const data = await res.json();
      
      const badge = document.getElementById('controller-status');
      
      if (data.connected) {
        badge.className = 'status-badge connected';
        badge.querySelector('.status-text').textContent = 'Connected';
        document.getElementById('stat-ip').textContent = data.ip || 'Unknown';
        document.getElementById('stat-sn').textContent = data.serial_number || 'Unknown';
        document.getElementById('stat-users').textContent = data.users_count || '0';
      } else {
        badge.className = 'status-badge';
        badge.querySelector('.status-text').textContent = 'Offline';
        document.getElementById('stat-ip').textContent = '--';
        document.getElementById('stat-sn').textContent = '--';
      }

      document.getElementById('stat-mqtt').textContent = data.mqtt_connected ? 'Active' : 'Disconnected';
      
    } catch (e) {
      console.error(e);
    }
  }

  async fetchEvents() {
    try {
      const res = await fetch(`${API_BASE}/events`);
      const data = await res.json();
      
      const tbody = document.getElementById('events-tbody');
      tbody.innerHTML = '';
      
      if (!data.events || data.events.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color: var(--text-secondary);">No recent events</td></tr>';
        return;
      }

      data.events.forEach(ev => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${new Date(ev.timestamp).toLocaleString()}</td>
          <td>Door ${ev.door_id}</td>
          <td>${ev.card_id || 'N/A'}</td>
          <td>${this.formatEventType(ev.event_type)}</td>
        `;
        tbody.appendChild(tr);
      });
      
    } catch (e) {
      console.error(e);
    }
  }

  formatEventType(type) {
    const types = {
      0: 'Normal Punch Open',
      27: 'Unregistered Card',
      // Add other types based on ZKAccess SDK docs
    };
    return types[type] || `Code: ${type}`;
  }

  async fetchSettings() {
    try {
      const res = await fetch(`${API_BASE}/settings`);
      const data = await res.json();
      
      document.getElementById('setting-zkt-connstr').value = data.zkt_connstr || '';
      document.getElementById('setting-mqtt-broker').value = data.mqtt_broker || '';
      document.getElementById('setting-mqtt-port').value = data.mqtt_port || '1883';
      document.getElementById('setting-mqtt-user').value = data.mqtt_user || '';
      document.getElementById('setting-mqtt-password').value = data.mqtt_password || '';
      
    } catch (e) {
      console.error(e);
    }
  }

  async saveSettings() {
    const payload = {
      zkt_connstr: document.getElementById('setting-zkt-connstr').value,
      mqtt_broker: document.getElementById('setting-mqtt-broker').value,
      mqtt_port: parseInt(document.getElementById('setting-mqtt-port').value) || 1883,
      mqtt_user: document.getElementById('setting-mqtt-user').value,
      mqtt_password: document.getElementById('setting-mqtt-password').value
    };

    try {
      const res = await fetch(`${API_BASE}/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      
      if (res.ok) {
        showToast('Settings saved successfully', 'success');
        this.fetchStatus(); // Refresh status after saving
      } else {
        showToast('Failed to save settings', 'error');
      }
    } catch (e) {
      showToast('API Communication Error', 'error');
    }
  }

  async testConnection() {
    const connstr = document.getElementById('setting-zkt-connstr').value;
    const btn = document.getElementById('test-conn-btn');
    btn.textContent = 'Testing...';
    btn.disabled = true;

    try {
      const res = await fetch(`${API_BASE}/test_connection`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ zkt_connstr: connstr })
      });
      
      const data = await res.json();
      if (data.success) {
        showToast('Connection to controller successful', 'success');
      } else {
        showToast('Connection failed: ' + data.detail, 'error');
      }
    } catch (e) {
      showToast('Error testing connection', 'error');
    } finally {
      btn.textContent = 'Test Connection';
      btn.disabled = false;
    }
  }
}

// Toast System
function showToast(message, type = 'success') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  
  container.appendChild(toast);
  
  setTimeout(() => {
    toast.remove();
  }, 3000);
}

// Init
const appNav = new AppNavigation();
const appState = new AppState();
