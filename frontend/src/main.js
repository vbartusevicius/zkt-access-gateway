// Frontend Logic for ZKAccess Gateway

const API_BASE = '/api';

// ============================================================
// Helpers
// ============================================================

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[c]));

const fmtDT = (s) => (s ? new Date(s).toLocaleString() : '—');
const humanize = (s) => (s ? String(s).replace(/_/g, ' ') : '—');

async function apiGet(path, params = {}) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') qs.append(k, v);
  }
  const res = await fetch(`${API_BASE}${path}${qs.size ? '?' + qs : ''}`);
  return res.json();
}

async function apiSend(path, { method = 'POST', body = null } = {}) {
  const opts = { method };
  if (body !== null) {
    opts.headers = { 'Content-Type': 'application/json' };
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(`${API_BASE}${path}`, opts);
  return res.json();
}

function showToast(message, type = 'success') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

// Modal
function openModal(title, contentHTML, onSubmit, submitLabel = 'Save') {
  const overlay = document.getElementById('modal-overlay');
  document.getElementById('modal-title').textContent = title;
  const content = document.getElementById('modal-content');
  content.innerHTML = contentHTML;
  const submit = document.createElement('button');
  submit.className = 'btn primary w-full mt-6';
  submit.textContent = submitLabel;
  content.appendChild(submit);
  submit.addEventListener('click', () => onSubmit(content, closeModal));
  overlay.classList.remove('hidden');
  overlay.firstElementChild.scrollTop = 0;
}
function closeModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
}

// Render a form input group from a spec field
// ctx.doors: array of door ids, needed for door_mask fields
function fieldInput(f, value, ctx = {}) {
  const name = `data-field="${esc(f.name)}"`;
  let input;
  switch (f.type) {
    case 'door_mask': {
      const doors = ctx.doors || [];
      const mask = parseInt(value || 0, 10);
      input = `<div class="flex gap-3 flex-wrap door-mask" ${name}>` + doors.map(d =>
        `<label class="flex items-center gap-1.5 text-sm cursor-pointer">
          <input type="checkbox" class="w-auto" data-door-bit="${d}" ${mask & (1 << (d - 1)) ? 'checked' : ''}>
          <span>Door ${d}</span>
        </label>`
      ).join('') + '</div>';
      break;
    }
    case 'select':
      input = `<select ${name}>` + (f.choices || []).map(([v, label]) =>
        `<option value="${esc(v)}" ${String(value) === String(v) ? 'selected' : ''}>${esc(label)}</option>`
      ).join('') + '</select>';
      break;
    case 'bool':
      input = `<input type="checkbox" class="w-auto" ${name} ${value ? 'checked' : ''}>`;
      break;
    case 'password':
      input = `<input type="password" autocomplete="off" ${name} value="${esc(value ?? '')}">`;
      break;
    case 'int':
      input = `<input type="number" ${name} value="${esc(value ?? '')}"`
        + (f.min !== undefined ? ` min="${f.min}"` : '')
        + (f.max !== undefined ? ` max="${f.max}"` : '') + '>';
      break;
    case 'date':
      input = `<input type="date" ${name} value="${esc(value ?? '')}">`;
      break;
    case 'timerange': {
      const [start, end] = Array.isArray(value) ? value : [];
      input = `<div class="flex gap-2 items-center timerange" ${name}>
        <input type="time" class="flex-1" value="${toHHMM(start)}">
        <span class="text-text-secondary">–</span>
        <input type="time" class="flex-1" value="${toHHMM(end)}">
      </div>`;
      break;
    }
    default:
      input = `<input type="text" ${name} value="${esc(value ?? '')}">`;
  }
  return `<div class="form-group mb-0">
    <label>${esc(f.label)}</label>${input}
    ${f.help ? `<p class="text-xs text-text-secondary mt-1">${esc(f.help)}</p>` : ''}
  </div>`;
}

function toHHMM(v) {
  if (v === undefined || v === null || v === '') return '';
  if (typeof v === 'string' && v.includes(':')) return v.slice(0, 5); // "HH:MM[:SS]"
  const s = String(v).padStart(4, '0'); // int HHMM
  return `${s.slice(0, 2)}:${s.slice(2)}`;
}

function collectForm(container, fields) {
  const data = {};
  for (const f of fields) {
    const el = container.querySelector(`[data-field="${f.name}"]`);
    if (!el) continue;
    if (f.type === 'bool') {
      data[f.name] = el.checked;
    } else if (f.type === 'door_mask') {
      let mask = 0;
      el.querySelectorAll('[data-door-bit]:checked').forEach(cb =>
        mask |= (1 << (parseInt(cb.dataset.doorBit, 10) - 1)));
      data[f.name] = mask;
    } else if (f.type === 'timerange') {
      const [startEl, endEl] = el.querySelectorAll('input[type="time"]');
      if (startEl.value && endEl.value) data[f.name] = [startEl.value.replace(':', ''), endEl.value.replace(':', '')];
    } else if (f.type === 'int' || f.type === 'select') {
      if (el.value !== '') data[f.name] = parseInt(el.value, 10);
    } else {
      if (el.value !== '') data[f.name] = el.value;
    }
  }
  return data;
}

