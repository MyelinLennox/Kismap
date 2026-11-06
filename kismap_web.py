"""Local browser interface for the Kismap."""

import json
import argparse
import os
import sqlite3
import math
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from datetime import datetime, timezone
import pandas as pd

from kismap import aggregate_cells, calibrate_path_loss, estimate_position, get_band, load_packets, normalize_frequency_mhz


APP_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kismet Field Map</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <style>
    :root {
      color-scheme: dark;
      --bg: #111719;
      --surface: #192124;
      --surface-raised: #202a2d;
      --border: #354246;
      --text: #e8efed;
      --muted: #9eaeaa;
      --accent: #73d6bd;
      --danger: #ff847b;
      --topbar: 58px;
      font-family: "Aptos", "Segoe UI Variable", "Segoe UI", sans-serif;
      color: var(--text);
      background: var(--bg);
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; margin: 0; overflow: hidden; }
    button, input, select, textarea { font: inherit; }
    button { color: inherit; }
    #map { position: absolute; inset: var(--topbar) 0 0; background: #101719; }
    .leaflet-tile-pane { filter: invert(1) hue-rotate(180deg) brightness(.62) saturate(.55); }
    .topbar {
      position: absolute; inset: 0 0 auto; z-index: 1200; height: var(--topbar);
      display: flex; align-items: center; gap: 8px; padding: 0 16px;
      background: #151d20; border-bottom: 1px solid var(--border);
    }
    .brand { display: flex; align-items: center; gap: 10px; margin-right: auto; }
    .brand-mark { width: 10px; height: 26px; background: var(--accent); border-radius: 2px; }
    .brand-title { font-size: 15px; font-weight: 700; }
    .brand-subtitle { margin-top: 2px; color: var(--muted); font-size: 11px; }
    .nav-button, .primary-button, .secondary-button, .icon-button {
      min-height: 36px; border: 1px solid var(--border); border-radius: 4px;
      background: var(--surface-raised); cursor: pointer;
    }
    .nav-button { padding: 0 12px; color: var(--muted); }
    .nav-button:hover, .nav-button[aria-expanded="true"] { color: var(--text); border-color: #61736f; }
    .primary-button { width: 100%; padding: 0 12px; color: #0c211d; background: var(--accent); border-color: var(--accent); font-weight: 700; }
    .secondary-button { width: 100%; margin-top: 8px; padding: 0 12px; }
    button:disabled { opacity: .5; cursor: not-allowed; }
    #connection-state { display: flex; align-items: center; gap: 7px; color: var(--muted); font-size: 12px; white-space: nowrap; }
    #connection-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); }
    .drawer {
      position: absolute; top: var(--topbar); bottom: 0; z-index: 1100;
      width: min(360px, calc(100vw - 24px)); padding: 18px;
      overflow-y: auto; background: var(--surface); border-color: var(--border);
      transition: transform 180ms ease; box-shadow: 0 8px 28px #0007;
    }
    .drawer-left { left: 0; border-right: 1px solid var(--border); transform: translateX(-105%); }
    .drawer-right { right: 0; border-left: 1px solid var(--border); transform: translateX(105%); }
    .drawer.open { transform: translateX(0); }
    .drawer-heading { display: flex; align-items: center; justify-content: space-between; margin-bottom: 18px; }
    .drawer-heading h1 { margin: 0; font-size: 17px; }
    .icon-button { width: 34px; padding: 0; background: transparent; font-size: 21px; }
    .section { padding: 15px 0; border-top: 1px solid var(--border); }
    .section:first-of-type { border-top: 0; padding-top: 0; }
    .section-title { margin: 0 0 11px; color: var(--accent); font-size: 11px; font-weight: 700; text-transform: uppercase; }
    label { display: block; margin: 10px 0; color: var(--muted); font-size: 12px; }
    input, select, textarea {
      display: block; width: 100%; margin-top: 5px; padding: 9px 10px;
      color: var(--text); background: #101719; border: 1px solid var(--border); border-radius: 3px;
    }
    input[type="file"] { padding: 7px; font-size: 12px; }
    input[type="file"]::file-selector-button { margin-right: 8px; padding: 5px 8px; color: var(--text); background: var(--surface-raised); border: 1px solid var(--border); border-radius: 3px; }
    .toggle-row { display: flex; align-items: center; gap: 9px; color: var(--text); }
    .toggle-row input { width: 16px; height: 16px; margin: 0; accent-color: var(--accent); }
    .band-filter-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; }
    .band-toggle { display: flex; align-items: center; gap: 7px; margin: 3px 0; color: var(--text); }
    .band-toggle input { width: 15px; height: 15px; margin: 0; accent-color: var(--accent); }
    .table-filter-group { margin: 8px 0; border: 1px solid var(--border); border-radius: 3px; }
    .table-filter-group summary { padding: 9px 10px; cursor: pointer; color: var(--text); font-size: 12px; }
    .table-filter-group summary span { color: var(--muted); font-size: 10px; }
    .table-filter-columns { padding: 0 10px 8px; }
    .table-column-filter { margin: 9px 0 13px; }
    .table-column-filter input[type="text"], .table-column-filter select { margin-top: 5px; }
    .table-column-filter input[type="range"] { margin-top: 2px; }
    .bssid-entry { display: grid; grid-template-columns: 1fr auto; align-items: end; gap: 8px; }
    .bssid-entry label { margin-bottom: 0; }
    .bssid-entry button { width: auto; min-width: 62px; margin-bottom: 0; }
    .bssid-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
    .bssid-chip { display: inline-flex; align-items: center; gap: 6px; max-width: 100%; padding: 5px 7px; color: var(--text); background: var(--surface-raised); border: 1px solid var(--border); border-radius: 3px; font-size: 11px; }
    .bssid-chip span { overflow-wrap: anywhere; }
    .bssid-chip button { width: 20px; height: 20px; padding: 0; color: var(--muted); background: transparent; border: 0; cursor: pointer; }
    textarea { min-height: 72px; resize: vertical; line-height: 1.45; }
    .field-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .range-filter { margin: 16px 0; }
    .range-filter-heading { display: flex; justify-content: space-between; gap: 8px; color: var(--muted); font-size: 12px; }
    .range-filter-value { color: var(--text); font-variant-numeric: tabular-nums; white-space: nowrap; }
    .range-filter-inputs { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .range-filter-inputs label { margin: 8px 0 0; font-size: 10px; }
    input[type="range"] { height: 20px; padding: 0; accent-color: var(--accent); background: transparent; }
    .hint, .status-copy { color: var(--muted); font-size: 12px; line-height: 1.5; }
    #data-summary, #estimate-result { margin-top: 10px; color: var(--muted); font-size: 12px; line-height: 1.5; }
    #toast {
      position: absolute; z-index: 1300; left: 50%; bottom: 22px; transform: translate(-50%, 12px);
      max-width: min(520px, calc(100vw - 32px)); padding: 10px 14px;
      color: var(--text); background: #202a2d; border: 1px solid var(--border); border-radius: 4px;
      opacity: 0; pointer-events: none; transition: opacity 150ms ease, transform 150ms ease;
      font-size: 12px; text-align: center;
    }
    #toast.show { opacity: 1; transform: translate(-50%, 0); }
    .leaflet-control-zoom a { color: #e8efed !important; background: #192124 !important; border-color: #354246 !important; }
    .leaflet-control-attribution { background: #111719cc !important; color: #b6c4c0 !important; }
    .leaflet-control-attribution a { color: #73d6bd !important; }
    .leaflet-tooltip.map-point-tooltip {
      max-width: min(440px, 82vw); max-height: 55vh; padding: 0; overflow: auto;
      color: var(--text); background: var(--surface); border: 1px solid var(--border);
      border-radius: 4px; box-shadow: 0 8px 24px #000b; white-space: normal;
    }
    .leaflet-tooltip.map-point-tooltip::before { display: none; }
    .point-tooltip-title { position: sticky; top: 0; padding: 9px 11px; color: var(--accent); background: var(--surface-raised); border-bottom: 1px solid var(--border); font-weight: 700; }
    .point-tooltip-grid { display: grid; grid-template-columns: minmax(100px, auto) minmax(120px, 1fr); gap: 5px 12px; padding: 9px 11px; font-size: 11px; }
    .point-tooltip-key { color: var(--muted); overflow-wrap: anywhere; }
    .point-tooltip-value { color: var(--text); margin: 0; overflow-wrap: anywhere; white-space: pre-wrap; }
    .device-name-label { padding: 2px 6px; color: var(--text); background: #192124eF; border: 1px solid var(--accent); border-radius: 3px; white-space: nowrap; box-shadow: 0 2px 8px #0009; }
    .device-name-label .device-frequency { margin-left: 5px; color: var(--accent); font-size: .85em; }
    .leaflet-div-icon.device-name-icon { background: transparent; border: 0; }
    #estimate-summary { margin-top: 10px; color: var(--muted); font-size: 12px; line-height: 1.5; }
    #estimate-details { margin-top: 7px; color: var(--text); font-size: 12px; }
    #estimate-details > summary, .estimate-group > summary { cursor: pointer; color: var(--accent); }
    .estimate-group { margin: 8px 0; padding-left: 8px; border-left: 1px solid var(--border); }
    .estimate-item { padding: 5px 0; color: var(--muted); overflow-wrap: anywhere; }
    .capture-metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; }
    .capture-metric { min-width: 0; padding: 8px; background: var(--surface-raised); border: 1px solid var(--border); border-radius: 3px; }
    .capture-metric-label { color: var(--muted); font-size: 10px; }
    .capture-metric-value { margin-top: 4px; color: var(--text); font-size: 13px; font-weight: 700; overflow-wrap: anywhere; }
    .capture-chart { display: grid; gap: 5px; margin-top: 10px; }
    .capture-chart-row { display: grid; grid-template-columns: 72px 1fr 30px; align-items: center; gap: 6px; color: var(--muted); font-size: 10px; }
    .capture-chart-track { height: 8px; background: #101719; border-radius: 2px; overflow: hidden; }
    .capture-chart-bar { height: 100%; min-width: 0; background: var(--accent); }
    .capture-chart-count { color: var(--text); text-align: right; font-variant-numeric: tabular-nums; }
    .capture-table-breakdown { margin-top: 12px; color: var(--text); font-size: 11px; }
    .capture-table-breakdown summary { cursor: pointer; color: var(--accent); }
    .capture-table-breakdown ul { max-height: 180px; margin: 8px 0 0; padding-left: 18px; overflow: auto; }
    .capture-table-breakdown li { margin: 5px 0; color: var(--muted); }
    @media (max-width: 640px) {
      :root { --topbar: 54px; }
      .topbar { gap: 5px; padding: 0 8px; }
      .brand { gap: 7px; }
      .brand-subtitle, #connection-state { display: none; }
      .brand-title { font-size: 13px; }
      .nav-button { min-height: 34px; padding: 0 8px; font-size: 12px; }
    }
    @media (prefers-reduced-motion: reduce) { *, *::before, *::after { transition-duration: 0.01ms !important; } }
  </style>
</head>
<body>
  <header class="topbar">
    <div class="brand"><span class="brand-mark"></span><div><div class="brand-title">KISMAP</div><div class="brand-subtitle">Kismet map</div></div></div>
    <button class="nav-button" data-panel="data-drawer" aria-expanded="false">Data</button>
    <button class="nav-button" data-panel="filter-drawer" aria-expanded="false">Filters</button>
    <button class="nav-button" data-panel="tools-drawer" aria-expanded="false">Tools</button>
    <div id="connection-state"><span id="connection-dot"></span><span id="state-text">Map ready</span></div>
  </header>
  <main id="map" aria-label="OpenStreetMap data map"></main>
  <aside class="drawer drawer-left" id="data-drawer" aria-label="Data">
    <div class="drawer-heading"><h1>Data</h1><button class="icon-button close-drawer" aria-label="Close data panel">&times;</button></div>
    <section class="section">
      <h2 class="section-title">Source</h2>
      <label>Kismet database<input id="database-file" type="file" accept=".kismet,.db,.sqlite,.sqlite3"></label>
      <label class="toggle-row"><input id="restrict-bssids" type="checkbox" role="switch"><span>Use BSSID allowlist</span></label>
      <label>Allowed BSSIDs<textarea id="allowlist" disabled placeholder="AA:BB:CC:DD:EE:FF&#10;11:22:33:44:55:66"></textarea></label>
      <div class="hint" id="allowlist-hint">All BSSIDs are included.</div>
      <button class="primary-button" id="load-database">Load database</button>
      <div id="data-summary" role="status">No database loaded.</div>
    </section>
    <section class="section">
      <h2 class="section-title">BSSIDs</h2>
      <label class="toggle-row"><input id="show-all-bssids" type="checkbox" role="switch" checked disabled><span>Show all BSSIDs</span></label>
      <div class="bssid-entry">
        <label>Add BSSID<input id="bssid-search" list="bssid-options" autocomplete="off" placeholder="Search database"></label>
        <datalist id="bssid-options"></datalist>
        <button class="secondary-button" id="add-bssid" disabled>Add</button>
      </div>
      <div id="bssid-chips" class="bssid-chips"></div>
      <div id="bssid-details" class="status-copy" role="status">BSSID details appear here after loading a database.</div>
    </section>
  </aside>

  <aside class="drawer drawer-right" id="filter-drawer" aria-label="Filters">
    <div class="drawer-heading"><h1>Filters</h1><button class="icon-button close-drawer" aria-label="Close filters">&times;</button></div>
    <section class="section">
      <h2 class="section-title">Bands</h2>
      <div id="band-filters" class="band-filter-list"></div>
      <div id="table-filters"></div>
      <div class="field-row">
        <label>From (UTC)<input id="date-start" type="date"></label>
        <label>Through (UTC)<input id="date-end" type="date"></label>
      </div>
      <button class="secondary-button" id="reset-filters">Reset filters</button>
      <div id="filter-summary" class="status-copy" role="status">No records loaded.</div>
    </section>
  </aside>

  <aside class="drawer drawer-right" id="tools-drawer" aria-label="Map tools">
    <div class="drawer-heading"><h1>Tools</h1><button class="icon-button close-drawer" aria-label="Close tools">&times;</button></div>
    <section class="section">
      <h2 class="section-title">Estimate</h2>
      <div class="field-row">
        <label>Cell size (m)<input id="cell-size" type="number" min="0.1" step="0.1" value="5"></label>
        <label>Path-loss n<input id="path-loss" type="number" min="0.1" step="0.1" value="2.5"></label>
      </div>
      <div class="hint">Applied to each selected BSSID.</div>
      <div class="field-row">
        <label>Surveyed AP latitude<input id="known-lat" type="number" min="-90" max="90" step="0.000001" placeholder="Required for calibration"></label>
        <label>Surveyed AP longitude<input id="known-lon" type="number" min="-180" max="180" step="0.000001" placeholder="Required for calibration"></label>
      </div>
      <button class="secondary-button" id="calibrate-button" disabled>Calibrate path loss</button>
      <div id="calibration-result" class="status-copy" role="status">Select one BSSID and enter its AP location.</div>
      <button class="secondary-button" id="estimate-button" disabled>Estimate locations</button>
      <label class="toggle-row"><input id="estimate-view-toggle" type="checkbox" disabled><span>Show estimates instead of capture points</span></label>
      <button class="secondary-button" id="return-to-capture" disabled>Show captures</button>
      <label class="toggle-row"><input id="heatmap-toggle" type="checkbox" disabled><span>Show signal heatmap</span></label>
      <div id="estimate-result" role="status">
        <div id="estimate-summary">No estimates yet.</div>
        <details id="estimate-details" hidden>
          <summary>View per-BSSID results</summary>
          <div id="estimate-groups"></div>
        </details>
      </div>
    </section>
    <section class="section">
      <h2 class="section-title">Devices</h2>
      <label class="toggle-row"><input id="device-overlay-toggle" type="checkbox" disabled><span>Show nearby device names</span></label>
      <div id="device-overlay-summary" class="hint">Labels scale by frequency.</div>
    </section>
    <section class="section">
      <h2 class="section-title">Capture metrics</h2>
      <div id="capture-metrics" class="capture-metrics"></div>
      <h3 class="section-title" style="margin-top:14px">Signal distribution (dBm)</h3>
      <div id="signal-chart" class="capture-chart"></div>
      <details class="capture-table-breakdown">
        <summary>Records by table</summary>
        <ul id="table-breakdown"></ul>
      </details>
    </section>
    <section class="section">
      <h2 class="section-title">Export</h2>
      <button class="secondary-button" id="export-csv">Export visible records as CSV</button>
    </section>
  </aside>
  <div id="toast" role="status"></div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>
  <script>
    const initialZoom = window.innerWidth < 640 ? 1.5 : 3;
    const map = L.map('map', {zoomControl: false, zoomSnap: 0.5, minZoom: 1, maxZoom: 23}).setView([20, 0], initialZoom);
    L.control.zoom({position: 'bottomright'}).addTo(map);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxNativeZoom: 19, maxZoom: 23,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);
    const dataPoints = [];
    let spiderfiedMarkers = null;
    let availableBssids = [];
    const selectedBssids = new Set();
    let filterDefaults = {dateStart: '', dateEnd: ''};
    let tableColumnFilters = [];
    let estimateMarkers = [];
    const calibratedPathLoss = new Map();
    let heatLayer = null;
    let captureBounds = null;
    let deviceLabels = [];
    const deviceLayer = L.layerGroup().addTo(map);
    let toastTimer;
    const byId = id => document.getElementById(id);
    const setState = text => { byId('state-text').textContent = text; };
    map.on('movestart zoomstart', collapseSpiderfiedMarkers);
    map.on('mousemove', event => {
      if (!spiderfiedMarkers) return;
      const pointer = map.latLngToContainerPoint(event.latlng);
      if (pointer.distanceTo(spiderfiedMarkers.center) > spiderfiedMarkers.radius + 16) collapseSpiderfiedMarkers();
    });
    map.getContainer().addEventListener('mouseleave', collapseSpiderfiedMarkers);
    function toast(text) {
      const node = byId('toast'); node.textContent = text; node.classList.add('show');
      clearTimeout(toastTimer); toastTimer = setTimeout(() => node.classList.remove('show'), 3200);
    }
    function openPanel(id) {
      document.querySelectorAll('.drawer').forEach(panel => panel.classList.toggle('open', panel.id === id));
      document.querySelectorAll('.nav-button').forEach(button => button.setAttribute('aria-expanded', String(button.dataset.panel === id)));
    }
    document.querySelectorAll('.nav-button').forEach(button => button.addEventListener('click', () => {
      const panel = byId(button.dataset.panel);
      openPanel(panel.classList.contains('open') ? '' : panel.id);
    }));
    document.querySelectorAll('.close-drawer').forEach(button => button.addEventListener('click', () => openPanel('')));
    document.addEventListener('keydown', event => { if (event.key === 'Escape') openPanel(''); });

    function signalColor(signal) {
      if (signal <= -85) return '#78a9e6';
      if (signal <= -75) return '#74d6a8';
      if (signal <= -60) return '#f2b35e';
      return '#ff756b';
    }
    function distanceMeters(lat1, lon1, lat2, lon2) {
      const radians = value => value * Math.PI / 180;
      const deltaLat = radians(lat2 - lat1);
      const deltaLon = radians(lon2 - lon1);
      const a = Math.sin(deltaLat / 2) ** 2
        + Math.cos(radians(lat1)) * Math.cos(radians(lat2)) * Math.sin(deltaLon / 2) ** 2;
      return 2 * 6371000 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    }
    function hasKnownPosition() {
      const lat = byId('known-lat').value.trim();
      const lon = byId('known-lon').value.trim();
      return lat !== '' && lon !== '' && Number.isFinite(Number(lat)) && Number.isFinite(Number(lon))
        && Number(lat) >= -90 && Number(lat) <= 90 && Number(lon) >= -180 && Number(lon) <= 180;
    }
    function collapseSpiderfiedMarkers() {
      if (!spiderfiedMarkers) return;
      spiderfiedMarkers.items.forEach(item => item.marker.setLatLng(item.original));
      spiderfiedMarkers.legs.forEach(leg => map.removeLayer(leg));
      spiderfiedMarkers = null;
    }
    function spreadNearbyMarkers(anchorPoint) {
      if (spiderfiedMarkers) return;
      const center = map.latLngToContainerPoint(anchorPoint.marker.getLatLng());
      const nearby = dataPoints
        .filter(point => map.hasLayer(point.marker))
        .map(point => ({point, screen: map.latLngToContainerPoint(point.marker.getLatLng())}))
        .map(item => ({...item, distance: item.screen.distanceTo(center)}))
        .filter(item => item.distance <= 18)
        .sort((left, right) => left.distance - right.distance)
        .slice(0, 25);
      const others = nearby.filter(item => item.point !== anchorPoint);
      if (!others.length) return;
      const radius = Math.min(64, 34 + Math.max(0, others.length - 8) * 1.5);
      spiderfiedMarkers = {center, radius, items: [], legs: []};
      others.forEach((item, index) => {
        const original = item.point.marker.getLatLng();
        const angle = -Math.PI / 2 + (2 * Math.PI * index) / others.length;
        const target = L.point(center.x + Math.cos(angle) * radius, center.y + Math.sin(angle) * radius);
        const spreadPosition = map.containerPointToLatLng(target);
        spiderfiedMarkers.items.push({marker: item.point.marker, original});
        spiderfiedMarkers.legs.push(L.polyline([original, spreadPosition], {
          color: '#73d6bd', weight: 1, opacity: .75, interactive: false
        }).addTo(map));
        item.point.marker.setLatLng(spreadPosition);
        item.point.marker.bringToFront();
      });
      anchorPoint.marker.bringToFront();
    }
    function escapeTooltipValue(value) {
      return String(value).replace(/[&<>"']/g, character => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      })[character]);
    }
    function pointTooltip(point) {
      const values = Object.entries(point.values || {}).filter(([key]) => !key.startsWith('__has_blob__:'));
      const rows = values.map(([key, value]) => {
        const display = point.values[`__has_blob__:${key}`]
          ? '[binary data present]'
          : value === null || value === undefined ? 'NULL' : value;
        return `<span class="point-tooltip-key">${escapeTooltipValue(key)}</span><pre class="point-tooltip-value">${escapeTooltipValue(display)}</pre>`;
      }).join('');
      return `<div><div class="point-tooltip-title">${escapeTooltipValue(point.table)}${point.bssid ? ` · ${escapeTooltipValue(point.bssid)}` : ''}</div><div class="point-tooltip-grid">${rows}</div></div>`;
    }
    function bssidDetails(info) {
      const bands = info.bands.map(band => band === 'unknown' ? 'unknown' : `${band} GHz`).join(', ');
      const count = info.records;
      return `${count.toLocaleString()} record${count === 1 ? '' : 's'} · ${bands} · ${info.first_seen} to ${info.last_seen} UTC · ${info.min_signal} to ${info.max_signal} dBm`;
    }
    function renderBandFilters(bands) {
      const container = byId('band-filters'); container.replaceChildren();
      bands.forEach(band => {
        const label = document.createElement('label'); label.className = 'band-toggle';
        const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.value = band; checkbox.checked = true;
        checkbox.addEventListener('change', applyFilters);
        const text = document.createElement('span'); text.textContent = band === 'unknown' ? 'Unknown' : `${band} GHz`;
        label.append(checkbox, text); container.append(label);
      });
    }
    function renderTableFilters(schema) {
      const container = byId('table-filters'); container.replaceChildren();
      tableColumnFilters = [];
      schema.forEach(table => {
        const group = document.createElement('details'); group.className = 'table-filter-group'; group.open = table.has_coordinates;
        const summary = document.createElement('summary'); summary.append(document.createTextNode(`${table.name} `));
        const count = document.createElement('span'); count.textContent = `${table.rows.toLocaleString()} rows`;
        summary.append(count); group.append(summary);
        const columns = document.createElement('div'); columns.className = 'table-filter-columns';
        table.columns.forEach(column => {
          const field = document.createElement('div'); field.className = 'table-column-filter';
          const title = document.createElement('label'); title.textContent = `${column.name} (${column.type})`;
          field.append(title);
          let control = null;
          if (column.kind === 'number' && column.has_values && column.min !== undefined) {
            const heading = document.createElement('div'); heading.className = 'range-filter-heading';
            const shown = document.createElement('output'); shown.className = 'range-filter-value'; heading.append(shown); field.append(heading);
            const pair = document.createElement('div'); pair.className = 'range-filter-inputs';
            const lower = document.createElement('input'); lower.type = 'range'; lower.min = column.min; lower.max = column.max;
            lower.step = column.step; lower.value = column.min; lower.setAttribute('aria-label', `Minimum ${table.name}.${column.name}`);
            const upper = document.createElement('input'); upper.type = 'range'; upper.min = column.min; upper.max = column.max;
            upper.step = column.step; upper.value = column.max; upper.setAttribute('aria-label', `Maximum ${table.name}.${column.name}`);
            const lowerLabel = document.createElement('label'); lowerLabel.textContent = 'Min'; lowerLabel.append(lower);
            const upperLabel = document.createElement('label'); upperLabel.textContent = 'Max'; upperLabel.append(upper);
            pair.append(lowerLabel, upperLabel); field.append(pair);
            control = {kind: 'number', lower, upper, shown, column};
            const update = event => {
              if (Number(lower.value) > Number(upper.value)) {
                if (event.target === lower) upper.value = lower.value;
                else lower.value = upper.value;
              }
              shown.textContent = `${Number(lower.value).toLocaleString()} - ${Number(upper.value).toLocaleString()}`;
              applyFilters();
            };
            lower.addEventListener('input', update); upper.addEventListener('input', update);
            update({target: null});
          } else if (column.kind === 'enum') {
            const select = document.createElement('select'); select.add(new Option('All values', ''));
            column.values.forEach(value => select.add(new Option(value, value)));
            select.addEventListener('change', applyFilters); title.append(select);
            control = {kind: 'enum', input: select, column};
          } else if (column.kind === 'text') {
            const input = document.createElement('input'); input.type = 'text'; input.placeholder = 'Contains…';
            input.addEventListener('input', applyFilters); title.append(input);
            control = {kind: 'text', input, column};
          } else if (column.kind === 'blob') {
            const label = document.createElement('label'); label.className = 'toggle-row';
            const checkbox = document.createElement('input'); checkbox.type = 'checkbox';
            const text = document.createElement('span'); text.textContent = 'Has binary value';
            checkbox.addEventListener('change', applyFilters); label.append(checkbox, text); field.append(label);
            control = {kind: 'blob', input: checkbox, column};
          } else {
            const empty = document.createElement('div'); empty.className = 'hint'; empty.textContent = 'No values'; field.append(empty);
          }
          if (control) tableColumnFilters.push({table: table.name, ...control});
          columns.append(field);
        });
        group.append(columns); container.append(group);
      });
    }
    function renderBssidSelection() {
      const allSelected = byId('show-all-bssids').checked;
      const chips = byId('bssid-chips'); chips.replaceChildren();
      if (allSelected) {
        const chip = document.createElement('span'); chip.className = 'bssid-chip';
        chip.textContent = `All ${availableBssids.length} BSSIDs`; chips.append(chip);
        byId('bssid-details').textContent = `${availableBssids.length} BSSIDs from the loaded database`;
      } else {
        selectedBssids.forEach(bssid => {
          const info = availableBssids.find(item => item.bssid === bssid);
          const chip = document.createElement('span'); chip.className = 'bssid-chip';
          chip.title = info ? bssidDetails(info) : bssid;
          const text = document.createElement('span'); text.textContent = bssid; chip.append(text);
          const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '×';
          remove.title = `Remove ${bssid}`; remove.setAttribute('aria-label', `Remove ${bssid}`);
          remove.addEventListener('click', () => {
            selectedBssids.delete(bssid); renderBssidSelection(); loadSelectedBssids();
          });
          chip.append(remove); chips.append(chip);
        });
        const selectedDetails = [...selectedBssids].map(bssid => {
          const info = availableBssids.find(item => item.bssid === bssid);
          return info ? bssidDetails(info) : bssid;
        });
        byId('bssid-details').textContent = selectedDetails.length
          ? selectedDetails.join(' | ')
          : 'No BSSIDs selected.';
      }
      byId('estimate-button').disabled = availableBssids.length === 0 || (!allSelected && selectedBssids.size === 0);
      byId('calibrate-button').disabled = allSelected || selectedBssids.size !== 1 || !hasKnownPosition();
    }
    function addBssid() {
      const input = byId('bssid-search');
      const value = input.value.trim().toUpperCase();
      const match = availableBssids.find(item => item.bssid === value);
      if (!match) return toast('Choose a BSSID from the database list.');
      if (byId('show-all-bssids').checked) {
        byId('show-all-bssids').checked = false;
        selectedBssids.clear();
      }
      selectedBssids.add(match.bssid);
      input.value = '';
      renderBssidSelection();
      loadSelectedBssids();
    }
    function updateHeatmap() {
      if (heatLayer) { map.removeLayer(heatLayer); heatLayer = null; }
      if (!byId('heatmap-toggle').checked || typeof L.heatLayer !== 'function') return;
      const points = dataPoints
        .filter(point => map.hasLayer(point.marker) && Number.isFinite(point.signal))
        .map(point => [point.lat, point.lon, Math.max(0.1, Math.min(1, (point.signal + 100) / 70))]);
      if (points.length) {
        heatLayer = L.heatLayer(points, {radius: 28, blur: 20, maxZoom: 17,
          gradient: {0.15: '#1e88e5', 0.45: '#00bfa5', 0.7: '#ffca28', 1: '#f4511e'}}).addTo(map);
      }
    }
    function applyPositionView() {
      const showEstimates = byId('estimate-view-toggle').checked && estimateMarkers.length > 0;
      dataPoints.forEach(point => {
        if (showEstimates || !map.hasLayer(point.marker)) map.removeLayer(point.marker);
      });
      estimateMarkers.forEach(marker => {
        if (showEstimates) marker.addTo(map);
        else map.removeLayer(marker);
      });
      if (!showEstimates) applyFilters();
      else updateHeatmap();
    }
    byId('estimate-view-toggle').addEventListener('change', applyPositionView);
    function updateDeviceOverlay() {
      deviceLayer.clearLayers();
      const enabled = byId('device-overlay-toggle').checked;
      if (!enabled) return;
      const area = captureBounds ? captureBounds.pad(0.35) : map.getBounds();
      const nearby = deviceLabels.filter(device => area.contains([device.lat, device.lon]));
      nearby.forEach(device => {
        const frequency = Number(device.frequency_mhz);
        const scale = Number.isFinite(frequency) ? Math.max(0, Math.min(1, (frequency - 2400) / 4725)) : 0;
        const fontSize = 10 + scale * 8;
        const name = document.createElement('span'); name.className = 'device-name-label'; name.style.fontSize = `${fontSize}px`;
        name.title = `${device.mac} · ${Number.isFinite(frequency) ? `${frequency.toLocaleString()} MHz` : 'frequency unavailable'}`;
        name.append(document.createTextNode(device.name));
        if (Number.isFinite(frequency)) {
          const frequencyLabel = document.createElement('span'); frequencyLabel.className = 'device-frequency';
          frequencyLabel.textContent = `${(frequency / 1000).toFixed(1)} GHz`; name.append(frequencyLabel);
        }
        L.marker([device.lat, device.lon], {
          icon: L.divIcon({className: 'device-name-icon', html: name.outerHTML, iconSize: [0, 0]}),
          interactive: false,
          keyboard: false,
        }).addTo(deviceLayer);
      });
      byId('device-overlay-summary').textContent = `${nearby.length.toLocaleString()} nearby devices · label size follows frequency`;
    }
    function updateCaptureMetrics() {
      const metrics = byId('capture-metrics');
      const chart = byId('signal-chart');
      const tableBreakdown = byId('table-breakdown');
      metrics.replaceChildren(); chart.replaceChildren(); tableBreakdown.replaceChildren();
      if (!dataPoints.length) {
        const empty = document.createElement('div'); empty.className = 'hint'; empty.textContent = 'Load a database to calculate capture metrics.';
        metrics.append(empty); return;
      }
      const addMetric = (label, value) => {
        const card = document.createElement('div'); card.className = 'capture-metric';
        const name = document.createElement('div'); name.className = 'capture-metric-label'; name.textContent = label;
        const reading = document.createElement('div'); reading.className = 'capture-metric-value'; reading.textContent = value;
        card.append(name, reading); metrics.append(card);
      };
      const signals = dataPoints.map(point => point.signal).filter(Number.isFinite).sort((a, b) => a - b);
      const latitudes = dataPoints.map(point => point.lat);
      const longitudes = dataPoints.map(point => point.lon);
      const dates = dataPoints.map(point => point.date).filter(Boolean).sort();
      const bssids = new Set(dataPoints.map(point => point.bssid).filter(Boolean));
      const tables = new Map();
      dataPoints.forEach(point => tables.set(point.table, (tables.get(point.table) || 0) + 1));
      const cellSize = Math.max(Number(byId('cell-size').value) || 5, 0.1);
      const centerLat = (Math.min(...latitudes) + Math.max(...latitudes)) / 2;
      const centerLon = (Math.min(...longitudes) + Math.max(...longitudes)) / 2;
      const cellKeys = new Set(dataPoints.map(point => {
        const x = 6371000 * Math.cos(centerLat * Math.PI / 180) * (point.lon - centerLon) * Math.PI / 180;
        const y = 6371000 * (point.lat - centerLat) * Math.PI / 180;
        return `${Math.floor(x / cellSize)},${Math.floor(y / cellSize)}`;
      }));
      const northSouth = (Math.max(...latitudes) - Math.min(...latitudes)) * 111320;
      const eastWest = (Math.max(...longitudes) - Math.min(...longitudes)) * 111320 * Math.cos(centerLat * Math.PI / 180);
      const medianSignal = !signals.length ? null : signals.length % 2
        ? signals[Math.floor(signals.length / 2)]
        : (signals[signals.length / 2 - 1] + signals[signals.length / 2]) / 2;
      const frequencies = dataPoints.map(point => point.frequency_mhz).filter(Number.isFinite);
      const bands = new Map();
      dataPoints.forEach(point => bands.set(point.band, (bands.get(point.band) || 0) + 1));
      addMetric('Map points', dataPoints.length.toLocaleString());
      addMetric('Selected BSSIDs', bssids.size.toLocaleString());
      addMetric('Source tables', tables.size.toLocaleString());
      addMetric(`${cellSize.toLocaleString()} m grid cells`, cellKeys.size.toLocaleString());
      addMetric('Capture span', dates.length ? `${dates[0]} to ${dates[dates.length - 1]}` : 'No timestamps');
      addMetric('Coordinate span', `${northSouth.toFixed(0)} m N-S × ${eastWest.toFixed(0)} m E-W`);
      addMetric('Frequency span', frequencies.length
        ? `${Math.min(...frequencies).toFixed(1)}–${Math.max(...frequencies).toFixed(1)} MHz`
        : 'No frequency values');
      addMetric('Bands', [...bands.entries()].sort((left, right) => right[1] - left[1])
        .map(([band, count]) => `${band === 'unknown' ? 'unknown' : `${band} GHz`}: ${count.toLocaleString()}`).join(' · '));
      addMetric('Signal min / median / max', signals.length
        ? `${signals[0].toFixed(0)} / ${medianSignal.toFixed(0)} / ${signals[signals.length - 1].toFixed(0)} dBm`
        : 'No signal values');

      if (signals.length) {
        const minimum = signals[0];
        const maximum = signals[signals.length - 1];
        const binCount = 8;
        const width = Math.max(maximum - minimum, 1);
        const bins = Array.from({length: binCount}, () => 0);
        signals.forEach(signal => {
          const index = Math.min(binCount - 1, Math.floor(((signal - minimum) / width) * binCount));
          bins[index] += 1;
        });
        const maxCount = Math.max(...bins);
        bins.forEach((count, index) => {
          const lower = minimum + width * index / binCount;
          const upper = minimum + width * (index + 1) / binCount;
          const row = document.createElement('div'); row.className = 'capture-chart-row';
          const range = document.createElement('span'); range.textContent = `${lower.toFixed(0)}–${upper.toFixed(0)}`;
          const track = document.createElement('div'); track.className = 'capture-chart-track';
          const bar = document.createElement('div'); bar.className = 'capture-chart-bar';
          bar.style.width = `${count / maxCount * 100}%`; bar.title = `${count} records`;
          track.append(bar);
          const number = document.createElement('span'); number.className = 'capture-chart-count'; number.textContent = count.toLocaleString();
          row.append(range, track, number); chart.append(row);
        });
      } else {
        const empty = document.createElement('div'); empty.className = 'hint'; empty.textContent = 'No signal values in this selection.'; chart.append(empty);
      }
      [...tables.entries()].sort((left, right) => right[1] - left[1]).forEach(([table, count]) => {
        const item = document.createElement('li'); item.textContent = `${table}: ${count.toLocaleString()}`; tableBreakdown.append(item);
      });
    }
    byId('device-overlay-toggle').addEventListener('change', updateDeviceOverlay);
    byId('cell-size').addEventListener('input', updateCaptureMetrics);
    byId('return-to-capture').addEventListener('click', () => {
      collapseSpiderfiedMarkers();
      byId('estimate-view-toggle').checked = false;
      applyPositionView();
      if (captureBounds && captureBounds.isValid()) map.fitBounds(captureBounds.pad(0.12));
    });
    function applyFilters() {
      collapseSpiderfiedMarkers();
      const bands = new Set([...byId('band-filters').querySelectorAll('input:checked')].map(input => input.value));
      const start = byId('date-start').value;
      const end = byId('date-end').value;
      let visible = 0;
      dataPoints.forEach(point => {
        const tableMatches = tableColumnFilters.every(filter => {
          if (filter.table !== point.table) return true;
          const raw = point.values[filter.column.name];
          if (filter.kind === 'number') {
            const value = raw === null || raw === undefined ? NaN : Number(raw);
            if (!Number.isFinite(value)) return Number(filter.lower.value) <= filter.column.min && Number(filter.upper.value) >= filter.column.max;
            return value >= Number(filter.lower.value) && value <= Number(filter.upper.value);
          }
          if (filter.kind === 'enum') return !filter.input.value || String(raw ?? '') === filter.input.value;
          if (filter.kind === 'text') return !filter.input.value || String(raw ?? '').toLowerCase().includes(filter.input.value.toLowerCase());
          if (filter.kind === 'blob') return !filter.input.checked || point.values[`__has_blob__:${filter.column.name}`] === true;
          return true;
        });
        const matches = bands.has(point.band)
          && tableMatches
          && (!start || !point.date || point.date >= start) && (!end || !point.date || point.date <= end);
        if (matches) {
          if (!byId('estimate-view-toggle').checked && !map.hasLayer(point.marker)) point.marker.addTo(map);
          visible += 1;
        }
        else if (map.hasLayer(point.marker)) map.removeLayer(point.marker);
      });
      byId('filter-summary').textContent = `${visible.toLocaleString()} of ${dataPoints.length.toLocaleString()} record${dataPoints.length === 1 ? '' : 's'} visible`;
      updateHeatmap();
    }
    ['date-start', 'date-end'].forEach(id => {
      byId(id).addEventListener('input', applyFilters); byId(id).addEventListener('change', applyFilters);
    });
    byId('reset-filters').addEventListener('click', () => {
      byId('band-filters').querySelectorAll('input[type="checkbox"]').forEach(input => { input.checked = true; });
      tableColumnFilters.forEach(filter => {
        if (filter.kind === 'number') { filter.lower.value = filter.column.min; filter.upper.value = filter.column.max; }
        else if (filter.kind === 'enum' || filter.kind === 'text') filter.input.value = '';
        else if (filter.kind === 'blob') filter.input.checked = false;
      });
      byId('date-start').value = filterDefaults.dateStart; byId('date-end').value = filterDefaults.dateEnd; applyFilters();
    });

    byId('restrict-bssids').addEventListener('change', event => {
      byId('allowlist').disabled = event.target.checked === false;
      byId('allowlist-hint').textContent = event.target.checked
        ? 'Only the BSSIDs entered here are loaded.'
        : 'All BSSIDs are included.';
    });
    byId('allowlist').disabled = !byId('restrict-bssids').checked;
    byId('heatmap-toggle').addEventListener('change', updateHeatmap);
    byId('show-all-bssids').addEventListener('change', () => {
      selectedBssids.clear(); renderBssidSelection(); loadSelectedBssids();
    });
    ['known-lat', 'known-lon'].forEach(id => byId(id).addEventListener('input', () => {
      byId('calibrate-button').disabled = byId('show-all-bssids').checked
        || selectedBssids.size !== 1 || !hasKnownPosition();
    }));
    byId('path-loss').addEventListener('input', () => calibratedPathLoss.clear());
    byId('add-bssid').addEventListener('click', addBssid);
    byId('bssid-search').addEventListener('keydown', event => {
      if (event.key === 'Enter') { event.preventDefault(); addBssid(); }
    });

    byId('load-database').addEventListener('click', async () => {
      const file = byId('database-file').files[0];
      const restrict = byId('restrict-bssids').checked;
      const allowlist = byId('allowlist').value.trim().replace(/[\s,]+/g, ' ');
      if (!file) return toast('Choose a Kismet database first.');
      if (restrict && !allowlist) return toast('Enter the BSSIDs to allow.');
      const button = byId('load-database'); button.disabled = true; button.textContent = 'Loading…'; setState('Reading database');
      try {
        const response = await fetch('/api/database', {method: 'POST', headers: {'X-Lab-Bssids': allowlist, 'X-Use-Allowlist': String(restrict)}, body: file});
        const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Could not load database.');
        calibratedPathLoss.clear();
        byId('path-loss').value = '2.5';
        byId('calibration-result').textContent = 'Select one BSSID and enter its AP location.';
        availableBssids = result.bssids;
        const suggestions = byId('bssid-options'); suggestions.replaceChildren();
        availableBssids.forEach(info => {
          const option = document.createElement('option'); option.value = info.bssid;
          option.label = `${info.bssid} · ${bssidDetails(info)}`; option.title = bssidDetails(info);
          suggestions.append(option);
        });
        byId('show-all-bssids').disabled = result.bssids.length === 0;
        byId('bssid-search').disabled = result.bssids.length === 0;
        byId('add-bssid').disabled = result.bssids.length === 0;
        byId('show-all-bssids').checked = true;
        selectedBssids.clear();
        renderBandFilters(result.bands);
        renderTableFilters(result.schema);
        filterDefaults = result.filters;
        byId('date-start').min = filterDefaults.dateStart;
        byId('date-start').max = filterDefaults.dateEnd;
        byId('date-start').value = filterDefaults.dateStart;
        byId('date-end').min = filterDefaults.dateStart;
        byId('date-end').max = filterDefaults.dateEnd;
        byId('date-end').value = filterDefaults.dateEnd;
        renderBssidSelection();
        const source = result.allowlist_active ? 'allowed' : 'database';
        byId('data-summary').textContent = `${result.count.toLocaleString()} records from ${result.bssids.length} ${source} BSSID${result.bssids.length === 1 ? '' : 's'}.`;
        openPanel(''); setState('Database loaded');
        if (result.bssids.length) { await loadSelectedBssids(); toast('Database loaded. All BSSIDs are shown.'); }
      } catch (error) { toast(error.message); setState('Load failed'); }
      finally { button.disabled = false; button.textContent = 'Load database'; }
    });

    async function loadSelectedBssids() {
      const all = byId('show-all-bssids').checked;
      const bssids = [...selectedBssids];
      if (!all && !bssids.length) {
        dataPoints.forEach(point => map.removeLayer(point.marker)); dataPoints.length = 0;
        updateCaptureMetrics();
        estimateMarkers.forEach(marker => map.removeLayer(marker)); estimateMarkers = [];
        byId('estimate-view-toggle').checked = false; byId('estimate-view-toggle').disabled = true;
        byId('estimate-summary').textContent = 'No estimates yet.';
        byId('estimate-details').hidden = true; byId('estimate-groups').replaceChildren();
        captureBounds = null;
        deviceLabels = []; deviceLayer.clearLayers();
        byId('device-overlay-toggle').checked = false; byId('device-overlay-toggle').disabled = true;
        byId('return-to-capture').disabled = true;
        byId('heatmap-toggle').checked = false; byId('heatmap-toggle').disabled = true; updateHeatmap();
        byId('filter-summary').textContent = 'No BSSIDs selected.';
        setState('No BSSIDs selected'); return;
      }
      setState('Loading BSSID data');
      try {
        const requestBody = JSON.stringify({all, bssids});
        const [recordsResponse, devicesResponse] = await Promise.all([
          fetch('/api/records', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: requestBody}),
          fetch('/api/devices', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: requestBody}),
        ]);
        const result = await recordsResponse.json(); if (!recordsResponse.ok) throw new Error(result.error || 'Could not load map data.');
        const devicesResult = await devicesResponse.json(); if (!devicesResponse.ok) throw new Error(devicesResult.error || 'Could not load device names.');
        dataPoints.forEach(point => map.removeLayer(point.marker)); dataPoints.length = 0;
        estimateMarkers.forEach(marker => map.removeLayer(marker)); estimateMarkers = [];
        byId('estimate-view-toggle').checked = false; byId('estimate-view-toggle').disabled = true;
        byId('estimate-summary').textContent = 'No estimates yet.';
        byId('estimate-details').hidden = true; byId('estimate-groups').replaceChildren();
        collapseSpiderfiedMarkers();
        result.records.forEach(point => {
          const signal = Number.isFinite(point.signal) ? point.signal : -100;
          const marker = L.circleMarker([point.lat, point.lon], {radius: 5, color: signalColor(signal), fillColor: signalColor(signal), fillOpacity: .85, weight: 1});
          const tooltip = pointTooltip(point);
          marker.bindTooltip(tooltip, {className: 'map-point-tooltip', direction: 'top', sticky: true, opacity: .98});
          marker.bindPopup(tooltip);
          const mapPoint = {...point, date: point.date || '', marker};
          marker.on('mouseover', () => spreadNearbyMarkers(mapPoint));
          dataPoints.push(mapPoint);
        });
        updateCaptureMetrics();
        captureBounds = dataPoints.length ? L.latLngBounds(dataPoints.map(point => [point.lat, point.lon])) : null;
        byId('return-to-capture').disabled = !captureBounds;
        deviceLabels = devicesResult.devices;
        byId('device-overlay-toggle').disabled = deviceLabels.length === 0;
        if (byId('device-overlay-toggle').disabled) byId('device-overlay-toggle').checked = false;
        updateDeviceOverlay();
        byId('heatmap-toggle').disabled = !dataPoints.some(point => Number.isFinite(point.signal));
        if (byId('heatmap-toggle').disabled) byId('heatmap-toggle').checked = false;
        applyFilters();
        if (captureBounds) {
          map.fitBounds(captureBounds.pad(.12));
          updateDeviceOverlay();
        }
        const label = dataPoints.length === 1 ? 'record' : 'records';
        setState(`${dataPoints.length.toLocaleString()} ${label}`);
      } catch (error) { toast(error.message); setState('Load failed'); }
    }
    byId('calibrate-button').addEventListener('click', async () => {
      const bssid = [...selectedBssids][0];
      if (!bssid || byId('show-all-bssids').checked || !hasKnownPosition()) return;
      const button = byId('calibrate-button'); button.disabled = true; button.textContent = 'Calibrating…';
      try {
        const response = await fetch('/api/calibrate', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
          bssid,
          known_lat: Number(byId('known-lat').value),
          known_lon: Number(byId('known-lon').value),
          cell_size: Number(byId('cell-size').value),
        })});
        const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Could not calibrate path loss.');
        calibratedPathLoss.set(bssid, result.path_loss_n);
        byId('path-loss').value = result.path_loss_n.toFixed(2);
        byId('calibration-result').textContent = `Calibrated n=${result.path_loss_n.toFixed(2)} · fit RMSE ${result.rmse.toFixed(1)} dB · ${result.cells} cells`;
      } catch (error) { byId('calibration-result').textContent = error.message; }
      finally {
        button.textContent = 'Calibrate path loss';
        button.disabled = byId('show-all-bssids').checked || selectedBssids.size !== 1 || !hasKnownPosition();
      }
    });
    byId('estimate-button').addEventListener('click', async () => {
      const all = byId('show-all-bssids').checked;
      const bssids = [...selectedBssids];
      if (!all && !bssids.length) return toast('Select at least one BSSID to estimate.');
      const targetBssids = all ? availableBssids.map(item => item.bssid) : bssids;
      const pathLossByBssid = Object.fromEntries(targetBssids
        .filter(bssid => calibratedPathLoss.has(bssid))
        .map(bssid => [bssid, calibratedPathLoss.get(bssid)]));
      const button = byId('estimate-button'); button.disabled = true; button.textContent = 'Estimating selected…';
      try {
        const response = await fetch('/api/estimates', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
          all, bssids, cell_size: Number(byId('cell-size').value), path_loss_n: Number(byId('path-loss').value),
          path_loss_by_bssid: pathLossByBssid,
        })});
        const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Could not estimate position.');
        estimateMarkers.forEach(marker => map.removeLayer(marker)); estimateMarkers = [];
        byId('estimate-view-toggle').checked = false;
        applyPositionView();
        const colors = ['#f37cbb', '#ffd166', '#5bc0eb', '#9bdeac', '#c8a2ff', '#ff8a65'];
        const successes = result.estimates.filter(estimate => !estimate.error);
        result.estimates.forEach((estimate, index) => {
          if (estimate.error) return;
          const color = colors[index % colors.length];
          const marker = L.circleMarker([estimate.lat, estimate.lon], {
            radius: 10, color, fillColor: color, fillOpacity: .95, weight: 2
          });
          const details = document.createElement('div');
          const title = document.createElement('strong'); title.textContent = estimate.bssid; details.append(title);
          details.append(document.createElement('br'), document.createTextNode('RSSI model position estimate'));
          details.append(document.createElement('br'), document.createTextNode(`RMSE: ${estimate.rmse.toFixed(1)} dB`));
          details.append(document.createElement('br'), document.createTextNode(`Angular coverage: ${estimate.angular_coverage.toFixed(0)}°`));
          marker.bindTooltip(estimate.bssid, {permanent: true, direction: 'top', className: 'map-point-tooltip'});
          marker.bindPopup(details);
          estimateMarkers.push(marker);
        });
        const failures = result.estimates.filter(estimate => estimate.error);
        const compareToSurvey = !all && bssids.length === 1 && hasKnownPosition();
        if (compareToSurvey) {
          successes.forEach(estimate => {
            estimate.position_error_m = distanceMeters(
              Number(byId('known-lat').value), Number(byId('known-lon').value), estimate.lat, estimate.lon
            );
          });
        }
        byId('estimate-summary').textContent = `${successes.length} position${successes.length === 1 ? '' : 's'} calculated${failures.length ? ` · ${failures.length} need more capture points` : ''}.`;
        const groups = byId('estimate-groups'); groups.replaceChildren();
        const appendGroup = (title, items, describe) => {
          if (!items.length) return;
          const group = document.createElement('details'); group.className = 'estimate-group';
          const heading = document.createElement('summary'); heading.textContent = `${title} (${items.length})`; group.append(heading);
          items.forEach(item => {
            const line = document.createElement('div'); line.className = 'estimate-item';
            line.textContent = describe(item); group.append(line);
          });
          groups.append(group);
        };
        appendGroup('Calculated positions', successes, estimate =>
          `${estimate.bssid} · ${estimate.lat.toFixed(6)}, ${estimate.lon.toFixed(6)} · n=${estimate.path_loss_n.toFixed(2)} · RMSE ${estimate.rmse.toFixed(1)} dB · ${estimate.angular_coverage.toFixed(0)}° coverage${estimate.position_error_m === undefined ? '' : ` · Survey error ${estimate.position_error_m.toFixed(1)} m`}`);
        appendGroup('Needs more capture', failures, estimate => {
          const reason = estimate.error.includes('6 distinct')
            ? 'Needs at least 6 distinct capture cells.'
            : estimate.error;
          return `${estimate.bssid} · ${reason}`;
        });
        byId('estimate-details').hidden = result.estimates.length === 0;
        byId('estimate-view-toggle').disabled = successes.length === 0;
        byId('estimate-view-toggle').checked = successes.length > 0;
        applyPositionView();
        if (successes.length) map.fitBounds(L.latLngBounds(successes.map(estimate => [estimate.lat, estimate.lon])).pad(.2));
        if (failures.length) toast(`${failures.length} selected BSSID(s) lacked enough distinct capture cells.`);
        else toast(`${successes.length} position estimate(s) added.`);
      } catch (error) { toast(error.message); }
      finally { button.disabled = false; button.textContent = 'Estimate locations'; }
    });

    byId('export-csv').addEventListener('click', () => {
      const visible = dataPoints.filter(point => map.hasLayer(point.marker));
      if (!visible.length) return toast('There are no visible records to export.');
      const escapeCsv = value => `"${String(value ?? '').replaceAll('"', '""')}"`;
      const lines = [['bssid', 'lat', 'lon', 'signal_dbm', 'frequency', 'band', 'time_utc'], ...visible.map(point => [point.bssid, point.lat, point.lon, point.signal, point.frequency, point.band, point.time_utc])];
      const blob = new Blob([lines.map(row => row.map(escapeCsv).join(',')).join('\r\n')], {type: 'text/csv;charset=utf-8'});
      const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = 'kismet_records.csv'; link.click(); URL.revokeObjectURL(link.href);
    });

    async function loadStartupDatabase() {
      try {
        const response = await fetch('/api/bootstrap');
        const result = await response.json();
        if (!result.loaded) return;
        availableBssids = result.bssids;
        byId('show-all-bssids').disabled = availableBssids.length === 0;
        byId('bssid-search').disabled = availableBssids.length === 0;
        byId('add-bssid').disabled = availableBssids.length === 0;
        byId('show-all-bssids').checked = true;
        const suggestions = byId('bssid-options'); suggestions.replaceChildren();
        availableBssids.forEach(info => {
          const option = document.createElement('option'); option.value = info.bssid;
          option.label = `${info.bssid} · ${bssidDetails(info)}`; option.title = bssidDetails(info);
          suggestions.append(option);
        });
        renderBandFilters(result.bands);
        renderTableFilters(result.schema);
        filterDefaults = result.filters;
        byId('date-start').value = filterDefaults.dateStart;
        byId('date-end').value = filterDefaults.dateEnd;
        renderBssidSelection();
        byId('data-summary').textContent = `${result.count.toLocaleString()} records from ${result.bssids.length} BSSID${result.bssids.length === 1 ? '' : 's'}.`;
        setState('Database loaded');
        await loadSelectedBssids();
      } catch (error) {
        toast(error.message);
      }
    }
    loadStartupDatabase();
  </script>
