# -*- coding: utf-8 -*-
"""
naks_st_lib.py — engine for the NAKS registry of organisations that passed
the readiness check for applying attested welding technologies
(«Реестр организаций, прошедших проверку готовности к применению
аттестованных технологий сварки»): https://naks.ru/registry/reg/st/

Sibling of naks_sm_lib.py (welding consumables) and deliberately built on
the same primitives: it REUSES naks_sm_lib.get() (stateless requests,
cache-busting nonce, windows-1251 query encoding) and the shared filter
code tables (SVARKA / TECH / TYPE_ATT), which were checked against the live
/reg/st/ filter form on 2026-10-09 and are byte-for-byte identical.

Like the SM engine, this is a LIBRARY: the caller composes site-level
filters plus its own predicate over the parsed rows.

=====================================================================
THINGS THAT WILL SILENTLY CORRUPT YOUR DATA IF YOU DON'T KNOW THEM
=====================================================================

1. 500-ROW CAP, AND SHARDING BY AC IS *NOT* ENOUGH HERE.
   Same cap as the SM registry ("НАЙДЕНО ЗАПИСЕЙ: 500" = possibly capped).
   But in this registry a SINGLE attestation centre already hits the cap:
   АЦСТ-1 alone with "valid from today" reported exactly 500 on
   2026-10-09 (real size 1457). So `collect_rows()` recursively BISECTS the
   «Срок действия свидетельства до» date range until every leaf is under
   the cap (a single day still at the cap is split by AC). Never trust a
   total of exactly 500. A full-registry walk is slow (~8 min per 1.5k
   rows); for high-strength work use collect_high_strength(), which unions
   targeted «Основные материалы» substring queries (HS_QUERIES).

2. Stateless requests only (inherited from naks_sm_lib gotcha #2). Use
   naks_sm_lib.get(); do not introduce a shared requests.Session.

3. windows-1251 for page AND for Cyrillic query values (inherited gotcha).
   Verified on /reg/st/: num_sv=АЦСТ-1-05705 encoded as cp1251 returns
   exactly 1 record; UTF-8 encoding of the same value returns 0.
   Go through naks_sm_lib.get(), never requests.get() directly.

4. CANCELLED-BUT-NOT-EXPIRED. Same as SM: the № свидетельства cell can
   read "АЦСТ-1-05813 <br>аннулировано 23.06.2026" while the validity date
   is still in the future. parse_list_page() sets cancelled=True and
   cancel_date; the date filter alone does not exclude these.

5. THE LIST VIEW IS RICHER THAN IN THE SM REGISTRY. The column
   «Основные материалы» carries the base-metal GROUP number(s) plus the
   actual steel grades, e.g.
       "1 (С235, С245, ... 09Г2С и другие по ПТД)"
       "1 (До К54 вкл.)"
       "Группа 1 - 08, 10, ... + Группа 2 - 14Х2ГРМ и другие по ПТД."
   so for "which plants weld which steels" you usually do NOT need the
   detail card. base_metal_groups() extracts the group numbers.
   HIGH-STRENGTH STEELS = GROUP 3 of base materials (ОМ), per the domain
   owner (corresponds to М03 — легированные конструкционные стали,
   σт > 360 МПа). Do NOT rely on the group number alone: the applicant
   assigns the group, and real rows put e.g. Cr-Mo 14Х2ГМР under group 2
   (heat-resistant, М02). is_high_strength() therefore checks group 3 OR
   a high-strength grade in the text (optional grade_matcher callback).

6. DETAIL CARD («открыть» → «Область распространения»). The button's
   onclick is
     clear_modal(); jsAjaxUtil.InsertDataToNode("/ast/reestrattst2/detail.php?ID=<b64>", "oblast_att")
   (verified live 2026-10-09). The ID is base64 of a PHP-serialized
   {svid_num, svid_date}; take it from the row, do not construct it.
   Scraping proxies strip on* attributes — fetch with naks_sm_lib.get().
   The card's «Сварочные (наплавочные) материалы» row names the actual
   consumables the plant qualified with (e.g. "электроды LB-52U") —
   parse_detail() exposes it as sm_text / sm_marks. This is the field
   that tells you WHOSE consumables a high-strength welder currently uses.

7. Page size is 25 rows; pagination param PAGEN_1 (same as SM).

=====================================================================
REFERENCE DATA (decoded from the live filter form 2026-10-09)
=====================================================================
"""

