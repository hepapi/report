#!/usr/bin/env python3
"""
Uptime Kuma PDF Rapor Web UI
=============================

kuma_report.py ile ayni klasorde calisir.

Kurulum (tek seferlik):
  pip install flask

Calistirma (lokal db dosyasi ile):
  python kuma_ui.py --db kuma.db
  python kuma_ui.py --db kuma.db --port 8080   # farkli port
  python kuma_ui.py --db kuma.db --host 0.0.0.0  # LAN'a ac

Calistirma (uzak sunucudaki kuma_api_server.py'a HTTP ile baglanarak,
backup kopyasi gerekmeden canli veriyi kullanmak icin):
  python kuma_ui.py --api-url http://uptime-host:8090 --api-key secret

Sonra tarayicidan: http://localhost:5000
"""
import argparse
import io
import os
import sys
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request, send_file

# kuma_report modulunden fonksiyonlari kullan
try:
    from kuma_report import build_report
    from kuma_dbaccess import make_backend
except ImportError:
    print("✗ Hata: kuma_report.py / kuma_dbaccess.py bu klasorde bulunamadi.")
    print("  UI'yi kuma_report.py ile ayni klasorden calistir.")
    sys.exit(1)


app = Flask(__name__)
DB_PATH = None
API_URL = None
API_KEY = None


def get_backend():
    """Her istek icin taze bir backend olusturur (thread-safety icin)."""
    return make_backend(db_path=DB_PATH, api_url=API_URL, api_key=API_KEY)


