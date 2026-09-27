"""
G2 - Independent demand baseline, one row per finished good.

Reads DimProduct only. Deliberately does NOT read DimCustomer, DimLocation,
BridgeProductLocation or any inventory artefact: demand is generated
independently of who buys it and of whether stock exists to serve it.

Output: data/generated/DemandBaseline.csv (100 rows)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sc_common import (SEED, SEASONALITY_BY_FAMILY, UNKNOWN_KEY,  # noqa: E402
                       WEEKDAY_PROFILES, load, sha256, write_csv)

rng = np.random.default_rng(SEED)

# Demand level by ABC class: lognormal(median, sigma) in units/working day.
LEVEL = {"A": (50.0, 0.45), "B": (14.0, 0.50), "C": (3.2, 0.60)}
# Coefficient of variation - slower movers are lumpier.
VOLATILITY = {"A": (0.25, 0.45), "B": (0.40, 0.65), "C": (0.60, 0.95)}
# Structural growth per year by family.
TREND = {
    "Energy Distribution Components": (0.00, 0.06),
    "Protection & Switching Devices": (0.01, 0.07),
    "Wiring Accessories": (-0.04, 0.03),
    "Cable Management Solutions": (-0.03, 0.04),
    "Building Automation Devices": (0.07, 0.14),
    "Energy Management Solutions": (0.06, 0.15),
    "Security & Access Solutions": (0.05, 0.12),
}
PROFILE_NAMES = list(WEEKDAY_PROFILES)
PROFILE_W = [0.50, 0.32, 0.18]


def main() -> None:
    prod = load("DimProduct")
    fg = prod[(prod["ProductType"] == "FinishedGood") & (prod["ProductKey"] != UNKNOWN_KEY)]
    fg = fg.sort_values("ProductKey")

    rows = []
    for pk, family, abc in zip(fg["ProductKey"], fg["ProductFamily"], fg["ABCClass"]):
        median, sigma = LEVEL[abc]
        base = float(rng.lognormal(mean=np.log(median), sigma=sigma))

        vlo, vhi = VOLATILITY[abc]
        volatility = float(rng.uniform(vlo, vhi))

        pattern = SEASONALITY_BY_FAMILY[family]
        amplitude = float(rng.uniform(0.03, 0.07) if pattern == "Flat"
                          else rng.uniform(0.12, 0.35))

        tlo, thi = TREND[family]
        trend = float(rng.uniform(tlo, thi))

        rows.append({
            "ProductKey": int(pk),
            "BaseDailyDemand": round(base, 3),
            "DemandVolatility": round(volatility, 4),
            "SeasonalityPattern": pattern,
            "SeasonalAmplitude": round(amplitude, 4),
            "TrendPerYear": round(trend, 4),
            "WeekdayProfile": str(rng.choice(PROFILE_NAMES, p=PROFILE_W)),
        })

    df = pd.DataFrame(rows)
    write_csv(df, "DemandBaseline.csv")
    print(f"G2 demand baseline - seed {SEED}")
    print(f"DemandBaseline.csv{len(df):>28}  {sha256('DemandBaseline.csv')[:16]}")


if __name__ == "__main__":
    main()