import re
import time
import html as html_lib

from bs4 import BeautifulSoup

import naks_sm_lib as _sm
from naks_sm_lib import SVARKA, TECH, TYPE_ATT, cp1251_url_value  # noqa: F401  (re-exported)

BASE = _sm.BASE
LIST_URL = BASE + "/ast/reestrattst2/index.php"
FILTER_PAGE_URL = BASE + "/registry/reg/st/"
PAGE_SIZE = 25
CAP = 500

# Раздел: производственные / исследовательские аттестации
SECTION = {"Производственные": "158", "Исследовательские": "159"}

# Регистрационный номер АЦСТ -> internal num_acst id (АЦСТ-1 .. АЦСТ-163)
AC_MAP = {
    1: 414566, 2: 414567, 3: 414568, 4: 414569, 5: 414570, 6: 414571,
    7: 414572, 8: 414573, 9: 414574, 10: 414575, 11: 414576, 12: 414577,
    13: 414578, 14: 414579, 15: 414580, 16: 414581, 17: 414582, 18: 414583,
    19: 414584, 20: 414585, 21: 414586, 22: 414587, 23: 414588, 24: 414589,
    25: 414590, 26: 414591, 27: 414592, 28: 414593, 29: 414594, 30: 414595,
    31: 414596, 32: 414597, 33: 414598, 34: 414599, 35: 414600, 36: 414601,
    37: 414602, 38: 414603, 39: 414604, 40: 414605, 41: 414606, 42: 414607,
    43: 414608, 44: 414609, 45: 414610, 46: 414611, 47: 414612, 48: 414613,
    49: 414614, 50: 414615, 51: 414616, 52: 414617, 53: 414618, 54: 414619,
    55: 414620, 56: 414621, 57: 414622, 58: 414623, 59: 414624, 60: 414625,
    61: 414626, 62: 414627, 63: 414628, 64: 414629, 65: 414630, 66: 414631,
    67: 414632, 68: 414633, 69: 414634, 70: 414635, 71: 612536, 72: 612537,
    73: 1724620, 74: 1863206, 75: 1724626, 76: 1724625, 77: 1786210, 78: 2083737,
    79: 2214701, 80: 2420113, 81: 2566040, 82: 2420116, 83: 2867106, 84: 3057820,
    85: 2867165, 86: 3173137, 87: 3173145, 88: 3173146, 89: 3421504, 90: 4649945,
    91: 4801727, 92: 4805851, 93: 4998347, 94: 5179441, 95: 5061204, 96: 5109069,
    97: 5107875, 98: 5108056, 99: 5115092, 100: 5124687, 101: 5136089, 102: 5124091,
    103: 5136090, 104: 5140549, 105: 5160422, 106: 5172899, 107: 5194642, 108: 5266593,
    109: 5312686, 110: 539801455, 111: 539865809, 112: 539897633, 113: 539924194, 114: 539936465,
    115: 540001342, 116: 539979028, 117: 540018376, 118: 540031285, 119: 540054487, 120: 540080980,
    121: 540107778, 122: 540356598, 123: 540345953, 124: 540407858, 125: 540421180, 126: 540595990,
    127: 540598154, 128: 540607689, 129: 540608506, 130: 540604382, 131: 540695905, 132: 540731108,
    133: 540764070, 134: 540777079, 135: 540782834, 136: 540796325, 137: 540796324, 138: 540851348,
    139: 540873709, 140: 540882083, 141: 540944811, 142: 540953141, 143: 540959856, 144: 540980203,
    145: 541168585, 146: 541196024, 147: 541262292, 148: 541281405, 149: 541328407, 150: 541353885,
    151: 541357078, 152: 541504548, 153: 541539265, 154: 541662631, 155: 541750562, 156: 541783899,
    157: 541801500, 158: 541808940, 159: 542125732, 160: 542262321, 161: 542311064, 162: 542353354,
    163: 542597716,
}
ALL_AC_IDS = list(AC_MAP.values())

# Группы основных материалов (ОМ). Группа 3 — высокопрочные (подтверждено
# владельцем задачи); остальные подписи — справочные, по наблюдаемым маркам.
HIGH_STRENGTH_GROUP = 3
GROUP_HINTS = {
    1: "углеродистые и низколегированные (09Г2С, 17Г1С, С345 …)",
    2: "легированные теплоустойчивые Cr-Mo (наблюдалась 14Х2ГМР)",
    3: "высокопрочные (легированные конструкционные, σт > 360 МПа)",
    9: "аустенитные (12Х18Н10Т …)",
}


