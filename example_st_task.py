# -*- coding: utf-8 -*-
"""
EXAMPLE (шаблон, адаптировать под запрос): все ДЕЙСТВУЮЩИЕ свидетельства
о готовности к применению технологий сварки ВЫСОКОПРОЧНЫХ сталей —
группа 3 ОМ или явная высокопрочная марка (σт ≥ 420) в «Основных
материалах» — с выгрузкой в Excel. Это список предприятий, которые уже
варят высокопрочные стали по аттестованной технологии: прямые лиды на СМ.

    python3 example_st_task.py [--ac 1 5 17] [--out naks_st_hs.xlsx]
"""
import argparse
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "monitoring"))
import naks_st_lib as st  # noqa: E402
from xlsx_helper import write_xlsx  # noqa: E402
from classify import classify  # noqa: E402  (словарь марок мониторинга)


def grade_matcher(text):
    c = classify(text)
    return bool(c and (c["max_class"] or 0) >= 420)


COLUMNS = [
    ("№ свидетельства", lambda r: r["svid_num"]),
    ("Организация-заявитель", lambda r: r["organization"]),
    ("Группы ОМ", lambda r: ", ".join(map(str, r["groups"]))),
    ("Высокопрочные: основание", lambda r: r["_hs_reason"]),
    ("Основные материалы", lambda r: r["osn_materialy"]),
    ("Способы сварки", lambda r: r["sposoby"]),
    ("Группы ТУ", lambda r: r["gruppy"]),
    ("Вид аттестации", lambda r: r["vid_att"]),
    ("Срок действия до", lambda r: r["srok"]),
    ("АЦСТ", lambda r: r["ac_name"]),
    ("Ссылка для проверки", lambda r: r["_verify_url"]),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ac", type=int, nargs="*", help="номера АЦСТ (по умолчанию все 163)")
    ap.add_argument("--out", default="naks_st_high_strength.xlsx")
    a = ap.parse_args()

    today = dt.date.today().strftime("%d.%m.%Y")
    params = st.build_filter_params(date_active_from=today, date_active_to="31.12.2099")
    ac_ids = [st.AC_MAP[n] for n in a.ac] if a.ac else None
    rows = st.collect_rows(params, ac_ids=ac_ids, log=print)
    active = [r for r in rows.values() if not r["cancelled"]]

    hits = []
    for r in active:
        by_group = st.HIGH_STRENGTH_GROUP in r["groups"]
        by_grade = grade_matcher(r["osn_materialy"])
        if by_group or by_grade:
            r["_hs_reason"] = " + ".join(filter(None, ["группа 3" if by_group else "",
                                                       "марка σт≥420" if by_grade else ""]))
            r["_verify_url"] = st.verification_url(r["svid_num"])
            hits.append(r)
    print(f"собрано {len(rows)}, действующих {len(active)}, высокопрочных {len(hits)}")

    orgs = sorted({r["organization"] for r in hits})
    write_xlsx(hits, a.out, columns=COLUMNS, sheet_name="Технологии ВП сталей",
               summary=[("Дата выгрузки", today), ("Действующих свидетельств", len(active)),
                        ("Из них по высокопрочным", len(hits)), ("Уникальных организаций", len(orgs))],
               sort_key=lambda r: (r["organization"], r["svid_num"]))
    print("→", a.out)


if __name__ == "__main__":
    main()
