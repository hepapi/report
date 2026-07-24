#!/usr/bin/env python3
"""
Uptime Kuma veri erisim katmani
=================================

Iki backend saglar, ikisi de ayni arayuzu (LocalBackend / RemoteBackend)
implemente eder:

  - LocalBackend:  kuma.db dosyasini dogrudan (salt-okunur) acar.
                   kuma_api_server.py bunu, Uptime Kuma container'inin
                   yaninda calisirken kullanir.
  - RemoteBackend: kuma_api_server.py'a HTTP istegi atarak ayni veriyi
                   ceker. kuma_report.py / kuma_ui.py rapor makinesinde
                   bunu kullanir; artik kuma.db'nin lokal bir kopyasina
                   (backup) ihtiyac yoktur.

Her iki backend de su metodlari sunar:
  list_monitors() -> [(id, name, active), ...]
  list_status_pages() -> [{'id', 'slug', 'title', 'groups': [...]}, ...]
  list_tags() -> [(id, name, value, count), ...]
  resolve_monitors(status_page=, tag=, parent=, monitor=, include_groups=)
      -> [(id, name), ...]
  get_summary(monitor_id, date_from, date_to) -> (total, up, down, avg, min, max)
  get_group_summary(monitor_ids, date_from, date_to) -> ayni sekil
  get_daily_stats(monitor_id, date_from, date_to) -> [(date, total, up, down, avg), ...]
  get_down_events(monitor_id, date_from, date_to) -> [(time, msg), ...]
  get_response_series(monitor_id, date_from, date_to) -> ([datetime, ...], [ping, ...])
"""
import json
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime


# ==================== HAM SQL SORGULARI (LocalBackend icin) ====================

def _list_monitors(conn):
    cur = conn.cursor()
    cur.execute("SELECT id, name, active FROM monitor ORDER BY id")
    return cur.fetchall()


def _list_status_pages(conn):
    cur = conn.cursor()
    cur.execute("SELECT id, slug, title FROM status_page ORDER BY title")
    pages = cur.fetchall()

    result = []
    for pid, slug, title in pages:
        cur.execute(
            'SELECT id, name FROM "group" WHERE status_page_id = ? ORDER BY weight',
            (pid,),
        )
        groups = cur.fetchall()
        page_info = {'id': pid, 'slug': slug, 'title': title, 'groups': []}
        for gid, gname in groups:
            cur.execute("""
                SELECT m.id, m.name FROM monitor m
                JOIN monitor_group mg ON mg.monitor_id = m.id
                WHERE mg.group_id = ? ORDER BY mg.weight
            """, (gid,))
            monitors = cur.fetchall()
            page_info['groups'].append({
                'id': gid, 'name': gname, 'monitors': monitors,
            })
        result.append(page_info)
    return result


