import base64
import json
import math
from typing import Optional

from datamodel import Order, OrderDepth, Symbol, TradingState


def best_bid_ask(order_depth: OrderDepth) -> tuple[Optional[int], Optional[int]]:
    best_bid = max(order_depth.buy_orders) if order_depth.buy_orders else None
    best_ask = min(order_depth.sell_orders) if order_depth.sell_orders else None
    return best_bid, best_ask


def mid_price(order_depth: OrderDepth) -> Optional[float]:
    best_bid, best_ask = best_bid_ask(order_depth)
    if best_bid is None or best_ask is None:
        return None
    return (best_bid + best_ask) / 2.0


def clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))


def clean_history(raw_values, history_limit: int) -> list[int]:
    cleaned: list[int] = []
    if not isinstance(raw_values, list):
        return cleaned
    for value in raw_values[-history_limit:]:
        try:
            cleaned.append(int(value))
        except (TypeError, ValueError):
            continue
    return cleaned


def clean_int16_history(raw_values, history_limit: int) -> list[int]:
    if isinstance(raw_values, str):
        try:
            raw_bytes = base64.b64decode(raw_values.encode("ascii"), validate=True)
        except Exception:
            return []
        if len(raw_bytes) % 2 != 0:
            return []
        values = [
            int.from_bytes(raw_bytes[index : index + 2], "big", signed=True)
            for index in range(0, len(raw_bytes), 2)
        ]
        return values[-history_limit:]
    return clean_history(raw_values, history_limit)


def dump_int16_history(values: list[int]) -> object:
    raw_bytes = bytearray()
    for value in values:
        if value < -32768 or value > 32767:
            return values
        raw_bytes.extend(value.to_bytes(2, "big", signed=True))
    return base64.b64encode(bytes(raw_bytes)).decode("ascii")


def clean_offset_int16_history(raw_values, history_limit: int) -> list[int]:
    if isinstance(raw_values, dict):
        try:
            offset = int(raw_values.get("o", 0))
            raw_data = raw_values.get("d", "")
            if not isinstance(raw_data, str):
                return []
            raw_bytes = base64.b64decode(raw_data.encode("ascii"), validate=True)
        except Exception:
            return []
        if len(raw_bytes) % 2 != 0:
            return []
        values = [
            int.from_bytes(raw_bytes[index : index + 2], "big", signed=True) + offset
            for index in range(0, len(raw_bytes), 2)
        ]
        return values[-history_limit:]
    return clean_int16_history(raw_values, history_limit)


def dump_offset_int16_history(values: list[int]) -> object:
    if not values:
        return ""
    lower = min(values)
    upper = max(values)
    offset = (lower + upper) // 2
    shifted_values = [value - offset for value in values]
    raw_bytes = bytearray()
    for value in shifted_values:
        if value < -32768 or value > 32767:
            return values
        raw_bytes.extend(value.to_bytes(2, "big", signed=True))
    return {"o": offset, "d": base64.b64encode(bytes(raw_bytes)).decode("ascii")}


def rolling_z_score(
    history: list[int],
    current_residual: int,
    window: int,
    min_history: int,
    min_std: float,
    residual_scale: int,
) -> Optional[float]:
    lookback = history[-window:]
    if len(lookback) < min_history:
        return None

    mean = sum(lookback) / len(lookback)
    mean_square = sum(value * value for value in lookback) / len(lookback)
    variance = max(0.0, mean_square - mean * mean)
    std = math.sqrt(variance)
    if std < min_std * residual_scale:
        return None

    return (current_residual - mean) / std


def residual_std_score(
    history: list[int],
    current_residual: int,
    window: int,
    min_history: int,
) -> Optional[float]:
    lookback = history[-window:]
    if len(lookback) < min_history:
        return None

    mean = sum(lookback) / len(lookback)
    mean_square = sum(value * value for value in lookback) / len(lookback)
    variance = max(0.0, mean_square - mean * mean)
    std = math.sqrt(variance)
    if std <= 0.0:
        return None

    return current_residual / std


def rolling_spread_z_score(
    history: list[int],
    current_value: int,
    window: int,
    min_history: int,
) -> Optional[float]:
    lookback = history[-window:]
    if len(lookback) < min_history:
        return None

    mean = sum(lookback) / len(lookback)
    mean_square = sum(value * value for value in lookback) / len(lookback)
    variance = max(0.0, mean_square - mean * mean)
    std = math.sqrt(variance)
    if std <= 0.0:
        return None

    return (current_value - mean) / std


def order_to_target(
    product: Symbol,
    order_depth: OrderDepth,
    current_position: int,
    target_position: int,
    position_limit: int,
    max_order_size: int,
) -> list[Order]:
    orders: list[Order] = []
    target_position = clamp(target_position, -position_limit, position_limit)
    desired_delta = target_position - current_position
    if desired_delta == 0:
        return orders

    best_bid, best_ask = best_bid_ask(order_depth)
    if desired_delta > 0:
        if best_ask is None:
            return orders
        visible_volume = max(0, -order_depth.sell_orders.get(best_ask, 0))
        limit_room = max(0, position_limit - current_position)
        quantity = min(desired_delta, visible_volume, limit_room, max_order_size)
        if quantity > 0:
            orders.append(Order(product, best_ask, quantity))
        return orders

    if best_bid is None:
        return orders
    visible_volume = max(0, order_depth.buy_orders.get(best_bid, 0))
    limit_room = max(0, position_limit + current_position)
    quantity = min(-desired_delta, visible_volume, limit_room, max_order_size)
    if quantity > 0:
        orders.append(Order(product, best_bid, -quantity))
    return orders


def market_make(
    product: Symbol,
    order_depth: OrderDepth,
    current_position: int,
    position_limit: int,
    max_order_size: int,
) -> list[Order]:
    orders: list[Order] = []
    best_bid, best_ask = best_bid_ask(order_depth)
    if best_bid is None or best_ask is None:
        return orders
    bid_price = best_bid + 1
    ask_price = best_ask - 1
    if bid_price >= ask_price:
        return orders
    buy_room = max(0, position_limit - current_position)
    buy_quantity = min(buy_room, max_order_size)
    if buy_quantity > 0:
        orders.append(Order(product, bid_price, buy_quantity))
    sell_room = max(0, position_limit + current_position)
    sell_quantity = min(sell_room, max_order_size)
    if sell_quantity > 0:
        orders.append(Order(product, ask_price, -sell_quantity))
    return orders


class PebblesModule:
    PRODUCTS: tuple[Symbol, ...] = (
        "PEBBLES_XS",
        "PEBBLES_S",
        "PEBBLES_M",
        "PEBBLES_L",
        "PEBBLES_XL",
    )

    WINDOW = 500
    MIN_HISTORY = 125
    ENTRY_Z = 2.35
    HOLD_TO_FLIP = True
    EXIT_Z: Optional[float] = None

    MIN_STD = 1.0
    TARGET_SIZE = 10
    POSITION_LIMIT = 10
    MAX_ORDER_SIZE = 10
    HISTORY_LIMIT = 500
    RESIDUAL_SCALE = 10

    def empty_state(self) -> tuple[dict[Symbol, list[int]], dict[Symbol, int]]:
        return {product: [] for product in self.PRODUCTS}, {product: 0 for product in self.PRODUCTS}

    def load_state(self, loaded) -> tuple[dict[Symbol, list[int]], dict[Symbol, int]]:
        histories, targets = self.empty_state()
        if not isinstance(loaded, dict):
            return histories, targets

        raw_histories = loaded.get("h", {})
        if isinstance(raw_histories, dict):
            for product in self.PRODUCTS:
                histories[product] = clean_history(raw_histories.get(product, []), self.HISTORY_LIMIT)

        raw_targets = loaded.get("t", {})
        if isinstance(raw_targets, dict):
            for product in self.PRODUCTS:
                try:
                    target = int(raw_targets.get(product, 0))
                except (TypeError, ValueError):
                    target = 0
                targets[product] = clamp(target, -self.TARGET_SIZE, self.TARGET_SIZE)

        return histories, targets

    def dump_state(self, histories: dict[Symbol, list[int]], targets: dict[Symbol, int]) -> dict:
        return {
            "h": {product: histories.get(product, [])[-self.HISTORY_LIMIT:] for product in self.PRODUCTS},
            "t": {product: int(targets.get(product, 0)) for product in self.PRODUCTS},
        }

    def target_from_signal(self, previous_target: int, z_score: Optional[float], has_min_history: bool) -> int:
        if not has_min_history or z_score is None:
            return 0 if not has_min_history else previous_target
        if z_score > self.ENTRY_Z:
            return -self.TARGET_SIZE
        if z_score < -self.ENTRY_Z:
            return self.TARGET_SIZE
        if not self.HOLD_TO_FLIP and self.EXIT_Z is not None and abs(z_score) < self.EXIT_Z:
            return 0
        return previous_target

    def run(
        self,
        state: TradingState,
        histories: dict[Symbol, list[int]],
        targets: dict[Symbol, int],
        result: dict[Symbol, list[Order]],
    ) -> dict[Symbol, int]:
        mids: dict[Symbol, float] = {}
        for product in self.PRODUCTS:
            order_depth = state.order_depths.get(product)
            if order_depth is None:
                return targets
            mid = mid_price(order_depth)
            if mid is None:
                return targets
            mids[product] = mid

        group_mean = sum(mids.values()) / len(self.PRODUCTS)
        residuals = {
            product: int(round((mids[product] - group_mean) * self.RESIDUAL_SCALE))
            for product in self.PRODUCTS
        }

        next_targets: dict[Symbol, int] = {}
        for product in self.PRODUCTS:
            history = histories[product]
            has_min_history = len(history) >= self.MIN_HISTORY
            z_score = rolling_z_score(
                history,
                residuals[product],
                self.WINDOW,
                self.MIN_HISTORY,
                self.MIN_STD,
                self.RESIDUAL_SCALE,
            )
            next_targets[product] = self.target_from_signal(targets.get(product, 0), z_score, has_min_history)

        for product in self.PRODUCTS:
            orders = order_to_target(
                product,
                state.order_depths[product],
                state.position.get(product, 0),
                next_targets[product],
                self.POSITION_LIMIT,
                self.MAX_ORDER_SIZE,
            )
            if orders:
                result[product] = orders

        for product in self.PRODUCTS:
            history = histories[product]
            history.append(residuals[product])
            if len(history) > self.HISTORY_LIMIT:
                del history[: len(history) - self.HISTORY_LIMIT]

        return next_targets


