"""The results page: a recommendation shown as cards a farmer can read at a glance.

    view = ResultsView(parent, theme)
    view.show(recommendation.to_dict())

Top to bottom: the field in a few numbers, things to know, the options side by side, then one
card per option (a month-by-month calendar, scores against the current rotation, why it was
picked, benefits, what to check, and the detail behind it folded away).

Everything is read from Recommendation.to_dict(), the same data any other front end gets. The
functions above the class need no window, so they can be tested directly.
"""

from __future__ import annotations

import tkinter as tk

from .theme import Theme
from .units import ACRES_PER_HA
from .widgets import Foldout, ScrollFrame, card, text

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MM_PER_INCH = 25.4

# Report-card items in the words a farmer would use (falls back to the back end's own label).
SCORE_NAMES = {"fit": "Suits your climate and soil", "cover": "Keeps the soil covered",
               "nitrogen": "Nitrogen from legumes", "diversity": "Variety of crops",
               "sequence": "Crops follow each other well", "water": "Low water need",
               "income": "Income", "market": "Easy to sell here"}
ROW_HEIGHT, HEADER_HEIGHT, YEAR_WIDTH = 30, 20, 58


# --------------------------------------------------------------------------------------
# Reading the data (no window needed)
# --------------------------------------------------------------------------------------
def out_of_100(score) -> int:
    return round(100 * float(score or 0))


def money(dollars) -> str:
    return f"${float(dollars or 0):,.0f}"


def per_acre(dollars_per_ha) -> str:
    return money(float(dollars_per_ha or 0) / ACRES_PER_HA)


def harvest_names(rotation: dict) -> str:
    """'corn, then soybean': the crops that are harvested, in order."""
    names = [s["crop"] for s in rotation.get("steps", []) if s.get("use") == "harvest"]
    return ", then ".join(names) if names else rotation.get("name", "")


def calendar(rotation: dict) -> list[list[tuple[str, str] | None]]:
    """One row per year, 12 cells each: (crop, "harvest" or "cover"), or None for bare soil."""
    years = max(1, int(rotation.get("years", 1)))
    cells: list = [None] * (12 * years)
    for step in rotation.get("steps", []):
        start = 12 * (int(step["year"]) - 1) + MONTHS.index(step["plant"])
        for i in range(int(step["months"])):
            cells[(start + i) % len(cells)] = (step["crop"], step["use"])
    return [cells[12 * y:12 * y + 12] for y in range(years)]


def covered_months_per_year(rotation: dict) -> float:
    rows = calendar(rotation)
    return sum(cell is not None for row in rows for cell in row) / len(rows)


def options(data: dict) -> list[tuple[str, dict]]:
    """[("Option 1", rotation), ...] followed by ("What you grow now", current) if it is known."""
    out = [(f"Option {n}", rot) for n, rot in enumerate(data.get("recommended_rotations", []), 1)]
    if data.get("current_rotation"):
        out.append(("What you grow now", data["current_rotation"]))
    return out


def field_facts(data: dict) -> list[tuple[str, str]]:
    """(label, value) tiles describing the field, in everyday units."""
    field = data.get("field", {})
    seen, site = field.get("insights", {}), field.get("site") or {}
    facts = []
    if seen.get("annual_rain_mm") is not None:
        rain = seen["annual_rain_mm"]
        facts.append(("Rain in a year", f"{rain:.0f} mm ({rain / MM_PER_INCH:.0f} in)"))
    if seen.get("frost_free_days") is not None:
        facts.append(("Frost-free days", f"{seen['frost_free_days']:.0f}"))
    if seen.get("heat_days_per_year") is not None:
        facts.append(("Very hot days a year", f"{seen['heat_days_per_year']:.0f}  (over 32°C / 90°F)"))
    if site:
        soil = ", ".join(str(part) for part in (site.get("text_raw"),
                                                f"pH {site['ph']}" if site.get("ph") is not None else None,
                                                str(site.get("dra_raw") or "").lower() or None) if part)
        facts.append(("Soil", soil or "unknown"))
    current = field.get("current_rotation")
    if current:
        facts.append(("You grow now", ", then ".join(str(c).lower() for c in current.get("crops", []))))
    return facts


def crop_colours(data: dict, palette: tuple) -> dict[str, str]:
    """One colour per harvest crop, the same on every calendar in the result."""
    colours: dict[str, str] = {}
    for _, rotation in options(data):
        for step in rotation.get("steps", []):
            if step.get("use") == "harvest" and step["crop"] not in colours:
                colours[step["crop"]] = palette[len(colours) % len(palette)]
    return colours