def _list_tags(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT t.id, t.name, mt.value, COUNT(DISTINCT mt.monitor_id) AS cnt
        FROM tag t LEFT JOIN monitor_tag mt ON mt.tag_id = t.id
        GROUP BY t.id, t.name, mt.value
        ORDER BY t.name, mt.value
    """)
    return cur.fetchall()


def _walk_descendants(conn, roots):
    cur = conn.cursor()
    seen = {m[0]: m for m in roots}
    queue = [m[0] for m in roots]
    while queue:
        current = queue.pop(0)
        cur.execute(
            "SELECT id, name FROM monitor WHERE parent = ? AND active = 1",
            (current,),
        )
        for cid, cname in cur.fetchall():
            if cid not in seen:
                seen[cid] = (cid, cname)
                queue.append(cid)
    return sorted(seen.values(), key=lambda x: x[1])


def _filter_out_groups(conn, monitors):
    """Alt monitoru olan (Group tipi) monitorlari cikartir."""
    if not monitors:
        return monitors
    ids = [m[0] for m in monitors]
    ph = ','.join('?' * len(ids))
    cur = conn.cursor()
    cur.execute(
        f"SELECT DISTINCT parent FROM monitor "
        f"WHERE parent IN ({ph}) AND active = 1",
        ids,
    )
    group_ids = {row[0] for row in cur.fetchall()}
    return [(mid, name) for mid, name in monitors if mid not in group_ids]


def _resolve_monitors(conn, status_page=None, tag=None, parent=None,
                       monitor='all', include_groups=False):
    cur = conn.cursor()

    if status_page:
        cur.execute("""
            SELECT DISTINCT m.id, m.name FROM monitor m
            JOIN monitor_group mg ON mg.monitor_id = m.id
            JOIN "group" g ON g.id = mg.group_id
            JOIN status_page sp ON sp.id = g.status_page_id
            WHERE (sp.slug = ? OR sp.title = ?) AND m.active = 1
        """, (status_page, status_page))
        monitors = _walk_descendants(conn, cur.fetchall())

    elif tag:
        if ':' in tag:
            tname, tvalue = tag.split(':', 1)
            cur.execute("""
                SELECT DISTINCT m.id, m.name FROM monitor m
                JOIN monitor_tag mt ON mt.monitor_id = m.id
                JOIN tag t ON t.id = mt.tag_id
                WHERE t.name = ? AND mt.value = ? AND m.active = 1
                ORDER BY m.name
            """, (tname.strip(), tvalue.strip()))
        else:
            cur.execute("""
                SELECT DISTINCT m.id, m.name FROM monitor m
                JOIN monitor_tag mt ON mt.monitor_id = m.id
                JOIN tag t ON t.id = mt.tag_id
                WHERE t.name = ? AND m.active = 1 ORDER BY m.name
            """, (tag,))
        monitors = _walk_descendants(conn, cur.fetchall())

    elif parent:
        try:
            pid = int(parent)
            cur.execute("SELECT id, name FROM monitor WHERE id = ?", (pid,))
        except ValueError:
            cur.execute("SELECT id, name FROM monitor WHERE name = ?", (parent,))
        root = cur.fetchone()
        if not root:
            return []
        monitors = _walk_descendants(conn, [root])

    elif not monitor or monitor.lower() == 'all':
        cur.execute("SELECT id, name FROM monitor WHERE active = 1 ORDER BY name")
        monitors = cur.fetchall()

    else:
        ids = [int(x.strip()) for x in monitor.split(',')]
        ph = ','.join('?' * len(ids))
        cur.execute(
            f"SELECT id, name FROM monitor WHERE id IN ({ph}) ORDER BY name", ids)
        monitors = cur.fetchall()

    if not include_groups:
        monitors = _filter_out_groups(conn, monitors)

    return monitors


def _list_parents(conn):
    """Cocugu olan (Group tipi) aktif monitorler, cocuk sayisiyla birlikte."""
    cur = conn.cursor()
    cur.execute("""
        SELECT m.id, m.name, COUNT(c.id) AS child_count
        FROM monitor m
        JOIN monitor c ON c.parent = m.id
        WHERE m.active = 1
        GROUP BY m.id, m.name
        ORDER BY m.name
    """)
    return cur.fetchall()


def _get_summary(conn, monitor_id, date_from, date_to):
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*),
               SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END),
               SUM(CASE WHEN status = 0 THEN 1 ELSE 0 END),
               AVG(CASE WHEN status = 1 THEN ping END),
               MIN(CASE WHEN status = 1 THEN ping END),
               MAX(CASE WHEN status = 1 THEN ping END)
        FROM heartbeat
        WHERE monitor_id = ?
          AND time >= ? AND time < datetime(?, '+1 day')
    """, (monitor_id, date_from, date_to))
    return cur.fetchone()


