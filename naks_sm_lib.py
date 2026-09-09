# -*- coding: utf-8 -*-
"""
naks_sm_lib.py — reusable, bug-fixed engine for scraping the NAKS registry
of attested welding materials: https://naks.ru/registry/reg/sm/

This is a LIBRARY, not a fixed-purpose script. It was generalized from a
one-off task that filtered for a single wire classification (ER70S-6 /
ER70S-G). It exposes the reliable primitives; the caller (Claude, driving
this per the user's actual request) composes filters and post-fetch
predicates for whatever criteria the user actually asked for — material
type, organization, diameter, standard/ТУ, welding method, technical
device group, attestation type, a specific AC, status, or any free-text
match against the card's real content (classification notes included).

=====================================================================
THINGS THAT WILL SILENTLY CORRUPT YOUR DATA IF YOU DON'T KNOW THEM
=====================================================================

1. THE SITE CAPS ANY SINGLE FILTERED QUERY AT 500 ROWS ("НАЙДЕНО ЗАПИСЕЙ").
   If your query is broad enough to hit 500, you are NOT seeing everything —
   silently. Work around it by sharding the query across the ~65
   "Регистрационный номер АЦ" (attestation center) values in AC_MAP, one
   shard at a time, and summing. `collect_rows()` below does this
   automatically ONLY when the unsharded query reports >= 500; for a
   narrow query (e.g. a specific organization name) it does one fetch.

2. DO NOT REUSE A requests.Session()/cookie jar ACROSS MANY DIFFERENT
   FILTER COMBINATIONS IN ONE RUN. The site keeps some pagination/filter
   state server-side keyed by PHPSESSID. Empirically: after ~40 distinct
   filter combinations were queried in one session, a "page=1" request
   started returning a DIFFERENT page's content (silently wrong data,
   no error). The site needs no login, so `get()` below makes every
   request stateless (no persisted cookies) plus a unique cache-busting
   nonce param, and it verifies collected row counts against the site's
   own reported total, retrying short pages. Do not "optimize" this by
   reintroducing a shared Session for speed — it reintroduces silent
   corruption that is easy to miss (the run completes with no errors,
   just fewer rows than actually exist).

3. THE LIST PAGE DOES **NOT** RELIABLY SHOW THE REAL CLASSIFICATION.
   The "Классификация (состав)" column in the search results is usually
   "-" / "---" (empty) even when the certificate DOES have a documented
   AWS/EN/ISO classification. The real classification (when the
   manufacturer's brand name isn't itself the classification) lives as
   free text inside the certificate's "Примечания" list, e.g.:
     "...имеет классификацию по AWS A5.18: ER70S-6"
   You must open the individual certificate card (detail.php) and read
   its full text to filter on classification reliably — filtering on the
   "Марка СМ" (brand) text alone WILL both miss and wrongly-include
   certificates. `parse_detail()` returns `full_text` (marka + tu_gost +
   notes, unescaped) specifically so callers can regex/substring-match
   against the real content, not just the brand name.

4. A CERTIFICATE CAN BE "аннулировано" (cancelled) WHILE ITS PRINTED
   VALIDITY DATE IS STILL IN THE FUTURE. Filtering by
   arrFilter_DATE_ACTIVE_TO_1/_2 alone is NOT enough to get only truly
   active certificates — a cancelled-but-not-yet-expired row shows
   "аннулировано <date>" appended under the certificate number in the
   list. `parse_list_page()` sets `cancelled=True` for these; decide
   per the user's actual definition of "active" whether to exclude them
   (usually yes).

5. THERE ARE (AT LEAST) TWO DETAIL-CARD LAYOUTS. Most cards are
   "producer" cards: the top organization IS the one that holds the
   attestation (usually the material's producer), tagged with a
   parenthetical role like "(производитель СМ)". Some cards are
   "потребитель СМ" (end-user / consignment) cards: the top organization
   is the CONSUMER who received a batch, and the real producer appears
   as a plain inline field "Производитель СМ: <name>" rather than a
   role-tagged organization block — these also carry "Партия" (batch)
   and "Сертификат качества" fields that producer cards don't have.
   `parse_detail()` handles both; don't assume the top organization is
   always the producer.

6. ENCODING IS windows-1251, NOT UTF-8 — for both the page you fetch
   (set `r.encoding = "windows-1251"`) and for any Cyrillic text you
   put INTO a URL query param (e.g. the verification link, or a text
   filter like Организация-заявитель). Percent-encode Cyrillic text by
   encoding to the 'cp1251' codec first, then percent-encoding the
   bytes — normal UTF-8 URL-encoding of Cyrillic will get you zero
   results with no error.

=====================================================================
REFERENCE DATA
=====================================================================
Filter checkbox values, decoded from the live filter form on
2026-09-08/09. Re-verify if the site changes (fetch the form and match
`<input name="...">` values against their adjacent label text).
"""

