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
   2026-10-09. So `collect_rows()` shards by AC (163 centres, AC_MAP) and,
   for any shard still at >= 500, recursively BISECTS the
   «Срок действия свидетельства до» date range until every leaf is under
   the cap. Never trust a shard total of exactly 500.

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

6. DETAIL CARD («открыть» → «Область распространения») IS NOT VERIFIED.
   The modal is filled by an inline onclick handler on the button. The
   only tool available when this was written (a scraping proxy) strips
   on* attributes, so neither the detail endpoint nor the card markup
   could be inspected. parse_list_page() therefore extracts ANY URL found
   in the button's onclick (expected, by analogy with the SM registry, to
   be /ast/reestrattst2/detail.php?ID=...), and parse_detail() is a
   generic label/value + full-text extractor. On the first run with
   direct network access, print one onclick and one detail HTML and
   harden parse_detail() against the real layout before relying on
   detail fields (thicknesses, diameters, positions, consumables used).

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


def get(url, params=None, tries=4):
    return _sm.get(url, params=params, tries=tries)


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


_GROUP_RE = re.compile(r"(?:(?<=^)|(?<=[,+.]\s)|(?<=[,+]))\s*(?:Группа\s*)?(\d{1,2})\s*(?=\(|-\s|\s-\s)", re.I)


def base_metal_groups(text):
    """Group numbers mentioned in «Основные материалы»: "1 (…), 9 (…)" -> [1, 9]."""
    return sorted({int(g) for g in _GROUP_RE.findall(text or "")})


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
        if log:
            log(f"  WARNING: {found} rows on a single day {date_from} — still capped; "
                f"add another split (type_att/tech) for this shard")
        return _collect_leaf(p, min(found, CAP), log=log, sleep=sleep)
    mid = (a + b) // 2
    if log:
        log(f"  {'  ' * depth}bisect {date_from}–{date_to} ({found}+)")
    out = _collect_with_bisect(params, date_from, _from_ord(mid), log, sleep, depth + 1)
    out.update(_collect_with_bisect(params, _from_ord(mid + 1), date_to, log, sleep, depth + 1))
    return out


def collect_rows(base_params, ac_ids=None, log=None, sleep=0.2,
                 default_from="01.01.2000", default_to="31.12.2099"):
    """Fetch every row matching base_params, beating the 500 cap by AC
    sharding plus date bisection (gotcha #1). Returns {svid_num: row}."""
    date_from = base_params.get("arrFilter_DATE_ACTIVE_TO_1", default_from)
    date_to = base_params.get("arrFilter_DATE_ACTIVE_TO_2", default_to)

    if ac_ids is None:
        found, _ = parse_list_page(get(LIST_URL, params=base_params))
        if found is not None and found < CAP:
            if log:
                log(f"unsharded query: {found} rows")
            return _collect_leaf(base_params, found, log=log, sleep=sleep) if found else {}
        if log:
            log(f"unsharded query reported {found} -> sharding by {len(ALL_AC_IDS)} AC")
        ac_ids = ALL_AC_IDS

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


def fetch_detail(row):
    """Detail HTML for a list row, or None if no detail URL was found
    in the button's onclick (see gotcha #6)."""
    url = row.get("detail_url")
    if not url:
        return None
    base, _, qs = url.partition("?")
    params = dict(kv.split("=", 1) for kv in qs.split("&") if "=" in kv)
    return get(base, params=params)


def parse_detail(html, row):
    """Generic card parser (UNVERIFIED layout — gotcha #6): every
    "Label: value" line and every 2-cell table row, plus full_text."""
    rec = dict(row)
    if not html:
        rec.update(detail_fields={}, detail_text="", full_text=row.get("osn_materialy", ""))
        return rec
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    fields = {}
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) == 2 and cells[0] and len(cells[0]) < 80:
            fields.setdefault(cells[0].rstrip(":"), cells[1])
    for m in re.finditer(r"^([А-ЯЁA-Z][^:\n]{2,60}):\s*(.+)$", text, re.M):
        fields.setdefault(m.group(1).strip(), m.group(2).strip())
    rec["detail_fields"] = fields
    rec["detail_text"] = text
    rec["full_text"] = " | ".join(filter(None, [row.get("osn_materialy", ""), text]))
    return rec


def verification_url(svid_num):
    """Clickable link that filters the live registry to one certificate."""
    return f"{FILTER_PAGE_URL}?arrFilter_pf[num_sv]={cp1251_url_value(svid_num)}&set_filter=Y"
