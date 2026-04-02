from __future__ import annotations

import argparse
import logging
import os
import platform
import shlex
import subprocess
import sys
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, List, Optional, Tuple

from deye_client.auth import DeyeCloudAPI
from deye_client.data_retriever import DeyeCloudDataRetriever
from deye_client.config import CONFIG as DEYE_CONFIG
from deye_client.check_heater import (
    extract_values_from_latest,
    POSSIBLE_PV_KEYS,
    POSSIBLE_SOC_KEYS,
    _to_float,
)

PYTHON_EXE = sys.executable
# from energy_scheduler import PYTHON_EXE
from meteo.open_meteo import fetch_weather_forecast, is_sunny_day
from rce_data.fetch_rce_pln import WARSAW_TZ, fetch_all_from_now
from smart_life.heater_control import (
    SmartLifePlug,
    load_config as load_smart_life_config,
    DEFAULT_CONFIG_PATH as SMART_LIFE_CONFIG_PATH,
)


# Configure logging
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "energy_automation.log")
log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] (Manager) %(message)s")

file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=2)
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO)

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(log_formatter)
stream_handler.setLevel(logging.INFO)

# Only configure root logger if no handlers are present (e.g. not imported by scheduler)
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, handlers=[file_handler, stream_handler])

logger = logging.getLogger(__name__)
# If we are the main script, we might want to ensure our logger has the correct level and handlers
# but basicConfig handles root. For named logger we can just rely on propagation.

# Updated values from utility bill:
GAS_PRICE = 0.20426  # "Gas fuel" line item
DYSTRYBUTION_GAS = 0.05388  # "Variable distribution" line item
VAT = 1.23  # current VAT rate
EFITENSY_HEATING_GAS = 0.80  # keep 0.80 or adjust based on boiler specification

# Calculation:
PRICE_POWER_I_BUY = 1.38  # current electricity buy price
PRICE_HEAT_FROM_GAS = (GAS_PRICE + DYSTRYBUTION_GAS) * VAT / EFITENSY_HEATING_GAS
TRESHOLD_PRICE_POWER_GAS = PRICE_HEAT_FROM_GAS * 0.99  # around PLN 0.39 / kWh

TRESHOLD_SOC_ON = 98
TRESHOLD_SOC_OFF = 90
TRESHOLD_PV_POWER = 500


def get_deye_data() -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """Fetches SOC, PV Power and Device SN from Deye Cloud."""
    api: DeyeCloudAPI = DeyeCloudAPI(region=DEYE_CONFIG.get("REGION", "eu"))
    ok: bool = api.obtain_token(
        app_id=DEYE_CONFIG.get("APP_ID", ""),
        app_secret=DEYE_CONFIG.get("APP_SECRET", ""),
        email=DEYE_CONFIG.get("EMAIL", ""),
        password=DEYE_CONFIG.get("PASSWORD", ""),
    )
    if not ok:
        logger.error("Deye authentication failed")
        return None, None, None

    retriever: DeyeCloudDataRetriever = DeyeCloudDataRetriever(api)

    device_sn: Optional[str] = None
    soc_fallback: Optional[float] = None
    pv_fallback: Optional[float] = None

    # 2. Fallback to station list
    stations_response: Optional[Dict[str, Any]] = retriever.get_station_list()
    stations: List[Any] = []
    if stations_response:
        stations = stations_response.get("stationList") or stations_response.get("data") or []

    if not stations:
        logger.error(f"No stations found either. Response: {stations_response}")
        return None, None, None

    first_station: Dict[str, Any] = stations[0]
    station_id: Any = first_station.get("id")

    # Check if station list entry has SN
    device_sn = str(first_station.get("deviceSn") or first_station.get("sn") or "")

    # Extract values directly from station record as fallback
    soc_fallback = _to_float(first_station.get("batterySOC"))
    pv_fallback = _to_float(first_station.get("generationPower"))

    # 3. Get station latest data
    station_data_response: Optional[Dict[str, Any]] = retriever.get_station_latest_data(station_id)
    if not station_data_response:
        logger.error(f"Failed to get data for station {station_id}")
        # If we already have device_sn from station list, we can still continue to step 5
        if not device_sn:
            return soc_fallback, pv_fallback, device_sn
    else:
        station_data: Dict[str, Any] = station_data_response.get("data") or {}

        # 4. Check if station data contains a device SN
        if not device_sn:
            device_sn = str(station_data.get("deviceSn") or station_data.get("sn") or "")

        # If station record doesn't include device SN, try station/device endpoint
        if not device_sn:
            station_devices_resp = retriever.get_station_devices([station_id])
            devices_list = []
            if station_devices_resp:
                devices_list = (
                    station_devices_resp.get("deviceList")
                    or station_devices_resp.get("data")
                    or station_devices_resp.get("deviceListItems")
                    or []
                )
            if isinstance(devices_list, list) and devices_list:
                first_dev = devices_list[0]
                device_sn = str(first_dev.get("deviceSn") or first_dev.get("sn") or "")

        if not device_sn:
            # Try to extract SOC/PV directly from station data as fallback
            logger.info("No device SN in station data, attempting to extract values directly.")
            soc: Optional[float] = None
            pv_power: Optional[float] = None

            for key in POSSIBLE_SOC_KEYS:
                if key in station_data:
                    soc = _to_float(station_data[key])
                    if soc is not None:
                        break

            for key in POSSIBLE_PV_KEYS:
                if key in station_data:
                    pv_power = _to_float(station_data[key])
                    if pv_power is not None:
                        break

            # Use fallbacks if station_data didn't have them
            soc = soc if soc is not None else soc_fallback
            pv_power = pv_power if pv_power is not None else pv_fallback

            if soc is not None or pv_power is not None:
                logger.info(f"Extracted from station: SOC={soc}%, PV={pv_power}W")
                return soc, pv_power, device_sn

            logger.error(f"Could not find device SN or data in station. Keys: {list(station_data.keys())}")
            return None, None, None

    # 5. Get latest data for the found device SN
    latest_response: Optional[Dict[str, Any]] = retriever.get_device_latest_data(device_sn)
    soc, pv_power = extract_values_from_latest(latest_response)

    # Use fallbacks if latest data is missing
    if soc is None and soc_fallback is not None:
        soc = soc_fallback
    if pv_power is None and pv_fallback is not None:
        pv_power = pv_fallback

    if soc is None or pv_power is None:
        logger.warning(f"Could not extract SOC/PV from device {device_sn} latest data. Response: {latest_response}")
        # Final attempt: maybe station data has it and we haven't checked yet (if we came from device list)
        # But if we have a device SN, the device latest data should be the source of truth.

    logger.info(f"Deye Data - Device: {device_sn}, SOC: {soc}%, PV Power: {pv_power}W")
    return soc, pv_power, device_sn