import re
import time
import html as html_lib
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup

BASE = "https://naks.ru"
LIST_URL = BASE + "/asm/reestrattsm2/index.php"
FILTER_PAGE_URL = BASE + "/registry/reg/sm/"
DETAIL_URL = BASE + "/asm/reestrattsm2/detail.php"

# Шифр СМ — material-shape code (what kind of consumable)
SHIFR_SM = {
    "Гг": "1200",   # газ горючий (fuel gas)
    "Гз": "1199",   # газ защитный (shielding gas)
    "Пм": "5186711",  # проволока порошковая (наплавочная?) — verify label meaning if it matters
    "Пп": "1198",   # проволока порошковая
    "Пр": "5186710",  # пруток
    "Пс": "1197",   # проволока сплошного сечения (solid wire)
    "Тм": "5186709",  # тврдый / термическая? — verify if used
    "Ф": "1201",    # флюс
    "Эн": "1196",   # электрод наплавочный
    "Эп": "1195",   # электрод покрытый
}

# Вид аттестации
TYPE_ATT = {
    "Вн": "4038107",
    "Дп": "414730",
    "Пв": "414729",
    "Пр": "416072",
}

# Способы сварки (наплавки) — extend/correct from the live form if needed
SVARKA = {
    "ААД": "1160", "ААДН": "1176", "ААДП": "1162", "ААДПН": "5256714",
    "АЛСН": "549415", "АПГ": "1161", "АПГН": "5256715", "АПИ": "542954",
    "АПИН": "572770", "АППГ": "592135", "АППГН": "612546", "АПС": "612549",
    "АПСН": "572771", "АФ": "1163", "АФДС": "612545", "АФЛН": "1177",
    "АФПН": "1178", "ВЧС": "1182", "Г": "1173", "ГН": "542019", "ЗН": "1185",
    "ИН": "612552", "К": "5256810", "КСО": "1181", "КСС": "1180",
    "КТС": "1179", "КШС": "5256811", "Л": "5256812", "МАД": "542083697",
    "МАДП": "1158", "МАДПН": "5256826", "МДС": "569687", "МКС": "612544",
    "МЛСН": "612543", "МП": "1159", "МПГ": "1167", "МПГН": "612539",
    "МПИ": "612540", "МПИН": "612538", "МПН": "542526", "МПС": "1166",
    "МПСН": "612542", "МСОД": "1169", "МФ": "1164", "НГ": "1186",
    "НИ": "1184", "П": "1170", "ПАК": "1183", "ПНП": "612551",
    "ППН": "612550", "РАД": "1157", "РАДН": "1175", "РД": "1155",
    "РДН": "1174", "СТ": "5256827", "Т": "5256828", "Э": "1187",
    "ЭЛ": "1172", "ЭШ": "1171", "Руководство": "1188", "ПиА": "1189",
}

# Группы технических устройств
TECH = {
    "ГДО": "1152", "ГО": "1149", "КО": "1148", "КСМ": "2566042",
    "МО": "1153", "НГДО": "1150", "НД": "1273", "ОТОГ": "1154",
    "ОХНВП": "1151", "ПР": "1192", "ПТО": "1147", "СК": "568801",
}

