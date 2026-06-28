SPOT_ALLOWED_ACTIONS = {"buy", "sell_existing", "hold", "cancel_order"}
DISALLOWED_MARKETS = {"margin", "swap", "future", "perpetual", "option"}
DISALLOWED_SIGNAL_ACTIONS = {"short", "sell_short", "leverage_buy", "margin_buy"}


def assert_spot_action(action: str) -> None:
    if action not in SPOT_ALLOWED_ACTIONS:
        raise ValueError(f"Unsupported action for MVP spot boundary: {action}")

