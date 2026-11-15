"""The farmer's plots: what is known about each one, and saving them between runs.

No tkinter here, so it can be used and tested without a window.

    store = PlotStore()                 # loads databases/gui/plots.json, or starts with 5 plots
    store.add("North field", 3.5)       # up to MAX_PLOTS
    store.update(0, lat=42.065, lon=-93.73, last_rotation=["corn", "soybean"])

A plot's location is its latitude and longitude. The zip code is how the farmer found them
(gui/plot_view.py looks it up) and `place` is the name that came back, e.g. "Ames, Iowa (zip 50010)".
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from data_pullers._common import DATA_DIR, check_location
from data_pullers.US_ZipCode_pull import check_zip

DEFAULT_PLOTS = 5
MAX_PLOTS = 10
DEFAULT_SIZE_HA = 1.0
SAVE_PATH = DATA_DIR / "gui" / "plots.json"


@dataclass(frozen=True)
class Plot:
    name: str
    size_ha: float = DEFAULT_SIZE_HA
    lat: float | None = None
    lon: float | None = None
    last_rotation: tuple[str, ...] = ()      # crops grown most recently, oldest first
    zip_code: str = ""                       # US zip code the location was found from, if any
    place: str = ""                          # its name, e.g. "Ames, Iowa (zip 50010)"

    @property
    def located(self) -> bool:
        return self.lat is not None and self.lon is not None

    @property
    def last_crop(self) -> str | None:
        return self.last_rotation[-1] if self.last_rotation else None


def parse_size(value) -> float:
    """Plot size in hectares from what the farmer typed."""
    try:
        size = float(str(value).strip())
    except ValueError:
        raise ValueError(f"Plot size must be a number of hectares, got {value!r}.") from None
    if not 0 < size < float("inf"):
        raise ValueError(f"Plot size must be more than 0 hectares, got {value!r}.")
    return size


def parse_crops(text) -> tuple[str, ...]:
    """'corn, soybean' (or a list) -> ('corn', 'soybean')."""
    parts = text.split(",") if isinstance(text, str) else list(text or [])
    return tuple(p.strip() for p in parts if str(p).strip())


def _checked(plot: Plot) -> Plot:
    """The plot with its values validated and tidied, or ValueError with a plain message."""
    name = plot.name.strip()
    if not name:
        raise ValueError("A plot needs a name.")
    lat, lon = plot.lat, plot.lon
    if (lat in (None, "")) != (lon in (None, "")):
        raise ValueError("Enter both latitude and longitude, or leave both empty.")
    if lat in (None, ""):
        lat = lon = None
    else:
        lat, lon = check_location(lat, lon)
    zip_code = check_zip(plot.zip_code) if str(plot.zip_code or "").strip() else ""
    place = str(plot.place or "").strip() if zip_code else ""
    return Plot(name, parse_size(plot.size_ha), lat, lon, parse_crops(plot.last_rotation),
                zip_code, place)


@dataclass
class PlotStore:
    """The list of plots, saved to `path` after every change."""
    path: Path = SAVE_PATH
    plots: list[Plot] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.plots:
            self.plots = self._load() or [Plot(f"Plot {n}") for n in range(1, DEFAULT_PLOTS + 1)]

    def _load(self) -> list[Plot]:
        try:
            saved = json.loads(Path(self.path).read_text(encoding="utf-8"))
            return [_checked(Plot(**row)) for row in saved][:MAX_PLOTS]
        except (OSError, ValueError, TypeError):
            return []                       # no file yet, or one we cannot read: start fresh

    def save(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.path).write_text(json.dumps([asdict(p) for p in self.plots], indent=2), encoding="utf-8")

    @property
    def full(self) -> bool:
        return len(self.plots) >= MAX_PLOTS

    def next_name(self) -> str:
        taken = {p.name.lower() for p in self.plots}
        return next(f"Plot {n}" for n in range(1, MAX_PLOTS + 2) if f"plot {n}" not in taken)

    def add(self, name: str, size_ha=DEFAULT_SIZE_HA) -> Plot:
        if self.full:
            raise ValueError(f"You can have at most {MAX_PLOTS} plots.")
        plot = _checked(Plot(name, size_ha))
        if plot.name.lower() in {p.name.lower() for p in self.plots}:
            raise ValueError(f"There is already a plot called {plot.name!r}.")
        self.plots.append(plot)
        self.save()
        return plot

    def update(self, index: int, **changes) -> Plot:
        """Change some of a plot's details (name, size_ha, lat, lon, last_rotation, zip_code,
        place)."""
        plot = _checked(replace(self.plots[index], **changes))
        others = {p.name.lower() for i, p in enumerate(self.plots) if i != index}
        if plot.name.lower() in others:
            raise ValueError(f"There is already a plot called {plot.name!r}.")
        self.plots[index] = plot
        self.save()
        return plot
