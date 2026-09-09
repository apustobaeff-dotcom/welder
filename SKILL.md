---
name: naks-sm-registry
description: Scrape the NAKS registry of attested welding materials (naks.ru/registry/reg/sm/) by any combination of criteria — material type, brand, real classification (AWS/EN/ISO, read from the card's actual text, not just the brand name), organization/producer/representative, diameter, ТУ/ГОСТ, welding method, technical device group, attestation type, a specific attestation center, status (active/cancelled/expired), etc. — and export matching certificates to Excel. Use when the user asks to parse, scrape, look up, cross-check, or export data from the NAKS сварочные материалы registry.
---

# NAKS welding-materials registry (reg/sm) scraper

This skill packages a validated, bug-fixed engine for querying
`https://naks.ru/registry/reg/sm/` programmatically instead of clicking
through the web UI. It was generalized from a task that filtered for one
specific wire classification (ER70S-6 / ER70S-G); **the engine itself is
generic** — it does not hardcode any classification, brand, or material
type. What changes per request is the filter you build and the predicate
you apply to each parsed card.

Files in this skill directory:
- `naks_sm_lib.py` — the engine: request handling, filter-building,
  list-page + detail-card parsing, AC-sharding, reference ID tables.
  **Read the module docstring before writing anything** — it documents
  six real gotchas that silently corrupt results if ignored (500-record
  cap, a session-state bug in the site's pagination, classification not
  being reliably shown in the list view, cancelled-but-not-expired
  certificates, two different detail-card layouts, windows-1251 encoding).
- `xlsx_helper.py` — generic `write_xlsx()` for turning parsed records
  into a formatted, filterable, hyperlinked spreadsheet.
- `example_task.py` — a full worked example (the ER70S-6/G task this was
  extracted from) showing the intended usage pattern end to end. Copy and
  adapt it; don't run it verbatim for a different request.

## How to use this skill for a new request

1. **Read `naks_sm_lib.py`'s docstring and `example_task.py` in full**
   before writing code. The gotchas are not optional context — every one
   of them was a real bug found by running this against the live site.

2. **Translate the user's criteria into `build_filter_params(...)`
   kwargs.** Available site-level filters (pushed to naks.ru itself, so
   they narrow what gets fetched at all):
   - `shifr_sm` — material type. Keys: `Гг` fuel gas, `Гз` shielding gas,
     `Пп`/`Пм` powder wire, `Пр` rod, `Пс` solid wire, `Тм`, `Ф` flux,
     `Эн` build-up electrode, `Эп` coated electrode (see `SHIFR_SM` dict;
     accepts a single key, a list, or a raw id if the user names one not
     in the table).
   - `vid_attestacii` — attestation type, keys of `TYPE_ATT` (`Вн`, `Дп`,
     `Пв`, `Пр`).
   - `svarka` — welding/build-up method(s), keys of `SVARKA` (61 codes,
     e.g. `РАД`, `МАДП`, `АПГ`...).
   - `tech` — technical device group(s), keys of `TECH` (e.g. `НГДО`,
     `КО`, `ОХНВП`...).
   - `organization` — substring match on Организация-заявитель.
   - `marka_sm` — substring match on the brand name field (**not**
     reliable for classification — see gotcha #3; fine for "find
     certificates whose brand name contains X").
   - `tu_gost` — substring match on ТУ/ГОСТ text.
   - `diametr` — diameter, as written on the site (e.g. `"1,2"`).
   - `num_sv` — certificate number, exact or substring.
   - `date_active_from` / `date_active_to` — "dd.mm.yyyy" validity-date
     range; use `date_active_from=<today>` to mean "still valid as of
     today" (but see gotcha #4 — a cancelled certificate can still pass
     this).
   - `num_acsm` — a single raw AC id; normally you don't set this
     directly, `collect_rows()` handles sharding (below).
   - `transneft=True` — the "С учетом требований ПАО Транснефть" flag.

   If the user's criterion isn't a site-level filter at all (e.g. "only
   certificates whose notes mention a specific standard", "only where the
   representative is company X", "diameter between 1.0 and 2.0mm" as a
   numeric range rather than exact text) — filter narrowly by whatever
   site-level params DO apply, then apply the rest as a **Python
   predicate on the parsed record** after `parse_detail()` (see step 4).
   Never try to force something the site can't filter into
   `build_filter_params`.

3. **Fetch with `collect_rows(base_params, log=...)`.** This handles the
   500-record cap by automatically sharding across all ~65 attestation
   centers when the unsharded query would hit/exceed it, verifies each
   shard's collected row count against the site's own reported total,
   and retries pages that come back short. Pass `ac_ids=[...]` (using
   `AC_MAP` numbers, e.g. `AC_MAP[62]`) only if the user explicitly
   restricted the search to specific attestation centers.

   If the user wants "active only" and that should exclude cancelled
   certificates (usually the correct reading of "действующие"), filter
   `row["cancelled"]` after collection — the date filter alone doesn't
   catch cancellations.

4. **For any criterion that depends on the certificate's real content**
   (classification, specific manufacturer note, standard actually
   referenced, role of a specific organization, etc.), fetch and parse
   each candidate: `naks.fetch_detail(row["id_param"])` →
   `naks.parse_detail(html, row)`. Apply your predicate against the
   returned dict — commonly `rec["full_text"]` (brand + ТУ/ГОСТ + notes,
   concatenated) for a classification/keyword regex, or
   `rec["proizvoditel"]`/`rec["predstavitel"]`/`rec["zayavitel"]`/
   `rec["postavshik"]`/`rec["potrebitel"]` for an organization-role
   question. `parse_detail` never returns `None`; it's always the
   caller's job to decide whether a record matches.

   This step is one HTTP request per candidate certificate — for a few
   hundred to ~1500 candidates, run it as a background task (PowerShell/
   Bash `run_in_background`) rather than foreground, with a small
   `time.sleep()` between requests (0.15–0.3s) to stay polite. Log
   progress every 50 records so you can report status without spamming
   output.

5. **Write results with `write_xlsx()`** from `xlsx_helper.py`. Build a
   `columns` list matching exactly what the user asked for (see
   `DEFAULT_COLUMNS` for the shape and lambda pattern) — don't just dump
   every field the library happens to extract. Add
   `rec["_verify_url"] = naks.verification_url(rec["svid_num"])` before
   writing if you want a working "check this yourself" link column (it
   round-trips through the site's own № свидетельства filter, confirmed
   to resolve to exactly the right record).

6. **Sanity-check before delivering:**
   - No duplicate `svid_num` in the output.
   - Compare your final unique-row count against the sum of "ЗАПИСЕЙ:"
     reported per AC shard during collection (they must match exactly —
     see gotcha #2; a silent shortfall here previously cost 20%+ of the
     real result set and was only caught by this check).
   - Spot-check 3–4 verification links actually resolve to 1 found record.
   - If organization-role columns are requested, confirm they're
     populated from the actual card wording (spot-check a handful against
     the raw detail HTML) rather than left blank because a template
     variant (see gotcha #5) wasn't handled.

## Known limitation / scope

This has only been built and validated against `/registry/reg/sm/`
(сварочные материалы — welding consumables). NAKS runs other registries
(e.g. welders, equipment, procedures) that may sit on the same Bitrix
engine with a very similar filter-form/detail-card pattern, but the field
names, checkbox values, and card layout have **not** been verified for
those. If the user asks about a different NAKS registry, fetch and
inspect that registry's own filter form and detail-card markup first
(same method used to build `SHIFR_SM`/`SVARKA`/`TECH` here — read the
`<input name=...>` values and their adjacent label text) before assuming
this library's constants apply; adapt or extend `naks_sm_lib.py` rather
than guessing.