HTML = r"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pegasus · Uptime Rapor Konsolu</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@600;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet">
<style>
  /* ---- tokens: light (default) ---- */
  :root {
    --bg: #FBF9F4;
    --panel: #F3EEE1;
    --card: #FFFFFF;
    --border: #E7E0CE;
    --border-strong: #D6CCB0;
    --text: #1B1D22;
    --text-muted: #6B6E76;
    --accent: #FFC933;
    --accent-hover: #F0B900;
    --accent-ink: #2E2400;
    --good: #1E9D57;
    --warn: #E07A12;
    --critical: #D8402B;
    --shadow: 0 1px 2px rgba(20,16,4,.05), 0 6px 20px -4px rgba(20,16,4,.10);
    --focus-ring: 0 0 0 3px rgba(255,201,51,.45);
    --font-display: 'Sora', ui-sans-serif, system-ui, sans-serif;
    --font-body: 'IBM Plex Sans', ui-sans-serif, system-ui, sans-serif;
    --font-mono: 'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  /* ---- tokens: dark, OS preference ---- */
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #14161B;
      --panel: #1B1E24;
      --card: #20232B;
      --border: #2B2F38;
      --border-strong: #3A3F4A;
      --text: #F1F0EA;
      --text-muted: #9BA0AA;
      --accent: #FFC933;
      --accent-hover: #FFD65C;
      --accent-ink: #241C00;
      --good: #3FCB80;
      --warn: #FF9A3D;
      --critical: #FF6B5E;
      --shadow: 0 1px 2px rgba(0,0,0,.35), 0 10px 28px -8px rgba(0,0,0,.55);
      --focus-ring: 0 0 0 3px rgba(255,201,51,.35);
    }
  }
  /* ---- tokens: explicit toggle overrides (win over the query above) ---- */
  :root[data-theme="dark"] {
    --bg: #14161B; --panel: #1B1E24; --card: #20232B;
    --border: #2B2F38; --border-strong: #3A3F4A;
    --text: #F1F0EA; --text-muted: #9BA0AA;
    --accent: #FFC933; --accent-hover: #FFD65C; --accent-ink: #241C00;
    --good: #3FCB80; --warn: #FF9A3D; --critical: #FF6B5E;
    --shadow: 0 1px 2px rgba(0,0,0,.35), 0 10px 28px -8px rgba(0,0,0,.55);
    --focus-ring: 0 0 0 3px rgba(255,201,51,.35);
  }
  :root[data-theme="light"] {
    --bg: #FBF9F4; --panel: #F3EEE1; --card: #FFFFFF;
    --border: #E7E0CE; --border-strong: #D6CCB0;
    --text: #1B1D22; --text-muted: #6B6E76;
    --accent: #FFC933; --accent-hover: #F0B900; --accent-ink: #2E2400;
    --good: #1E9D57; --warn: #E07A12; --critical: #D8402B;
    --shadow: 0 1px 2px rgba(20,16,4,.05), 0 6px 20px -4px rgba(20,16,4,.10);
    --focus-ring: 0 0 0 3px rgba(255,201,51,.45);
  }

  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    margin: 0;
    font-family: var(--font-body);
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
    font-size: 14px;
    -webkit-font-smoothing: antialiased;
  }
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation-duration: 0.001ms !important; transition-duration: 0.001ms !important; }
  }

  .shell { max-width: 1080px; margin: 0 auto; padding: 28px 20px 96px; }

  /* ---- top bar / brand ---- */
  .topbar {
    display: flex; align-items: center; justify-content: space-between;
    gap: 16px; flex-wrap: wrap; margin-bottom: 28px;
  }
  .brand { display: flex; align-items: center; gap: 12px; }
  .brand-mark {
    width: 38px; height: 38px; flex: none; border-radius: 10px;
    background: #1B1D22; color: var(--accent);
    display: flex; align-items: center; justify-content: center;
  }
  .brand-text { display: flex; flex-direction: column; line-height: 1.25; }
  .brand-eyebrow {
    font-family: var(--font-body); font-size: 11px; font-weight: 600;
    letter-spacing: .12em; text-transform: uppercase; color: var(--text-muted);
  }
  .brand-title {
    font-family: var(--font-display); font-size: 19px; font-weight: 700;
    letter-spacing: -0.01em; text-wrap: balance;
  }
  .source-pill {
    display: flex; align-items: center; gap: 8px;
    background: var(--card); border: 1px solid var(--border);
    border-radius: 999px; padding: 7px 14px; box-shadow: var(--shadow);
    font-size: 12.5px; color: var(--text-muted); flex-wrap: wrap;
  }
  .source-pill .dot {
    width: 7px; height: 7px; border-radius: 50%; background: var(--good);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--good) 20%, transparent);
    flex: none;
  }
  .source-pill code {
    font-family: var(--font-mono); color: var(--text); font-size: 12px;
    max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .source-pill strong { color: var(--text); font-weight: 600; font-variant-numeric: tabular-nums; }

  /* ---- console layout: rail + action pane ---- */
  .console { display: grid; grid-template-columns: 340px 1fr; gap: 20px; align-items: start; }
  @media (max-width: 880px) { .console { grid-template-columns: 1fr; } }

  .panel {
    background: var(--card); border: 1px solid var(--border);
    border-radius: 12px; padding: 18px; box-shadow: var(--shadow);
  }
  .rail { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
  .action { display: flex; flex-direction: column; gap: 16px; position: sticky; top: 20px; min-width: 0; }

  .panel-title {
    display: flex; align-items: center; gap: 8px;
    font-family: var(--font-body); font-size: 12px; font-weight: 600;
    text-transform: uppercase; letter-spacing: .08em; color: var(--text-muted);
    margin: 0 0 14px;
  }
  .panel-title svg { width: 15px; height: 15px; flex: none; color: var(--text-muted); }

  /* ---- segmented filter-type control ---- */
  .segmented {
    display: grid; grid-template-columns: repeat(5, 1fr); gap: 3px;
    background: var(--panel); border: 1px solid var(--border);
    padding: 3px; border-radius: 9px; margin-bottom: 16px;
  }
  .segmented button {
    min-width: 0;
    background: transparent; border: none; padding: 8px 4px;
    font-family: var(--font-body); font-size: 12.5px; font-weight: 500;
    color: var(--text-muted); cursor: pointer; border-radius: 6px;
    transition: background .15s, color .15s; white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis;
  }
  .segmented button:hover { color: var(--text); }
  .segmented button.active {
    background: var(--accent); color: var(--accent-ink); font-weight: 600;
  }

  .filter-input { display: none; }
  .filter-input.active { display: block; }

  label { display: block; font-size: 12.5px; font-weight: 500; margin-bottom: 6px; }
  .label-hint { color: var(--text-muted); font-weight: 400; }

  select, input[type="text"], input[type="date"] {
    width: 100%; padding: 9px 11px; border: 1px solid var(--border-strong);
    border-radius: 8px; font-size: 13.5px; font-family: var(--font-body);
    background: var(--bg); color: var(--text);
    transition: border-color .15s, box-shadow .15s;
  }
  select:focus-visible, input:focus-visible {
    outline: none; border-color: var(--accent-hover); box-shadow: var(--focus-ring);
  }
  .hint { font-size: 11.5px; color: var(--text-muted); margin-top: 6px; line-height: 1.5; }

  .monitor-select { min-height: 160px; padding: 4px; }
  select[multiple] option { padding: 6px 8px; border-radius: 5px; font-size: 13px; }

  /* ---- date range ---- */
  .date-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .date-row > div { min-width: 0; }
  input[type="date"] { min-width: 0; }
  .presets { display: flex; gap: 6px; margin-top: 10px; flex-wrap: wrap; }
  .presets button {
    background: var(--panel); border: 1px solid var(--border);
    padding: 6px 11px; border-radius: 999px; font-size: 11.5px;
    font-family: var(--font-body); cursor: pointer; color: var(--text-muted);
    transition: border-color .15s, color .15s;
  }
  .presets button:hover { color: var(--text); border-color: var(--border-strong); }

  /* ---- switches (replace old checkbox+description block) ---- */
  .switch-row {
    display: flex; align-items: flex-start; gap: 12px;
    padding: 12px 0; border-top: 1px solid var(--border);
  }
  .switch-row:first-of-type { border-top: none; padding-top: 4px; }
  .switch-copy { flex: 1; min-width: 0; }
  .switch-title { font-size: 13.5px; font-weight: 500; }
  .switch-desc { font-size: 11.5px; color: var(--text-muted); margin-top: 3px; line-height: 1.5; }
  .switch {
    position: relative; flex: none; width: 38px; height: 22px; margin-top: 1px;
  }
  .switch input { position: absolute; opacity: 0; width: 100%; height: 100%; margin: 0; cursor: pointer; }
  .switch-track {
    position: absolute; inset: 0; border-radius: 999px;
    background: var(--border-strong); transition: background .15s;
  }
  .switch-track::after {
    content: ''; position: absolute; top: 2px; left: 2px; width: 18px; height: 18px;
    border-radius: 50%; background: var(--card); box-shadow: 0 1px 2px rgba(0,0,0,.25);
    transition: transform .15s;
  }
  .switch input:checked ~ .switch-track { background: var(--accent); }
  .switch input:checked ~ .switch-track::after { transform: translateX(16px); }
  .switch input:focus-visible ~ .switch-track { box-shadow: var(--focus-ring); }

  /* ---- action pane: stat readout ---- */
  .stat-panel { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  .stat-label {
    display: block; font-size: 11px; font-weight: 600; text-transform: uppercase;
    letter-spacing: .08em; color: var(--text-muted); margin-bottom: 6px;
  }
  .stat-value {
    font-family: var(--font-mono); font-size: 30px; font-weight: 600;
    font-variant-numeric: tabular-nums; letter-spacing: -0.01em;
  }
  .stat-unit { font-size: 13px; color: var(--text-muted); margin-left: 4px; }
  .stat-note { font-size: 12px; color: var(--text-muted); text-align: right; }
  .stat-note.is-empty { color: var(--critical); }

  .btn-primary {
    width: 100%; background: var(--accent); color: var(--accent-ink);
    border: none; padding: 14px; font-size: 14.5px; font-weight: 600;
    border-radius: 10px; cursor: pointer; font-family: var(--font-body);
    transition: background .15s, transform .05s;
    display: flex; align-items: center; justify-content: center; gap: 8px;
  }
  .btn-primary svg { width: 16px; height: 16px; }
  .btn-primary:hover { background: var(--accent-hover); }
  .btn-primary:active { transform: translateY(1px); }
  .btn-primary:focus-visible { outline: none; box-shadow: var(--focus-ring); }
  .btn-primary:disabled { background: var(--border-strong); color: var(--text-muted); cursor: not-allowed; transform: none; }

  .spinner {
    width: 15px; height: 15px; border: 2px solid rgba(0,0,0,.2);
    border-top-color: var(--accent-ink); border-radius: 50%;
    animation: spin .6s linear infinite; display: none;
  }
  .btn-primary.loading .spinner { display: inline-block; }
  @keyframes spin { to { transform: rotate(360deg); } }

  .status {
    padding: 11px 14px; border-radius: 9px; font-size: 13px; display: none;
    border: 1px solid transparent;
  }
  .status.success { background: color-mix(in srgb, var(--good) 14%, var(--card)); color: var(--good); border-color: color-mix(in srgb, var(--good) 35%, transparent); display: block; }
  .status.error { background: color-mix(in srgb, var(--critical) 12%, var(--card)); color: var(--critical); border-color: color-mix(in srgb, var(--critical) 35%, transparent); display: block; }
</style>
</head>
<body>
<div class="shell">
  <header class="topbar">
    <div class="brand">
      <span class="brand-mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none">
          <path d="M3 15.5 L11 5 L14.4 5 L8 15.5 Z" fill="currentColor"/>
          <path d="M10 15.5 L18 5 L21.4 5 L15 15.5 Z" fill="currentColor" opacity=".55"/>
        </svg>
      </span>
      <div class="brand-text">
        <span class="brand-eyebrow">Pegasus</span>
        <span class="brand-title">Uptime Rapor Konsolu</span>
      </div>
    </div>
    <div class="source-pill">
      <span class="dot" aria-hidden="true"></span>
      <span>Kaynak</span>
      <code>{{ db_path }}</code>
      <span>·</span>
      <strong>{{ total_monitors }}</strong>
      <span>monitor</span>
    </div>
  </header>

  <form id="report-form" class="console">
    <section class="rail" aria-label="Filtreler">
      <div class="panel">
        <h2 class="panel-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M4 6h16M7 12h10M10 18h4"/></svg>
          Kapsam
        </h2>
        <div class="segmented" role="tablist">
          <button type="button" data-tab="page" class="active" role="tab" aria-selected="true">Sayfa</button>
          <button type="button" data-tab="tag" role="tab" aria-selected="false">Tag</button>
          <button type="button" data-tab="parent" role="tab" aria-selected="false">Parent</button>
          <button type="button" data-tab="ids" role="tab" aria-selected="false">Belirli</button>
          <button type="button" data-tab="all" role="tab" aria-selected="false">Tumu</button>
        </div>

        <div class="filter-input active" data-panel="page">
          <label for="status_page">Status page</label>
          <select name="status_page" id="status_page">
            {% for p in pages %}
            <option value="{{ p.slug }}">{{ p.title }} ({{ p.monitor_count }} monitor)</option>
            {% endfor %}
            {% if not pages %}
            <option value="" disabled>Hic status page yok</option>
            {% endif %}
          </select>
        </div>

        <div class="filter-input" data-panel="tag">
          <label for="tag">Tag</label>
          <select name="tag" id="tag">
            {% for t in tags %}
            <option value="{{ t.key }}">{{ t.display }} ({{ t.count }} monitor)</option>
            {% endfor %}
            {% if not tags %}
            <option value="" disabled>Hic tag yok</option>
            {% endif %}
          </select>
        </div>

        <div class="filter-input" data-panel="parent">
          <label for="parent">Parent monitor</label>
          <select name="parent" id="parent">
            {% for m in parents %}
            <option value="{{ m.id }}">{{ m.name }} ({{ m.child_count }} alt)</option>
            {% endfor %}
            {% if not parents %}
            <option value="" disabled>Hic parent monitor yok</option>
            {% endif %}
          </select>
          <div class="hint">Sadece "Group" tipi (alt monitoru olan) monitorlar.</div>
        </div>

        <div class="filter-input" data-panel="ids">
          <label for="monitor_ids">Monitor sec (Ctrl/Cmd + tikla ile coklu secim)</label>
          <select name="monitor_ids" id="monitor_ids" multiple class="monitor-select">
            {% for m in all_monitors %}
            <option value="{{ m.id }}">[{{ m.id }}] {{ m.name }}</option>
            {% endfor %}
          </select>
        </div>

        <div class="filter-input" data-panel="all">
          <div class="hint">Tum aktif monitorlar rapora dahil edilecek.</div>
        </div>
      </div>

      <div class="panel">
        <h2 class="panel-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 9.5h17M8 3v3.5M16 3v3.5"/></svg>
          Tarih araligi
        </h2>
        <div class="date-row">
          <div>
            <label for="from">Baslangic</label>
            <input type="date" id="from" name="from" required>
          </div>
          <div>
            <label for="to">Bitis</label>
            <input type="date" id="to" name="to" required>
          </div>
        </div>
        <div class="presets">
          <button type="button" data-days="7">Son 7 gun</button>
          <button type="button" data-days="30">Son 30 gun</button>
          <button type="button" data-days="90">Son 90 gun</button>
          <button type="button" data-days="180">Son 6 ay</button>
          <button type="button" data-days="365">Son 1 yil</button>
        </div>
      </div>

      <div class="panel">
        <h2 class="panel-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M4 7h9M4 12h16M4 17h9"/><circle cx="16" cy="7" r="1.8" fill="currentColor" stroke="none"/><circle cx="9" cy="17" r="1.8" fill="currentColor" stroke="none"/></svg>
          Secenekler
        </h2>
        <label for="title">Rapor basligi <span class="label-hint">(bos birakirsan otomatik doldurulur)</span></label>
        <input type="text" id="title" name="title" placeholder="Uptime Rapor" autocomplete="off" style="margin-bottom: 4px;">

        <div class="switch-row">
          <label class="switch">
            <input type="checkbox" name="detailed" id="detailed">
            <span class="switch-track" aria-hidden="true"></span>
          </label>
          <div class="switch-copy">
            <div class="switch-title">Detayli rapor</div>
            <div class="switch-desc">Her monitor icin ayri sayfa (yanit suresi grafigi, gunluk uptime tablosu, down olaylari). Cok monitor varsa buyuk PDF uretir.</div>
          </div>
        </div>
        <div class="switch-row">
          <label class="switch">
            <input type="checkbox" name="include_groups" id="include_groups">
            <span class="switch-track" aria-hidden="true"></span>
          </label>
          <div class="switch-copy">
            <div class="switch-title">Group tipi monitorlari da dahil et</div>
            <div class="switch-desc">Varsayilan olarak alt monitoru olan monitorler cikarilir - dahil edilirse ayni DOWN olaylari iki kez sayilir.</div>
          </div>
        </div>
      </div>
    </section>

    <section class="action" aria-label="Onizleme ve olustur">
      <div class="panel stat-panel">
        <div>
          <span class="stat-label">Rapora girecek</span>
          <span class="stat-value" id="preview-count">–</span>
          <span class="stat-unit">monitor</span>
        </div>
        <div class="stat-note" id="preview-note">Filtre secince guncellenir</div>
      </div>

      <button type="submit" class="btn-primary" id="submit-btn">
        <span class="spinner" aria-hidden="true"></span>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v11M7 11l5 5 5-5"/><path d="M4 18v1.5A1.5 1.5 0 0 0 5.5 21h13a1.5 1.5 0 0 0 1.5-1.5V18"/></svg>
        <span class="btn-text">PDF olustur</span>
      </button>

      <div class="status" id="status" role="status"></div>
    </section>
  </form>
</div>

<script>
const form = document.getElementById('report-form');
const previewCount = document.getElementById('preview-count');
const previewNote = document.getElementById('preview-note');
const submitBtn = document.getElementById('submit-btn');
const btnText = submitBtn.querySelector('.btn-text');
const statusEl = document.getElementById('status');

// Sekme degistirme
document.querySelectorAll('.segmented button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.segmented button').forEach(b => {
      b.classList.remove('active');
      b.setAttribute('aria-selected', 'false');
    });
    document.querySelectorAll('.filter-input').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    btn.setAttribute('aria-selected', 'true');
    document.querySelector(`[data-panel="${btn.dataset.tab}"]`).classList.add('active');
    updateTitlePlaceholder();
    updatePreview();
  });
});

