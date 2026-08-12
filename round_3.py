# Round 3, Final Algorithm

## IMPORTS ##  ## IMPORTS ##  ## IMPORTS ##  ## IMPORTS ##  ## IMPORTS ##
from datamodel import OrderDepth, UserId, TradingState, Order
import numpy as np
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
    "EMA_ALPHA":         0.0002,  # shared alpha for hydrogel EMA, options EMA mean & EMA std
    "INITIAL_HYDRO_EMA": 9991,
    "ZSCORE_ENTRY":      1.5,     # enter when |z| exceeds this threshold
}

# Historical mean and std computed from days 0-2 (30k ticks each).
# Seed values for the EMA mean and EMA std on the very first tick.
# VEV_6000 and VEV_6500 are excluded — permanently at 0.5, std=0, untradeable.
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

class Trader:
    
    ## TRADE HYDROGEL ##     ## TRADE HYDROGEL ##
    def _trade_hydrogel(self, product, order_depth, position, limit, prev_hydro_ema, prev_bid, prev_ask):
        orders = []

        # Collect order book information
        if order_depth.buy_orders and order_depth.sell_orders:
            best_bid = max(order_depth.buy_orders.keys())
            bid_quantity = order_depth.buy_orders[best_bid]
            best_ask = min(order_depth.sell_orders.keys())
            ask_quantity = order_depth.sell_orders[best_ask]
        spread = best_ask - best_bid
        mid = round((best_ask + best_bid) / 2)

        # Set Caps
        buy_cap = limit - position
        sell_cap = limit + position

        # Calculate Parameters
        alpha = PARAMS.get('EMA_ALPHA')
        hydro_ema = prev_hydro_ema if prev_hydro_ema else PARAMS.get('INITIAL_HYDRO_EMA')
        new_hydro_ema = alpha * mid + (1 - alpha) * hydro_ema
        X = mid - new_hydro_ema

        ## Decrypt the spread scenario
        buy_spread = sell_spread = False
        if spread <= 9 and prev_bid and prev_ask:
            bid_shift = abs(best_bid - prev_bid)
            ask_shift = abs(best_ask - prev_ask)
            # Buy Signal - the ask has dropped while the bid has remained constant
            if ask_shift > bid_shift + 2:
                buy_spread = True
            # Sell signal - the bid has risen while the ask has remained constant
            elif bid_shift > ask_shift + 2:
                sell_spread = True
            # Mixed signal - the bid has risen while the ask has dropped
            else:
                buy_spread = sell_spread = True
        elif spread >= 15:
            prev_bid = best_bid
            prev_ask = best_ask


        # Target position and aggressiveness if we are far away 
        target_pos = -round(3.5*X)
        
        # Mean Reversion Logic
        thresh = 45
        if X > 5 and sell_spread:
            orders.append(Order(product, best_bid, -min(bid_quantity, sell_cap)))
        elif X > thresh:
            sell_quantity = max(min(bid_quantity, sell_cap, position-target_pos), 0)
            orders.append(Order(product, best_bid, -sell_quantity))
        elif X < -5 and buy_spread:
            orders.append(Order(product, best_ask, min(-ask_quantity, buy_cap)))
        elif X < -thresh:
            buy_quantity = max(min(-ask_quantity, buy_cap, target_pos-position), 0)
            orders.append(Order(product, best_ask, buy_quantity))

        return orders, new_hydro_ema, prev_bid, prev_ask

    ## TRADE Z-SCORE ##     ## TRADE Z-SCORE ##
    def _trade_zscore(self, product, order_depth, position, limit, ema_mean, ema_std):
        """
        Z-score mean reversion using EMA mean and EMA std (alpha = EMA_ALPHA).
        Both are seeded from historical priors on the first tick and updated
        every tick thereafter — no rolling window, just two floats in pstate.

        EMA std tracks the EMA of |deviation| (mean absolute deviation),
        which is robust and sign-symmetric.

        Buys aggressively (hits ask) when z < -ZSCORE_ENTRY.
        Sells aggressively (hits bid) when z > +ZSCORE_ENTRY.
        Returns: (orders, new_ema_mean, new_ema_std)
        """
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

        # Cold-start: seed from historical priors on the very first tick
        if ema_mean is None:
            ema_mean = prior["mean"]
        if ema_std is None:
            ema_std = prior["std"]

        # Update EMA mean
        new_ema_mean = alpha * mid + (1 - alpha) * ema_mean

        # Update EMA std as EMA of absolute deviation from the current mean
        deviation    = abs(mid - new_ema_mean)
        new_ema_std  = alpha * deviation + (1 - alpha) * ema_std

        # Guard against a degenerate flat series
        if new_ema_std < 1e-8:
            return orders, new_ema_mean, new_ema_std

        z = (mid - new_ema_mean) / new_ema_std

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

        # Load previous data
        pstate: dict = {}
        if state.traderData:
            try:
                pstate = json.loads(state.traderData)
            except Exception:
                pstate = {}

        options = [
            "VELVETFRUIT_EXTRACT",
            "VEV_4000", "VEV_4500", "VEV_5000",
            "VEV_5100", "VEV_5200", "VEV_5300",
            "VEV_5400", "VEV_5500",
            # VEV_6000, VEV_6500 excluded — permanently flat at 0.5, std=0
        ]

        # Run algorithms for all products
        for product, order_depth in state.order_depths.items():
            position = state.position.get(product, 0)
            limit    = POS_LIMITS.get(product, 20)

            if product == "HYDROGEL_PACK":
                prev_hydro_ema = pstate.get('HYDRO_EMA', None)
                prev_bid = pstate.get('HYDRO_BID', None)
                prev_ask = pstate.get('HYDRO_ASK', None)
                orders, new_hydro_ema, new_bid, new_ask = self._trade_hydrogel(
                    product, order_depth, position, limit,
                    prev_hydro_ema, prev_bid, prev_ask
                )
                pstate['HYDRO_EMA'] = new_hydro_ema
                pstate['HYDRO_BID'] = new_bid
                pstate['HYDRO_ASK'] = new_ask

            elif product in options:
                ema_mean = pstate.get(f"ZSCORE_MEAN_{product}", None)
                ema_std  = pstate.get(f"ZSCORE_STD_{product}",  None)
                orders, new_ema_mean, new_ema_std = self._trade_zscore(
                    product, order_depth, position, limit, ema_mean, ema_std
                )
                pstate[f"ZSCORE_MEAN_{product}"] = new_ema_mean
                pstate[f"ZSCORE_STD_{product}"]  = new_ema_std

            else:
                orders = []

            result[product] = orders

        # Return results
        conversions = 0
        return result, conversions, json.dumps(pstate)
