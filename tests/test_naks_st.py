# -*- coding: utf-8 -*-
"""Офлайн-тесты naks_st_lib: разбор реальной страницы списка (АЦСТ-1,
снята 09.10.2026) и обход лимита 500 через бисекцию дат на фейковом сайте."""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import naks_st_lib as st  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "naks_st_list_acst1.html")


def test_parse_real_list_page():
    found, rows = st.parse_list_page(open(FIXTURE, encoding="utf-8").read())
    assert found == 500 and len(rows) == 25
    r = rows[0]
    assert r["svid_num"] == "АЦСТ-1-05707" and r["vid_att"] == "Пв"
    assert r["sposoby"] == "РД" and r["gruppy"] == "НГДО" and r["srok"] == "08.09.2029"
    assert r["groups"] == [1] and not r["cancelled"]
    canc = [x for x in rows if x["cancelled"]]
    assert {x["svid_num"] for x in canc} == {"АЦСТ-1-05813", "АЦСТ-1-05785"}
    assert all(x["cancel_date"] == "23.06.2026" for x in canc)
    assert len(st.AC_MAP) == 163 and st.AC_MAP[1] == 414566


def test_groups_and_high_strength():
    g = st.base_metal_groups
    assert g("1 (Ст3сп, 09Г2С и другие по ПТД), 9 (12Х18Н10Т)") == [1, 9]
    assert g("Группа 1 - 08, 10 по ПТД. + Группа 3 - 14ХГНДЦ по ПТД.") == [1, 3]
    assert g("07Х16Н6") == []
    assert st.is_high_strength({"groups": [1, 3]})
    assert not st.is_high_strength({"groups": [1, 2], "osn_materialy": "14Х2ГМР"})
    assert st.is_high_strength({"groups": [2], "osn_materialy": "S690QL"},
                               grade_matcher=lambda t: "S690" in t)


def test_groups_real_formats():
    """Формы «Основных материалов», встреченные в живом реестре 09.10.2026."""
    cases = {
        "Группа 1, марки согласно ПТД": [1],
        "Группа 30 (ПЭ 80, ПЭ 100)": [30],
        "1 (Ст3кп, Ст3пс, 10, 15, 20, 15К, 09Г2С и др), 9 (12Х18Н10Т)": [1, 9],
        "1- 09Г2С и другие +3-30ХГСА и другие": [1, 3],
        "1-14ХГНДЦ, 2-14ХГНДЦ": [1, 2],
        "1-09Г2С, 15ХСНД, 2-10ХСНД, 1-14ХГНДЦ (345), 2-14ХГНДЦ (390)": [1, 2],
        "3(М03), 1+3 (М01 + М03) - 09Г2С + С590, S690, W700": [1, 3],
        "1 – 20, 09Г2С, 20ГЛ, 2 – 10ХСНД, 10Г2ФБЮ, 1+2 – 20, 09Г2С": [1, 2],
        "Стальные трубы, СДТ, ТПА группы 3(М03) класса прочности К65": [3],
        "07Х16Н6": [],
    }
    for text, exp in cases.items():
        assert st.base_metal_groups(text) == exp, (text, st.base_metal_groups(text))


def test_sm_marks_real_formats():
    m = st.sm_marks
    assert m("… слоев шва электроды LB-52U и другие аттестованные … ПТД.") == ["LB-52U"]
    assert m("Проволока: AKEM4. Флюс: OK Flux 10.62P") == ["AKEM4", "OK Flux 10.62P"]
    assert m("ULTRA 700") == ["ULTRA 700"]
    assert m("… покрытия марки Nittetsu L-74S и другие аналоги в соответствии с ПТД") == ["Nittetsu L-74S"]
    assert m("типа Э50А марок LB-52U, ОК 53.70 и другие аналоги согласно ПТД") == ["LB-52U", "OK 53.70"]
    assert m("электроды УОНИ 13/55") == ["УОНИ-13/55"] and m("OK 53.70") == ["OK 53.70"]
    assert m("Сварочная проволока: Св-08Г2С-О и другие") == ["Св-08Г2С-О"]