// ============================================================
// Event type classification
// ============================================================
function eventBadgeClass(t) {
  if (t === undefined || t === null) return 'neutral';
  if ([101, 103].includes(t)) return 'danger';        // duress events
  if (t >= 20 && t <= 37) return 'danger';            // denied family (card & fingerprint)
  if ([204, 220, 221].includes(t)) return 'warning';  // normal-open expiry / aux input faults
  if ([200, 201].includes(t)) return 'accent';        // door contact
  if ([205, 206].includes(t)) return 'neutral';       // remote normal open / device start
  if (t >= 0 && t <= 19) return 'success';            // granted family
  return 'neutral';
}

// ============================================================
// Views
// ============================================================

class DashboardView {
  async load() {
    try {
      const [data, evData, status] = await Promise.all([
        apiGet('/hardware'), apiGet('/events', { limit: 50 }), apiGet('/status')
      ]);
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

      const connBadge = status.connected
        ? `<span class="badge success">Online</span>`
        : `<span class="badge">Offline</span>`;
      const mqttBadge = status.mqtt_connected
        ? `<span class="badge info">MQTT Active</span>`
        : `<span class="badge">MQTT Off</span>`;

      container.innerHTML += `
        <div class="stat-card glass-panel interactive border-l-4 border-l-success col-span-full">
          <div class="flex items-center justify-between mb-4">
            <div class="flex items-center gap-3">
              <div class="w-10 h-10 rounded-lg bg-success/20 flex items-center justify-center">
                <svg class="w-5 h-5 text-success" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
              </div>
              <div>
                <h3 class="text-lg font-semibold">${esc(hw.device_name || 'ZKTeco Access Controller')}</h3>
                <p class="text-sm text-text-secondary">Main Controller</p>
              </div>
            </div>
            <div class="flex gap-2">${connBadge}${mqttBadge}</div>
          </div>
          <div class="grid grid-cols-2 md:grid-cols-6 gap-4 text-sm">
            <div><span class="text-text-secondary">IP Address</span><br><span class="font-medium">${esc(hw.ip)}</span></div>
            <div><span class="text-text-secondary">Serial Number</span><br><span class="font-medium break-all">${esc(hw.serial_number)}</span></div>
            <div><span class="text-text-secondary">Doors</span><br><span class="font-medium">${activeDoors.length} active / ${esc(hw.door_count)} total</span></div>
            <div><span class="text-text-secondary">Readers</span><br><span class="font-medium">${esc(hw.reader_count)}</span></div>
            <div><span class="text-text-secondary">Aux Inputs</span><br><span class="font-medium">${esc(hw.aux_input_count)}</span></div>
            <div><span class="text-text-secondary">Users</span><br><span class="font-medium">${esc(status.users_count || 0)}</span></div>
          </div>
        </div>
      `;

      for (const door of activeDoors) {
        const did = door.door_id;
        const lastDoorEvent = events.find(ev => ev.door_id === did);
        const lastEventHTML = lastDoorEvent
          ? `<span class="badge ${eventBadgeClass(lastDoorEvent.event_type)}">${esc(lastDoorEvent.description || 'Code: ' + lastDoorEvent.event_type)}</span>
             <span class="text-xs text-text-secondary ml-2">${fmtDT(lastDoorEvent.timestamp)}</span>`
          : '<span class="text-text-secondary italic">No events yet</span>';
        const lastCardEvent = events.find(ev => ev.door_id === did && ev.card_id);
        const lastCardHTML = lastCardEvent
          ? `<span class="font-medium">${lastCardEvent.user_name ? `${esc(lastCardEvent.user_name)} ` : ''}<span class="text-text-secondary">(${esc(lastCardEvent.card_id)})</span></span>`
          : '<span class="text-text-secondary italic">--</span>';
        const contactEvent = events.find(ev => ev.door_id === did && [200, 201, 202].includes(ev.event_type));
        let doorStateHTML = '<span class="text-text-secondary italic">Unknown</span>';
        if (contactEvent) {
          doorStateHTML = [200, 202].includes(contactEvent.event_type)
            ? '<span class="badge danger">Open</span>'
            : '<span class="badge success">Closed</span>';
        }
        const auxBtn = (door.aux_relay_count || 0) > 0
          ? `<button class="btn secondary aux-relay-btn text-xs px-3 py-1.5" data-door="${did}">Aux Relay</button>`
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
                  <p class="text-xs text-text-secondary">${esc(door.verify_mode || '')}</p>
                </div>
              </div>
              <div>${doorStateHTML}</div>
            </div>
            <div class="grid grid-cols-2 gap-3 text-sm mb-4">
              <div><span class="text-text-secondary">Reader</span><br><span class="font-medium">${esc(door.reader || 'Unknown')}</span></div>
              <div><span class="text-text-secondary">Last Card</span><br>${lastCardHTML}</div>
              <div class="col-span-2"><span class="text-text-secondary">Last Event</span><br>${lastEventHTML}</div>
            </div>
            <div class="flex gap-2 pt-3 border-t border-white/5">
              <button class="btn secondary door-lock-btn text-xs px-3 py-1.5" data-door="${did}">Trigger Lock</button>
              ${auxBtn}
            </div>
          </div>
        `;
      }

      container.querySelectorAll('.door-lock-btn').forEach(btn =>
        btn.addEventListener('click', () => this._trigger(btn.dataset.door, 'relays')));
      container.querySelectorAll('.aux-relay-btn').forEach(btn =>
        btn.addEventListener('click', () => this._trigger(btn.dataset.door, 'aux')));
    } catch (e) {
      console.error(e);
    }
  }

  async _trigger(doorId, kind) {
    try {
      showToast(`Triggering ${kind} for Door ${doorId}...`, 'neutral');
      const data = await apiSend(`/${kind}/${doorId}/trigger`);
      showToast(data.success ? `Door ${doorId} ${kind} triggered!` : `Failed: ${data.detail}`,
        data.success ? 'success' : 'error');
    } catch (e) {
      showToast('System Error', 'error');
    }
  }
}

class EventsView {
  constructor() {
    ['filter-door', 'filter-type', 'filter-from', 'filter-to']
      .forEach(id => document.getElementById(id)?.addEventListener('change', () => this.load()));
    document.getElementById('filter-q')?.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') this.load();
    });
    document.getElementById('filter-clear-btn')?.addEventListener('click', () => {
      ['filter-door', 'filter-type', 'filter-from', 'filter-to', 'filter-q']
        .forEach(id => { document.getElementById(id).value = ''; });
      this.load();
    });
    document.getElementById('refresh-events-btn')?.addEventListener('click', () => this.load());
  }

  initFilters(doors) {
    const doorSel = document.getElementById('filter-door');
    if (!doorSel.options.length && doors) {
      doorSel.innerHTML = '<option value="">All doors</option>'
        + doors.map(d => `<option value="${d.door_id}">Door ${d.door_id}</option>`).join('');
    }
    const typeSel = document.getElementById('filter-type');
    if (!typeSel.options.length && schemas.event_types) {
      typeSel.innerHTML = '<option value="">All types</option>'
        + Object.entries(schemas.event_types)
            .sort((a, b) => a[1].localeCompare(b[1]))
            .map(([code, label]) => `<option value="${code}">${esc(label)} (${code})</option>`).join('');
    }
  }

  async load() {
    try {
      const hw = await apiGet('/hardware');
      this.initFilters((hw.doors || []).filter(d => d.active));

      const params = { limit: 200 };
      const f = (id) => document.getElementById(id)?.value;
      if (f('filter-door')) params.door_id = f('filter-door');
      if (f('filter-type')) params.event_type = f('filter-type');
      if (f('filter-q')) params.q = f('filter-q');
      if (f('filter-from')) params.dt_from = f('filter-from') + ':00';
      if (f('filter-to')) params.dt_to = f('filter-to') + ':59';

      const data = await apiGet('/events', params);
      const tbody = document.getElementById('events-tbody');
      tbody.innerHTML = '';

      if (!data.events || !data.events.length) {
        tbody.innerHTML = '<tr><td colspan="8" class="text-center text-text-secondary">No events match the current filters</td></tr>';
        return;
      }

      for (const ev of data.events) {
        const tr = document.createElement('tr');
        const door = ev.door_id ? `Door ${ev.door_id}` : 'Device';
        const addBtn = (ev.event_type === 27 && ev.card_id)
          ? `<button class="btn secondary !px-2 !py-0.5 text-xs register-card-btn ml-2" data-card="${esc(ev.card_id)}">+ Register</button>`
          : '';
        tr.innerHTML = `
          <td class="whitespace-nowrap">${fmtDT(ev.timestamp)}</td>
          <td>${door}</td>
          <td>${esc(ev.card_id || 'N/A')}${addBtn}</td>
          <td class="font-medium">${ev.user_name ? esc(ev.user_name) : '<span class="text-text-secondary italic">—</span>'}</td>
          <td>${esc(ev.pin || '—')}</td>
          <td><span class="badge ${eventBadgeClass(ev.event_type)}">${esc(ev.description || 'Code: ' + ev.event_type)}</span></td>
          <td class="text-text-secondary">${esc(humanize(ev.verify_mode))}</td>
          <td class="text-text-secondary">${esc(ev.entry_exit || '—')}</td>
        `;
        tbody.appendChild(tr);
      }

      tbody.querySelectorAll('.register-card-btn').forEach(btn =>
        btn.addEventListener('click', () => {
          appNav.switchView('users');
          document.getElementById('new-user-card').value = btn.dataset.card;
          document.getElementById('new-user-pin').focus();
          showToast('Card prefilled from event — complete the form to register.', 'neutral');
        }));
    } catch (e) {
      console.error(e);
    }
  }
}

class UsersView {
  constructor() {
    document.getElementById('create-user-form')?.addEventListener('submit', (e) => {
      e.preventDefault();
      let mask = 0;
      document.querySelectorAll('#new-user-doors [data-door-bit]:checked').forEach(cb =>
        mask |= (1 << (parseInt(cb.dataset.doorBit, 10) - 1)));
      this.saveUser({
        name: document.getElementById('new-user-name').value,
        pin: document.getElementById('new-user-pin').value,
        card: document.getElementById('new-user-card').value,
        password: document.getElementById('new-user-password').value,
        group: document.getElementById('new-user-group').value,
        start_time: document.getElementById('new-user-start').value,
        end_time: document.getElementById('new-user-end').value,
        super_authorize: document.getElementById('new-user-admin').checked,
        doors: mask,
        timezone_id: 1,
      }, true);
    });
    document.getElementById('autofill-card-btn')?.addEventListener('click', () => this.autofillLatestCard());
    document.getElementById('refresh-users-btn')?.addEventListener('click', () => this.load());
  }

  async saveUser(fields, isNew = false, closeFn = null) {
    try {
      const data = await apiSend('/users', { body: fields });
      if (data.success) {
        showToast(`User ${fields.pin} ${isNew ? 'created' : 'updated'}!`, 'success');
        if (isNew) document.getElementById('create-user-form').reset();
        if (closeFn) closeFn();
        this.load();
      } else {
        showToast(`Failed: ${data.detail}`, 'error');
      }
    } catch (e) {
      showToast('System Error', 'error');
    }
  }

  async load() {
    try {
      const [data, hw] = await Promise.all([apiGet('/users'), apiGet('/hardware')]);
      this.hwDoors = (hw.doors || []).filter(d => d.active).map(d => d.door_id);

      // Populate door checkboxes of the create form once the door list is known
      const doorsHolder = document.getElementById('new-user-doors');
      if (doorsHolder && !doorsHolder.children.length) {
        doorsHolder.innerHTML = this.hwDoors.map(d => `
          <label class="flex items-center gap-1.5 text-sm cursor-pointer">
            <input type="checkbox" class="w-auto" data-door-bit="${d}">
            <span>Door ${d}</span>
          </label>`).join('');
      }

      const tbody = document.getElementById('users-tbody');
      tbody.innerHTML = '';

      if (!data.users || !data.users.length) {
        tbody.innerHTML = '<tr><td colspan="8" class="text-center text-text-secondary">No assigned users</td></tr>';
        return;
      }

      for (const u of data.users) {
        const validity = (u.start_time || u.end_time)
          ? `${esc((u.start_time || '?').slice(0, 10))} → ${esc((u.end_time || '?').slice(0, 10))}`
          : '<span class="text-text-secondary italic">Unlimited</span>';
        const badge = u.super_authorize
          ? '<span class="badge info">Admin</span>'
          : '<span class="badge">Standard</span>';
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td class="font-medium">${esc(u.name || '')}</td>
          <td>${esc(u.pin)}</td>
          <td>${esc(u.card || 'No Card')}</td>
          <td>${esc(u.group_id || 'Default')}</td>
          <td class="text-sm">${validity}</td>
          <td>${badge}</td>
          <td>${u.last_used ? fmtDT(u.last_used) : '<span class="text-text-secondary italic">Never</span>'}</td>
          <td class="flex gap-2">
            <button class="btn secondary edit-user-btn !px-3 !py-1.5 text-xs" data-pin="${esc(u.pin)}">Edit</button>
            <button class="btn delete-user-btn bg-danger text-white hover:bg-red-600 !px-3 !py-1.5 text-xs shadow-soft" data-pin="${esc(u.pin)}">Delete</button>
          </td>
        `;
        tbody.appendChild(tr);
      }

      tbody.querySelectorAll('.edit-user-btn').forEach(btn =>
        btn.addEventListener('click', () => {
          const u = data.users.find(x => String(x.pin) === btn.dataset.pin);
          if (u) this.openEditModal(u);
        }));
      tbody.querySelectorAll('.delete-user-btn').forEach(btn =>
        btn.addEventListener('click', () => this.deleteUser(btn.dataset.pin)));
    } catch (e) {
      console.error(e);
    }
  }

