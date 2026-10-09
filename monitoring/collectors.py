# -*- coding: utf-8 -*-
"""Сборщики сигналов. Каждый возвращает список записей единого вида:

    {"source": "telegram:severstal", "source_type": "telegram",
     "url": ..., "title": ..., "text": ..., "date": "YYYY-MM-DD", "org": ...}

Ни один сборщик не бросает исключение наружу: ошибка сети/разметки
поднимается в run_weekly.py и попадает в блок «здоровье источников» отчёта,
чтобы молчаливая потеря источника была видна.
"""
import datetime as dt
import html as html_lib
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"


def _get(url, params=None, headers=None, timeout=30, tries=3):
    h = {"User-Agent": UA}
    h.update(headers or {})
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=h, timeout=timeout)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


# --- Telegram (публичное веб-превью t.me/s/<channel>) -----------------------

def telegram_channel(name, since, max_pages=6):
    out, before = [], None
    for _ in range(max_pages):
        url = f"https://t.me/s/{name}" + (f"?before={before}" if before else "")
        soup = BeautifulSoup(_get(url).text, "html.parser")
        msgs = soup.select("div.tgme_widget_message[data-post]")
        if not msgs:
            break
        oldest_id, reached_old = None, False
        for m in msgs:
            post = m["data-post"]                       # "<channel>/<id>"
            mid = int(post.rsplit("/", 1)[1])
            oldest_id = mid if oldest_id is None else min(oldest_id, mid)
            t = m.select_one("time[datetime]")
            d = dt.datetime.fromisoformat(t["datetime"]).date() if t else None
            if d and d < since:
                reached_old = True
                continue
            body = m.select_one("div.tgme_widget_message_text")
            text = body.get_text("\n", strip=True) if body else ""
            if not text:
                continue
            out.append({
                "source": f"telegram:{name}", "source_type": "telegram",
                "url": f"https://t.me/{post}", "title": text.split("\n", 1)[0][:160],
                "text": text, "date": d.isoformat() if d else None, "org": name,
            })
        if reached_old or oldest_id is None or oldest_id <= 1:
            break
        before = oldest_id
        time.sleep(0.5)
    return out


# --- hh.ru ------------------------------------------------------------------

def hh_vacancies(query, area, since):
    days = max(1, (dt.date.today() - since).days)
    r = _get("https://api.hh.ru/vacancies",
             params={"text": query, "area": area, "period": days, "per_page": 100},
             headers={"HH-User-Agent": "welder-monitoring/1.0 (lead-gen research)"})
    out = []
    for v in r.json().get("items", []):
        snippet = v.get("snippet") or {}
        text = " ".join(filter(None, [v.get("name"), snippet.get("requirement"),
                                      snippet.get("responsibility")]))
        text = re.sub(r"</?highlighttext>", "", text)
        emp = (v.get("employer") or {}).get("name")
        out.append({
            "source": "hh.ru", "source_type": "vacancy", "url": v.get("alternate_url"),
            "title": f"{v.get('name')} — {emp} ({(v.get('area') or {}).get('name')})",
            "text": text, "date": (v.get("published_at") or "")[:10], "org": emp,
        })
    return out


# --- RSS / Atom (в т.ч. YouTube channel feeds) ------------------------------

def rss(url, since, source):
    root = ET.fromstring(_get(url).content)
    ns = {"a": "http://www.w3.org/2005/Atom", "m": "http://search.yahoo.com/mrss/"}
    out = []
    items = root.findall(".//item") or root.findall(".//a:entry", ns)
    for it in items:
        def f(*tags):
            for t in tags:
                el = it.find(t, ns)
                if el is not None:
                    return el.get("href") if t.endswith("link") and el.get("href") else (el.text or "")
            return ""
        title = f("title", "a:title")
        link = f("link", "a:link")
        desc = f("description", "a:content", "m:group/m:description", "a:summary")
        desc = BeautifulSoup(html_lib.unescape(desc or ""), "html.parser").get_text(" ", strip=True)
        raw_date = f("pubDate", "a:published", "a:updated")
        d = _parse_date(raw_date)
        if d and d < since:
            continue
        out.append({"source": source, "source_type": "rss", "url": link, "title": title,
                    "text": f"{title}\n{desc}", "date": d.isoformat() if d else None, "org": source})
    return out