class TranslatorModule:
    PRODUCTS: tuple[Symbol, ...] = (
        "TRANSLATOR_SPACE_GRAY",
        "TRANSLATOR_ASTRO_BLACK",
        "TRANSLATOR_ECLIPSE_CHARCOAL",
        "TRANSLATOR_GRAPHITE_MIST",
        "TRANSLATOR_VOID_BLUE",
    )

    WINDOW = 1200
    MIN_HISTORY = 1200
    ENTRY_Z = 1.75
    HOLD_TO_FLIP = True
    EXIT_Z: Optional[float] = None

    MIN_STD = 1.0
    TARGET_SIZE = 10
    POSITION_LIMIT = 10
    MAX_ORDER_SIZE = 10
    HISTORY_LIMIT = 1200
    RESIDUAL_SCALE = 10
    PAIR_CONFIGS: dict[str, tuple[tuple[str, Symbol, Symbol, int, int, float], ...]] = {
        "3pair": (
            ("ab_gm", "TRANSLATOR_ASTRO_BLACK", "TRANSLATOR_GRAPHITE_MIST", 500, 500, 2.00),
            ("ec_vb", "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_VOID_BLUE", 500, 500, 2.75),
            ("sg_ec", "TRANSLATOR_SPACE_GRAY", "TRANSLATOR_ECLIPSE_CHARCOAL", 250, 250, 3.25),
        ),
        "4pair": (
            ("ab_ec", "TRANSLATOR_ASTRO_BLACK", "TRANSLATOR_ECLIPSE_CHARCOAL", 500, 500, 3.25),
            ("ab_gm", "TRANSLATOR_ASTRO_BLACK", "TRANSLATOR_GRAPHITE_MIST", 500, 500, 2.00),
            ("ec_vb", "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_VOID_BLUE", 500, 500, 2.75),
            ("sg_ec", "TRANSLATOR_SPACE_GRAY", "TRANSLATOR_ECLIPSE_CHARCOAL", 250, 250, 3.25),
        ),
        "off": (),
    }
    CONFIG_NAME = "current"
    PAIRS: tuple[tuple[str, Symbol, Symbol, int, int, float], ...] = ()

    @classmethod
    def resolve_config(cls) -> tuple[str, tuple[tuple[str, Symbol, Symbol, int, int, float], ...]]:
        return "4pair", cls.PAIR_CONFIGS["4pair"]

    def empty_state(self) -> tuple[dict[Symbol, list[int]], dict[Symbol, int]]:
        if self.CONFIG_NAME != "current":
            return (
                {name: [] for name, *_ in self.PAIRS},
                {name: 0 for name, *_ in self.PAIRS},
            )
        return {product: [] for product in self.PRODUCTS}, {product: 0 for product in self.PRODUCTS}

    def load_state(self, loaded) -> tuple[dict[Symbol, list[int]], dict[Symbol, int]]:
        histories, targets = self.empty_state()
        if not isinstance(loaded, dict):
            return histories, targets

        raw_histories = loaded.get("h", {})
        if isinstance(raw_histories, dict):
            if self.CONFIG_NAME == "current":
                for product in self.PRODUCTS:
                    histories[product] = clean_history(raw_histories.get(product, []), self.HISTORY_LIMIT)
            else:
                for name, _, _, window, _, _ in self.PAIRS:
                    histories[name] = clean_int16_history(raw_histories.get(name, []), window)

        raw_targets = loaded.get("t", {})
        if isinstance(raw_targets, dict):
            target_names = self.PRODUCTS if self.CONFIG_NAME == "current" else tuple(name for name, *_ in self.PAIRS)
            for product in target_names:
                try:
                    target = int(raw_targets.get(product, 0))
                except (TypeError, ValueError):
                    target = 0
                targets[product] = clamp(target, -self.TARGET_SIZE, self.TARGET_SIZE)

        return histories, targets

    def dump_state(self, histories: dict[Symbol, list[int]], targets: dict[Symbol, int]) -> dict:
        if self.CONFIG_NAME != "current":
            return {
                "h": {
                    name: dump_int16_history(histories.get(name, [])[-window:])
                    for name, _, _, window, _, _ in self.PAIRS
                },
                "t": {name: int(targets.get(name, 0)) for name, *_ in self.PAIRS},
            }
        return {
            "h": {product: histories.get(product, [])[-self.HISTORY_LIMIT:] for product in self.PRODUCTS},
            "t": {product: int(targets.get(product, 0)) for product in self.PRODUCTS},
        }

    def target_from_signal(
        self,
        previous_target: int,
        z_score: Optional[float],
        has_min_history: bool,
        entry_z: Optional[float] = None,
    ) -> int:
        if not has_min_history or z_score is None:
            return 0 if not has_min_history else previous_target
        threshold = self.ENTRY_Z if entry_z is None else entry_z
        if z_score > threshold:
            return -self.TARGET_SIZE
        if z_score < -threshold:
            return self.TARGET_SIZE
        if not self.HOLD_TO_FLIP and self.EXIT_Z is not None and abs(z_score) < self.EXIT_Z:
            return 0
        return previous_target

    def run(
        self,
        state: TradingState,
        histories: dict[Symbol, list[int]],
        targets: dict[Symbol, int],
        result: dict[Symbol, list[Order]],
    ) -> dict[Symbol, int]:
        if self.CONFIG_NAME != "current":
            return self.run_pair_network(state, histories, targets, result)

        mids: dict[Symbol, float] = {}
        for product in self.PRODUCTS:
            order_depth = state.order_depths.get(product)
            if order_depth is None:
                return targets
            mid = mid_price(order_depth)
            if mid is None:
                return targets
            mids[product] = mid

        group_mean = sum(mids.values()) / len(self.PRODUCTS)
        residuals = {
            product: int(round((mids[product] - group_mean) * self.RESIDUAL_SCALE))
            for product in self.PRODUCTS
        }

        next_targets: dict[Symbol, int] = {}
        for product in self.PRODUCTS:
            history = histories[product]
            has_min_history = len(history) >= self.MIN_HISTORY
            z_score = rolling_z_score(
                history,
                residuals[product],
                self.WINDOW,
                self.MIN_HISTORY,
                self.MIN_STD,
                self.RESIDUAL_SCALE,
            )
            next_targets[product] = self.target_from_signal(targets.get(product, 0), z_score, has_min_history)

        for product in self.PRODUCTS:
            orders = order_to_target(
                product,
                state.order_depths[product],
                state.position.get(product, 0),
                next_targets[product],
                self.POSITION_LIMIT,
                self.MAX_ORDER_SIZE,
            )
            if orders:
                result[product] = orders

        for product in self.PRODUCTS:
            history = histories[product]
            history.append(residuals[product])
            if len(history) > self.HISTORY_LIMIT:
                del history[: len(history) - self.HISTORY_LIMIT]

        return next_targets

    def run_pair_network(
        self,
        state: TradingState,
        histories: dict[Symbol, list[int]],
        targets: dict[Symbol, int],
        result: dict[Symbol, list[Order]],
    ) -> dict[Symbol, int]:
        next_targets: dict[Symbol, int] = {name: targets.get(name, 0) for name, *_ in self.PAIRS}
        spreads: dict[str, int] = {}
        active_pairs: list[tuple[str, Symbol, Symbol, int, int, float]] = []

        for pair in self.PAIRS:
            name, prod_a, prod_b, window, min_history, entry_z = pair
            depth_a = state.order_depths.get(prod_a)
            depth_b = state.order_depths.get(prod_b)
            if depth_a is None or depth_b is None:
                continue
            mid_a = mid_price(depth_a)
            mid_b = mid_price(depth_b)
            if mid_a is None or mid_b is None:
                continue

            spread = int(round((mid_a - mid_b) * self.RESIDUAL_SCALE))
            history = histories[name]
            has_min_history = len(history) >= min_history
            z_score = rolling_spread_z_score(history, spread, window, min_history)
            next_targets[name] = self.target_from_signal(
                targets.get(name, 0), z_score, has_min_history, entry_z
            )
            spreads[name] = spread
            active_pairs.append(pair)

        aggregate_targets = {product: 0 for product in self.PRODUCTS}
        for name, prod_a, prod_b, _, _, _ in active_pairs:
            pair_target = next_targets[name]
            aggregate_targets[prod_a] += pair_target
            aggregate_targets[prod_b] -= pair_target
        for product in aggregate_targets:
            aggregate_targets[product] = clamp(
                aggregate_targets[product], -self.POSITION_LIMIT, self.POSITION_LIMIT
            )

        for product in self.PRODUCTS:
            depth = state.order_depths.get(product)
            if depth is None:
                continue
            orders = order_to_target(
                product,
                depth,
                state.position.get(product, 0),
                aggregate_targets[product],
                self.POSITION_LIMIT,
                self.MAX_ORDER_SIZE,
            )
            if orders:
                result[product] = orders

        for name, _, _, window, _, _ in active_pairs:
            history = histories[name]
            history.append(spreads[name])
            if len(history) > window:
                del history[: len(history) - window]

        return next_targets


