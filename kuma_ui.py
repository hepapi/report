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
<title>Uptime Kuma Rapor</title>
<style>
  :root {
    --bg: #FAFAFA;
    --card: #FFFFFF;
    --border: #E5E7EB;
    --border-strong: #D1D5DB;
    --text: #111827;
    --text-muted: #6B7280;
    --primary: #1976D2;
    --primary-hover: #1565C0;
    --primary-soft: #E3F2FD;
    --success: #2E7D32;
    --warning: #F57C00;
    --danger: #C62828;
    --shadow: 0 1px 2px rgba(0,0,0,0.04), 0 1px 3px rgba(0,0,0,0.06);
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 Oxygen, Ubuntu, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
  }
  .container {
    max-width: 640px;
    margin: 0 auto;
    padding: 32px 20px 80px;
  }
  header {
    margin-bottom: 24px;
  }
  h1 {
    font-size: 24px;
    font-weight: 700;
    margin: 0 0 4px;
    letter-spacing: -0.02em;
  }
  header p {
    margin: 0;
    color: var(--text-muted);
    font-size: 14px;
  }
  header code {
    font-family: "JetBrains Mono", "SF Mono", Menlo, Consolas, monospace;
    background: var(--primary-soft);
    color: var(--primary);
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 12px;
  }
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 20px;
    margin-bottom: 16px;
    box-shadow: var(--shadow);
  }
  .card-label {
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    margin-bottom: 12px;
  }
  .filter-tabs {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 4px;
    background: var(--bg);
    padding: 4px;
    border-radius: 8px;
    margin-bottom: 16px;
  }
  .filter-tabs button {
    background: transparent;
    border: none;
    padding: 8px 4px;
    font-size: 13px;
    font-weight: 500;
    color: var(--text-muted);
    cursor: pointer;
    border-radius: 6px;
    transition: all 0.15s;
    font-family: inherit;
  }
  .filter-tabs button:hover { color: var(--text); }
  .filter-tabs button.active {
    background: var(--card);
    color: var(--primary);
    box-shadow: var(--shadow);
  }
  .filter-input { display: none; }
  .filter-input.active { display: block; }
  label {
    display: block;
    font-size: 13px;
    font-weight: 500;
    margin-bottom: 6px;
  }
  select, input[type="text"], input[type="date"], input[type="number"] {
    width: 100%;
    padding: 10px 12px;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    font-size: 14px;
    font-family: inherit;
    background: var(--card);
    color: var(--text);
    transition: border-color 0.15s, box-shadow 0.15s;
  }
  select:focus, input:focus {
    outline: none;
    border-color: var(--primary);
    box-shadow: 0 0 0 3px rgba(25, 118, 210, 0.1);
  }
  .hint {
    font-size: 12px;
    color: var(--text-muted);
    margin-top: 6px;
  }
  .date-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }
  .presets {
    display: flex;
    gap: 6px;
    margin-top: 10px;
    flex-wrap: wrap;
  }
  .presets button {
    background: var(--bg);
    border: 1px solid var(--border);
    padding: 6px 12px;
    border-radius: 6px;
    font-size: 12px;
    cursor: pointer;
    color: var(--text-muted);
    font-family: inherit;
  }
  .presets button:hover {
    background: var(--primary-soft);
    color: var(--primary);
    border-color: var(--primary);
  }
  .toggle {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 12px;
    background: var(--bg);
    border-radius: 8px;
    cursor: pointer;
    border: 1px solid var(--border);
    transition: all 0.15s;
  }
  .toggle:hover { border-color: var(--border-strong); }
  .toggle input {
    margin: 3px 0 0;
    accent-color: var(--primary);
    cursor: pointer;
  }
  .toggle-content { flex: 1; }
  .toggle-title { font-weight: 500; font-size: 14px; }
  .toggle-desc { font-size: 12px; color: var(--text-muted); margin-top: 2px; }
  .preview {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 16px;
    background: var(--primary-soft);
    border-radius: 8px;
    margin-bottom: 16px;
  }
  .preview-num {
    font-size: 22px;
    font-weight: 700;
    color: var(--primary);
    font-variant-numeric: tabular-nums;
  }
  .preview-label {
    font-size: 12px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
  }
  .preview-right { text-align: right; }
  .preview-note { font-size: 12px; color: var(--text-muted); }
  .btn-primary {
    width: 100%;
    background: var(--primary);
    color: white;
    border: none;
    padding: 14px;
    font-size: 15px;
    font-weight: 600;
    border-radius: 8px;
    cursor: pointer;
    transition: background 0.15s, transform 0.05s;
    font-family: inherit;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
  }
  .btn-primary:hover { background: var(--primary-hover); }
  .btn-primary:active { transform: translateY(1px); }
  .btn-primary:disabled {
    background: var(--border-strong);
    cursor: not-allowed;
    transform: none;
  }
  .spinner {
    width: 16px;
    height: 16px;
    border: 2px solid rgba(255,255,255,0.3);
    border-top-color: white;
    border-radius: 50%;
    animation: spin 0.6s linear infinite;
    display: none;
  }
  .btn-primary.loading .spinner { display: inline-block; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .status {
    margin-top: 12px;
    padding: 10px 14px;
    border-radius: 6px;
    font-size: 13px;
    display: none;
  }
  .status.success {
    background: #E8F5E9;
    color: var(--success);
    border: 1px solid #A5D6A7;
    display: block;
  }
  .status.error {
    background: #FFEBEE;
    color: var(--danger);
    border: 1px solid #EF9A9A;
    display: block;
  }
  .monitor-select {
    min-height: 140px;
  }
  select[multiple] {
    padding: 4px;
  }
  select[multiple] option {
    padding: 6px 8px;
    border-radius: 4px;
  }
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>Uptime Kuma Rapor</h1>
    <p>Kaynak: <code>{{ db_path }}</code> · {{ total_monitors }} monitor</p>
  </header>

  <form id="report-form">
    <div class="card">
      <div class="card-label">Filtre</div>
      <div class="filter-tabs" role="tablist">
        <button type="button" data-tab="page" class="active">Status Page</button>
        <button type="button" data-tab="tag">Tag</button>
        <button type="button" data-tab="parent">Parent</button>
        <button type="button" data-tab="ids">Belirli</button>
        <button type="button" data-tab="all">Tumu</button>
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

    <div class="card">
      <div class="card-label">Tarih araligi</div>
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

    <div class="card">
      <div class="card-label">Secenekler</div>
      <label for="title">Rapor basligi <span style="color: var(--text-muted); font-weight: 400;">(bos birakirsan otomatik doldurulur)</span></label>
      <input type="text" id="title" name="title" placeholder="Uptime Rapor" autocomplete="off" style="margin-bottom: 14px;">
      <label class="toggle">
        <input type="checkbox" name="detailed" id="detailed">
        <div class="toggle-content">
          <div class="toggle-title">Detayli rapor</div>
          <div class="toggle-desc">Her monitor icin ayri sayfa (yanit suresi grafigi, gunluk uptime tablosu, down olaylari). Cok monitor varsa buyuk PDF uretir.</div>
        </div>
      </label>
      <label class="toggle" style="margin-top: 10px;">
        <input type="checkbox" name="include_groups" id="include_groups">
        <div class="toggle-content">
          <div class="toggle-title">Group tipi monitorlari da dahil et</div>
          <div class="toggle-desc">Varsayilan olarak alt monitoru olan (Group tipi) monitorlar cikarilir. Cunku Uptime Kuma bunlara cocuklarindan turetilmis heartbeat kaydediyor - dahil edince ayni DOWN olaylari iki kez sayilir ve aggregate istatistikleri bozar.</div>
        </div>
      </label>
    </div>

    <div class="preview">
      <div>
        <div class="preview-label">Rapora girecek</div>
        <div><span class="preview-num" id="preview-count">-</span> <span style="color: var(--text-muted); font-size: 14px;">monitor</span></div>
      </div>
      <div class="preview-right">
        <div class="preview-note" id="preview-note">Filtre secince guncellenir</div>
      </div>
    </div>

    <button type="submit" class="btn-primary" id="submit-btn">
      <span class="spinner"></span>
      <span class="btn-text">PDF olustur</span>
    </button>

    <div class="status" id="status"></div>
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
document.querySelectorAll('.filter-tabs button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.filter-tabs button').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.filter-input').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
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
  const activeTab = document.querySelector('.filter-tabs button.active').dataset.tab;
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
  const tab = document.querySelector('.filter-tabs button.active').dataset.tab;
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
      previewNote.style.color = 'var(--danger)';
    } else {
      const pages = detailed ? `~${d.count * 3} sayfa PDF` : '1 sayfalik ozet';
      previewNote.textContent = pages;
      previewNote.style.color = 'var(--text-muted)';
    }
  } catch (e) {
    previewCount.textContent = '-';
    previewNote.textContent = 'Hata';
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
    p.add_argument('--api-url',
                   help='kuma_api_server.py adresi, orn. http://uptime-host:8090 '
                        '(--db yerine; uzak sunucudaki canli DB\'ye HTTP ile baglanir)')
    p.add_argument('--api-key', help='--api-url ile kullanilacak API anahtari '
                                      '(KUMA_API_KEY ortam degiskeni ile ayni)')
    p.add_argument('--host', default='127.0.0.1',
                   help='Sadece localhost icin 127.0.0.1 (varsayilan), '
                        'LAN icin 0.0.0.0')
    p.add_argument('--port', type=int, default=5000)
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
    API_KEY = args.api_key or os.environ.get('KUMA_API_KEY')

    print(f'→ Kaynak: {DB_PATH or API_URL}')
    print(f'→ Tarayicidan ac: http://{args.host}:{args.port}')
    print('  (Durdurmak icin Ctrl+C)')
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == '__main__':
    main()
