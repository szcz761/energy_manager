"""
Tests for summer_heater - daily minimum finding and scheduling.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import CONFIG

TZ = ZoneInfo("Europe/Warsaw")


def make_rce_response(hour_price_pairs: list[tuple[int, float]], date=None):
    """Helper: create (items, _) response from fetch_all_from_now."""
    if date is None:
        date = datetime(2026, 8, 5, tzinfo=TZ)
    items = []
    for hour, price_kwh in hour_price_pairs:
        dt = date.replace(hour=hour, minute=0, second=0, microsecond=0)
        items.append({
            "dtime": dt.strftime("%Y-%m-%d %H:%M"),
            "rce_pln": str(int(price_kwh * 1000)),
        })
    return items, None


class TestFindDailyMinimum:
    """Tests for find_daily_minimum."""
    
    @patch("summer_heater.datetime")
    def test_no_rce_data_fallback(self, mock_dt):
        """No RCE data should return fallback 11:00."""
        mock_dt.now.return_value = datetime(2026, 8, 5, 6, 0, tzinfo=TZ)
        
        with patch("rce_data.fetch_rce_pln.fetch_all_from_now", return_value=([], None)):
            from summer_heater import find_daily_minimum
            result = find_daily_minimum()
        
        assert result.hour == 11
    
    @patch("summer_heater.datetime")
    def test_api_exception_fallback(self, mock_dt):
        """API exception should return fallback 11:00."""
        mock_dt.now.return_value = datetime(2026, 8, 5, 6, 0, tzinfo=TZ)
        
        with patch("rce_data.fetch_rce_pln.fetch_all_from_now", side_effect=Exception("timeout")):
            from summer_heater import find_daily_minimum
            result = find_daily_minimum()
        
        assert result.hour == 11
    
    @patch("summer_heater.datetime")
    def test_typical_day(self, mock_dt):
        """Typical day with clear minimum at 12-13."""
        now = datetime(2026, 8, 5, 6, 0, tzinfo=TZ)
        mock_dt.now.return_value = now
        
        items, _ = make_rce_response([
            (8, 0.40), (9, 0.35), (10, 0.30), (11, 0.20),
            (12, 0.05), (13, 0.03), (14, 0.25), (15, 0.35),
        ])
        
        with patch("rce_data.fetch_rce_pln.fetch_all_from_now", return_value=(items, None)):
            with patch("rce_data.fetch_rce_pln.parse_rce_datetime") as mock_parse:
                mock_parse.side_effect = lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
                from summer_heater import find_daily_minimum
                result = find_daily_minimum()
        
        # Cheapest 2h: 12+13 (0.05+0.03=0.08)
        assert result.hour == 12
    
    @patch("summer_heater.datetime")
    def test_single_hour_data(self, mock_dt):
        """Only one hour in range - should return that hour."""
        now = datetime(2026, 8, 5, 6, 0, tzinfo=TZ)
        mock_dt.now.return_value = now
        
        items, _ = make_rce_response([(12, 0.10)])
        
        with patch("rce_data.fetch_rce_pln.fetch_all_from_now", return_value=(items, None)):
            with patch("rce_data.fetch_rce_pln.parse_rce_datetime") as mock_parse:
                mock_parse.side_effect = lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
                from summer_heater import find_daily_minimum
                result = find_daily_minimum()
        
        assert result.hour == 12
    
    @patch("summer_heater.datetime")
    def test_negative_prices(self, mock_dt):
        """Negative prices should be handled."""
        now = datetime(2026, 8, 5, 6, 0, tzinfo=TZ)
        mock_dt.now.return_value = now
        
        items, _ = make_rce_response([
            (8, 0.30), (9, -0.05), (10, -0.10), (11, 0.20),
            (12, 0.01), (13, 0.02), (14, 0.30), (15, 0.40),
        ])
        
        with patch("rce_data.fetch_rce_pln.fetch_all_from_now", return_value=(items, None)):
            with patch("rce_data.fetch_rce_pln.parse_rce_datetime") as mock_parse:
                mock_parse.side_effect = lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
                from summer_heater import find_daily_minimum
                result = find_daily_minimum()
        
        # 9+10: -0.05 + -0.10 = -0.15 (cheapest)
        assert result.hour == 9
    
    @patch("summer_heater.datetime")
    def test_no_hours_in_range(self, mock_dt):
        """No prices in 8-16 range should return fallback."""
        now = datetime(2026, 8, 5, 6, 0, tzinfo=TZ)
        mock_dt.now.return_value = now
        
        # Only hours outside 8-16
        items, _ = make_rce_response([(6, 0.50), (7, 0.60), (17, 0.70)])
        
        with patch("rce_data.fetch_rce_pln.fetch_all_from_now", return_value=(items, None)):
            with patch("rce_data.fetch_rce_pln.parse_rce_datetime") as mock_parse:
                mock_parse.side_effect = lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
                from summer_heater import find_daily_minimum
                result = find_daily_minimum()
        
        assert result.hour == 11  # fallback


class TestPlanSummerHeating:
    """Tests for plan_summer_heating scheduling logic."""
    
    @patch("summer_heater.schedule_task", return_value=True)
    @patch("summer_heater.cleanup_tasks")
    @patch("summer_heater.find_daily_minimum")
    @patch("summer_heater.datetime")
    def test_schedules_on_and_off(self, mock_dt, mock_find, mock_cleanup, mock_schedule):
        """Should schedule ON at window start and OFF at window start + 2h."""
        now = datetime(2026, 8, 5, 6, 0, tzinfo=TZ)
        mock_dt.now.return_value = now
        
        window_start = datetime(2026, 8, 5, 12, 0, tzinfo=TZ)
        mock_find.return_value = window_start
        
        from summer_heater import plan_summer_heating
        plan_summer_heating()
        
        mock_cleanup.assert_called_once()
        assert mock_schedule.call_count == 2
        
        # First call: ON at 12:00
        on_call = mock_schedule.call_args_list[0]
        assert on_call[0][0] == window_start
        assert on_call[0][2] == "on"
        
        # Second call: OFF at 14:00
        off_call = mock_schedule.call_args_list[1]
        assert off_call[0][0] == window_start + timedelta(hours=2)
        assert off_call[0][2] == "off"
    
    @patch("summer_heater.schedule_task", return_value=True)
    @patch("summer_heater.cleanup_tasks")
    @patch("summer_heater.find_daily_minimum")
    @patch("summer_heater.datetime")
    def test_skips_past_on_time(self, mock_dt, mock_find, mock_cleanup, mock_schedule):
        """If ON time already passed, skip it but still schedule OFF."""
        now = datetime(2026, 8, 5, 12, 30, tzinfo=TZ)
        mock_dt.now.return_value = now
        
        # Window starts at 12:00, but it's already 12:30
        window_start = datetime(2026, 8, 5, 12, 0, tzinfo=TZ)
        mock_find.return_value = window_start
        
        from summer_heater import plan_summer_heating
        plan_summer_heating()
        
        # Only OFF should be scheduled (14:00 > 12:30)
        assert mock_schedule.call_count == 1
        off_call = mock_schedule.call_args_list[0]
        assert off_call[0][2] == "off"
    
    @patch("summer_heater.schedule_task", return_value=True)
    @patch("summer_heater.cleanup_tasks")
    @patch("summer_heater.find_daily_minimum")
    @patch("summer_heater.datetime")
    def test_skips_both_if_past(self, mock_dt, mock_find, mock_cleanup, mock_schedule):
        """If both ON and OFF times passed, schedule nothing."""
        now = datetime(2026, 8, 5, 15, 0, tzinfo=TZ)
        mock_dt.now.return_value = now
        
        # Window 12:00-14:00, but it's already 15:00
        window_start = datetime(2026, 8, 5, 12, 0, tzinfo=TZ)
        mock_find.return_value = window_start
        
        from summer_heater import plan_summer_heating
        plan_summer_heating()
        
        mock_schedule.assert_not_called()