# Регистрационный номер АЦ -> internal num_acsm id (АЦСМ-1 .. АЦСМ-65).
# The site shards nothing by itself; WE shard by this to beat the 500 cap.
AC_MAP = {
    1: 1084, 2: 1085, 3: 1086, 4: 1087, 5: 1088, 6: 1089, 7: 1090, 8: 1091,
    9: 1092, 10: 1093, 11: 1094, 12: 1095, 13: 414479, 14: 414480,
    15: 414481, 16: 414482, 17: 414483, 18: 414484, 19: 414485, 20: 414486,
    21: 414487, 22: 414488, 23: 414489, 24: 414490, 25: 414491, 26: 414492,
    27: 414493, 28: 414494, 29: 414495, 30: 414496, 31: 414497, 32: 414498,
    33: 414499, 34: 517075, 35: 1839847, 36: 414501, 37: 414502, 38: 414503,
    39: 414504, 40: 612533, 41: 1724619, 42: 2214699, 43: 2420114,
    44: 3173138, 45: 3173148, 46: 4649943, 47: 4821228, 48: 5108054,
    49: 5115090, 50: 5124688, 51: 5136087, 52: 5124089, 53: 5134743,
    54: 5160424, 55: 5165266, 56: 5381161, 57: 540031283, 58: 540107079,
    59: 540407676, 60: 540604380, 61: 540707859, 62: 540730641,
    63: 540782832, 64: 541137834, 65: 541539263,
}
ALL_AC_IDS = list(AC_MAP.values())

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
}

_nonce_counter = [0]


def get(url, params=None, tries=4):
    """Stateless GET (no cookie jar reuse — see gotcha #2) with a
    cache-busting nonce (see the transient-empty-page issue in gotcha #2)
    and retry-with-backoff on network errors."""
    _nonce_counter[0] += 1
    params = dict(params or {})
    params["_cb"] = f"{int(time.time() * 1000)}{_nonce_counter[0]}"
    last_exc = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=25)
            r.encoding = "windows-1251"
            return r.text
        except Exception as e:
            last_exc = e
            time.sleep(1.5 * (i + 1))
    raise last_exc


def cp1251_url_value(text):
    """Percent-encode Cyrillic text the way this site's GET filter forms
    expect (windows-1251 bytes), not UTF-8. Use for building a
    human-clickable verification/search link, e.g. by № свидетельства
    or by Организация-заявитель."""
    return quote(text.encode("cp1251"))


def build_filter_params(
    shifr_sm=None,        # str or list[str], keys of SHIFR_SM (e.g. "Пс") or raw ids
    vid_attestacii=None,  # str or list[str], keys of TYPE_ATT (e.g. "Пв") or raw ids
    svarka=None,           # str or list[str], keys of SVARKA or raw ids
    tech=None,             # str or list[str], keys of TECH or raw ids
    num_acsm=None,         # single raw num_acsm id (used internally for sharding)
    num_sv=None,           # № свидетельства, substring/exact text
    organization=None,     # Организация-заявитель, substring text (arrFilter_ff[NAME])
    marka_sm=None,         # Марка СМ, substring text (arrFilter_ff[PREVIEW_TEXT])
    tu_gost=None,          # ТУ/ГОСТ, substring text (arrFilter_ff[DETAIL_TEXT])
    diametr=None,          # Диаметр, мм — text as shown on site (e.g. "1,2")
    date_active_from=None,  # "dd.mm.yyyy" — Срок действия свидетельства до, range start
    date_active_to=None,    # "dd.mm.yyyy" — range end
    transneft=False,        # "С учетом требований ПАО Транснефть" checkbox
):
    """Translate human-friendly criteria into the site's raw GET params.
    Any of these can be combined freely; omit what you don't need."""

    def _norm(val, table):
        if val is None:
            return []
        if isinstance(val, (list, tuple, set)):
            items = val
        else:
            items = [val]
        return [table.get(v, v) for v in items]  # falls back to raw id if not a known label

    params = {"set_filter": "Y"}

    for i, v in enumerate(_norm(shifr_sm, SHIFR_SM)):
        params[f"arrFilter_pf[shifr_sm][{i}]"] = v
    for i, v in enumerate(_norm(vid_attestacii, TYPE_ATT)):
        params[f"arrFilter_pf[type_att][{i}]"] = v
    for i, v in enumerate(_norm(svarka, SVARKA)):
        params[f"arrFilter_pf[svarka][{i}]"] = v
    for i, v in enumerate(_norm(tech, TECH)):
        params[f"arrFilter_pf[tech][{i}]"] = v
    if num_acsm is not None:
        params["arrFilter_pf[num_acsm][0]"] = str(num_acsm)
    if num_sv:
        params["arrFilter_pf[num_sv]"] = num_sv
    if organization:
        params["arrFilter_ff[NAME]"] = organization
    if marka_sm:
        params["arrFilter_ff[PREVIEW_TEXT]"] = marka_sm
    if tu_gost:
        params["arrFilter_ff[DETAIL_TEXT]"] = tu_gost
    if diametr:
        params["arrFilter_pf[diametr]"] = diametr
    if date_active_from:
        params["arrFilter_DATE_ACTIVE_TO_1"] = date_active_from
    if date_active_to:
        params["arrFilter_DATE_ACTIVE_TO_2"] = date_active_to
    if transneft:
        params["arrFilter_pf[tn]"] = "ТН"
    return params


