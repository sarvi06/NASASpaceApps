"""Plain-English explanations: for each rotation, why it was suggested, the evidence behind it,
its benefits, the information gaps and the risks a farmer or local expert should check.
Also the full text report printed by demo.py.
"""

from __future__ import annotations

from .economics import Economy
from .rotations import CARD, Rotation, calendar_grid
from .sequence import AFTER_LEGUME, SAME_FAMILY, follow_score
from .suitability import MONTHS

DISCLAIMER = ("This tool highlights patterns and possibilities from NASA and USDA data. It does not "
              "replace your own judgement or local agricultural expertise: check any change with "
              "an agronomist or extension service before acting on it.")

WIDELY_GROWN = 0.8     # market score at or above this is worth naming as a benefit
ACRES_PER_HA = 2.471   # the app covers the USA only, so money is given per acre first
RARELY_GROWN = 0.34    # market score below this (about 0.1% of the country's cropland) is a gap
RELIABLE_SHARE = 0.8   # suiting at least this share of the years on record counts as a benefit
FIT_DROP_WORTH_NAMING = 0.02   # a smaller fall in fit in the hotter, drier case = it holds up
MAX_WEAK_YEARS = 3     # bad years named in the reliability sentence

GLOSSARY = {
    "suitability": "0-1 score for how well the field's climate and soil match a crop's needs "
                   "(FAO EcoCrop); 1 = ideal, 0 = can't grow. The weakest factor sets the score.",
    "optimal vs absolute range": "EcoCrop gives each crop an optimal range (grows best) and an "
                                 "absolute range (survives, with lower yield).",
    "cover crop": "A crop grown to protect and feed the soil between harvest crops, then ended "
                  "(rolled, grazed, mowed or tilled) before the next crop is planted.",
    "nitrogen fixation": "Legumes (beans, peas, clovers, vetch, alfalfa) host bacteria that take "
                         "nitrogen from the air, leaving some in the soil for the next crop.",
    "frost-free days": "Days between the last spring frost and the first autumn frost "
                       "(NASA POWER daily minimum temperature at or below 0 degC).",
    "root-zone wetness": "How wet the top 1 m of soil is, 0 = dry to 1 = saturated "
                         "(NASA POWER model; NASA SMAP satellite if enabled).",
    "dormancy / winter-kill": "Overwintering crops (winter wheat, rye, vetch) stop growing in cold "
                              "months; if nights are colder than they tolerate, they can die.",
    "income per hectare": "Average yield x price paid to farmers in the field's country (FAOSTAT), "
                          "in US dollars. It is income before costs unless you entered costs. "
                          "Your own price or yield replaces FAOSTAT's. It is scored against "
                          "the country's typical hectare: 0.5 = typical, 1 = ten times typical.",
    "local market": "How widely a crop is grown in the field's country (its share of harvested "
                    "area, FAOSTAT). Widely grown crops have buyers, equipment and know-how; a "
                    "crop almost nobody grows usually has high costs or few buyers.",
    "bare months": "Months with nothing growing, when soil is most exposed to wind and water "
                   "erosion and nutrients can wash out.",
}


def _per_area(usd_per_ha: float) -> str:
    """Money per acre first (US farmers think in acres), with the hectare figure in brackets."""
    return f"${usd_per_ha / ACRES_PER_HA:,.0f} per acre (${usd_per_ha:,.0f} per hectare)"


def _names(slots) -> str:
    names = list(dict.fromkeys(s.crop.name for s in slots))
    return ", ".join(names[:-1]) + (" and " if len(names) > 1 else "") + names[-1] if names else ""


def _verb(slots, singular: str, plural: str) -> str:
    return singular if len({s.crop.name for s in slots}) == 1 else plural


def _covered_per_year(rot: Rotation) -> float:
    return len(rot.covered_months()) / rot.years


def _held_back(crop: str, limited_by: str) -> str:
    return f"{crop} could not grow" if limited_by == "cannot grow" else f"{crop} limited by {limited_by}"