def is_high_strength(row, grade_matcher=None):
    """True if the technology covers group 3 base metal, or (when a
    grade_matcher(text)->bool is given) names a high-strength grade.
    See gotcha #5 for why the group number alone is not enough."""
    if HIGH_STRENGTH_GROUP in row.get("groups", []):
        return True
    return bool(grade_matcher and grade_matcher(row.get("osn_materialy", "")))


def get(url, params=None, tries=7):
    """naks_sm_lib.get() + длинный экспоненциальный backoff. На длинных
    обходах (сотни запросов подряд) naks.ru периодически рвёт соединение
    («Connection reset by peer», живой прогон 09.10.2026); короткие повторы
    внутри naks_sm_lib.get() этого не переживают."""
    last = None
    for i in range(tries):
        try:
            return _sm.get(url, params=params, tries=2)
        except Exception as e:  # noqa: BLE001 — сетевые ошибки requests
            last = e
            time.sleep(min(90, 5 * 2 ** i))
    raise last


def build_filter_params(
    section=None,          # key of SECTION or raw id
    vid_attestacii=None,   # str/list, keys of TYPE_ATT
    svarka=None,           # str/list, keys of SVARKA
    tech=None,             # str/list, keys of TECH
    num_acst=None,         # single raw num_acst id (used internally for sharding)
    num_sv=None,           # № свидетельства, substring/exact
    organization=None,     # Организация-заявитель, substring
    osn_materialy=None,    # Основные материалы, substring (e.g. "14Х2ГМР", "К60")
    date_active_from=None,  # "dd.mm.yyyy" — Срок действия до, range start
    date_active_to=None,    # "dd.mm.yyyy" — range end
    transneft=False,        # С учетом требований ПАО «Транснефть»
    gazprom=False,          # С учетом требований ПАО «Газпром»
):
    def _norm(val, table):
        if val is None:
            return []
        items = val if isinstance(val, (list, tuple, set)) else [val]
        return [table.get(v, v) for v in items]

    p = {"set_filter": "Y"}
    for i, v in enumerate(_norm(section, SECTION)):
        p[f"arrFilter_ff[SECTION_ID][{i}]"] = v
    for i, v in enumerate(_norm(vid_attestacii, TYPE_ATT)):
        p[f"arrFilter_pf[type_att][{i}]"] = v
    for i, v in enumerate(_norm(svarka, SVARKA)):
        p[f"arrFilter_pf[svarka][{i}]"] = v
    for i, v in enumerate(_norm(tech, TECH)):
        p[f"arrFilter_pf[tech][{i}]"] = v
    if num_acst is not None:
        p["arrFilter_pf[num_acst][0]"] = str(num_acst)
    if num_sv:
        p["arrFilter_pf[num_sv]"] = num_sv
    if organization:
        p["arrFilter_ff[NAME]"] = organization
    if osn_materialy:
        p["arrFilter_ff[PREVIEW_TEXT]"] = osn_materialy
    if date_active_from:
        p["arrFilter_DATE_ACTIVE_TO_1"] = date_active_from
    if date_active_to:
        p["arrFilter_DATE_ACTIVE_TO_2"] = date_active_to
    if transneft:
        p["arrFilter_pf[tn]"] = "ТН"
    if gazprom:
        p["arrFilter_pf[gazprom]"] = "1"
    return p


_URL_IN_JS = re.compile(r"""['"]((?:https?://naks\.ru)?/[^'"]*\.php\?[^'"]+)['"]""")


def _cell(td):
    return re.sub(r"\s+", " ", td.get_text(" ", strip=True).replace("\xa0", " ")).strip()


