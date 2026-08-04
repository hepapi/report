#!/usr/bin/env python3
"""
Uptime Kuma PDF Rapor Olusturucu (v4 - ozet/detayli mod)
=========================================================

Varsayilan: Kompakt ozet raporu — kapak + grup ozeti + monitor listesi
tablosu. Yuzlerce monitor icin ideal, hizli uretir.

--detailed: Her monitor icin ayri sayfa (yanit suresi grafigi, gunluk
uptime tablosu, down olaylari). Az sayida monitor icin faydali.

Discovery:
  python kuma_report.py --db kuma.db --list
  python kuma_report.py --db kuma.db --list-pages
  python kuma_report.py --db kuma.db --list-tags

Ozet rapor (varsayilan - sadece PROD toplamı):
  python kuma_report.py --db kuma.db --status-page prod \
      --from 2025-01-01 --to 2025-10-31 --output prod_ozet.pdf

Detayli rapor (her monitor icin ayri sayfa):
  python kuma_report.py --db kuma.db --status-page prod --detailed \
      --from 2025-01-01 --to 2025-10-31 --output prod_detayli.pdf

Tag/parent ile:
  python kuma_report.py --db kuma.db --tag env:prod --from ... --to ...
  python kuma_report.py --db kuma.db --parent "Azure Foundry" --from ... --to ...
"""
import argparse
import os
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
from pypdf import PdfReader, PdfWriter

from kuma_dbaccess import RemoteBackendError, make_backend


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


# ==================== YARDIMCILAR ====================
# DB erisimi (list_monitors, resolve_monitors, get_summary, vb.) artik
# kuma_dbaccess.py'daki LocalBackend/RemoteBackend uzerinden yapiliyor.
# Bkz: make_backend() ve build_report()'a verilen `backend` parametresi.

def uptime_color(pct):
    if pct >= 99:
        return '#2E7D32'
    if pct >= 95:
        return '#F57C00'
    return '#C62828'


def _combine_summaries(bulk):
    """get_summaries_bulk() sonucundan grup ozetini (COUNT/SUM/AVG/MIN/MAX)
    Python tarafinda hesaplar - backend.get_group_summary() gibi heartbeat
    tablosunu ikinci kez taramaya gerek kalmaz.

    Ortalama ping, her monitorun kendi UP sayisiyla agirliklandirilarak
    birlestirilir (duz ortalamalarin ortalamasi degil - matematiksel
    olarak SQL'deki AVG(ping WHERE status=1) ile birebir ayni sonucu verir).
    """
    total = up_c = down_c = 0
    min_p = max_p = None
    weighted_ping_sum = 0.0
    ping_weight = 0
    for s in bulk.values():
        t, u, d, avg, mn, mx = s
        total += t or 0
        up_c += u or 0
        down_c += d or 0
        if mn is not None:
            min_p = mn if min_p is None else min(min_p, mn)
        if mx is not None:
            max_p = mx if max_p is None else max(max_p, mx)
        if avg is not None and u:
            weighted_ping_sum += avg * u
            ping_weight += u
    avg_p = (weighted_ping_sum / ping_weight) if ping_weight else None
    return total, up_c, down_c, avg_p, min_p, max_p


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

def _apply_letterhead(content_bytes, letterhead_path):
    """Rapor sayfalarini antetli kagidin uzerine bindirir.

    Antetli kagit 1 sayfaysa tum rapor sayfalarinda tekrar kullanilir.
    2 (ya da daha fazla) sayfaysa: ilk sayfa kapak icin, ikinci sayfa
    devam sayfalari icin kullanilir.
    """
    content_reader = PdfReader(BytesIO(content_bytes))
    n_letterhead_pages = len(PdfReader(letterhead_path).pages)

    writer = PdfWriter()
    for i, content_page in enumerate(content_reader.pages):
        # Her sayfa icin antetli kagidin TAZE bir kopyasini parse ediyoruz.
        # pypdf'te ayni PageObject'i birden fazla add_page()+merge_page()
        # cagrisinda paylasmak, ic content stream'in sayfalar arasinda
        # (mutasyonla) sizmasina yol aciyordu - her sayfa kendi bagimsiz
        # kopyasini almali.
        lh_idx = 0 if (n_letterhead_pages == 1 or i == 0) else 1
        lh_page = PdfReader(letterhead_path).pages[lh_idx]
        writer.add_page(lh_page)
        writer.pages[-1].merge_page(content_page)

    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _finalize_pdf(raw_buf, output_path, letterhead_path):
    """doc.build() ciktisini (gerekirse antetli kagitla birlestirip) hedefe yazar."""
    raw_buf.seek(0)
    data = raw_buf.getvalue()
    if letterhead_path:
        data = _apply_letterhead(data, letterhead_path)

    if isinstance(output_path, (str, Path)):
        Path(output_path).write_bytes(data)
    else:
        output_path.write(data)