def _get_group_summary(conn, monitor_ids, date_from, date_to):
    if not monitor_ids:
        return (0, 0, 0, None, None, None)
    ph = ','.join('?' * len(monitor_ids))
    cur = conn.cursor()
    cur.execute(f"""
        SELECT COUNT(*),
               SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END),
               SUM(CASE WHEN status = 0 THEN 1 ELSE 0 END),
               AVG(CASE WHEN status = 1 THEN ping END),
               MIN(CASE WHEN status = 1 THEN ping END),
               MAX(CASE WHEN status = 1 THEN ping END)
        FROM heartbeat
        WHERE monitor_id IN ({ph})
          AND time >= ? AND time < datetime(?, '+1 day')
    """, (*monitor_ids, date_from, date_to))
    return cur.fetchone()


def _get_daily_stats(conn, monitor_id, date_from, date_to):
    cur = conn.cursor()
    cur.execute("""
        SELECT date(time), COUNT(*),
               SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END),
               SUM(CASE WHEN status = 0 THEN 1 ELSE 0 END),
               AVG(CASE WHEN status = 1 THEN ping END)
        FROM heartbeat
        WHERE monitor_id = ?
          AND time >= ? AND time < datetime(?, '+1 day')
        GROUP BY date(time) ORDER BY date(time)
    """, (monitor_id, date_from, date_to))
    return cur.fetchall()


def _get_down_events(conn, monitor_id, date_from, date_to):
    cur = conn.cursor()
    cur.execute("""
        SELECT time, msg FROM heartbeat
        WHERE monitor_id = ? AND status = 0
          AND time >= ? AND time < datetime(?, '+1 day')
        ORDER BY time DESC
    """, (monitor_id, date_from, date_to))
    return cur.fetchall()


def _get_response_series(conn, monitor_id, date_from, date_to):
    d1 = datetime.strptime(date_from, '%Y-%m-%d')
    d2 = datetime.strptime(date_to, '%Y-%m-%d')
    days = (d2 - d1).days

    cur = conn.cursor()
    if days > 14:
        cur.execute("""
            SELECT strftime('%Y-%m-%d %H:00:00', time), AVG(ping)
            FROM heartbeat
            WHERE monitor_id = ? AND status = 1 AND ping IS NOT NULL
              AND time >= ? AND time < datetime(?, '+1 day')
            GROUP BY strftime('%Y-%m-%d %H:00:00', time) ORDER BY 1
        """, (monitor_id, date_from, date_to))
        rows = cur.fetchall()
        times = [datetime.strptime(r[0], '%Y-%m-%d %H:%M:%S') for r in rows]
    else:
        cur.execute("""
            SELECT time, ping FROM heartbeat
            WHERE monitor_id = ? AND status = 1 AND ping IS NOT NULL
              AND time >= ? AND time < datetime(?, '+1 day')
            ORDER BY time
        """, (monitor_id, date_from, date_to))
        rows = cur.fetchall()
        times = []
        for r in rows:
            t = r[0].split('.')[0] if '.' in r[0] else r[0]
            times.append(datetime.strptime(t, '%Y-%m-%d %H:%M:%S'))
    pings = [r[1] for r in rows]
    return times, pings


# ==================== BACKEND: LOCAL (sqlite dosyasi) ====================

class LocalBackend:
    """kuma.db dosyasini salt-okunur acar. API sunucusu bunu kullanir."""

    def __init__(self, db_path):
        # mode=ro: dosyayi degistirmeden, Uptime Kuma yazarken bile
        # (WAL sayesinde) guvenle okur.
        uri = f'file:{db_path}?mode=ro'
        self.conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self.conn.execute('PRAGMA query_only = ON')
        self.conn.execute('PRAGMA busy_timeout = 5000')

    def list_monitors(self):
        return _list_monitors(self.conn)

    def list_status_pages(self):
        return _list_status_pages(self.conn)

    def list_tags(self):
        return _list_tags(self.conn)

    def list_parents(self):
        return _list_parents(self.conn)

    def resolve_monitors(self, status_page=None, tag=None, parent=None,
                          monitor='all', include_groups=False):
        return _resolve_monitors(
            self.conn, status_page=status_page, tag=tag, parent=parent,
            monitor=monitor, include_groups=include_groups)

    def get_summary(self, monitor_id, date_from, date_to):
        return _get_summary(self.conn, monitor_id, date_from, date_to)

    def get_group_summary(self, monitor_ids, date_from, date_to):
        return _get_group_summary(self.conn, monitor_ids, date_from, date_to)

    def get_daily_stats(self, monitor_id, date_from, date_to):
        return _get_daily_stats(self.conn, monitor_id, date_from, date_to)

    def get_down_events(self, monitor_id, date_from, date_to):
        return _get_down_events(self.conn, monitor_id, date_from, date_to)

    def get_response_series(self, monitor_id, date_from, date_to):
        return _get_response_series(self.conn, monitor_id, date_from, date_to)

    def close(self):
        self.conn.close()