def _parse_date(s):
    if not s:
        return None
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            return dt.datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    try:
        return dt.datetime.fromisoformat(s.strip().replace("Z", "+00:00")).date()
    except ValueError:
        return None


# --- НАКС: еженедельная дельта реестра СМ -----------------------------------

def naks_delta(known_svid, shifr_list, log=print):
    """Вернуть (новые_записи, все_текущие_номера). Новые карточки открываются
    и классифицируются по полному тексту (классификация AWS/ISO живёт в
    примечаниях карточки, а не в списке — см. naks_sm_lib, gotcha #3).

    При пустом known_svid (первый прогон) возвращает только базу без новых
    записей, иначе весь реестр попал бы в отчёт как «новое».
    """
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import naks_sm_lib as naks

    today = dt.date.today().strftime("%d.%m.%Y")
    current, new_rows = set(), []
    for shifr in shifr_list:
        params = naks.build_filter_params(shifr_sm=shifr, date_active_from=today,
                                          date_active_to="31.12.2099")
        rows = naks.collect_rows(params, log=log)
        for r in rows.values():
            if r["cancelled"]:
                continue
            current.add(r["svid_num"])
            if known_svid and r["svid_num"] not in known_svid:
                new_rows.append(r)

    out = []
    for r in new_rows:
        rec = naks.parse_detail(naks.fetch_detail(r["id_param"]), r)
        time.sleep(0.25)
        org = rec.get("proizvoditel") or rec.get("zayavitel") or r.get("organization_list")
        out.append({
            "source": "НАКС реестр СМ", "source_type": "naks",
            "url": naks.verification_url(rec["svid_num"]),
            "title": f"{r['shifr']} {r['marka']} ⌀{r['diametr']} — {r['organization_list']} (св. {r['svid_num']})",
            "text": rec.get("full_text", ""), "date": dt.date.today().isoformat(), "org": org,
            "naks": {k: rec.get(k) for k in ("svid_num", "proizvoditel", "zayavitel",
                                              "predstavitel", "postavshik", "potrebitel")},
        })
    return out, current


# --- НАКС: еженедельная дельта реестра технологий (АЦСТ) --------------------

def naks_st_delta(known_svid, grade_matcher, log=print):
    """Новые действующие свидетельства о готовности к применению технологий
    сварки ВЫСОКОПРОЧНЫХ сталей (группа 3 ОМ или высокопрочная марка в тексте).
    Предприятие, аттестовавшее такую технологию, уже варит эти стали —
    это самый «тёплый» лид на СМ. Первый прогон только фиксирует базу."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import naks_st_lib as st

    today = dt.date.today().strftime("%d.%m.%Y")
    rows = st.collect_rows(st.build_filter_params(date_active_from=today,
                                                  date_active_to="31.12.2099"), log=log)
    current, out = set(), []
    for r in rows.values():
        if r["cancelled"]:
            continue
        current.add(r["svid_num"])
        if not known_svid or r["svid_num"] in known_svid:
            continue
        if not st.is_high_strength(r, grade_matcher):
            continue
        out.append({
            "source": "НАКС реестр технологий (АЦСТ)", "source_type": "naks_st",
            "url": st.verification_url(r["svid_num"]),
            "title": f"Аттестация технологии: {r['organization']} — {r['sposoby']}, "
                     f"ОМ гр. {','.join(map(str, r['groups'])) or '?'} (св. {r['svid_num']})",
            "text": f"НАКС аттестация технологии сварки. Основные материалы: {r['osn_materialy']}. "
                    f"Способы: {r['sposoby']}. Группы ТУ: {r['gruppy']}. Высокопрочная сталь.",
            "date": dt.date.today().isoformat(), "org": r["organization"],
            "action": "Предприятие аттестовало технологию сварки высокопрочной стали: "
                      "выйти к главному сварщику с СМ под эту марку/группу",
        })
    return out, current
