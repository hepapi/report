#!/usr/bin/env python3
"""
Uptime Kuma DB API sunucusu (sidecar)
=======================================

Uptime Kuma container'i ile ayni sunucuda / ayni docker network'unde,
onun veri volume'unu SALT-OKUNUR olarak mount ederek calisir. Rapor
uygulamasi (kuma_report.py / kuma_ui.py) artik kuma.db'nin bir backup
kopyasini cekmek yerine bu servise HTTP istegi atar.

Ortam degiskenleri:
  KUMA_DB_PATH   kuma.db dosyasinin yolu (varsayilan: /app/data/kuma.db,
                 yani resmi Uptime Kuma image'inin data dizini)
  KUMA_API_KEY   Bearer/X-API-Key ile beklenen gizli anahtar.
                 Bos birakilirsa (ONERILMEZ) auth kapali calisir.

Calistirma (lokal test):
  KUMA_DB_PATH=./kuma.db KUMA_API_KEY=secret python3 kuma_api_server.py

Docker/production icin Dockerfile ve docker-compose ornegi
kuma_api_server.Dockerfile ve docker-compose.kuma-api.yml.example
dosyalarinda.
"""
import os
from functools import wraps

from flask import Flask, jsonify, request

from kuma_dbaccess import LocalBackend

app = Flask(__name__)

DB_PATH = os.environ.get('KUMA_DB_PATH', '/app/data/kuma.db')
API_KEY = os.environ.get('KUMA_API_KEY', '')

_MISSING_PARAMS_ERROR = 'monitor_id, from, to zorunlu'

_backend = None


def get_backend():
    global _backend
    if _backend is None:
        _backend = LocalBackend(DB_PATH)
    return _backend


def require_api_key(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if API_KEY:
            supplied = request.headers.get('X-API-Key', '')
            if supplied != API_KEY:
                return jsonify({'error': 'unauthorized'}), 401
        return fn(*args, **kwargs)
    return wrapper


@app.route('/health', methods=['GET'])
def health():
    # Auth'suz: container orchestrator health-check'i icin.
    return jsonify({'status': 'ok', 'db': DB_PATH})


@app.route('/monitors', methods=['GET'])
@require_api_key
def monitors():
    return jsonify(get_backend().list_monitors())


@app.route('/status-pages', methods=['GET'])
@require_api_key
def status_pages():
    return jsonify(get_backend().list_status_pages())


@app.route('/tags', methods=['GET'])
@require_api_key
def tags():
    return jsonify(get_backend().list_tags())


@app.route('/parents', methods=['GET'])
@require_api_key
def parents():
    return jsonify(get_backend().list_parents())


@app.route('/resolve-monitors', methods=['POST'])
@require_api_key
def resolve_monitors():
    data = request.get_json(silent=True) or {}
    result = get_backend().resolve_monitors(
        status_page=data.get('status_page'),
        tag=data.get('tag'),
        parent=data.get('parent'),
        monitor=data.get('monitor', 'all'),
        include_groups=bool(data.get('include_groups', False)),
    )
    return jsonify(result)


@app.route('/summary', methods=['GET'])
@require_api_key
def summary():
    monitor_id = request.args.get('monitor_id', type=int)
    date_from = request.args.get('from')
    date_to = request.args.get('to')
    if monitor_id is None or not date_from or not date_to:
        return jsonify({'error': _MISSING_PARAMS_ERROR}), 400
    return jsonify(get_backend().get_summary(monitor_id, date_from, date_to))


@app.route('/summaries-bulk', methods=['POST'])
@require_api_key
def summaries_bulk():
    data = request.get_json(silent=True) or {}
    monitor_ids = data.get('monitor_ids') or []
    date_from = data.get('from')
    date_to = data.get('to')
    if not date_from or not date_to:
        return jsonify({'error': 'monitor_ids, from, to zorunlu'}), 400
    result = get_backend().get_summaries_bulk(monitor_ids, date_from, date_to)
    # JSON object anahtarlari string olmak zorunda (int monitor_id -> str)
    return jsonify({str(mid): row for mid, row in result.items()})


@app.route('/group-summary', methods=['POST'])
@require_api_key
def group_summary():
    data = request.get_json(silent=True) or {}
    monitor_ids = data.get('monitor_ids') or []
    date_from = data.get('from')
    date_to = data.get('to')
    if not date_from or not date_to:
        return jsonify({'error': 'from, to zorunlu'}), 400
    return jsonify(get_backend().get_group_summary(monitor_ids, date_from, date_to))


@app.route('/daily-stats', methods=['GET'])
@require_api_key
def daily_stats():
    monitor_id = request.args.get('monitor_id', type=int)
    date_from = request.args.get('from')
    date_to = request.args.get('to')
    if monitor_id is None or not date_from or not date_to:
        return jsonify({'error': _MISSING_PARAMS_ERROR}), 400
    return jsonify(get_backend().get_daily_stats(monitor_id, date_from, date_to))


@app.route('/down-events', methods=['GET'])
@require_api_key
def down_events():
    monitor_id = request.args.get('monitor_id', type=int)
    date_from = request.args.get('from')
    date_to = request.args.get('to')
    if monitor_id is None or not date_from or not date_to:
        return jsonify({'error': _MISSING_PARAMS_ERROR}), 400
    return jsonify(get_backend().get_down_events(monitor_id, date_from, date_to))


@app.route('/response-series', methods=['GET'])
@require_api_key
def response_series():
    monitor_id = request.args.get('monitor_id', type=int)
    date_from = request.args.get('from')
    date_to = request.args.get('to')
    if monitor_id is None or not date_from or not date_to:
        return jsonify({'error': _MISSING_PARAMS_ERROR}), 400
    times, pings = get_backend().get_response_series(monitor_id, date_from, date_to)
    return jsonify({
        'times': [t.isoformat() for t in times],
        'pings': pings,
    })


if __name__ == '__main__':
    if not API_KEY:
        print('UYARI: KUMA_API_KEY tanimli degil, API auth olmadan aciliyor!')
    print(f'-> DB: {DB_PATH}')
    port = int(os.environ.get('PORT', '8090'))
    # threaded=True: birden fazla istemci (veya bir istemcinin ust uste
    # baglantilari) ayni anda bekletilmeden isleme alinsin diye.
    app.run(host='0.0.0.0', port=port, threaded=True)