def parse_list_page(html):
    """Return (found_total_or_None, rows[]). found is 0 for an empty result."""
    if "ЗАПИСЕЙ НЕ НАЙДЕНО" in html:
        return 0, []
    m = re.search(r"НАЙДЕНО ЗАПИСЕЙ:\s*(\d+)", html)
    found = int(m.group(1)) if m else None

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="tabl")
    rows = []
    if table is None:
        return found, rows
    for tr in table.find_all("tr"):
        btn = tr.find("button")
        tds = tr.find_all("td", recursive=False)
        if btn is None or len(tds) < 9:
            continue
        (org, vid, sposoby, materialy, gruppy, sv_cell, srok, ac_name) = [_cell(t) for t in tds[:8]]
        sv_text = tds[5].get_text("|", strip=True).replace("\xa0", " ")
        parts = [x.strip() for x in sv_text.split("|") if x.strip()]
        svid = parts[0] if parts else sv_cell
        cm = re.search(r"аннулировано\s*(\d{2}\.\d{2}\.\d{4})?", sv_cell, re.I)
        onclick = btn.get("onclick", "") or ""
        um = _URL_IN_JS.search(html_lib.unescape(onclick))
        detail_url = um.group(1) if um else ""
        if detail_url.startswith("/"):
            detail_url = BASE + detail_url
        rows.append({
            "svid_num": svid,
            "cancelled": bool(cm),
            "cancel_date": cm.group(1) if cm and cm.group(1) else "",
            "organization": org,
            "vid_att": vid,
            "sposoby": sposoby,
            "osn_materialy": materialy,
            "gruppy": gruppy,
            "srok": srok,
            "ac_name": ac_name,
            "groups": base_metal_groups(materialy),
            "detail_onclick": onclick,
            "detail_url": detail_url,
        })
    return found, rows


# Номер группы ОМ в свободном тексте «Основных материалов». Реальные формы
# (живой реестр, 2026-10-09):
#   "1 (Ст3сп, …, 10, 15, 20 …)"   "Группа 1, марки согласно ПТД"
#   "1-14ХГНДЦ, 2-14ХГНДЦ"          "1 – 09Г2С, 20ГЛ, 2 – 10ХСНД, К56"
#   "1- 09Г2С и другие +3-30ХГСА"   "3(М03), 1+3 (М01 + М03) - 09Г2С + С590, S690"
#   "Группа 30 (ПЭ 80, ПЭ 100)"  ← группы 2x/3x — полимеры, не сталь
# Поэтому: содержимое скобок выкидываем (там списки марок вида "10, 15, 20"),
# номер считаем группой только в начале сегмента (после начала строки, «,», «;»,
# «+») и только если за ним идёт «(», тире или «+», либо перед ним слово «Группа».
# Коды М01/М02/М03… тоже дают номер группы.
_PARENS_RE = re.compile(r"\([^()]*\)")
_GROUP_RE = re.compile(
    r"(?:^|[,;+])\s*(?:(Групп[аы]\s*)(\d{1,2})|(\d{1,2})(?=\s*(?:\(|[-–—]|\+)))", re.I)
_M_CODE_RE = re.compile(r"(?<![\w])[МM]0(\d)(?!\d)")


def base_metal_groups(text):
    """Group numbers in «Основные материалы»: "1 (…), 9 (…)" -> [1, 9];
    "3(М03), 1+3 (М01 + М03) - …" -> [1, 3]."""
    t = text or ""
    groups = {int(d) for d in _M_CODE_RE.findall(t)}
    flat = _PARENS_RE.sub("(", t)
    for m in _GROUP_RE.finditer(flat):
        groups.add(int(m.group(2) or m.group(3)))
    return sorted(groups)


def _page(params, page, expected_min, max_tries=5, log=None):
    p = dict(params)
    if page > 1:
        p["PAGEN_1"] = str(page)
    found, rows = None, []
    for attempt in range(1, max_tries + 1):
        found, rows = parse_list_page(get(LIST_URL, params=p))
        if len(rows) >= expected_min:
            return found, rows
        if log:
            log(f"  short page {page} (got {len(rows)}, expected >= {expected_min}), retry {attempt}")
        time.sleep(0.8 * attempt)
    return found, rows


def _collect_leaf(params, found, log=None, sleep=0.2):
    out = {}
    pages = (found + PAGE_SIZE - 1) // PAGE_SIZE
    for page in range(1, pages + 1):
        expected = min(PAGE_SIZE, found - (page - 1) * PAGE_SIZE)
        _, rows = _page(params, page, expected, log=log)
        for r in rows:
            out[r["svid_num"]] = r
        time.sleep(sleep)
    if len(out) != found and log:
        log(f"  WARNING: leaf collected {len(out)} but site reported {found}")
    return out