// Tarih preset'leri
document.querySelectorAll('.presets button').forEach(btn => {
  btn.addEventListener('click', () => {
    const days = parseInt(btn.dataset.days, 10);
    const to = new Date();
    const from = new Date();
    from.setDate(to.getDate() - days);
    document.getElementById('from').value = from.toISOString().slice(0, 10);
    document.getElementById('to').value = to.toISOString().slice(0, 10);
  });
});

// Varsayilan tarih: son 30 gun
(() => {
  const to = new Date();
  const from = new Date();
  from.setDate(to.getDate() - 30);
  document.getElementById('from').value = from.toISOString().slice(0, 10);
  document.getElementById('to').value = to.toISOString().slice(0, 10);
})();

// Aktif filtre bilgisini topla
function getFilterData() {
  const activeTab = document.querySelector('.segmented button.active').dataset.tab;
  const data = {
    filter_type: activeTab,
    include_groups: document.getElementById('include_groups').checked,
  };
  if (activeTab === 'page') data.status_page = document.getElementById('status_page').value;
  if (activeTab === 'tag') data.tag = document.getElementById('tag').value;
  if (activeTab === 'parent') data.parent = document.getElementById('parent').value;
  if (activeTab === 'ids') {
    data.monitor_ids = Array.from(document.getElementById('monitor_ids').selectedOptions)
      .map(o => o.value).join(',');
  }
  return data;
}