def parse_list_page(html):
    """Return (found_total_or_0, rows[]). Each row keeps every list-view
    column plus the base64 `id_param` needed to fetch its detail card."""
    if "ЗАПИСЕЙ НЕ НАЙДЕНО" in html:
        return 0, []
    m = re.search(r"ЗАПИСЕЙ:\s*(\d+)", html)
    found = int(m.group(1)) if m else None

    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for btn in soup.find_all("button", onclick=re.compile("detail.php")):
        onclick = btn.get("onclick", "")
        idm = re.search(r"ID=([A-Za-z0-9+/=]+)", onclick)
        if not idm:
            continue
        id_param = idm.group(1)
        tr = btn.find_parent("tr")
        if tr is None:
            continue
        tds = tr.find_all("td")
        cells = [td.get_text(separator="|", strip=True) for td in tds]
        if len(cells) < 13:
            continue
        (organization, vid_att, shifr, marka, klass_col, partiya, diametr,
         tu_gost, sposoby, gruppy, num_sv_cell, srok, ac_name) = cells[:13]

        parts = [x for x in num_sv_cell.split("|") if x.strip()]
        svid_num = parts[0].strip() if parts else num_sv_cell.strip()
        cancelled = "аннулировано" in num_sv_cell.lower()

        rows.append({
            "svid_num": svid_num, "cancelled": cancelled, "id_param": id_param,
            "organization_list": organization, "vid_att": vid_att, "shifr": shifr,
            "marka": marka, "klass_col": klass_col, "partiya": partiya,
            "diametr": diametr, "tu_gost": tu_gost, "sposoby": sposoby,
            "gruppy": gruppy, "srok": srok, "ac_name": ac_name,
        })
    return found, rows


def _fetch_page_with_retry(base_params, page, expected_min, max_tries=5, log=None):
    p = dict(base_params)
    if page > 1:
        p["PAGEN_1"] = str(page)
    for attempt in range(1, max_tries + 1):
        html = get(LIST_URL, params=p)
        found, rows = parse_list_page(html)
        if len(rows) >= expected_min:
            return found, rows
        if log:
            log(f"  short page (got {len(rows)}, expected >= {expected_min}), "
                f"retry {attempt}/{max_tries}")
        time.sleep(0.8 * attempt)
    return found, rows


