# -*- coding: utf-8 -*-
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from classify import classify

CASES = [
    # (текст, ожидаем релевантность, мин. класс или None, ожидаемый тип сигнала или None)
    ("Извещение о закупке: проволока сварочная ER110S-G д.1,2 мм, 2 т, НМЦК 3,1 млн", True, 690, "тендер"),
    ("Требуется сварщик MAG, опыт сварки стали S700MC, Hardox 450, стрелы кранов", True, 690, "вакансия"),
    ("ММК освоил выпуск нового высокопрочного проката с пределом текучести 700 МПа", True, 690, "запуск/освоение"),
    ("Электроды УОНИ-13/85 тип Э85 для сварки сталей 14Х2ГМР", True, 690, None),
    ("Свидетельство НАКС: проволока G 69 4 M21 Mn3Ni1CrMo, ГОСТ Р ИСО 16834", True, 690, "аттестация/допуск"),
    ("Магистральный газопровод: трубы К65 X80 Ду1420", True, 550, None),
    ("Мостовой пролёт из стали 15ХСНД и С345", False, None, None),
    ("Высокопрочный бетон B60 для фундамента", False, None, None),
    ("Высокопрочные болты М24 класс 10.9", False, None, None),
    ("Сварка стали 09Г2С проволокой ER70S-6", False, None, None),
    ("Продам Samsung Galaxy S500 Pro", False, None, None),
    ("Трещины в сварном шве стрелы крана из S960QL после 2 лет эксплуатации", True, 890, "отказ/проблема"),
    ("Электрод E11018-M и проволока Св-08ХН2ГМЮ для корпусов", True, 690, None),
]

def test_cases():
    bad = []
    for text, rel, cls, sig in CASES:
        c = classify(text)
        if bool(c) != rel:
            bad.append((text, "relevance", c)); continue
        if not c: continue
        if cls and (c["max_class"] or 0) < cls:
            bad.append((text, f"class {c['max_class']} < {cls}", c))
        if sig and sig not in c["signal_types"]:
            bad.append((text, f"signal {c['signal_types']}", None))
    assert not bad, "\n".join(map(str, bad))

if __name__ == "__main__":
    for text, *_ in CASES:
        c = classify(text)
        print(("✓ " if c else "· ") + text[:70], "→", c and (c["priority"], c["score"], c["max_class"], c["signal_types"], [s["name"] for s in c["steels"]+c["consumables"]]))
    test_cases(); print("OK")
