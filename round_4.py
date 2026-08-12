# Round 4, voucher risk-hardening research candidate.
# Built on top of the FROZEN Hydro v2 + VELVET M4 candidate. Both legs are
# preserved exactly. Vouchers keep the old M0 z-score engine by default, with
# targeted risk-hardening modes controlled by VOUCHER_RISK.
#
# Voucher risk modes:
#   M0_control                 frozen M0 z-score, unchanged.
#   M1_diagnostics_only        same orders as M0, diagnostics only.
#   M2_upper_long_cap_250      cap positive 5400/5500 inventory at +250.
#   M3_upper_long_cap_200      cap positive 5400/5500 inventory at +200.
#   M4_5400_only_cap           cap positive 5400 only, cap from config.
#   M5_5500_only_cap           cap positive 5500 only, cap from config.
#   M6_terminal_upper_reduction late-day upper buy block when BS edge is weak.
#   M7_extreme_BS_veto_upper   rare upper buy veto when BS says overpriced.
#   M8_extreme_BS_veto_all     same veto across vouchers, diagnostic control.
#   M9_net_delta_soft_cap      z-score with a soft voucher-delta order clip.
#   M10_selective_combined     upper cap plus rare BS veto; optional net cap.
#
# All modes share:
#   - one TTE helper get_tte_days(day, timestamp) returning calendar days,
#     using the documented (8 - day) - ts/1e6 roll-down (public day 1 -> 7
#     calendar days, final-sim day 4 -> 4 calendar days). Floored at 0.5d.
#   - live ATM-IV calibration from central strike mids, with strict validity
#     gates and an EMA on a single sigma. Fallback to the conservative default
#     0.24 (research mid-point) when fewer than 2 strikes are live.
#   - delta ledger: net_delta = velvet_pos + sum(voucher_pos[k] * BS_delta[k]).
#   - strike-bucket caps (deep_itm, central, upper, far) read from
#     VOUCHER_BS["bucket_cap_*"]. Hard product limit 300 per voucher always.
#
# All numbers are tunable via VOUCHER_BS / VOUCHER_OVERLAY config; M0 is the
# default so a no-op replay matches the frozen Hydro+VELVET candidate exactly.
# r4_hydro_velvet_m4_candidate.py stays frozen; r4_trader.py is the submission copy.
#
# Anti-anchor design (vs. rejected v1):
#   - Welford-style adaptive alpha (1/(n+1)) during warm-up so the slow EMA is
#     dominated by live mids within the first few hundred ticks. The seed value
#     (warm_start, first_mid, median) becomes irrelevant within ~1k ticks.
#   - warm_start_weight default lowered from 0.75 to 0.25 *with* additional
#     decay-to-zero schedule on top of the Welford adaptation.
#   - Multiple warm-start modes (first_mid, blend_10, blend_25, median_early,
#     control_75) selectable via HYDRO_PARAMS["warm_start_mode"] for ablation.
#   - Mean-shift guard rewritten to a *live-only* regime detector:
#       (a) abs(fast_ema - slow_ema) gap, plus
#       (b) persistent abs(mid - slow_ema) over a small bounded window, plus
#       (c) drift EMA magnitude.
#     No comparison to the public 9995 anchor anywhere in the production path.
#   - spread > 16 lean disabled by default (kept as opt-in feature flag).
#   - Mark22 is a test-only feature flag, default disabled. No timestamp,
#     bot-name or sequence logic is used.

## IMPORTS ##  ## IMPORTS ##  ## IMPORTS ##  ## IMPORTS ##  ## IMPORTS ##
try:
    from datamodel import OrderDepth, UserId, TradingState, Order
except ImportError:
    from prosperity_backtester.datamodel import OrderDepth, UserId, TradingState, Order
import math
import json

## GENERAL ##  ## GENERAL ##  ## GENERAL ##  ## GENERAL ##  ## GENERAL ##
POS_LIMITS = {
        "HYDROGEL_PACK": 200,
        "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000": 300,
        "VEV_4500": 300,
        "VEV_5000": 300,
        "VEV_5100": 300,
        "VEV_5200": 300,
        "VEV_5300": 300,
        "VEV_5400": 300,
        "VEV_5500": 300,
        "VEV_6000": 300,
        "VEV_6500": 300
}

PARAMS = {
    "EMA_ALPHA":         0.0002,
    "INITIAL_HYDRO_EMA": 9991,
    "ZSCORE_ENTRY":      1.5,
    # None = full baseline (+/-200 hard cap). Integers 150 and 100 are the
    # documented reduced-baseline fallbacks. Active candidate default = None
    # (full baseline + M4 overlay).
    "VELVET_BASELINE_CAP": None,
}

THRESHOLD_RESCUE = {
    "mode": "cap_safe",  # off / rejected_reference / cap_safe / delta_add_gated / combined / selective
    "thresholds": {
        "VEV_4000": 1.75,
        "VEV_4500": 1.75,
        "VEV_5100": 1.00,
    },
    "base_threshold": 1.5,
    "cap_near": 250,
    "strict_cap_near": 225,
    "strict_products": ("VEV_4000", "VEV_4500", "VEV_5100"),
    "delta_block_abs": 1600.0,
    "delta_strong_abs": 1400.0,
    "delta_strong_margin": 0.25,
}

# All HYDROGEL knobs live here. No magic constants in the trade function.
HYDRO_PARAMS = {
    # Top-level feature flags
    "enabled": True,
    "passive_enabled": True,
    "imbalance_enabled": True,
    "spread_lean_enabled": False,         # spread>16 lean: barely mattered, off by default
    "spread_shift_enabled": True,
    "large_dev_enabled": True,
    "mark22_enabled": False,              # test-only; default disabled

    # EMAs
    "ema_alpha": 0.0002,                  # main slow EMA alpha (post-warmup)
    "fast_ema_alpha": 0.01,
    "warmup_alpha_floor_ticks": 800,      # 1/(n+1) Welford alpha for first N ticks

    # Warm-start (de-anchored)
    # Modes: "first_mid", "blend_10", "blend_25", "median_early", "control_75"
    "warm_start_mode": "blend_25",
    "warm_start": 9995.0,
    "warm_start_weight": 0.25,            # used by blend_* modes; default 0.25 (was 0.75)
    "warm_start_decay_ticks": 600,        # extra anchor decay on top of Welford
    "median_warmup_ticks": 50,            # bounded window for median_early mode

    "warmup_ticks": 300,                  # for size-scale only, no anchor reference

    # L1+L2 imbalance
    "imb_trigger": 0.20,
    "imb_lean_ticks": 8.0,
    "imb_lean_max": 3.0,

    # Spread leans
    "spread_bear_lean": 0.50,
    "spread_lean_max": 1.0,

    # Targets
    "target_slope": 3.25,
    "target_max": 190,

    # Large-deviation crossing
    "large_dev": 45.0,
    "large_dev_imb_agree": 38.0,
    "large_dev_conflict": 58.0,
    "spread_shift_dev": 5.0,

    "cross_edge": 1.0,
    "passive_min_edge": 1.5,
    "base_order_size": 8,
    "strong_order_size": 28,
    "passive_order_size": 6,

    # Inventory caps
    "soft_limit": 175,
    "stop_add_level": 195,

    # Live drift-aware fair adjustment
    "drift_reduce_ticks": 55.0,
    "drift_fair_threshold": 35.0,
    "drift_fair_blend": 0.50,
    "drift_fair_max": 45.0,

    # Live regime detector (replaces v1 mean_shift_guard that referenced 9995)
    "live_regime_fast_slow_ticks": 60.0,  # |fast_ema - slow_ema| trigger
    "live_regime_persist_ticks": 70.0,    # |mid - slow_ema| persistence trigger
    "live_regime_persist_window": 50,     # bounded ring length
    "live_regime_persist_frac": 0.50,     # fraction of window above threshold
    "live_regime_blend": 0.65,            # how much to pull fair toward fast_ema
    "live_regime_size_scale": 0.55,
}


# ---------------------------------------------------------------------------
# VELVET overlay configuration. Active default is "premium_overlay": keep the
# baseline z-score VELVET leg and add a small premium-cross overlay. Other
# modes are retained for documented ablation overrides only.
# Phase 1 measured premium-bullish fwd5 ~ +2.1, cost-adjusted ~ +1.6 across
# all three days. Broad is a fair-lean only (cost-adj ~ +0.7) and is never a
# crossing trigger here. Bearish is never a cross-short.
VELVET_OVERLAY = {
    "mode": "premium_overlay",
    # Compression triggers (Phase 1 definitions, abs() applied to volumes).
    "premium_spread": 1,
    "premium_ask_vol": 15,
    "broad_spread_max": 2,
    "broad_ask_vol": 15,

    # Premium cross overlay sizing - single small default; not constant-fished.
    "overlay_size": 8,
    "overlay_soft_cap_long": 100,   # well below hard 200, leaves voucher delta room
    "overlay_short_reduction_priority": True,

    # Mark49 fade gate window (counts ticks since the last Mark 49 sell).
    "mark49_window_ticks": 5,
    # Mark67 modifier (only active in name-modifier mode).
    "mark67_size_bonus": 4,
    "mark67_window_ticks": 5,

    # Name ablation knob: "normal" / "shuffled" / "sign_flipped".
    "name_mode": "normal",
    # Per-name kill switches (used by name ablation matrix).
    "use_mark67": True,
    "use_mark49": True,
}


# ---------------------------------------------------------------------------
# VOUCHER BS/IV research module config. The active mode in this file is
# "M0_old_zscore" so that a stock replay matches the frozen Hydro+VELVET M4
# candidate exactly. The ablation harness flips VOUCHER_OVERLAY["mode"] (or
# the JSON env override below) to test other modes.
VOUCHER_OVERLAY = {
    "mode": "M0_old_zscore",
    # If True the BS module computes IV/fair/delta state every tick even in
    # M0/M1 so dashboards/diagnostics get the same trace. The trader function
    # still respects the active mode for actual order generation. Cheap
    # (constant-time math per strike per tick).
    "always_compute_state": True,
}

VOUCHER_RISK = {
    "mode": "M3_upper_long_cap_200",
    "upper_long_cap": 250,
    "terminal_fraction": 0.85,
    "terminal_min_buy_edge": 1.0,
    "bs_veto_edge": 8.0,
    "net_delta_cap": 1100,
    "net_delta_priority": [5500, 5400, 5300, 4000, 4500, 5200, 5100, 5000],
    "combined_use_net_delta": False,
}