TranslatorModule.CONFIG_NAME, TranslatorModule.PAIRS = TranslatorModule.resolve_config()


_MICROCHIP_PAIR_LIBRARY: dict[str, tuple[tuple[str, Symbol, Symbol, int, int, float], ...]] = {
    "ot": (
        ("ot", "MICROCHIP_OVAL", "MICROCHIP_TRIANGLE", 1000, 1000, 1.50),
    ),
    "ot_cr_sr": (
        ("ot", "MICROCHIP_OVAL", "MICROCHIP_TRIANGLE", 1000, 1000, 1.50),
        ("cr", "MICROCHIP_CIRCLE", "MICROCHIP_RECTANGLE", 1000, 1000, 1.25),
        ("sr", "MICROCHIP_SQUARE", "MICROCHIP_RECTANGLE", 2500, 2500, 3.00),
    ),
    "ot_cr_cs": (
        ("ot", "MICROCHIP_OVAL", "MICROCHIP_TRIANGLE", 1000, 1000, 1.50),
        ("cr", "MICROCHIP_CIRCLE", "MICROCHIP_RECTANGLE", 1000, 1000, 1.25),
        ("cs", "MICROCHIP_CIRCLE", "MICROCHIP_SQUARE", 250, 250, 3.00),
    ),
    "ot_cr_cs_sr": (
        ("ot", "MICROCHIP_OVAL", "MICROCHIP_TRIANGLE", 1000, 1000, 1.50),
        ("cr", "MICROCHIP_CIRCLE", "MICROCHIP_RECTANGLE", 1000, 1000, 1.25),
        ("cs", "MICROCHIP_CIRCLE", "MICROCHIP_SQUARE", 250, 250, 3.00),
        ("sr", "MICROCHIP_SQUARE", "MICROCHIP_RECTANGLE", 2500, 2500, 3.00),
    ),
    "off": (),
}


def _resolve_microchip_config() -> tuple[str, tuple[tuple[str, Symbol, Symbol, int, int, float], ...]]:
    return "ot_cr_sr", _MICROCHIP_PAIR_LIBRARY["ot_cr_sr"]


class MicrochipModule:
    PRODUCTS_ALL: tuple[Symbol, ...] = (
        "MICROCHIP_CIRCLE",
        "MICROCHIP_OVAL",
        "MICROCHIP_RECTANGLE",
        "MICROCHIP_SQUARE",
        "MICROCHIP_TRIANGLE",
    )
    CONFIG_NAME, PAIRS = _resolve_microchip_config()

    TARGET_SIZE = 10
    POSITION_LIMIT = 10
    MAX_ORDER_SIZE = 10
    RESIDUAL_SCALE = 10

    def empty_state(self) -> tuple[dict[str, list[int]], dict[str, int]]:
        return (
            {name: [] for name, *_ in self.PAIRS},
            {name: 0 for name, *_ in self.PAIRS},
        )

    def load_state(self, loaded) -> tuple[dict[str, list[int]], dict[str, int]]:
        histories, targets = self.empty_state()
        if not isinstance(loaded, dict):
            return histories, targets

        raw_histories = loaded.get("h", {})
        if isinstance(raw_histories, dict):
            for name, _, _, window, _, _ in self.PAIRS:
                histories[name] = clean_int16_history(raw_histories.get(name, []), window)

        raw_targets = loaded.get("t", {})
        if isinstance(raw_targets, dict):
            for name, *_ in self.PAIRS:
                try:
                    target = int(raw_targets.get(name, 0))
                except (TypeError, ValueError):
                    target = 0
                targets[name] = clamp(target, -self.TARGET_SIZE, self.TARGET_SIZE)

        return histories, targets

    def dump_state(self, histories: dict[str, list[int]], targets: dict[str, int]) -> dict:
        return {
            "h": {
                name: dump_int16_history(histories.get(name, [])[-window:])
                for name, _, _, window, *_ in self.PAIRS
            },
            "t": {name: int(targets.get(name, 0)) for name, *_ in self.PAIRS},
        }

    def target_from_signal(
        self,
        previous_target: int,
        z_score: Optional[float],
        has_min_history: bool,
        entry_z: float,
    ) -> int:
        if not has_min_history or z_score is None:
            return 0 if not has_min_history else previous_target
        if z_score > entry_z:
            return -self.TARGET_SIZE
        if z_score < -entry_z:
            return self.TARGET_SIZE
        return previous_target

    def run(
        self,
        state: TradingState,
        histories: dict[str, list[int]],
        targets: dict[str, int],
        result: dict[Symbol, list[Order]],
    ) -> dict[str, int]:
        next_targets: dict[str, int] = {name: targets.get(name, 0) for name, *_ in self.PAIRS}
        diffs: dict[str, int] = {}
        active_pairs: list[tuple[str, Symbol, Symbol, int, int, float]] = []

        for pair in self.PAIRS:
            name, prod_a, prod_b, window, min_history, entry_z = pair
            depth_a = state.order_depths.get(prod_a)
            depth_b = state.order_depths.get(prod_b)
            if depth_a is None or depth_b is None:
                continue
            mid_a = mid_price(depth_a)
            mid_b = mid_price(depth_b)
            if mid_a is None or mid_b is None:
                continue

            diff = int(round((mid_a - mid_b) * self.RESIDUAL_SCALE))
            history = histories[name]
            has_min_history = len(history) >= min_history
            z_score = rolling_spread_z_score(history, diff, window, min_history)
            next_targets[name] = self.target_from_signal(
                targets.get(name, 0), z_score, has_min_history, entry_z
            )
            diffs[name] = diff
            active_pairs.append(pair)

        aggregate_targets = {product: 0 for product in self.PRODUCTS_ALL}
        for pair in active_pairs:
            name, prod_a, prod_b, *_ = pair
            pair_target = next_targets[name]
            aggregate_targets[prod_a] += pair_target
            aggregate_targets[prod_b] -= pair_target
        for product in aggregate_targets:
            aggregate_targets[product] = clamp(
                aggregate_targets[product], -self.POSITION_LIMIT, self.POSITION_LIMIT
            )

        for product in self.PRODUCTS_ALL:
            depth = state.order_depths.get(product)
            if depth is None:
                continue
            orders = order_to_target(
                product,
                depth,
                state.position.get(product, 0),
                aggregate_targets[product],
                self.POSITION_LIMIT,
                self.MAX_ORDER_SIZE,
            )
            if orders:
                result[product] = orders

        for name, _, _, window, _, _ in active_pairs:
            history = histories[name]
            history.append(diffs[name])
            if len(history) > window:
                del history[: len(history) - window]

        return next_targets


