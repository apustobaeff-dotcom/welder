# -*- coding: utf-8 -*-
"""HTML-письмо еженедельного отчёта. Инлайн-стили: Gmail вырезает <style>."""
import html

E = html.escape
TD = 'style="border:1px solid #d0d4da;padding:6px 8px;vertical-align:top;font-size:13px"'
TH = 'style="border:1px solid #d0d4da;padding:6px 8px;background:#eef1f5;text-align:left;font-size:13px"'
H2 = 'style="font-size:17px;margin:22px 0 8px;color:#1b2b40"'

SECTIONS = [
    ("тендер", "Тендеры и закупки"),
    ("аттестация/допуск", "Аттестации и допуски (НАКС, регистры)"),
    ("вакансия", "Вакансии: кто внедряет"),
    ("запуск/освоение", "Запуск производств, новые марки стали и СМ"),
    ("инвестпроект", "Инвестпроекты"),
    ("отказ/проблема", "Отказы и проблемы: повод для экспертного входа"),
    ("нормативка", "Нормативка"),
    (None, "Прочие релевантные упоминания"),
]


def _tags(it):
    c = it["cls"]
    parts = []
    if c["max_class"]:
        parts.append(f"σт≥{c['max_class']}")
    parts += [s["name"] for s in c["steels"][:3]]
    parts += [s["name"] for s in c["consumables"][:3]]
    parts += c["industries"][:2]
    return ", ".join(parts)


def _table(items):
    rows = [f"<tr><th {TH}>Пр.</th><th {TH}>Дата</th><th {TH}>Сигнал</th>"
            f"<th {TH}>Компания / источник</th><th {TH}>Теги</th><th {TH}>Действие</th></tr>"]
    for it in items:
        rows.append(
            f"<tr><td {TD}><b>{E(it['cls']['priority'])}</b> {it['cls']['score']}</td>"
            f"<td {TD}>{E(it.get('date') or '—')}</td>"
            f"<td {TD}><a href=\"{E(it.get('url') or '')}\">{E(it.get('title') or '')}</a>"
            f"{'<br><span style=\"color:#555\">' + E(it['comment']) + '</span>' if it.get('comment') else ''}</td>"
            f"<td {TD}>{E(it.get('org') or '')}<br><span style=\"color:#777\">{E(it['source'])}</span></td>"
            f"<td {TD}>{E(_tags(it))}</td>"
            f"<td {TD}>{E(it.get('action') or '')}</td></tr>")
    return f'<table style="border-collapse:collapse;width:100%">{"".join(rows)}</table>'


def build(items, health, period, notes=None, top_n=5):
    """items — отсортированы по убыванию балла; каждый с ключом 'cls'.
    health — [{"source":..,"status":"ok"/"error","count":N,"error":..}].
    notes — свободный текст аналитического резюме (заполняется в прогоне)."""
    a = [i for i in items if i["cls"]["priority"] == "A"]
    b = [i for i in items if i["cls"]["priority"] == "B"]
    parts = [
        '<div style="font-family:Arial,Helvetica,sans-serif;color:#111;max-width:980px">',
        f'<h1 style="font-size:20px;margin:0 0 4px">Высокопрочные СМ: мониторинг РФ и СНГ</h1>',
        f'<div style="color:#555">Период: {E(period)} · сигналов: {len(items)} '
        f'(A: {len(a)}, B: {len(b)}) · источников: {len(health)}, '
        f'с ошибкой: {sum(1 for h in health if h["status"] != "ok")}</div>',
    ]
    if notes:
        parts.append(f'<h2 {H2}>Главное за неделю</h2><div style="font-size:14px;line-height:1.5">{notes}</div>')
    top = (a + b)[:top_n]
    if not a and not b:
        parts.append(f'<h2 {H2}>Значимых сигналов нет</h2><p>Классы A/B за период не зафиксированы. '
                     'Ниже — состояние источников.</p>')
    else:
        parts.append(f'<h2 {H2}>Топ-{min(top_n, len(a) + len(b))} лидов</h2>' + _table(top))

    used = {id(i) for i in top}
    for key, title in SECTIONS:
        sel = [i for i in items if id(i) not in used and i["cls"]["priority"] in ("A", "B")
               and (key is None or key in i["cls"]["signal_types"])]
        if not sel:
            continue
        used.update(id(i) for i in sel)
        parts.append(f'<h2 {H2}>{E(title)} ({len(sel)})</h2>' + _table(sel))

    c_items = [i for i in items if i["cls"]["priority"] == "C"]
    if c_items:
        parts.append(f'<h2 {H2}>Фон (класс C, {len(c_items)})</h2><ul style="font-size:13px">' + "".join(
            f'<li><a href="{E(i.get("url") or "")}">{E(i.get("title") or "")}</a> '
            f'<span style="color:#777">— {E(i["source"])}, {E(_tags(i))}</span></li>' for i in c_items[:30]) + "</ul>")

    parts.append(f'<h2 {H2}>Здоровье источников</h2><table style="border-collapse:collapse">' + "".join(
        f'<tr><td {TD}>{E(h["source"])}</td><td {TD}>{"✅" if h["status"] == "ok" else "❌"} {h.get("count", 0)}</td>'
        f'<td {TD}>{E(h.get("error") or "")}</td></tr>' for h in health) + "</table>")
    parts.append('<p style="color:#777;font-size:12px;margin-top:18px">Слепые зоны: закупки ВПК и '
                 'компаний под ПП РФ № 301, прямые договоры, закрытые Telegram-каналы. '
                 'Каждая строка отчёта ведёт на первоисточник; без ссылки сигнал в отчёт не попадает.</p></div>')
    return "\n".join(parts)
