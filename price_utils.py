"""
Price utilities - sliding window algorithms for finding optimal
2-hour price windows (cheapest/most expensive).

Used by energy_scheduler and summer_heater.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional, Tuple


# Type alias: list of (datetime, price) tuples sorted by time
PriceList = List[Tuple[datetime, float]]


def find_best_window(
    prices: PriceList,
    window_size: int = 2,
    mode: str = "min",
) -> Optional[Tuple[datetime, float]]:
    """
    Find the best N-hour window in a sorted price list.
    
    Args:
        prices: List of (datetime, price) tuples, sorted by time.
        window_size: Number of consecutive hours in the window.
        mode: "min" for cheapest window, "max" for most expensive window.
    
    Returns:
        Tuple of (window_start_datetime, window_sum) or None if not enough data.
    """
    if len(prices) < window_size:
        return None
    
    if mode == "min":
        best_sum = float('inf')
        compare = lambda new, old: new < old
    else:
        best_sum = float('-inf')
        compare = lambda new, old: new > old
    
    best_start = prices[0][0]
    
    for i in range(len(prices) - window_size + 1):
        window_sum = sum(prices[i + j][1] for j in range(window_size))
        if compare(window_sum, best_sum):
            best_sum = window_sum
            best_start = prices[i][0]
    
    return (best_start, best_sum)


def find_cheapest_window(
    prices: PriceList,
    window_size: int = 2,
) -> Optional[Tuple[datetime, float]]:
    """
    Find the cheapest N-hour window.
    
    Returns:
        Tuple of (window_start_datetime, window_sum) or None if not enough data.
    """
    return find_best_window(prices, window_size=window_size, mode="min")


def find_most_expensive_window(
    prices: PriceList,
    window_size: int = 2,
) -> Optional[Tuple[datetime, float]]:
    """
    Find the most expensive N-hour window.
    
    Returns:
        Tuple of (window_start_datetime, window_sum) or None if not enough data.
    """
    return find_best_window(prices, window_size=window_size, mode="max")


def filter_prices_by_hour_range(
    prices: PriceList,
    hour_start: int,
    hour_end: int,
) -> PriceList:
    """
    Filter price list to only include hours in [hour_start, hour_end).
    """
    return [(dt, price) for dt, price in prices if hour_start <= dt.hour < hour_end]