class RobotModule:
    PRODUCTS: tuple[Symbol, ...] = (
        "ROBOT_DISHES",
        "ROBOT_LAUNDRY",
        "ROBOT_MOPPING",
        "ROBOT_VACUUMING",
    )
    PAIRS: tuple[tuple[str, Symbol, Symbol, int, int, float], ...] = (
        ("lv", "ROBOT_LAUNDRY", "ROBOT_VACUUMING", 2000, 2000, 2.25),
        ("dm", "ROBOT_DISHES", "ROBOT_MOPPING", 500, 500, 3.00),
    )

    TARGET_SIZE = 10
    POSITION_LIMIT = 10
    MAX_ORDER_SIZE = 10
    RESIDUAL_SCALE = 10

    def empty_state(self) -> tuple[dict[str, list[int]], dict[str, int]]:
        return (
            {name: [] for name, *_ in self.PAIRS},
            {name: 0 for name, *_ in self.PAIRS},
        )

    def load_state(self, loaded) -> tuple[dict[str, list[int]], dict[str, int]]:
        histories, targets = self.empty_state()
        if not isinstance(loaded, dict):
            return histories, targets

        raw_histories = loaded.get("h", {})
        if isinstance(raw_histories, dict):
            for name, _, _, window, _, _ in self.PAIRS:
                histories[name] = clean_history(raw_histories.get(name, []), window)
        else:
            histories["lv"] = clean_history(raw_histories, 2000)

        raw_targets = loaded.get("t", {})
        if isinstance(raw_targets, dict):
            for name, *_ in self.PAIRS:
                try:
                    target = int(raw_targets.get(name, 0))
                except (TypeError, ValueError):
                    target = 0
                targets[name] = clamp(target, -self.TARGET_SIZE, self.TARGET_SIZE)
            if "lv" not in raw_targets:
                try:
                    laundry_target = int(raw_targets.get("ROBOT_LAUNDRY", 0))
                except (TypeError, ValueError):
                    laundry_target = 0
                targets["lv"] = clamp(laundry_target, -self.TARGET_SIZE, self.TARGET_SIZE)

        return histories, targets

    def dump_state(self, histories: dict[str, list[int]], targets: dict[str, int]) -> dict:
        return {
            "h": {name: histories.get(name, [])[-window:] for name, _, _, window, *_ in self.PAIRS},
            "t": {name: int(targets.get(name, 0)) for name, *_ in self.PAIRS},
        }

    def target_from_signal(
        self,
        previous_target: int,
        z_score: Optional[float],
        has_min_history: bool,
        entry_z: float,
    ) -> int:
        if not has_min_history or z_score is None:
            return 0 if not has_min_history else previous_target
        if z_score > entry_z:
            return -self.TARGET_SIZE
        if z_score < -entry_z:
            return self.TARGET_SIZE
        return previous_target

    def run(
        self,
        state: TradingState,
        histories: dict[str, list[int]],
        targets: dict[str, int],
        result: dict[Symbol, list[Order]],
    ) -> dict[str, int]:
        next_targets: dict[str, int] = {name: targets.get(name, 0) for name, *_ in self.PAIRS}
        diffs: dict[str, int] = {}
        active_pairs: list[tuple[str, Symbol, Symbol, int, int, float]] = []

        for pair in self.PAIRS:
            name, prod_a, prod_b, window, min_history, entry_z = pair
            depth_a = state.order_depths.get(prod_a)
            depth_b = state.order_depths.get(prod_b)
            if depth_a is None or depth_b is None:
                continue
            mid_a = mid_price(depth_a)
            mid_b = mid_price(depth_b)
            if mid_a is None or mid_b is None:
                continue

            diff = int(round((mid_a - mid_b) * self.RESIDUAL_SCALE))
            history = histories[name]
            has_min_history = len(history) >= min_history
            z_score = rolling_spread_z_score(history, diff, window, min_history)
            next_targets[name] = self.target_from_signal(
                targets.get(name, 0), z_score, has_min_history, entry_z
            )
            diffs[name] = diff
            active_pairs.append(pair)

        aggregate_targets = {product: 0 for product in self.PRODUCTS}
        for name, prod_a, prod_b, _, _, _ in active_pairs:
            pair_target = next_targets[name]
            aggregate_targets[prod_a] += pair_target
            aggregate_targets[prod_b] -= pair_target
        for product in self.PRODUCTS:
            target = clamp(aggregate_targets[product], -self.POSITION_LIMIT, self.POSITION_LIMIT)
            orders = order_to_target(
                product,
                state.order_depths[product],
                state.position.get(product, 0),
                target,
                self.POSITION_LIMIT,
                self.MAX_ORDER_SIZE,
            )
            if orders:
                result[product] = orders

        for name, _, _, window, _, _ in active_pairs:
            history = histories[name]
            history.append(diffs[name])
            if len(history) > window:
                del history[: len(history) - window]

        return next_targets


class SnackpackEwmaModule:
    PRODUCTS: tuple[Symbol, ...] = (
        "SNACKPACK_CHOCOLATE",
        "SNACKPACK_VANILLA",
        "SNACKPACK_PISTACHIO",
        "SNACKPACK_STRAWBERRY",
        "SNACKPACK_RASPBERRY",
    )
    PAIRS: tuple[tuple[str, Symbol, Symbol], ...] = (
        ("cv", "SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA"),
        ("rs", "SNACKPACK_RASPBERRY", "SNACKPACK_STRAWBERRY"),
        ("pr", "SNACKPACK_PISTACHIO", "SNACKPACK_RASPBERRY"),
    )

    EMA_ALPHA = 0.00005
    ROLLING_STD_WINDOW = 1000
    MIN_HISTORY = 500
    ENTRY_Z = 2.75
    TARGET_SIZE = 10
    POSITION_LIMIT = 10
    MAX_ORDER_SIZE = 10
    HISTORY_LIMIT = 1000
    RESIDUAL_SCALE = 10

    def empty_state(self) -> tuple[dict[str, list[int]], dict[str, float], dict[str, int]]:
        return (
            {pair_name: [] for pair_name, _, _ in self.PAIRS},
            {},
            {pair_name: 0 for pair_name, _, _ in self.PAIRS},
        )

    def load_state(self, loaded) -> tuple[dict[str, list[int]], dict[str, float], dict[str, int]]:
        histories, emas, pair_states = self.empty_state()
        if not isinstance(loaded, dict):
            return histories, emas, pair_states

        raw_histories = loaded.get("h", {})
        if isinstance(raw_histories, dict):
            for pair_name, _, _ in self.PAIRS:
                histories[pair_name] = clean_history(raw_histories.get(pair_name, []), self.HISTORY_LIMIT)

        raw_emas = loaded.get("e", {})
        if isinstance(raw_emas, dict):
            for pair_name, _, _ in self.PAIRS:
                try:
                    emas[pair_name] = float(raw_emas[pair_name])
                except (KeyError, TypeError, ValueError):
                    continue

        raw_pair_states = loaded.get("s", {})
        if isinstance(raw_pair_states, dict):
            for pair_name, _, _ in self.PAIRS:
                try:
                    pair_state = int(raw_pair_states.get(pair_name, 0))
                except (TypeError, ValueError):
                    pair_state = 0
                pair_states[pair_name] = clamp(pair_state, -1, 1)

        return histories, emas, pair_states

    def dump_state(
        self,
        histories: dict[str, list[int]],
        emas: dict[str, float],
        pair_states: dict[str, int],
    ) -> dict:
        return {
            "h": {pair_name: histories.get(pair_name, [])[-self.HISTORY_LIMIT:] for pair_name, _, _ in self.PAIRS},
            "e": {pair_name: float(emas[pair_name]) for pair_name, _, _ in self.PAIRS if pair_name in emas},
            "s": {pair_name: int(pair_states.get(pair_name, 0)) for pair_name, _, _ in self.PAIRS},
        }

    def next_pair_state(self, current_state: int, residual: float, z_score: Optional[float]) -> int:
        if current_state == 1:
            return 0 if residual >= 0.0 else current_state
        if current_state == -1:
            return 0 if residual <= 0.0 else current_state
        if z_score is None:
            return 0
        if z_score > self.ENTRY_Z:
            return -1
        if z_score < -self.ENTRY_Z:
            return 1
        return 0

    def run(
        self,
        state: TradingState,
        histories: dict[str, list[int]],
        emas: dict[str, float],
        pair_states: dict[str, int],
        result: dict[Symbol, list[Order]],
    ) -> dict[str, int]:
        mids: dict[Symbol, float] = {}
        for product in self.PRODUCTS:
            order_depth = state.order_depths.get(product)
            if order_depth is None:
                return pair_states
            mid = mid_price(order_depth)
            if mid is None:
                return pair_states
            mids[product] = mid

        diffs: dict[str, float] = {}
        scaled_residuals: dict[str, int] = {}
        next_pair_states: dict[str, int] = {}

        for pair_name, product_a, product_b in self.PAIRS:
            diff = mids[product_a] - mids[product_b]
            if pair_name not in emas:
                emas[pair_name] = diff

            residual = diff - emas[pair_name]
            scaled_residual = int(round(residual * self.RESIDUAL_SCALE))
            z_score = residual_std_score(
                histories[pair_name],
                scaled_residual,
                self.ROLLING_STD_WINDOW,
                self.MIN_HISTORY,
            )

            diffs[pair_name] = diff
            scaled_residuals[pair_name] = scaled_residual
            next_pair_states[pair_name] = self.next_pair_state(pair_states.get(pair_name, 0), residual, z_score)

        aggregate_targets = {product: 0 for product in self.PRODUCTS}
        for pair_name, product_a, product_b in self.PAIRS:
            pair_state = next_pair_states[pair_name]
            if pair_state == 0:
                continue
            aggregate_targets[product_a] += pair_state * self.TARGET_SIZE
            aggregate_targets[product_b] -= pair_state * self.TARGET_SIZE

        for product in self.PRODUCTS:
            target = clamp(aggregate_targets[product], -self.POSITION_LIMIT, self.POSITION_LIMIT)
            orders = order_to_target(
                product,
                state.order_depths[product],
                state.position.get(product, 0),
                target,
                self.POSITION_LIMIT,
                self.MAX_ORDER_SIZE,
            )
            if orders:
                result[product] = orders

        for pair_name, _, _ in self.PAIRS:
            history = histories[pair_name]
            history.append(scaled_residuals[pair_name])
            if len(history) > self.HISTORY_LIMIT:
                del history[: len(history) - self.HISTORY_LIMIT]
            emas[pair_name] += self.EMA_ALPHA * (diffs[pair_name] - emas[pair_name])

        return next_pair_states