def _to_ord(d):
    dd, mm, yy = map(int, d.split("."))
    import datetime as _dt
    return _dt.date(yy, mm, dd).toordinal()


def _from_ord(o):
    import datetime as _dt
    return _dt.date.fromordinal(o).strftime("%d.%m.%Y")


def _collect_with_bisect(params, date_from, date_to, log=None, sleep=0.2, depth=0):
    p = dict(params)
    p["arrFilter_DATE_ACTIVE_TO_1"] = date_from
    p["arrFilter_DATE_ACTIVE_TO_2"] = date_to
    found, _ = parse_list_page(get(LIST_URL, params=p))
    if not found:
        return {}
    if found < CAP:
        return _collect_leaf(p, found, log=log, sleep=sleep)
    a, b = _to_ord(date_from), _to_ord(date_to)
    if a >= b:
        if "arrFilter_pf[num_acst][0]" not in params:
            out = {}
            for ac in ALL_AC_IDS:   # один день всё ещё ≥ 500 — делим этот день по АЦ
                q = dict(params)
                q["arrFilter_pf[num_acst][0]"] = str(ac)
                out.update(_collect_with_bisect(q, date_from, date_to, log, sleep, depth + 1))
            return out
        if log:
            log(f"  WARNING: {found} rows on a single day {date_from} in one AC — still capped")
        return _collect_leaf(p, min(found, CAP), log=log, sleep=sleep)
    mid = (a + b) // 2
    if log:
        log(f"  {'  ' * depth}bisect {date_from}–{date_to} ({found}+)")
    out = _collect_with_bisect(params, date_from, _from_ord(mid), log, sleep, depth + 1)
    out.update(_collect_with_bisect(params, _from_ord(mid + 1), date_to, log, sleep, depth + 1))
    return out


def collect_rows(base_params, ac_ids=None, log=None, sleep=0.2,
                 default_from="01.01.2000", default_to="31.12.2099"):
    """Fetch every row matching base_params, beating the 500 cap (gotcha #1).

    Default: bisect the validity-date range until each leaf is < 500 (a day
    that is still capped is split by AC). Live check 2026-10-09: АЦСТ-1,
    active certificates -> 1457 rows, every leaf matched the site's count.
    Pass ac_ids=[...] to restrict to specific centres. Returns {svid_num: row}."""
    date_from = base_params.get("arrFilter_DATE_ACTIVE_TO_1", default_from)
    date_to = base_params.get("arrFilter_DATE_ACTIVE_TO_2", default_to)
    if ac_ids is None:
        return _collect_with_bisect(base_params, date_from, date_to, log=log, sleep=sleep)
    all_rows = {}
    for ac in ac_ids:
        p = dict(base_params)
        p["arrFilter_pf[num_acst][0]"] = str(ac)
        got = _collect_with_bisect(p, date_from, date_to, log=log, sleep=sleep)
        if got and log:
            log(f"AC id {ac}: {len(got)} rows")
        all_rows.update(got)
        time.sleep(sleep)
    return all_rows


# Подстроки «Основных материалов», которыми сайт сужает выборку до кандидатов
# в высокопрочные (подобраны на живом реестре 09.10.2026; фильтр сайта — по
# подстроке, пунктуацию учитывает плохо: "3(" и "3 (" возвращают почти всё).
# Это фильтр ПОЛНОТЫ, точность даёт is_high_strength() после сбора.
HS_QUERIES = [
    "М03", "M03", "Группа 3", "3 –", "3-",
    "К56", "К60", "К65", "X65", "X70", "X80",
    "С390", "С440", "С460", "С590", "S420", "S460", "S500", "S550", "S690", "S700",
    "S890", "S960", "Q690", "Weldox", "Strenx", "Hardox", "W700", "MAGSTRONG",
    "Quend", "14ХГНДЦ", "10ХСНД", "15ХСНД", "30ХГСА", "12ГН2МФАЮ", "14Х2ГМР", "АБ2",
    "высокопрочн",
]


