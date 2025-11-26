# app.py - Vamsy + ChatGPT full merged version (dark history fixed)
from flask import Flask, render_template_string, request, redirect, url_for, make_response
import sqlite3, os, socket, traceback, sys, csv, io
from datetime import datetime, timedelta

DB_PATH = "devices.db"
LOG_FILE = "logs.csv"
REFRESH_MS = 30000  # 30 seconds
app = Flask(__name__)

# ---------- discover host IPs (for owner-only actions) ----------
def discover_local_ips():
    ips = set(["127.0.0.1", "::1"])
    try:
        hn_ip = socket.gethostbyname(socket.gethostname())
        if hn_ip:
            ips.add(hn_ip)
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return ips

ALLOWED_HOST_IPS = discover_local_ips()
print("Allowed host IPs:", ALLOWED_HOST_IPS)

def is_request_from_host():
    ip = request.remote_addr
    return ip in ALLOWED_HOST_IPS

# ---------- helper formatting ----------
def format_eta_display(eta_str):
    try:
        dt = datetime.fromisoformat(eta_str)
        return dt.strftime("%d-%m-%Y %I:%M %p")
    except Exception:
        return eta_str or "-"

def compute_duration(start_str, end_str):
    """duration like '2h 10m' or '15m' or '-'"""
    if not start_str or not end_str:
        return "-"
    try:
        st = datetime.fromisoformat(start_str)
        et = datetime.fromisoformat(end_str)
        delta = et - st
        total_minutes = int(delta.total_seconds() // 60)
        if total_minutes < 0:
            return "-"
        hours = total_minutes // 60
        minutes = total_minutes % 60
        if hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"
    except Exception:
        return "-"

# ---------- export logs to CSV (per-day serial + partition rows) ----------
def export_logs_to_file():
    """
    Writes logs to LOG_FILE as CSV with:
      date, serial (resets each day), device_id, device_name, user,
      start_time, end_time, duration, status
    and blank row between days.
    """
    try:
        conn = get_db()
        rows = conn.execute("""
            SELECT l.id,
                   l.device_id,
                   d.name AS device_name,
                   l.user,
                   l.start_time,
                   l.end_time
            FROM logs l
            JOIN devices d ON d.id = l.device_id
            ORDER BY date(l.start_time) ASC, l.start_time ASC, l.id ASC
        """).fetchall()
        conn.close()

        with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "date", "serial", "device_id", "device_name",
                "user", "start_time", "end_time", "duration", "status"
            ])

            current_date = None
            serial = 0

            for r in rows:
                start_str = r["start_time"]
                end_str = r["end_time"]

                # parse start datetime
                try:
                    st_dt = datetime.fromisoformat(start_str)
                    date_str = st_dt.strftime("%Y-%m-%d")
                    start_time_str = st_dt.strftime("%H:%M")
                except Exception:
                    date_str = ""
                    start_time_str = ""

                if end_str:
                    try:
                        et_dt = datetime.fromisoformat(end_str)
                        end_time_str = et_dt.strftime("%H:%M")
                    except Exception:
                        end_time_str = ""
                    status = "Completed"
                else:
                    end_time_str = ""
                    status = "Ongoing"

                duration = compute_duration(start_str, end_str)

                # new date group
                if date_str != current_date:
                    if current_date is not None:
                        writer.writerow([])  # partition row
                    current_date = date_str
                    serial = 1
                else:
                    serial += 1

                writer.writerow([
                    date_str,
                    serial,
                    r["device_id"],
                    r["device_name"],
                    r["user"],
                    start_time_str,
                    end_time_str,
                    duration,
                    status
                ])

        print(f"[LOG EXPORT] Logs written to {LOG_FILE}")
    except Exception as e:
        print("[LOG EXPORT] Failed to export logs:", e)
        traceback.print_exc()