def _fx(name):
    return open(os.path.join(ROOT, "tests", "fixtures", name), encoding="utf-8").read()


def test_parse_real_detail_cards():
    r = st.parse_detail(_fx("naks_st_detail_acst1_05705.html"), {"osn_materialy": "1 (До К54 вкл.)"})
    assert r["detail_available"] and r["tech_shifr"] == "ТИ-РД-НГДО-1,3-2021"
    assert r["tech_date"] == "11.01.2021" and r["sm_marks"] == ["LB-52U"]
    assert r["params"]["Диапазон диаметров, мм"] == "от 57 до 150 вкл. / св. 150 до 426 вкл."
    assert r["params"]["Наличие подогрева"] == "с подогревом"
    hs = st.parse_detail(_fx("naks_st_detail_acst69_03538_s690.html"), {})
    assert "S690" in hs["osn_materialy_card"] and hs["sm_marks"] == ["AKEM4", "OK Flux 10.62P"]
    na = st.parse_detail(_fx("naks_st_detail_unavailable.html"), {"osn_materialy": "x"})
    assert na["detail_available"] is False and na["params"] == {}


def test_verification_url_is_cp1251():
    assert "%C0%D6%D1%D2-1-05705" in st.verification_url("АЦСТ-1-05705")


def test_bisect_beats_cap(monkeypatch=None):
    """Фейковый реестр: 1300 записей в одном АЦ, разнесённых по датам.
    collect_rows должен собрать все, хотя любой запрос шире ~500 капится."""
    import datetime as dt
    base = dt.date(2027, 1, 1)
    recs = [(f"АЦСТ-1-{i:05d}", (base + dt.timedelta(days=i % 900)).strftime("%d.%m.%Y"))
            for i in range(1300)]

    def ordv(d):
        dd, mm, yy = map(int, d.split("."))
        return dt.date(yy, mm, dd)

    calls = {"ac": 0}

    def fake_get(url, params=None, tries=4):
        if "arrFilter_pf[num_acst][0]" in params:
            calls["ac"] += 1
        lo = ordv(params.get("arrFilter_DATE_ACTIVE_TO_1", "01.01.2000"))
        hi = ordv(params.get("arrFilter_DATE_ACTIVE_TO_2", "31.12.2099"))
        sel = [r for r in recs if lo <= ordv(r[1]) <= hi]
        if "arrFilter_pf[num_acst][0]" in params and params["arrFilter_pf[num_acst][0]"] != str(st.AC_MAP[1]):
            sel = []
        total = min(len(sel), 500)
        page = int(params.get("PAGEN_1", 1))
        chunk = sel[:500][(page - 1) * 25: page * 25]
        trs = "".join(
            f"<tr><td>Org</td><td>Пв</td><td>РД</td><td>3 (S690QL)</td><td>ПТО</td>"
            f"<td>{n}</td><td>{d}</td><td>АЦСТ - 1</td><td><button>открыть</button></td></tr>"
            for n, d in chunk)
        head = f"<p><strong>НАЙДЕНО ЗАПИСЕЙ: {total}</strong></p>" if total else "ЗАПИСЕЙ НЕ НАЙДЕНО"
        return f"<html>{head}<table class='tabl'>{trs}</table></html>"

    orig = st.get
    st.get = fake_get
    try:
        rows = st.collect_rows(st.build_filter_params(), sleep=0)
    finally:
        st.get = orig
    assert len(rows) == 1300
    assert all(r["groups"] == [3] for r in rows.values())
    # бисекция по датам без перебора 163 АЦ (дубль старого collect_rows
    # однажды тихо вернул медленный путь — 30 минут без результата)
    assert calls["ac"] == 0, calls


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