def collect_high_strength(date_from=None, date_to="31.12.2099", grade_matcher=None,
                          queries=HS_QUERIES, log=None, sleep=0.3, cache_path=None):
    """Active, non-cancelled certificates for high-strength steels:
    union of site-level HS_QUERIES, then is_high_strength() on each row.
    cache_path: JSON-файл, куда после каждого запроса пишется результат —
    повторный запуск после обрыва продолжает с недоделанного запроса.
    Returns {svid_num: row} with row["_hs_reason"]."""
    import datetime as _dt
    import json as _json
    import os as _os
    date_from = date_from or _dt.date.today().strftime("%d.%m.%Y")
    cache = {}
    if cache_path and _os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            cache = _json.load(f)
        if cache.get("_date_from") != date_from:
            cache = {}
    cache["_date_from"] = date_from
    pool = {}
    for q in queries:
        if q in cache:
            got = cache[q]
        else:
            got = collect_rows(build_filter_params(osn_materialy=q, date_active_from=date_from,
                                                   date_active_to=date_to), log=log, sleep=sleep)
            if cache_path:
                cache[q] = got
                with open(cache_path, "w", encoding="utf-8") as f:
                    _json.dump(cache, f, ensure_ascii=False)
        if log:
            log(f"query {q!r}: {len(got)}")
        pool.update(got)
    out = {}
    for k, r in pool.items():
        if r["cancelled"]:
            continue
        by_group = HIGH_STRENGTH_GROUP in r["groups"]
        by_grade = bool(grade_matcher and grade_matcher(r["osn_materialy"]))
        if by_group or by_grade:
            r["_hs_reason"] = " + ".join(filter(None, ["группа 3 (М03)" if by_group else "",
                                                       "марка σт≥420" if by_grade else ""]))
            out[k] = r
    return out


def fetch_detail(row):
    """Detail («Область распространения») HTML for a list row, or None if
    the row carries no detail URL. Endpoint verified 2026-10-09:
    /ast/reestrattst2/detail.php?ID=<base64 of a PHP-serialized
    {svid_num (cp1251), svid_date}> — always take it from the row, never
    build it yourself."""
    url = row.get("detail_url")
    if not url:
        return None
    base, _, qs = url.partition("?")
    params = dict(kv.split("=", 1) for kv in qs.split("&") if "=" in kv)
    return get(base, params=params)


def _txt(el, sep=" "):
    for br in el.find_all("br"):
        br.replace_with("\n")
    t = el.get_text(sep, strip=True).replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", re.sub(r"\s*\n\s*", " | ", t)).strip(" |")


# Марки СМ в «Сварочные (наплавочные) материалы». Реальные формы (2026-10-09):
#   "электроды LB-52U и другие …"            "Проволока: AKEM4. Флюс: OK Flux 10.62P"
#   "ULTRA 700"                              "… марки Nittetsu L-74S и другие аналоги"
#   "типа Э50А марок LB-52U, ОК 53.70 …"     "Сварочная проволока: Св-08Г2С-О и другие"
# Ищем сами «марочные» токены, а не текст после ключевого слова: латинские
# бренды (≥1 цифра или ≥2 слова) и типовые отечественные обозначения.
_SM_LATIN_RE = re.compile(
    r"(?<![\w.-])([A-Z][A-Za-z]*[A-Za-z0-9.\-/]*(?:\s+(?:[A-Z][A-Za-z0-9.\-/]*|\d[\w.\-/]*)){0,2})")
_SM_CYR_RE = re.compile(
    r"(?<![\w-])((?:Св|УОНИ|ОЗС|АНО|МР|ЦЛ|ЦУ|ТМУ|ОК|ЛБ|ЭА|ТМЛ|ЦТ|ОЗЛ|НИАТ|ПП|ПГ)"
    r"[\s-]?\d[\w.\-/]*|Св-[\wА-Яа-я.\-/]+|ОК\s\d+\.\d+)")
_SM_NOT_MARK = re.compile(
    r"^(?:ПТД|НД|ГОСТ|ТУ|СТО|ISO|AWS|EN|DIN|РД|СП|ВСН)\b|^Э\d|^(?:CO2|СО2|Ar|M2[0-4]|C1)\b", re.I)  # газы — не марки


_LOOKALIKE = str.maketrans("АВЕКМНОРСТХ", "ABEKMHOPCTX")