def build_report(backend, monitors, date_from, date_to, output_path,
                 report_title='Uptime Kuma Rapor', max_down_events=200,
                 detailed=False, letterhead_path=None,
                 margin_top_cm=1.5, margin_bottom_cm=1.5,
                 margin_left_cm=1.5, margin_right_cm=1.5):
    if not monitors:
        print("⚠  Filtreye uyan monitor yok.")
        return

    print(f"→ {len(monitors)} monitor için rapor hazırlanıyor...")

    # PDF-safe title
    safe_title = ascii_safe(report_title)

    raw_buf = BytesIO()
    doc = SimpleDocTemplate(
        raw_buf, pagesize=A4,
        leftMargin=margin_left_cm * cm, rightMargin=margin_right_cm * cm,
        topMargin=margin_top_cm * cm, bottomMargin=margin_bottom_cm * cm,
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

    # Her monitor icin ayri ayri get_summary() cagirmak yerine (uzak backend'de
    # N ayri HTTP round-trip demek - cok monitorlu raporlarda timeout'a yol
    # aciyordu) TEK toplu sorguyla hepsini birden cekiyoruz.
    empty_summary = (0, 0, 0, None, None, None)
    bulk = backend.get_summaries_bulk([m[0] for m in monitors], date_from, date_to)

    # --- Grup ozeti (her zaman goster, birden fazla monitor varsa) ---
    if len(monitors) > 1:
        story.append(P('Genel Ozet (Tum Monitorlar Birlesik)', h2))
        # ONEMLI: backend.get_group_summary() ile AYRI bir sorgu daha atmak
        # yerine (heartbeat tablosunu ikinci kez tarayip, cok monitorlu
        # raporlarda kendi basina timeout'a sebep oluyordu) yukarida zaten
        # cekilmis olan per-monitor 'bulk' verisini Python tarafinda
        # toplayarak ayni sonucu uretiyoruz - ekstra DB sorgusu yok.
        total, up_c, down_c, avg_p, min_p, max_p = _combine_summaries(bulk)
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

    # --- Monitor listesi (zenginlestirilmis: uptime + down + avg ping) ---
    story.append(P('Monitor Listesi', h3))
    toc_data = [['#', 'Monitor', 'ID', 'Uptime %', 'Toplam', 'DOWN', 'Ort. Ping']]
    per_monitor = {}
    for i, (mid, mname) in enumerate(monitors, 1):
        s = bulk.get(mid, empty_summary)
        per_monitor[mid] = s
        total = s[0] or 0
        up_c = s[1] or 0
        down_c = s[2] or 0
        avg_p = s[3]
        pct = (up_c / total * 100) if total else 0
        toc_data.append([
            str(i), ascii_safe(mname), str(mid),
            f'{pct:.2f}%' if total else '-',
            f'{total:,}' if total else '-',
            f'{down_c:,}' if total else '-',
            f'{avg_p:.0f} ms' if avg_p else '-',
        ])
    toc = Table(
        toc_data,
        colWidths=[1 * cm, 7.5 * cm, 1.5 * cm, 2 * cm, 2 * cm, 1.5 * cm, 2 * cm],
        repeatRows=1,
    )
    toc.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1976D2')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1),
         [colors.white, colors.HexColor('#F5F5F5')]),
        ('PADDING', (0, 0), (-1, -1), 3),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
    ]))
    story.append(toc)

    # --- Detayli mod degilse burada bit ---
    if not detailed:
        doc.build(story)
        _finalize_pdf(raw_buf, output_path, letterhead_path)
        print(f'✓ Ozet rapor oluşturuldu: {output_path}')
        print(f'  (Her monitor icin ayri sayfa istersen --detailed ekle)')
        return

    # --- Detayli mod: her monitor icin sayfa ---
    print(f'  Detayli mod: {len(monitors)} monitor icin ayri sayfa uretiliyor...')
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
        times, pings = backend.get_response_series(mid, date_from, date_to)
        chart = render_response_chart(times, pings, mname)
        if chart:
            story.append(Image(chart, width=17 * cm, height=6.5 * cm))
        else:
            story.append(P('<i>Yanit suresi verisi yok.</i>'))
        story.append(Spacer(1, 0.4 * cm))

        daily = backend.get_daily_stats(mid, date_from, date_to)
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

        downs = backend.get_down_events(mid, date_from, date_to)
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
    _finalize_pdf(raw_buf, output_path, letterhead_path)
    print(f'✓ Detayli rapor oluşturuldu: {output_path}')