VOUCHER_BS = {
    # ---- TTE -------------------------------------------------------------
    # Documented public-day roll-down: day 1 -> 7d, day 2 -> 6d, day 3 -> 5d.
    # Final-sim 4-day TTE matches if the simulator passes day=4.
    # Formula: tte_days = (offset - day) - timestamp/1e6, floored at floor_days.
    "tte_offset_days": 8.0,
    "tte_floor_days": 0.5,
    # Public replay starts at day 1 and increments when timestamp resets.
    # If a future BS-trading submission runs a single official final day with
    # no day field, set this to 4 before promotion.
    "initial_day_index": 1,

    # ---- IV calibration --------------------------------------------------
    # Central strikes used for the live IV anchor.
    "central_strikes": [5000, 5100, 5200, 5300],
    # IV bounds for "valid" per-strike implied vols.
    "iv_floor": 0.05,
    "iv_cap":   1.00,
    # Conservative fallback sigma when too few central strikes give a valid
    # IV in the current tick. Research midpoint of 7/6/5 ATM IV (~0.24).
    "fallback_sigma": 0.24,
    # EMA on the live sigma (slow). 1/(N+1) Welford warm-up for first
    # warmup_alpha_floor_ticks ticks.
    "sigma_ema_alpha": 0.02,
    "sigma_warmup_ticks": 200,
    # Min number of valid central strikes required to update sigma this tick.
    "min_valid_strikes": 2,
    # Max wide-spread for a strike to be considered for sigma calibration.
    "max_calib_spread": 8,

    # ---- Edge thresholds (price-space, after-cost) -----------------------
    # cross_buy condition:  ask < BS_fair - cross_buy_edge
    # cross_sell condition: bid > BS_fair + cross_sell_edge
    "cross_buy_edge":  1.5,
    "cross_sell_edge": 1.5,
    # passive maker; place if mid_residual >= passive_min_edge AND book is
    # wide enough.
    "passive_min_edge": 1.0,
    "passive_min_spread": 3,
    # Soft minimum vol-of-residual; below this we trust the smile less.
    # We only allow trading if abs(price_residual) > k * residual_floor.
    "residual_floor": 0.7,
    "residual_floor_mult": 1.0,

    # ---- Sizing ----------------------------------------------------------
    "base_order_size": 8,
    "max_order_size":  30,
    "passive_order_size": 5,
    # Cautious 5400 buy-only sizing.
    "edge_5400_buy_size":     12,
    "edge_5400_buy_threshold": 1.0,   # extra mispricing required vs. central edge
    "edge_5400_min_spread_room": 0,    # always crossable when spread<=2

    # ---- Per-strike enable/disable ---------------------------------------
    "include_5000": True,
    "include_5100": True,
    "include_5200": True,
    "include_5300": True,    # cautious; disabled when residual too small
    "include_5400_buy_only": False,    # enabled in M5/M6
    "deep_itm_enabled": False,         # 4000/4500 disabled by default
    "far_otm_enabled":  False,         # 6000/6500 disabled by default

    # ---- Bucket caps (per-bucket sum of |voucher_position|) -------------
    "bucket_cap_central": 600,         # sum across 5000/5100/5200(/5300)
    "bucket_cap_upper":   300,         # sum across 5400/5500
    "bucket_cap_deep":    0,           # 4000/4500 disabled
    "bucket_cap_far":     0,           # 6000/6500 disabled

    # ---- Net portfolio delta cap (VELVET-equivalent units) ---------------
    # Applied in M6 only.
    "net_delta_cap": 500,

    # ---- Old z-score gate (M4/M7) ---------------------------------------
    # Drop a z-score order if it disagrees with BS by more than gate_edge in
    # price space. e.g. z-score wants to SELL but BS_fair > mid + gate_edge
    # (i.e. BS thinks it's cheap), drop the sell.
    "gate_edge": 1.5,
    # M7 z-score size shrink factor.
    "zscore_shrink": 0.5,

    # ---- Diagnostics -----------------------------------------------------
    # If True, the trader records small per-strike fair/delta scalars in
    # pstate so dashboards can attribute. Bounded to a constant-size dict.
    "emit_diagnostics": True,
}

# Strikes the BS module actively considers (excluding 6000/6500 which trade
# at near-zero and are explicitly out of scope this phase).
_BS_STRIKE_LIST = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500]
_BS_BUCKET_OF = {
    4000: "deep", 4500: "deep",
    5000: "central", 5100: "central", 5200: "central", 5300: "central",
    5400: "upper",  5500: "upper",
    6000: "far",    6500: "far",
}


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def get_best_bid_ask(order_depth):
    if not order_depth.buy_orders or not order_depth.sell_orders:
        return None, 0, None, 0
    best_bid = max(order_depth.buy_orders)
    best_ask = min(order_depth.sell_orders)
    bid_qty = max(0, int(order_depth.buy_orders.get(best_bid, 0)))
    ask_qty = max(0, abs(int(order_depth.sell_orders.get(best_ask, 0))))
    if bid_qty <= 0 or ask_qty <= 0:
        return None, 0, None, 0
    return best_bid, bid_qty, best_ask, ask_qty


def get_mid(order_depth):
    best_bid, _, best_ask, _ = get_best_bid_ask(order_depth)
    if best_bid is None or best_ask is None:
        return None
    return (best_bid + best_ask) / 2.0


def get_l1_l2_depths(order_depth):
    bid_levels = sorted(order_depth.buy_orders.items(), reverse=True)[:2]
    ask_levels = sorted(order_depth.sell_orders.items())[:2]
    bid_l1_qty = abs(int(bid_levels[0][1])) if len(bid_levels) >= 1 else 0
    bid_l2_qty = abs(int(bid_levels[1][1])) if len(bid_levels) >= 2 else 0
    ask_l1_qty = abs(int(ask_levels[0][1])) if len(ask_levels) >= 1 else 0
    ask_l2_qty = abs(int(ask_levels[1][1])) if len(ask_levels) >= 2 else 0
    return bid_l1_qty, bid_l2_qty, ask_l1_qty, ask_l2_qty


def get_l1_l2_imbalance(order_depth):
    # (bid_l1+bid_l2 - ask_l1-ask_l2) / max(1, total_l1+l2). Falls back to L1
    # if L2 is missing because get_l1_l2_depths returns 0 for absent levels.
    bid_l1_qty, bid_l2_qty, ask_l1_qty, ask_l2_qty = get_l1_l2_depths(order_depth)
    bid_depth = bid_l1_qty + bid_l2_qty
    ask_depth = ask_l1_qty + ask_l2_qty
    return (bid_depth - ask_depth) / max(1, bid_depth + ask_depth)


def safe_order(product, price, qty, expected_pos, limit):
    qty = int(qty)
    if qty > 0:
        qty = min(qty, limit - expected_pos)
    elif qty < 0:
        qty = -min(-qty, limit + expected_pos)
    if qty == 0:
        return None, expected_pos
    return Order(product, int(price), qty), expected_pos + qty


def append_hydro_orders(orders, product, price, qty, expected_pos, limit):
    order, expected_pos = safe_order(product, price, qty, expected_pos, limit)
    if order is not None:
        orders.append(order)
    return expected_pos


# ---------------------------------------------------------------------------
# BS / IV helpers (stdlib only; no numpy/scipy in trader).
_SQRT_2 = math.sqrt(2.0)
_SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / _SQRT_2))


def _norm_pdf(x):
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def get_voucher_strike(product):
    if isinstance(product, str) and product.startswith("VEV_"):
        try:
            return int(product[4:])
        except (ValueError, TypeError):
            return None
    return None


def get_tte_days(day, timestamp, mode="default"):
    """One central TTE function. Returns calendar days remaining to expiry.

    Public R4 days (1, 2, 3) map to roll-down 7, 6, 5; final-sim day=4 maps to
    4 days. The trader uses tte_years = tte_days / 365.0 inside BS.
    """
    offset = float(VOUCHER_BS["tte_offset_days"])
    floor = float(VOUCHER_BS["tte_floor_days"])
    if mode == "r4_4_3_2":
        offset = 5.0
    elif mode == "r4_8_7_6":
        offset = 9.0
    raw = (offset - float(day)) - float(timestamp) / 1_000_000.0
    if raw < floor:
        raw = floor
    return raw


def _resolve_bs_day_index(pstate, timestamp, observed_day=None):
    """Resolve public/final day for BS TTE without relying on the backtester."""
    if observed_day is not None:
        try:
            day = int(observed_day)
        except (TypeError, ValueError):
            day = int(VOUCHER_BS["initial_day_index"])
    else:
        prev_day = pstate.get("BS_DAY_INDEX", None)
        day = int(prev_day) if prev_day is not None else int(VOUCHER_BS["initial_day_index"])
        prev_ts = pstate.get("BS_LAST_TIMESTAMP", None)
        try:
            if prev_ts is not None and int(timestamp) < int(prev_ts):
                day += 1
        except (TypeError, ValueError):
            pass
    pstate["BS_DAY_INDEX"] = int(day)
    pstate["BS_LAST_TIMESTAMP"] = int(timestamp)
    return int(day)


def bs_call_price(S, K, T, sigma):
    if T <= 0.0 or sigma <= 0.0 or S <= 0.0 or K <= 0.0:
        return max(0.0, S - K)
    sT = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / sT
    d2 = d1 - sT
    return S * _norm_cdf(d1) - K * _norm_cdf(d2)


def bs_call_delta(S, K, T, sigma):
    if T <= 0.0 or sigma <= 0.0 or S <= 0.0 or K <= 0.0:
        return 1.0 if S > K else 0.0
    sT = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / sT
    return _norm_cdf(d1)


def bs_call_vega(S, K, T, sigma):
    if T <= 0.0 or sigma <= 0.0 or S <= 0.0 or K <= 0.0:
        return 0.0
    sT = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / sT
    return S * math.sqrt(T) * _norm_pdf(d1)