# ==================== BACKEND: REMOTE (HTTP uzerinden API) ====================

class RemoteBackendError(RuntimeError):
    pass


class RemoteBackend:
    """kuma_api_server.py'a HTTP istegi atarak ayni veriyi ceker."""

    def __init__(self, api_url, api_key=None, timeout=60):
        self.base_url = api_url.rstrip('/')
        self.api_key = api_key
        self.timeout = timeout

    def _request(self, method, path, params=None, json_body=None):
        url = self.base_url + path
        if params:
            from urllib.parse import urlencode
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url += '?' + urlencode(clean)

        data = None
        headers = {}
        if json_body is not None:
            data = json.dumps(json_body).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        if self.api_key:
            headers['X-API-Key'] = self.api_key

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')
            raise RemoteBackendError(f'{method} {path} -> HTTP {e.code}: {body}') from e
        except urllib.error.URLError as e:
            raise RemoteBackendError(f'{method} {path} -> {e.reason}') from e

    def list_monitors(self):
        return [tuple(row) for row in self._request('GET', '/monitors')]

    def list_status_pages(self):
        return self._request('GET', '/status-pages')

    def list_tags(self):
        return [tuple(row) for row in self._request('GET', '/tags')]

    def list_parents(self):
        return [tuple(row) for row in self._request('GET', '/parents')]

    def resolve_monitors(self, status_page=None, tag=None, parent=None,
                          monitor='all', include_groups=False):
        rows = self._request('POST', '/resolve-monitors', json_body={
            'status_page': status_page, 'tag': tag, 'parent': parent,
            'monitor': monitor, 'include_groups': include_groups,
        })
        return [tuple(row) for row in rows]

    def get_summary(self, monitor_id, date_from, date_to):
        row = self._request('GET', '/summary', params={
            'monitor_id': monitor_id, 'from': date_from, 'to': date_to,
        })
        return tuple(row)

    def get_group_summary(self, monitor_ids, date_from, date_to):
        row = self._request('POST', '/group-summary', json_body={
            'monitor_ids': list(monitor_ids), 'from': date_from, 'to': date_to,
        })
        return tuple(row)

    def get_daily_stats(self, monitor_id, date_from, date_to):
        rows = self._request('GET', '/daily-stats', params={
            'monitor_id': monitor_id, 'from': date_from, 'to': date_to,
        })
        return [tuple(row) for row in rows]

    def get_down_events(self, monitor_id, date_from, date_to):
        rows = self._request('GET', '/down-events', params={
            'monitor_id': monitor_id, 'from': date_from, 'to': date_to,
        })
        return [tuple(row) for row in rows]

    def get_response_series(self, monitor_id, date_from, date_to):
        payload = self._request('GET', '/response-series', params={
            'monitor_id': monitor_id, 'from': date_from, 'to': date_to,
        })
        times = [datetime.fromisoformat(t) for t in payload['times']]
        pings = payload['pings']
        return times, pings

    def close(self):
        pass  # HTTP client'ta acik kalan bir baglanti yok


def make_backend(db_path=None, api_url=None, api_key=None):
    """CLI/UI argumanlarina gore uygun backend'i olusturur."""
    if api_url:
        return RemoteBackend(api_url, api_key=api_key)
    if db_path:
        return LocalBackend(db_path)
    raise ValueError('db_path veya api_url belirtilmeli')
