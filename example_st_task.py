# -*- coding: utf-8 -*-
"""
EXAMPLE (шаблон, адаптировать под запрос): все ДЕЙСТВУЮЩИЕ свидетельства
о готовности к применению технологий сварки ВЫСОКОПРОЧНЫХ сталей —
группа 3 ОМ или явная высокопрочная марка (σт ≥ 420) в «Основных
материалах» — с выгрузкой в Excel. Это список предприятий, которые уже
варят высокопрочные стали по аттестованной технологии: прямые лиды на СМ.

    python3 example_st_task.py [--no-detail] [--out naks_st_hs.xlsx]

Сбор: collect_high_strength() — объединение целевых запросов по «Основным
материалам» (HS_QUERIES) + проверка группы 3 (М03) / марки σт ≥ 420.
Затем для каждой записи открывается карточка «Область распространения»:
технология, СМ (марки!), толщины, диаметры, подогрев.
"""
import argparse
import datetime as dt
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "monitoring"))
import naks_st_lib as st  # noqa: E402
from xlsx_helper import write_xlsx  # noqa: E402
from classify import classify  # noqa: E402  (словарь марок мониторинга)


def grade_matcher(text):
    # префикс даёт классификатору контекст «сталь» — в реестре его нет, а без
    # него голые марки (К56, С440, S460) отбрасываются как шум
    c = classify("сталь: " + text)
    return bool(c and (c["max_class"] or 0) >= 420)


COLUMNS = [
    ("№ свидетельства", lambda r: r["svid_num"]),
    ("Организация-заявитель", lambda r: r["organization"]),
    ("СМ: марки", lambda r: ", ".join(r.get("sm_marks", []))),
    ("СМ: как в карточке", lambda r: r.get("sm_text", "")),
    ("Технология (шифр, дата)", lambda r: " ".join(filter(None, [r.get("tech_shifr", ""), r.get("tech_date", "")]))),
    ("Толщины, мм", lambda r: r.get("params", {}).get("Диапазон толщин, мм", "")),
    ("Подогрев", lambda r: r.get("params", {}).get("Наличие подогрева", "")),
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
    ap.add_argument("--no-detail", action="store_true", help="не открывать карточки")
    ap.add_argument("--out", default="naks_st_high_strength.xlsx")
    a = ap.parse_args()

    today = dt.date.today().strftime("%d.%m.%Y")
    rows = st.collect_high_strength(date_from=today, grade_matcher=grade_matcher,
                                    log=lambda m: print(m) if m.startswith("query") else None)
    hits = list(rows.values())
    print(f"высокопрочных действующих свидетельств: {len(hits)}")

    for i, r in enumerate(hits, 1):
        r["_verify_url"] = st.verification_url(r["svid_num"])
        if not a.no_detail:
            r.update(st.parse_detail(st.fetch_detail(r), r))
            time.sleep(0.25)
            if i % 50 == 0:
                print(f"  карточек {i}/{len(hits)}")

    orgs = sorted({r["organization"] for r in hits})
    write_xlsx(hits, a.out, columns=COLUMNS, sheet_name="Технологии ВП сталей",
               summary=[("Дата выгрузки", today), ("Свидетельств по ВП сталям", len(hits)),
                        ("Уникальных организаций", len(orgs))],
               sort_key=lambda r: (r["organization"], r["svid_num"]))
    print("→", a.out)


if __name__ == "__main__":
    main()