def collect_rows(base_params, ac_ids=None, log=None, sleep=0.2):
    """Fetch every row matching `base_params` (from build_filter_params),
    automatically sharding by AC (see gotcha #1) only when needed.

    - If `ac_ids` is given, always shard across exactly that list (use
      this when the user asked about a specific AC / list of ACs).
    - Otherwise, probe once unsharded: if the reported total is < 500,
      that single (paginated) query already has everything. If it is
      >= 500 (i.e. possibly capped), fall back to sharding across
      ALL_AC_IDS to get the true, complete total.

    Returns dict {svid_num: row_dict}.
    """
    def log_(msg):
        if log:
            log(msg)

    def collect_for_params(params):
        out = {}
        found, rows = _fetch_page_with_retry(params, 1, 0, log=log)
        if not found:
            return out
        for r in rows:
            out[r["svid_num"]] = r
        total_pages = (found + 24) // 25
        for page in range(2, total_pages + 1):
            remaining = found - (page - 1) * 25
            expected_min = min(25, remaining)
            _, rows = _fetch_page_with_retry(params, page, expected_min, log=log)
            for r in rows:
                out[r["svid_num"]] = r
            time.sleep(sleep)
        if len(out) != found:
            log_(f"  WARNING: shard collected {len(out)} but site reported {found} "
                 f"(params={ {k: v for k, v in params.items() if k != '_cb'} })")
        return out

    all_rows = {}
    if ac_ids is not None:
        for ac in ac_ids:
            p = dict(base_params)
            p["arrFilter_pf[num_acsm][0]"] = str(ac)
            got = collect_for_params(p)
            log_(f"AC id {ac}: {len(got)} rows")
            all_rows.update(got)
            time.sleep(sleep)
        return all_rows

    # probe unsharded
    probe_html = get(LIST_URL, params=base_params)
    found, _ = parse_list_page(probe_html)
    if found is not None and found < 500:
        log_(f"unsharded query: {found} rows (under the cap, no sharding needed)")
        return collect_for_params(base_params)

    log_(f"unsharded query reported {found} (>= 500 cap or unknown) -> sharding by AC")
    for ac in ALL_AC_IDS:
        p = dict(base_params)
        p["arrFilter_pf[num_acsm][0]"] = str(ac)
        got = collect_for_params(p)
        if got:
            log_(f"AC id {ac}: {len(got)} rows")
        all_rows.update(got)
        time.sleep(sleep)
    return all_rows


def fetch_detail(id_param):
    return get(DETAIL_URL, params={"ID": id_param})


_EXTRA_ORG_RE = re.compile(
    r"Организация\s*-\s*([^:<]{2,60}):\s*(?:</[a-zA-Z][a-zA-Z0-9]*>\s*)*<span[^>]*>\s*([^<]+)",
    re.IGNORECASE,
)