  async openEditModal(u) {
    // Current door access (UserAuthorize row) for this user, if any
    let auth = null;
    try {
      const res = await apiGet('/tables/UserAuthorize');
      if (res.success) auth = (res.rows || []).find(r => String(r.pin) === String(u.pin));
    } catch (e) { /* access table unreadable — proceed without it */ }

    const fields = [
      { name: 'name', label: 'Cardholder Name', type: 'str' },
      { name: 'card', label: 'Card Number', type: 'str' },
      { name: 'password', label: 'Keypad Password', type: 'password' },
      { name: 'group', label: 'Access Group', type: 'str' },
      { name: 'start_time', label: 'Valid From', type: 'date' },
      { name: 'end_time', label: 'Valid To', type: 'date' },
      { name: 'super_authorize', label: 'Admin Privileges', type: 'bool' },
      { name: 'doors', label: 'Allowed Doors', type: 'door_mask',
        help: 'Unchecking all doors revokes door access' },
      { name: 'timezone_id', label: 'Time Zone ID', type: 'int', min: 1, max: 50,
        help: 'Time during which this user may open the checked doors' },
    ];
    const html = fields.map(f => fieldInput(f, {
      name: u.name, card: u.card, password: u.password, group: u.group_id,
      start_time: (u.start_time || '').slice(0, 10),
      end_time: (u.end_time || '').slice(0, 10),
      super_authorize: !!u.super_authorize,
      doors: auth ? auth.doors : 0,
      timezone_id: auth ? auth.timezone_id : 1,
    }[f.name], { doors: this.hwDoors || [] })).join('');

    openModal(`Edit User ${u.pin}`, html, (content, close) => {
      const values = collectForm(content, fields);
      values.pin = u.pin;
      const hadAuth = !!auth;
      if (hadAuth && values.doors === 0) {
        // Revoking all access: drop the authorization row instead of upserting
        apiSend('/tables/UserAuthorize/row', { method: 'DELETE', body: { key: { pin: u.pin } } })
          .then(() => { values.doors = undefined; this.saveUser(values, false, close); });
        return;
      }
      this.saveUser(values, false, close);
    });
  }