class SleepPodModule:
    PRODUCTS: tuple[Symbol, ...] = (
        "SLEEP_POD_POLYESTER",
        "SLEEP_POD_COTTON",
        "SLEEP_POD_LAMB_WOOL",
        "SLEEP_POD_NYLON",
        "SLEEP_POD_SUEDE",
    )
    PC_PAIR: tuple[Symbol, Symbol] = ("SLEEP_POD_POLYESTER", "SLEEP_POD_COTTON")
    LN_PAIR: tuple[Symbol, Symbol] = ("SLEEP_POD_LAMB_WOOL", "SLEEP_POD_NYLON")
    SP_PAIR: tuple[Symbol, Symbol] = ("SLEEP_POD_SUEDE", "SLEEP_POD_POLYESTER")

    PC_EMA_ALPHA = 0.0001
    PC_ROLLING_STD_WINDOW = 1000
    PC_MIN_HISTORY = 500
    PC_ENTRY_Z = 2.75

    LN_WINDOW = 1000
    LN_MIN_HISTORY = 1000
    LN_ENTRY_Z = 2.75

    SP_EMA_ALPHA = 0.0001
    SP_ROLLING_STD_WINDOW = 1000
    SP_MIN_HISTORY = 500
    SP_ENTRY_Z = 2.75

    TARGET_SIZE = 10
    POSITION_LIMIT = 10
    MAX_ORDER_SIZE = 10
    HISTORY_LIMIT = 1000
    RESIDUAL_SCALE = 10

    def empty_state(self) -> tuple[list[int], Optional[float], int, list[int], int, list[int], Optional[float], int]:
        return [], None, 0, [], 0, [], None, 0

    def load_state(self, loaded) -> tuple[list[int], Optional[float], int, list[int], int, list[int], Optional[float], int]:
        pc_history, pc_ema, pc_state, ln_history, ln_state, sp_history, sp_ema, sp_state = self.empty_state()
        if not isinstance(loaded, dict):
            return pc_history, pc_ema, pc_state, ln_history, ln_state, sp_history, sp_ema, sp_state

        pc_history = clean_history(loaded.get("ph", []), self.HISTORY_LIMIT)
        ln_history = clean_history(loaded.get("lh", []), self.HISTORY_LIMIT)
        sp_history = clean_history(loaded.get("sh", []), self.HISTORY_LIMIT)

        try:
            pc_ema = float(loaded["pe"])
        except (KeyError, TypeError, ValueError):
            pc_ema = None

        try:
            sp_ema = float(loaded["se"])
        except (KeyError, TypeError, ValueError):
            sp_ema = None

        try:
            pc_state = int(loaded.get("ps", 0))
        except (TypeError, ValueError):
            pc_state = 0

        try:
            ln_state = int(loaded.get("ls", 0))
        except (TypeError, ValueError):
            ln_state = 0

        try:
            sp_state = int(loaded.get("ss", 0))
        except (TypeError, ValueError):
            sp_state = 0

        return (
            pc_history,
            pc_ema,
            clamp(pc_state, -1, 1),
            ln_history,
            clamp(ln_state, -1, 1),
            sp_history,
            sp_ema,
            clamp(sp_state, -1, 1),
        )

    def dump_state(
        self,
        pc_history: list[int],
        pc_ema: Optional[float],
        pc_state: int,
        ln_history: list[int],
        ln_state: int,
        sp_history: list[int],
        sp_ema: Optional[float],
        sp_state: int,
    ) -> dict:
        dumped = {
            "ph": pc_history[-self.HISTORY_LIMIT:],
            "ps": int(pc_state),
            "lh": ln_history[-self.HISTORY_LIMIT:],
            "ls": int(ln_state),
            "sh": sp_history[-self.HISTORY_LIMIT:],
            "ss": int(sp_state),
        }
        if pc_ema is not None:
            dumped["pe"] = float(pc_ema)
        if sp_ema is not None:
            dumped["se"] = float(sp_ema)
        return dumped

    def next_ewma_state(
        self,
        current_state: int,
        residual: float,
        z_score: Optional[float],
        entry_z: float,
    ) -> int:
        if current_state == 1:
            return 0 if residual >= 0.0 else current_state
        if current_state == -1:
            return 0 if residual <= 0.0 else current_state
        if z_score is None:
            return 0
        if z_score > entry_z:
            return -1
        if z_score < -entry_z:
            return 1
        return 0

    def next_raw_state(self, current_state: int, z_score: Optional[float], has_min_history: bool) -> int:
        if not has_min_history or z_score is None:
            return 0 if not has_min_history else current_state
        if z_score > self.LN_ENTRY_Z:
            return -1
        if z_score < -self.LN_ENTRY_Z:
            return 1
        return current_state

    def run(
        self,
        state: TradingState,
        pc_history: list[int],
        pc_ema: Optional[float],
        pc_state: int,
        ln_history: list[int],
        ln_state: int,
        sp_history: list[int],
        sp_ema: Optional[float],
        sp_state: int,
        result: dict[Symbol, list[Order]],
    ) -> tuple[Optional[float], int, int, Optional[float], int]:
        mids: dict[Symbol, float] = {}
        for product in self.PRODUCTS:
            order_depth = state.order_depths.get(product)
            if order_depth is None:
                return pc_ema, pc_state, ln_state, sp_ema, sp_state
            mid = mid_price(order_depth)
            if mid is None:
                return pc_ema, pc_state, ln_state, sp_ema, sp_state
            mids[product] = mid

        pc_a, pc_b = self.PC_PAIR
        pc_diff = mids[pc_a] - mids[pc_b]
        if pc_ema is None:
            pc_ema = pc_diff
        pc_residual = pc_diff - pc_ema
        scaled_pc_residual = int(round(pc_residual * self.RESIDUAL_SCALE))
        pc_z_score = residual_std_score(
            pc_history,
            scaled_pc_residual,
            self.PC_ROLLING_STD_WINDOW,
            self.PC_MIN_HISTORY,
        )
        next_pc_state = self.next_ewma_state(pc_state, pc_residual, pc_z_score, self.PC_ENTRY_Z)

        ln_a, ln_b = self.LN_PAIR
        ln_diff = mids[ln_a] - mids[ln_b]
        scaled_ln_diff = int(round(ln_diff * self.RESIDUAL_SCALE))
        ln_has_min_history = len(ln_history) >= self.LN_MIN_HISTORY
        ln_z_score = rolling_spread_z_score(
            ln_history,
            scaled_ln_diff,
            self.LN_WINDOW,
            self.LN_MIN_HISTORY,
        )
        next_ln_state = self.next_raw_state(ln_state, ln_z_score, ln_has_min_history)

        sp_a, sp_b = self.SP_PAIR
        sp_diff = mids[sp_a] - mids[sp_b]
        if sp_ema is None:
            sp_ema = sp_diff
        sp_residual = sp_diff - sp_ema
        scaled_sp_residual = int(round(sp_residual * self.RESIDUAL_SCALE))
        sp_z_score = residual_std_score(
            sp_history,
            scaled_sp_residual,
            self.SP_ROLLING_STD_WINDOW,
            self.SP_MIN_HISTORY,
        )
        next_sp_state = self.next_ewma_state(sp_state, sp_residual, sp_z_score, self.SP_ENTRY_Z)

        targets = {product: 0 for product in self.PRODUCTS}
        targets[pc_a] += next_pc_state * self.TARGET_SIZE
        targets[pc_b] -= next_pc_state * self.TARGET_SIZE
        targets[ln_a] += next_ln_state * self.TARGET_SIZE
        targets[ln_b] -= next_ln_state * self.TARGET_SIZE
        targets[sp_a] += next_sp_state * self.TARGET_SIZE
        targets[sp_b] -= next_sp_state * self.TARGET_SIZE

        for product in targets:
            targets[product] = clamp(targets[product], -self.POSITION_LIMIT, self.POSITION_LIMIT)

        for product in self.PRODUCTS:
            orders = order_to_target(
                product,
                state.order_depths[product],
                state.position.get(product, 0),
                targets[product],
                self.POSITION_LIMIT,
                self.MAX_ORDER_SIZE,
            )
            if orders:
                result[product] = orders

        pc_history.append(scaled_pc_residual)
        if len(pc_history) > self.HISTORY_LIMIT:
            del pc_history[: len(pc_history) - self.HISTORY_LIMIT]
        pc_ema += self.PC_EMA_ALPHA * (pc_diff - pc_ema)

        ln_history.append(scaled_ln_diff)
        if len(ln_history) > self.HISTORY_LIMIT:
            del ln_history[: len(ln_history) - self.HISTORY_LIMIT]

        sp_history.append(scaled_sp_residual)
        if len(sp_history) > self.HISTORY_LIMIT:
            del sp_history[: len(sp_history) - self.HISTORY_LIMIT]
        sp_ema += self.SP_EMA_ALPHA * (sp_diff - sp_ema)

        return pc_ema, next_pc_state, next_ln_state, sp_ema, next_sp_state