// Baslik placeholder'ini secime gore guncelle
function updateTitlePlaceholder() {
  const tab = document.querySelector('.segmented button.active').dataset.tab;
  let suggested = 'Uptime Rapor';
  const stripCount = t => t.replace(/\s*\(\d+[^)]*\)\s*$/, '').trim();

  if (tab === 'page') {
    const opt = document.getElementById('status_page').selectedOptions[0];
    if (opt && opt.value) suggested = 'Uptime Rapor - ' + stripCount(opt.text);
  } else if (tab === 'tag') {
    const opt = document.getElementById('tag').selectedOptions[0];
    if (opt && opt.value) suggested = 'Uptime Rapor - ' + stripCount(opt.text);
  } else if (tab === 'parent') {
    const opt = document.getElementById('parent').selectedOptions[0];
    if (opt && opt.value) suggested = 'Uptime Rapor - ' + stripCount(opt.text);
  } else if (tab === 'ids') {
    const n = document.getElementById('monitor_ids').selectedOptions.length;
    suggested = n ? `Uptime Rapor - ${n} monitor` : 'Uptime Rapor';
  } else if (tab === 'all') {
    suggested = 'Uptime Rapor - Tum Monitorlar';
  }
  document.getElementById('title').placeholder = suggested;
}

// Filtre degisince monitor sayisini onizle
async function updatePreview() {
  previewCount.textContent = '...';
  previewNote.textContent = 'Hesaplaniyor';
  previewNote.classList.remove('is-empty');
  try {
    const r = await fetch('/api/count', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(getFilterData()),
    });
    const d = await r.json();
    previewCount.textContent = d.count.toLocaleString('tr-TR');
    const detailed = document.getElementById('detailed').checked;
    if (d.count === 0) {
      previewNote.textContent = 'Filtreye uyan monitor yok';
      previewNote.classList.add('is-empty');
    } else {
      const pages = detailed ? `~${d.count * 3} sayfa PDF` : '1 sayfalik ozet';
      previewNote.textContent = pages;
    }
  } catch (e) {
    previewCount.textContent = '-';
    previewNote.textContent = 'Hata';
    previewNote.classList.add('is-empty');
  }
}