  async deleteUser(pin) {
    if (!confirm(`Are you sure you want to delete user ${pin}?`)) return;
    try {
      const data = await apiSend(`/users/${pin}`, { method: 'DELETE' });
      showToast(data.success ? `User ${pin} deleted!` : `Failed: ${data.detail}`,
        data.success ? 'success' : 'error');
      if (data.success) this.load();
    } catch (e) {
      showToast(`Error: ${e.message}`, 'error');
    }
  }

  async autofillLatestCard() {
    try {
      const data = await apiGet('/events', { limit: 50 });
      const event = data.events?.find(ev => ev.card_id);
      if (event) {
        document.getElementById('new-user-card').value = event.card_id;
        showToast('Card ID Autofilled from latest swipe!', 'success');
      } else {
        showToast('No recent event contained a Card ID.', 'error');
      }
    } catch (e) {
      showToast('Error fetching events.', 'error');
    }
  }
}

class DoorsView {
  constructor() {
    document.getElementById('refresh-doors-btn')?.addEventListener('click', () => this.load());
    document.getElementById('cancel-alarm-btn')?.addEventListener('click', async () => {
      showToast('Cancelling alarm...', 'neutral');
      const data = await apiSend('/device/cancel-alarm');
      showToast(data.success ? 'Alarm cancelled.' : `Failed: ${data.detail}`,
        data.success ? 'success' : 'error');
    });
  }