def _reliability(res: dict) -> tuple[str, bool] | None:
    """(sentence, is a benefit) for how many years on record the rotation would have suited."""
    n, ok, bad = res.get("years_checked", 0), res.get("years_ok", 0), res.get("bad_years", [])
    if not n:
        return None
    if ok == n:
        span = "the one full year on record" if n == 1 else f"every one of the last {n} years on record"
        return (f"Would have suited the weather in {span} (NASA POWER), not just the average "
                f"year.", True)
    weak = "; ".join(f"{b['year']}, {_held_back(b['crop'], b['limited_by'])}"
                     for b in bad[:MAX_WEAK_YEARS])
    if len(bad) > MAX_WEAK_YEARS:
        weak += f"; and {len(bad) - MAX_WEAK_YEARS} more"
    if ok / n >= RELIABLE_SHARE:
        return f"Would have suited the weather in {ok} of the last {n} years on record (weak: {weak}).", True
    return (f"Would have suited the weather in only {ok} of the last {n} years on record: in the "
            f"others a harvest crop would have done poorly (weak: {weak}). Expect some bad years "
            f"and plan for them.", False)


def _hotter_drier(res: dict) -> tuple[str, bool] | None:
    """(sentence, is a benefit) for the rotation re-scored in a hotter, drier climate."""
    sc = res.get("scenario")
    if not sc:
        return None
    now, then = sc["fit_now"], sc["fit"]
    if now - then < FIT_DROP_WORTH_NAMING:
        change = (f"stays at about {now:.0%}" if f"{now:.0%}" == f"{then:.0%}"
                  else f"would be {then:.0%} against {now:.0%} now")
        return f"Holds up in a hotter, drier climate ({sc['name']}): the climate and soil fit {change}.", True
    hit = sc.get("weakest")
    if hit:
        why = "it could not grow" if hit["limited_by"] == "cannot grow" else f"limited by {hit['limited_by']}"
        hardest = f"; {hit['crop']} is hit hardest ({why})"
    else:                        # no harvest crop loses, so the drop is in the cover crops
        hardest = "; the cover crops suffer, not the harvest crops"
    return (f"In a hotter, drier climate ({sc['name']}), the climate and soil fit drops from "
            f"{now:.0%} to {then:.0%}{hardest}.", False)


