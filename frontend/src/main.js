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
    document.getElementById('refresh-doors-btn')?.addEventListener('click', () => this.fetchEvents());
    document.getElementById('refresh-users-btn')?.addEventListener('click', () => this.fetchUsers());
    document.getElementById('refresh-hardware-btn')?.addEventListener('click', () => this.fetchHardware());
    
    // Quick Actions
    document.getElementById('sync-time-btn')?.addEventListener('click', () => this.triggerDeviceAction('sync-time'));
    document.getElementById('reboot-btn')?.addEventListener('click', () => {
        if(confirm("Are you sure you want to reboot the controller? This will take it offline for a few moments!")) {
            this.triggerDeviceAction('reboot');
        }
    });

    // User Form Handlers
    document.getElementById('create-user-form')?.addEventListener('submit', (e) => {
        e.preventDefault();
        this.createUser();
    });
    document.getElementById('autofill-card-btn')?.addEventListener('click', () => this.autofillLatestCard());
  }
  
  async triggerDeviceAction(action) {
    try {
      showToast(`Triggering ${action}...`, 'neutral');
      const res = await fetch(`${API_BASE}/device/${action}`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
          showToast(`Successfully completed ${action}!`, 'success');
      } else {
          showToast(`Failed: ${data.detail || 'Device may be busy. Try again soon.'}`, 'error');
      }
    } catch (e) {
      console.error(e);
      showToast(`Error: ${e.message}`, 'error');
    }
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
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color: var(--text-secondary);">No assigned users</td></tr>';
        return;
      }

      data.users.forEach(u => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${u.pin}</td>
          <td>${u.card || 'No Card'}</td>
          <td>${u.group_id || 'Default'}</td>
          <td>${u.super_authorize ? '<span style="color:var(--color-primary)">Admin</span>' : 'Standard'}</td>
          <td>${u.last_used ? new Date(u.last_used).toLocaleString() : '<span style="color:var(--text-secondary)">Never</span>'}</td>
          <td>
            <button class="btn primary delete-user-btn" data-pin="${u.pin}" style="background:var(--color-danger); padding:0.25rem 0.5rem; font-size:0.75rem;">Delete</button>
          </td>
        `;
        tbody.appendChild(tr);
      });

      // Bind delete buttons
      document.querySelectorAll('.delete-user-btn').forEach(btn => {
         btn.addEventListener('click', async (e) => {
             const pin = e.currentTarget.dataset.pin;
             if (confirm(`Are you sure you want to delete user ${pin}?`)) {
                 try {
                     const res = await fetch(`${API_BASE}/users/${pin}`, { method: 'DELETE' });
                     const resData = await res.json();
                     if (resData.success) {
                         showToast(`User ${pin} deleted!`, 'success');
                         this.fetchUsers();
                     } else {
                         showToast(`Failed to delete user: ${resData.detail}`, 'error');
                     }
                 } catch (err) {
                    showToast(`Error: ${err.message}`, 'error');
                 }
             }
         });
      });
      
    } catch (e) {
      console.error(e);
    }
  }

  async createUser() {
    const pin = document.getElementById('new-user-pin').value;
    const card = document.getElementById('new-user-card').value;
    const group = document.getElementById('new-user-group').value;
    const admin = document.getElementById('new-user-admin').checked;

    try {
        const res = await fetch(`${API_BASE}/users`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                pin, card, group, super_authorize: admin
            })
        });
        const data = await res.json();
        if (data.success) {
            showToast('User created successfully!', 'success');
            document.getElementById('create-user-form').reset();
            this.fetchUsers();
        } else {
            showToast(`Failed: ${data.detail}`, 'error');
        }
    } catch(err) {
        showToast('System Error', 'error');
    }
  }

  async autofillLatestCard() {
     try {
       const res = await fetch(`${API_BASE}/events`);
       const data = await res.json();
       if (data.events && data.events.length > 0) {
           // Find latest event with unregistered card (type 27) or any card
           const event = data.events[0];
           if (event && event.card_id) {
               document.getElementById('new-user-card').value = event.card_id;
               showToast('Card ID Autofilled from latest swipe!', 'success');
           } else {
               showToast('Latest event did not contain a Card ID.', 'error');
           }
       } else {
           showToast('No events found to pull card IDs from.', 'error');
       }
     } catch (e) {
       showToast('Error fetching events.', 'error');
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
        const isDisabled = door.verify_mode.includes('Custom/Unsupported (7)');
        const statusText = isDisabled ? 'Disabled / Not Present' : 'Operational';
        const colorStyle = isDisabled ? 'border-left: 4px solid var(--text-secondary); opacity: 0.7;' : 'border-left: 4px solid var(--color-accent)';
        
        // Find if there's a matching relay (door 1 usually maps to relay 1)
        const relayBtnHTML = isDisabled ? '' : `<button class="btn secondary trigger-door-btn" data-relay="${door.door_id}" style="margin-top: 0.5rem; float:right;">Remote Trigger (5s)</button>`;

        container.innerHTML += `
          <div class="stat-card glass-panel" style="${colorStyle}">
            <h3>Door ${door.door_id} Node</h3>
            <p class="stat-value" style="font-size:1.25rem;">${statusText}</p>
            <div style="margin-top:1rem;font-size:0.875rem;color:var(--text-secondary);">
               Verify Mode Configured: ${door.verify_mode}
               ${relayBtnHTML}
            </div>
          </div>
        `;
      });
      
      // Bind door remote triggers
      document.querySelectorAll('.trigger-door-btn').forEach(btn => {
         btn.addEventListener('click', async (e) => {
             const relayId = e.currentTarget.dataset.relay;
             try {
                showToast(`Triggering Relay ${relayId}...`, 'neutral');
                const res = await fetch(`${API_BASE}/relays/${relayId}/trigger`, { method: 'POST' });
                const resData = await res.json();
                if (resData.success) {
                    showToast(`Relay ${relayId} successfully triggered!`, 'success');
                } else {
                    showToast(`Remote Trigger Failed: ${resData.detail}`, 'error');
                }
             } catch(err) {
                showToast(`System Error`, 'error');
             }
         });
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
