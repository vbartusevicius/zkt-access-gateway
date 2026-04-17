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
        badge.className = 'flex items-center gap-3 px-4 py-2 mt-2 w-max rounded-full text-sm font-medium bg-success-bg text-success border border-success/20';
        badge.innerHTML = `
          <span class="relative flex h-3 w-3">
            <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-success opacity-75"></span>
            <span class="relative inline-flex rounded-full h-3 w-3 bg-success"></span>
          </span>
          <span class="status-text tracking-wide">Connected</span>
        `;
        document.getElementById('stat-ip').textContent = data.ip || 'Unknown';
        document.getElementById('stat-sn').textContent = data.serial_number || 'Unknown';
        document.getElementById('stat-users').textContent = data.users_count || '0';
      } else {
        badge.className = 'flex items-center gap-3 px-4 py-2 mt-2 w-max rounded-full text-sm font-medium bg-white/5 text-text-secondary border border-panel-border';
        badge.innerHTML = `
          <span class="relative flex h-3 w-3">
            <span class="relative inline-flex rounded-full h-3 w-3 bg-text-secondary"></span>
          </span>
          <span class="status-text tracking-wide">Offline</span>
        `;
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
        tbody.innerHTML = '<tr><td colspan="4" class="text-center text-text-secondary">No recent events</td></tr>';
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
      1: 'Punch during Normal Open',
      2: 'First Card Normal Open',
      3: 'Multi-Card Open',
      4: 'Emergency Password Open',
      5: 'Open during Normal Open',
      6: 'Linkage Event Triggered',
      7: 'Cancel Alarm',
      8: 'Remote Opening',
      9: 'Remote Closing',
      10: 'Disable Intraday Normal Open',
      11: 'Enable Intraday Normal Open',
      12: 'Open Auxiliary Output',
      13: 'Close Auxiliary Output',
      20: 'Too Short Punch Interval',
      21: 'Door Inactive Time Zone',
      22: 'Illegal Time Zone',
      23: 'Access Denied',
      24: 'Anti-Passback',
      25: 'Interlock',
      26: 'Multi-Card Authentication',
      27: 'Unregistered Card',
      28: 'Opening Timeout',
      29: 'Card Expired',
      30: 'Password Error',
      200: 'Door Open',
      201: 'Door Closed',
      202: 'Exit Button Open',
      203: 'Door Open Too Long',
      204: 'Forced Open Alarm',
      220: 'Duress Password Open',
      221: 'Opened Unexpectedly',
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
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-text-secondary">No assigned users</td></tr>';
        return;
      }

      data.users.forEach(u => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${u.pin}</td>
          <td>${u.card || 'No Card'}</td>
          <td>${u.group_id || 'Default'}</td>
          <td>${u.super_authorize ? '<span class="text-primary font-medium">Admin</span>' : 'Standard'}</td>
          <td>${u.last_used ? new Date(u.last_used).toLocaleString() : '<span class="text-text-secondary italic">Never</span>'}</td>
          <td>
            <button class="btn delete-user-btn bg-danger text-white hover:bg-red-600 px-3 py-1.5 text-xs shadow-soft" data-pin="${u.pin}">Delete</button>
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
      const [hwRes, evRes] = await Promise.all([
        fetch(`${API_BASE}/hardware`),
        fetch(`${API_BASE}/events`)
      ]);
      const data = await hwRes.json();
      const evData = await evRes.json();
      
      const container = document.getElementById('hw-params-container');
      container.innerHTML = '';
      
      if (!data.hw || !data.hw.ip) {
        container.innerHTML = '<p class="text-text-secondary col-span-full">Controller is completely offline or not synced yet.</p>';
        return;
      }

      const hw = data.hw;
      const doors = data.doors || [];
      const activeDoors = doors.filter(d => d.active);
      const events = evData.events || [];

      // --- Main Controller Card ---
      container.innerHTML += `
        <div class="stat-card glass-panel interactive border-l-4 border-l-success col-span-full">
          <div class="flex items-center gap-3 mb-4">
            <div class="w-10 h-10 rounded-lg bg-success/20 flex items-center justify-center">
              <svg class="w-5 h-5 text-success" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
            </div>
            <div>
              <h3 class="text-lg font-semibold">${hw.device_name || 'ZKTeco Access Controller'}</h3>
              <p class="text-sm text-text-secondary">Main Controller</p>
            </div>
          </div>
          <div class="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div><span class="text-text-secondary">IP Address</span><br><span class="font-medium">${hw.ip}</span></div>
            <div><span class="text-text-secondary">Serial Number</span><br><span class="font-medium">${hw.serial_number}</span></div>
            <div><span class="text-text-secondary">Doors</span><br><span class="font-medium">${activeDoors.length} active / ${hw.door_count} total</span></div>
            <div><span class="text-text-secondary">Readers</span><br><span class="font-medium">${hw.reader_count}</span></div>
          </div>
        </div>
      `;

      // --- Per-Active-Door Sub-Device Cards ---
      activeDoors.forEach(door => {
        const did = door.door_id;

        // Find last event for this door
        const lastDoorEvent = events.find(ev => ev.door_id === did);
        const lastEventHTML = lastDoorEvent
          ? `<span class="font-medium text-text-primary">${this.formatEventType(lastDoorEvent.event_type)}</span>
             <span class="text-xs text-text-secondary ml-2">${new Date(lastDoorEvent.timestamp).toLocaleString()}</span>`
          : '<span class="text-text-secondary italic">No events yet</span>';

        // Find last card for this door
        const lastCardEvent = events.find(ev => ev.door_id === did && ev.card_id);
        const lastCardHTML = lastCardEvent
          ? `<span class="font-medium text-text-primary">${lastCardEvent.card_id}</span>`
          : '<span class="text-text-secondary italic">--</span>';

        // Door open/close from last contact event
        const contactEvent = events.find(ev => ev.door_id === did && [200, 201, 202].includes(ev.event_type));
        let doorStateHTML = '<span class="text-text-secondary italic">Unknown</span>';
        if (contactEvent) {
          const isOpen = [200, 202].includes(contactEvent.event_type);
          doorStateHTML = isOpen
            ? '<span class="text-danger font-medium">Open</span>'
            : '<span class="text-success font-medium">Closed</span>';
        }

        // Buttons
        const lockBtnHTML = `<button class="btn secondary door-lock-btn text-xs px-3 py-1.5" data-door="${did}">
          <svg class="w-4 h-4 inline mr-1" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>
          Door Lock
        </button>`;
        const auxBtnHTML = (door.aux_relay_count || 0) > 0
          ? `<button class="btn secondary aux-relay-btn text-xs px-3 py-1.5" data-door="${did}">
              <svg class="w-4 h-4 inline mr-1" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 1v6m0 6v6m11-7h-6m-6 0H1"/></svg>
              Aux Relay
            </button>`
          : '';

        container.innerHTML += `
          <div class="stat-card glass-panel interactive border-l-4 border-l-accent">
            <div class="flex items-center justify-between mb-4">
              <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-lg bg-accent/20 flex items-center justify-center">
                  <svg class="w-5 h-5 text-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
                </div>
                <div>
                  <h3 class="text-lg font-semibold">Door ${did}</h3>
                  <p class="text-xs text-text-secondary">via ${hw.device_name || 'Controller'}</p>
                </div>
              </div>
              <div>${doorStateHTML}</div>
            </div>
            <div class="grid grid-cols-2 gap-3 text-sm mb-4">
              <div><span class="text-text-secondary">Verify Mode</span><br><span class="font-medium">${door.verify_mode}</span></div>
              <div><span class="text-text-secondary">Reader</span><br><span class="font-medium">${door.reader || 'Unknown'}</span></div>
              <div><span class="text-text-secondary">Last Event</span><br>${lastEventHTML}</div>
              <div><span class="text-text-secondary">Last Card</span><br>${lastCardHTML}</div>
            </div>
            <div class="flex gap-2 pt-3 border-t border-white/5">
              ${lockBtnHTML}
              ${auxBtnHTML}
            </div>
          </div>
        `;
      });

      // Bind door lock buttons
      document.querySelectorAll('.door-lock-btn').forEach(btn => {
         btn.addEventListener('click', async (e) => {
             const doorId = e.currentTarget.dataset.door;
             try {
                showToast(`Opening Door ${doorId}...`, 'neutral');
                const res = await fetch(`${API_BASE}/relays/${doorId}/trigger`, { method: 'POST' });
                const resData = await res.json();
                if (resData.success) {
                    showToast(`Door ${doorId} lock triggered!`, 'success');
                } else {
                    showToast(`Failed: ${resData.detail}`, 'error');
                }
             } catch(err) {
                showToast(`System Error`, 'error');
             }
         });
      });

      // Bind aux relay buttons
      document.querySelectorAll('.aux-relay-btn').forEach(btn => {
         btn.addEventListener('click', async (e) => {
             const doorId = e.currentTarget.dataset.door;
             try {
                showToast(`Triggering Aux Relay for Door ${doorId}...`, 'neutral');
                const res = await fetch(`${API_BASE}/aux/${doorId}/trigger`, { method: 'POST' });
                const resData = await res.json();
                if (resData.success) {
                    showToast(`Aux Relay for Door ${doorId} triggered!`, 'success');
                } else {
                    showToast(`Failed: ${resData.detail}`, 'error');
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