class GalaxyPairsModule:
    PAIRS: tuple[tuple[str, Symbol, Symbol, int, int, float], ...] = (
        ("dmbh", "GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_BLACK_HOLES", 3000, 3000, 2.50),
        ("swsf", "GALAXY_SOUNDS_SOLAR_WINDS", "GALAXY_SOUNDS_SOLAR_FLAMES", 1500, 1500, 3.00),
    )
    TARGET_SIZE = 10
    POSITION_LIMIT = 10
    MAX_ORDER_SIZE = 10
    RESIDUAL_SCALE = 10
    HOLD_TO_FLIP = True

    def empty_state(self) -> tuple[dict[str, list[int]], dict[str, int]]:
        return (
            {name: [] for name, *_ in self.PAIRS},
            {name: 0 for name, *_ in self.PAIRS},
        )

    def load_state(self, loaded) -> tuple[dict[str, list[int]], dict[str, int]]:
        histories, targets = self.empty_state()
        if not isinstance(loaded, dict):
            return histories, targets
        raw_histories = loaded.get("h", {})
        if isinstance(raw_histories, dict):
            for name, _, _, window, _, _ in self.PAIRS:
                histories[name] = clean_history(raw_histories.get(name, []), window)
        raw_targets = loaded.get("t", {})
        if isinstance(raw_targets, dict):
            for name, *_ in self.PAIRS:
                try:
                    target = int(raw_targets.get(name, 0))
                except (TypeError, ValueError):
                    target = 0
                targets[name] = clamp(target, -self.TARGET_SIZE, self.TARGET_SIZE)
        return histories, targets

    def dump_state(self, histories: dict[str, list[int]], targets: dict[str, int]) -> dict:
        return {
            "h": {name: histories.get(name, [])[-window:] for name, _, _, window, *_ in self.PAIRS},
            "t": {name: int(targets.get(name, 0)) for name, *_ in self.PAIRS},
        }

    def target_from_signal(
        self,
        previous_target: int,
        z_score: Optional[float],
        has_min_history: bool,
        entry_z: float,
    ) -> int:
        if not has_min_history or z_score is None:
            return 0 if not has_min_history else previous_target
        if z_score > entry_z:
            return -self.TARGET_SIZE
        if z_score < -entry_z:
            return self.TARGET_SIZE
        return previous_target

    def run(
        self,
        state: TradingState,
        histories: dict[str, list[int]],
        targets: dict[str, int],
        result: dict[Symbol, list[Order]],
    ) -> dict[str, int]:
        next_targets: dict[str, int] = {name: targets.get(name, 0) for name, *_ in self.PAIRS}
        diffs: dict[str, int] = {}
        active_pairs: list[tuple[str, Symbol, Symbol, int, int, float]] = []

        for pair in self.PAIRS:
            name, prod_a, prod_b, window, min_history, entry_z = pair
            depth_a = state.order_depths.get(prod_a)
            depth_b = state.order_depths.get(prod_b)
            if depth_a is None or depth_b is None:
                continue
            mid_a = mid_price(depth_a)
            mid_b = mid_price(depth_b)
            if mid_a is None or mid_b is None:
                continue
            diff = int(round((mid_a - mid_b) * self.RESIDUAL_SCALE))
            history = histories[name]
            has_min_history = len(history) >= min_history
            z_score = rolling_spread_z_score(history, diff, window, min_history)
            next_targets[name] = self.target_from_signal(
                targets.get(name, 0), z_score, has_min_history, entry_z
            )
            diffs[name] = diff
            active_pairs.append(pair)

        for name, prod_a, prod_b, _, _, _ in active_pairs:
            target = next_targets[name]
            orders_a = order_to_target(
                prod_a,
                state.order_depths[prod_a],
                state.position.get(prod_a, 0),
                target,
                self.POSITION_LIMIT,
                self.MAX_ORDER_SIZE,
            )
            if orders_a:
                result[prod_a] = orders_a
            orders_b = order_to_target(
                prod_b,
                state.order_depths[prod_b],
                state.position.get(prod_b, 0),
                -target,
                self.POSITION_LIMIT,
                self.MAX_ORDER_SIZE,
            )
            if orders_b:
                result[prod_b] = orders_b

        for name, _, _, window, _, _ in active_pairs:
            history = histories[name]
            history.append(diffs[name])
            if len(history) > window:
                del history[: len(history) - window]

        return next_targets


class OxygenPairsModule:
    PAIRS: tuple[tuple[str, Symbol, Symbol, int, int, float], ...] = (
        ("cg", "OXYGEN_SHAKE_CHOCOLATE", "OXYGEN_SHAKE_GARLIC", 3500, 3500, 2.00),
        ("em", "OXYGEN_SHAKE_EVENING_BREATH", "OXYGEN_SHAKE_MINT", 500, 500, 3.00),
    )
    TARGET_SIZE = 10
    POSITION_LIMIT = 10
    MAX_ORDER_SIZE = 10
    RESIDUAL_SCALE = 10

    def empty_state(self) -> tuple[dict[str, list[int]], dict[str, int]]:
        return (
            {name: [] for name, *_ in self.PAIRS},
            {name: 0 for name, *_ in self.PAIRS},
        )

    def load_state(self, loaded) -> tuple[dict[str, list[int]], dict[str, int]]:
        histories, targets = self.empty_state()
        if not isinstance(loaded, dict):
            return histories, targets
        raw_histories = loaded.get("h", {})
        if isinstance(raw_histories, dict):
            for name, _, _, window, _, _ in self.PAIRS:
                histories[name] = clean_history(raw_histories.get(name, []), window)
        raw_targets = loaded.get("t", {})
        if isinstance(raw_targets, dict):
            for name, *_ in self.PAIRS:
                try:
                    target = int(raw_targets.get(name, 0))
                except (TypeError, ValueError):
                    target = 0
                targets[name] = clamp(target, -self.TARGET_SIZE, self.TARGET_SIZE)
        return histories, targets

    def dump_state(self, histories: dict[str, list[int]], targets: dict[str, int]) -> dict:
        return {
            "h": {name: histories.get(name, [])[-window:] for name, _, _, window, *_ in self.PAIRS},
            "t": {name: int(targets.get(name, 0)) for name, *_ in self.PAIRS},
        }

    def target_from_signal(
        self,
        previous_target: int,
        z_score: Optional[float],
        has_min_history: bool,
        entry_z: float,
    ) -> int:
        if not has_min_history or z_score is None:
            return 0 if not has_min_history else previous_target
        if z_score > entry_z:
            return -self.TARGET_SIZE
        if z_score < -entry_z:
            return self.TARGET_SIZE
        return previous_target

    def run(
        self,
        state: TradingState,
        histories: dict[str, list[int]],
        targets: dict[str, int],
        result: dict[Symbol, list[Order]],
    ) -> dict[str, int]:
        next_targets: dict[str, int] = {name: targets.get(name, 0) for name, *_ in self.PAIRS}
        diffs: dict[str, int] = {}
        active_pairs: list[tuple[str, Symbol, Symbol, int, int, float]] = []

        for pair in self.PAIRS:
            name, prod_a, prod_b, window, min_history, entry_z = pair
            depth_a = state.order_depths.get(prod_a)
            depth_b = state.order_depths.get(prod_b)
            if depth_a is None or depth_b is None:
                continue
            mid_a = mid_price(depth_a)
            mid_b = mid_price(depth_b)
            if mid_a is None or mid_b is None:
                continue
            diff = int(round((mid_a - mid_b) * self.RESIDUAL_SCALE))
            history = histories[name]
            has_min_history = len(history) >= min_history
            z_score = rolling_spread_z_score(history, diff, window, min_history)
            next_targets[name] = self.target_from_signal(
                targets.get(name, 0), z_score, has_min_history, entry_z
            )
            diffs[name] = diff
            active_pairs.append(pair)

        for name, prod_a, prod_b, _, _, _ in active_pairs:
            target = next_targets[name]
            orders_a = order_to_target(
                prod_a,
                state.order_depths[prod_a],
                state.position.get(prod_a, 0),
                target,
                self.POSITION_LIMIT,
                self.MAX_ORDER_SIZE,
            )
            if orders_a:
                result[prod_a] = orders_a
            orders_b = order_to_target(
                prod_b,
                state.order_depths[prod_b],
                state.position.get(prod_b, 0),
                -target,
                self.POSITION_LIMIT,
                self.MAX_ORDER_SIZE,
            )
            if orders_b:
                result[prod_b] = orders_b

        for name, _, _, window, _, _ in active_pairs:
            history = histories[name]
            history.append(diffs[name])
            if len(history) > window:
                del history[: len(history) - window]

        return next_targets


