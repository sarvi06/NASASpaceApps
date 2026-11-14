"""Pull every no-login dataset for the test field, save CSVs, and print a summary.

Run from the repo root:
    .venv\\Scripts\\python.exe source\\pull_test_field.py
"""

from data_pull.config import DATA_DIR, TEST_FIELD
from data_pull.cropscape import fetch_crop_history
from data_pull.power import fetch_power_daily
from data_pull.soils import fetch_soil_at_point


def main() -> None:
    field = TEST_FIELD
    out_dir = DATA_DIR / field.name
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Test field: {field.name} ({field.lat}, {field.lon})\n")

    # 1. Climate (NASA POWER), 10 years of daily data
    print("[1/3] NASA POWER climate ...")
    climate = fetch_power_daily(field.lat, field.lon, "20150101", "20241231")
    climate.to_csv(out_dir / "power_daily.csv")
    yearly = climate.groupby(climate.index.year).agg(
        mean_temp_c=("T2M", "mean"),
        rain_mm=("PRECTOTCORR", "sum"),
        frost_days=("T2M_MIN", lambda s: int((s < 0).sum())),
        hot_days_over_32c=("T2M_MAX", lambda s: int((s > 32).sum())),
        mean_root_wetness=("GWETROOT", "mean"),
    ).round(2)
    print(f"      {len(climate)} days saved. Yearly summary:")
    print(yearly.to_string(), "\n")

    # 2. Crop history (USDA CDL via CropScape)
    print("[2/3] CropScape crop history ...")
    crops = fetch_crop_history(field.lat, field.lon, range(2008, 2026))
    crops.to_csv(out_dir / "cdl_history.csv", index=False)
    ok = crops[crops["error"].isna()]
    print(f"      {len(ok)}/{len(crops)} years retrieved:")
    print("      " + " -> ".join(f"{r.year}:{r.crop}" for r in ok.itertuples()))
    for r in crops[crops["error"].notna()].itertuples():
        print(f"      {r.year}: FAILED ({r.error[:80]})")
    print()

    # 3. Soil (USDA SSURGO via Soil Data Access)
    print("[3/3] SSURGO soil ...")
    soil = fetch_soil_at_point(field.lat, field.lon)
    soil.to_csv(out_dir / "ssurgo_soil.csv", index=False)
    print(f"      {len(soil)} soil components in map unit:")
    cols = ["compname", "comppct_r", "hydgrp", "drainagecl", "slope_r",
            "om_r", "claytotal_r", "awc_r", "kwfact"]
    print(soil[cols].to_string(index=False), "\n")

    print(f"Saved CSVs to: {out_dir}")


if __name__ == "__main__":
    main()
