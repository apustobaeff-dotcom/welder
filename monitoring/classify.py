# -*- coding: utf-8 -*-
"""Классификация и скоринг текстового сигнала по словарю taxonomy.py.

Классификатор намеренно детерминированный: он отбирает кандидатов и даёт
черновой балл. Финальную оценку значимости делает человек или LLM в
еженедельном прогоне (см. RUNBOOK.md), но только по отобранным здесь записям
и всегда со ссылкой на первоисточник.
"""
import re

try:
    from . import taxonomy as T
except ImportError:  # запуск как скрипта
    import taxonomy as T

_STEEL = [(re.compile(p), cls, note) for p, cls, note in T.STEEL_PATTERNS]
_INDUSTRIES = {k: re.compile(v, re.IGNORECASE) for k, v in T.INDUSTRIES.items()}
_SIGNALS = {k: (w, re.compile(v, re.IGNORECASE)) for k, (w, v) in T.SIGNAL_TYPES.items()}

CLASS_BONUS = {420: 0, 460: 1, 490: 1, 550: 2, 620: 2, 690: 3, 790: 3, 890: 3}


def _steels(text):
    found = []
    for rx, cls, note in _STEEL:
        for m in rx.finditer(text):
            c = cls
            if c is None:  # класс в самой марке (S690, Q890, С550)
                c = T.step_for(int(m.group(1)))
                if c is None:
                    continue
            found.append((m.group(0).strip(), c, note))
    for m in T.YIELD_NUMBER_RE.finditer(text):
        c = T.step_for(int(m.group(1)))
        if c:
            found.append((m.group(0).strip(), c, "предел текучести в тексте"))
    return found


def _consumables(text):
    found = []
    for rx, table, label in (
        (T.AWS_SOLID_RE, T.AWS_TO_STEEL, "AWS A5.28 проволока"),
        (T.AWS_STICK_RE, T.AWS_TO_STEEL, "AWS A5.5 электрод"),
        (T.AWS_FCAW_RE, T.AWS_TO_STEEL, "AWS A5.29 порошковая"),
        (T.GOST_ELECTRODE_RE, T.GOST_E_TO_STEEL, "ГОСТ 9467 тип"),
        (T.UONI_RE, {"65": 460, "85": 690}, "УОНИ"),
    ):
        for m in rx.finditer(text):
            found.append((m.group(0).strip(), table[m.group(1)], label))
    for m in T.ISO_CLASS_RE.finditer(text):
        found.append((m.group(0).strip(), T.ISO_TO_STEEL[m.group(2)], "ISO 16834/18276/18275"))
    for m in T.GOST_WIRE_HS_RE.finditer(text):
        found.append((m.group(0).strip(), 550, "ГОСТ 2246 легированная"))
    for m in T.BRAND_SM_RE.finditer(text):
        found.append((m.group(0).strip(), 690, "бренд СМ"))
    return found


def classify(text):
    """Вернуть dict с тегами и баллом, либо None, если текст нерелевантен."""
    if not text:
        return None
    if T.STOP_RE.search(text) and not _consumables(text):
        return None

    steels = _steels(text)
    sms = _consumables(text)
    generic = bool(T.GENERIC_HS_RE.search(text))
    if not (steels or sms or generic):
        return None
    if not sms and not generic and not T.CONTEXT_RE.search(text):
        return None

    industries = sorted(k for k, rx in _INDUSTRIES.items() if rx.search(text))
    signals = sorted(((w, k) for k, (w, rx) in _SIGNALS.items() if rx.search(text)), reverse=True)
    max_class = max([c for _, c, _ in steels + sms] or [0])

    score = signals[0][0] if signals else 1
    score += CLASS_BONUS.get(max_class, 0)
    score += 2 if sms else 0
    score += 1 if industries else 0
    score += 1 if T.SM_BRANDS.search(text) else 0

    def uniq(items):
        seen, out = set(), []
        for name, cls, note in items:
            key = re.sub(r"\s+", "", name.upper())
            if key not in seen:
                seen.add(key)
                out.append({"name": name, "class": cls, "note": note})
        return out

    retail = bool(T.RETAIL_RE.search(text))
    priority = "A" if score >= 8 else "B" if score >= 5 else "C"
    if retail:
        priority = "C"

    return {
        "steels": uniq(steels),
        "consumables": uniq(sms),
        "generic_hs": generic,
        "max_class": max_class or None,
        "industries": industries,
        "signal_types": [k for _, k in signals],
        "sm_brands": sorted({m.group(0) for m in T.SM_BRANDS.finditer(text)}),
        "score": score,
        "retail": retail,
        "priority": priority,
    }
