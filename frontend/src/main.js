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
    if (targetId === 'users') appState.fetchUsers();
    if (targetId === 'hardware') appState.fetchHardware();
  }
}

// State & API Manager
class AppState {
  constructor() {
    this.statusInterval = null;
    this.init();
  }

  init() {
    this.fetchStatus();
    this.fetchEvents();
    this.fetchUsers();
    this.fetchHardware();

    // Setup periodic refresh
    this.statusInterval = setInterval(() => {
        this.fetchStatus();
        this.fetchEvents();
        this.fetchUsers();
        this.fetchHardware();
    }, 15000);

    // Bind event listeners
    document.getElementById('refresh-doors-btn').addEventListener('click', () => this.fetchEvents());
    document.getElementById('refresh-users-btn').addEventListener('click', () => this.fetchUsers());
    document.getElementById('refresh-hardware-btn').addEventListener('click', () => this.fetchHardware());
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

  async fetchUsers() {
    try {
      const res = await fetch(`${API_BASE}/users`);
      const data = await res.json();
      
      const tbody = document.getElementById('users-tbody');
      tbody.innerHTML = '';
      
      if (!data.users || data.users.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color: var(--text-secondary);">No assigned users</td></tr>';
        return;
      }

      data.users.forEach(u => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${u.pin}</td>
          <td>${u.card || 'No Card'}</td>
          <td>${u.group_id || 'Default'}</td>
          <td>${u.super_authorize ? '<span style="color:var(--color-primary)">Admin</span>' : 'Standard'}</td>
        `;
        tbody.appendChild(tr);
      });
      
    } catch (e) {
      console.error(e);
    }
  }

  async fetchHardware() {
    try {
      const res = await fetch(`${API_BASE}/hardware`);
      const data = await res.json();
      
      const container = document.getElementById('hw-params-container');
      container.innerHTML = '';
      
      if (!data.hw || !data.hw.ip) {
        container.innerHTML = '<p style="color: var(--text-secondary);">Controller is completely offline or not synced yet.</p>';
        return;
      }

      // Base Device Info
      container.innerHTML += `
        <div class="stat-card glass-panel">
          <h3>Hardware Info</h3>
          <p class="stat-value" style="font-size:1.25rem;">ZKTeco Access Device</p>
          <div style="margin-top:1rem;font-size:0.875rem;color:var(--text-secondary);">
             IP: ${data.hw.ip}<br>
             SN: ${data.hw.serial_number}<br>
             Doors: ${data.hw.door_count}<br>
             Readers: ${data.hw.reader_count}<br>
             Relays/Locks: ${data.hw.relay_count}<br>
             Aux Inputs: ${data.hw.aux_input_count}
          </div>
        </div>
      `;

      // Render Each Door separately
      (data.doors || []).forEach(door => {
        container.innerHTML += `
          <div class="stat-card glass-panel" style="border-left: 4px solid var(--color-accent)">
            <h3>Door ${door.door_id} Node</h3>
            <p class="stat-value" style="font-size:1.25rem;">Operational</p>
            <div style="margin-top:1rem;font-size:0.875rem;color:var(--text-secondary);">
               Verify Mode Configured: ${door.verify_mode}
            </div>
          </div>
        `;
      });
      
    } catch (e) {
      console.error(e);
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
