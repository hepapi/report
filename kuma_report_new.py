#!/usr/bin/env python3
"""
Uptime Kuma PDF Rapor Olusturucu (v3 - ASCII metin)
====================================================

PDF'te Turkce karakter kullanilmiyor (ReportLab varsayilan Helvetica
fontu Turkce karakterleri render edemiyor). Terminal ciktilarinda
Turkce karakter kullanmaya devam ediyoruz.

Discovery:
  python kuma_report.py --db kuma.db --list
  python kuma_report.py --db kuma.db --list-pages
  python kuma_report.py --db kuma.db --list-tags

Rapor:
  python kuma_report.py --db kuma.db --status-page prod \
      --from 2025-01-01 --to 2025-10-31 --output prod_rapor.pdf

  python kuma_report.py --db kuma.db --tag env:prod \
      --from 2025-01-01 --to 2025-10-31

  python kuma_report.py --db kuma.db --parent "Azure Foundry Service" \
      --from 2025-01-01 --to 2025-10-31

Not: Eger Turkce karakterlerin PDF'te dogru gorunmesini istersen
     --font DejaVuSans parametresiyle sistemdeki bir TTF fontu kullanabilirsin.
"""
import argparse
import sqlite3
from datetime import datetime
from io import BytesIO
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)


# Turkce -> ASCII cevirici
_TR = str.maketrans({
    'ç': 'c', 'Ç': 'C', 'ğ': 'g', 'Ğ': 'G',
    'ı': 'i', 'İ': 'I', 'ö': 'o', 'Ö': 'O',
    'ş': 's', 'Ş': 'S', 'ü': 'u', 'Ü': 'U',
    '—': '-', '–': '-', '…': '...',
})


def ascii_safe(s):
    """PDF'e giden metinden Turkce karakterleri ve emojileri temizle."""
    if not isinstance(s, str):
        return s
    # Turkce karakterleri cevir
    out = s.translate(_TR)
    # ASCII olmayan karakterleri (emoji dahil) ayikla
    return ''.join(c if ord(c) < 128 else '' for c in out)


# ==================== DISCOVERY ====================

def list_monitors(conn):
    cur = conn.cursor()
    cur.execute("SELECT id, name, active FROM monitor ORDER BY id")
    return cur.fetchall()


def list_status_pages(conn):
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


def list_tags(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT t.id, t.name, mt.value, COUNT(DISTINCT mt.monitor_id) AS cnt
        FROM tag t LEFT JOIN monitor_tag mt ON mt.tag_id = t.id
        GROUP BY t.id, t.name, mt.value
        ORDER BY t.name, mt.value
    """)
    return cur.fetchall()


# ==================== FILTRELEME ====================

def resolve_monitors(conn, args):
    cur = conn.cursor()

    if args.status_page:
        cur.execute("""
            SELECT DISTINCT m.id, m.name FROM monitor m
            JOIN monitor_group mg ON mg.monitor_id = m.id
            JOIN "group" g ON g.id = mg.group_id
            JOIN status_page sp ON sp.id = g.status_page_id
            WHERE (sp.slug = ? OR sp.title = ?) AND m.active = 1
        """, (args.status_page, args.status_page))
        return _walk_descendants(conn, cur.fetchall())

    if args.tag:
        if ':' in args.tag:
            tname, tvalue = args.tag.split(':', 1)
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
            """, (args.tag,))
        return _walk_descendants(conn, cur.fetchall())

    if args.parent:
        try:
            pid = int(args.parent)
            cur.execute("SELECT id, name FROM monitor WHERE id = ?", (pid,))
        except ValueError:
            cur.execute("SELECT id, name FROM monitor WHERE name = ?", (args.parent,))
        root = cur.fetchone()
        if not root:
            return []
        return _walk_descendants(conn, [root])

    if args.monitor.lower() == 'all':
        cur.execute("SELECT id, name FROM monitor WHERE active = 1 ORDER BY name")
        return cur.fetchall()

    ids = [int(x.strip()) for x in args.monitor.split(',')]
    ph = ','.join('?' * len(ids))
    cur.execute(f"SELECT id, name FROM monitor WHERE id IN ({ph}) ORDER BY name", ids)
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


# ==================== DB SORGULARI ====================