// Her secim degisikliginde tetikle
['status_page', 'tag', 'parent', 'monitor_ids', 'detailed', 'include_groups'].forEach(id => {
  const el = document.getElementById(id);
  if (el) {
    el.addEventListener('change', () => {
      updateTitlePlaceholder();
      updatePreview();
    });
  }
});

// Ilk yukleme
updateTitlePlaceholder();
updatePreview();

// Form gonderme
form.addEventListener('submit', async (e) => {
  e.preventDefault();
  submitBtn.disabled = true;
  submitBtn.classList.add('loading');
  btnText.textContent = 'PDF hazirlaniyor...';
  statusEl.className = 'status';
  statusEl.textContent = '';

  const body = {
    ...getFilterData(),
    from: document.getElementById('from').value,
    to: document.getElementById('to').value,
    detailed: document.getElementById('detailed').checked,
    title: document.getElementById('title').value.trim(),
  };

  try {
    const r = await fetch('/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const err = await r.json();
      throw new Error(err.error || 'Bilinmeyen hata');
    }
    const blob = await r.blob();
    const cd = r.headers.get('Content-Disposition') || '';
    const match = cd.match(/filename="?([^"]+)"?/);
    const filename = match ? match[1] : 'kuma_rapor.pdf';

    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);

    statusEl.className = 'status success';
    statusEl.textContent = `✓ ${filename} indirildi`;
  } catch (err) {
    statusEl.className = 'status error';
    statusEl.textContent = `✗ ${err.message}`;
  } finally {
    submitBtn.disabled = false;
    submitBtn.classList.remove('loading');
    btnText.textContent = 'PDF olustur';
  }
});
</script>
</body>
</html>"""


# ==================== FLASK ENDPOINTS ====================

@app.route('/')
def index():
    backend = get_backend()

    # Status pages + monitor sayisi
    pages_raw = backend.list_status_pages()
    pages = []
    for p in pages_raw:
        count = sum(len(g['monitors']) for g in p['groups'])
        pages.append({
            'slug': p['slug'], 'title': p['title'], 'monitor_count': count,
        })

    # Tag'ler
    tags_raw = backend.list_tags()
    tags = []
    for tid, tname, tvalue, cnt in tags_raw:
        key = f'{tname}:{tvalue}' if tvalue else tname
        display = f'{tname}: {tvalue}' if tvalue else tname
        tags.append({'key': key, 'display': display, 'count': cnt})

    # Parent monitorlar (cocugu olanlar)
    parents = [{'id': mid, 'name': name, 'child_count': cnt}
               for mid, name, cnt in backend.list_parents()]

    # Tum monitorlar (secim listesi)
    all_mons = backend.list_monitors()
    all_monitors = [{'id': mid, 'name': name}
                    for mid, name, active in all_mons if active]

    backend.close()

    return render_template_string(
        HTML,
        db_path=DB_PATH or API_URL,
        total_monitors=len(all_monitors),
        pages=pages,
        tags=tags,
        parents=parents,
        all_monitors=all_monitors,
    )


class _Filters:
    """resolve_monitors() cagrisi icin filtre degerlerini tutar."""
    status_page = None
    tag = None
    parent = None
    monitor = 'all'
    include_groups = False


def _build_filters_from_json(data):
    f = _Filters()
    ft = data.get('filter_type', 'all')
    if ft == 'page':
        f.status_page = data.get('status_page') or None
    elif ft == 'tag':
        f.tag = data.get('tag') or None
    elif ft == 'parent':
        f.parent = data.get('parent') or None
    elif ft == 'ids':
        ids = data.get('monitor_ids', '').strip()
        f.monitor = ids if ids else 'all'
    # else: 'all' — hepsi
    f.include_groups = bool(data.get('include_groups', False))
    return f


@app.route('/api/count', methods=['POST'])
def count():
    """Filtre icin monitor sayisini dondur (canli onizleme)."""
    data = request.get_json(silent=True) or {}
    backend = get_backend()
    try:
        f = _build_filters_from_json(data)
        monitors = backend.resolve_monitors(
            status_page=f.status_page, tag=f.tag, parent=f.parent,
            monitor=f.monitor, include_groups=f.include_groups)
        return jsonify({'count': len(monitors)})
    finally:
        backend.close()


def _status_page_title(backend, slug_or_title):
    for p in backend.list_status_pages():
        if slug_or_title in (p['slug'], p['title']):
            return p['title']
    return slug_or_title


def _parent_name(backend, id_or_name):
    try:
        pid = int(id_or_name)
        match_fn = lambda mid, mname: mid == pid
    except ValueError:
        match_fn = lambda mid, mname: mname == id_or_name
    for mid, mname, _cnt in backend.list_parents():
        if match_fn(mid, mname):
            return mname
    return id_or_name


def _default_title(backend, f, filter_type):
    """Backend'den okunabilir isimlerle akilli default baslik uretir."""
    if filter_type == 'page' and f.status_page:
        return f'Uptime Rapor - {_status_page_title(backend, f.status_page)}'
    if filter_type == 'tag' and f.tag:
        return f'Uptime Rapor - {f.tag}'
    if filter_type == 'parent' and f.parent:
        return f'Uptime Rapor - {_parent_name(backend, f.parent)}'
    if filter_type == 'ids' and f.monitor != 'all':
        cnt = len([x for x in f.monitor.split(',') if x.strip()])
        return f'Uptime Rapor - {cnt} monitor'
    return 'Uptime Rapor - Tum Monitorlar'


