from pathlib import Path


CORE_JS = Path(__file__).resolve().parent / "shared" / "chart_board_core.js"


def _read_core_js() -> str:
    return CORE_JS.read_text(encoding="utf-8")


def _function_body(source: str, name: str) -> str:
    start = source.index(f"function {name}")
    brace = source.index("{", start)
    depth = 0
    for idx in range(brace, len(source)):
        char = source[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1 : idx]
    raise AssertionError(f"{name} body not found")


def test_watchlist_refresh_uses_cache_and_limited_concurrency():
    source = _read_core_js()
    body = _function_body(source, "refreshWatchlistPrices")

    assert "WATCHLIST_PRICE_CACHE_TTL_MS" in source
    assert "WATCHLIST_PRICE_MAX_CONCURRENT_REQUESTS" in source
    assert "isWatchlistPriceFresh" in source
    assert "runLimitedConcurrency" in source
    assert "Promise.all(tasks)" not in body


def test_auto_refresh_skips_hidden_page_and_watchlist_inflight_refresh():
    source = _read_core_js()
    body = _function_body(source, "refreshWatchlistPrices")
    auto_body = _function_body(source, "startAutoRefresh")

    assert "watchlistPriceRefreshInFlight" in source
    assert 'document.visibilityState !== "visible"' in body
    assert 'document.visibilityState !== "visible"' in auto_body