def get_summary(conn, monitor_id, date_from, date_to):
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


def get_group_summary(conn, monitor_ids, date_from, date_to):
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


def get_daily_stats(conn, monitor_id, date_from, date_to):
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


def get_down_events(conn, monitor_id, date_from, date_to):
    cur = conn.cursor()
    cur.execute("""
        SELECT time, msg FROM heartbeat
        WHERE monitor_id = ? AND status = 0
          AND time >= ? AND time < datetime(?, '+1 day')
        ORDER BY time DESC
    """, (monitor_id, date_from, date_to))
    return cur.fetchall()


def get_response_series(conn, monitor_id, date_from, date_to):
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


# ==================== YARDIMCILAR ====================

def uptime_color(pct):
    if pct >= 99:
        return '#2E7D32'
    if pct >= 95:
        return '#F57C00'
    return '#C62828'


def summary_table(data, uptime_pct=None):
    t = Table(data, colWidths=[6 * cm, 6 * cm])
    style = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1976D2')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
        ('ROWBACKGROUNDS', (0, 2), (-1, -1),
         [colors.white, colors.HexColor('#F5F5F5')]),
        ('PADDING', (0, 0), (-1, -1), 5),
    ]
    if uptime_pct is not None:
        style.extend([
            ('BACKGROUND', (1, 1), (1, 1),
             colors.HexColor(uptime_color(uptime_pct))),
            ('TEXTCOLOR', (1, 1), (1, 1), colors.white),
            ('FONTNAME', (1, 1), (1, 1), 'Helvetica-Bold'),
        ])
    t.setStyle(TableStyle(style))
    return t


def render_response_chart(times, pings, monitor_name):
    if not times:
        return None
    fig, ax = plt.subplots(figsize=(9, 3.5))
    ax.plot(times, pings, linewidth=0.7, color='#1976D2')
    ax.fill_between(times, pings, alpha=0.15, color='#1976D2')
    ax.set_ylabel('Ping (ms)')
    # matplotlib DejaVu Sans kullanir, Turkce destegi tam
    # ama tutarli olsun diye burada da ASCII kullaniyoruz
    ax.set_title(f'{ascii_safe(monitor_name)} - Response Time')
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    fig.autofmt_xdate()
    plt.tight_layout()
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=120)
    plt.close(fig)
    buf.seek(0)
    return buf


# ==================== PDF ====================