# --------------------------------------------------------------------------------------
# The page
# --------------------------------------------------------------------------------------
class ResultsView(ScrollFrame):
    def __init__(self, parent, theme: Theme) -> None:
        super().__init__(parent, theme)
        self.theme = theme

    def show(self, data: dict) -> None:
        self.clear()
        self.data = data
        self.colours = crop_colours(data, self.theme.crop_colours)
        self.current = data.get("current_rotation")
        self._field()
        self._notes()
        self._at_a_glance()
        for label, rotation in options(data):
            self._option(label, rotation)
        self._footer()

    # ---- small pieces ----
    def _heading(self, parent, words: str, **pack) -> None:
        text(parent, words, self.theme, font=self.theme.heading_font(), **pack)

    def _bullets(self, parent, lines, mark: str, colour: str) -> None:
        for line in lines:
            row = tk.Frame(parent, bg=parent.cget("bg"))
            row.pack(fill="x", pady=1)
            tk.Label(row, text=mark, bg=row.cget("bg"), fg=colour, font=self.theme.bold_font(),
                     width=2).pack(side="left", anchor="n")
            text(row, line, self.theme, side="left", expand=True)

    def _bar(self, parent, score, marker=None, width: int = 150) -> tk.Canvas:
        """A 0-100 bar; `marker` draws a tick where the current rotation scores."""
        bar = tk.Canvas(parent, width=width, height=14, bg=parent.cget("bg"), highlightthickness=0)
        bar.create_rectangle(0, 3, width, 11, fill=self.theme.track, width=0)
        bar.create_rectangle(0, 3, width * out_of_100(score) / 100, 11, fill=self.theme.good, width=0)
        if marker is not None:
            x = min(width - 1, max(1, width * out_of_100(marker) / 100))
            bar.create_line(x, 0, x, 14, fill=self.theme.colour1, width=2)
        return bar

    # ---- sections ----
    def _field(self) -> None:
        field = self.data.get("field")
        if not field:
            return
        box = card(self.body, self.theme)
        where = self.data.get("place") or f"latitude {field.get('lat')}, longitude {field.get('lon')}"
        self._heading(box, f"Your field: {where}")
        tiles = tk.Frame(box, bg=box.cget("bg"))
        tiles.pack(fill="x", pady=(6, 0))
        for column, (label, value) in enumerate(field_facts(self.data)):
            tile = tk.Frame(tiles, bg=self.theme.background1)
            tile.grid(row=0, column=column, padx=(0, 8), sticky="nsew")
            tiles.columnconfigure(column, weight=1, uniform="tile")
            tk.Label(tile, text=label, bg=tile.cget("bg"), fg=self.theme.muted,
                     font=self.theme.small_font(), anchor="w").pack(fill="x", padx=8, pady=(4, 0))
            text(tile, value, self.theme, font=self.theme.bold_font(), padx=8, pady=(0, 4))
        years = field.get("insights", {}).get("years_of_data")
        text(box, f"Weather from NASA POWER ({years} years), soil from the USDA soil survey, crop history "
                  f"from USDA CropScape.", self.theme, font=self.theme.small_font(),
             fg=self.theme.muted, pady=(6, 0))

    def _notes(self) -> None:
        notes = self.data.get("warnings") or []
        if notes:
            box = card(self.body, self.theme, bg=self.theme.warn_soft)
            self._heading(box, "Things to know first")
            self._bullets(box, notes, "!", self.theme.warn)

    def _at_a_glance(self) -> None:
        rows = options(self.data)
        if not rows:
            return
        box = card(self.body, self.theme)
        self._heading(box, "The options side by side")
        table = tk.Frame(box, bg=box.cget("bg"))
        table.pack(fill="x", pady=(6, 0))
        table.columnconfigure(1, weight=1)
        heads = ("", "Crops harvested", "Overall score", "Income a year", "Soil covered")
        for column, head in enumerate(heads):
            tk.Label(table, text=head, bg=table.cget("bg"), fg=self.theme.muted,
                     font=self.theme.small_font(), anchor="w").grid(row=0, column=column, sticky="w", padx=6)
        for r, (label, rot) in enumerate(rows, 1):
            is_current = rot is self.current
            font = self.theme.text_font() if is_current else self.theme.bold_font()
            cell = lambda words, column, f=font: tk.Label(
                table, text=words, bg=table.cget("bg"), fg=self.theme.colour1, font=f, anchor="w",
                justify="left", wraplength=330).grid(row=r, column=column, sticky="w", padx=6, pady=3)
            cell(label, 0)
            cell(harvest_names(rot), 1, self.theme.text_font())
            score = tk.Frame(table, bg=table.cget("bg"))
            score.grid(row=r, column=2, sticky="w", padx=6)
            self._bar(score, rot.get("overall"), width=90).pack(side="left")
            tk.Label(score, text=f" {out_of_100(rot.get('overall'))}", bg=score.cget("bg"),
                     fg=self.theme.colour1, font=font).pack(side="left")
            income = rot.get("trusted_income_usd_ha_per_year", rot.get("income_usd_ha_per_year"))
            cell(f"{per_acre(income)} an acre", 3)
            cell(f"{covered_months_per_year(rot):.0f} of 12 months", 4)
        text(box, "Scores are out of 100 for the priority you chose. Income is the cautious estimate "
                  "the score uses, before costs unless you entered yours.",
             self.theme, font=self.theme.small_font(), fg=self.theme.muted, pady=(6, 0))

    def _option(self, label: str, rot: dict) -> None:
        is_current = rot is self.current
        box = card(self.body, self.theme)
        why = rot.get("explanation", {})

        top = tk.Frame(box, bg=box.cget("bg"))
        top.pack(fill="x")
        tk.Label(top, text=f"{out_of_100(rot.get('overall'))} / 100", bg=self.theme.good_soft,
                 fg=self.theme.good, font=self.theme.heading_font(), padx=10, pady=2).pack(side="right", anchor="n")
        title = label if is_current else f"{label}: {str(rot.get('strategy', '')).capitalize()}"
        self._heading(top, title, side="left", expand=True)
        text(box, rot.get("name", "").replace(" -> ", "  →  "), self.theme, pady=(2, 6))

        self._calendar(box, rot)

        columns = tk.Frame(box, bg=box.cget("bg"))
        columns.pack(fill="x", pady=(10, 0))
        columns.columnconfigure(0, weight=1, uniform="half")
        columns.columnconfigure(1, weight=1, uniform="half")
        left = tk.Frame(columns, bg=box.cget("bg"))
        left.grid(row=0, column=0, sticky="new", padx=(0, 12))
        right = tk.Frame(columns, bg=box.cget("bg"))
        right.grid(row=0, column=1, sticky="new")

        self._scores(left, rot, None if is_current else self.current)
        self._money(right, rot)
        if why.get("benefits"):
            text(right, "What it does well" if is_current else "What you gain", self.theme,
                 font=self.theme.bold_font(), pady=(8, 2))
            self._bullets(right, why["benefits"], "✓", self.theme.good)

        if why.get("risks"):
            text(box, "Check before you plant", self.theme, font=self.theme.bold_font(), pady=(10, 2))
            self._bullets(box, why["risks"], "!", self.theme.warn)
        if why.get("information_gaps"):
            fold = Foldout(box, f"What this tool does not know ({len(why['information_gaps'])})", self.theme)
            fold.pack(fill="x", pady=(8, 0))
            self._bullets(fold.body, why["information_gaps"], "?", self.theme.muted)
        if why.get("evidence"):
            fold = Foldout(box, "The numbers behind each crop", self.theme)
            fold.pack(fill="x")
            for line in why["evidence"]:
                detail = line.startswith("    ")
                text(fold.body, line.strip(), self.theme, padx=(18 if detail else 0, 0),
                     font=self.theme.small_font() if detail else self.theme.bold_font(),
                     fg=self.theme.muted if detail else self.theme.colour1)

    def _scores(self, parent, rot: dict, compare: dict | None) -> None:
        text(parent, "How it scores" + ("  (black line = what you grow now)" if compare else ""),
             self.theme, font=self.theme.bold_font(), pady=(0, 2))
        names = self.data.get("priorities", {}).get("card_items", {})
        grid = tk.Frame(parent, bg=parent.cget("bg"))
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1)
        for row, (key, score) in enumerate(rot.get("card", {}).items()):
            tk.Label(grid, text=SCORE_NAMES.get(key, names.get(key, key)), bg=grid.cget("bg"),
                     fg=self.theme.colour1, font=self.theme.text_font(), anchor="w").grid(
                row=row, column=0, sticky="w")
            self._bar(grid, score, (compare or {}).get("card", {}).get(key)).grid(row=row, column=1, padx=8)
            tk.Label(grid, text=str(out_of_100(score)), bg=grid.cget("bg"), fg=self.theme.colour1,
                     font=self.theme.text_font(), width=3, anchor="e").grid(row=row, column=2)

    def _money(self, parent, rot: dict) -> None:
        full = rot.get("income_usd_ha_per_year") or 0
        counted = rot.get("trusted_income_usd_ha_per_year", full) or 0
        cost = rot.get("cost_usd_ha_per_year") or 0
        if not full:
            return
        text(parent, "Money", self.theme, font=self.theme.bold_font(), pady=(0, 2))
        words = f"About {per_acre(counted)} an acre a year ({money(counted)} a hectare)"
        words += " after the costs you entered." if cost else ", before costs."
        if counted < 0.9 * full:
            words += (f" National prices put it as high as {per_acre(full)} an acre, but crops few "
                      f"farmers here grow usually cost more or sell less than that suggests.")
        text(parent, words, self.theme)

    def _calendar(self, parent, rot: dict) -> None:
        rows = calendar(rot)
        height = HEADER_HEIGHT + ROW_HEIGHT * len(rows)
        canvas = tk.Canvas(parent, height=height, bg=parent.cget("bg"), highlightthickness=0)
        canvas.pack(fill="x")
        small, bold = self.theme.small_font(), self.theme.bold_font()

        def draw(event=None) -> None:
            canvas.delete("all")
            width = max(canvas.winfo_width(), 300)
            cell = (width - YEAR_WIDTH - 2) / 12
            for m, name in enumerate(MONTHS):
                canvas.create_text(YEAR_WIDTH + cell * (m + 0.5), HEADER_HEIGHT / 2, text=name,
                                   font=small, fill=self.theme.muted)
            for y, row in enumerate(rows):
                top = HEADER_HEIGHT + ROW_HEIGHT * y
                canvas.create_text(4, top + ROW_HEIGHT / 2, text=f"Year {y + 1}", anchor="w",
                                   font=small, fill=self.theme.muted)
                m = 0
                while m < 12:                               # one block per run of the same crop
                    end = m
                    while end + 1 < 12 and row[end + 1] == row[m]:
                        end += 1
                    x0, x1 = YEAR_WIDTH + cell * m, YEAR_WIDTH + cell * (end + 1)
                    if row[m] is None:
                        fill, ink, label = self.theme.bare, self.theme.muted, "bare" if end > m else ""
                    elif row[m][1] == "cover":
                        fill, ink, label = self.theme.cover, self.theme.colour1, f"{row[m][0]} (cover)"
                    else:
                        fill, ink, label = self.colours.get(row[m][0], self.theme.good), "white", row[m][0]
                    canvas.create_rectangle(x0 + 1, top + 2, x1 - 1, top + ROW_HEIGHT - 2, fill=fill, width=0)
                    font = small if row[m] is None or row[m][1] == "cover" else bold
                    if font.measure(label) < x1 - x0 - 6:
                        canvas.create_text((x0 + x1) / 2, top + ROW_HEIGHT / 2, text=label, font=font, fill=ink)
                    m = end + 1

        canvas.bind("<Configure>", draw)
        legend = tk.Frame(parent, bg=parent.cget("bg"))
        legend.pack(anchor="w", pady=(2, 0))
        for colour, words in ((self.theme.good, "harvest crop"), (self.theme.cover, "cover crop (protects the soil)"),
                              (self.theme.bare, "bare soil")):
            tk.Label(legend, bg=colour, width=2).pack(side="left", padx=(0, 4))
            tk.Label(legend, text=words, bg=legend.cget("bg"), fg=self.theme.muted,
                     font=small).pack(side="left", padx=(0, 14))

    def _footer(self) -> None:
        box = card(self.body, self.theme, bg=self.theme.background1)
        if self.data.get("disclaimer"):
            text(box, self.data["disclaimer"], self.theme, font=self.theme.bold_font())
        if self.data.get("glossary"):
            fold = Foldout(box, "What the words mean", self.theme)
            fold.pack(fill="x", pady=(6, 0))
            for word, meaning in self.data["glossary"].items():
                text(fold.body, f"{word.capitalize()}: {meaning}", self.theme, font=self.theme.small_font(), pady=1)
        if self.data.get("data_sources"):
            text(box, "Data: " + "; ".join(self.data["data_sources"]), self.theme,
                 font=self.theme.small_font(), fg=self.theme.muted, pady=(6, 0))