def implied_vol_solve(C, S, K, T, lo=1e-4, hi=3.0, n_iter=40, tol=1e-4):
    """Bisection IV solver. Returns None on inadmissible inputs."""
    if T <= 0.0 or S <= 0.0 or K <= 0.0:
        return None
    intrinsic = max(0.0, S - K)
    if C <= intrinsic + 1e-9 or C >= S:
        return None
    p_lo = bs_call_price(S, K, T, lo)
    p_hi = bs_call_price(S, K, T, hi)
    if not (p_lo <= C <= p_hi):
        # Expand a bit if our cap is too low.
        for _ in range(4):
            hi *= 1.5
            p_hi = bs_call_price(S, K, T, hi)
            if p_hi >= C:
                break
        if not (p_lo <= C <= p_hi):
            return None
    a, b = lo, hi
    for _ in range(n_iter):
        m = 0.5 * (a + b)
        p = bs_call_price(S, K, T, m)
        if p > C:
            b = m
        else:
            a = m
        if (b - a) < tol:
            break
    return 0.5 * (a + b)


def _bs_calibrate_sigma(spot, ttey, voucher_mids, voucher_spreads, pstate, tick_count):
    """Calibrate live ATM-ish sigma from central strike mids.

    Returns (sigma, n_valid). EMA-smoothed across ticks. Falls back to the
    config "fallback_sigma" if too few central strikes have valid IV.
    """
    floor = float(VOUCHER_BS["iv_floor"])
    cap = float(VOUCHER_BS["iv_cap"])
    max_sp = float(VOUCHER_BS["max_calib_spread"])
    central = VOUCHER_BS["central_strikes"]
    ivs = []
    for K in central:
        mid = voucher_mids.get(K)
        sp = voucher_spreads.get(K)
        if mid is None or sp is None or sp > max_sp:
            continue
        # Need extrinsic above zero for IV to be defined.
        intrinsic = max(0.0, spot - float(K))
        if mid <= intrinsic + 0.5:
            continue
        iv = implied_vol_solve(mid, spot, float(K), ttey)
        if iv is None or iv < floor or iv > cap:
            continue
        ivs.append(iv)
    n_valid = len(ivs)
    prev_sigma = pstate.get("BS_SIGMA", None)
    if n_valid < int(VOUCHER_BS["min_valid_strikes"]):
        if prev_sigma is None:
            return float(VOUCHER_BS["fallback_sigma"]), n_valid
        return float(prev_sigma), n_valid
    # Use median to be robust to one-strike outliers.
    ivs_sorted = sorted(ivs)
    if len(ivs_sorted) % 2 == 1:
        med = ivs_sorted[len(ivs_sorted) // 2]
    else:
        med = 0.5 * (ivs_sorted[len(ivs_sorted) // 2 - 1] + ivs_sorted[len(ivs_sorted) // 2])
    if prev_sigma is None:
        return med, n_valid
    alpha = float(VOUCHER_BS["sigma_ema_alpha"])
    floor_ticks = max(1, int(VOUCHER_BS["sigma_warmup_ticks"]))
    if tick_count < floor_ticks:
        alpha = max(alpha, 1.0 / (tick_count + 1))
    return alpha * med + (1.0 - alpha) * float(prev_sigma), n_valid


def _initial_seed(mid, pstate):
    """Compute the *first-tick* seed for the slow EMA.

    Welford adaptive alpha makes the seed nearly irrelevant after a few hundred
    ticks, but we still expose multiple seed modes for ablation. The chosen
    mode is read from HYDRO_PARAMS so a single env override picks the variant.
    """
    mode = HYDRO_PARAMS.get("warm_start_mode", "blend_25")
    anchor = float(HYDRO_PARAMS.get("warm_start", mid))
    weight = float(HYDRO_PARAMS.get("warm_start_weight", 0.25))
    if mode == "first_mid":
        return float(mid)
    if mode == "blend_10":
        return 0.10 * anchor + 0.90 * float(mid)
    if mode == "blend_25":
        return 0.25 * anchor + 0.75 * float(mid)
    if mode == "control_75":
        return 0.75 * anchor + 0.25 * float(mid)
    if mode == "median_early":
        # The first call seeds with first_mid; the median is finalised later.
        return float(mid)
    # Unknown mode: fall back to a safe blend.
    weight = clamp(weight, 0.0, 1.0)
    return weight * anchor + (1.0 - weight) * float(mid)


def _decay_anchor_pull(slow_ema, tick_count):
    """Optional residual anchor pull that decays linearly to zero.

    Adds a *small* nudge of slow_ema toward warm_start during the first
    `warm_start_decay_ticks` ticks, scaled by warm_start_weight. After the
    decay window the function is the identity. Using a separate decay term
    keeps the EMA truthful to live mids while still letting first_mid /
    blend_25 / control_75 differ during the first few hundred ticks (so the
    ablation actually exposes warm-start sensitivity).
    """
    decay_ticks = max(1, int(HYDRO_PARAMS.get("warm_start_decay_ticks", 600)))
    if tick_count >= decay_ticks:
        return slow_ema
    mode = HYDRO_PARAMS.get("warm_start_mode", "blend_25")
    if mode == "first_mid":
        return slow_ema
    if mode == "blend_10":
        weight0 = 0.10
    elif mode == "blend_25":
        weight0 = 0.25
    elif mode == "control_75":
        weight0 = 0.75
    elif mode == "median_early":
        weight0 = 0.0
    else:
        weight0 = clamp(float(HYDRO_PARAMS.get("warm_start_weight", 0.25)), 0.0, 1.0)
    if weight0 <= 0.0:
        return slow_ema
    decay = max(0.0, 1.0 - tick_count / decay_ticks)
    pull = weight0 * decay
    if pull <= 0.0:
        return slow_ema
    anchor = float(HYDRO_PARAMS.get("warm_start", slow_ema))
    return (1.0 - pull) * slow_ema + pull * anchor


def compute_hydro_fair(mid, ema, imbalance, spread, pstate):
    """Build the live fair from EMA plus bounded leans.

    L1+L2 imbalance is a small bounded lean (max imb_lean_max ticks).
    Spread>16 bearish lean is off by default and capped at spread_lean_max.
    """
    fair = float(ema)
    if HYDRO_PARAMS.get("imbalance_enabled", True):
        lean = clamp(
            imbalance * HYDRO_PARAMS["imb_lean_ticks"],
            -HYDRO_PARAMS["imb_lean_max"],
            HYDRO_PARAMS["imb_lean_max"],
        )
        fair += lean
    if HYDRO_PARAMS.get("spread_lean_enabled", False) and spread > 16:
        fair -= clamp(
            (spread - 16) * HYDRO_PARAMS["spread_bear_lean"],
            0.0,
            HYDRO_PARAMS["spread_lean_max"],
        )
    return fair


def compute_hydro_target(mid, fair, imbalance, position, pstate):
    deviation = mid - fair
    slope = HYDRO_PARAMS["target_slope"]
    trigger = HYDRO_PARAMS["imb_trigger"]
    if abs(imbalance) > trigger:
        if (deviation > 0 and imbalance < 0) or (deviation < 0 and imbalance > 0):
            slope += 0.35
        else:
            slope -= 0.45
    target = -round(slope * deviation)
    return int(clamp(target, -HYDRO_PARAMS["target_max"], HYDRO_PARAMS["target_max"]))


# Historical mean and std computed from days 0-2 (30k ticks each).
# Seed values for the EMA mean and EMA std on the very first tick.
# VEV_6000 and VEV_6500 are excluded - permanently at 0.5, std=0, untradeable.
ZSCORE_PRIORS = {
    "VELVETFRUIT_EXTRACT": {"mean": 5250.0981, "std": 15.6304},
    "VEV_4000":            {"mean": 1250.1098, "std": 15.6472},
    "VEV_4500":            {"mean":  750.1096, "std": 15.6399},
    "VEV_5000":            {"mean":  255.0224, "std": 14.3756},
    "VEV_5100":            {"mean":  166.8054, "std": 12.7426},
    "VEV_5200":            {"mean":   95.5488, "std":  9.6642},
    "VEV_5300":            {"mean":   46.7599, "std":  6.2281},
    "VEV_5400":            {"mean":   15.9519, "std":  3.4292},
    "VEV_5500":            {"mean":    6.6414, "std":  1.7388},
}


# ---------------------------------------------------------------------------
# VELVET overlay implementation. Runs AFTER baseline _trade_zscore so that
# baseline behaviour is the default; the overlay either filters or augments
# the baseline orders depending on VELVET_MODE.

_VELVET_NAMES = ("Mark 67", "Mark 49", "Mark 55", "Mark 14", "Mark 01", "Mark 22", "Mark 38")


def _velvet_normalise_name(raw):
    return str(raw or "").strip().replace("_", " ")


def _velvet_apply_name_mode(name):
    mode = VELVET_OVERLAY.get("name_mode", "normal")
    if mode == "shuffled":
        # A fixed permutation that swaps the two informational names with
        # noise names. Used as the shuffled-name control.
        mapping = {
            "Mark 67": "Mark 14",
            "Mark 49": "Mark 55",
            "Mark 55": "Mark 67",
            "Mark 14": "Mark 49",
        }
        return mapping.get(name, name)
    return name


def _velvet_name_signs():
    """Return signs (mark67_buy_sign, mark49_sell_sign).

    +1 means use the empirical sign (Mark 67 buy -> bullish; Mark 49 sell ->
    bullish/fade). sign_flipped inverts both for the ablation.
    """
    if VELVET_OVERLAY.get("name_mode") == "sign_flipped":
        return -1.0, -1.0
    return 1.0, 1.0


def _velvet_update_name_state(market_trades, pstate):
    """Read VELVET market trades for the current tick and update last-seen
    counters for Mark 67 buy and Mark 49 sell. Decay each tick."""
    m67 = int(pstate.get("VELVET_M67_TICKS_AGO", 9999))
    m49 = int(pstate.get("VELVET_M49_TICKS_AGO", 9999))
    m67 += 1
    m49 += 1
    if VELVET_OVERLAY.get("use_mark67", True):
        for tr in market_trades or []:
            buyer = _velvet_apply_name_mode(_velvet_normalise_name(getattr(tr, "buyer", "")))
            if buyer == "Mark 67":
                m67 = 0
                break
    if VELVET_OVERLAY.get("use_mark49", True):
        for tr in market_trades or []:
            seller = _velvet_apply_name_mode(_velvet_normalise_name(getattr(tr, "seller", "")))
            if seller == "Mark 49":
                m49 = 0
                break
    pstate["VELVET_M67_TICKS_AGO"] = m67
    pstate["VELVET_M49_TICKS_AGO"] = m49
    return m67, m49


def _velvet_compression_state(order_depth):
    best_bid, bid_qty, best_ask, ask_qty = get_best_bid_ask(order_depth)
    if best_bid is None or best_ask is None:
        return None
    spread = best_ask - best_bid
    av = abs(int(ask_qty))
    bv = abs(int(bid_qty))
    premium_bull = spread == VELVET_OVERLAY["premium_spread"] and av < VELVET_OVERLAY["premium_ask_vol"]
    broad_bull = spread <= VELVET_OVERLAY["broad_spread_max"] and av < VELVET_OVERLAY["broad_ask_vol"]
    broad_bear = spread <= VELVET_OVERLAY["broad_spread_max"] and bv < VELVET_OVERLAY["broad_ask_vol"]
    return {
        "best_bid": best_bid, "bid_qty": bid_qty,
        "best_ask": best_ask, "ask_qty": ask_qty,
        "spread": spread, "premium_bull": premium_bull,
        "broad_bull": broad_bull, "broad_bear": broad_bear,
    }


def _velvet_filter_sells(orders, msg=""):
    """Drop SELL orders (qty<0). Returns filtered list."""
    return [o for o in orders if o.quantity >= 0]


def _velvet_overlay(product, order_depth, position, limit, baseline_orders,
                    market_trades, pstate, mode):
    """Apply the requested VELVET mode on top of baseline z-score orders.

    Modes:
      baseline             -> pass through.
      disabled             -> drop all VELVET orders.
      premium_gate         -> drop baseline SELL when premium-bullish active.
      mark49_gate          -> drop baseline SELL when Mark49 sold within window.
      premium_overlay      -> baseline + small cross buy on premium-bullish.
      premium_overlay_names-> premium_overlay + Mark67 size bonus + Mark49 gate.
      standalone_premium   -> drop baseline, only premium cross buy.
      fair_provider        -> drop all VELVET orders, maintain fair state only.
    """
    state = _velvet_compression_state(order_depth)
    m67_age, m49_age = _velvet_update_name_state(market_trades, pstate)

    if state is None:
        # No two-sided book: keep baseline behaviour for safety.
        return baseline_orders if mode != "disabled" and mode != "fair_provider" else []

    # Maintain a small fair state (live mid EMA) for diagnostics / future
    # voucher use. Bounded, no history.
    mid = (state["best_bid"] + state["best_ask"]) / 2.0
    prev_ema = float(pstate.get("VELVET_EMA", mid))
    new_ema = 0.04 * mid + 0.96 * prev_ema
    pstate["VELVET_EMA"] = new_ema
    pstate["VELVET_LAST_MID"] = mid

    if mode == "baseline":
        return baseline_orders
    if mode in ("disabled", "fair_provider"):
        return []

    premium = bool(state["premium_bull"])
    m67_recent = m67_age <= int(VELVET_OVERLAY["mark67_window_ticks"])
    m49_recent = m49_age <= int(VELVET_OVERLAY["mark49_window_ticks"])
    sign67, sign49 = _velvet_name_signs()
    # If sign_flipped, "recent informed signal" inverts: pretend the recent
    # signals are the opposite. Implemented by swapping which gate fires.
    if sign67 < 0 or sign49 < 0:
        m67_recent_eff = m67_recent and (sign67 > 0)
        m49_recent_eff = m49_recent and (sign49 > 0)
    else:
        m67_recent_eff = m67_recent
        m49_recent_eff = m49_recent

    # ---- gates: filter baseline orders ----
    if mode == "premium_gate":
        if premium:
            # Block fresh shorts/sells; allow buys (which reduce existing short
            # or build long against compression).
            return _velvet_filter_sells(baseline_orders)
        return baseline_orders

    if mode == "mark49_gate":
        if m49_recent_eff:
            return _velvet_filter_sells(baseline_orders)
        return baseline_orders

    # ---- overlays: keep baseline, add small premium cross buys ----
    if mode in ("premium_overlay", "premium_overlay_names"):
        out = list(baseline_orders)
        if not premium:
            return out
        # Compute expected position after baseline orders.
        expected_pos = position + sum(o.quantity for o in baseline_orders)
        size = int(VELVET_OVERLAY["overlay_size"])
        if mode == "premium_overlay_names" and m67_recent_eff and VELVET_OVERLAY.get("use_mark67", True):
            size += int(VELVET_OVERLAY["mark67_size_bonus"])
        soft_cap = int(VELVET_OVERLAY["overlay_soft_cap_long"])
        # Priority: if currently short, use this buy to reduce short before
        # building fresh long. Achieved naturally by not capping below 0.
        if expected_pos >= soft_cap:
            return out
        room = min(limit - expected_pos, soft_cap - expected_pos)
        if room <= 0:
            return out
        qty = min(size, int(state["ask_qty"]), room)
        if qty <= 0:
            return out
        # Cross at best ask only.
        out.append(Order(product, int(state["best_ask"]), qty))
        return out

    if mode == "standalone_premium":
        if not premium:
            return []
        size = int(VELVET_OVERLAY["overlay_size"])
        soft_cap = int(VELVET_OVERLAY["overlay_soft_cap_long"])
        if position >= soft_cap:
            return []
        room = min(limit - position, soft_cap - position)
        if room <= 0:
            return []
        qty = min(size, int(state["ask_qty"]), room)
        if qty <= 0:
            return []
        return [Order(product, int(state["best_ask"]), qty)]

    # Unknown mode falls back to baseline (defensive).
    return baseline_orders


def _bs_voucher_orders_central(product, K, order_depth, position, limit, S, T, sigma,
                               expected_pos_in, bucket_room):
    """BS-residual trader for one central voucher strike.

    Returns (orders, expected_pos_out, fair, delta).
    """
    orders = []
    best_bid, bid_qty, best_ask, ask_qty = get_best_bid_ask(order_depth)
    if best_bid is None or best_ask is None:
        return orders, expected_pos_in, None, None
    spread = best_ask - best_bid
    fair = bs_call_price(S, float(K), T, sigma)
    delta = bs_call_delta(S, float(K), T, sigma)
    mid = (best_bid + best_ask) / 2.0
    residual = mid - fair
    if abs(residual) < float(VOUCHER_BS["residual_floor"]) * float(VOUCHER_BS["residual_floor_mult"]):
        return orders, expected_pos_in, fair, delta

    cross_buy_edge = float(VOUCHER_BS["cross_buy_edge"])
    cross_sell_edge = float(VOUCHER_BS["cross_sell_edge"])
    base_size = int(VOUCHER_BS["base_order_size"])
    max_size = int(VOUCHER_BS["max_order_size"])
    passive_size = int(VOUCHER_BS["passive_order_size"])
    expected_pos = expected_pos_in

    def _size_room_buy():
        return min(limit - expected_pos, max(0, bucket_room))

    def _size_room_sell():
        return min(limit + expected_pos, max(0, bucket_room))

    # Cross BUY when ask sits below fair by more than the threshold.
    edge_cross_buy = (fair - float(best_ask)) - 0.0
    if edge_cross_buy >= cross_buy_edge:
        room = _size_room_buy()
        if room > 0:
            qty = min(int(ask_qty), max_size, base_size, room)
            if qty > 0:
                orders.append(Order(product, int(best_ask), int(qty)))
                expected_pos += qty
    # Cross SELL when bid sits above fair by more than the threshold.
    edge_cross_sell = (float(best_bid) - fair) - 0.0
    if edge_cross_sell >= cross_sell_edge:
        room = _size_room_sell()
        if room > 0:
            qty = min(int(bid_qty), max_size, base_size, room)
            if qty > 0:
                orders.append(Order(product, int(best_bid), -int(qty)))
                expected_pos -= qty

    # Passive maker (Tier 1) when book is wide enough.
    if spread >= int(VOUCHER_BS["passive_min_spread"]):
        passive_min_edge = float(VOUCHER_BS["passive_min_edge"])
        buy_price = int(best_bid) + 1
        sell_price = int(best_ask) - 1
        if buy_price < int(best_ask) and (fair - buy_price) >= passive_min_edge:
            room = _size_room_buy()
            if room > 0:
                qty = min(passive_size, room)
                if qty > 0:
                    orders.append(Order(product, buy_price, int(qty)))
                    expected_pos += qty
        if sell_price > int(best_bid) and (sell_price - fair) >= passive_min_edge:
            room = _size_room_sell()
            if room > 0:
                qty = min(passive_size, room)
                if qty > 0:
                    orders.append(Order(product, sell_price, -int(qty)))
                    expected_pos -= qty
    return orders, expected_pos, fair, delta


def _bs_voucher_orders_5400_buy(product, order_depth, position, limit, S, T, sigma,
                                 expected_pos_in, bucket_room):
    """Cautious BUY-ONLY 5400 leg. Only crosses when residual is sufficiently
    negative (ask below fair by more than the central threshold + extra).
    """
    orders = []
    best_bid, bid_qty, best_ask, ask_qty = get_best_bid_ask(order_depth)
    if best_bid is None or best_ask is None:
        return orders, expected_pos_in, None, None
    fair = bs_call_price(S, 5400.0, T, sigma)
    delta = bs_call_delta(S, 5400.0, T, sigma)
    cross_buy_edge = float(VOUCHER_BS["cross_buy_edge"]) + float(VOUCHER_BS["edge_5400_buy_threshold"])
    edge_cross_buy = (fair - float(best_ask))
    if edge_cross_buy < cross_buy_edge:
        return orders, expected_pos_in, fair, delta
    room = min(limit - expected_pos_in, max(0, bucket_room))
    if room <= 0:
        return orders, expected_pos_in, fair, delta
    qty = min(int(ask_qty), int(VOUCHER_BS["edge_5400_buy_size"]), room)
    if qty > 0:
        orders.append(Order(product, int(best_ask), int(qty)))
        return orders, expected_pos_in + qty, fair, delta
    return orders, expected_pos_in, fair, delta


def _bs_apply_overlay_gate(zscore_orders, order_depth, S, K, T, sigma):
    """Drop z-score orders that disagree with BS by more than gate_edge.

    A z-score SELL is dropped if BS_fair > mid + gate_edge (BS thinks cheap).
    A z-score BUY  is dropped if BS_fair < mid - gate_edge (BS thinks rich).
    """
    if not zscore_orders:
        return zscore_orders
    best_bid, _, best_ask, _ = get_best_bid_ask(order_depth)
    if best_bid is None or best_ask is None:
        return zscore_orders
    mid = (best_bid + best_ask) / 2.0
    fair = bs_call_price(S, float(K), T, sigma)
    gate = float(VOUCHER_BS["gate_edge"])
    out = []
    for o in zscore_orders:
        if o.quantity > 0 and (mid - fair) > gate:
            # z wants to BUY but mid is well above fair (rich) -> block.
            continue
        if o.quantity < 0 and (fair - mid) > gate:
            # z wants to SELL but mid is well below fair (cheap) -> block.
            continue
        out.append(o)
    return out


def _clip_positive_inventory_orders(orders, position, long_cap):
    """Clip only buy quantity that would take projected inventory above cap."""
    if long_cap is None:
        return orders
    cap = int(long_cap)
    expected_pos = int(position)
    out = []
    for order in orders:
        qty = int(order.quantity)
        if qty > 0:
            room = cap - expected_pos
            if room <= 0:
                continue
            qty = min(qty, room)
        if qty != 0:
            out.append(Order(order.symbol, int(order.price), int(qty)))
            expected_pos += qty
    return out


def _drop_new_long_buy_orders(orders, position):
    """Allow short-covering buys, but block opening or extending long exposure."""
    expected_pos = int(position)
    out = []
    for order in orders:
        qty = int(order.quantity)
        if qty > 0 and expected_pos >= 0:
            continue
        if qty > 0 and expected_pos < 0 and expected_pos + qty > 0:
            qty = -expected_pos
        if qty != 0:
            out.append(Order(order.symbol, int(order.price), int(qty)))
            expected_pos += qty
    return out


def _bs_buy_veto_is_active(order_depth, fair, edge):
    best_bid, _, best_ask, _ = get_best_bid_ask(order_depth)
    if best_bid is None or best_ask is None or fair is None:
        return False
    return (float(best_ask) - float(fair)) >= float(edge)


def _order_delta_change(product, order, bs_deltas):
    K = get_voucher_strike(product)
    if K is None:
        return 0.0
    return float(order.quantity) * float(bs_deltas.get(K, 0.0) or 0.0)


def _apply_net_delta_soft_cap(orders_by_product, current_net_delta, bs_deltas, cap, priority):
    projected = float(current_net_delta)
    for product, orders in orders_by_product.items():
        for order in orders:
            projected += _order_delta_change(product, order, bs_deltas)
    cap = float(cap)
    if abs(projected) <= cap:
        return orders_by_product

    sign = 1.0 if projected > 0.0 else -1.0
    out = {product: list(orders) for product, orders in orders_by_product.items()}
    priority_products = [f"VEV_{int(K)}" for K in priority]
    for product in priority_products:
        orders = out.get(product)
        if not orders or abs(projected) <= cap:
            continue
        K = get_voucher_strike(product)
        delta = float(bs_deltas.get(K, 0.0) or 0.0) if K is not None else 0.0
        if delta <= 0.0:
            continue
        clipped = []
        for order in orders:
            qty = int(order.quantity)
            if abs(projected) <= cap or qty == 0 or (qty > 0) != (sign > 0):
                clipped.append(order)
                continue
            excess = abs(projected) - cap
            qty_to_remove = min(abs(qty), int(math.ceil(excess / max(delta, 1e-9))))
            if qty_to_remove <= 0:
                clipped.append(order)
                continue
            new_qty = qty - int(sign) * qty_to_remove
            projected -= sign * qty_to_remove * delta
            if new_qty != 0:
                clipped.append(Order(order.symbol, int(order.price), int(new_qty)))
        out[product] = clipped
    return out


def _bucket_position_sums(positions):
    sums = {"deep": 0, "central": 0, "upper": 0, "far": 0}
    for K in _BS_STRIKE_LIST:
        bucket = _BS_BUCKET_OF[K]
        sums[bucket] = sums.get(bucket, 0) + abs(int(positions.get(f"VEV_{K}", 0)))
    return sums


def _net_delta_from_positions(positions, bs_deltas, velvet_pos):
    nd = float(velvet_pos)
    for K, d in bs_deltas.items():
        if d is None:
            continue
        nd += float(positions.get(f"VEV_{K}", 0)) * float(d)
    return nd


def _threshold_rescue_mode(product):
    mode = str(THRESHOLD_RESCUE.get("mode", "off"))
    if not isinstance(product, str) or not product.startswith("VEV_"):
        return "off"
    allowed = {"rejected_reference", "cap_safe", "delta_add_gated", "combined", "selective"}
    return mode if mode in allowed else "off"


def _threshold_rescue_threshold(product):
    thresholds = THRESHOLD_RESCUE.get("thresholds", {})
    base = float(THRESHOLD_RESCUE.get("base_threshold", PARAMS["ZSCORE_ENTRY"]))
    return float(thresholds.get(product, base))


def _zscore_order_for_threshold(product, best_bid, bid_quantity, best_ask,
                                ask_quantity, position, limit, z, threshold):
    position = int(position)
    limit = int(limit)
    if z < -float(threshold):
        qty = min(abs(int(ask_quantity)), limit - position)
        if qty > 0:
            return Order(product, int(best_ask), int(qty))
    elif z > float(threshold):
        qty = min(abs(int(bid_quantity)), limit + position)
        if qty > 0:
            return Order(product, int(best_bid), -int(qty))
    return None


def _threshold_near_cap(product, position):
    strict_products = set(THRESHOLD_RESCUE.get("strict_products", ()))
    threshold = (
        int(THRESHOLD_RESCUE.get("strict_cap_near", 225))
        if product in strict_products
        else int(THRESHOLD_RESCUE.get("cap_near", 250))
    )
    return abs(int(position)) >= threshold


def _order_adds_abs_position(position, order):
    if order is None:
        return False
    current = int(position)
    projected = current + int(order.quantity)
    return abs(projected) > abs(current)


def _order_reduces_abs_position(position, order):
    if order is None:
        return False
    current = int(position)
    projected = current + int(order.quantity)
    return abs(projected) < abs(current)


def _order_projected_delta(product, order, current_net_delta, bs_deltas):
    if order is None or current_net_delta is None:
        return None
    K = get_voucher_strike(product)
    if K is None:
        return None
    delta = float((bs_deltas or {}).get(K, 0.0) or 0.0)
    return float(current_net_delta) + float(order.quantity) * delta


def _order_increases_abs_delta(product, order, current_net_delta, bs_deltas):
    projected = _order_projected_delta(product, order, current_net_delta, bs_deltas)
    if projected is None:
        return False
    return abs(projected) > abs(float(current_net_delta)) + 1e-9


def _order_reduces_abs_delta(product, order, current_net_delta, bs_deltas):
    projected = _order_projected_delta(product, order, current_net_delta, bs_deltas)
    if projected is None:
        return False
    return abs(projected) < abs(float(current_net_delta)) - 1e-9


def _threshold_rescue_blocks_extra(product, order, position, z, threshold,
                                   current_net_delta, bs_deltas):
    mode = _threshold_rescue_mode(product)
    if mode in ("cap_safe", "combined"):
        if _threshold_near_cap(product, position) and _order_adds_abs_position(position, order):
            return True
    if mode in ("delta_add_gated", "combined") and current_net_delta is not None:
        abs_delta = abs(float(current_net_delta))
        worsens_delta = _order_increases_abs_delta(product, order, current_net_delta, bs_deltas)
        if abs_delta >= float(THRESHOLD_RESCUE.get("delta_block_abs", 1600.0)) and worsens_delta:
            return True
        strong_edge = float(threshold) + float(THRESHOLD_RESCUE.get("delta_strong_margin", 0.25))
        if (
            abs_delta >= float(THRESHOLD_RESCUE.get("delta_strong_abs", 1400.0))
            and worsens_delta
            and abs(float(z)) < strong_edge
        ):
            return True
    return False


def _select_threshold_rescue_order(product, candidate_order, baseline_order,
                                   position, z, threshold, current_net_delta,
                                   bs_deltas):
    mode = _threshold_rescue_mode(product)
    if mode == "off":
        return candidate_order
    if mode == "rejected_reference" or mode == "selective":
        return candidate_order

    if candidate_order is not None:
        extra_order = baseline_order is None
        if extra_order and _threshold_rescue_blocks_extra(
            product, candidate_order, position, z, threshold, current_net_delta, bs_deltas
        ):
            return None
        return candidate_order

    if baseline_order is None:
        return None

    if mode in ("cap_safe", "combined"):
        if _threshold_near_cap(product, position) and _order_reduces_abs_position(position, baseline_order):
            return baseline_order
    if mode in ("delta_add_gated", "combined"):
        if _order_reduces_abs_delta(product, baseline_order, current_net_delta, bs_deltas):
            return baseline_order
    return None


class Trader:

    ## TRADE HYDROGEL ##     ## TRADE HYDROGEL ##
    def _trade_hydrogel(self, product, order_depth, position, limit, pstate):
        orders = []

        best_bid, bid_quantity, best_ask, ask_quantity = get_best_bid_ask(order_depth)
        mid = get_mid(order_depth)
        tick_count = int(pstate.get("HYDRO_TICK_COUNT", 0) or 0)
        if best_bid is None or best_ask is None or mid is None:
            pstate["HYDRO_TICK_COUNT"] = tick_count
            return orders

        spread = best_ask - best_bid
        imbalance = get_l1_l2_imbalance(order_depth)

        # --- Live slow EMA with Welford-adaptive alpha during warm-up. ---
        prev_hydro_ema = pstate.get("HYDRO_EMA", None)
        if prev_hydro_ema is None:
            prev_hydro_ema = _initial_seed(mid, pstate)
            # If using the median_early mode, seed an early-mid ring.
            if HYDRO_PARAMS.get("warm_start_mode") == "median_early":
                pstate["HYDRO_EARLY_MIDS"] = [float(mid)]
        prev_hydro_ema = float(prev_hydro_ema)
        prev_fast_ema = float(pstate.get("HYDRO_FAST_EMA", prev_hydro_ema))
        prev_drift_ema = float(pstate.get("HYDRO_DRIFT_EMA", 0.0))

        # Median_early mode: bounded list, finalised at warm-up end.
        if HYDRO_PARAMS.get("warm_start_mode") == "median_early":
            warm_n = int(HYDRO_PARAMS.get("median_warmup_ticks", 50))
            buf = pstate.get("HYDRO_EARLY_MIDS", [])
            if isinstance(buf, list) and len(buf) < warm_n:
                buf = list(buf) + [float(mid)]
                pstate["HYDRO_EARLY_MIDS"] = buf
                if len(buf) == warm_n:
                    sb = sorted(buf)
                    median_v = sb[len(sb) // 2] if len(sb) % 2 == 1 else 0.5 * (sb[len(sb) // 2 - 1] + sb[len(sb) // 2])
                    # Re-anchor the slow EMA exactly once when the median is ready.
                    prev_hydro_ema = float(median_v)

        # Welford-style adaptive alpha for the first warmup_alpha_floor_ticks ticks
        # makes the seed lose influence quickly regardless of mode.
        floor_ticks = max(1, int(HYDRO_PARAMS.get("warmup_alpha_floor_ticks", 800)))
        alpha = HYDRO_PARAMS["ema_alpha"]
        if tick_count < floor_ticks:
            alpha = max(alpha, 1.0 / (tick_count + 1))
        fast_alpha = HYDRO_PARAMS["fast_ema_alpha"]

        new_hydro_ema = alpha * mid + (1 - alpha) * prev_hydro_ema
        new_hydro_ema = _decay_anchor_pull(new_hydro_ema, tick_count)
        new_fast_ema = fast_alpha * mid + (1 - fast_alpha) * prev_fast_ema
        new_drift_ema = 0.02 * abs(new_fast_ema - new_hydro_ema) + 0.98 * prev_drift_ema

        # --- Drift-aware fair adjustment (live, no anchor reference). ---
        drift_gap = new_fast_ema - new_hydro_ema
        fair_ema = new_hydro_ema
        if abs(drift_gap) > HYDRO_PARAMS["drift_fair_threshold"]:
            fair_ema += clamp(
                drift_gap * HYDRO_PARAMS["drift_fair_blend"],
                -HYDRO_PARAMS["drift_fair_max"],
                HYDRO_PARAMS["drift_fair_max"],
            )

        # --- Live regime detector (replaces 9995-comparing mean_shift_guard). ---
        # Two independent live triggers, both must fire to shrink size and pull
        # the fair toward fast_ema. Persistence is measured over a small bounded
        # ring of recent |mid - slow_ema| values; no unbounded history.
        persist_threshold = HYDRO_PARAMS["live_regime_persist_ticks"]
        window_n = max(4, int(HYDRO_PARAMS["live_regime_persist_window"]))
        ring = pstate.get("HYDRO_PERSIST_RING", [])
        if not isinstance(ring, list):
            ring = []
        ring.append(1 if abs(mid - new_hydro_ema) > persist_threshold else 0)
        if len(ring) > window_n:
            ring = ring[-window_n:]
        persist_count = sum(ring)
        persist_active = (
            len(ring) >= window_n
            and persist_count / max(1, len(ring)) >= HYDRO_PARAMS["live_regime_persist_frac"]
        )
        fast_slow_active = abs(new_fast_ema - new_hydro_ema) > HYDRO_PARAMS["live_regime_fast_slow_ticks"]
        regime_active = bool(persist_active and fast_slow_active)
        if regime_active:
            # Pull fair toward fast EMA (live signal), bounded blend.
            blend = clamp(HYDRO_PARAMS["live_regime_blend"], 0.0, 1.0)
            fair_ema += (new_fast_ema - fair_ema) * blend

        fair = compute_hydro_fair(mid, fair_ema, imbalance, spread, pstate)
        target_pos = compute_hydro_target(mid, fair, imbalance, position, pstate)
        deviation = mid - fair

        prev_bid = pstate.get("HYDRO_LAST_BID", pstate.get("HYDRO_BID", None))
        prev_ask = pstate.get("HYDRO_LAST_ASK", pstate.get("HYDRO_ASK", None))

        # Persist all live state. Compact: scalars + one bounded ring.
        pstate["HYDRO_EMA"] = new_hydro_ema
        pstate["HYDRO_FAST_EMA"] = new_fast_ema
        pstate["HYDRO_LAST_MID"] = mid
        pstate["HYDRO_LAST_BID"] = best_bid
        pstate["HYDRO_LAST_ASK"] = best_ask
        pstate["HYDRO_BID"] = best_bid
        pstate["HYDRO_ASK"] = best_ask
        pstate["HYDRO_DRIFT_EMA"] = new_drift_ema
        pstate["HYDRO_TICK_COUNT"] = tick_count + 1
        pstate["HYDRO_LAST_IMB"] = imbalance
        pstate["HYDRO_PERSIST_RING"] = ring
        pstate["HYDRO_REGIME"] = 1 if regime_active else 0

        if not HYDRO_PARAMS.get("enabled", True):
            return orders

        # --- Size scaling: warm-up, drift, regime, abnormal spread. ---
        warmup_scale = 0.60 if tick_count < HYDRO_PARAMS["warmup_ticks"] else 1.0
        drift_scale = 0.50 if new_drift_ema > HYDRO_PARAMS["drift_reduce_ticks"] else 1.0
        regime_scale = HYDRO_PARAMS["live_regime_size_scale"] if regime_active else 1.0
        spread_scale = 0.70 if spread < 12 or spread > 18 else 1.0
        size_scale = min(warmup_scale, drift_scale, regime_scale, spread_scale)
        base_size = max(1, int(round(HYDRO_PARAMS["base_order_size"] * size_scale)))
        strong_size = max(1, int(round(HYDRO_PARAMS["strong_order_size"] * size_scale)))
        passive_size = max(1, int(round(HYDRO_PARAMS["passive_order_size"] * size_scale)))
        expected_pos = position

        def may_buy():
            if expected_pos >= HYDRO_PARAMS["stop_add_level"]:
                return False
            if expected_pos >= HYDRO_PARAMS["soft_limit"] and target_pos >= expected_pos:
                return False
            return expected_pos < limit

        def may_sell():
            if expected_pos <= -HYDRO_PARAMS["stop_add_level"]:
                return False
            if expected_pos <= -HYDRO_PARAMS["soft_limit"] and target_pos <= expected_pos:
                return False
            return expected_pos > -limit

        # --- Large-deviation crossing (the dominant Hydro signal). ---
        # Threshold is modulated by L1+L2 imbalance: tighter when imbalance
        # agrees with the reversion direction, looser when it conflicts.
        if HYDRO_PARAMS.get("large_dev_enabled", True):
            sell_threshold = HYDRO_PARAMS["large_dev_imb_agree"] if imbalance < -HYDRO_PARAMS["imb_trigger"] else HYDRO_PARAMS["large_dev"]
            buy_threshold = HYDRO_PARAMS["large_dev_imb_agree"] if imbalance > HYDRO_PARAMS["imb_trigger"] else HYDRO_PARAMS["large_dev"]
            if imbalance > HYDRO_PARAMS["imb_trigger"]:
                sell_threshold = HYDRO_PARAMS["large_dev_conflict"]
            if imbalance < -HYDRO_PARAMS["imb_trigger"]:
                buy_threshold = HYDRO_PARAMS["large_dev_conflict"]

            if deviation > sell_threshold and may_sell() and best_bid - fair >= HYDRO_PARAMS["cross_edge"]:
                qty_to_target = max(1, expected_pos - target_pos)
                qty = min(bid_quantity, strong_size, qty_to_target)
                expected_pos = append_hydro_orders(orders, product, best_bid, -qty, expected_pos, limit)
            elif deviation < -buy_threshold and may_buy() and fair - best_ask >= HYDRO_PARAMS["cross_edge"]:
                qty_to_target = max(1, target_pos - expected_pos)
                qty = min(ask_quantity, strong_size, qty_to_target)
                expected_pos = append_hydro_orders(orders, product, best_ask, qty, expected_pos, limit)

        # --- Narrow-spread shift heuristic (must clear fair edge). ---
        if HYDRO_PARAMS.get("spread_shift_enabled", True) and prev_bid is not None and prev_ask is not None and spread <= 9:
            bid_shift = abs(best_bid - int(prev_bid))
            ask_shift = abs(best_ask - int(prev_ask))
            buy_spread = sell_spread = False
            if ask_shift > bid_shift + 2:
                buy_spread = True
            elif bid_shift > ask_shift + 2:
                sell_spread = True
            else:
                buy_spread = sell_spread = True

            if sell_spread and deviation > HYDRO_PARAMS["spread_shift_dev"] and may_sell() and best_bid - fair >= HYDRO_PARAMS["cross_edge"]:
                qty = min(bid_quantity, base_size, max(1, expected_pos - target_pos))
                expected_pos = append_hydro_orders(orders, product, best_bid, -qty, expected_pos, limit)
            if buy_spread and deviation < -HYDRO_PARAMS["spread_shift_dev"] and may_buy() and fair - best_ask >= HYDRO_PARAMS["cross_edge"]:
                qty = min(ask_quantity, base_size, max(1, target_pos - expected_pos))
                expected_pos = append_hydro_orders(orders, product, best_ask, qty, expected_pos, limit)

        # --- L1+L2 imbalance immediate tilt (small, edge-gated, not standalone). ---
        if HYDRO_PARAMS.get("imbalance_enabled", True) and abs(imbalance) > HYDRO_PARAMS["imb_trigger"]:
            if imbalance > 0 and may_buy() and fair - best_ask >= HYDRO_PARAMS["cross_edge"] and deviation < -HYDRO_PARAMS["spread_shift_dev"]:
                qty = min(ask_quantity, base_size, max(1, target_pos - expected_pos))
                expected_pos = append_hydro_orders(orders, product, best_ask, qty, expected_pos, limit)
            elif imbalance < 0 and may_sell() and best_bid - fair >= HYDRO_PARAMS["cross_edge"] and deviation > HYDRO_PARAMS["spread_shift_dev"]:
                qty = min(bid_quantity, base_size, max(1, expected_pos - target_pos))
                expected_pos = append_hydro_orders(orders, product, best_bid, -qty, expected_pos, limit)

        if not HYDRO_PARAMS.get("passive_enabled", True):
            return orders

        # --- Inside-quote passive maker, edge-gated, inventory-skewed. ---
        fair_inside = best_bid < fair < best_ask
        if fair_inside and spread >= 12:
            buy_price = best_bid + 1
            sell_price = best_ask - 1
            inv_ratio = clamp(expected_pos / max(1, limit), -1.0, 1.0)
            buy_size = passive_size
            sell_size = passive_size
            if inv_ratio > 0:
                buy_size = max(1, int(round(buy_size * (1.0 - inv_ratio))))
                sell_size = int(round(sell_size * (1.0 + 0.5 * inv_ratio)))
            elif inv_ratio < 0:
                sell_size = max(1, int(round(sell_size * (1.0 + inv_ratio))))
                buy_size = int(round(buy_size * (1.0 - 0.5 * inv_ratio)))
            if imbalance > HYDRO_PARAMS["imb_trigger"]:
                buy_size += 1
            elif imbalance < -HYDRO_PARAMS["imb_trigger"]:
                sell_size += 1

            if may_buy() and buy_price < best_ask and fair - buy_price >= HYDRO_PARAMS["passive_min_edge"]:
                expected_pos = append_hydro_orders(orders, product, buy_price, buy_size, expected_pos, limit)
            if may_sell() and sell_price > best_bid and sell_price - fair >= HYDRO_PARAMS["passive_min_edge"]:
                expected_pos = append_hydro_orders(orders, product, sell_price, -sell_size, expected_pos, limit)

        # --- Mark22 test-only branch ---
        # Default disabled. Currently unimplemented because the gates listed in
        # the v2 brief (count, cost-adjusted edge, day-stable sign, fill-stress,
        # mean-shift survival, no name/timestamp dependence, beats no-Mark22 and
        # shuffled-name) have not been independently verified in this audit.
        # The flag remains so future research can wire a directional Mark22
        # contribution without re-touching the trader scaffolding.
        # if HYDRO_PARAMS.get("mark22_enabled", False): pass

        return orders

    ## TRADE Z-SCORE ##     ## TRADE Z-SCORE ##
    def _trade_zscore(self, product, order_depth, position, limit, ema_mean, ema_std,
                      current_net_delta=None, bs_deltas=None):
        orders = []

        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders, ema_mean, ema_std

        best_bid    = max(order_depth.buy_orders.keys())
        bid_quantity = order_depth.buy_orders[best_bid]
        best_ask    = min(order_depth.sell_orders.keys())
        ask_quantity = order_depth.sell_orders[best_ask]
        mid = (best_ask + best_bid) / 2.0

        alpha        = PARAMS["EMA_ALPHA"]
        entry_thresh = PARAMS["ZSCORE_ENTRY"]
        prior        = ZSCORE_PRIORS[product]

        if ema_mean is None:
            ema_mean = prior["mean"]
        if ema_std is None:
            ema_std = prior["std"]

        new_ema_mean = alpha * mid + (1 - alpha) * ema_mean
        deviation    = abs(mid - new_ema_mean)
        new_ema_std  = alpha * deviation + (1 - alpha) * ema_std

        if new_ema_std < 1e-8:
            return orders, new_ema_mean, new_ema_std

        z = (mid - new_ema_mean) / new_ema_std

        rescue_mode = _threshold_rescue_mode(product)
        if rescue_mode != "off":
            base_threshold = float(THRESHOLD_RESCUE.get("base_threshold", PARAMS["ZSCORE_ENTRY"]))
            rescue_threshold = _threshold_rescue_threshold(product)
            baseline_order = _zscore_order_for_threshold(
                product, best_bid, bid_quantity, best_ask, ask_quantity,
                position, limit, z, base_threshold,
            )
            candidate_order = _zscore_order_for_threshold(
                product, best_bid, bid_quantity, best_ask, ask_quantity,
                position, limit, z, rescue_threshold,
            )
            selected = _select_threshold_rescue_order(
                product, candidate_order, baseline_order, position, z,
                rescue_threshold, current_net_delta, bs_deltas,
            )
            if selected is not None:
                orders.append(selected)
            return orders, new_ema_mean, new_ema_std

        buy_cap  = limit - position
        sell_cap = limit + position

        if z < -entry_thresh and buy_cap > 0:
            qty = min(-ask_quantity, buy_cap)
            if qty > 0:
                orders.append(Order(product, best_ask, qty))

        elif z > entry_thresh and sell_cap > 0:
            qty = min(bid_quantity, sell_cap)
            if qty > 0:
                orders.append(Order(product, best_bid, -qty))

        return orders, new_ema_mean, new_ema_std

    ## RUN ALGORITHMS ##     ## RUN ALGORITHMS ##
    def run(self, state: TradingState):
        result = {}

        pstate: dict = {}
        if state.traderData:
            try:
                pstate = json.loads(state.traderData)
            except Exception:
                pstate = {}

        zscore_products = [
            "VELVETFRUIT_EXTRACT",
            "VEV_4000", "VEV_4500", "VEV_5000",
            "VEV_5100", "VEV_5200", "VEV_5300",
            "VEV_5400", "VEV_5500",
        ]
        voucher_products = [p for p in zscore_products if p.startswith("VEV_")]

        # ---- 0) HYDROGEL --------------------------------------------------
        for product, order_depth in state.order_depths.items():
            if product != "HYDROGEL_PACK":
                continue
            position = state.position.get(product, 0)
            limit = POS_LIMITS.get(product, 20)
            result[product] = self._trade_hydrogel(product, order_depth, position, limit, pstate)
            break

        # ---- 1) VELVET (unchanged Hydro v2 + VELVET M4 path) -------------
        if "VELVETFRUIT_EXTRACT" in state.order_depths:
            product = "VELVETFRUIT_EXTRACT"
            order_depth = state.order_depths[product]
            position = state.position.get(product, 0)
            limit = POS_LIMITS.get(product, 200)
            ema_mean = pstate.get(f"ZSCORE_MEAN_{product}", None)
            ema_std = pstate.get(f"ZSCORE_STD_{product}", None)
            orders, new_ema_mean, new_ema_std = self._trade_zscore(
                product, order_depth, position, limit, ema_mean, ema_std
            )
            pstate[f"ZSCORE_MEAN_{product}"] = new_ema_mean
            pstate[f"ZSCORE_STD_{product}"] = new_ema_std

            cap = PARAMS.get("VELVET_BASELINE_CAP")
            if cap is not None:
                cap = int(cap)
                clipped = []
                proj = position
                for o in orders:
                    q = int(o.quantity)
                    if q > 0:
                        room = max(0, cap - proj)
                        q = min(q, room) if proj < cap else (q if proj < 0 else 0)
                        if proj >= 0:
                            q = min(q, max(0, cap - proj))
                    elif q < 0:
                        room = max(0, cap + proj)
                        q = -min(-q, room) if proj > -cap else (q if proj > 0 else 0)
                        if proj <= 0:
                            q = -min(-q, max(0, cap + proj))
                    if q != 0:
                        clipped.append(Order(product, int(o.price), q))
                        proj += q
                orders = clipped
            orders = _velvet_overlay(
                product, order_depth, position, limit, orders,
                state.market_trades.get(product, []), pstate,
                VELVET_OVERLAY.get("mode", "baseline"),
            )
            result[product] = orders

        # ---- 2) VOUCHER BS/IV state computation (once per tick) ----------
        mode = VOUCHER_OVERLAY.get("mode", "M0_old_zscore")
        # Underlying spot.
        velvet_depth = state.order_depths.get("VELVETFRUIT_EXTRACT")
        spot = get_mid(velvet_depth) if velvet_depth is not None else None
        ts = int(getattr(state, "timestamp", 0) or 0)
        observed_day = getattr(state, "day", None)
        day = _resolve_bs_day_index(pstate, ts, observed_day)
        tte_days = get_tte_days(day, ts)
        tte_years = max(1e-6, tte_days / 365.0)

        # Collect voucher mids/spreads for IV calibration.
        voucher_mids = {}
        voucher_spreads = {}
        for product in voucher_products:
            depth = state.order_depths.get(product)
            if depth is None:
                continue
            bb, _, ba, _ = get_best_bid_ask(depth)
            if bb is None or ba is None:
                continue
            K = get_voucher_strike(product)
            if K is None:
                continue
            voucher_mids[K] = (bb + ba) / 2.0
            voucher_spreads[K] = ba - bb
        bs_tick_count = int(pstate.get("BS_TICK_COUNT", 0))
        sigma = float(VOUCHER_BS["fallback_sigma"])
        n_valid = 0
        if spot is not None and spot > 0.0 and voucher_mids:
            sigma, n_valid = _bs_calibrate_sigma(spot, tte_years, voucher_mids,
                                                 voucher_spreads, pstate, bs_tick_count)
        pstate["BS_SIGMA"] = sigma
        pstate["BS_TICK_COUNT"] = bs_tick_count + 1
        pstate["BS_TTE_DAYS"] = tte_days
        pstate["BS_VALID_STRIKES"] = n_valid

        # Per-strike fair/delta cache for this tick.
        bs_fairs = {}
        bs_deltas = {}
        if spot is not None and spot > 0.0:
            for K in _BS_STRIKE_LIST:
                bs_fairs[K] = bs_call_price(spot, float(K), tte_years, sigma)
                bs_deltas[K] = bs_call_delta(spot, float(K), tte_years, sigma)
        current_net_delta = _net_delta_from_positions(
            state.position,
            bs_deltas,
            state.position.get("VELVETFRUIT_EXTRACT", 0),
        )
        if VOUCHER_BS.get("emit_diagnostics", False):
            pstate["BS_FAIRS"] = {str(k): round(v, 3) for k, v in bs_fairs.items()}
            pstate["BS_DELTAS"] = {str(k): round(v, 4) for k, v in bs_deltas.items()}

        # Bucket usage.
        bucket_used = _bucket_position_sums(state.position)
        bucket_caps = {
            "deep": int(VOUCHER_BS["bucket_cap_deep"]),
            "central": int(VOUCHER_BS["bucket_cap_central"]),
            "upper": int(VOUCHER_BS["bucket_cap_upper"]),
            "far": int(VOUCHER_BS["bucket_cap_far"]),
        }

        # ---- 3) VOUCHER ROUTING (per mode) -------------------------------
        # Build z-score orders for each voucher product first; the BS modes
        # decide whether to keep, gate, replace, or extend them.
        zscore_orders_by_product = {}
        zscore_state_updates = {}
        for product in voucher_products:
            depth = state.order_depths.get(product)
            if depth is None:
                zscore_orders_by_product[product] = []
                continue
            position = state.position.get(product, 0)
            limit = POS_LIMITS.get(product, 300)
            ema_mean = pstate.get(f"ZSCORE_MEAN_{product}", None)
            ema_std = pstate.get(f"ZSCORE_STD_{product}", None)
            zorders, new_ema_mean, new_ema_std = self._trade_zscore(
                product, depth, position, limit, ema_mean, ema_std,
                current_net_delta, bs_deltas,
            )
            zscore_state_updates[product] = (new_ema_mean, new_ema_std)
            zscore_orders_by_product[product] = zorders

        for product, (m, s) in zscore_state_updates.items():
            pstate[f"ZSCORE_MEAN_{product}"] = m
            pstate[f"ZSCORE_STD_{product}"] = s

        def _bucket_room(K):
            bucket = _BS_BUCKET_OF.get(K, "central")
            return max(0, bucket_caps.get(bucket, 0) - bucket_used.get(bucket, 0))

        def _shrink_zscore(orders, factor):
            if factor >= 1.0:
                return orders
            out = []
            for o in orders:
                q = int(round(int(o.quantity) * factor))
                if q == 0 and o.quantity != 0:
                    q = 1 if o.quantity > 0 else -1
                if q != 0:
                    out.append(Order(o.symbol, int(o.price), int(q)))
            return out

        def _projected_net_delta(extra_pos_changes):
            nd = float(state.position.get("VELVETFRUIT_EXTRACT", 0))
            for K in _BS_STRIKE_LIST:
                pos_now = int(state.position.get(f"VEV_{K}", 0))
                pos_now += int(extra_pos_changes.get(K, 0))
                d = bs_deltas.get(K, 0.0) or 0.0
                nd += pos_now * d
            return nd

        risk_mode = VOUCHER_RISK.get("mode", "M0_control")
        risk_modes = {
            "M0_control",
            "M1_diagnostics_only",
            "M2_upper_long_cap_250",
            "M3_upper_long_cap_200",
            "M4_5400_only_cap",
            "M5_5500_only_cap",
            "M6_terminal_upper_reduction",
            "M7_extreme_BS_veto_upper",
            "M8_extreme_BS_veto_all",
            "M9_net_delta_soft_cap",
            "M10_selective_combined",
        }
        risk_handled = risk_mode in risk_modes

        if risk_handled:
            risk_orders_by_product = {
                product: list(zscore_orders_by_product.get(product, []))
                for product in voucher_products
            }

            if risk_mode in ("M2_upper_long_cap_250", "M3_upper_long_cap_200"):
                cap = 250 if risk_mode == "M2_upper_long_cap_250" else 200
                for product in ("VEV_5400", "VEV_5500"):
                    risk_orders_by_product[product] = _clip_positive_inventory_orders(
                        risk_orders_by_product.get(product, []),
                        state.position.get(product, 0),
                        cap,
                    )

            elif risk_mode == "M4_5400_only_cap":
                risk_orders_by_product["VEV_5400"] = _clip_positive_inventory_orders(
                    risk_orders_by_product.get("VEV_5400", []),
                    state.position.get("VEV_5400", 0),
                    int(VOUCHER_RISK["upper_long_cap"]),
                )

            elif risk_mode == "M5_5500_only_cap":
                risk_orders_by_product["VEV_5500"] = _clip_positive_inventory_orders(
                    risk_orders_by_product.get("VEV_5500", []),
                    state.position.get("VEV_5500", 0),
                    int(VOUCHER_RISK["upper_long_cap"]),
                )

            elif risk_mode == "M6_terminal_upper_reduction":
                terminal_fraction = float(VOUCHER_RISK["terminal_fraction"])
                weak_edge = float(VOUCHER_RISK["terminal_min_buy_edge"])
                if float(ts) / 1_000_000.0 >= terminal_fraction:
                    for product in ("VEV_5400", "VEV_5500"):
                        K = get_voucher_strike(product)
                        depth = state.order_depths.get(product)
                        fair = bs_fairs.get(K)
                        best_bid, _, best_ask, _ = get_best_bid_ask(depth) if depth is not None else (None, 0, None, 0)
                        if best_ask is None or fair is None:
                            continue
                        if state.position.get(product, 0) > 0 and (float(fair) - float(best_ask)) < weak_edge:
                            risk_orders_by_product[product] = _drop_new_long_buy_orders(
                                risk_orders_by_product.get(product, []),
                                state.position.get(product, 0),
                            )

            elif risk_mode in ("M7_extreme_BS_veto_upper", "M8_extreme_BS_veto_all"):
                selected = (
                    ("VEV_5400", "VEV_5500")
                    if risk_mode == "M7_extreme_BS_veto_upper"
                    else tuple(f"VEV_{K}" for K in _BS_STRIKE_LIST)
                )
                edge = float(VOUCHER_RISK["bs_veto_edge"])
                for product in selected:
                    K = get_voucher_strike(product)
                    depth = state.order_depths.get(product)
                    if depth is None or K is None:
                        continue
                    if _bs_buy_veto_is_active(depth, bs_fairs.get(K), edge):
                        risk_orders_by_product[product] = _drop_new_long_buy_orders(
                            risk_orders_by_product.get(product, []),
                            state.position.get(product, 0),
                        )

            elif risk_mode == "M9_net_delta_soft_cap":
                risk_orders_by_product = _apply_net_delta_soft_cap(
                    risk_orders_by_product,
                    _projected_net_delta({k: 0 for k in _BS_STRIKE_LIST}),
                    bs_deltas,
                    int(VOUCHER_RISK["net_delta_cap"]),
                    VOUCHER_RISK["net_delta_priority"],
                )

            elif risk_mode == "M10_selective_combined":
                for product in ("VEV_5400", "VEV_5500"):
                    risk_orders_by_product[product] = _clip_positive_inventory_orders(
                        risk_orders_by_product.get(product, []),
                        state.position.get(product, 0),
                        int(VOUCHER_RISK["upper_long_cap"]),
                    )
                    K = get_voucher_strike(product)
                    depth = state.order_depths.get(product)
                    if depth is not None and K is not None and _bs_buy_veto_is_active(
                        depth, bs_fairs.get(K), float(VOUCHER_RISK["bs_veto_edge"])
                    ):
                        risk_orders_by_product[product] = _drop_new_long_buy_orders(
                            risk_orders_by_product.get(product, []),
                            state.position.get(product, 0),
                        )
                if VOUCHER_RISK.get("combined_use_net_delta", False):
                    risk_orders_by_product = _apply_net_delta_soft_cap(
                        risk_orders_by_product,
                        _projected_net_delta({k: 0 for k in _BS_STRIKE_LIST}),
                        bs_deltas,
                        int(VOUCHER_RISK["net_delta_cap"]),
                        VOUCHER_RISK["net_delta_priority"],
                    )

            for product in voucher_products:
                result[product] = risk_orders_by_product.get(product, [])

        if not risk_handled:
            delta_cap_active = (mode == "M6_bs_delta_capped")
            delta_cap = int(VOUCHER_BS["net_delta_cap"])

            for product in voucher_products:
                depth = state.order_depths.get(product)
                position = state.position.get(product, 0)
                limit = POS_LIMITS.get(product, 300)
                K = get_voucher_strike(product)
                zorders = zscore_orders_by_product[product]

                if mode == "M0_old_zscore":
                    result[product] = zorders
                    continue
                if mode == "M1_disabled":
                    result[product] = []
                    continue
                if mode == "M2_bs_diagnostics":
                    # Trade z-score; BS state already computed above.
                    result[product] = zorders
                    continue

                if mode in ("M3_bs_central", "M5_bs_central_5400", "M6_bs_delta_capped"):
                    if depth is None or spot is None or spot <= 0.0 or K is None:
                        result[product] = []
                        continue
                    # Default: BS replaces z-score. Decide per strike if active.
                    bucket = _BS_BUCKET_OF.get(K)
                    active = False
                    buy_only_5400 = False
                    if bucket == "central":
                        if K == 5000 and not VOUCHER_BS["include_5000"]:
                            active = False
                        elif K == 5100 and not VOUCHER_BS["include_5100"]:
                            active = False
                        elif K == 5200 and not VOUCHER_BS["include_5200"]:
                            active = False
                        elif K == 5300 and not VOUCHER_BS["include_5300"]:
                            active = False
                        else:
                            active = True
                    elif K == 5400 and mode in ("M5_bs_central_5400", "M6_bs_delta_capped"):
                        if VOUCHER_BS.get("include_5400_buy_only", False):
                            active = True
                            buy_only_5400 = True
                    else:
                        active = False
                    if not active:
                        result[product] = []
                        continue
                    bucket_room = _bucket_room(K)
                    if buy_only_5400:
                        bs_orders, _new_pos, _fair, _delta = _bs_voucher_orders_5400_buy(
                            product, depth, position, limit, spot, tte_years, sigma,
                            position, bucket_room
                        )
                    else:
                        bs_orders, _new_pos, _fair, _delta = _bs_voucher_orders_central(
                            product, K, depth, position, limit, spot, tte_years, sigma,
                            position, bucket_room
                        )
                    if delta_cap_active and bs_orders:
                        # Project delta with these orders applied; if it would
                        # exceed cap in the same direction, shrink/drop.
                        extras = {kk: 0 for kk in _BS_STRIKE_LIST}
                        extras[K] = sum(o.quantity for o in bs_orders)
                        nd = _projected_net_delta(extras)
                        if abs(nd) > delta_cap:
                            # Drop this strike's orders this tick to keep portfolio
                            # delta within cap. A more nuanced version would shrink
                            # by the responsible delta; we use a hard drop for
                            # transparency.
                            bs_orders = []
                    bucket_used[bucket] = bucket_used.get(bucket, 0) + sum(abs(int(o.quantity)) for o in bs_orders)
                    result[product] = bs_orders
                    continue

                if mode == "M4_bs_overlay_gate":
                    if depth is None or spot is None or K is None:
                        result[product] = zorders
                        continue
                    gated = _bs_apply_overlay_gate(zorders, depth, spot, K, tte_years, sigma)
                    result[product] = gated
                    continue

                if mode == "M7_zscore_shrunk_overlay":
                    if depth is None or spot is None or K is None:
                        result[product] = _shrink_zscore(zorders, float(VOUCHER_BS["zscore_shrink"]))
                        continue
                    shrunk = _shrink_zscore(zorders, float(VOUCHER_BS["zscore_shrink"]))
                    gated = _bs_apply_overlay_gate(shrunk, depth, spot, K, tte_years, sigma)
                    result[product] = gated
                    continue

                # Defensive default: behave like M0 if mode string is unknown.
                result[product] = zorders

        # ---- 4) Optional pstate diagnostics (compact, bounded) -----------
        if VOUCHER_BS.get("emit_diagnostics", False):
            pstate["BS_NET_DELTA"] = round(_projected_net_delta({k: 0 for k in _BS_STRIKE_LIST}), 2)
            pstate["BS_BUCKET_USED"] = {k: int(v) for k, v in bucket_used.items()}

        conversions = 0
        return result, conversions, json.dumps(pstate)