def explain(rot: Rotation, field, baseline: Rotation | None, weights: dict,
            priority_name: str, familiar: set | None = None, used_smap: bool = False,
            economy: Economy | None = None, budget: dict | None = None) -> dict:
    """why / evidence / benefits / gaps / risks for one rotation (lists of plain sentences)."""
    economy = economy or Economy()
    card, insights = rot.card, field.insights
    base_card = baseline.card if baseline else {}

    # ---- why ----
    contributions = sorted(CARD, key=lambda k: -weights[k] * card[k])
    strengths = [f"{CARD[k]} {card[k]:.2f}" + (f" (current {base_card[k]:.2f})" if base_card else "")
                 for k in contributions[:3]]
    if rot.is_baseline:
        why = (f"This is what the field grows now, scored the same way as the options. Overall "
               f"{rot.overall:.2f} for your '{priority_name}' priorities. Strongest points: "
               f"{'; '.join(strengths)}.")
    else:
        why = (f"Picked as: {rot.strategy}. Overall score {rot.overall:.2f} for your "
               f"'{priority_name}' priorities"
               + (f", against {baseline.overall:.2f} for your current rotation" if baseline else "")
               + f". Strongest points: {'; '.join(strengths)}.")
        if rot.start_note:
            why += " " + rot.start_note
    hand_overs = [follow_score(a.crop, b.crop) for a, b in rot.hand_overs()]

    # ---- evidence ----
    evidence = []
    for a, s in rot.placed:
        evidence.append(f"{s.crop.name} ({'cover crop' if s.use == 'cover' else 'harvest'}, "
                        f"{MONTHS[a % 12]}-{MONTHS[(a + s.months - 1) % 12]}, year {a // 12 % rot.years + 1}): "
                        f"suitability {s.score:.2f}, limited by {s.limiter}.")
        evidence += [f"    {line}" for line in s.evidence]
        if s.use == "harvest" and economy.get(s.crop):
            evidence.append(f"    Money: {economy.get(s.crop).describe()}")

    # ---- benefits ----
    benefits = []
    covered = _covered_per_year(rot)
    if not baseline or covered > _covered_per_year(baseline) + 0.5:
        benefits.append(f"Soil is covered about {covered:.0f} of every 12 months"
                        + (f" (current rotation: {_covered_per_year(baseline):.0f})" if baseline else "")
                        + ", cutting erosion and nutrient loss in bare months.")
    legumes = [s for s in rot.slots if s.crop.legume]
    if legumes:
        benefits.append(f"{_names(legumes)} {_verb(legumes, 'fixes', 'fix')} nitrogen from the air, "
                        f"lowering fertiliser needs for the crop that follows.")
    good_order = list(dict.fromkeys(reason for score, reason in hand_overs if score >= AFTER_LEGUME))
    if good_order:
        benefits.append("Crop order: " + "; ".join(good_order) + ".")
    if rot.covers:
        benefits.append(f"Cover crops ({_names(rot.covers)}) protect the soil between harvests and "
                        f"add organic matter as they break down.")
    priced = [s for s in rot.harvests if economy.get(s.crop)]
    gaps_first = ""
    if priced:
        typical = (f"; the typical hectare in {economy.country or 'this country'} earns about "
                   f"${economy.typical_income:,.0f}" if economy.typical_income else "")
        benefits.append(f"Estimated earnings of about {_per_area(rot.income_usd_ha)} per year "
                        f"from {_names(priced)} (average yields scaled by how well each crop suits "
                        f"the field{typical}; see Money lines above).")
        if rot.trusted_income_usd_ha < 0.9 * rot.income_usd_ha:
            gaps_first = (f"Only about {_per_area(rot.trusted_income_usd_ha)} of the "
                          f"{_per_area(rot.income_usd_ha)} per year is counted in the score: "
                          f"income far above the typical hectare from a crop few farmers here grow "
                          f"usually means high costs or few buyers that FAOSTAT does not show. Enter "
                          f"your own price or cost for a crop to have its income counted in full.")
    if budget:
        yearly = rot.cost_usd_ha * budget["plot_size_ha"]
        verdict = "within" if rot.cost_usd_ha <= budget["max_cost_usd_ha"] else "OVER"
        benefits.append(f"Growing costs of about ${yearly:,.0f} a year for the whole plot "
                        f"({budget['plot_size_ha']:g} ha at {_per_area(rot.cost_usd_ha)}): "
                        f"{verdict} your budget of ${budget['budget_usd']:,.0f}.")
    established = [s for s in priced if economy.market(s.crop) >= WIDELY_GROWN]
    if established:
        benefits.append(f"{_names(established)} {_verb(established, 'is', 'are')} widely grown in "
                        f"{economy.country or 'this country'}, so buyers, equipment and know-how exist.")
    families = len({s.crop.family for s in rot.slots})
    base_families = len({s.crop.family for s in baseline.slots}) if baseline else 0
    if families > base_families:
        benefits.append(f"{families} plant families" + (f" (current: {base_families})" if baseline else "")
                        + " break pest, weed and disease cycles that build up when the same "
                          "crops repeat.")
    if baseline and card["water"] > base_card.get("water", 0) + 0.03:
        benefits.append("Lower overall water demand than the current rotation (EcoCrop rainfall "
                        "needs vs NASA POWER rainfall).")
    # EcoCrop also tags some food crops (e.g. tomato) as forage; only name crops that are
    # grown as a cover crop or are not cash crops, or the sentence reads oddly.
    forage = [s for s in rot.slots if "forage" in s.crop.roles
              and (s.use == "cover" or "cash" not in s.crop.roles)]
    if forage:
        benefits.append(f"{_names(forage)} can also be grazed or cut for forage/hay.")

    # ---- information gaps ----
    gaps = ([gaps_first] if gaps_first else []) + list(dict.fromkeys(g for s in rot.slots for g in s.gaps))
    unfamiliar = [s for s in rot.harvests if familiar and s.crop.sci not in familiar]
    if unfamiliar:
        gaps.append(f"{_names(unfamiliar)} {_verb(unfamiliar, 'has', 'have')} not been grown on this "
                    f"field (CropScape): local buyers, prices, equipment and storage are unknown.")
    unpriced = [s for s in rot.harvests if not economy.get(s.crop)]
    if unpriced and economy.crops:
        gaps.append(f"No price or yield for {_names(unpriced)} (FAOSTAT), so "
                    f"{_verb(unpriced, 'it counts', 'they count')} as no income; enter your own "
                    f"price and yield if you can sell {_verb(unpriced, 'it', 'them')}.")
    if priced:
        gaps.append("Prices and yields are national yearly averages (FAOSTAT), not local ones; "
                    "enter your own price or yield to correct them.")
    estimated = [s for s in priced if "estimate" in economy.get(s.crop).price_source
                 or "world median" in economy.get(s.crop).yield_source]
    if estimated:
        gaps.append(f"The price or yield of {_names(estimated)} is an estimate from world figures, "
                    f"because FAOSTAT has no local one.")
    niche = [s for s in priced if economy.market(s.crop) < RARELY_GROWN]
    if niche:
        gaps.append(f"{_names(niche)} {_verb(niche, 'is', 'are')} rarely or never grown in "
                    f"{economy.country or 'this country'} (FAOSTAT area harvested): check there is "
                    f"a buyer, and the labour and equipment, before planting.")
    no_cost = [s for s in priced if economy.get(s.crop).cost_usd_ha is None]
    if no_cost:
        gaps.append(f"Costs (seed, fertiliser, labour, machinery) are not included for "
                    f"{_names(no_cost)}: FAOSTAT holds none, so high-cost crops such as vegetables "
                    f"earn less than shown. Enter your costs to compare on profit.")
    guessed = [s for s in priced if economy.get(s.crop).cost_source.startswith("estimated")]
    if guessed:
        gaps.append(f"The cost of {_names(guessed)} is assumed to be {economy.cost_share:.0%} of "
                    f"income, the share in the costs you entered, so that every crop is compared "
                    f"on profit. Enter the real cost if it differs.")
    if budget and rot.covers:
        gaps.append(f"The cost of the cover crops ({_names(rot.covers)}) is not known and is not "
                    f"in the budget figure: add seed and labour for them.")
    gaps.append("EcoCrop ranges are for the species as a whole; local varieties can differ.")
    gaps.append("NASA POWER climate is a ~50 km grid average, not a measurement at the field.")
    if not used_smap:
        gaps.append("Soil moisture comes from the NASA POWER model; NASA SMAP satellite data "
                    "was not used for this run.")

    # ---- risks ----
    risks = list(dict.fromkeys(f for s in rot.slots for f in s.flags))
    risks += list(dict.fromkeys(f"Crop order: {reason}." for score, reason in hand_overs
                                if score <= SAME_FAMILY))
    trend = insights.get("rain_trend_mm_per_decade")
    if trend is not None and trend < 0:
        risks.append(f"Rainfall trended down by about {-trend:.0f} mm per decade over the period "
                     f"(NASA POWER; yearly totals ranged {insights.get('driest_year_rain_mm', 0):.0f}-"
                     f"{insights.get('wettest_year_rain_mm', 0):.0f} mm). Short records are noisy, but "
                     f"thirsty crops would struggle if dry years continue.")
    if (insights.get("heat_days_per_year") or 0) >= 5:
        risks.append(f"About {insights['heat_days_per_year']:.0f} heat-stress days (>32 degC) a year: "
                     f"check flowering dates of summer crops.")
    if (insights.get("heavy_rain_days_per_year") or 0) >= 3:
        risks.append(f"About {insights['heavy_rain_days_per_year']:.0f} heavy-rain days (>25 mm) a "
                     f"year: bare months are an erosion risk.")
    for i, (a, s) in enumerate(rot.placed):
        if s.use == "cover":
            nxt = rot.placed[(i + 1) % len(rot.placed)][1]
            risks.append(f"{s.crop.name} cover must be ended in good time before planting "
                         f"{nxt.crop.name}; in a dry spring it can use soil water the next crop needs.")
    if rot.resilience:
        for found in (_reliability(rot.resilience), _hotter_drier(rot.resilience)):
            if found:
                sentence, is_benefit = found
                (benefits if is_benefit else risks).append(sentence)
    risks.append("Timings are monthly; actual planting and harvest dates depend on the season, "
                 "varieties and machinery - plan them locally.")

    return {"strategy": rot.strategy, "why": why, "evidence": evidence, "benefits": benefits,
            "information_gaps": gaps, "risks": risks}