</body>
</html>
"""


def quote_identifier(identifier):
  return '"' + identifier.replace('"', '""') + '"'


def inspect_database(database_path, allowed_bssids=None):
  connection = sqlite3.connect(database_path)
  schema = []
  timestamps = []
  try:
    table_names = [
      row[0]
      for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
      )
    ]
    for table_name in table_names:
      quoted_table = quote_identifier(table_name)
      column_rows = connection.execute(
        f"PRAGMA table_info({quoted_table})"
      ).fetchall()
      columns = [{"name": row[1], "type": (row[2] or "").upper()} for row in column_rows]
      column_names = {column["name"].lower(): column for column in columns}
      mac_columns = [
        column_names[name]["name"]
        for name in ("sourcemac", "devmac", "bssid", "mac")
        if name in column_names
      ]

      where = ""
      params = []
      if allowed_bssids:
        if mac_columns:
          match = ",".join("?" for _ in allowed_bssids)
          where = " WHERE (" + " OR ".join(
            f"UPPER(CAST({quote_identifier(column)} AS TEXT)) IN ({match})"
            for column in mac_columns
          ) + ")"
          params = list(allowed_bssids) * len(mac_columns)
        elif table_name.upper() != "KISMET":
          where = " WHERE 0"

      row_count = connection.execute(
        f"SELECT COUNT(*) FROM {quoted_table}{where}", params
      ).fetchone()[0]
      column_filters = []
      for column in columns:
        name = column["name"]
        declared_type = column["type"]
        quoted_column = quote_identifier(name)
        aggregate = connection.execute(
          f"SELECT MIN({quoted_column}), MAX({quoted_column}), "
          f"MAX({quoted_column} IS NOT NULL) "
          f"FROM {quoted_table}{where}", params
        ).fetchone()
        has_values = bool(aggregate[2])
        descriptor = {
          "name": name,
          "type": declared_type or "UNDECLARED",
          "has_values": has_values,
        }

        if "BLOB" in declared_type:
          descriptor["kind"] = "blob"
        elif any(token in declared_type for token in ("INT", "REAL", "FLOA", "DOUB", "NUM", "DEC")):
          descriptor["kind"] = "number"
          minimum, maximum = aggregate[0], aggregate[1]
          try:
            minimum = float(minimum)
            maximum = float(maximum)
          except (TypeError, ValueError):
            minimum = maximum = None
          if minimum is not None and maximum is not None and math.isfinite(minimum) and math.isfinite(maximum):
            base_step = 1 if "INT" in declared_type else 0.00001
            descriptor.update({
              "min": minimum,
              "max": maximum,
              "step": max(base_step, (maximum - minimum) / 1000),
            })
          else:
            descriptor["has_values"] = False
        else:
          distinct = connection.execute(
            f"SELECT DISTINCT {quoted_column} FROM {quoted_table}"
            f"{where}{' AND' if where else ' WHERE'} {quoted_column} IS NOT NULL "
            f"ORDER BY {quoted_column} LIMIT 51",
            params,
          ).fetchall()
          if len(distinct) <= 50:
            descriptor["kind"] = "enum"
            descriptor["values"] = [str(row[0]) for row in distinct]
          else:
            descriptor["kind"] = "text"

        if name.lower() in {"ts_sec", "timestamp", "first_time", "last_time"} and aggregate[0] is not None and aggregate[1] is not None:
          try:
            timestamps.extend((float(aggregate[0]), float(aggregate[1])))
          except (TypeError, ValueError):
            pass
        column_filters.append(descriptor)

      normalized_names = set(column_names)
      schema.append({
        "name": table_name,
        "rows": row_count,
        "has_coordinates": "lat" in normalized_names and "lon" in normalized_names,
        "columns": column_filters,
      })
  finally:
    connection.close()

  date_values = []
  for timestamp in timestamps:
    try:
      date_values.append(datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat())
    except (OverflowError, OSError, ValueError):
      pass
  return schema, (min(date_values), max(date_values)) if date_values else ("", "")


def load_geographic_records(database_path, selected_bssids=None):
  connection = sqlite3.connect(database_path)
  connection.row_factory = sqlite3.Row
  records = []
  try:
    tables = connection.execute(
      "SELECT name FROM sqlite_master WHERE type='table' "
      "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    selected = {value.upper() for value in selected_bssids or []}
    for (table_name,) in tables:
      quoted_table = quote_identifier(table_name)
      columns = [row[1] for row in connection.execute(f"PRAGMA table_info({quoted_table})")]
      by_lower = {column.lower(): column for column in columns}
      if "lat" not in by_lower or "lon" not in by_lower:
        continue
      mac_column = next(
        (by_lower[name] for name in ("sourcemac", "devmac", "bssid", "mac") if name in by_lower),
        None,
      )
      if selected and not mac_column:
        continue
      where = " WHERE lat IS NOT NULL AND lon IS NOT NULL"
      params = []
      if selected:
        match = ",".join("?" for _ in selected)
        where += f" AND UPPER(CAST({quote_identifier(mac_column)} AS TEXT)) IN ({match})"
        params.extend(sorted(selected))
      query = f"SELECT * FROM {quoted_table}{where}"
      for row in connection.execute(query, params):
        values = {}
        for column in columns:
          raw = row[column]
          if isinstance(raw, bytes):
            values[column] = None
            values[f"__has_blob__:{column}"] = True
          elif isinstance(raw, (int, float)):
            values[column] = raw if math.isfinite(float(raw)) else None
          else:
            values[column] = raw
        try:
          lat = float(row[by_lower["lat"]])
          lon = float(row[by_lower["lon"]])
        except (TypeError, ValueError):
          continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
          continue
        if lat == 0 and lon == 0:
          continue
        bssid = str(row[mac_column]).strip().upper() if mac_column and row[mac_column] else None
        signal_column = next((by_lower[name] for name in ("signal", "strongest_signal") if name in by_lower), None)
        frequency_column = by_lower.get("frequency")
        signal = row[signal_column] if signal_column else None
        try:
          signal = float(signal) if signal is not None else None
          if signal == 0 or (signal is not None and not math.isfinite(signal)):
            signal = None
        except (TypeError, ValueError):
          signal = None
        frequency = row[frequency_column] if frequency_column else None
        time_column = next((by_lower[name] for name in ("ts_sec", "timestamp", "first_time") if name in by_lower), None)
        time_value = row[time_column] if time_column else None
        try:
          time_utc = datetime.fromtimestamp(float(time_value), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if time_value is not None else None
        except (OverflowError, OSError, TypeError, ValueError):
          time_utc = None
        records.append({
          "table": table_name,
          "bssid": bssid,
          "lat": lat,
          "lon": lon,
                    "signal": signal,
          "frequency": float(frequency) if frequency is not None else None,
          "frequency_mhz": normalize_frequency_mhz(frequency) if frequency is not None else None,
          "band": get_band(frequency) if frequency is not None else "unknown",
          "time_utc": time_utc,
          "date": time_utc[:10] if time_utc else None,
          "values": values,
        })
  finally:
    connection.close()
  return records


def load_device_labels(database_path, selected_bssids=None):
  connection = sqlite3.connect(database_path)
  devices = []
  selected = {value.upper() for value in selected_bssids or []}
  try:
    tables = {
      row[0]
      for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if "devices" not in tables:
      return devices
    columns = {
      row[1].lower(): row[1]
      for row in connection.execute('PRAGMA table_info("devices")')
    }
    required = {"devmac", "avg_lat", "avg_lon", "device"}
    if not required.issubset(columns):
      return devices
    query = (
      f"SELECT {quote_identifier(columns['devmac'])}, "
      f"{quote_identifier(columns['avg_lat'])}, {quote_identifier(columns['avg_lon'])}, "
      f"{quote_identifier(columns['device'])} FROM {quote_identifier('devices')}"
    )
    for mac, lat, lon, device_blob in connection.execute(query):
      if not mac or device_blob is None:
        continue
      mac = str(mac).strip().upper()
      if selected and mac not in selected:
        continue
      try:
        lat = float(lat)
        lon = float(lon)
      except (TypeError, ValueError):
        continue
      if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        continue
      try:
        details = json.loads(device_blob)
      except (TypeError, ValueError):
        details = {}
      name = str(
        details.get("kismet.device.base.name")
        or details.get("kismet.device.base.commonname")
        or mac
      ).strip()
      if not name:
        name = mac
      frequency = details.get("kismet.device.base.frequency")
      frequency_mhz = normalize_frequency_mhz(frequency) if frequency is not None else None
      devices.append({
        "mac": mac,
        "name": name,
        "lat": lat,
        "lon": lon,
        "frequency_mhz": frequency_mhz if frequency_mhz is not None and math.isfinite(frequency_mhz) else None,
      })
  finally:
    connection.close()
  return devices


STATE = {
  "df": pd.DataFrame(),
  "allowed": set(),
  "allowlist_active": False,
  "database_path": None,
  "schema": [],
  "database_owned": False,
}
STATE_LOCK = threading.RLock()


def initialize_input_database(database_path, allowed_bssids=None):
    database_path = os.path.abspath(os.fspath(database_path))
    if not os.path.isfile(database_path):
        raise ValueError(f"Input database not found: {database_path}")
    allowed = {str(item).strip().upper() for item in (allowed_bssids or []) if str(item).strip()}
    df = load_packets(database_path, allowed)
    if df.empty:
        raise ValueError("No usable records found in the input database.")
    schema, database_dates = inspect_database(database_path, allowed or None)
    with STATE_LOCK:
        STATE["df"] = df
        STATE["allowed"] = set(df["sourcemac"].unique())
        STATE["allowlist_active"] = bool(allowed)
        STATE["database_path"] = database_path
        STATE["schema"] = schema
        STATE["database_owned"] = False
    return database_dates


class KismetRequestHandler(BaseHTTPRequestHandler):
    app_html = APP_HTML

    def _send(self, status, body, content_type):
        payload = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, status, data):
        self._send(status, json.dumps(data, allow_nan=False), "application/json; charset=utf-8")

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 2_000_000:
            raise ValueError("Invalid request size.")
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        if self.path == "/":
            self._send(200, self.app_html, "text/html; charset=utf-8")
            return
        if self.path == "/api/bootstrap":
            self._send_bootstrap()
            return
        self._send_json(404, {"error": "Not found."})

    def _send_bootstrap(self):
        with STATE_LOCK:
            df = STATE["df"]
            database_path = STATE["database_path"]
            allowed = set(STATE["allowed"])
            allowlist_active = STATE["allowlist_active"]
            schema = STATE["schema"]
        if not database_path or df.empty:
            self._send_json(200, {"loaded": False})
            return
        bssid_details = []
        for bssid, observations in df.groupby("sourcemac"):
            bssid_details.append({
                "bssid": bssid,
                "records": len(observations),
                "bands": sorted(observations["band"].unique()),
                "first_seen": observations["time_utc"].min().strftime("%Y-%m-%d"),
                "last_seen": observations["time_utc"].max().strftime("%Y-%m-%d"),
                "min_signal": round(float(observations["signal"].min()), 1),
                "max_signal": round(float(observations["signal"].max()), 1),
            })
        dates = df["time_utc"].dt.strftime("%Y-%m-%d").sort_values().unique()
        self._send_json(200, {
            "loaded": True,
            "count": len(df),
            "bssids": bssid_details,
            "bands": sorted(set(df["band"].dropna().unique()) | {"unknown"}),
            "filters": {"dateStart": dates[0] if len(dates) else "", "dateEnd": dates[-1] if len(dates) else ""},
            "schema": schema,
            "allowlist_active": allowlist_active,
        })

    def do_POST(self):
        try:
            if self.path == "/api/database":
                self._load_database()
            elif self.path == "/api/records":
              self._send_records()
            elif self.path == "/api/devices":
              self._send_devices()
            elif self.path == "/api/estimates":
                self._estimate()
            elif self.path == "/api/calibrate":
              self._calibrate()
            else:
                self._send_json(404, {"error": "Not found."})
        except (ValueError, sqlite3.Error) as error:
            self._send_json(400, {"error": str(error)})
        except Exception:
            self._send_json(500, {"error": "Internal server error."})

    def _load_database(self):
        use_allowlist = self.headers.get("X-Use-Allowlist", "false").lower() == "true"
        allowed = {
            item.strip().upper()
            for item in self.headers.get("X-Lab-Bssids", "").replace(",", " ").split()
            if item.strip()
        }
        if use_allowlist and not allowed:
            raise ValueError("Enter at least one BSSID before loading.")
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("The uploaded database is empty.")

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".kismet") as temp_file:
                temp_path = temp_file.name
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("Database upload ended unexpectedly.")
                    temp_file.write(chunk)
                    remaining -= len(chunk)
            df = load_packets(temp_path, allowed if use_allowlist else set())
            if df.empty:
                raise ValueError("No usable records were found for the selected BSSIDs.")
            schema, database_dates = inspect_database(
              temp_path, allowed if use_allowlist else None
            )
            bssid_details = []
            for bssid, observations in df.groupby("sourcemac"):
                bssid_details.append({
                    "bssid": bssid,
                    "records": len(observations),
                    "bands": sorted(observations["band"].unique()),
                    "first_seen": observations["time_utc"].min().strftime("%Y-%m-%d"),
                    "last_seen": observations["time_utc"].max().strftime("%Y-%m-%d"),
                    "min_signal": round(float(observations["signal"].min()), 1),
                    "max_signal": round(float(observations["signal"].max()), 1),
                })
            bands = sorted(set(df["band"].dropna().unique()) | {"unknown"})
            filters = {
                "dateStart": database_dates[0],
                "dateEnd": database_dates[1],
            }
            previous_path = None
            previous_owned = False
            with STATE_LOCK:
                previous_path = STATE["database_path"]
                previous_owned = STATE["database_owned"]
                STATE["df"] = df
                STATE["allowed"] = {item["bssid"] for item in bssid_details}
                STATE["allowlist_active"] = use_allowlist
                STATE["database_path"] = temp_path
                STATE["schema"] = schema
                STATE["database_owned"] = True
                temp_path = None
            if previous_owned and previous_path and os.path.exists(previous_path):
                os.remove(previous_path)
            self._send_json(200, {
                "count": len(df),
                "bssids": bssid_details,
                "bands": bands,
                "filters": filters,
                "schema": schema,
                "allowlist_active": use_allowlist,
            })
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

    def _selected_data(self, bssid):
        selected = str(bssid).strip().upper()
        with STATE_LOCK:
            df = STATE["df"]
            if df.empty:
                raise ValueError("Load a Kismet database first.")
            if selected == "__ALL__":
                return df.copy()
            if selected not in STATE["allowed"]:
                raise ValueError("Select a BSSID from the loaded database.")
            return df[df["sourcemac"] == selected].copy()

    def _send_records(self):
        request = self._read_json()
        with STATE_LOCK:
            database_path = STATE["database_path"]
            allowed = set(STATE["allowed"])
            allowlist_active = STATE["allowlist_active"]
        if not database_path or not os.path.isfile(database_path):
            raise ValueError("Load a Kismet database first.")
        if request.get("all"):
            selected = allowed if allowlist_active else None
        else:
            raw_bssids = request.get("bssids", [])
            if not isinstance(raw_bssids, list):
                raise ValueError("BSSIDs must be provided as a list.")
            selected = {str(item).strip().upper() for item in raw_bssids if str(item).strip()}
            if not selected:
                raise ValueError("Select at least one BSSID.")
            if not selected.issubset(allowed):
                raise ValueError("Select BSSIDs from the loaded database.")
        records = load_geographic_records(database_path, selected)
        self._send_json(200, {"records": records})

    def _send_devices(self):
        request = self._read_json()
        with STATE_LOCK:
            database_path = STATE["database_path"]
            allowed = set(STATE["allowed"])
            allowlist_active = STATE["allowlist_active"]
        if not database_path or not os.path.isfile(database_path):
            raise ValueError("Load a Kismet database first.")
        if request.get("all"):
            selected = allowed if allowlist_active else None
        else:
            raw_bssids = request.get("bssids", [])
            if not isinstance(raw_bssids, list):
                raise ValueError("BSSIDs must be provided as a list.")
            selected = {str(item).strip().upper() for item in raw_bssids if str(item).strip()}
            if not selected:
                raise ValueError("Select at least one BSSID.")
            if not selected.issubset(allowed):
                raise ValueError("Select BSSIDs from the loaded database.")
        self._send_json(200, {"devices": load_device_labels(database_path, selected)})

    def _estimate(self):
        request = self._read_json()
        with STATE_LOCK:
            allowed = set(STATE["allowed"])
            all_data = STATE["df"]
        if all_data.empty:
            raise ValueError("Load a Kismet database first.")
        if request.get("all"):
            bssids = sorted(allowed)
        else:
            raw_bssids = request.get("bssids", [])
            if not isinstance(raw_bssids, list):
                raise ValueError("BSSIDs must be provided as a list.")
            bssids = sorted({str(item).strip().upper() for item in raw_bssids if str(item).strip()})
            if not bssids:
                raise ValueError("Select at least one BSSID to estimate.")
            if not set(bssids).issubset(allowed):
                raise ValueError("Select BSSIDs from the loaded database.")
        cell_size = float(request.get("cell_size", 5))
        default_path_loss_n = float(request.get("path_loss_n", 2.5))
        path_loss_by_bssid = request.get("path_loss_by_bssid", {})
        if not isinstance(path_loss_by_bssid, dict):
            raise ValueError("Per-BSSID path-loss values must be an object.")
        if not (0 < cell_size <= 1000) or not (0 < default_path_loss_n <= 10):
            raise ValueError("Cell size and path-loss exponent must be positive and reasonable.")
        results = []
        for bssid in bssids:
            df = all_data[all_data["sourcemac"] == bssid].copy()
            try:
                path_loss_n = float(path_loss_by_bssid.get(bssid, default_path_loss_n))
                if not 0 < path_loss_n <= 10:
                    raise ValueError("Path-loss exponent must be positive and reasonable.")
                cells, origin_lat, origin_lon = aggregate_cells(df, cell_size)
                estimate = estimate_position(cells, origin_lat, origin_lon, path_loss_n)
                results.append({"bssid": bssid, "path_loss_n": path_loss_n, **estimate})
            except ValueError as error:
                results.append({"bssid": bssid, "error": str(error)})
        self._send_json(200, {"estimates": results})

    def _calibrate(self):
        request = self._read_json()
        bssid = str(request.get("bssid", "")).strip().upper()
        df = self._selected_data(bssid)
        known_lat = float(request.get("known_lat"))
        known_lon = float(request.get("known_lon"))
        cell_size = float(request.get("cell_size", 5))
        if not (-90 <= known_lat <= 90 and -180 <= known_lon <= 180):
            raise ValueError("Surveyed coordinates must be valid latitude/longitude values.")
        if not (0 < cell_size <= 1000):
            raise ValueError("Cell size must be positive and reasonable.")
        cells, origin_lat, origin_lon = aggregate_cells(df, cell_size)
        result = calibrate_path_loss(cells, origin_lat, origin_lon, known_lat, known_lon)
        self._send_json(200, {"bssid": bssid, **result})

    def log_message(self, format, *args):
        return


def run_app(host="127.0.0.1", port=0, open_browser=True, input_path=None,
            allowed_bssids=None, cell_size=5, path_loss_n=2.5):
    """Run the local web application until interrupted.

    ``port=0`` asks the operating system to select an available port. The
    browser URL uses loopback when the server is bound to all interfaces.
    """
    if input_path:
        initialize_input_database(input_path, allowed_bssids)
    configured_html = APP_HTML.replace('value="5"', f'value="{cell_size}"', 1)
    configured_html = configured_html.replace('value="2.5"', f'value="{path_loss_n}"', 1)
    KismetRequestHandler.app_html = configured_html
    server = ThreadingHTTPServer((host, port), KismetRequestHandler)
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    if ":" in browser_host and not browser_host.startswith("["):
        browser_host = f"[{browser_host}]"
    url = f"http://{browser_host}:{server.server_port}/"
    print(f"Kismet Field Map is running at {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        database_path = STATE.get("database_path")
        if STATE.get("database_owned") and database_path and os.path.exists(database_path):
            os.remove(database_path)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run the KISMAP local web interface."
    )
    parser.add_argument("--config", help="JSON configuration file.")
    parser.add_argument("--input", help="Kismet SQLite database to load at startup.")
    parser.add_argument("--host", help="Interface to bind to.")
    parser.add_argument("--port", type=int, help="TCP port; 0 selects an available port.")
    parser.add_argument("--no-browser", action="store_true", default=None, help="Do not open a browser.")
    parser.add_argument("--browser", action="store_true", default=None, help="Open a browser.")
    parser.add_argument("--cell-size", type=float, help="Default estimate cell size in meters.")
    parser.add_argument("--path-loss", type=float, help="Default path-loss exponent.")
    parser.add_argument("--allowlist", nargs="+", help="BSSIDs to load.")
    args = parser.parse_args(argv)
    config = {}
    if args.config:
        with open(args.config, encoding="utf-8") as config_file:
            config = json.load(config_file)
        if not isinstance(config, dict):
            parser.error("Configuration must be a JSON object.")

    def setting(name, default):
        value = getattr(args, name)
        return value if value is not None else config.get(name, default)

    host = setting("host", "127.0.0.1")
    port = setting("port", 0)
    input_path = setting("input", None)
    cell_size = setting("cell_size", 5)
    path_loss_n = setting("path_loss", 2.5)
    allowed_bssids = args.allowlist if args.allowlist is not None else config.get("allowlist", [])
    open_browser = config.get("browser", True)
    if args.no_browser:
        open_browser = False
    if args.browser:
        open_browser = True
    if not isinstance(allowed_bssids, list):
        allowed_bssids = str(allowed_bssids).replace(",", " ").split()
    try:
        port = int(port)
        cell_size = float(cell_size)
        path_loss_n = float(path_loss_n)
    except (TypeError, ValueError):
        parser.error("port, cell_size, and path_loss must be numeric")
    if not 0 <= port <= 65535:
        parser.error("--port must be between 0 and 65535")
    if not 0 < cell_size <= 1000 or not 0 < path_loss_n <= 10:
        parser.error("--cell-size must be > 0 and --path-loss must be between 0 and 10")
    run_app(host, port, open_browser, input_path, allowed_bssids, cell_size, path_loss_n)


if __name__ == "__main__":
    main()
