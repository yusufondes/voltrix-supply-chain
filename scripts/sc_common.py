"""Shared constants and helpers for the Voltrix synthetic supply chain pipeline."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20250920
DATE_START = "2024-01-01"
DATE_END = "2025-12-31"        # transaction horizon
CALENDAR_END = "2026-12-31"   # DimDate extent - forward-looking fact dates resolve here
UNKNOWN_KEY = -1

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "data" / "generated"
PROFILE = ROOT / "data" / "validation"
DOCS = ROOT / "docs"

# --------------------------------------------------------------------------
# Seasonality - raw monthly shapes (Jan..Dec). Centred to mean 0 and scaled to
# max |x| = 1 by seasonal_shape(), then applied as 1 + amplitude * shape[month].
# --------------------------------------------------------------------------
SEASONALITY_RAW = {
    "ConstructionPeak": [-0.5, -0.4, -0.1, 0.1, 0.3, 0.4, 0.0, -1.0, 0.7, 1.0, 0.8, 0.2],
    "RetrofitSpring": [-0.6, -0.4, 0.4, 0.8, 1.0, 0.7, 0.1, -0.9, -0.2, 0.2, 0.0, -0.5],
    "YearEndBudget": [-0.7, -0.6, -0.4, -0.3, -0.2, 0.0, 0.1, -0.8, 0.2, 0.5, 1.0, 0.9],
    "Flat": [0.10, -0.10, 0.05, -0.05, 0.10, -0.10, 0.0, -0.20, 0.05, 0.10, -0.05, 0.10],
}

SEASONALITY_BY_FAMILY = {
    "Energy Distribution Components": "ConstructionPeak",
    "Protection & Switching Devices": "ConstructionPeak",
    "Wiring Accessories": "RetrofitSpring",
    "Cable Management Solutions": "RetrofitSpring",
    "Building Automation Devices": "YearEndBudget",
    "Energy Management Solutions": "YearEndBudget",
    "Security & Access Solutions": "Flat",
}

# Mon..Sun multipliers. B2B ordering is weekdays only.
WEEKDAY_PROFILES = {
    "StandardB2B": [1.15, 1.10, 1.05, 1.00, 0.80, 0.0, 0.0],
    "MidweekHeavy": [0.95, 1.15, 1.20, 1.10, 0.75, 0.0, 0.0],
    "EarlyWeek": [1.30, 1.20, 0.95, 0.85, 0.70, 0.0, 0.0],
}


def seasonal_shape(pattern: str) -> np.ndarray:
    raw = np.array(SEASONALITY_RAW[pattern], dtype=float)
    centred = raw - raw.mean()
    return centred / np.abs(centred).max()


def seasonal_factor(pattern: str, amplitude: float, month: np.ndarray) -> np.ndarray:
    """month is 1..12"""
    return 1.0 + amplitude * seasonal_shape(pattern)[month - 1]


def trend_factor(trend_per_year: float, day_index: np.ndarray, days_total: int) -> np.ndarray:
    """Linear trend, +/- trend_per_year applied pro rata over the horizon."""
    return 1.0 + trend_per_year * (day_index / 365.0)


# --------------------------------------------------------------------------
# Material requirements planning (MRP) - shared by G4 (buys) and G5 (consumes).
#
# Materials are dependent demand. The buyer (G4) explodes the master production
# schedule (master_schedule, below) through the bill of materials
# (BomProductMaterial): every planned production order for Q units of a product
# draws ceil(Q x QtyPerUnit) of each of its materials on the day it is planned.
# The buyer sees planned orders as they are raised and projects the next ones
# from each product's position and plan rate; it never sees actual inventory,
# production or shipments (G5 output), so late, short or rejected receipts are
# not anticipated - they surface later as material shortages in production.
#
#   plan rate       sum over drawing products of planned rate x QtyPerUnit
#   safety stock    base cover + z x sqrt(L x sd_draw^2 + rate^2 x sd_L^2): the
#                   textbook safety stock for variable demand over a variable lead
#                   time. sd_draw is the day-to-day spread of the scheduled kit
#                   draws (production draws materials in lumps), sd_L the primary
#                   supplier's lead-time standard deviation, L its promised lead
#   order rule      order when on hand + open purchase quantity - the draws
#                   projected over (lead + safety) falls below safety stock
#   order qty       plan rate x cycle days, at least MinOrderQty and at least the
#                   deficit, rounded up to the material's order scale
#
# Where production runs and draws materials: each plant produces its own stock;
# the Southern-region warehouses (Zaragoza, Bologna) are replenished from the
# Lyon plant, the nearest one; the distribution centre and the other warehouses
# are replenished from the primary hub (Rhein-Neckar). A run draws each material
# from its production plant if that plant holds it, otherwise from the hub.
# --------------------------------------------------------------------------
# Make-to-stock production lead: release -> finished stock available (G5), also
# the nominal lead G8 uses to decide whether a run could have arrived in time.
FG_PROD_LEAD = {"A": 14, "B": 21, "C": 28}
MATERIAL_SAFETY_BASE_DAYS = 3
MATERIAL_SAFETY_Z = 0.3           # lean component policy: with the base cover, 5-15 days of safety stock
CYCLE_TARGET_DAYS = {"A": 4, "B": 8, "C": 12}


def material_sites(bridge: pd.DataFrame, prod: pd.DataFrame) -> set[tuple[int, int]]:
    """(material, site) pairs that hold material stock."""
    mt = set(prod.loc[prod["ProductType"] == "Material", "ProductKey"].astype(int))
    return {(int(p), int(l)) for p, l in zip(bridge["ProductKey"], bridge["LocationKey"]) if int(p) in mt}


def primary_hub(loc: pd.DataFrame) -> int:
    hub = loc[loc["IsPrimaryHub"].astype(str).str.upper() == "TRUE"]["LocationKey"]
    return int(hub.iloc[0])


def production_sites(loc: pd.DataFrame) -> dict[int, int]:
    """Location -> plant that produces its stock."""
    real = loc[loc["LocationKey"] != UNKNOWN_KEY]
    plant = real["IsManufacturingSite"].astype(str).str.upper() == "TRUE"
    hub = primary_hub(loc)
    south_plant = int(real.loc[plant & (real["LocationKey"] != hub), "LocationKey"].iloc[0])
    out = {}
    for lk, is_plant, region in zip(real["LocationKey"], plant, real["Region"]):
        out[int(lk)] = int(lk) if is_plant else (south_plant if region == "Southern" else hub)
    return out


def draw_site(fg_location: int, material: int, held: set[tuple[int, int]],
              site_of: dict[int, int], hub: int) -> int:
    """Site whose material stock a production run for fg_location draws on."""
    site = site_of[fg_location]
    return site if (material, site) in held else hub


def load_bom() -> dict[int, list[tuple[int, float]]]:
    bom = pd.read_csv(GEN / "BomProductMaterial.csv")
    out: dict[int, list[tuple[int, float]]] = {}
    for pk, mk, q in zip(bom["ProductKey"], bom["MaterialKey"], bom["QtyPerUnit"]):
        out.setdefault(int(pk), []).append((int(mk), float(q)))
    return out


def kit_qty(lot: float, qty_per_unit: float) -> int:
    return int(np.ceil(lot * qty_per_unit - 1e-9))


def material_order_qty(rate: float, moq: int, scale: int, abc: str, deficit: float = 0.0) -> int:
    q = max(float(moq), rate * CYCLE_TARGET_DAYS[abc], deficit)
    return int(np.ceil(q / scale) * scale)


def material_plan(prod: pd.DataFrame, sup: pd.DataFrame, loc: pd.DataFrame, bridge: pd.DataFrame,
                  bom: dict[int, list[tuple[int, float]]], plans: dict[tuple[int, int], dict],
                  mps: dict[tuple[int, int], dict], n_days: int) -> dict[tuple[int, int], dict]:
    """Per (material, site): drawing products, plan rate, safety stock, the MPS kit
    draws by day and the opening stock (safety stock + the draws scheduled inside
    the first quoted lead time, before any purchase order can land)."""
    held = material_sites(bridge, prod)
    site_of = production_sites(loc)
    hub = primary_hub(loc)
    p = prod.set_index("ProductKey")
    s = sup.set_index("SupplierKey")
    out = {k: {"users": [], "rate": 0.0, "draws": np.zeros(n_days + 1)} for k in sorted(held)}
    for (pk, lk), pl in plans.items():
        for mk, q in bom.get(pk, []):
            site = draw_site(lk, mk, held, site_of, hub)
            m = out[(mk, site)]
            m["users"].append(((pk, lk), q))
            m["rate"] += pl["planned"] * q
            for d, lot in mps[(pk, lk)]["orders"]:
                m["draws"][d] += kit_qty(lot, q)
    for (mk, site), m in out.items():
        prim = int(p.loc[mk, "PrimarySupplierKey"])
        m["lead"] = float(s.loc[prim, "PromisedLeadTimeDays"])
        sd_lead = float(s.loc[prim, "LeadTimeStdDevDays"])
        sd_draw = float(np.std(m["draws"][:n_days]))
        m["ss"] = (m["rate"] * MATERIAL_SAFETY_BASE_DAYS
                   + MATERIAL_SAFETY_Z * np.sqrt(m["lead"] * sd_draw ** 2 + (m["rate"] * sd_lead) ** 2))
        m["safety_days"] = m["ss"] / m["rate"] if m["rate"] > 0 else 0.0
        m["rop"] = m["rate"] * (m["lead"] + m["safety_days"])
        # quoted lead = promised + two standard deviations (the most a buyer is quoted)
        m["opening"] = m["ss"] + m["draws"][: int(np.ceil(m["lead"] + 2 * sd_lead)) + 1].sum()
    return out


def projected_draws(m: dict, plans: dict[tuple[int, int], dict], mps: dict[tuple[int, int], dict],
                    d: int, horizon: float) -> float:
    """Kit draws the buyer expects in (d, d + horizon]: for each drawing product,
    the days its position (end of day d) will cross the reorder point at plan
    rate, then one further order every lot / rate days."""
    total = 0.0
    for key, q in m["users"]:
        pl = plans[key]
        if pl["planned"] <= 0 or pl["lot"] <= 0:
            continue
        first = max(1.0, np.ceil((mps[key]["position"][d] - pl["rop"]) / pl["planned"]))
        if first > horizon:
            continue
        n = int((horizon - first) // (pl["lot"] / pl["planned"])) + 1
        total += n * kit_qty(pl["lot"], q)
    return total


# --------------------------------------------------------------------------
# Finished-goods replenishment plan - shared by G4 (master production schedule)
# and G5 (execution), so the schedule the buyer plans materials against is built
# from exactly the rule the plant runs.
#
# Replenishment is sized from the ROUTINE demand observed at each Product x
# Location pair (lines above the pair's 98th-percentile line size are treated as
# exceptional project demand and trimmed), NOT from DimProduct.ReorderPoint - the
# G1 reorder point is a product-level attribute with no per-location demand
# knowledge. Each pair carries a persistent forecast bias (lognormal, sigma
# FORECAST_BIAS_SIGMA): some SKUs are chronically under-planned, others
# over-planned - the ordinary cause of both stockouts and excess stock.
#
#   reorder point   planned rate x (production lead + safety days)
#   lot             planned rate x cover days, rounded to the order scale
# --------------------------------------------------------------------------
FG_COVER_DAYS = {"A": 80, "B": 100, "C": 130}  # production lot (campaign) = this many days of cover
FG_SAFETY_DAYS = {"A": 14, "B": 18, "C": 22}   # 2-3 weeks of cover above production lead at the trigger
FORECAST_BIAS_SIGMA = 0.15
ROUTINE_WINSOR_PCT = 0.98
SHORT_CLOSE_DAYS = 14   # customer cancels the undelivered remainder this far past the requested date
FG_PLAN_STREAM = 51


def fg_plans(so: pd.DataFrame, prod: pd.DataFrame, bridge: pd.DataFrame,
             n_days: int) -> dict[tuple[int, int], dict]:
    """Planning parameters and opening stock per finished-goods Product x Location."""
    def routine(q: pd.Series) -> float:
        cap = q.quantile(ROUTINE_WINSOR_PCT) if len(q) >= 10 else q.max()
        return float(q.clip(upper=cap).sum()) / n_days

    rate = so.groupby(["ProductKey", "LocationKey"])["OrderedQuantity"].apply(routine).to_dict()
    p = prod.set_index("ProductKey")
    out = {}
    for pk, lk in sorted((int(a), int(b)) for a, b in zip(bridge["ProductKey"], bridge["LocationKey"])):
        if p.loc[pk, "ProductType"] != "FinishedGood":
            continue
        r = np.random.default_rng([SEED, FG_PLAN_STREAM, pk, lk])
        abc, scale = p.loc[pk, "ABCClass"], int(p.loc[pk, "TypicalOrderQtyScale"])
        lead = FG_PROD_LEAD[abc]
        rt = float(rate.get((pk, lk), 0.0))
        planned = rt * float(r.lognormal(0.0, FORECAST_BIAS_SIGMA))
        rop = planned * (lead + FG_SAFETY_DAYS[abc])
        lot = int(max(scale, round(planned * FG_COVER_DAYS[abc] / scale) * scale)) if rt > 0 else 0
        stock0 = (int(round(rop * r.uniform(0.7, 1.3))) if rt > 0
                  else int(round(max(scale, float(p.loc[pk, "ReorderPoint"]) * 0.15))))
        out[(pk, lk)] = {"planned": planned, "rop": rop, "lot": lot, "stock0": stock0, "lead": lead}
    return out


def master_schedule(so: pd.DataFrame, plans: dict[tuple[int, int], dict],
                    n_days: int) -> dict[tuple[int, int], dict]:
    """Master production schedule: the order book replayed, day by day, against each
    pair's replenishment rule - demand ships as soon as stock allows (remainders
    cancelled SHORT_CLOSE_DAYS past the requested date), a production order is
    planned whenever stock + on order falls below the reorder point, and it lands
    one production lead later. Causal: day d uses only orders entered by day d.

    Returns per pair: 'position' (stock + on order, end of each day) and
    'orders' [(day, lot)] - the planned production orders and their kit draw days.
    """
    start = pd.Timestamp(DATE_START)
    od = (pd.to_datetime(so["OrderDate"]) - start).dt.days.to_numpy()
    rq = (pd.to_datetime(so["RequestedDeliveryDate"]) - start).dt.days.to_numpy()
    book: dict[tuple[int, int], list] = {}
    for d, r_, pk, lk, q in zip(od, rq, so["ProductKey"].to_numpy(), so["LocationKey"].to_numpy(),
                                so["OrderedQuantity"].to_numpy()):
        book.setdefault((int(pk), int(lk)), []).append((int(d), int(r_), int(q)))
    out = {}
    for key, pl in plans.items():
        lines = sorted(book.get(key, []))
        stock, arrivals, queue, ptr = pl["stock0"], {}, [], 0
        pos = np.zeros(n_days)
        orders = []
        for d in range(n_days):
            stock += arrivals.pop(d, 0)
            while ptr < len(lines) and lines[ptr][0] <= d:
                queue.append([lines[ptr][1], lines[ptr][2]])
                ptr += 1
            queue = [x for x in queue if d <= x[0] + SHORT_CLOSE_DAYS]
            for x in queue:
                if stock <= 0:
                    break
                take = min(stock, x[1])
                stock -= take
                x[1] -= take
            queue = [x for x in queue if x[1] > 0]
            on_order = sum(arrivals.values())
            if pl["lot"] > 0 and stock + on_order < pl["rop"]:
                arrivals[d + pl["lead"]] = arrivals.get(d + pl["lead"], 0) + pl["lot"]
                orders.append((d, pl["lot"]))
                on_order += pl["lot"]
            pos[d] = stock + on_order
        out[key] = {"position": pos, "orders": orders}
    return out


def replenishment_twin(lines: list[tuple[int, int, int, int]], plan: dict, delays: list[int],
                       n_days: int, pick_days: int = 1) -> dict[int, int]:
    """Deterministic twin of one finished-goods pair's replenishment loop, used to
    ask "but for these production delays, would this line have shipped on time?".

    lines   [(order day, requested day, qty, line key)]
    delays  extra days before the k-th production order lands (kit wait + slip),
            in trigger order; orders beyond the list land after the nominal lead
    Stock ships FIFO once a line is pick_days old; remainders are cancelled
    SHORT_CLOSE_DAYS past the requested date; a production order is raised when
    stock + on order falls below the reorder point. Returns line key -> day the
    line was complete (lines never completed are absent).
    """
    stock, arrivals, queue, ptr, k = plan["stock0"], {}, [], 0, 0
    lines = sorted(lines)
    done: dict[int, int] = {}
    on_order = 0
    for d in range(n_days):
        got = arrivals.pop(d, 0)
        stock += got
        on_order -= got
        while ptr < len(lines) and lines[ptr][0] <= d:
            o, r_, q, key = lines[ptr]
            queue.append([o, r_, q, key])
            ptr += 1
        queue = [x for x in queue if d <= x[1] + SHORT_CLOSE_DAYS]
        for x in queue:
            if stock <= 0:
                break
            if d < x[0] + pick_days:
                continue
            take = min(stock, x[2])
            stock -= take
            x[2] -= take
            if x[2] == 0:
                done[x[3]] = d
        queue = [x for x in queue if x[2] > 0]
        if plan["lot"] > 0 and stock + on_order < plan["rop"]:
            land = d + plan["lead"] + (delays[k] if k < len(delays) else 0)
            arrivals[land] = arrivals.get(land, 0) + plan["lot"]
            on_order += plan["lot"]
            k += 1
    return done


def load(name: str) -> pd.DataFrame:
    return pd.read_csv(GEN / f"{name}.csv", keep_default_na=False, na_values=[])


def write_csv(df: pd.DataFrame, name: str, float_format: str = "%.4f") -> None:
    GEN.mkdir(parents=True, exist_ok=True)
    df.to_csv(GEN / name, index=False, lineterminator="\n",
              encoding="utf-8", float_format=float_format)


def sha256(name: str) -> str:
    return hashlib.sha256((GEN / name).read_bytes()).hexdigest()


class Checks:
    """Collects PASS/FAIL results for a validation script."""

    def __init__(self, title: str) -> None:
        self.title = title
        self.rows: list[tuple[str, str, bool, str]] = []

    def add(self, cid: str, name: str, ok: bool, detail: str = "") -> None:
        self.rows.append((cid, name, bool(ok), detail))

    def report(self, out_name: str) -> int:
        width = max(len(n) for _, n, _, _ in self.rows)
        lines = [self.title, ""]
        for cid, name, ok, detail in self.rows:
            line = f"[{'PASS' if ok else 'FAIL'}] {cid:>2}. {name:<{width}}  {detail}"
            print(line)
            lines.append(line)
        failed = [c for c, _, ok, _ in self.rows if not ok]
        verdict = (f"\n{len(self.rows) - len(failed)}/{len(self.rows)} criteria passed"
                   + (f" - FAILED: {', '.join(failed)}" if failed else " - ALL PASS"))
        print(verdict)
        lines.append(verdict)
        PROFILE.mkdir(parents=True, exist_ok=True)
        (PROFILE / out_name).write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 1 if failed else 0