class UVVisorPairsModule:
    PAIRS: tuple[tuple[str, Symbol, Symbol, int, int, float], ...] = (
        ("ym", "UV_VISOR_YELLOW", "UV_VISOR_MAGENTA", 1500, 1500, 2.75),
        ("ar", "UV_VISOR_AMBER", "UV_VISOR_RED", 2500, 2500, 2.50),
    )
    TARGET_SIZE = 10
    POSITION_LIMIT = 10
    MAX_ORDER_SIZE = 10
    RESIDUAL_SCALE = 10

    def empty_state(self) -> tuple[dict[str, list[int]], dict[str, int]]:
        return (
            {name: [] for name, *_ in self.PAIRS},
            {name: 0 for name, *_ in self.PAIRS},
        )

    def load_state(self, loaded) -> tuple[dict[str, list[int]], dict[str, int]]:
        histories, targets = self.empty_state()
        if not isinstance(loaded, dict):
            return histories, targets
        raw_histories = loaded.get("h", {})
        if isinstance(raw_histories, dict):
            for name, _, _, window, _, _ in self.PAIRS:
                histories[name] = clean_int16_history(raw_histories.get(name, []), window)
        raw_targets = loaded.get("t", {})
        if isinstance(raw_targets, dict):
            for name, *_ in self.PAIRS:
                try:
                    target = int(raw_targets.get(name, 0))
                except (TypeError, ValueError):
                    target = 0
                targets[name] = clamp(target, -self.TARGET_SIZE, self.TARGET_SIZE)
        return histories, targets

    def dump_state(self, histories: dict[str, list[int]], targets: dict[str, int]) -> dict:
        return {
            "h": {name: dump_int16_history(histories.get(name, [])[-window:]) for name, _, _, window, *_ in self.PAIRS},
            "t": {name: int(targets.get(name, 0)) for name, *_ in self.PAIRS},
        }

    def target_from_signal(
        self,
        previous_target: int,
        z_score: Optional[float],
        has_min_history: bool,
        entry_z: float,
    ) -> int:
        if not has_min_history or z_score is None:
            return 0 if not has_min_history else previous_target
        if z_score > entry_z:
            return -self.TARGET_SIZE
        if z_score < -entry_z:
            return self.TARGET_SIZE
        return previous_target

    def run(
        self,
        state: TradingState,
        histories: dict[str, list[int]],
        targets: dict[str, int],
        result: dict[Symbol, list[Order]],
    ) -> dict[str, int]:
        next_targets: dict[str, int] = {name: targets.get(name, 0) for name, *_ in self.PAIRS}
        diffs: dict[str, int] = {}
        active_pairs: list[tuple[str, Symbol, Symbol, int, int, float]] = []

        for pair in self.PAIRS:
            name, prod_a, prod_b, window, min_history, entry_z = pair
            depth_a = state.order_depths.get(prod_a)
            depth_b = state.order_depths.get(prod_b)
            if depth_a is None or depth_b is None:
                continue
            mid_a = mid_price(depth_a)
            mid_b = mid_price(depth_b)
            if mid_a is None or mid_b is None:
                continue
            diff = int(round((mid_a - mid_b) * self.RESIDUAL_SCALE))
            history = histories[name]
            has_min_history = len(history) >= min_history
            z_score = rolling_spread_z_score(history, diff, window, min_history)
            next_targets[name] = self.target_from_signal(
                targets.get(name, 0), z_score, has_min_history, entry_z
            )
            diffs[name] = diff
            active_pairs.append(pair)

        for name, prod_a, prod_b, _, _, _ in active_pairs:
            target = next_targets[name]
            orders_a = order_to_target(
                prod_a,
                state.order_depths[prod_a],
                state.position.get(prod_a, 0),
                target,
                self.POSITION_LIMIT,
                self.MAX_ORDER_SIZE,
            )
            if orders_a:
                result[prod_a] = orders_a
            orders_b = order_to_target(
                prod_b,
                state.order_depths[prod_b],
                state.position.get(prod_b, 0),
                -target,
                self.POSITION_LIMIT,
                self.MAX_ORDER_SIZE,
            )
            if orders_b:
                result[prod_b] = orders_b

        for name, _, _, window, _, _ in active_pairs:
            history = histories[name]
            history.append(diffs[name])
            if len(history) > window:
                del history[: len(history) - window]

        return next_targets


class PanelPairsModule:
    PAIRS: tuple[tuple[str, Symbol, Symbol, int, int, float], ...] = (
        ("p1224", "PANEL_1X2", "PANEL_2X4", 1000, 1000, 1.75),
        ("p2214", "PANEL_2X2", "PANEL_1X4", 4000, 4000, 2.50),
    )
    TARGET_SIZE = 10
    POSITION_LIMIT = 10
    MAX_ORDER_SIZE = 10
    RESIDUAL_SCALE = 10

    def empty_state(self) -> tuple[dict[str, list[int]], dict[str, int]]:
        return (
            {name: [] for name, *_ in self.PAIRS},
            {name: 0 for name, *_ in self.PAIRS},
        )

    def load_state(self, loaded) -> tuple[dict[str, list[int]], dict[str, int]]:
        histories, targets = self.empty_state()
        if not isinstance(loaded, dict):
            return histories, targets

        raw_histories = loaded.get("h", {})
        if isinstance(raw_histories, dict):
            for name, _, _, window, _, _ in self.PAIRS:
                histories[name] = clean_offset_int16_history(raw_histories.get(name, []), window)

        raw_targets = loaded.get("t", {})
        if isinstance(raw_targets, dict):
            for name, *_ in self.PAIRS:
                try:
                    target = int(raw_targets.get(name, 0))
                except (TypeError, ValueError):
                    target = 0
                targets[name] = clamp(target, -self.TARGET_SIZE, self.TARGET_SIZE)

        return histories, targets

    def dump_state(self, histories: dict[str, list[int]], targets: dict[str, int]) -> dict:
        return {
            "h": {
                name: dump_offset_int16_history(histories.get(name, [])[-window:])
                for name, _, _, window, *_ in self.PAIRS
            },
            "t": {name: int(targets.get(name, 0)) for name, *_ in self.PAIRS},
        }

    def target_from_signal(
        self,
        previous_target: int,
        z_score: Optional[float],
        has_min_history: bool,
        entry_z: float,
    ) -> int:
        if not has_min_history or z_score is None:
            return 0 if not has_min_history else previous_target
        if z_score > entry_z:
            return -self.TARGET_SIZE
        if z_score < -entry_z:
            return self.TARGET_SIZE
        return previous_target

    def run(
        self,
        state: TradingState,
        histories: dict[str, list[int]],
        targets: dict[str, int],
        result: dict[Symbol, list[Order]],
    ) -> dict[str, int]:
        next_targets: dict[str, int] = {name: targets.get(name, 0) for name, *_ in self.PAIRS}
        diffs: dict[str, int] = {}
        active_pairs: list[tuple[str, Symbol, Symbol, int, int, float]] = []

        for pair in self.PAIRS:
            name, prod_a, prod_b, window, min_history, entry_z = pair
            depth_a = state.order_depths.get(prod_a)
            depth_b = state.order_depths.get(prod_b)
            if depth_a is None or depth_b is None:
                continue
            mid_a = mid_price(depth_a)
            mid_b = mid_price(depth_b)
            if mid_a is None or mid_b is None:
                continue

            diff = int(round((mid_a - mid_b) * self.RESIDUAL_SCALE))
            history = histories[name]
            has_min_history = len(history) >= min_history
            z_score = rolling_spread_z_score(history, diff, window, min_history)
            next_targets[name] = self.target_from_signal(
                targets.get(name, 0), z_score, has_min_history, entry_z
            )
            diffs[name] = diff
            active_pairs.append(pair)

        for name, prod_a, prod_b, _, _, _ in active_pairs:
            target = next_targets[name]
            orders_a = order_to_target(
                prod_a,
                state.order_depths[prod_a],
                state.position.get(prod_a, 0),
                target,
                self.POSITION_LIMIT,
                self.MAX_ORDER_SIZE,
            )
            if orders_a:
                result[prod_a] = orders_a
            orders_b = order_to_target(
                prod_b,
                state.order_depths[prod_b],
                state.position.get(prod_b, 0),
                -target,
                self.POSITION_LIMIT,
                self.MAX_ORDER_SIZE,
            )
            if orders_b:
                result[prod_b] = orders_b

        for name, _, _, window, _, _ in active_pairs:
            history = histories[name]
            history.append(diffs[name])
            if len(history) > window:
                del history[: len(history) - window]

        return next_targets


