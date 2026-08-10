"""
Status dashboard route for the HA ingress panel.
Serves a simple real-time HTML page showing current door state.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import web

LOGGER = logging.getLogger(__name__)

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Ryobi GDO Local Server</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #1a1a2e;
      color: #e0e0e0;
      min-height: 100vh;
      padding: 20px;
    }
    h1 {
      font-size: 1.4rem;
      font-weight: 600;
      color: #7eb8f7;
      margin-bottom: 20px;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .dot {
      width: 10px; height: 10px;
      border-radius: 50%;
      background: #4caf50;
      animation: pulse 2s infinite;
    }
    @keyframes pulse {
      0%, 100% { opacity: 1; } 50% { opacity: 0.4; }
    }
    .dot.offline { background: #f44336; animation: none; }
    .card {
      background: #16213e;
      border: 1px solid #0f3460;
      border-radius: 12px;
      padding: 20px;
      margin-bottom: 16px;
    }
    .card h2 {
      font-size: 0.85rem;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: #7eb8f7;
      margin-bottom: 14px;
    }
    .state-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
      gap: 12px;
    }
    .state-item {
      background: #0f3460;
      border-radius: 8px;
      padding: 12px;
    }
    .state-item .label {
      font-size: 0.75rem;
      color: #9e9e9e;
      margin-bottom: 4px;
    }
    .state-item .value {
      font-size: 1.1rem;
      font-weight: 600;
    }
    .door-open   { color: #4caf50; }
    .door-closed { color: #2196f3; }
    .door-moving { color: #ff9800; }
    .door-fault  { color: #f44336; }
    .light-on    { color: #ffc107; }
    .light-off   { color: #9e9e9e; }
    .webhook-form { margin-top: 16px; }
    .webhook-form h2 { font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.1em; color: #7eb8f7; margin-bottom: 12px; }
    .btn-row { display: flex; gap: 10px; flex-wrap: wrap; }
    button {
      padding: 10px 20px;
      border: none;
      border-radius: 8px;
      cursor: pointer;
      font-size: 0.9rem;
      font-weight: 500;
      transition: opacity 0.2s;
    }
    button:hover { opacity: 0.8; }
    .btn-open  { background: #4caf50; color: white; }
    .btn-close { background: #2196f3; color: white; }
    .btn-light-on  { background: #ffc107; color: #333; }
    .btn-light-off { background: #455a64; color: white; }
    #log {
      margin-top: 16px;
      background: #0a0a1a;
      border-radius: 8px;
      padding: 12px;
      font-family: monospace;
      font-size: 0.8rem;
      color: #7eb8f7;
      max-height: 180px;
      overflow-y: auto;
    }
    #log p { margin-bottom: 4px; }
    .ts { color: #555; }
  </style>
</head>
<body>
  <h1>
    <span class="dot" id="ws-dot"></span>
    Ryobi GDO Local Server
  </h1>

  <div class="card" id="device-card">
    <h2 id="device-title">Loading…</h2>
    <div class="state-grid" id="state-grid"></div>
  </div>

  <div class="card">
    <div class="webhook-form">
      <h2>Manual State Push (testing)</h2>
      <div class="btn-row">
        <button class="btn-open"      onclick="pushState('door_state','1')">🔓 Door Open</button>
        <button class="btn-close"     onclick="pushState('door_state','0')">🔒 Door Closed</button>
        <button class="btn-light-on"  onclick="pushState('light_state',true)">💡 Light On</button>
        <button class="btn-light-off" onclick="pushState('light_state',false)">🌙 Light Off</button>
      </div>
    </div>
  </div>

  <div id="log"><p><span class="ts">—</span> Dashboard loaded</p></div>

<script>
const DOOR_LABELS = { '0':'Closed','1':'Open','2':'Closing','3':'Opening','4':'Fault' };
const DOOR_CLASSES = { '0':'door-closed','1':'door-open','2':'door-moving','3':'door-moving','4':'door-fault' };
let deviceId = null;

function log(msg) {
  const el = document.getElementById('log');
  const ts = new Date().toLocaleTimeString();
  el.innerHTML = `<p><span class="ts">${ts}</span> ${msg}</p>` + el.innerHTML;
}

function renderState(data) {
  const grid = document.getElementById('state-grid');
  const doorState = data.door_state ?? '?';
  const doorLabel = DOOR_LABELS[doorState] ?? doorState;
  const doorCls   = DOOR_CLASSES[doorState] ?? '';
  const lightOn   = data.light_state;

  grid.innerHTML = `
    <div class="state-item">
      <div class="label">Door</div>
      <div class="value ${doorCls}">${doorLabel}</div>
    </div>
    <div class="state-item">
      <div class="label">Light</div>
      <div class="value ${lightOn ? 'light-on':'light-off'}">${lightOn ? 'On':'Off'}</div>
    </div>
    ${data.battery_level != null ? `<div class="state-item"><div class="label">Battery</div><div class="value">${data.battery_level}%</div></div>` : ''}
    ${data.wifi_rssi != null ? `<div class="state-item"><div class="label">WiFi RSSI</div><div class="value">${data.wifi_rssi} dBm</div></div>` : ''}
    <div class="state-item">
      <div class="label">Safety Sensor</div>
      <div class="value">${data.safety ? '⚠ Blocked' : '✓ Clear'}</div>
    </div>
    ${data.device_name ? `<div class="state-item"><div class="label">Device</div><div class="value" style="font-size:0.9rem">${data.device_name}</div></div>` : ''}
  `;
}

// Compute Ingress base path
const basePath = (function() {
  const p = window.location.pathname;
  return p.endsWith('/') ? p : p + '/';
})();

// Fetch initial state
async function loadState() {
  try {
    const r = await fetch(basePath + 'state');
    const data = await r.json();
    const ids = Object.keys(data);
    if (ids.length === 0) { log('No devices found'); return; }
    deviceId = ids[0];
    document.getElementById('device-title').textContent = data[deviceId].device_name || deviceId;
    renderState(data[deviceId]);
  } catch(e) { log('Error loading state: ' + e); }
}

// Push state via webhook
async function pushState(field, value) {
  if (!deviceId) { log('No device loaded'); return; }
  const body = { device_id: deviceId, [field]: value };
  try {
    const r = await fetch(basePath + 'state', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
    const j = await r.json();
    log(`Pushed ${field}=${JSON.stringify(value)} → ${j.result}`);
    await loadState();
  } catch(e) { log('Push error: ' + e); }
}

// WebSocket live updates
function connectWS() {
  const dot = document.getElementById('ws-dot');
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsCleanPath = basePath.replace(/^\/+/, '');
  const wsUrl = `${proto}//${location.host}/${wsCleanPath}api/wsrpc`;
  const ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    dot.classList.remove('offline');
    log('WebSocket connected — live updates active');
    // Authenticate with a dummy key (enforce_token is false in addon)
    ws.send(JSON.stringify({jsonrpc:'2.0',id:1,method:'srvWebSocketAuth',params:{varName:'dashboard',apiKey:'addon-dashboard'}}));
    // Subscribe to all
    if (deviceId) {
      ws.send(JSON.stringify({jsonrpc:'2.0',id:2,method:'wskSubscribe',params:{topic:`${deviceId}.wskAttributeUpdateNtfy`}}));
    }
  };

  ws.onmessage = (evt) => {
    try {
      const msg = JSON.parse(evt.data);
      if (msg.method === 'wskAttributeUpdateNtfy') {
        log('Live update received');
        loadState();
      }
    } catch(e) {}
  };

  ws.onclose = () => {
    dot.classList.add('offline');
    log('WebSocket disconnected — reconnecting in 5s…');
    setTimeout(connectWS, 5000);
  };

  ws.onerror = (e) => { log('WebSocket error'); };
}

loadState().then(() => connectWS());
</script>
</body>
</html>
"""


def make_dashboard_handler():
    """GET / — serve the status dashboard HTML."""
    async def handle_dashboard(request: web.Request) -> web.Response:
        return web.Response(
            body=DASHBOARD_HTML,
            content_type="text/html",
        )
    return handle_dashboard
