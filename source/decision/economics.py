"""What a crop earns per hectare in the field's country.

    income per hectare = yield (t/ha) x price paid to farmers (USD/t)  [- cost, if the farmer gave one]

Yields and prices are FAOSTAT national averages (data_pullers/FAOSTAT_pull.py). The farmer's own
price for a crop replaces FAOSTAT's. FAOSTAT has no costs, so income is gross unless the farmer
enters a cost per hectare for that crop. All money is in US dollars.

  FAOSTAT_TO_ECOCROP   translation between the two databases' crop names
  income_table()       {scientific name: Economics} for the crops with a known yield and price
  with_economics()     the crops, each given its Economics and a 0-1 `value` for the report card
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import pandas as pd

from .crops import Crop, find_crop

LOWEST_VALUE = 0.2      # report-card value of the lowest-earning priced crop (highest = 1.0)
NO_PRICE_VALUE = 0.1    # harvest crops FAOSTAT has no local yield or price for

# FAOSTAT crop item -> EcoCrop scientific name -> everyday name.
# A translation table between the two databases (they share no code), not a list of preferred
# crops: which of these are used is decided by crops.is_rotation_crop() and by the data.
# Tree and orchard items are left out because trees are never rotation crops.
_TRANSLATION = [
    ("Barley", "Hordeum vulgare", "barley"),
    ("Bambara beans, dry", "Vigna subterranea", "bambara groundnut"),
    ("Beans, dry", "Phaseolus vulgaris", "dry bean"),
    ("Broad beans and horse beans, dry", "Vicia faba", "faba bean"),
    ("Buckwheat", "Fagopyrum esculentum", "buckwheat"),
    ("Cabbages", "Brassica oleracea var. capitata", "cabbage"),
    ("Canary seed", "Phalaris canariensis", "canary seed"),
    ("Cantaloupes and other melons", "Cucumis melo", "melon"),
    ("Carrots and turnips", "Daucus carota", "carrot"),
    ("Cassava, fresh", "Manihot esculenta", "cassava"),
    ("Cauliflowers and broccoli", "Brassica oleracea var. botrytis", "cauliflower"),
    ("Cauliflowers and broccoli", "Brassica oleracea var. italica", "broccoli"),
    ("Chick peas, dry", "Cicer arietinum", "chickpea"),
    ("Chicory roots", "Cichorium intybus", "chicory"),
    ("Chillies and peppers, green (Capsicum spp. and Pimenta spp.)", "Capsicum annuum", "pepper"),
    ("Cow peas, dry", "Vigna unguiculata", "cowpea"),
    ("Cucumbers and gherkins", "Cucumis sativus", "cucumber"),
    ("Eggplants (aubergines)", "Solanum melongena", "eggplant"),
    ("Fonio", "Digitaria exilis", "fonio"),
    ("Ginger, raw", "Zingiber officinale", "ginger"),
    ("Green corn (maize)", "Zea mays ssp. saccharata", "sweet corn"),
    ("Green garlic", "Allium sativum", "garlic"),
    ("Groundnuts, excluding shelled", "Arachis hypogaea", "peanut"),
    ("Hempseed", "Cannabis sativa ssp. indica", "hemp"),
    ("Jute, raw or retted", "Corchorus capsularis", "jute"),
    ("Kenaf, and other textile bast fibres, raw or retted", "Hibiscus cannabinus", "kenaf"),
    ("Leeks and other alliaceous vegetables", "Allium ampeloprasum", "leek"),
    ("Lentils, dry", "Lens culinaris", "lentil"),
    ("Lettuce and chicory", "Lactuca sativa var. capitata", "lettuce"),
    ("Linseed", "Linum usitatissimum", "flax"),
    ("Lupins", "Lupinus angustifolius", "blue lupin"),
    ("Lupins", "Lupinus albus", "white lupin"),
    ("Maize (corn)", "Zea mays ssp. mays", "corn"),
    ("Millet", "Pennisetum glaucum", "pearl millet"),
    ("Millet", "Panicum miliaceum", "proso millet"),
    ("Millet", "Setaria italica", "foxtail millet"),
    ("Millet", "Eleusine coracana ssp. coracana", "finger millet"),
    ("Mustard seed", "Sinapis alba", "white mustard"),
    ("Mustard seed", "Brassica juncea", "brown mustard"),
    ("Oats", "Avena sativa", "oats"),
    ("Okra", "Abelmoschus esculentus", "okra"),
    ("Onions and shallots, dry (excluding dehydrated)", "Allium cepa", "onion"),
    ("Peas, dry", "Pisum sativum", "field pea"),
    ("Pigeon peas, dry", "Cajanus cajan", "pigeon pea"),
    ("Potatoes", "Solanum tuberosum", "potato"),
    ("Pumpkins, squash and gourds", "Cucurbita maxima", "pumpkin"),
    ("Pumpkins, squash and gourds", "Cucurbita pepo", "squash"),
    ("Quinoa", "Chenopodium quinoa", "quinoa"),
    ("Rape or colza seed", "Brassica napus", "canola"),
    ("Rice", "Oryza sativa", "rice"),
    ("Rye", "Secale cereale", "rye"),
    ("Safflower seed", "Carthamus tinctorius", "safflower"),
    ("Seed cotton, unginned", "Gossypium hirsutum", "cotton"),
    ("Sesame seed", "Sesamum indicum", "sesame"),
    ("Sorghum", "Sorghum bicolor", "sorghum"),
    ("Soya beans", "Glycine max", "soybean"),
    ("Spinach", "Spinacia oleracea", "spinach"),
    ("Strawberries", "Fragaria x ananassa", "strawberry"),
    ("Sugar beet", "Beta vulgaris var. saccharifera", "sugar beet"),
    ("Sugar cane", "Saccharum officinarum", "sugarcane"),
    ("Sunflower seed", "Helianthus annuus", "sunflower"),
    ("Sweet potatoes", "Ipomoea batatas", "sweet potato"),
    ("Taro", "Colocasia esculenta", "taro"),
    ("Tomatoes", "Lycopersicon esculentum", "tomato"),
    ("Unmanufactured tobacco", "Nicotiana tabacum", "tobacco"),
    ("Vetches", "Vicia sativa ssp. sativa", "common vetch"),
    ("Watermelons", "Citrullus lanatus", "watermelon"),
    ("Wheat", "Triticum aestivum", "wheat"),
    ("Wheat", "Triticum durum", "durum wheat"),
    ("Yams", "Dioscorea alata", "yam"),
    ("Yautia", "Xanthosoma sagittifolium", "tannia"),
]
FAOSTAT_TO_ECOCROP: dict[str, tuple[str, ...]] = {}
for _item, _sci, _name in _TRANSLATION:
    FAOSTAT_TO_ECOCROP[_item] = FAOSTAT_TO_ECOCROP.get(_item, ()) + (_sci,)
SOLD_CROPS = {sci: name for _, sci, name in _TRANSLATION}     # scientific name -> everyday name


@dataclass(frozen=True)
class Economics:
    yield_t_ha: float
    yield_source: str
    price_usd_t: float
    price_source: str
    cost_usd_ha: float | None       # only when the farmer entered one
    income_usd_ha: float            # yield x price, minus the cost if there is one

    @property
    def kind(self) -> str:
        return "income" if self.cost_usd_ha is None else "profit"

    def describe(self) -> str:
        text = (f"about ${self.income_usd_ha:,.0f} {self.kind} per hectare at an average yield: "
                f"{self.yield_t_ha:.1f} t/ha ({self.yield_source}) x ${self.price_usd_t:,.0f}/t "
                f"({self.price_source})")
        if self.cost_usd_ha is None:
            return text + "; costs not included"
        return text + f" - ${self.cost_usd_ha:,.0f}/ha cost (entered by you)"

    def to_dict(self) -> dict:
        return {"yield_t_ha": round(self.yield_t_ha, 2), "yield_source": self.yield_source,
                "price_usd_t": round(self.price_usd_t, 2), "price_source": self.price_source,
                "cost_usd_ha": self.cost_usd_ha, "income_usd_ha": round(self.income_usd_ha),
                "income_is": "gross income" if self.cost_usd_ha is None else "profit after your costs"}


def _by_crop(entries: dict | None, crops: dict[str, Crop], what: str) -> dict[str, float]:
    """{crop name: number} from the farmer -> {scientific name: number}."""
    out, unknown = {}, []
    for name, number in (entries or {}).items():
        crop = find_crop(name, crops)
        try:
            number = float(number)
        except (TypeError, ValueError):
            raise ValueError(f"The {what} for {name!r} must be a number, got {number!r}.") from None
        if crop is None:
            unknown.append(name)
        elif number < 0 or not math.isfinite(number):
            raise ValueError(f"The {what} for {name!r} must be 0 or more, got {number}.")
        else:
            out[crop.sci] = number
    if unknown:
        raise ValueError(f"Unknown crop name(s) in {what}s: {unknown}.")
    return out


def _known(value) -> bool:
    return value is not None and not pd.isna(value)


def income_table(faostat: pd.DataFrame, crops: dict[str, Crop], country: str = "",
                 local_prices: dict | None = None, costs: dict | None = None) -> dict[str, Economics]:
    """{scientific name: Economics} for every crop with a yield and a price.

    faostat       get_crop_economics() output for the field's country (may be empty)
    local_prices  {crop name: USD per tonne} from the farmer; replaces FAOSTAT's price
    costs         {crop name: USD per hectare} from the farmer; turns income into profit

    Price used: the farmer's, else FAOSTAT's for the country, else (only for crops FAOSTAT
    shows are grown there) the world median. Yield: the country's, else the world median when
    the farmer gave a price. A farmer's price for a crop FAOSTAT has no yield for anywhere is
    an error, because it cannot be turned into income per hectare.
    """
    prices, costs = _by_crop(local_prices, crops, "price"), _by_crop(costs, crops, "cost")
    rows = faostat.set_index("item") if len(faostat) else pd.DataFrame()
    where = f"FAOSTAT {country}".strip()
    table: dict[str, Economics] = {}
    for item, species in FAOSTAT_TO_ECOCROP.items():
        row = rows.loc[item] if item in rows.index else {}
        for sci in species:
            if sci not in crops:
                continue
            grown_here = _known(row.get("yield_t_ha"))
            if grown_here:
                yield_, yield_source = row["yield_t_ha"], f"{where} {row['yield_years']}"
            elif sci in prices and _known(row.get("world_yield_t_ha")):
                yield_, yield_source = row["world_yield_t_ha"], "FAOSTAT world median; not grown locally"
            else:
                continue
            if sci in prices:
                price, price_source = prices[sci], "your price"
            elif _known(row.get("price_usd_t")):
                price, price_source = row["price_usd_t"], f"{where} {row['price_years']}"
            elif _known(row.get("world_price_usd_t")):
                price, price_source = row["world_price_usd_t"], "FAOSTAT world median; no local price"
            else:
                continue
            cost = costs.get(sci)
            table[sci] = Economics(float(yield_), yield_source, float(price), price_source, cost,
                                   float(yield_) * float(price) - (cost or 0.0))
    stranded = [crops[sci].name for sci in {**prices, **costs} if sci not in table]
    if stranded:
        raise ValueError(f"FAOSTAT has no yield for {', '.join(sorted(stranded))}, so a price or "
                         f"cost for it cannot be turned into income per hectare.")
    return table


def value_scores(table: dict[str, Economics]) -> dict[str, float]:
    """0-1 report-card value per crop, on a log scale from the lowest to the highest earner.

    Log scale because incomes span 100x (grain vs vegetables) and are mostly gross: a crop
    earning ten times more is more attractive, but not ten times, while costs are unknown.
    A crop that loses money after the farmer's costs scores 0."""
    earning = {sci: math.log(e.income_usd_ha) for sci, e in table.items() if e.income_usd_ha > 0}
    if not earning:
        return {sci: 0.0 for sci in table}
    low, high = min(earning.values()), max(earning.values())

    def scaled(log_income: float) -> float:
        if high == low:
            return 1.0
        return min(1.0, LOWEST_VALUE + (1 - LOWEST_VALUE) * (log_income - low) / (high - low))

    return {sci: scaled(earning[sci]) if sci in earning else 0.0 for sci in table}


def with_economics(crops: dict[str, Crop], table: dict[str, Economics]) -> dict[str, Crop]:
    """The same crops with `economics` and `value` filled in (no price -> NO_PRICE_VALUE)."""
    values = value_scores(table)
    return {sci: replace(crop, economics=table.get(sci), value=values.get(sci, NO_PRICE_VALUE))
            for sci, crop in crops.items()}