  async load() {
    const container = document.getElementById('doors-config-container');
    container.innerHTML = '<p class="text-text-secondary col-span-full">Loading door parameters from device...</p>';
    try {
      const [hw, params] = await Promise.all([apiGet('/hardware'), apiGet('/doors/params')]);
      container.innerHTML = '';

      if (!params.success) {
        container.innerHTML = `<p class="text-danger col-span-full">Failed to read door params: ${esc(params.detail || 'unknown error')}</p>`;
        return;
      }

      const hwDoors = (hw.doors || []);
      for (const door of params.doors || []) {
        const did = door.door_id;
        const hwDoor = hwDoors.find(d => d.door_id === did) || {};
        const fields = schemas.door_params;
        const snapshot = door.params;

        const formHTML = fields.map(f => {
          const cur = snapshot[f.name];
          return fieldInput(f, f.type === 'select' || f.type === 'int' ? (cur ?? '') : cur);
        }).join('');

        const card = document.createElement('div');
        card.className = 'stat-card glass-panel border-l-4 border-l-accent';
        card.innerHTML = `
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-lg font-semibold">Door ${did}</h3>
            <span class="text-xs text-text-secondary">${esc(hwDoor.reader || '')}</span>
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">${formHTML}</div>
          <div class="flex gap-2 pt-4 mt-4 border-t border-white/5">
            <button class="btn primary save-door-btn w-full" data-door="${did}">Save Configuration</button>
          </div>
        `;
        container.appendChild(card);

        card.querySelector('.save-door-btn').addEventListener('click', () => this.save(card, did, fields, snapshot));
      }
    } catch (e) {
      console.error(e);
      container.innerHTML = '<p class="text-danger col-span-full">Failed to load doors.</p>';
    }
  }

