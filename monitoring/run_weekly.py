# -*- coding: utf-8 -*-
"""Еженедельный прогон: сбор → классификация → дедуп → отчёт.

    python -m monitoring.run_weekly                    # всё, что достижимо
    python -m monitoring.run_weekly --extra found.json # + записи, найденные
                                                       #   веб-поиском (Firecrawl)
    python -m monitoring.run_weekly --save-state       # зафиксировать «уже видели»

Выход: monitoring/out/<YYYY-Www>/{items.json, report.html, health.json}
Состояние: monitoring/state/seen.json (коммитится в репозиторий, иначе
следующий прогон в новом контейнере не узнает, что уже было в отчётах).
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import classify  # noqa: E402
import collectors  # noqa: E402
import report  # noqa: E402
import sources  # noqa: E402

STATE = os.path.join(HERE, "state", "seen.json")


def load_state():
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    return {"seen": {}, "naks_svid": []}


def key_of(it):
    base = it.get("url") or ""
    if not base or "t.me/s/" in base:
        base += (it.get("text") or "")[:300]
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--extra", help="JSON-список записей из веб-поиска")
    ap.add_argument("--only", nargs="*", help="telegram hh rss youtube naks naks_st")
    ap.add_argument("--notes", help="HTML-файл с резюме «Главное за неделю»")
    ap.add_argument("--save-state", action="store_true")
    args = ap.parse_args()

    today = dt.date.today()
    since = today - dt.timedelta(days=args.days)
    week = today.strftime("%G-W%V")
    outdir = os.path.join(HERE, "out", week)
    os.makedirs(outdir, exist_ok=True)
    state = load_state()
    want = set(args.only) if args.only is not None else {"telegram", "hh", "rss", "youtube", "naks", "naks_st"}

    raw, health = [], []

    def run(name, fn):
        try:
            got = fn()
            raw.extend(got)
            health.append({"source": name, "status": "ok", "count": len(got)})
        except Exception as e:  # noqa: BLE001 — сбой источника не должен ронять прогон
            health.append({"source": name, "status": "error", "count": 0,
                           "error": f"{type(e).__name__}: {str(e)[:160]}"})

    if "telegram" in want:
        for ch in sources.TELEGRAM_CHANNELS:
            run(f"telegram:{ch}", lambda ch=ch: collectors.telegram_channel(ch, since))
    if "hh" in want:
        for area in sources.HH_AREAS:
            for q in sources.HH_QUERIES:
                run(f"hh.ru[{sources.HH_AREAS[area]}] {q}",
                    lambda q=q, area=area: collectors.hh_vacancies(q, area, since))
    if "rss" in want:
        for name, url in sources.RSS_FEEDS.items():
            run(f"rss:{name}", lambda url=url, name=name: collectors.rss(url, since, name))
    if "youtube" in want:
        for cid, name in sources.YOUTUBE_CHANNELS.items():
            run(f"youtube:{name}", lambda cid=cid, name=name: collectors.rss(
                f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}", since, f"youtube:{name}"))
    if "naks" in want:
        new_svid = {}

        def naks_run():
            items, current = collectors.naks_delta(set(state.get("naks_svid", [])),
                                                   sources.NAKS_SHIFR, log=lambda m: None)
            new_svid["all"] = sorted(current)
            return items
        run("НАКС реестр СМ (дельта)", naks_run)
        if new_svid.get("all"):
            state["naks_svid"] = new_svid["all"]

    if "naks_st" in want:
        st_all = {}

        def hs(text):
            c = classify.classify(text)
            return bool(c and (c["max_class"] or 0) >= 420)

        def naks_st_run():
            items, current = collectors.naks_st_delta(set(state.get("naks_st_svid", [])),
                                                      hs, log=lambda m: None)
            st_all["all"] = sorted(current)
            return items
        run("НАКС реестр технологий (дельта, ВП стали)", naks_st_run)
        if st_all.get("all"):
            state["naks_st_svid"] = st_all["all"]

    if args.extra:
        with open(args.extra, encoding="utf-8") as f:
            extra = json.load(f)
        raw.extend(extra)
        health.append({"source": "веб-поиск (Firecrawl)", "status": "ok", "count": len(extra)})

    items, seen_now = [], set()
    for it in raw:
        k = key_of(it)
        if k in state["seen"] or k in seen_now:
            continue
        # НАКС-записи уже отобраны как новые; классифицируем по полному тексту карточки
        c = classify.classify(f"{it.get('title', '')}\n{it.get('text', '')}")
        if not c:
            continue
        if it.get("source_type") == "naks_st":
            c["priority"] = "A"   # предприятие уже аттестовало сварку ВП стали — сильнейший лид
        seen_now.add(k)
        it["cls"], it["key"] = c, k
        items.append(it)
    rank = {"A": 2, "B": 1, "C": 0}
    items.sort(key=lambda i: (rank[i["cls"]["priority"]], i["cls"]["score"], i.get("date") or ""), reverse=True)

    with open(os.path.join(outdir, "items.json"), "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    with open(os.path.join(outdir, "health.json"), "w", encoding="utf-8") as f:
        json.dump(health, f, ensure_ascii=False, indent=1)
    period = f"{since.strftime('%d.%m.%Y')} — {today.strftime('%d.%m.%Y')}"
    with open(os.path.join(outdir, "report.html"), "w", encoding="utf-8") as f:
        notes = open(args.notes, encoding="utf-8").read() if args.notes else None
        f.write(report.build(items, health, period, notes=notes))

    if args.save_state:
        for k in seen_now:
            state["seen"][k] = today.isoformat()
        cutoff = (today - dt.timedelta(days=180)).isoformat()   # не раздувать файл
        state["seen"] = {k: v for k, v in state["seen"].items() if v >= cutoff}
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)

    ok = sum(1 for h in health if h["status"] == "ok")
    print(f"week={week} raw={len(raw)} relevant={len(items)} "
          f"A={sum(i['cls']['priority'] == 'A' for i in items)} "
          f"B={sum(i['cls']['priority'] == 'B' for i in items)} "
          f"sources_ok={ok}/{len(health)} out={outdir}")


if __name__ == "__main__":
    main()