def _slugify(text):
    """Baslik'tan dosya adi icin guvenli slug uretir."""
    import re
    from kuma_report import ascii_safe
    clean = ascii_safe(text).lower()
    clean = re.sub(r'[^a-z0-9]+', '_', clean).strip('_')
    return clean[:80] if clean else 'kuma_rapor'


@app.route('/generate', methods=['POST'])
def generate():
    data = request.get_json(silent=True) or {}
    date_from = data.get('from')
    date_to = data.get('to')
    if not date_from or not date_to:
        return jsonify({'error': 'Tarih araligi eksik'}), 400

    backend = get_backend()
    try:
        f = _build_filters_from_json(data)
        monitors = backend.resolve_monitors(
            status_page=f.status_page, tag=f.tag, parent=f.parent,
            monitor=f.monitor, include_groups=f.include_groups)
        if not monitors:
            return jsonify({'error': 'Filtreye uyan monitor yok'}), 400

        # Kullanici baslik verdiyse onu kullan, yoksa akilli default
        ft = data.get('filter_type', 'all')
        user_title = (data.get('title') or '').strip()
        title = user_title if user_title else _default_title(backend, f, ft)

        # Dosya adini basliktan uret
        fname = f'{_slugify(title)}_{date_from}_{date_to}.pdf'

        # PDF'i memory'de olustur
        buf = io.BytesIO()
        build_report(
            backend, monitors, date_from, date_to, buf,
            report_title=title,
            detailed=bool(data.get('detailed', False)),
        )
        buf.seek(0)
        return send_file(
            buf, mimetype='application/pdf',
            as_attachment=True, download_name=fname,
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        backend.close()


# ==================== MAIN ====================

def main():
    p = argparse.ArgumentParser(description='Uptime Kuma PDF rapor web UI')
    p.add_argument('--db', help='SQLite DB dosyasi (lokal mod)')
    p.add_argument('--api-url', default=os.environ.get('KUMA_API_URL'),
                   help='kuma_api_server.py adresi, orn. http://uptime-host:8090 '
                        '(--db yerine; uzak sunucudaki canli DB\'ye HTTP ile baglanir. '
                        'KUMA_API_URL ortam degiskeninden de okunur — container icinde '
                        'kullanisli.)')
    p.add_argument('--api-key', default=os.environ.get('KUMA_API_KEY'),
                   help='--api-url ile kullanilacak API anahtari '
                        '(KUMA_API_KEY ortam degiskeni ile ayni)')
    p.add_argument('--host', default=os.environ.get('KUMA_UI_HOST', '127.0.0.1'),
                   help='Sadece localhost icin 127.0.0.1 (varsayilan), '
                        'tum arayuzlerden (LAN/internet) erisim icin 0.0.0.0')
    p.add_argument('--port', type=int, default=int(os.environ.get('KUMA_UI_PORT', '5000')))
    p.add_argument('--debug', action='store_true')
    args = p.parse_args()

    if not args.db and not args.api_url:
        print('✗ Hata: --db veya --api-url belirtilmeli')
        sys.exit(1)

    global DB_PATH, API_URL, API_KEY
    if args.db:
        DB_PATH = str(Path(args.db).resolve())
        if not Path(DB_PATH).exists():
            print(f'✗ Hata: {DB_PATH} bulunamadi')
            sys.exit(1)
    API_URL = args.api_url
    API_KEY = args.api_key

    print(f'→ Kaynak: {DB_PATH or API_URL}')
    print(f'→ Tarayicidan ac: http://{args.host}:{args.port}')
    print('  (Durdurmak icin Ctrl+C)')
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == '__main__':
    main()