  async save(card, doorId, fields, snapshot) {
    const values = collectForm(card, fields.concat());
    // bools must be captured even when unchanged-false
    for (const f of fields) {
      if (f.type === 'bool') {
        const el = card.querySelector(`[data-field="${f.name}"]`);
        values[f.name] = el ? el.checked : false;
      }
    }

    const changes = [];
    for (const f of fields) {
      const oldVal = snapshot[f.name];
      const newVal = values[f.name];
      if (newVal === undefined) continue;                // cleared → don't touch
      if (String(oldVal ?? '') === String(newVal)) continue;
      changes.push({ name: f.name, value: newVal });
    }

    if (!changes.length) {
      showToast(`Door ${doorId}: no changes to save.`, 'neutral');
      return;
    }

    showToast(`Saving ${changes.length} parameter(s) to Door ${doorId}...`, 'neutral');
    const failures = [];
    for (const change of changes) {
      try {
        const data = await apiSend(`/doors/${doorId}/param`, { body: change });
        if (!data.success) failures.push(`${change.name}: ${data.detail}`);
      } catch (e) {
        failures.push(`${change.name}: request failed`);
      }
    }

    if (failures.length) {
      showToast(`Saved ${changes.length - failures.length}/${changes.length}. Failed: ${failures.join('; ')}`, 'error');
    } else {
      showToast(`Door ${doorId} configuration saved!`, 'success');
    }
    this.load();
  }
}

class AccessView {
  constructor() {
    this.activeTable = null;
    document.getElementById('refresh-access-btn')?.addEventListener('click', () => this.load(this.activeTable));
  }

  async load(table) {
    const tabs = Object.keys(schemas.tables);
    const tabBar = document.getElementById('access-tabs');
    tabBar.innerHTML = '';
    for (const name of tabs) {
      const btn = document.createElement('button');
      btn.className = `tab ${name === (table || this.activeTable) ? 'active' : ''}`;
      btn.textContent = schemas.tables[name].label;
      btn.addEventListener('click', () => { this.activeTable = name; this.load(name); });
      tabBar.appendChild(btn);
    }

    this.activeTable = table || this.activeTable || tabs[0];
    tabBar.querySelectorAll('.tab').forEach(b =>
      b.classList.toggle('active', b.textContent === schemas.tables[this.activeTable].label));

    const content = document.getElementById('access-content');
    content.innerHTML = '<p class="text-text-secondary">Loading...</p>';
    try {
      const schema = schemas.tables[this.activeTable];
      if (schema.fields.some(f => f.type === 'door_mask') && !this.hwDoors) {
        const hw = await apiGet('/hardware');
        this.hwDoors = (hw.doors || []).filter(d => d.active).map(d => d.door_id);
      }
      const data = await apiGet(`/tables/${this.activeTable}`);

      if (!data.success) {
        content.innerHTML = `<p class="text-danger">Failed to read table: ${esc(data.detail || 'unknown error')}</p>`;
        return;
      }

      const rows = data.rows || [];
      let html = `
        <div class="flex justify-between items-center mb-4">
          <h3 class="text-xl font-semibold">${esc(schema.label)}</h3>
          <button class="btn primary !px-4 !py-2 text-sm" id="add-row-btn">+ Add</button>
        </div>`;

      if (!rows.length) {
        html += '<p class="text-text-secondary">Table is empty.</p>';
      } else {
        html += `<div class="w-full overflow-x-auto"><table class="w-full border-collapse text-sm">
          <thead><tr>${schema.fields.map(f => `<th>${esc(f.label)}</th>`).join('')}<th></th></tr></thead>
          <tbody>${rows.map((row, i) => `
            <tr>
              ${schema.fields.map(f => `<td>${this.renderCell(f, row[f.name])}</td>`).join('')}
              <td class="flex gap-2 justify-end">
                <button class="btn secondary !px-2 !py-1 text-xs edit-row-btn" data-idx="${i}">Edit</button>
                <button class="btn bg-danger text-white !px-2 !py-1 text-xs delete-row-btn" data-idx="${i}">Del</button>
              </td>
            </tr>`).join('')}</tbody></table></div>`;
      }
      content.innerHTML = html;

      content.querySelector('#add-row-btn').addEventListener('click', () => this.editRow(schema, {}));
      content.querySelectorAll('.edit-row-btn').forEach(btn =>
        btn.addEventListener('click', () => this.editRow(schema, rows[btn.dataset.idx])));
      content.querySelectorAll('.delete-row-btn').forEach(btn =>
        btn.addEventListener('click', () => this.deleteRow(schema, rows[btn.dataset.idx])));
    } catch (e) {
      console.error(e);
      content.innerHTML = '<p class="text-danger">Failed to load table.</p>';
    }
  }

