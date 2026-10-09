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

    def fake_get(url, params=None, tries=4):
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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