# ==================== CLI ====================

def parse_args():
    p = argparse.ArgumentParser(
        description='Uptime Kuma SQLite DB\'sinden PDF rapor uretir.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument('--db', help='kuma.db dosya yolu (lokal mod)')
    p.add_argument('--api-url',
                   help='kuma_api_server.py adresi, orn. http://uptime-host:8090 '
                        '(--db yerine; uzak sunucudaki canli DB\'ye HTTP ile baglanir)')
    p.add_argument('--api-key', help='--api-url ile kullanilacak API anahtari '
                                      '(KUMA_API_KEY ortam degiskeni ile ayni)')
    p.add_argument('--api-timeout', type=int, default=300,
                   help='--api-url istekleri icin saniye cinsinden zaman asimi '
                        '(varsayilan: 300). Cok monitorlu/genis tarih araligi '
                        'raporlari zaman asimina uğrarsa buyutun.')
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
    p.add_argument('--detailed', action='store_true',
                   help='Her monitor icin ayri detay sayfasi da uret '
                        '(varsayilan: sadece ozet + monitor listesi)')
    p.add_argument('--include-groups', action='store_true',
                   help='Group tipi (alt monitoru olan) monitorlari da dahil et '
                        '(varsayilan: cikarilir, cunku ayni DOWN olaylarini iki '
                        'kez sayarak aggregate istatistikleri bozuyor)')
    p.add_argument('--letterhead',
                   help='Antetli kagit PDF dosyasi. Verilirse rapor sayfalari '
                        'bunun uzerine bindirilir. Tek sayfaysa tum sayfalarda, '
                        'iki (+) sayfaysa ilk sayfa kapak / ikincisi devam '
                        'sayfalari icin kullanilir.')
    p.add_argument('--margin-top', type=float, default=1.5,
                   help='Ust kenar bosluğu (cm). Antetli kagitta ustte logo/baslik '
                        'alani varsa buyutun (orn. 4.5).')
    p.add_argument('--margin-bottom', type=float, default=1.5,
                   help='Alt kenar bosluğu (cm). Antetli kagitta altta altbilgi '
                        'alani varsa buyutun (orn. 2.5).')
    p.add_argument('--margin-left', type=float, default=1.5, help='Sol kenar bosluğu (cm)')
    p.add_argument('--margin-right', type=float, default=1.5, help='Sag kenar bosluğu (cm)')
    return p.parse_args()


def main():
    args = parse_args()

    if not args.db and not args.api_url:
        print('✗ Hata: --db veya --api-url belirtilmeli')
        return
    if args.db and not args.api_url and not Path(args.db).exists():
        print(f'✗ Hata: {args.db} bulunamadı')
        return

    api_key = args.api_key or os.environ.get('KUMA_API_KEY')
    backend = make_backend(db_path=args.db, api_url=args.api_url, api_key=api_key,
                            api_timeout=args.api_timeout)

    if args.list:
        monitors = backend.list_monitors()
        print(f'\n{len(monitors)} monitor bulundu:\n')
        print(f'{"ID":>5} | {"Aktif":<6} | Ad')
        print('-' * 60)
        for mid, name, active in monitors:
            print(f'{mid:>5} | {"Evet" if active else "Hayır":<6} | {name}')
        return

    if args.list_pages:
        pages = backend.list_status_pages()
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
        tags = backend.list_tags()
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

    monitors = backend.resolve_monitors(
        status_page=args.status_page, tag=args.tag, parent=args.parent,
        monitor=args.monitor, include_groups=args.include_groups,
    )

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
        backend, monitors, args.date_from, args.date_to, args.output,
        report_title=title, max_down_events=args.max_down,
        detailed=args.detailed, letterhead_path=args.letterhead,
        margin_top_cm=args.margin_top, margin_bottom_cm=args.margin_bottom,
        margin_left_cm=args.margin_left, margin_right_cm=args.margin_right,
    )
    backend.close()


if __name__ == '__main__':
    try:
        main()
    except RemoteBackendError as e:
        print(f'✗ API hatasi: {e}')