  renderCell(f, value) {
    if (value === undefined || value === null || value === '') return '<span class="text-text-secondary italic">—</span>';
    if (f.type === 'door_mask') {
      const doors = [];
      for (const d of (this.hwDoors || [])) {
        if (parseInt(value, 10) & (1 << (d - 1))) doors.push(d);
      }
      return doors.length ? `Doors ${doors.join(', ')}` : '<span class="text-text-secondary italic">None</span>';
    }
    if (f.type === 'timerange' && Array.isArray(value)) {
      return `${toHHMM(value[0])} – ${toHHMM(value[1])}`;
    }
    if (f.type === 'select') {
      const hit = (f.choices || []).find(([v]) => String(v) === String(value));
      return esc(hit ? hit[1] : String(value));
    }
    if (f.type === 'bool') return value ? 'Yes' : 'No';
    return esc(String(value));
  }

  editRow(schema, row) {
    const ctx = { doors: this.hwDoors || [] };
    const html = schema.fields.map(f => {
      let value = row[f.name];
      if (f.type === 'int' || f.type === 'select') value = value ?? '';
      return fieldInput(f, value, ctx);
    }).join('');

    openModal(`${schema.label} — ${Object.keys(row).length ? 'Edit' : 'Add'}`, html, async (content, close) => {
      const fields = collectForm(content, schema.fields);
      try {
        const data = await apiSend(`/tables/${this.activeTable}`, { body: { data: fields } });
        if (data.success) {
          showToast('Row saved to device.', 'success');
          close();
          this.load(this.activeTable);
        } else {
          showToast(`Failed: ${data.detail}`, 'error');
        }
      } catch (e) {
        showToast('System Error', 'error');
      }
    });
  }

  async deleteRow(schema, row) {
    if (!confirm(`Delete this ${schema.label} row?`)) return;
    try {
      const data = await apiSend(`/tables/${this.activeTable}/row`, { method: 'DELETE', body: { key: row } });
      showToast(data.success ? 'Row deleted.' : `Failed: ${data.detail}`, data.success ? 'success' : 'error');
      if (data.success) this.load(this.activeTable);
    } catch (e) {
      showToast('System Error', 'error');
    }
  }
}

class DeviceView {
  constructor() {
    document.getElementById('refresh-device-btn')?.addEventListener('click', () => this.load());
    document.getElementById('search-devices-btn')?.addEventListener('click', () => this.search());
    document.getElementById('device-reboot-btn')?.addEventListener('click', async () => {
      if (!confirm('Are you sure you want to reboot the controller?')) return;
      showToast('Rebooting controller...', 'neutral');
      const data = await apiSend('/device/reboot');
      showToast(data.success ? 'Device rebooting.' : `Failed: ${data.detail}`,
        data.success ? 'success' : 'error');
    });
  }

  async load() {
    const container = document.getElementById('device-params-container');
    container.innerHTML = '<p class="text-text-secondary">Loading parameters from device...</p>';
    try {
      const data = await apiGet('/device/params');
      container.innerHTML = '';

      if (!data.success) {
        container.innerHTML = `<p class="text-danger">Failed to read parameters: ${esc(data.detail || 'unknown error')}</p>`;
        return;
      }

      const grid = document.createElement('div');
      grid.className = 'grid grid-cols-1 md:grid-cols-2 gap-x-12 gap-y-4';
      for (const spec of schemas.device_params) {
        const value = data.params?.[spec.name];
        const error = data.param_errors?.[spec.name];
        const row = document.createElement('div');
        row.className = 'flex items-end gap-3 py-2 border-b border-white/5';

        if (spec.editable === false || error) {
          row.innerHTML = `
            <div class="flex-1">
              <span class="text-sm text-text-secondary">${esc(spec.label)}</span>
              <div class="font-medium break-all">${error ? `<span class="text-danger text-xs">unreadable</span>` : esc(value ?? '—')}</div>
            </div>`;
        } else {
          row.innerHTML = `
            <div class="flex-1">${fieldInput(spec, spec.type === 'bool' ? !!value : (value ?? ''))}</div>
            <button class="btn secondary !px-3 !py-1.5 text-xs save-param-btn" data-name="${esc(spec.name)}">Set</button>`;
          row.querySelector('.save-param-btn').addEventListener('click', async () => {
            const el = row.querySelector(`[data-field="${spec.name}"]`);
            const value = spec.type === 'bool' ? el.checked : el.value;
            if (!confirm(`Set ${spec.label} to "${value}"?`)) return;
            try {
              const res = await apiSend('/device/param', { body: { name: spec.name, value } });
              showToast(res.success ? `${spec.label} updated.` : `Failed: ${res.detail}`,
                res.success ? 'success' : 'error');
            } catch (e) {
              showToast('System Error', 'error');
            }
          });
        }
        grid.appendChild(row);
      }
      container.appendChild(grid);
    } catch (e) {
      console.error(e);
      container.innerHTML = '<p class="text-danger">Failed to load device parameters.</p>';
    }
  }

