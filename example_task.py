# -*- coding: utf-8 -*-
"""
EXAMPLE — not meant to be run as-is for every request. This is the template
to copy and adapt per the user's actual criteria; it reproduces the task
this skill was extracted from (find active Пс wire certificates whose real
classification is ER70S-6 or ER70S-G), to show the intended usage pattern:

  1. build_filter_params(...)      -> narrow down with whatever site-level
                                       filters apply (material type, welding
                                       method, organization, ТУ/ГОСТ text,
                                       diameter, attestation type, a specific
                                       AC, date range, Транснефть flag...)
  2. collect_rows(...)             -> shards across AC automatically if the
                                       site's own 500-cap would otherwise
                                       hide rows; excludes nothing by itself
  3. drop cancelled rows           -> per the user's definition of "active"
  4. fetch_detail() + parse_detail() for every remaining row
  5. YOUR OWN predicate over the parsed record (full_text / primechaniya /
     any specific field) — this is the part that changes per request; it is
     NOT baked into the library, because "criteria" is open-ended
  6. write_xlsx(...) with a column layout matching the user's ask
"""
import re
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
import naks_sm_lib as naks
from xlsx_helper import write_xlsx, DEFAULT_COLUMNS

TODAY = "09.09.2026"  # dd.mm.yyyy — replace with the actual current date


def log(msg):
    print(msg, flush=True)


def main():
    # 1) Site-level filter: material type "Пс" (solid wire), active only
    #    (срок действия >= today). Add organization=..., svarka=[...],
    #    tech=[...], tu_gost=..., diametr=..., vid_attestacii=... etc. as
    #    the user's request actually calls for.
    base_params = naks.build_filter_params(
        shifr_sm="Пс",
        date_active_from=TODAY,
        date_active_to="31.12.2099",
    )

    # 2) Collect every matching row, auto-sharded by AC if needed.
    rows = naks.collect_rows(base_params, log=log)
    log(f"collected {len(rows)} raw rows")

    # 3) "Active" for this user meant: not cancelled either.
    active_rows = [r for r in rows.values() if not r["cancelled"]]
    log(f"{len(active_rows)} active (non-cancelled) rows to inspect")

    # 4+5) Open each card; keep only those whose REAL classification
    #      (not just the brand name) is ER70S-6 or ER70S-G per AWS A5.18.
    cls_re = re.compile(r"\bER\s*-?\s*70\s*S\s*-?\s*(6|G)\b", re.IGNORECASE)
    matches = []
    for i, row in enumerate(active_rows, 1):
        html = naks.fetch_detail(row["id_param"])
        rec = naks.parse_detail(html, row)
        m = cls_re.search(rec["full_text"])
        if m:
            rec["klassifikaciya_naydena"] = f"ER70S-{m.group(1).upper()}"
            rec["_verify_url"] = naks.verification_url(rec["svid_num"])
            matches.append(rec)
        if i % 50 == 0:
            log(f"{i}/{len(active_rows)} checked, {len(matches)} matches so far")

    log(f"DONE: {len(matches)} matches out of {len(active_rows)} checked")

    # 6) Write results. Customize `columns` per the user's requested layout;
    #    DEFAULT_COLUMNS is a reasonable generic starting point.
    write_xlsx(
        matches,
        out_path="naks_result.xlsx",
        columns=DEFAULT_COLUMNS,
        sort_key=lambda r: (r.get("klassifikaciya_naydena", ""), r["svid_num"]),
        summary=[
            ("Источник", naks.FILTER_PAGE_URL),
            ("Критерий", "Шифр СМ = Пс, действующие, классификация ER70S-6/ER70S-G"),
            ("Всего найдено (сайт)", len(rows)),
            ("Проверено активных карточек", len(active_rows)),
            ("Совпадений", len(matches)),
        ],
    )


if __name__ == "__main__":
    main()