# ---------- HTML TEMPLATE ----------
TEMPLATE = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Device Availability Dashboard</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">

  <style>
    /* ---------- theme variables ---------- */
    :root{
      --bg: linear-gradient(135deg,#4285F4 0%,#EA4335 25%,#FBBC05 50%,#34A853 75%,#4285F4 100%);
      --card-bg: rgba(255,255,255,0.96);
      --text: #0f172a;
      --muted: #475569;
      --panel: #d1fae5;
      --panel-red: #fee2e2;
      --thead-bg: #0f172a;
      --thead-color: #f8fafc;
      --accent: #111827;
      --shadow: rgba(0,0,0,0.35);
      --button-bg: #111827;
      --button-color: #fff;
    }

    html[data-theme="dark"]{
      --bg: linear-gradient(135deg,#0f172a 0%, #0b3d91 40%, #07172a 100%);
      --card-bg: rgba(6,10,24,0.92);
      --text: #e6eef8;
      --muted: #a8b3c6;
      --panel: rgba(16,64,48,0.25);
      --panel-red: rgba(139, 30, 40, 0.12);
      --thead-bg: #071028;
      --thead-color: #e6eef8;
      --accent: #9cc3ff;
      --shadow: rgba(0,0,0,0.7);
      --button-bg: #e6eef8;
      --button-color: #071028;
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial;
      font-weight: 700;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      display: flex;
      align-items: flex-start;
      justify-content: center;
      padding: 16px;
    }

    .container {
      width: 95vw;
      max-width: 2000px;
      background: var(--card-bg);
      border-radius: 26px;
      padding: 28px 32px 32px;
      box-shadow: 0 25px 45px var(--shadow);
      backdrop-filter: blur(8px);
      display: flex;
      flex-direction: column;
    }

    .header { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:12px; gap:12px; }
    h2 { margin:0; font-size:28px; color:var(--text); }
    .subtitle { font-size:12px; color:var(--muted); font-weight:700; }

    .controls { display:flex; gap:12px; align-items:center; }
    .btn-action {
      padding:8px 14px; border-radius:999px; border:none; cursor:pointer; font-weight:800; text-transform:uppercase;
      background:var(--button-bg); color:var(--button-color);
      box-shadow: 0 6px 12px rgba(0,0,0,0.12);
      font-size:12px;
      white-space:nowrap;
    }

    .table-wrapper {
      margin-top: 8px;
      border-radius: 8px;
    }

    table { width:100%; border-collapse:collapse; font-size:14px; }
    thead th {
      position: sticky; top:0;
      background: var(--thead-bg); color: var(--thead-color); padding:12px 10px; text-align:left;
      z-index:2; border-bottom:3px solid var(--thead-bg);
    }
    th, td { padding:8px 10px; vertical-align:middle; font-weight:700; }
    tbody tr { transition: transform 160ms cubic-bezier(.2,.9,.2,1), box-shadow 160ms cubic-bezier(.2,.9,.2,1); transform-origin:center; position:relative; z-index:0; }
    tbody tr:hover, tbody tr.row-popped, tbody tr:focus-within {
      transform: translateY(-4px) scale(1.01);
      box-shadow: 0 12px 22px rgba(15,23,42,0.12);
      z-index:3;
    }

    .status-available { background: var(--panel); }
    .status-inuse, .status-maintenance { background: var(--panel-red); }

    .tag { display:inline-block; padding:3px 8px; border-radius:999px; font-size:10px; text-transform:uppercase; letter-spacing:.03em; }
    .status-available .tag { background:#16a34a; color:#052e16; }
    .status-inuse .tag { background:#ef4444; color:#fff; }

    .eta-badge { display:inline-block; padding:4px 8px; border-radius:999px; font-size:11px; font-weight:800; color:#fff; }
    .eta-active { background:#10b981; }
    .eta-passed { background:#ef4444; }
    .eta-none { background:#9ca3af; }

    .btn { padding:5px 10px; border-radius:999px; border:none; cursor:pointer; font-size:11px; font-weight:800; text-transform:uppercase; white-space:nowrap; }
    .btn-lock { background:#2563eb; color:#fff; }
    .btn-unlock { background:#16a34a; color:#fff; }
    .btn-edit { background:#f59e0b; color:#fff; }
    .btn-delete { background:#ef4444; color:#fff; }
    .btn-small { padding:4px 8px; font-size:10px; border-radius:8px; }

    form.inline {
      display:inline-flex;
      align-items:center;
      gap:6px;
      flex-wrap:nowrap;
      white-space:nowrap;
    }

    input[type="text"], input[type="datetime-local"], input[type="date"] {
      border-radius:999px; border:1px solid #d1d5db; padding:4px 8px; font-size:11px; font-weight:700;
    }
    input[type="text"] { max-width:110px; }
    input[type="datetime-local"] { background:#fff; max-width:170px; }

    html[data-theme="dark"] input[type="text"],
    html[data-theme="dark"] input[type="datetime-local"],
    html[data-theme="dark"] input[type="date"] {
      background: rgba(255,255,255,0.03);
      border-color: rgba(255,255,255,0.06);
      color: var(--text);
    }

    .user-name-display {
      text-transform: uppercase;
      font-size: 14px;
      font-weight: 900;
      letter-spacing: 0.5px;
      color: var(--text);
    }

    .action-group {
      display:flex;
      align-items:center;
      gap:6px;
      flex-wrap:nowrap;
      white-space:nowrap;
    }

    /* modals */
    .modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.45); display:none; align-items:center; justify-content:center; z-index:9999; }
    .modal { background:#fff; border-radius:12px; padding:18px; width:480px; max-width:96%; box-shadow: 0 12px 30px rgba(0,0,0,0.35); text-align:center; font-weight:700; }
    .modal h3 { margin:0 0 8px 0; font-size:18px; color:#0f172a; }
    .modal p { margin:0 0 16px 0; font-size:14px; color:#475569; font-weight:700; }
    .modal .actions { display:flex; gap:10px; justify-content:center; margin-top:12px; }
    .modal .actions button { padding:8px 14px; border-radius:999px; border:none; cursor:pointer; font-weight:800; text-transform:uppercase; font-size:12px; }
    .btn-yes { background:#16a34a; color:#fff; }
    .btn-no { background:#ef4444; color:#fff; }

    .modal form input[type="text"] { width:100%; border-radius:8px; padding:10px; font-weight:700; }

    .time-display { margin-left:8px; font-weight:800; font-size:11px; color:var(--text); }

    /* History section */
    .history-section { margin-top:22px; }
    .history-header-row {
      display:flex;
      justify-content:space-between;
      align-items:center;
      gap:12px;
      flex-wrap:wrap;
    }
    .history-title { margin:0 0 4px 0; font-size:18px; color:var(--text); }
    .history-note { font-size:12px; color:var(--muted); font-weight:700; margin-bottom:4px; }

    .download-form {
      display:flex;
      align-items:center;
      gap:8px;
      flex-wrap:wrap;
      font-size:11px;
    }
    .download-form label { display:flex; align-items:center; gap:4px; }
    .btn-download {
      padding:6px 12px;
      border-radius:999px;
      border:none;
      cursor:pointer;
      font-size:11px;
      font-weight:800;
      text-transform:uppercase;
      background:var(--button-bg);
      color:var(--button-color);
      box-shadow:0 4px 10px rgba(0,0,0,0.18);
      white-space:nowrap;
    }

    .history-table-wrapper { margin-top:8px; border-radius:8px; }

    /* use theme colours for history header */
    .history-table thead th {
      background: var(--thead-bg);
      color: var(--thead-color);
    }

    /* light-mode history row highlights */
    .history-table tbody tr.log-ongoing {
      background:#d1fae5;
    }
    .history-table tbody tr.log-ended {
      background:#fee2e2;
    }

    /* darker, glowing rows in dark theme for better sync with top table */
    html[data-theme="dark"] .history-table tbody tr.log-ongoing {
      background: rgba(16,185,129,0.28);
    }
    html[data-theme="dark"] .history-table tbody tr.log-ended {
      background: rgba(248,113,113,0.30);
    }

    @media (max-width: 820px) {
      .container { padding:14px; width:100vw; }
      table { font-size:12px; }
      th, td { padding:6px; }
      input[type="text"] { max-width:80px; }
      input[type="datetime-local"] { max-width:140px; }
    }
  </style>

  <!-- Theme + auto refresh -->
  <script>
    (function(){
      const saved = localStorage.getItem('dashboard_theme');
      if (saved) {
        document.documentElement.setAttribute('data-theme', saved);
      } else {
        const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
        document.documentElement.setAttribute('data-theme', prefersDark ? 'dark' : 'light');
      }
    })();

    function toggleTheme() {
      const cur = document.documentElement.getAttribute('data-theme') || 'light';
      const next = cur === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('dashboard_theme', next);
      const btn = document.getElementById('themeToggleBtn');
      if (btn) btn.textContent = next === 'dark' ? 'Dark' : 'Light';
    }

    let refreshInterval = null;
    function startAutoRefresh() {
      if (refreshInterval) return;
      refreshInterval = setInterval(() => { window.location.reload(); }, {{ refresh_ms }});
    }
    function stopAutoRefresh() {
      if (!refreshInterval) return;
      clearInterval(refreshInterval);
      return refreshInterval = null;
    }
  </script>

  <!-- Datetime limits + AM/PM label -->
  <script>
    function formatAMPM(date) {
      const pad = n => (n < 10 ? '0' + n : n);
      let hours = date.getHours();
      const minutes = pad(date.getMinutes());
      const ampm = hours >= 12 ? 'PM' : 'AM';
      hours = hours % 12;
      if (hours === 0) hours = 12;
      return hours + ':' + minutes + ' ' + ampm;
    }

    function updateTimeLabelForInput(inp) {
      let label = inp.nextElementSibling;
      if (!label || !label.classList || !label.classList.contains('time-display')) {
        label = document.createElement('span');
        label.className = 'time-display';
        inp.parentNode.insertBefore(label, inp.nextSibling);
      }
      if (inp.value) {
        const d = new Date(inp.value);
        if (!isNaN(d.getTime())) label.textContent = formatAMPM(d);
        else label.textContent = '';
      } else {
        label.textContent = '';
      }
    }

    function setDateTimeLimits() {
      const inputs = document.querySelectorAll('input[type="datetime-local"]');
      if (!inputs.length) return;

      const now = new Date();
      now.setSeconds(0,0);
      const max = new Date(now.getTime() + 30 * 24 * 60 * 60 * 1000);
      function fmtLocal(d) {
        const pad = n => n < 10 ? '0'+n : n;
        return d.getFullYear() + '-' + pad(d.getMonth()+1) + '-' + pad(d.getDate()) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
      }
      const minStr = fmtLocal(now);
      const maxStr = fmtLocal(max);

      inputs.forEach(inp => {
        inp.setAttribute('min', minStr);
        inp.setAttribute('max', maxStr);
        inp.setAttribute('step', '60');
        if (!inp.value) inp.value = minStr;
        updateTimeLabelForInput(inp);
        inp.addEventListener('input', function(){ updateTimeLabelForInput(inp); });
      });
    }
  </script>

  <!-- Main JS: modals, CRUD, theme button, host controls -->
  <script>
    document.addEventListener('DOMContentLoaded', function () {
      setDateTimeLimits();
      startAutoRefresh();

      const confirmModal = document.getElementById('confirmModal');
      const modalTitle = document.getElementById('modalTitle');
      const modalMessage = document.getElementById('modalMessage');
      const modalYes = document.getElementById('modalYes');
      const modalNo = document.getElementById('modalNo');

      const deviceModal = document.getElementById('deviceModal');
      const deviceForm = document.getElementById('deviceForm');
      const deviceNameInput = document.getElementById('deviceName');
      const deviceActionInput = document.getElementById('deviceAction');
      const deviceIdInput = document.getElementById('deviceId');
      const deviceClose = document.getElementById('deviceClose');
      const addDeviceBtn = document.getElementById('addDeviceBtn');
      const recoverBtn = document.getElementById('recoverBtn');

      const deleteModal = document.getElementById('deleteModal');
      const deleteYes = document.getElementById('deleteYes');
      const deleteNo = document.getElementById('deleteNo');
      let deleteTargetId = null;

      let pendingUnlockForm = null;

      function openConfirm(title, message, onYes) {
        modalTitle.textContent = title;
        modalMessage.textContent = message;
        confirmModal.style.display = 'flex';
        stopAutoRefresh();
        modalYes.onclick = function(){ confirmModal.style.display='none'; startAutoRefresh(); onYes && onYes(); };
        modalNo.onclick = function(){ confirmModal.style.display='none'; startAutoRefresh(); };
      }

      function showDeviceModal(action, id, name) {
        deviceActionInput.value = action;
        deviceIdInput.value = id || '';
        deviceNameInput.value = name || '';
        deviceModal.style.display = 'flex';
        stopAutoRefresh();
        deviceNameInput.focus();
      }
      function closeDeviceModal() {
        deviceModal.style.display = 'none';
        startAutoRefresh();
      }

      function openDeleteConfirm(id, name) {
        deleteTargetId = id;
        document.getElementById('deleteMessage').textContent = `Delete "${name}"? This cannot be undone.`;
        deleteModal.style.display = 'flex';
        stopAutoRefresh();
      }
      function closeDeleteConfirm() {
        deleteModal.style.display = 'none';
        deleteTargetId = null;
        startAutoRefresh();
      }

      if (addDeviceBtn) {
        addDeviceBtn.addEventListener('click', function(){
          showDeviceModal('add', '', '');
        });
      }

      if (recoverBtn) {
        recoverBtn.addEventListener('click', function(){
          const f = document.createElement('form');
          f.method = 'POST'; f.action = '{{ url_for("recover") }}';
          document.body.appendChild(f); f.submit();
        });
      }

      deviceClose.addEventListener('click', closeDeviceModal);

      deviceForm.addEventListener('submit', function(e){
        e.preventDefault();
        const action = deviceActionInput.value;
        const id = deviceIdInput.value;
        const name = deviceNameInput.value.trim();
        if (!name) return;
        if (action === 'add') {
          const f = document.createElement('form');
          f.method = 'POST'; f.action = '{{ url_for("add_device") }}';
          const ni = document.createElement('input'); ni.name = 'name'; ni.value = name; f.appendChild(ni);
          document.body.appendChild(f); f.submit();
        } else if (action === 'edit') {
          const f = document.createElement('form');
          f.method = 'POST'; f.action = '{{ url_for("edit_device", device_id=0) }}'.replace('0', id);
          const ni = document.createElement('input'); ni.name = 'name'; ni.value = name; f.appendChild(ni);
          document.body.appendChild(f); f.submit();
        }
      });

      deleteYes.addEventListener('click', function(){
        if (!deleteTargetId) return closeDeleteConfirm();
        const f = document.createElement('form');
        f.method = 'POST'; f.action = '{{ url_for("delete_device", device_id=0) }}'.replace('0', deleteTargetId);
        document.body.appendChild(f); f.submit();
      });
      deleteNo.addEventListener('click', closeDeleteConfirm);

      document.addEventListener('submit', function (ev) {
        const form = ev.target;
        if (form.classList && form.classList.contains('unlock-form')) {
          ev.preventDefault();
          const row = form.closest('tr');
          pendingUnlockForm = form;
          const deviceId = row.getAttribute('data-id') || '?';
          const etaStatus = row.getAttribute('data-eta-status') || '';
          if (etaStatus === 'Passed') {
            openConfirm('ETA Passed — Confirm Unlock', `Device ${deviceId} has reached its ETA. Unlock now?`, function(){
              pendingUnlockForm.submit();
            });
          } else {
            openConfirm('Release Device', `Do you want to release Device ${deviceId}?`, function(){
              pendingUnlockForm.submit();
            });
          }
        }
      });

      document.addEventListener('click', function(e){
        const el = e.target;
        if (el.matches('[data-edit-id], [data-edit-id] *')) {
          const btn = el.closest('[data-edit-id]');
          const id = btn.getAttribute('data-edit-id');
          const name = btn.getAttribute('data-edit-name') || '';
          showDeviceModal('edit', id, name);
          e.preventDefault();
          return;
        }
        if (el.matches('[data-delete-id], [data-delete-id] *')) {
          const btn = el.closest('[data-delete-id]');
          const id = btn.getAttribute('data-delete-id');
          const name = btn.getAttribute('data-delete-name') || '';
          const row = btn.closest('tr');
          const status = row ? row.getAttribute('data-status') : null;
          if (status === 'In Use') {
            alert('Cannot delete device while it is locked (In Use). Release/unlock first.');
            e.preventDefault();
            return;
          }
          openDeleteConfirm(id, name);
          e.preventDefault();
          return;
        }
        if (el.id === 'themeToggleBtn' || (el.closest && el.closest('#themeToggleBtn'))) {
          toggleTheme();
        }
      });

      [deviceModal, confirmModal, deleteModal].forEach(md => {
        md.addEventListener('click', function(ev){
          if (ev.target === md) {
            md.style.display = 'none';
            startAutoRefresh();
          }
        });
      });

      document.addEventListener('keydown', function(e){
        if (e.key === 'Escape') {
          [deviceModal, confirmModal, deleteModal].forEach(md => { if (md.style.display === 'flex') md.style.display = 'none'; });
          startAutoRefresh();
        }
      });

      const rows = document.querySelectorAll('tbody tr');
      rows.forEach(r => {
        r.addEventListener('touchstart', function () {
          rows.forEach(rr => rr.classList.remove('row-popped'));
          r.classList.add('row-popped');
        }, {passive:true});
        r.addEventListener('touchend', function () {
          setTimeout(() => r.classList.remove('row-popped'), 700);
        });
      });

      const tableWrapper = document.querySelector('.table-wrapper');
      if (tableWrapper) {
        tableWrapper.addEventListener('scroll', function () {
          rows.forEach(rr => rr.classList.remove('row-popped'));
        }, {passive:true});
      }

      const tbtn = document.getElementById('themeToggleBtn');
      if (tbtn) {
        const cur = document.documentElement.getAttribute('data-theme') || 'light';
        tbtn.textContent = cur === 'dark' ? 'Dark' : 'Light';
      }
    });
  </script>

</head>
<body>
  <div class="container">
    <div class="header">
      <div>
        <h2>Device Availability</h2>
        <div class="subtitle">Green = Available, Red = In Use</div>
      </div>

      <div class="controls">
        <button id="addDeviceBtn" class="btn-action">ADD DEVICE</button>
        {% if is_host %}
        <button id="recoverBtn" class="btn-action" title="Recover missing devices">RECOVER ID</button>
        {% endif %}
        <button id="themeToggleBtn" class="btn-action" title="Toggle theme">Theme</button>
      </div>
    </div>

    <!-- DEVICE TABLE -->
    <div class="table-wrapper" role="region" aria-label="Device list">
      <table>
        <thead>
          <tr>
            <th style="width:48px">ID</th>
            <th>Device Name</th>
            <th>Status</th>
            <th>Current User</th>
            <th>ETA</th>
            <th>ETA Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {% for d in devices %}
          <tr
            data-id="{{ d['id'] }}"
            data-status="{{ d['status'] }}"
            data-user="{{ d['current_user'] or '' }}"
            data-eta="{{ d['eta'] or '' }}"
            data-eta-status="{{ d.get('eta_status','') }}"
            class="status-{{ d['status']|lower|replace(' ', '') }}">
            <td>{{ d['id'] }}</td>
            <td>{{ d['name'] }}</td>
            <td><span class="tag">{{ d['status'] }}</span></td>
            <td class="user-name-display">{{ d['current_user'] or '-' }}</td>
            <td>{{ d['eta_display'] }}</td>
            <td>
              {% if d.get('eta_status') == 'Passed' %}
                <span class="eta-badge eta-passed">PASSED</span>
              {% elif d.get('eta_status') == 'Active' %}
                <span class="eta-badge eta-active">ACTIVE</span>
              {% else %}
                <span class="eta-badge eta-none">-</span>
              {% endif %}
            </td>
            <td>
              <div class="action-group">
                {% if d['status'] == 'Available' %}
                  <form class="inline" method="post" action="{{ url_for('lock_device', device_id=d['id']) }}">
                    <input type="text" name="user" placeholder="Your name" required>
                    <input class="eta-input" type="datetime-local" name="eta" required>
                    <button type="submit" class="btn btn-lock">Lock</button>
                  </form>
                {% else %}
                  <form class="unlock-form inline" method="post" action="{{ url_for('unlock_device', device_id=d['id']) }}">
                    <button type="submit" class="btn btn-unlock">Unlock</button>
                  </form>
                {% endif %}

                {% if is_host %}
                  <button class="btn btn-edit btn-small" data-edit-id="{{ d['id'] }}" data-edit-name="{{ d['name'] }}">Edit</button>
                  <button class="btn btn-delete btn-small" data-delete-id="{{ d['id'] }}" data-delete-name="{{ d['name'] }}">Delete</button>
                {% endif %}
              </div>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>

    <!-- USAGE HISTORY -->
    <div class="history-section">
      <div class="history-header-row">
        <div>
          <h3 class="history-title">Recent Usage History</h3>
          <div class="history-note">Green = Ongoing (still using), Red = Completed usage</div>
        </div>

        <form class="download-form" method="get" action="{{ url_for('download_logs') }}">
          <label>
            From
            <input type="date" name="start_date" max="{{ today }}">
          </label>
          <label>
            To
            <input type="date" name="end_date" max="{{ today }}">
          </label>
          <button type="submit" class="btn-download">Download Logs</button>
        </form>
      </div>

      <div class="history-table-wrapper" role="region" aria-label="Usage history">
        <table class="history-table">
          <thead>
            <tr>
              <th style="width:48px">ID</th>
              <th>Device Name</th>
              <th>User</th>
              <th>From</th>
              <th>To</th>
              <th>Duration</th>
            </tr>
          </thead>
          <tbody>
            {% if logs %}
              {% for log in logs %}
              <tr class="{% if log['is_ongoing'] %}log-ongoing{% else %}log-ended{% endif %}">
                <td>{{ log['device_id'] }}</td>
                <td>{{ log['device_name'] }}</td>
                <td>{{ log['user'] }}</td>
                <td>{{ log['start_display'] }}</td>
                <td>{{ log['end_display'] }}</td>
                <td>{{ log['duration'] }}</td>
              </tr>
              {% endfor %}
            {% else %}
              <tr>
                <td colspan="6">No usage history yet. Lock a device to start logging.</td>
              </tr>
            {% endif %}
          </tbody>
        </table>
      </div>
    </div>

  </div>

  <!-- Confirm modal -->
  <div id="confirmModal" class="modal-backdrop" aria-hidden="true" role="dialog" aria-modal="true">
    <div class="modal" role="document">
      <h3 id="modalTitle">Confirm</h3>
      <p id="modalMessage">Are you sure?</p>
      <div class="actions">
        <button id="modalYes" class="btn-yes">Yes</button>
        <button id="modalNo" class="btn-no">No</button>
      </div>
    </div>
  </div>

  <!-- Device modal -->
  <div id="deviceModal" class="modal-backdrop" style="display:none;">
    <div class="modal">
      <h3 id="deviceModalTitle">Device</h3>
      <form id="deviceForm">
        <input type="hidden" id="deviceAction" name="action" value="add">
        <input type="hidden" id="deviceId" name="device_id" value="">
        <input type="text" id="deviceName" name="name" placeholder="Device name" required>
        <div class="actions">
          <button type="submit" class="btn-yes">Save</button>
          <button type="button" id="deviceClose" class="btn-no">Cancel</button>
        </div>
      </form>
    </div>
  </div>

  <!-- Delete confirm -->
  <div id="deleteModal" class="modal-backdrop" style="display:none;">
    <div class="modal">
      <h3>Delete Device</h3>
      <p id="deleteMessage">Are you sure?</p>
      <div class="actions">
        <button id="deleteYes" class="btn-yes">Delete</button>
        <button id="deleteNo" class="btn-no">Cancel</button>
      </div>
    </div>
  </div>

</body>
</html>
"""

# ---------- DB helpers ----------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    create = not os.path.exists(DB_PATH)
    conn = get_db()
    if create:
        conn.execute("""
            CREATE TABLE devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Available',
                current_user TEXT,
                eta TEXT
            )
        """)
        for i in range(1, 16):
            conn.execute("INSERT INTO devices (name) VALUES (?)", (f"Device {i}",))
        conn.commit()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id INTEGER NOT NULL,
            user TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT,
            FOREIGN KEY(device_id) REFERENCES devices(id)
        )
    """)
    conn.commit()
    conn.close()

    export_logs_to_file()

def find_smallest_missing_id(conn):
    cur = conn.execute("SELECT id FROM devices ORDER BY id")
    rows = cur.fetchall()
    expect = 1
    for r in rows:
        try:
            i = int(r["id"])
        except Exception:
            continue
        if i == expect:
            expect += 1
        elif i > expect:
            return expect
    return expect

def get_max_id(conn):
    cur = conn.execute("SELECT MAX(id) as m FROM devices")
    r = cur.fetchone()
    return r["m"] or 0

# ---------- routes ----------
@app.route("/")
def index():
    conn = get_db()
    cur = conn.execute("SELECT id, name, status, current_user, eta FROM devices ORDER BY id")
    rows = cur.fetchall()

    log_rows = conn.execute("""
        SELECT l.id, l.device_id, d.name AS device_name,
               l.user, l.start_time, l.end_time
        FROM logs l
        JOIN devices d ON d.id = l.device_id
        ORDER BY l.id DESC
        LIMIT 50
    """).fetchall()
    conn.close()

    devices = []
    now = datetime.now()
    for r in rows:
        d = dict(r)
        eta_status = ''
        if d['status'] == 'In Use' and d.get('eta'):
            try:
                eta_dt = datetime.fromisoformat(d['eta'])
                eta_status = 'Passed' if eta_dt <= now else 'Active'
            except Exception:
                eta_status = ''
        d['eta_status'] = eta_status
        d['eta_display'] = format_eta_display(d['eta']) if d.get('eta') else '-'
        devices.append(d)

    logs = []
    for r in log_rows:
        l = dict(r)
        l['start_display'] = format_eta_display(l['start_time'])
        if l.get('end_time'):
            l['end_display'] = format_eta_display(l['end_time'])
            l['duration'] = compute_duration(l['start_time'], l['end_time'])
            l['is_ongoing'] = False
        else:
            l['end_display'] = "Ongoing"
            l['duration'] = "-"
            l['is_ongoing'] = True
        logs.append(l)

    today = datetime.now().date().isoformat()
    host_flag = is_request_from_host()
    return render_template_string(
        TEMPLATE,
        devices=devices,
        logs=logs,
        refresh_ms=REFRESH_MS,
        today=today,
        is_host=host_flag
    )

@app.route("/lock/<int:device_id>", methods=["POST"])
def lock_device(device_id):
    user = request.form.get('user', '').strip().upper()
    eta = request.form.get('eta', '').strip()
    if not user or not eta:
        return redirect(url_for('index'))

    try:
        eta_dt = datetime.fromisoformat(eta)
    except Exception:
        return redirect(url_for('index'))
    now = datetime.now()
    max_allowed = now + timedelta(days=30)
    if eta_dt < now or eta_dt > max_allowed:
        return redirect(url_for('index'))

    conn = get_db()
    conn.execute("UPDATE devices SET status='In Use', current_user=?, eta=? WHERE id=?",
                 (user, eta, device_id))
    conn.execute(
        "INSERT INTO logs (device_id, user, start_time) VALUES (?, ?, ?)",
        (device_id, user, now.isoformat(timespec='minutes'))
    )
    conn.commit()
    conn.close()

    export_logs_to_file()
    return redirect(url_for('index'))

@app.route("/unlock/<int:device_id>", methods=["POST"])
def unlock_device(device_id):
    now = datetime.now()
    conn = get_db()
    conn.execute("UPDATE devices SET status='Available', current_user=NULL, eta=NULL WHERE id=?",
                 (device_id,))
    conn.execute("""
        UPDATE logs
        SET end_time = ?
        WHERE id = (
            SELECT id FROM logs
            WHERE device_id = ? AND end_time IS NULL
            ORDER BY id DESC
            LIMIT 1
        )
    """, (now.isoformat(timespec='minutes'), device_id))
    conn.commit()
    conn.close()

    export_logs_to_file()
    return redirect(url_for('index'))

@app.route("/add", methods=["POST"])
def add_device():
    name = request.form.get('name', '').strip()
    if not name:
        return redirect(url_for('index'))

    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        new_id = find_smallest_missing_id(conn)
        conn.execute("INSERT OR IGNORE INTO devices (id, name) VALUES (?, ?)", (new_id, name))
        cur = conn.execute("SELECT 1 FROM devices WHERE id=?", (new_id,))
        if not cur.fetchone():
            conn.execute("INSERT INTO devices (name) VALUES (?)", (name,))
        conn.commit()
    except Exception:
        conn.rollback()
        try:
            conn.execute("INSERT INTO devices (name) VALUES (?)", (name,))
            conn.commit()
        except Exception:
            conn.rollback()
    finally:
        conn.close()
    return redirect(url_for('index'))

@app.route("/edit/<int:device_id>", methods=["POST"])
def edit_device(device_id):
    if not is_request_from_host():
        return redirect(url_for('index'))
    name = request.form.get('name', '').strip()
    if not name:
        return redirect(url_for('index'))
    conn = get_db()
    conn.execute("UPDATE devices SET name=? WHERE id=?", (name, device_id))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route("/delete/<int:device_id>", methods=["POST"])
def delete_device(device_id):
    if not is_request_from_host():
        return redirect(url_for('index'))
    conn = get_db()
    cur = conn.execute("SELECT status FROM devices WHERE id=?", (device_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return redirect(url_for('index'))
    if row["status"] == "In Use":
        conn.close()
        return redirect(url_for('index'))
    conn.execute("DELETE FROM devices WHERE id=?", (device_id,))
    conn.commit()
    conn.close()
    export_logs_to_file()
    return redirect(url_for('index'))

@app.route("/recover", methods=["POST"])
def recover():
    if not is_request_from_host():
        return redirect(url_for('index'))
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        max_id = get_max_id(conn)
        if max_id < 1:
            conn.execute("INSERT INTO devices (id, name, status) VALUES (?, ?, ?)", (1, "Device 1", "Available"))
            conn.commit()
            conn.close()
            return redirect(url_for('index'))
        cur = conn.execute("SELECT id FROM devices")
        present = set(r["id"] for r in cur.fetchall())
        missing = [i for i in range(1, max_id+1) if i not in present]
        for mid in missing:
            conn.execute(
                "INSERT OR IGNORE INTO devices (id, name, status) VALUES (?, ?, ?)",
                (mid, f"Device {mid}", "Available")
            )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()
    return redirect(url_for('index'))

@app.route("/download_logs")
def download_logs():
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()

    conn = get_db()
    sql = """
        SELECT l.id,
               l.device_id,
               d.name AS device_name,
               l.user,
               l.start_time,
               l.end_time
        FROM logs l
        JOIN devices d ON d.id = l.device_id
    """
    where = []
    params = []
    if start_date:
        where.append("date(l.start_time) >= date(?)")
        params.append(start_date)
    if end_date:
        where.append("date(l.start_time) <= date(?)")
        params.append(end_date)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY date(l.start_time) ASC, l.start_time ASC, l.id ASC"

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date", "serial", "device_id", "device_name", "user", "start_time", "end_time", "duration", "status"])

    current_date = None
    serial = 0
    for r in rows:
        start_str = r["start_time"]
        end_str = r["end_time"]

        try:
            st_dt = datetime.fromisoformat(start_str)
            date_str = st_dt.strftime("%Y-%m-%d")
            start_time_str = st_dt.strftime("%H:%M")
        except Exception:
            date_str = ""
            start_time_str = ""

        if end_str:
            try:
                et_dt = datetime.fromisoformat(end_str)
                end_time_str = et_dt.strftime("%H:%M")
            except Exception:
                end_time_str = ""
            status = "Completed"
        else:
            end_time_str = ""
            status = "Ongoing"

        duration = compute_duration(start_str, end_str)

        if date_str != current_date:
            if current_date is not None:
                writer.writerow([])
            current_date = date_str
            serial = 1
        else:
            serial += 1

        writer.writerow([
            date_str,
            serial,
            r["device_id"],
            r["device_name"],
            r["user"],
            start_time_str,
            end_time_str,
            duration,
            status
        ])

    csv_data = output.getvalue()
    output.close()

    if start_date or end_date:
        fn_start = start_date or "start"
        fn_end = end_date or "end"
        filename = f"logs_{fn_start}_to_{fn_end}.csv"
    else:
        filename = "logs_all.csv"

    response = make_response(csv_data)
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response

# ---------- start ----------
if __name__ == "__main__":
    try:
        init_db()
        print("Starting server at http://127.0.0.1:5000")
        print("Allowed hosts:", ALLOWED_HOST_IPS)
        app.run(host="0.0.0.0", port=5000, debug=True)
    except Exception as e:
        print("Failed to start:", e)
        traceback.print_exc()
        sys.exit(1)