def get_current_rce_price() -> Optional[float]:
    """Fetches the current RCE price (PLN)."""
    try:
        items, _ = fetch_all_from_now()
        if not items:
            logger.warning("No RCE price data available for the current time")
            return None

        # The first item should be the current/closest future price
        # fetch_all_from_now filters for dtime >= now
        current_item = items[0]
        current_price_str: Any = current_item.get("rce_pln") or current_item.get("rce")
        if current_price_str is None:
            logger.warning(f"RCE field missing in data. Keys: {list(current_item.keys())}")
            return None

        price_mwh: float = float(current_price_str)
        price_kwh: float = price_mwh / 1000.0
        logger.info(f"Current RCE Price: {price_mwh:.2f} PLN/MWh ({price_kwh:.4f} PLN/kWh)")
        return price_kwh
    except Exception as e:
        logger.error(f"Error fetching RCE price: {e}")
        return None


def manage_energy() -> Optional[float]:
    """Main entry for legacy/standalone energy management."""
    soc, pv_power, device_sn = get_deye_data()
    rce_price_kwh = get_current_rce_price()

    if rce_price_kwh is None:
        logger.error("Could not fetch RCE price. Aborting energy management.")
        return None

    if soc is None or pv_power is None or device_sn is None:
        logger.warning("Inverter data (SOC/PV/SN) missing. Cannot make full decision.")
        return soc

    manage_sell_power(rce_price_kwh)
    manage_heater_on_off(soc, pv_power, rce_price_kwh)
    return soc


def manage_sell_power(rce_price_kwh):
    weather_data = fetch_weather_forecast()
    api: DeyeCloudAPI = DeyeCloudAPI(region=DEYE_CONFIG.get("REGION", "eu"))
    api.obtain_token(
        app_id=DEYE_CONFIG.get("APP_ID", ""),
        app_secret=DEYE_CONFIG.get("APP_SECRET", ""),
        email=DEYE_CONFIG.get("EMAIL", ""),
        password=DEYE_CONFIG.get("PASSWORD", ""),
    )
    retriever = DeyeCloudDataRetriever(api)

    if is_sunny_day(weather_data) and datetime.now().hour < 12 and rce_price_kwh > TRESHOLD_PRICE_POWER_GAS:
        logger.info(
            f"Price {rce_price_kwh:.4f} > Threshold {TRESHOLD_PRICE_POWER_GAS:.4f}. Setting Deye to 'SELLING_FIRST'."
        )
        resp = retriever.set_system_work_mode("SELLING_FIRST")
        if not resp or resp.get("success") is not True:
            logger.warning(
                "set_system_work_mode did not report success; not attempting /order/battery/modeControl as it's for battery charge-mode actions."
            )
    else:
        logger.info(
            f"Price {rce_price_kwh:.4f} <= Threshold {TRESHOLD_PRICE_POWER_GAS:.4f}. or Not a sunny day. Setting Deye to 'ZERO_EXPORT_TO_CT'."
        )
        resp = retriever.set_system_work_mode("ZERO_EXPORT_TO_CT")
        if not resp or resp.get("success") is not True:
            logger.warning(
                "set_system_work_mode did not report success; not attempting /order/battery/modeControl as it's for battery charge-mode actions."
            )


