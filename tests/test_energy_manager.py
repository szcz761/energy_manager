"""
Tests for energy_manager - decision logic and state handling.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from zoneinfo import ZoneInfo

# Must mock CONFIG before importing energy_manager
import CONFIG

TZ = ZoneInfo("Europe/Warsaw")


class TestEnergyState:
    """Tests for EnergyState dataclass."""
    
    def test_default_state(self):
        from energy_manager import EnergyState
        state = EnergyState()
        assert state.soc is None
        assert state.pv_power is None
        assert state.rce_price is None
        assert state.cloud_cover_tomorrow is None
        assert state.current_hour == 0


class TestGetEveningSocLimit:
    """Tests for get_evening_soc_limit."""
    
    def test_none_cloud_cover(self):
        from energy_manager import get_evening_soc_limit
        assert get_evening_soc_limit(None) == CONFIG.EVENING_SELL_SOC_DEFAULT
    
    def test_very_sunny(self):
        from energy_manager import get_evening_soc_limit
        # Below VERY_SUNNY_CLOUD_THRESHOLD (35)
        assert get_evening_soc_limit(20.0) == CONFIG.EVENING_SELL_SOC_SUNNY
    
    def test_cloudy(self):
        from energy_manager import get_evening_soc_limit
        # Above SUNNY_CLOUD_THRESHOLD (85)
        assert get_evening_soc_limit(90.0) == CONFIG.EVENING_SELL_SOC_CLOUDY
    
    def test_moderate(self):
        from energy_manager import get_evening_soc_limit
        # Between 35 and 85
        assert get_evening_soc_limit(50.0) == CONFIG.EVENING_SELL_SOC_DEFAULT
    
    def test_boundary_very_sunny(self):
        from energy_manager import get_evening_soc_limit
        # Exactly at threshold
        assert get_evening_soc_limit(35.0) == CONFIG.EVENING_SELL_SOC_DEFAULT
    
    def test_boundary_cloudy(self):
        from energy_manager import get_evening_soc_limit
        # Exactly at threshold (> not >=)
        assert get_evening_soc_limit(85.0) == CONFIG.EVENING_SELL_SOC_DEFAULT
        assert get_evening_soc_limit(85.1) == CONFIG.EVENING_SELL_SOC_CLOUDY


class TestIsLowPrice:
    """Tests for is_low_price."""
    
    def test_none_price(self):
        from energy_manager import is_low_price
        assert is_low_price(None) is False
    
    def test_below_threshold(self):
        from energy_manager import is_low_price
        assert is_low_price(0.20) is True
    
    def test_at_threshold(self):
        from energy_manager import is_low_price
        assert is_low_price(CONFIG.SELL_THRESHOLD) is False
    
    def test_above_threshold(self):
        from energy_manager import is_low_price
        assert is_low_price(0.50) is False
    
    def test_negative_price(self):
        from energy_manager import is_low_price
        assert is_low_price(-0.05) is True
    
    def test_zero_price(self):
        from energy_manager import is_low_price
        assert is_low_price(0.0) is True


class TestCalculateNextCheckMinutes:
    """Tests for calculate_next_check_minutes."""
    
    def test_soc_none(self):
        from energy_manager import calculate_next_check_minutes, EnergyState
        state = EnergyState(soc=None)
        assert calculate_next_check_minutes(state) == CONFIG.MIN_CHECK_INTERVAL_MINUTES
    
    @patch("energy_manager.is_evening", return_value=False)
    def test_day_high_soc(self, _):
        from energy_manager import calculate_next_check_minutes, EnergyState
        state = EnergyState(soc=95.0)
        result = calculate_next_check_minutes(state)
        expected = int(abs(95.0 - CONFIG.TRESHOLD_SOC_OFF) * CONFIG.MINUTES_PER_SOC_PERCENT)
        assert result == expected
    
    @patch("energy_manager.is_evening", return_value=False)
    def test_day_low_soc(self, _):
        from energy_manager import calculate_next_check_minutes, EnergyState
        state = EnergyState(soc=20.0)
        result = calculate_next_check_minutes(state)
        expected = max(int(abs(20.0 - CONFIG.TRESHOLD_SOC_OFF) * CONFIG.MINUTES_PER_SOC_PERCENT),
                       CONFIG.MIN_CHECK_INTERVAL_MINUTES)
        assert result == expected
    
    @patch("energy_manager.is_evening", return_value=False)
    def test_min_interval_floor(self, _):
        from energy_manager import calculate_next_check_minutes, EnergyState
        # SOC exactly at threshold = 0 minutes -> should use MIN
        state = EnergyState(soc=float(CONFIG.TRESHOLD_SOC_OFF))
        result = calculate_next_check_minutes(state)
        assert result == CONFIG.MIN_CHECK_INTERVAL_MINUTES
    
    @patch("energy_manager.is_evening", return_value=True)
    def test_evening_above_limit(self, _):
        from energy_manager import calculate_next_check_minutes, EnergyState
        state = EnergyState(soc=80.0, cloud_cover_tomorrow=50.0)
        result = calculate_next_check_minutes(state)
        soc_limit = CONFIG.EVENING_SELL_SOC_DEFAULT  # 50% for moderate cloud
        expected = max(int(abs(80.0 - soc_limit) * CONFIG.MINUTES_PER_SOC_PERCENT),
                       CONFIG.MIN_CHECK_INTERVAL_MINUTES)
        assert result == expected


class TestShouldContinuePeriodic:
    """Tests for should_continue_periodic."""
    
    def test_soc_none(self):
        from energy_manager import should_continue_periodic, EnergyState
        state = EnergyState(soc=None)
        assert should_continue_periodic(state) is False
    
    @patch("energy_manager.is_evening", return_value=False)
    def test_day_low_price(self, _):
        from energy_manager import should_continue_periodic, EnergyState
        state = EnergyState(soc=50.0, rce_price=0.20)
        assert should_continue_periodic(state) is True
    
    @patch("energy_manager.is_evening", return_value=False)
    def test_day_high_price(self, _):
        from energy_manager import should_continue_periodic, EnergyState
        state = EnergyState(soc=50.0, rce_price=0.50)
        assert should_continue_periodic(state) is False
    
    @patch("energy_manager.is_evening", return_value=True)
    def test_evening_above_limit(self, _):
        from energy_manager import should_continue_periodic, EnergyState
        state = EnergyState(soc=80.0, cloud_cover_tomorrow=50.0)
        # Default SOC limit = 50, SOC 80 > 50 -> True
        assert should_continue_periodic(state) is True
    
    @patch("energy_manager.is_evening", return_value=True)
    def test_evening_below_limit(self, _):
        from energy_manager import should_continue_periodic, EnergyState
        state = EnergyState(soc=30.0, cloud_cover_tomorrow=50.0)
        # Default SOC limit = 50, SOC 30 <= 50 -> False
        assert should_continue_periodic(state) is False


class TestManageEnergy:
    """Integration tests for manage_energy (mocked external calls)."""
    
    @patch("energy_manager.set_inverter_mode")
    @patch("energy_manager.get_state")
    def test_deye_failure_returns_none(self, mock_state, mock_inverter):
        from energy_manager import manage_energy, EnergyState
        mock_state.return_value = EnergyState(soc=None, rce_price=0.5)
        result = manage_energy()
        assert result is None
        mock_inverter.assert_not_called()
    
    @patch("energy_manager.control_heater")
    @patch("energy_manager.set_inverter_mode")
    @patch("energy_manager.is_evening", return_value=False)
    @patch("energy_manager.get_state")
    def test_day_high_price_sells(self, mock_state, mock_evening, mock_inverter, mock_heater):
        from energy_manager import manage_energy, EnergyState
        mock_state.return_value = EnergyState(soc=60.0, pv_power=3000, rce_price=0.55, current_hour=10)
        result = manage_energy()
        assert result == 60.0
        mock_inverter.assert_called_once_with(selling=True)
        mock_heater.assert_not_called()
    
    @patch("energy_manager.control_heater")
    @patch("energy_manager.set_inverter_mode")
    @patch("energy_manager.is_evening", return_value=False)
    @patch("energy_manager.get_state")
    def test_day_low_price_controls_heater(self, mock_state, mock_evening, mock_inverter, mock_heater):
        from energy_manager import manage_energy, EnergyState
        state = EnergyState(soc=95.0, pv_power=4000, rce_price=0.10, current_hour=12)
        mock_state.return_value = state
        result = manage_energy()
        assert result == 95.0
        mock_inverter.assert_called_once_with(selling=False)
        mock_heater.assert_called_once_with(state)
    
    @patch("energy_manager.set_inverter_mode")
    @patch("energy_manager.is_evening", return_value=True)
    @patch("energy_manager.get_state")
    def test_evening_high_soc_high_price_sells(self, mock_state, mock_evening, mock_inverter):
        from energy_manager import manage_energy, EnergyState
        mock_state.return_value = EnergyState(
            soc=80.0, pv_power=0, rce_price=0.55, 
            current_hour=20, cloud_cover_tomorrow=50.0
        )
        result = manage_energy()
        assert result == 80.0
        mock_inverter.assert_called_once_with(selling=True)
    
    @patch("energy_manager.set_inverter_mode")
    @patch("energy_manager.is_evening", return_value=True)
    @patch("energy_manager.get_state")
    def test_evening_low_soc_stops_selling(self, mock_state, mock_evening, mock_inverter):
        from energy_manager import manage_energy, EnergyState
        mock_state.return_value = EnergyState(
            soc=30.0, pv_power=0, rce_price=0.55,
            current_hour=20, cloud_cover_tomorrow=50.0
        )
        result = manage_energy()
        assert result == 30.0
        mock_inverter.assert_called_once_with(selling=False)
    
    @patch("energy_manager.set_inverter_mode")
    @patch("energy_manager.is_evening", return_value=True)
    @patch("energy_manager.get_state")
    def test_evening_low_price_stops_selling(self, mock_state, mock_evening, mock_inverter):
        from energy_manager import manage_energy, EnergyState
        mock_state.return_value = EnergyState(
            soc=80.0, pv_power=0, rce_price=0.20,
            current_hour=20, cloud_cover_tomorrow=50.0
        )
        result = manage_energy()
        assert result == 80.0
        mock_inverter.assert_called_once_with(selling=False)


class TestGetState:
    """Tests for get_state with API failures."""
    
    @patch("energy_manager.fetch_cloud_cover_tomorrow", return_value=None)
    @patch("energy_manager.fetch_rce_price", return_value=None)
    @patch("energy_manager.fetch_deye_data", return_value=None)
    def test_all_apis_fail(self, mock_deye, mock_rce, mock_cloud):
        from energy_manager import get_state
        with patch("energy_manager.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 8, 5, 10, 0, tzinfo=TZ)
            # Can't fully mock datetime.now in this context, so test directly
        state = get_state()
        assert state.soc is None
        assert state.pv_power is None
        # RCE fallback to threshold
        assert state.rce_price == CONFIG.SELL_THRESHOLD
    
    @patch("energy_manager.fetch_rce_price", return_value=0.45)
    @patch("energy_manager.fetch_deye_data", return_value=(85.0, 3500.0))
    def test_successful_fetch(self, mock_deye, mock_rce):
        from energy_manager import get_state
        state = get_state()
        assert state.soc == 85.0
        assert state.pv_power == 3500.0
        assert state.rce_price == 0.45
    
    @patch("energy_manager.fetch_rce_price", return_value=None)
    @patch("energy_manager.fetch_deye_data", return_value=(50.0, 2000.0))
    def test_rce_exception_uses_fallback(self, mock_deye, mock_rce):
        from energy_manager import get_state
        state = get_state()
        assert state.soc == 50.0
        # fetch_rce_price returns None (as with_retry would after failures), then fallback kicks in
        assert state.rce_price == CONFIG.SELL_THRESHOLD
