"""
Tests for price_utils - sliding window algorithms.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

from price_utils import (
    find_best_window,
    find_cheapest_window,
    find_most_expensive_window,
    filter_prices_by_hour_range,
    PriceList,
)

TZ = ZoneInfo("Europe/Warsaw")


def make_prices(hour_price_pairs: list[tuple[int, float]], date=None) -> PriceList:
    """Helper: create PriceList from (hour, price) pairs."""
    if date is None:
        date = datetime(2026, 8, 5, tzinfo=TZ)
    return [(date.replace(hour=h, minute=0, second=0, microsecond=0), p)
            for h, p in hour_price_pairs]


class TestFindBestWindow:
    """Tests for find_best_window."""
    
    def test_empty_list(self):
        assert find_best_window([], mode="min") is None
        assert find_best_window([], mode="max") is None
    
    def test_single_element_window_size_2(self):
        prices = make_prices([(10, 0.5)])
        assert find_best_window(prices, window_size=2, mode="min") is None
    
    def test_single_element_window_size_1(self):
        prices = make_prices([(10, 0.5)])
        result = find_best_window(prices, window_size=1, mode="min")
        assert result is not None
        assert result[0].hour == 10
        assert result[1] == 0.5
    
    def test_two_elements_min(self):
        prices = make_prices([(10, 0.3), (11, 0.4)])
        result = find_cheapest_window(prices)
        assert result is not None
        assert result[0].hour == 10
        assert result[1] == pytest.approx(0.7)
    
    def test_two_elements_max(self):
        prices = make_prices([(10, 0.3), (11, 0.4)])
        result = find_most_expensive_window(prices)
        assert result is not None
        assert result[0].hour == 10
        assert result[1] == pytest.approx(0.7)
    
    def test_cheapest_window_basic(self):
        """Standard case: cheapest 2h window in the middle."""
        prices = make_prices([
            (8, 0.50), (9, 0.40), (10, 0.10), (11, 0.05), (12, 0.30), (13, 0.60)
        ])
        result = find_cheapest_window(prices)
        assert result is not None
        assert result[0].hour == 10  # 10:00-12:00 = 0.10 + 0.05 = 0.15
        assert result[1] == pytest.approx(0.15)
    
    def test_most_expensive_window_basic(self):
        """Standard case: most expensive 2h window."""
        prices = make_prices([
            (6, 0.30), (7, 0.80), (8, 0.90), (9, 0.40), (10, 0.20), (11, 0.10)
        ])
        result = find_most_expensive_window(prices)
        assert result is not None
        assert result[0].hour == 7  # 7:00-9:00 = 0.80 + 0.90 = 1.70
        assert result[1] == pytest.approx(1.70)
    
    def test_spike_doesnt_dominate(self):
        """
        Single spike should not dominate if surrounding hours are cheap.
        Window approach should pick consistent high prices over single spike.
        """
        # Spike at 9:00 but surrounded by low prices
        # vs consistent high at 7-8
        prices = make_prices([
            (6, 0.30), (7, 0.70), (8, 0.75), (9, 1.20), (10, 0.10), (11, 0.20)
        ])
        result = find_most_expensive_window(prices)
        assert result is not None
        # 7-8: 0.70+0.75=1.45, 8-9: 0.75+1.20=1.95, 9-10: 1.20+0.10=1.30
        # Best: 8-9 (spike+high neighbor)
        assert result[0].hour == 8
        assert result[1] == pytest.approx(1.95)
    
    def test_spike_isolated_min(self):
        """
        Single cheap spike surrounded by expensive hours.
        Should not be selected if neighbours are expensive.
        """
        prices = make_prices([
            (10, 0.50), (11, 0.60), (12, 0.01), (13, 0.55), (14, 0.45), (15, 0.40)
        ])
        result = find_cheapest_window(prices)
        assert result is not None
        # 12-13: 0.01+0.55=0.56, 14-15: 0.45+0.40=0.85, 11-12: 0.60+0.01=0.61
        # Best: 12-13 (cheapest window even if only one hour is very cheap)
        assert result[0].hour == 12
        assert result[1] == pytest.approx(0.56)
    
    def test_two_cheap_consecutive(self):
        """Two consecutive cheap hours should win over single cheapest."""
        prices = make_prices([
            (10, 0.50), (11, 0.20), (12, 0.20), (13, 0.01), (14, 0.50)
        ])
        result = find_cheapest_window(prices)
        assert result is not None
        # 11-12: 0.20+0.20=0.40, 12-13: 0.20+0.01=0.21, 13-14: 0.01+0.50=0.51
        # Best: 12-13
        assert result[0].hour == 12
        assert result[1] == pytest.approx(0.21)
    
    def test_negative_prices(self):
        """Negative prices (can happen on RCE market)."""
        prices = make_prices([
            (10, -0.05), (11, -0.10), (12, 0.02), (13, 0.30)
        ])
        result = find_cheapest_window(prices)
        assert result is not None
        assert result[0].hour == 10  # -0.05 + -0.10 = -0.15
        assert result[1] == pytest.approx(-0.15)
    
    def test_all_same_price(self):
        """All prices equal - should pick first window."""
        prices = make_prices([
            (10, 0.39), (11, 0.39), (12, 0.39), (13, 0.39)
        ])
        result = find_cheapest_window(prices)
        assert result is not None
        assert result[0].hour == 10
        assert result[1] == pytest.approx(0.78)
    
    def test_window_size_3(self):
        """Larger window size."""
        prices = make_prices([
            (8, 0.50), (9, 0.10), (10, 0.10), (11, 0.10), (12, 0.50), (13, 0.60)
        ])
        result = find_best_window(prices, window_size=3, mode="min")
        assert result is not None
        assert result[0].hour == 9  # 0.10+0.10+0.10 = 0.30
        assert result[1] == pytest.approx(0.30)
    
    def test_descending_prices(self):
        """Prices descending - cheapest window at end."""
        prices = make_prices([
            (10, 0.80), (11, 0.60), (12, 0.40), (13, 0.20), (14, 0.10)
        ])
        result = find_cheapest_window(prices)
        assert result is not None
        assert result[0].hour == 13  # 0.20 + 0.10 = 0.30
    
    def test_ascending_prices(self):
        """Prices ascending - cheapest window at start."""
        prices = make_prices([
            (10, 0.10), (11, 0.20), (12, 0.40), (13, 0.60), (14, 0.80)
        ])
        result = find_cheapest_window(prices)
        assert result is not None
        assert result[0].hour == 10  # 0.10 + 0.20 = 0.30


class TestFilterPricesByHourRange:
    """Tests for filter_prices_by_hour_range."""
    
    def test_empty_list(self):
        assert filter_prices_by_hour_range([], 6, 12) == []
    
    def test_filter_morning(self):
        prices = make_prices([
            (5, 0.1), (6, 0.2), (7, 0.3), (11, 0.5), (12, 0.6), (13, 0.7)
        ])
        result = filter_prices_by_hour_range(prices, 6, 12)
        assert len(result) == 3
        hours = [dt.hour for dt, _ in result]
        assert hours == [6, 7, 11]
    
    def test_filter_evening(self):
        prices = make_prices([
            (15, 0.3), (16, 0.4), (17, 0.5), (18, 0.6), (23, 0.9)
        ])
        result = filter_prices_by_hour_range(prices, 17, 24)
        assert len(result) == 3
        hours = [dt.hour for dt, _ in result]
        assert hours == [17, 18, 23]
    
    def test_inclusive_start_exclusive_end(self):
        prices = make_prices([(10, 0.5), (11, 0.6), (12, 0.7)])
        result = filter_prices_by_hour_range(prices, 10, 12)
        assert len(result) == 2
        assert result[0][0].hour == 10
        assert result[1][0].hour == 11


class TestEdgeCases:
    """Edge cases and real-world scenarios."""
    
    def test_very_volatile_prices(self):
        """Real-world: very volatile prices with negative values."""
        prices = make_prices([
            (8, 0.80), (9, -0.20), (10, 1.50), (11, -0.30),
            (12, 0.002), (13, 0.10), (14, 0.60), (15, 0.40)
        ])
        cheapest = find_cheapest_window(prices)
        assert cheapest is not None
        # 11-12: -0.30+0.002=-0.298, 9-10: -0.20+1.50=1.30, 8-9: 0.80+(-0.20)=0.60
        assert cheapest[0].hour == 11
        
        most_exp = find_most_expensive_window(prices)
        assert most_exp is not None
        # 9-10: -0.20+1.50=1.30, 10-11: 1.50+(-0.30)=1.20
        assert most_exp[0].hour == 9
    
    def test_real_day_pattern(self):
        """Simulates a typical Polish RCE day: morning peak, midday dip, evening peak."""
        prices = make_prices([
            (6, 0.45), (7, 0.65), (8, 0.70),  # morning peak
            (9, 0.40), (10, 0.35), (11, 0.30),  # decline
            (12, 0.05), (13, 0.10),  # midday dip (solar)
            (14, 0.35), (15, 0.40),  # afternoon rise
            (16, 0.45), (17, 0.55), (18, 0.70),  # evening build
            (19, 0.85), (20, 0.90),  # evening peak
            (21, 0.75), (22, 0.50), (23, 0.30)  # night decline
        ])
        
        # Morning (6-12): best sell window
        morning = filter_prices_by_hour_range(prices, 6, 12)
        result = find_most_expensive_window(morning)
        assert result is not None
        assert result[0].hour == 7  # 0.65+0.70=1.35
        
        # Midday (10-17): cheapest window for heater
        midday = filter_prices_by_hour_range(prices, 10, 17)
        result = find_cheapest_window(midday)
        assert result is not None
        assert result[0].hour == 12  # 0.05+0.10=0.15
        
        # Evening (17-24): best sell window
        evening = filter_prices_by_hour_range(prices, 17, 24)
        result = find_most_expensive_window(evening)
        assert result is not None
        assert result[0].hour == 19  # 0.85+0.90=1.75
    
    def test_flat_midday_with_single_spike(self):
        """Flat cheap midday but single expensive spike - window should avoid it."""
        prices = make_prices([
            (10, 0.10), (11, 0.10), (12, 0.80), (13, 0.10), (14, 0.10)
        ])
        result = find_cheapest_window(prices)
        assert result is not None
        # 10-11: 0.20, 13-14: 0.20, 11-12: 0.90, 12-13: 0.90
        # Should pick 10-11 (first of equal)
        assert result[0].hour == 10
        assert result[1] == pytest.approx(0.20)