def manage_heater_on_off(soc, pv_power, rce_price_kwh):
    try:
        smart_life_config = load_smart_life_config(SMART_LIFE_CONFIG_PATH)
        plug = SmartLifePlug(smart_life_config)
        is_heater_on: bool = plug.is_on()
        logger.info(f"Current heater state: {'ON' if is_heater_on else 'OFF'}")

        if not is_heater_on:
            if (
                (pv_power > TRESHOLD_PV_POWER)
                and (soc >= TRESHOLD_SOC_ON)
                and (rce_price_kwh < TRESHOLD_PRICE_POWER_GAS)
            ):
                logger.info("Conditions MET. Turning ON the heater.")
                plug.turn_on()
            else:
                logger.info("Conditions NOT MET for turning ON. Staying OFF.")
        else:
            if (soc <= TRESHOLD_SOC_OFF) or (pv_power < TRESHOLD_PV_POWER):
                logger.info(f"Conditions MET for turning OFF: SOC={soc}% or PV={pv_power}W. Turning OFF.")
                plug.turn_off()
            else:
                logger.info("Conditions NOT MET for turning OFF. Staying ON.")

    except Exception as e:
        logger.error(f"Error controlling Smart Life device: {e}")


def manage_energy_periodic() -> Optional[int]:
    """Entry point for periodic energy management (e.g. called by scheduler)."""
    soc = manage_energy()
    if soc is not None:
        if soc < TRESHOLD_SOC_OFF:
            minutes_to_run_again = abs((TRESHOLD_SOC_ON - soc) * 2)
        else:
            minutes_to_run_again = abs(soc - TRESHOLD_SOC_OFF)
            minutes_to_run_again_2 = abs(soc - TRESHOLD_SOC_OFF)
            minutes_to_run_again = min(minutes_to_run_again, minutes_to_run_again_2)
        return int(minutes_to_run_again)
    return None


def run_cmd(command: str) -> bool:
    logger.info(f"Running command: {command}")
    try:
        subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {command}. Error: {e.stderr}")
        return False


def schedule_self(time: datetime, task_name: str, start_time: str, end_time: str) -> bool:
    script_path = os.path.abspath(__file__)
    st = time.strftime("%H:%M")
    sd = time.strftime("%d/%m/%Y")

    if platform.system() == "Windows":
        tr = f'"{PYTHON_EXE}" "{script_path}" --period {start_time} {end_time}'
        cmd = f'schtasks /create /sc once /tn "{task_name}" /tr "{tr}" /st {st} /sd {sd} /f'
    else:
        # On Linux, use shlex.quote to handle potential spaces in paths
        # tr is the command to be executed by at
        tr = f"{shlex.quote(PYTHON_EXE)} {shlex.quote(script_path)} --period {shlex.quote(start_time)} {shlex.quote(end_time)}"
        # We use a single quote for echo to prevent shell expansion of tr content,
        # and shlex.quote to safely wrap it.
        cmd = f"echo {shlex.quote(tr)} | at {time.strftime('%H:%M %Y-%m-%d')}"
    return run_cmd(cmd)


def manage_periodic(start: bool, start_time: str, end_time: str) -> bool:
    task_name = "EnergyPeriodicHeater"
    if start:
        minutes = manage_energy_periodic()
        if minutes is not None:
            next_time = datetime.now(WARSAW_TZ) + timedelta(minutes=minutes)
            schedule_self(next_time, task_name, start_time, end_time)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Energy Manager")
    parser.add_argument(
        "--period",
        nargs=2,
        metavar=("START", "END"),
        help="Run in periodic mode between START and END times (HH:MM) and schedule next run",
    )
    args = parser.parse_args()
    logger.info(f"######### Starting Energy Manager ##########")
    if args.period:
        start_time_str, end_time_str = args.period
        try:
            start_time = datetime.strptime(start_time_str, "%H:%M").time()
            end_time = datetime.strptime(end_time_str, "%H:%M").time()
        except ValueError as e:
            logger.error(f"Invalid time format in --period: {e}")
            sys.exit(1)

        now = datetime.now(WARSAW_TZ)
        current_time = now.time()

        if start_time <= current_time <= end_time:
            logger.info(f"Periodic mode active (within {start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}).")
            minutes = manage_energy_periodic()
            if minutes is not None:
                next_time = now + timedelta(minutes=minutes)
                logger.info(f"Scheduling next run in {minutes} minutes (at {next_time.strftime('%H:%M')}).")
                schedule_self(next_time, "EnergyPeriodicHeater", start_time_str, end_time_str)
        else:
            logger.info(
                f"Current time {current_time.strftime('%H:%M')} is outside window {start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}. Stopping."
            )
    else:
        manage_energy()
