"""
Tests for energy_scheduler - plan calculation and scheduling.
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


def make_rce_items(hour_price_pairs: list[tuple[int, float]], date=None) -> list[dict]:
    """Helper: create RCE API response items from (hour, price_pln_kwh) pairs.
    Uses today's date by default so tests work regardless of when they run."""
    if date is None:
        date = datetime.now(TZ)
    items = []
    for hour, price_kwh in hour_price_pairs:
        dt = date.replace(hour=hour, minute=0, second=0, microsecond=0)
        items.append({
            "dtime": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "rce_pln": str(int(price_kwh * 1000)),  # API returns PLN/MWh as string
        })
    return items


class TestCalculatePlan:
    """Tests for calculate_plan."""
    
    @patch("energy_scheduler.get_sunrise", return_value=None)
    @patch("energy_scheduler.get_rce_prices", return_value=[])
    def test_no_prices_uses_defaults(self, mock_rce, mock_sunrise):
        from energy_scheduler import calculate_plan
        with patch("energy_scheduler.datetime") as mock_dt:
            now = datetime(2026, 8, 5, 4, 0, tzinfo=TZ)
            mock_dt.now.return_value = now
            # Can't fully replace datetime, so we test directly
        plan = calculate_plan()
        # Should have all keys
        assert "morning_sell" in plan
        assert "midday_start" in plan
        assert "evening_start" in plan
        assert "next_sunrise" in plan
    
    @patch("energy_scheduler.get_sunrise", return_value=None)
    @patch("energy_scheduler.get_rce_prices")
    def test_typical_day_plan(self, mock_rce, mock_sunrise):
        """Typical summer day with morning peak, cheap midday, evening peak."""
        from energy_scheduler import calculate_plan, WARSAW_TZ
        
        now = datetime(2026, 8, 5, 4, 0, tzinfo=TZ)
        
        # Simulate full day prices
        items = make_rce_items([
            (6, 0.45), (7, 0.65), (8, 0.70), (9, 0.40),
            (10, 0.35), (11, 0.30), (12, 0.05), (13, 0.10),
            (14, 0.35), (15, 0.40), (16, 0.45),
            (17, 0.55), (18, 0.70), (19, 0.85), (20, 0.90),
            (21, 0.75), (22, 0.50), (23, 0.30),
        ])
        mock_rce.return_value = items
        
        with patch("energy_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            # Direct call since datetime mocking is complex
        
        plan = calculate_plan()
        
        # Morning sell: most expensive 2h in 6-12 = 7+8 (0.65+0.70=1.35)
        assert plan["morning_sell"].hour == 7
        
        # Midday: cheapest 2h in 10-17 = 12+13 (0.05+0.10=0.15)
        assert plan["midday_start"].hour == 12
        
        # Evening: most expensive 2h in 17-24 = 19+20 (0.85+0.90=1.75)
        assert plan["evening_start"].hour == 19
    
    @patch("energy_scheduler.get_sunrise", return_value=None)
    @patch("energy_scheduler.get_rce_prices")
    def test_all_prices_above_threshold_no_midday(self, mock_rce, mock_sunrise):
        """When all midday prices are above threshold, midday stays at default."""
        from energy_scheduler import calculate_plan
        
        items = make_rce_items([
            (6, 0.50), (7, 0.60), (8, 0.55), (9, 0.50),
            (10, 0.45), (11, 0.42), (12, 0.41), (13, 0.43),
            (14, 0.48), (15, 0.50), (16, 0.55),
            (17, 0.60), (18, 0.70), (19, 0.80), (20, 0.75),
            (21, 0.65), (22, 0.50), (23, 0.40),
        ])
        mock_rce.return_value = items
        
        plan = calculate_plan()
        
        # All midday prices > 0.39 threshold, so midday_start should stay at default 10:00
        # avg of cheapest window (11+12: 0.42+0.41=0.83, avg=0.415) > 0.39
        assert plan["midday_start"].hour == 10  # default
    
    @patch("energy_scheduler.get_sunrise", return_value=None)
    @patch("energy_scheduler.get_rce_prices")
    def test_negative_prices_midday(self, mock_rce, mock_sunrise):
        """Negative prices should be handled and picked for midday."""
        from energy_scheduler import calculate_plan
        
        items = make_rce_items([
            (6, 0.50), (7, 0.60), (8, 0.55), (9, 0.45),
            (10, 0.30), (11, -0.05), (12, -0.10), (13, 0.20),
            (14, 0.35), (15, 0.40), (16, 0.45),
            (17, 0.55), (18, 0.70), (19, 0.80), (20, 0.75),
            (21, 0.60), (22, 0.45), (23, 0.30),
        ])
        mock_rce.return_value = items
        
        plan = calculate_plan()
        
        # Cheapest midday: 11+12 (-0.05 + -0.10 = -0.15, avg=-0.075)
        assert plan["midday_start"].hour == 11
    
    @patch("energy_scheduler.get_sunrise", return_value=None)
    @patch("energy_scheduler.get_rce_prices")
    def test_spike_in_morning(self, mock_rce, mock_sunrise):
        """Single spike shouldn't dominate if neighbour hours are cheap."""
        from energy_scheduler import calculate_plan
        
        items = make_rce_items([
            (6, 0.30), (7, 0.35), (8, 1.20), (9, 0.20),  # spike at 8, but 7+8 > 8+9
            (10, 0.25), (11, 0.20), (12, 0.10), (13, 0.15),
            (14, 0.30), (15, 0.35), (16, 0.40),
            (17, 0.50), (18, 0.60), (19, 0.70), (20, 0.65),
            (21, 0.55), (22, 0.40), (23, 0.30),
        ])
        mock_rce.return_value = items
        
        plan = calculate_plan()
        
        # Morning: 7+8=0.35+1.20=1.55, 8+9=1.20+0.20=1.40, 6+7=0.30+0.35=0.65
        # Best: 7 (start of 7+8 window)
        assert plan["morning_sell"].hour == 7
    
    @patch("energy_scheduler.get_sunrise")
    @patch("energy_scheduler.get_rce_prices", return_value=[])
    def test_sunrise_api_success(self, mock_rce, mock_sunrise):
        """Sunrise from API should be used for next_sunrise."""
        from energy_scheduler import calculate_plan
        
        sunrise_time = datetime(2026, 8, 6, 5, 23, tzinfo=TZ)
        mock_sunrise.return_value = sunrise_time
        
        plan = calculate_plan()
        assert plan["next_sunrise"] == sunrise_time
    
    @patch("energy_scheduler.get_sunrise", return_value=None)
    @patch("energy_scheduler.get_rce_prices", side_effect=Exception("API timeout"))
    def test_rce_api_crash(self, mock_rce, mock_sunrise):
        """RCE API crash should use defaults."""
        from energy_scheduler import calculate_plan
        
        plan = calculate_plan()
        # Should not raise, use defaults
        assert plan["morning_sell"].hour == 6
        assert plan["midday_start"].hour == 10
        assert plan["evening_start"].hour == 20
    
    @patch("energy_scheduler.get_sunrise", return_value=None)
    @patch("energy_scheduler.get_rce_prices")
    def test_only_one_morning_hour(self, mock_rce, mock_sunrise):
        """Only one hour in morning range - single hour fallback."""
        from energy_scheduler import calculate_plan
        
        items = make_rce_items([
            (6, 0.50),  # only one morning hour
            (10, 0.20), (11, 0.15), (12, 0.10), (13, 0.30),
            (17, 0.60), (18, 0.70), (19, 0.80), (20, 0.75),
        ])
        mock_rce.return_value = items
        
        plan = calculate_plan()
        assert plan["morning_sell"].hour == 6  # single hour fallback
    
    @patch("energy_scheduler.get_sunrise", return_value=None)
    @patch("energy_scheduler.get_rce_prices")
    def test_evening_double_peak(self, mock_rce, mock_sunrise):
        """Two peaks in evening - should pick the higher sum window."""
        from energy_scheduler import calculate_plan
        
        items = make_rce_items([
            (6, 0.50), (7, 0.55), (8, 0.50),
            (10, 0.20), (11, 0.15), (12, 0.10), (13, 0.20),
            (17, 0.80), (18, 0.40),  # first peak
            (19, 0.30), (20, 0.85), (21, 0.90),  # second peak (higher sum)
            (22, 0.40), (23, 0.30),
        ])
        mock_rce.return_value = items
        
        plan = calculate_plan()
        # 17+18: 1.20, 20+21: 1.75, 18+19: 0.70 -> best: 20
        assert plan["evening_start"].hour == 20


class TestPlanDay:
    """Tests for plan_day scheduling logic."""
    
    @patch("energy_scheduler.schedule_task", return_value=True)
    @patch("energy_scheduler.cleanup_tasks")
    @patch("energy_scheduler.calculate_plan")
    def test_skips_past_times(self, mock_plan, mock_cleanup, mock_schedule):
        """Tasks with times in the past should not be scheduled."""
        from energy_scheduler import plan_day, WARSAW_TZ
        
        now = datetime(2026, 8, 5, 12, 0, tzinfo=TZ)
        
        mock_plan.return_value = {
            "morning_sell": now.replace(hour=7),  # in the past
            "midday_start": now.replace(hour=13),  # in the future
            "evening_start": now.replace(hour=19),  # in the future
            "next_sunrise": datetime(2026, 8, 6, 5, 0, tzinfo=TZ),
        }
        
        with patch("energy_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            with patch("energy_scheduler.SUMMER_MODE", False):
                plan_day()
        
        # Morning should NOT be scheduled (past), others should be
        calls = mock_schedule.call_args_list
        task_names = [c[1].get("task_name") or c[0][1] for c in calls]
        assert "EnergyMorningSell" not in task_names
    
    @patch("energy_scheduler.subprocess.run")
    @patch("energy_scheduler.schedule_task", return_value=True)
    @patch("energy_scheduler.cleanup_tasks")
    @patch("energy_scheduler.calculate_plan")
    def test_summer_mode_schedules_heater(self, mock_plan, mock_cleanup, mock_schedule, mock_run):
        """SUMMER_MODE should schedule summer_heater.py."""
        from energy_scheduler import plan_day
        
        now = datetime(2026, 8, 5, 4, 0, tzinfo=TZ)
        mock_plan.return_value = {
            "morning_sell": now.replace(hour=7),
            "midday_start": now.replace(hour=12),
            "evening_start": now.replace(hour=19),
            "next_sunrise": datetime(2026, 8, 6, 5, 0, tzinfo=TZ),
        }
        
        with patch("energy_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            with patch("energy_scheduler.SUMMER_MODE", True):
                plan_day()
        
        # Should schedule SummerHeaterPlan
        calls = mock_schedule.call_args_list
        scheduled_scripts = [str(c) for c in calls]
        assert any("summer_heater" in str(c) for c in calls)


class TestCleanupTasks:
    """Tests for cleanup_tasks."""
    
    @patch("energy_scheduler.platform.system", return_value="Linux")
    @patch("energy_scheduler.subprocess.run")
    @patch("energy_scheduler.subprocess.check_output")
    def test_linux_cleanup_filters_correctly(self, mock_check, mock_run, mock_platform):
        """Should remove only energy-related at jobs."""
        from energy_scheduler import cleanup_tasks
        
        mock_check.side_effect = [
            # atq output
            "1\tTue Aug  5 06:15:00 2026\n2\tTue Aug  5 10:30:00 2026\n3\tTue Aug  5 08:00:00 2026\n",
            # at -c 1
            "#!/bin/sh\n/usr/bin/python3 /home/user/energy_manager.py\n",
            # at -c 2
            "#!/bin/sh\n/usr/bin/python3 /home/user/summer_heater.py --on\n",
            # at -c 3
            "#!/bin/sh\n/usr/bin/python3 /home/user/other_script.py\n",
        ]
        
        cleanup_tasks()
        
        # Should remove jobs 1 and 2 (energy_manager and summer_heater)
        atrm_calls = [c for c in mock_run.call_args_list if "atrm" in str(c)]
        assert len(atrm_calls) == 2
    
    @patch("energy_scheduler.platform.system", return_value="Linux")
    @patch("energy_scheduler.subprocess.check_output", side_effect=Exception("atq not found"))
    def test_linux_cleanup_handles_atq_failure(self, mock_check, mock_platform):
        """Should not crash if atq is not available."""
        from energy_scheduler import cleanup_tasks
        # Should not raise
        cleanup_tasks()
    
    @patch("energy_scheduler.platform.system", return_value="Windows")
    @patch("energy_scheduler.subprocess.run")
    def test_windows_cleanup(self, mock_run, mock_platform):
        """Windows cleanup should delete all task names."""
        from energy_scheduler import cleanup_tasks, TASK_NAMES
        cleanup_tasks()
        assert mock_run.call_count == len(TASK_NAMES)