# --------------------------------------------------------------------------------------
# Full text report (used by demo.py)
# --------------------------------------------------------------------------------------
def _field_summary(field, country: dict | None = None, place: str | None = None) -> list[str]:
    i = field.insights
    lines = ["Location: " + (f"near {place}, " if place else "")
             + f"latitude {field.lat}, longitude {field.lon}"
             + (f", {country['name']}" if country else "")
             + (f"  (elevation {field.elevation_m:.0f} m)" if field.elevation_m is not None else ""),
             f"Data period: {field.start_date} to {field.end_date} ({i.get('years_of_data')} years)", ""]
    from .suitability import Climate
    lines += ["Monthly climate (NASA POWER): Tmean = average temp, Coldest = typical coldest night "
              "of the month (not the average night), Rain = typical monthly total (mm)",
              Climate.from_monthly(field.climate_monthly).table(), ""]
    facts = [
        ("Annual rain", f"{i.get('annual_rain_mm'):.0f} mm"
         + (f" (driest year {i['driest_year_rain_mm']:.0f}, wettest {i['wettest_year_rain_mm']:.0f})"
            if "driest_year_rain_mm" in i else "")),
        ("Warm-season rain", f"{i.get('warm_season_rain_mm'):.0f} mm"),
        ("Frost-free days", i.get("frost_free_days")),
        ("Coldest night (yearly avg)", f"{i['coldest_night_c']} degC" if "coldest_night_c" in i else None),
        ("Heat-stress days >32 degC", i.get("heat_days_per_year")),
        ("Heavy-rain days >25 mm", i.get("heavy_rain_days_per_year")),
        ("Rain trend", f"{i['rain_trend_mm_per_decade']:+.0f} mm per decade"
         if i.get("rain_trend_mm_per_decade") is not None else None),
        ("Temperature trend", f"{i['temp_trend_c_per_decade']:+.2f} degC per decade"
         if i.get("temp_trend_c_per_decade") is not None else None),
        ("Warm-season root-zone wetness", i.get("warm_season_root_wetness")),
        ("SMAP root-zone moisture (m3/m3)", i.get("smap_root_zone_moisture")),
    ]
    lines += [f"  {k:<32} {v}" for k, v in facts if v is not None]
    lines.append("")
    if field.site:
        s = field.site
        lines.append(f"Soil (USDA SSURGO): {s['soil_component']} ({s['soil_component_pct']:.0f}% of map unit), "
                     f"pH {s['ph']}, {s['text_raw']} texture, {s['dra_raw']}, organic matter "
                     f"{s['fer_raw_om_pct']}%, slope {s.get('slope_pct')}%")
    else:
        lines.append("Soil: the USDA SSURGO service did not answer - soil needs were not checked.")
    cr = field.current_rotation
    if cr:
        lines.append(f"Current rotation ({cr.get('source', 'you')}): " + " -> ".join(cr["crops"])
                     + ("" if cr.get("repeating", True) else "  (no clear repeating pattern; recent crops)"))
    else:
        lines.append("Current rotation: unknown (CropScape shows no crop rotation at this point; "
                     "enter your last rotation to compare against it)")
    return lines


