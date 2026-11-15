"""All the money questions: what a crop earns here, and how easily it sells here.

    economy = build_economy(faostat_rows, crops, "Japan", farm_numbers)
    economy.income(crop)    US dollars per hectare at an average yield (0 if unknown)
    economy.trusted_income(crop)   the part of that income the ranking counts (see below)
    economy.value(crop)     0-1: trusted income against the country's typical hectare
    economy.market(crop)    0-1: how widely the crop is grown in the country (1 with the farmer's price)
    economy.score(dollars)  0-1 for any dollars-per-hectare figure (e.g. a whole rotation's)
    economy.rank(slot)      first-cut ranking of a crop option: suitability x (value and market);
                            0 for a crop grown too little to suggest (MIN_MARKET_TO_SUGGEST)

Where the numbers come from (data_pullers/FAOSTAT_pull.py):
  income  = yield (t/ha) x price paid to farmers (USD/t), national 5-year averages. The
            farmer's own price, yield or cost for a crop replaces or adds to them.
  typical = the area-weighted average income per hectare of everything the country grows.
            Scoring against it (not against the other crops) keeps scores stable.
  market  = the crop's share of the country's harvested area. FAOSTAT has no costs, but
            what farmers actually plant shows what pays after costs and what can be sold.
  trusted = income above the typical hectare is counted only as far as the crop is grown
            (market), unless the farmer entered its price or cost.
All money is in US dollars. The other decision modules never read prices themselves.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from statistics import median

import pandas as pd

from .crops import Crop, find_crop
from .suitability import Slot

# FAOSTAT crop item -> EcoCrop scientific name -> everyday name: a translation between the two
# databases (they share no code), kept as data. Tree crops, FAOSTAT's grouped "n.e.c." items,
# second forms of the same crop (green peas, cotton lint) and the few items EcoCrop has no row
# for (triticale, hops, pyrethrum, mate, melonseed) are not in it.
NAMES_FILE = Path(__file__).parent / "data" / "faostat_to_ecocrop.csv"
_NAMES = pd.read_csv(NAMES_FILE)
FAOSTAT_TO_ECOCROP: dict[str, tuple[str, ...]] = {
    item: tuple(rows["scientific_name"]) for item, rows in _NAMES.groupby("faostat_item", sort=False)}
SOLD_CROPS: dict[str, str] = dict(zip(_NAMES["scientific_name"], _NAMES["name"]))
_ITEM_OF = {sci: item for item, species in FAOSTAT_TO_ECOCROP.items() for sci in species}

NEUTRAL = 0.5                  # every score when there is no price data at all
MARKET_FULL_SHARE = 0.10       # 10% of the country's harvested area or more -> market 1.0
MARKET_ZERO_SHARE = 0.0001     # 0.01% or less -> market 0.0 (log scale in between)
# Crops below this market score (about 0.3% of the country's harvested area) are not suggested
# unless the farmer asks for them (must-grow, own price or own cost): a crop so few farmers grow
# usually has costs or buyer limits that FAOSTAT does not show, however high its income looks.
MIN_MARKET_TO_SUGGEST = 0.5
MAX_ASSUMED_COST_SHARE = 0.95  # cap on the cost share carried over to crops without a cost
MIN_ITEMS_FOR_PRICE_LEVEL = 3  # crops needed to compare a country's prices with the world's
COST_ENTERED = "entered by you"
FARM_FIELDS = {"price": "US dollars per tonne", "yield": "tonnes per hectare",
               "cost": "US dollars per hectare"}


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


@dataclass(frozen=True)
class Economics:
    """One crop's money figures in the field's country."""
    yield_t_ha: float
    yield_source: str
    price_usd_t: float
    price_source: str
    price_range: tuple[float, float] | None = None   # lowest and highest yearly FAOSTAT price
    area_share: float | None = None                  # share of the country's harvested area
    own_price: bool = False                          # the farmer gave the price
    cost_usd_ha: float | None = None
    cost_source: str = ""                            # "entered by you" or how it was estimated

    @property
    def gross_usd_ha(self) -> float:
        return self.yield_t_ha * self.price_usd_t

    @property
    def income_usd_ha(self) -> float:
        """Yield x price, minus the cost when there is one."""
        return self.gross_usd_ha - (self.cost_usd_ha or 0.0)

    @property
    def kind(self) -> str:
        return "income" if self.cost_usd_ha is None else "profit"

    def describe(self) -> str:
        swing = (f", yearly range ${self.price_range[0]:,.0f}-{self.price_range[1]:,.0f}"
                 if self.price_range else "")
        text = (f"about ${self.income_usd_ha:,.0f} {self.kind} per hectare at an average yield: "
                f"{self.yield_t_ha:.1f} t/ha ({self.yield_source}) x ${self.price_usd_t:,.0f}/t "
                f"({self.price_source}{swing})")
        if self.cost_usd_ha is None:
            return text + "; costs not included"
        return text + f" - ${self.cost_usd_ha:,.0f}/ha cost ({self.cost_source})"

    def to_dict(self) -> dict:
        return {"yield_t_ha": round(self.yield_t_ha, 2), "yield_source": self.yield_source,
                "price_usd_t": round(self.price_usd_t, 2), "price_source": self.price_source,
                "price_range_usd_t": [round(p, 2) for p in self.price_range] if self.price_range else None,
                "area_share": self.area_share,
                "cost_usd_ha": None if self.cost_usd_ha is None else round(self.cost_usd_ha),
                "cost_source": self.cost_source, "income_usd_ha": round(self.income_usd_ha),
                "income_is": "gross income" if self.cost_usd_ha is None else "profit after costs"}


@dataclass
class Economy:
    """Every priced crop in one country, and the yardsticks to score them with.
    Economy() with no crops is "no price data": every score is NEUTRAL."""
    country: str = ""
    crops: dict[str, Economics] = field(default_factory=dict)    # by scientific name
    typical_income: float | None = None     # USD per hectare of the country's typical hectare
    cost_share: float | None = None         # share of income assumed as cost where none was entered

    def get(self, crop: Crop) -> Economics | None:
        return self.crops.get(crop.sci)

    def income(self, crop: Crop) -> float:
        priced = self.get(crop)
        return priced.income_usd_ha if priced else 0.0

    def cost(self, crop: Crop) -> float:
        """Cost per hectare of growing the crop, entered or estimated (0 if unknown)."""
        priced = self.get(crop)
        return (priced.cost_usd_ha or 0.0) if priced else 0.0

    def score(self, income_usd_ha: float) -> float:
        """0-1 for an income per hectare: 0.5 = the country's typical hectare, 1.0 = ten times
        it, 0 = a tenth of it or a loss."""
        if not self.crops or not self.typical_income:
            return NEUTRAL
        if income_usd_ha <= 0:
            return 0.0
        return _clamp(0.5 + 0.5 * math.log10(income_usd_ha / self.typical_income))

    def trusted_income(self, crop: Crop) -> float:
        """The income used for ranking. Income up to the typical hectare counts in full. The
        part above it counts only as far as the crop is actually grown in the country:
        typical x (income / typical) ^ market. A crop showing 40x the typical income on 0.1%
        of the land almost certainly has costs or market limits FAOSTAT does not show.
        Trusted in full: a crop the farmer entered a cost or a price for."""
        priced = self.get(crop)
        if priced is None:
            return 0.0
        income, typical = priced.income_usd_ha, self.typical_income
        if not typical or income <= typical or priced.cost_source == COST_ENTERED:
            return income
        return typical * (income / typical) ** self.market(crop)

    def value(self, crop: Crop) -> float:
        return self.score(self.trusted_income(crop))

    def market(self, crop: Crop) -> float:
        """0-1 for how established the crop is in the country (log scale of its area share).
        A crop the farmer gave a price for has a buyer, so it scores 1."""
        if not self.crops:
            return NEUTRAL
        priced = self.get(crop)
        if priced is None:
            return 0.0
        if priced.own_price:
            return 1.0
        if not priced.area_share:
            return 0.0
        low, high = math.log10(MARKET_ZERO_SHARE), math.log10(MARKET_FULL_SHARE)
        return _clamp((math.log10(priced.area_share) - low) / (high - low))

    def rank(self, slot: Slot) -> float:
        """First-cut ranking of a crop option; 0 = nothing known to sell it for, or grown too
        little in the country to suggest (unless the farmer entered its cost; a crop with the
        farmer's own price already has market 1). With no price data, market is NEUTRAL and
        the ranking is suitability alone."""
        market = self.market(slot.crop)
        priced = self.get(slot.crop)
        if market < MIN_MARKET_TO_SUGGEST and not (priced and priced.cost_source == COST_ENTERED):
            return 0.0
        return slot.score * (self.value(slot.crop) + market) / 2

    def table(self, crops: dict[str, Crop]) -> list[dict]:
        """Every priced crop as a JSON-safe row, highest income first."""
        rows = [{"crop": crops[sci].name, "scientific_name": sci, **priced.to_dict(),
                 "value": round(self.value(crops[sci]), 3), "market": round(self.market(crops[sci]), 3)}
                for sci, priced in self.crops.items() if sci in crops]
        return sorted(rows, key=lambda r: -r["income_usd_ha"])


# --------------------------------------------------------------------------------------
# Building an Economy
# --------------------------------------------------------------------------------------
def _known(value) -> bool:
    return value is not None and not pd.isna(value)


def _farm_numbers(entries: dict | None, crops: dict[str, Crop]) -> dict[str, dict[str, float]]:
    """{crop name: {"price"/"yield"/"cost": number}} from the farmer -> keyed by scientific name."""
    out: dict[str, dict[str, float]] = {}
    for name, numbers in (entries or {}).items():
        crop = find_crop(name, crops)
        if crop is None:
            raise ValueError(f"Unknown crop name {name!r} in farm_numbers.")
        if not isinstance(numbers, dict) or set(numbers) - set(FARM_FIELDS):
            raise ValueError(f"farm_numbers for {name!r} must be a dict using only "
                             f"{', '.join(FARM_FIELDS)}, got {numbers!r}.")
        for what, number in numbers.items():
            try:
                number = float(number)
            except (TypeError, ValueError):
                raise ValueError(f"The {what} for {name!r} must be a number, got {number!r}.") from None
            if not math.isfinite(number) or number < 0 or (what == "yield" and number == 0):
                raise ValueError(f"The {what} for {name!r} must be {'more than 0' if what == 'yield' else '0 or more'}"
                                 f" ({FARM_FIELDS[what]}), got {number}.")
            out.setdefault(crop.sci, {})[what] = number
    return out


def price_level(rows: pd.DataFrame) -> float:
    """How the country's farm prices compare with the world's: the median, over crops with
    both, of local price / world median price (about 1 for the US, 3.5 for Japan)."""
    if not {"price_usd_t", "world_price_usd_t"} <= set(rows.columns):
        return 1.0
    both = rows[(rows["price_usd_t"] > 0) & (rows["world_price_usd_t"] > 0)]
    if len(both) < MIN_ITEMS_FOR_PRICE_LEVEL:
        return 1.0
    return float((both["price_usd_t"] / both["world_price_usd_t"]).median())


def typical_income(rows: pd.DataFrame) -> float | None:
    """Income per hectare of the country's typical hectare: every crop's yield x price,
    weighted by the area it is grown on."""
    if not {"yield_t_ha", "price_usd_t", "area_ha"} <= set(rows.columns):
        return None
    known = rows.dropna(subset=["yield_t_ha", "price_usd_t", "area_ha"])
    known = known[known["area_ha"] > 0]
    if known.empty:
        return None
    income = known["yield_t_ha"] * known["price_usd_t"]
    return float((income * known["area_ha"]).sum() / known["area_ha"].sum())


def _price_crop(row, mine: dict, country: str, level: float, total_area: float) -> Economics | None:
    """One crop's Economics from its FAOSTAT row (may be empty) and the farmer's numbers,
    or None if either a yield or a price is missing."""
    where = f"FAOSTAT {country}".strip()
    if "yield" in mine:
        yield_, yield_source = mine["yield"], "your yield"
    elif _known(row.get("yield_t_ha")):
        yield_, yield_source = row["yield_t_ha"], f"{where} {row['yield_years']}"
    elif _known(row.get("world_yield_t_ha")):
        yield_, yield_source = row["world_yield_t_ha"], f"FAOSTAT world median; not grown in {country or 'this country'}"
    else:
        return None
    price_range = None
    if "price" in mine:
        price, price_source = mine["price"], "your price"
    elif _known(row.get("price_usd_t")):
        price, price_source = row["price_usd_t"], f"{where} {row['price_years']}"
        if _known(row.get("price_low_usd_t")) and _known(row.get("price_high_usd_t")):
            price_range = (float(row["price_low_usd_t"]), float(row["price_high_usd_t"]))
    elif _known(row.get("world_price_usd_t")):
        price = row["world_price_usd_t"] * level
        price_source = (f"estimate: FAOSTAT world median x {level:.2f}, the local price level"
                        if level != 1.0 else "estimate: FAOSTAT world median")
    else:
        return None
    area = row.get("area_ha")
    share = float(area) / total_area if _known(area) and total_area > 0 else None
    return Economics(float(yield_), yield_source, float(price), price_source, price_range, share,
                     own_price="price" in mine, cost_usd_ha=mine.get("cost"),
                     cost_source=COST_ENTERED if "cost" in mine else "")


def _spread_costs(priced: dict[str, Economics]) -> tuple[dict[str, Economics], float | None]:
    """If the farmer gave costs for some crops, give the others the same share of income as
    a cost, so profit is compared with profit. Returns (crops, the share used or None)."""
    shares = [e.cost_usd_ha / e.gross_usd_ha for e in priced.values()
              if e.cost_usd_ha is not None and e.gross_usd_ha > 0]
    if not shares:
        return priced, None
    share = min(MAX_ASSUMED_COST_SHARE, median(shares))
    note = f"estimated: {share:.0%} of income, the share in the costs you entered"
    return {sci: e if e.cost_usd_ha is not None
            else replace(e, cost_usd_ha=e.gross_usd_ha * share, cost_source=note)
            for sci, e in priced.items()}, share


def build_economy(faostat: pd.DataFrame, crops: dict[str, Crop], country: str = "",
                  farm_numbers: dict | None = None) -> Economy:
    """Price every crop that can be priced.

    faostat       get_crop_economics() output for the field's country (may be empty)
    farm_numbers  the farmer's own figures, {crop name: {"price": USD per tonne,
                  "yield": tonnes per hectare, "cost": USD per hectare}}, each optional

    Yield: the farmer's, else the country's, else the world median (a crop new to the country).
    Price: the farmer's, else the country's, else the world median at the country's price level.
    A crop outside FAOSTAT (e.g. alfalfa hay) is priced when the farmer gives both. Costs:
    see _spread_costs(). Numbers that cannot be turned into an income are an error.
    """
    mine = _farm_numbers(farm_numbers, crops)
    rows = faostat.set_index("item") if len(faostat) else pd.DataFrame()
    level = price_level(rows)
    total_area = float(rows["area_ha"].sum()) if "area_ha" in rows.columns else 0.0
    priced: dict[str, Economics] = {}
    for sci in crops:
        item = _ITEM_OF.get(sci)
        if item is None and sci not in mine:
            continue
        row = rows.loc[item] if item in rows.index else {}
        found = _price_crop(row, mine.get(sci, {}), country, level, total_area)
        if found is not None:
            priced[sci] = found
    stranded = sorted(crops[sci].name for sci in mine if sci not in priced)
    if stranded:
        raise ValueError(f"Not enough numbers to price {', '.join(stranded)}: FAOSTAT has no yield "
                         f"or price for it here, so give both a price and a yield.")
    priced, share = _spread_costs(priced)
    typical = typical_income(rows)
    if typical is not None and share is not None:
        typical *= 1 - share                        # the yardstick is profit too
    if typical is None:
        earning = [e.income_usd_ha for e in priced.values() if e.income_usd_ha > 0]
        typical = median(earning) if earning else None
    return Economy(country, priced, typical, share)