  async search() {
    const panel = document.getElementById('search-results-panel');
    const tbody = document.getElementById('search-results-tbody');
    panel.classList.remove('hidden');
    tbody.innerHTML = '<tr><td colspan="5" class="text-text-secondary">Broadcasting search on the local segment (this can take a while)...</td></tr>';
    try {
      const data = await apiSend('/device/search');
      if (!data.success) {
        tbody.innerHTML = `<tr><td colspan="5" class="text-danger">Search failed: ${esc(data.detail)}</td></tr>`;
        return;
      }
      if (!data.devices?.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-text-secondary">No controllers answered the broadcast.</td></tr>';
        return;
      }
      tbody.innerHTML = data.devices.map(d => `
        <tr>
          <td class="font-medium">${esc(d.ip)}</td>
          <td>${esc(d.mac)}</td>
          <td>${esc(d.model)}</td>
          <td>${esc(d.serial_number)}</td>
          <td class="text-text-secondary text-sm">${esc(d.version)}</td>
        </tr>`).join('');
    } catch (e) {
      tbody.innerHTML = '<tr><td colspan="5" class="text-danger">Search request failed.</td></tr>';
    }
  }
}

// ============================================================
// Navigation & App state
// ============================================================

let schemas = null;
let currentView = 'dashboard';

const views = {
  dashboard: new DashboardView(),
  events: null,    // instantiated after DOM ready below
  users: null,
  doors: null,
  access: null,
  device: null,
};

class AppNavigation {
  constructor() {
    this.navItems = document.querySelectorAll('.nav-item');
    this.navItems.forEach(item => {
      item.addEventListener('click', (e) => {
        this.switchView(e.currentTarget.dataset.target);
      });
    });
  }

  switchView(targetId) {
    currentView = targetId;
    this.navItems.forEach(btn => btn.classList.remove('active'));
    document.querySelector(`[data-target="${targetId}"]`)?.classList.add('active');

    document.querySelectorAll('.view-section').forEach(sec => {
      sec.classList.remove('active');
      sec.classList.add('hidden');
    });
    const activeSection = document.getElementById(targetId);
    activeSection.classList.remove('hidden');
    void activeSection.offsetWidth; // Force reflow
    activeSection.classList.add('active');

    views[targetId]?.load();
  }
}

// Global actions from dashboard header
function bindGlobalActions() {
  document.getElementById('refresh-hardware-btn')?.addEventListener('click', () => views.dashboard.load());
  document.getElementById('sync-time-btn')?.addEventListener('click', async () => {
    showToast('Syncing device time...', 'neutral');
    const data = await apiSend('/device/sync-time');
    showToast(data.success ? 'Device time synchronized!' : `Failed: ${data.detail}`,
      data.success ? 'success' : 'error');
  });
  document.getElementById('reboot-btn')?.addEventListener('click', async () => {
    if (!confirm('Are you sure you want to reboot the controller? This will take it offline for a few moments!')) return;
    showToast('Rebooting controller...', 'neutral');
    const data = await apiSend('/device/reboot');
    showToast(data.success ? 'Device rebooting.' : `Failed: ${data.detail}`,
      data.success ? 'success' : 'error');
  });
  document.getElementById('modal-close-btn')?.addEventListener('click', closeModal);
  document.getElementById('modal-overlay')?.addEventListener('click', (e) => {
    if (e.target.id === 'modal-overlay') closeModal();
  });
}

// Init
let appNav;
(async function boot() {
  try {
    schemas = await apiGet('/schemas');
  } catch (e) {
    console.error('Failed to load schemas', e);
    schemas = { tables: {}, door_params: [], device_params: [], event_types: {} };
  }

  views.events = new EventsView();
  views.users = new UsersView();
  views.doors = new DoorsView();
  views.access = new AccessView();
  views.device = new DeviceView();

  appNav = new AppNavigation();
  bindGlobalActions();
  views.dashboard.load();

  // Periodic refresh of the visible view only
  setInterval(() => views[currentView]?.load(), 15000);
})();