class Trader:
    PEBBLES_STATE_KEY = "p"
    TRANSLATOR_STATE_KEY = "tr"
    MICROCHIP_STATE_KEY = "mc"
    ROBOT_STATE_KEY = "rb"
    SNACKPACK_STATE_KEY = "sp"
    POD_STATE_KEY = "pod"
    GALAXY_STATE_KEY = "gx"
    OXYGEN_STATE_KEY = "ox"
    UV_STATE_KEY = "uv"
    PANEL_STATE_KEY = "pn"

    def __init__(self) -> None:
        self.pebbles = PebblesModule()
        self.translator = TranslatorModule()
        self.microchip = MicrochipModule()
        self.robot = RobotModule()
        self.snackpack = SnackpackEwmaModule()
        self.pod = SleepPodModule()
        self.galaxy = GalaxyPairsModule()
        self.oxygen = OxygenPairsModule()
        self.uv = UVVisorPairsModule()
        self.panel = PanelPairsModule()

    def _load_json(self, trader_data: str) -> dict:
        if not trader_data:
            return {}
        try:
            loaded = json.loads(trader_data)
        except Exception:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def run(self, state: TradingState):
        loaded = self._load_json(state.traderData)

        pebbles_histories, pebbles_targets = self.pebbles.load_state(loaded.get(self.PEBBLES_STATE_KEY, {}))
        translator_histories, translator_targets = self.translator.load_state(
            loaded.get(self.TRANSLATOR_STATE_KEY, {})
        )
        microchip_history, microchip_targets = self.microchip.load_state(loaded.get(self.MICROCHIP_STATE_KEY, {}))
        robot_history, robot_targets = self.robot.load_state(loaded.get(self.ROBOT_STATE_KEY, {}))
        snack_histories, snack_emas, snack_pair_states = self.snackpack.load_state(
            loaded.get(self.SNACKPACK_STATE_KEY, {})
        )
        (
            pod_pc_history,
            pod_pc_ema,
            pod_pc_state,
            pod_ln_history,
            pod_ln_state,
            pod_sp_history,
            pod_sp_ema,
            pod_sp_state,
        ) = self.pod.load_state(loaded.get(self.POD_STATE_KEY, {}))
        galaxy_histories, galaxy_targets = self.galaxy.load_state(loaded.get(self.GALAXY_STATE_KEY, {}))
        oxygen_histories, oxygen_targets = self.oxygen.load_state(loaded.get(self.OXYGEN_STATE_KEY, {}))
        uv_histories, uv_targets = self.uv.load_state(loaded.get(self.UV_STATE_KEY, {}))
        panel_histories, panel_targets = self.panel.load_state(loaded.get(self.PANEL_STATE_KEY, {}))

        result: dict[Symbol, list[Order]] = {}

        next_pebbles_targets = self.pebbles.run(state, pebbles_histories, pebbles_targets, result)
        next_translator_targets = self.translator.run(state, translator_histories, translator_targets, result)
        next_microchip_targets = self.microchip.run(state, microchip_history, microchip_targets, result)
        next_robot_targets = self.robot.run(state, robot_history, robot_targets, result)
        next_snack_pair_states = self.snackpack.run(state, snack_histories, snack_emas, snack_pair_states, result)
        (
            next_pod_pc_ema,
            next_pod_pc_state,
            next_pod_ln_state,
            next_pod_sp_ema,
            next_pod_sp_state,
        ) = self.pod.run(
            state,
            pod_pc_history,
            pod_pc_ema,
            pod_pc_state,
            pod_ln_history,
            pod_ln_state,
            pod_sp_history,
            pod_sp_ema,
            pod_sp_state,
            result,
        )
        next_galaxy_targets = self.galaxy.run(state, galaxy_histories, galaxy_targets, result)
        next_oxygen_targets = self.oxygen.run(state, oxygen_histories, oxygen_targets, result)
        next_uv_targets = self.uv.run(state, uv_histories, uv_targets, result)
        next_panel_targets = self.panel.run(state, panel_histories, panel_targets, result)

        # Determine which products have an active directional signal
        active_products: set[Symbol] = set()

        # Simple per-product modules (targets keyed by product)
        for targets_dict in (
            next_pebbles_targets,
        ):
            for product, target in targets_dict.items():
                if target != 0:
                    active_products.add(product)

        # Robot: now pair-based (targets keyed by pair name, not product)
        for name, prod_a, prod_b, *_ in self.robot.PAIRS:
            if next_robot_targets.get(name, 0) != 0:
                active_products.add(prod_a)
                active_products.add(prod_b)

        # Translator: in "current" mode targets are product-keyed;
        # in pair-network mode targets are pair-name-keyed, so use PAIRS directly
        if self.translator.CONFIG_NAME == "current":
            for product, target in next_translator_targets.items():
                if target != 0:
                    active_products.add(product)
        else:
            for name, prod_a, prod_b, *_ in self.translator.PAIRS:
                if next_translator_targets.get(name, 0) != 0:
                    active_products.add(prod_a)
                    active_products.add(prod_b)

        # Snackpack: pair_name → (prod_a, prod_b)
        for pair_name, prod_a, prod_b in self.snackpack.PAIRS:
            if next_snack_pair_states.get(pair_name, 0) != 0:
                active_products.add(prod_a)
                active_products.add(prod_b)

        # Sleep Pod: individual sub-pair states (SP pair applies both legs)
        pc_a, pc_b = self.pod.PC_PAIR
        ln_a, ln_b = self.pod.LN_PAIR
        sp_a, sp_b = self.pod.SP_PAIR
        if next_pod_pc_state != 0:
            active_products.add(pc_a)
            active_products.add(pc_b)
        if next_pod_ln_state != 0:
            active_products.add(ln_a)
            active_products.add(ln_b)
        if next_pod_sp_state != 0:
            active_products.add(sp_a)
            active_products.add(sp_b)

        # Pair-based modules (microchip, galaxy, oxygen, uv, panel)
        for module, targets_dict in (
            (self.microchip, next_microchip_targets),
            (self.galaxy, next_galaxy_targets),
            (self.oxygen, next_oxygen_targets),
            (self.uv, next_uv_targets),
            (self.panel, next_panel_targets),
        ):
            for name, prod_a, prod_b, *_ in module.PAIRS:
                if targets_dict.get(name, 0) != 0:
                    active_products.add(prod_a)
                    active_products.add(prod_b)

        # Market make every product without an active signal
        for product, depth in state.order_depths.items():
            if product not in active_products:
                mm_orders = market_make(
                    product,
                    depth,
                    state.position.get(product, 0),
                    position_limit=10,
                    max_order_size=10,
                )
                if mm_orders:
                    result[product] = mm_orders

        trader_data = json.dumps(
            {
                self.PEBBLES_STATE_KEY: self.pebbles.dump_state(pebbles_histories, next_pebbles_targets),
                self.TRANSLATOR_STATE_KEY: self.translator.dump_state(
                    translator_histories,
                    next_translator_targets,
                ),
                self.MICROCHIP_STATE_KEY: self.microchip.dump_state(microchip_history, next_microchip_targets),
                self.ROBOT_STATE_KEY: self.robot.dump_state(robot_history, next_robot_targets),
                self.SNACKPACK_STATE_KEY: self.snackpack.dump_state(
                    snack_histories,
                    snack_emas,
                    next_snack_pair_states,
                ),
                self.POD_STATE_KEY: self.pod.dump_state(
                    pod_pc_history,
                    next_pod_pc_ema,
                    next_pod_pc_state,
                    pod_ln_history,
                    next_pod_ln_state,
                    pod_sp_history,
                    next_pod_sp_ema,
                    next_pod_sp_state,
                ),
                self.GALAXY_STATE_KEY: self.galaxy.dump_state(galaxy_histories, next_galaxy_targets),
                self.OXYGEN_STATE_KEY: self.oxygen.dump_state(oxygen_histories, next_oxygen_targets),
                self.UV_STATE_KEY: self.uv.dump_state(uv_histories, next_uv_targets),
                self.PANEL_STATE_KEY: self.panel.dump_state(panel_histories, next_panel_targets),
            },
            separators=(",", ":"),
        )
        return result, 0, trader_data