def build_report(conn, monitors, date_from, date_to, output_path,
                 report_title='Uptime Kuma Rapor', max_down_events=200,
                 include_overview=True):
    if not monitors:
        print("⚠  Filtreye uyan monitor yok.")
        return

    print(f"→ {len(monitors)} monitor için rapor hazırlanıyor...")

    # PDF-safe title
    safe_title = ascii_safe(report_title)

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        title=safe_title,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('T', parent=styles['Title'], fontSize=22, spaceAfter=10)
    h2 = ParagraphStyle('H2', parent=styles['Heading2'], fontSize=15,
                        textColor=colors.HexColor('#1976D2'), spaceAfter=6)
    h3 = ParagraphStyle('H3', parent=styles['Heading3'], fontSize=11,
                        textColor=colors.HexColor('#333333'), spaceBefore=8)
    body = styles['BodyText']

    def P(text, style=body):
        """Turkce karakterleri temizleyerek Paragraph olustur."""
        return Paragraph(ascii_safe(text), style)

    story = []
    story.append(P(safe_title, title_style))
    story.append(P(f'<b>Donem:</b> {date_from} -> {date_to}'))
    story.append(P(f'<b>Olusturulma:</b> {datetime.now().strftime("%Y-%m-%d %H:%M")}'))
    story.append(P(f'<b>Monitor sayisi:</b> {len(monitors)}'))
    story.append(Spacer(1, 0.4 * cm))

    # --- Grup ozeti ---
    if include_overview and len(monitors) > 1:
        story.append(P('Genel Ozet (Tum Monitorlar Birlesik)', h2))
        ids = [m[0] for m in monitors]
        total, up_c, down_c, avg_p, min_p, max_p = get_group_summary(
            conn, ids, date_from, date_to)
        if total:
            pct = (up_c / total * 100)
            story.append(summary_table([
                ['Metrik', 'Deger'],
                ['Uptime %', f'{pct:.3f}%'],
                ['Toplam kontrol', f'{total:,}'],
                ['UP', f'{up_c:,}'],
                ['DOWN', f'{down_c:,}'],
                ['Ortalama ping', f'{avg_p:.1f} ms' if avg_p else '-'],
                ['Min / Max ping',
                 f'{min_p:.1f} / {max_p:.1f} ms' if min_p else '-'],
            ], uptime_pct=pct))
        story.append(Spacer(1, 0.4 * cm))

    # --- Monitor listesi ---
    story.append(P('Monitor Listesi', h3))
    toc_data = [['#', 'Monitor', 'ID', 'Uptime %']]
    per_monitor = {}
    for i, (mid, mname) in enumerate(monitors, 1):
        s = get_summary(conn, mid, date_from, date_to)
        per_monitor[mid] = s
        total = s[0] or 0
        up_c = s[1] or 0
        pct = (up_c / total * 100) if total else 0
        toc_data.append([str(i), ascii_safe(mname), str(mid),
                         f'{pct:.2f}%' if total else '-'])
    toc = Table(toc_data, colWidths=[1.2 * cm, 11 * cm, 2 * cm, 3 * cm])
    toc.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1976D2')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1),
         [colors.white, colors.HexColor('#F5F5F5')]),
        ('PADDING', (0, 0), (-1, -1), 4),
        ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
    ]))
    story.append(toc)

    # --- Her monitor detayi ---
    for idx, (mid, mname) in enumerate(monitors):
        story.append(PageBreak())
        print(f"  · [{idx + 1}/{len(monitors)}] {mname}")

        safe_mname = ascii_safe(mname)
        story.append(P(safe_mname, h2))
        story.append(P(f'Monitor ID: {mid}'))

        total, up_c, down_c, avg_p, min_p, max_p = per_monitor[mid]
        if not total:
            story.append(Spacer(1, 0.3 * cm))
            story.append(P('<i>Bu donemde veri yok.</i>'))
            continue

        pct = (up_c / total * 100)
        story.append(P('Ozet', h3))
        story.append(summary_table([
            ['Metrik', 'Deger'],
            ['Uptime %', f'{pct:.3f}%'],
            ['Toplam kontrol', f'{total:,}'],
            ['UP', f'{up_c:,}'],
            ['DOWN', f'{down_c:,}'],
            ['Ortalama ping', f'{avg_p:.1f} ms' if avg_p else '-'],
            ['Min ping', f'{min_p:.1f} ms' if min_p else '-'],
            ['Max ping', f'{max_p:.1f} ms' if max_p else '-'],
        ], uptime_pct=pct))
        story.append(Spacer(1, 0.4 * cm))

        story.append(P('Yanit Suresi', h3))
        times, pings = get_response_series(conn, mid, date_from, date_to)
        chart = render_response_chart(times, pings, mname)
        if chart:
            story.append(Image(chart, width=17 * cm, height=6.5 * cm))
        else:
            story.append(P('<i>Yanit suresi verisi yok.</i>'))
        story.append(Spacer(1, 0.4 * cm))

        daily = get_daily_stats(conn, mid, date_from, date_to)
        if daily:
            story.append(P(f'Gunluk Uptime ({len(daily)} gun)', h3))
            td = [['Tarih', 'Toplam', 'UP', 'DOWN', 'Uptime %', 'Ort. Ping']]
            for gun, tot, up, dn, avg in daily:
                p = (up / tot * 100) if tot else 0
                td.append([gun, f'{tot:,}', f'{up:,}', f'{dn:,}',
                           f'{p:.2f}%', f'{avg:.0f} ms' if avg else '-'])
            t = Table(td,
                      colWidths=[3 * cm, 2.5 * cm, 2.5 * cm,
                                 2.5 * cm, 2.5 * cm, 2.5 * cm],
                      repeatRows=1)
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1976D2')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1),
                 [colors.white, colors.HexColor('#F5F5F5')]),
                ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
                ('PADDING', (0, 0), (-1, -1), 3),
            ]))
            story.append(t)
            story.append(Spacer(1, 0.4 * cm))

        downs = get_down_events(conn, mid, date_from, date_to)
        story.append(P(f'Down Olaylari ({len(downs)} adet)', h3))
        if downs:
            td = [['Zaman', 'Hata Mesaji']]
            for time_s, msg in downs[:max_down_events]:
                m = ascii_safe((msg or '-').replace('\n', ' ').replace('\r', ' '))
                if len(m) > 140:
                    m = m[:140] + '...'
                m = m.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                short_time = time_s.split('.')[0] if time_s else '-'
                td.append([short_time, Paragraph(m, body)])
            t = Table(td, colWidths=[4 * cm, 13.5 * cm], repeatRows=1)
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#C62828')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('PADDING', (0, 0), (-1, -1), 3),
            ]))
            story.append(t)
            if len(downs) > max_down_events:
                story.append(Spacer(1, 0.2 * cm))
                story.append(P(
                    f'<i>... ve {len(downs) - max_down_events} tane daha '
                    f'(toplam {len(downs)}).</i>'))
        else:
            story.append(P('<b>Bu donemde down olayi yok.</b>'))

    doc.build(story)
    print(f'✓ Rapor oluşturuldu: {output_path}')