def normalize_mark(tok):
    """Одна марка — одно написание: «ОК 53.70» (кириллица) -> «OK 53.70»,
    «УОНИ 13/55» -> «УОНИ-13/55», «Св-08Г2С» без изменений."""
    tok = re.sub(r"\s+", " ", tok.strip())
    if re.match(r"^[ОО][КK]\s", tok) or re.match(r"^[A-ZА-Я]{2}\s\d", tok) and tok[:2] in ("ОК", "ОK", "OК"):
        tok = tok[:2].translate(_LOOKALIKE) + tok[2:]
    tok = re.sub(r"^[ОO][КK]\s?(\d)", r"OK \1", tok)
    tok = re.sub(r"^УОНИ[\s-]*(\d)", r"УОНИ-\1", tok, flags=re.I)
    return tok


def sm_marks(text):
    """Consumable brands/grades named in the card, in order of appearance."""
    t = text or ""
    found = []
    for rx in (_SM_LATIN_RE, _SM_CYR_RE):
        for m in rx.finditer(t):
            tok = m.group(1).strip(" .,;")
            if _SM_NOT_MARK.search(tok):
                continue
            if rx is _SM_LATIN_RE and not (re.search(r"\d", tok) or " " in tok):
                continue
            found.append((m.start(), tok))
    out = []
    for _, tok in sorted(found):
        tok = normalize_mark(tok)
        if not any(tok in o or o in tok for o in out):
            out.append(tok)
    return out


def parse_detail(html, row):
    """Parse a detail card (layout verified on live cards 2026-10-09).

    Card = header table (Организация, Название технологии — with Шифр and
    Дата утверждения inside, Способ сварки, Группы ТУ) + «Параметры /
    Область распространения» table (one row per parameter; several value
    columns when the scope has several sub-ranges) + notes block.
    NB: the second table has unclosed <tr> tags, so html.parser nests
    rows — always read cells with recursive=False.

    Adds: tech_name, tech_shifr, tech_date, params {label: "v1 / v2"},
    sm_text, sm_marks, osn_materialy_card, notes, full_text, detail_available
    (False when the site answers «Информация об области аттестации …
    недоступна» — happens for some older certificates)."""
    rec = dict(row)
    rec.update(tech_name="", tech_shifr="", tech_date="", params={}, sm_text="",
               sm_marks=[], osn_materialy_card="", notes="", header={}, detail_available=bool(html))
    if html and "недоступна" in html and "Информация об области аттестации" in html:
        # Реальный ответ сайта для части старых свидетельств: «Информация об
        # области аттестации … недоступна. Обратитесь по телефону …»
        rec["detail_available"] = False
        html = None
    if not html:
        rec["full_text"] = row.get("osn_materialy", "")
        return rec
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")

    header = {}
    if tables:
        for tr in tables[0].find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) >= 2:
                header[_txt(tds[0]).rstrip(":")] = _txt(tds[1])
    rec["header"] = header
    name = header.get("Название технологии", "")
    # шифр может содержать запятую ("ТИ-РД-НГДО-1,3-2021") — режем по ", Дата утверждения"
    m = re.search(r"Шифр:\s*(.+?)(?:,\s*Дата утверждения:\s*(\d{2}\.\d{2}\.\d{4}))?\s*(?:г\.\s*)*$", name)
    rec["tech_name"] = name[:m.start()].rstrip(" .") if m else name
    rec["tech_shifr"] = m.group(1).strip() if m else ""
    rec["tech_date"] = (m.group(2) or "").rstrip(".") if m else ""

    params = {}
    for t in tables[1:]:
        for tr in t.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            if not tds:
                continue
            label = _txt(tds[0]).replace(" | ", " ").rstrip(":")
            if not label or label == "Параметры":
                continue
            vals = []
            for v in (_txt(c) for c in tds[1:]):
                if v and v not in vals:
                    vals.append(v)
            params.setdefault(label, " / ".join(vals))
    rec["params"] = params
    rec["sm_text"] = params.get("Сварочные (наплавочные) материалы", "")
    rec["sm_marks"] = sm_marks(rec["sm_text"])
    rec["osn_materialy_card"] = params.get("Группы и марки основных материалов", "")

    note = soup.find("div", class_="modal-note")
    rec["notes"] = _txt(note) if note else ""
    rec["full_text"] = " | ".join(filter(None, [
        rec["osn_materialy_card"] or row.get("osn_materialy", ""), rec["sm_text"],
        rec["tech_name"], rec["notes"]]))
    return rec


def verification_url(svid_num):
    """Clickable link that filters the live registry to one certificate."""
    return f"{FILTER_PAGE_URL}?arrFilter_pf[num_sv]={cp1251_url_value(svid_num)}&set_filter=Y"