def _previous_crop_line(previous: dict | None) -> str:
    if previous:
        return f"Crop grown last ({previous['source']}): {previous['crop']}"
    return "Crop grown last: unknown (pass --previous to add it)"


def _rotation_block(rot: Rotation, title: str) -> list[str]:
    e = rot.explanation
    lines = [title, "-" * len(title), rot.name, "", calendar_grid(rot), "",
             "Report card (0-1): " + ", ".join(f"{CARD[k]} {v:.2f}" for k, v in rot.card.items())
             + f"  ->  overall {rot.overall:.2f}"]
    res = rot.resilience
    if res and res.get("years_checked"):
        sc = res["scenario"]
        lines.append(f"Other weather: suited {res['years_ok']} of {res['years_checked']} years on "
                     f"record; {sc['name']}: fit {sc['fit_now']:.2f} -> {sc['fit']:.2f}")
    if not e:
        return lines + [""]
    lines += ["", "Why: " + e["why"], "", "Evidence:"] + [f"  {x}" for x in e["evidence"]]
    for key, label in (("benefits", "Benefits"), ("information_gaps", "Information gaps"),
                       ("risks", "Risks to check locally")):
        lines += ["", f"{label}:"] + [f"  - {x}" for x in e[key]]
    return lines + [""]


def text_report(rec) -> str:
    """The whole recommendation as printable text."""
    bar = "=" * 90
    lines = [bar, "  FIELD SHIFT - crop rotation options", bar, ""]
    lines += _field_summary(rec.field, rec.country, rec.place) + [_previous_crop_line(rec.previous_crop)]
    if rec.must_grow:
        lines.append("Must grow (in every option): " + ", ".join(rec.must_grow))
    if rec.budget:
        lines.append(f"Budget: ${rec.budget['budget_usd']:,.0f} a year for {rec.budget['plot_size_ha']:g} ha"
                     f" = at most {_per_area(rec.budget['max_cost_usd_ha'])} a year")
    economy = rec.economy
    if economy.crops:
        lines.append(f"Prices and yields: {len(economy.crops)} crops priced"
                     + (f", FAOSTAT national averages for {economy.country}" if economy.country else "")
                     + (f"; the typical hectare there earns about ${economy.typical_income:,.0f}"
                        if economy.typical_income else ""))
        lines.append("Crops grown on less than about 0.3% of the country's cropland are only "
                     "suggested if you add them as must-grow or enter your own price or cost")
        if economy.cost_share is not None:
            lines.append(f"Costs: yours where entered; other crops assumed at {economy.cost_share:.0%} "
                         f"of income, the share in the costs you entered")
    else:
        lines.append("Prices and yields: none available, so income and market did not affect the ranking")
    if rec.warnings:
        lines += ["", "Notes:"] + [f"  ! {w}" for w in rec.warnings]
    lines += ["", f"Priorities: {rec.priority_name}  (" + ", ".join(
        f"{CARD[k].split(' (')[0]} {v:.0%}" for k, v in rec.weights.items()) + ")", ""]
    if rec.baseline:
        lines += [bar] + _rotation_block(rec.baseline, "YOUR CURRENT ROTATION (scored the same way)")
    for i, rot in enumerate(rec.rotations, 1):
        lines += [bar] + _rotation_block(rot, f"OPTION {i}: {rot.strategy.upper()}")
    lines += [bar, "Words used:"] + [f"  {k}: {v}" for k, v in GLOSSARY.items()]
    lines += ["", "Data: " + "; ".join(rec.data_sources), "", DISCLAIMER, bar]
    return "\n".join(lines)