# ==================== CLI ====================

def parse_args():
    p = argparse.ArgumentParser(
        description='Uptime Kuma SQLite DB\'sinden PDF rapor uretir.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument('--db', required=True)
    p.add_argument('--list', action='store_true')
    p.add_argument('--list-pages', action='store_true')
    p.add_argument('--list-tags', action='store_true')
    p.add_argument('--status-page')
    p.add_argument('--tag')
    p.add_argument('--parent')
    p.add_argument('--monitor', default='all')
    p.add_argument('--from', dest='date_from')
    p.add_argument('--to', dest='date_to')
    p.add_argument('--output', default='kuma_rapor.pdf')
    p.add_argument('--title')
    p.add_argument('--max-down', type=int, default=200)
    p.add_argument('--no-overview', action='store_true')
    return p.parse_args()


def main():
    args = parse_args()
    if not Path(args.db).exists():
        print(f'✗ Hata: {args.db} bulunamadı')
        return

    conn = sqlite3.connect(args.db)

    if args.list:
        monitors = list_monitors(conn)
        print(f'\n{len(monitors)} monitor bulundu:\n')
        print(f'{"ID":>5} | {"Aktif":<6} | Ad')
        print('-' * 60)
        for mid, name, active in monitors:
            print(f'{mid:>5} | {"Evet" if active else "Hayır":<6} | {name}')
        return

    if args.list_pages:
        pages = list_status_pages(conn)
        if not pages:
            print('Hiç status page yok.')
            return
        print(f'\n{len(pages)} status page bulundu:\n')
        for p in pages:
            print(f'■ {p["title"]}  (slug: {p["slug"]})')
            print(f'    → --status-page "{p["slug"]}"')
            for g in p['groups']:
                print(f'  └─ Grup: {g["name"]} ({len(g["monitors"])} monitor)')
                for mid, mname in g['monitors']:
                    print(f'      └─ [{mid}] {mname}')
            print()
        return

    if args.list_tags:
        tags = list_tags(conn)
        if not tags:
            print('Hiç tag yok.')
            return
        print(f'\n{len(tags)} tag/değer:\n')
        for tid, tname, tvalue, cnt in tags:
            key = f'{tname}:{tvalue}' if tvalue else tname
            print(f'  {tname:<20} {(tvalue or "-"):<20} ({cnt} monitor)')
            print(f'    → --tag "{key}"')
        return

    if not args.date_from or not args.date_to:
        print('✗ Hata: --from ve --to zorunlu')
        return

    monitors = resolve_monitors(conn, args)

    title = args.title
    if not title:
        if args.status_page:
            title = f'Uptime Rapor - {args.status_page}'
        elif args.tag:
            title = f'Uptime Rapor - {args.tag}'
        elif args.parent:
            title = f'Uptime Rapor - {args.parent} alti'
        else:
            title = 'Uptime Kuma Rapor'

    build_report(
        conn, monitors, args.date_from, args.date_to, args.output,
        report_title=title, max_down_events=args.max_down,
        include_overview=not args.no_overview,
    )
    conn.close()


if __name__ == '__main__':
    main()