def parse_detail(html, list_row):
    """Parse one certificate card into a structured dict. Always returns
    a record (never None) — filtering on content is the CALLER's job,
    using `full_text` / `primechaniya` / any other field. This is what
    makes the library reusable for arbitrary criteria instead of only
    ER70S-6/G classification."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)

    top_org_name = None
    top_org_role = None
    m = re.search(r"Организация:\s*</span>\s*<span[^>]*>\s*([^<]+)", html)
    if not m:
        m = re.search(r"Организация:\s*([^<\n]+)", html)  # older/simpler markup, no <span>
    if m:
        top_org_name = html_lib.unescape(m.group(1).strip())
    m2 = re.search(
        r"\(([^()<>]{0,40}(?:производит|поставщ|заявит|изготовит|представит|"
        r"дистрибьют|потребит)[^()<>]{0,40})\)",
        html, re.IGNORECASE,
    )
    if m2:
        top_org_role = html_lib.unescape(m2.group(1).strip())

    extra_orgs = []
    for lm in _EXTRA_ORG_RE.finditer(html):
        role = html_lib.unescape(lm.group(1).strip())
        val = html_lib.unescape(re.sub(r"<[^>]+>", "", lm.group(2).strip()))
        extra_orgs.append((role, val))

    inline_producer = None
    ipm = re.search(r"Производитель\s+СМ\s*:\s*</[bB]>\s*([^<\n]+)", html)
    if not ipm:
        ipm = re.search(r"Производитель\s+СМ\s*:\s*([^<\n]+)", text)
    if ipm:
        inline_producer = html_lib.unescape(ipm.group(1).strip())

    proizvoditel = zayavitel = predstavitel = postavshik = potrebitel = ""
    if top_org_role:
        rl = top_org_role.lower()
        if "производит" in rl or "изготовит" in rl:
            proizvoditel = top_org_name or ""
        elif "поставщ" in rl:
            postavshik = top_org_name or ""
        elif "заявит" in rl:
            zayavitel = top_org_name or ""
        elif "представит" in rl:
            predstavitel = top_org_name or ""
        elif "потребит" in rl:
            potrebitel = top_org_name or ""
    for role, val in extra_orgs:
        rl = role.lower()
        if "представит" in rl and not predstavitel:
            predstavitel = val
        elif "заявит" in rl and not zayavitel:
            zayavitel = val
        elif "поставщ" in rl and not postavshik:
            postavshik = val
        elif ("производит" in rl or "изготовит" in rl) and not proizvoditel:
            proizvoditel = val
    if not proizvoditel and inline_producer:
        proizvoditel = inline_producer

    def field(label):
        mm = re.search(re.escape(label) + r"\s*:\s*([^\n]+)", text)
        return mm.group(1).strip() if mm else ""

    title_m = re.search(r"<h4[^>]*>([^<]+)</h4>", html)
    svid_num_card = title_m.group(1).strip() if title_m else list_row.get("svid_num", "")

    protokol = ""
    pm = re.search(r"Основание:\s*([^\n]+)", text)
    if pm:
        protokol = pm.group(1).strip()

    ac_full_name = ""
    am = re.search(r"Наименование и юридический адрес [^:]+:\s*([^\n]+)", text)
    if am:
        ac_full_name = am.group(1).strip()

    primech = ""
    pm2 = soup.find(string=re.compile("Примечания"))
    if pm2:
        parent = pm2.find_parent("div")
        if parent:
            lis = parent.find_all("li")
            primech = " | ".join(li.get_text(" ", strip=True) for li in lis)

    marka_sm = field("Марка СМ") or list_row.get("marka", "")
    tu_gost = field("Технические требования к СМ") or list_row.get("tu_gost", "")
    partiya = field("Партия") or list_row.get("partiya", "")
    sert_kach = field("Сертификат качества")

    rec = {
        "svid_num": svid_num_card,
        "cancelled": list_row.get("cancelled", False),
        "srok_deystviya": list_row.get("srok", ""),
        "ac_reg_num": list_row.get("ac_name", ""),
        "top_org_name": top_org_name or "",
        "top_org_role": top_org_role or "",
        "proizvoditel": proizvoditel,
        "zayavitel": zayavitel,
        "predstavitel": predstavitel,
        "postavshik": postavshik,
        "potrebitel": potrebitel,
        "vid_attestacii": field("Вид аттестации") or list_row.get("vid_att", ""),
        "vid_sm": field("Вид СМ") or list_row.get("shifr", ""),
        "marka_sm": marka_sm,
        "diametr": field("Диаметр, мм") or list_row.get("diametr", ""),
        "tu_gost": tu_gost,
        "partiya": partiya,
        "sertifikat_kachestva": sert_kach,
        "sposoby_svarki": list_row.get("sposoby", ""),
        "gruppy_tu": list_row.get("gruppy", ""),
        "primechaniya": primech,
        "protokol_osnovanie": protokol,
        "ac_yur_adres": ac_full_name,
        "id_param": list_row.get("id_param", ""),
    }
    # Concatenated free-text blob for callers to regex/substring-match on —
    # this is what makes classification (or any other free-text) filtering
    # reliable, since the list view's own columns are frequently blank.
    rec["full_text"] = " | ".join(filter(None, [marka_sm, tu_gost, primech]))
    return rec


def verification_url(svid_num):
    """A real, working link a human can click to look up one certificate
    by number on the live site (uses the num_sv text filter)."""
    return (f"{FILTER_PAGE_URL}?arrFilter_pf[num_sv]="
            f"{cp1251_url_value(svid_num)}&set_filter=Y")
