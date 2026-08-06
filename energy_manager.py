"""
Energy Manager - bezstanowy moduł zarządzania energią.

Sam rozpoznaje co robić na podstawie: pory dnia, ceny RCE, SOC.
Pogoda wpływa tylko na limit SOC wieczorem.
"""
from __future__ import annotations

import argparse
import logging
import os
import platform
import shlex
import subprocess
import sys
import time
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from typing import Optional, Tuple
from dataclasses import dataclass

from CONFIG import *
from zoneinfo import ZoneInfo

WARSAW_TZ = ZoneInfo(TIMEZONE)
PYTHON_EXE = sys.executable

# === Logging ===
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "energy_automation.log")
log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=2)
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO)

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(log_formatter)
stream_handler.setLevel(logging.INFO)

if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, handlers=[file_handler, stream_handler])

logger = logging.getLogger(__name__)


@dataclass
class EnergyState:
    """Aktualny stan systemu."""
    soc: Optional[float] = None
    pv_power: Optional[float] = None
    rce_price: Optional[float] = None
    cloud_cover_tomorrow: Optional[float] = None
    current_hour: int = 0


# === Retry decorator ===
def with_retry(func):
    """Decorator dodający retry do funkcji API."""
    def wrapper(*args, **kwargs):
        last_error = None
        for attempt in range(API_RETRY_ATTEMPTS):
            try:
                result = func(*args, **kwargs)
                if result is not None:
                    return result
            except Exception as e:
                last_error = e
                logger.warning(f"{func.__name__} attempt {attempt + 1}/{API_RETRY_ATTEMPTS} failed: {e}")
            if attempt < API_RETRY_ATTEMPTS - 1:
                time.sleep(API_RETRY_DELAY_SECONDS)
        logger.error(f"{func.__name__} failed after {API_RETRY_ATTEMPTS} attempts: {last_error}")
        return None
    return wrapper


# === Data fetching ===
@with_retry
def fetch_deye_data() -> Optional[Tuple[float, float]]:
    """Pobiera SOC i moc PV z Deye Cloud."""
    from deye_client.auth import DeyeCloudAPI
    from deye_client.data_retriever import DeyeCloudDataRetriever
    from deye_client.config import CONFIG as DEYE_CONFIG
    from deye_client.check_heater import extract_values_from_latest, _to_float
    
    api = DeyeCloudAPI(region=DEYE_CONFIG.get("REGION", "eu"))
    if not api.obtain_token(
        app_id=DEYE_CONFIG.get("APP_ID", ""),
        app_secret=DEYE_CONFIG.get("APP_SECRET", ""),
        email=DEYE_CONFIG.get("EMAIL", ""),
        password=DEYE_CONFIG.get("PASSWORD", ""),
    ):
        raise Exception("Deye authentication failed")
    
    retriever = DeyeCloudDataRetriever(api)
    stations_resp = retriever.get_station_list()
    stations = (stations_resp or {}).get("stationList") or (stations_resp or {}).get("data") or []
    if not stations:
        raise Exception("No stations found")
    
    station = stations[0]
    device_sn = str(station.get("deviceSn") or station.get("sn") or "")
    soc = _to_float(station.get("batterySOC"))
    pv_power = _to_float(station.get("generationPower"))
    
    if device_sn:
        latest = retriever.get_device_latest_data(device_sn)
        if latest:
            dev_soc, dev_pv = extract_values_from_latest(latest)
            soc = dev_soc if dev_soc is not None else soc
            pv_power = dev_pv if dev_pv is not None else pv_power
    
    if soc is None:
        raise Exception("Could not get SOC")
    
    logger.info(f"Deye: SOC={soc}%, PV={pv_power}W")
    return soc, pv_power or 0


@with_retry
def fetch_rce_price() -> Optional[float]:
    """Pobiera aktualna cene RCE w PLN/kWh. Fallback: SELL_THRESHOLD (bezpieczna wartosc)."""
    from rce_data.fetch_rce_pln import fetch_all_from_now
    items, _ = fetch_all_from_now()
    if not items:
        raise Exception("No RCE data")
    price_kwh = float(items[0].get("rce_pln") or items[0].get("rce") or 0) / 1000.0
    logger.info(f"RCE: {price_kwh:.4f} PLN/kWh")
    return price_kwh


@with_retry  
def fetch_cloud_cover_tomorrow() -> Optional[float]:
    """Pobiera średnie zachmurzenie jutro (7-18)."""
    from meteo.open_meteo import how_sunny_tomorrow
    return how_sunny_tomorrow(LAT, LON, TIMEZONE)


def get_state() -> EnergyState:
    """Pobiera pelny stan systemu. Uzywa fallbackow gdy API nie dziala."""
    state = EnergyState()
    state.current_hour = datetime.now(WARSAW_TZ).hour
    
    deye = fetch_deye_data()
    if deye:
        state.soc, state.pv_power = deye
    
    state.rce_price = fetch_rce_price()
    # Fallback dla ceny: uzyj progu (nie sprzedawaj, nie kupuj)
    if state.rce_price is None:
        state.rce_price = SELL_THRESHOLD
        logger.warning(f"RCE API failed - using threshold {SELL_THRESHOLD} as fallback")
    
    # Pogoda jutro tylko wieczorem (potrzebna do limitu SOC)
    if state.current_hour >= EVENING_PEAK_START_HOUR:
        state.cloud_cover_tomorrow = fetch_cloud_cover_tomorrow()
        # Fallback: 50% zachmurzenia = domyslny limit SOC
    
    return state


# === Decision helpers ===
def get_evening_soc_limit(cloud_cover_tomorrow: Optional[float]) -> int:
    """Limit SOC wieczorem zależny od pogody jutro i MORNING_SELL_ENABLED."""
    if not MORNING_SELL_ENABLED:
        # Bez porannej sprzedazy - niższy limit, sprzedajemy więcej wieczorem
        return 35
    if cloud_cover_tomorrow is None:
        return EVENING_SELL_SOC_DEFAULT
    if cloud_cover_tomorrow < VERY_SUNNY_CLOUD_THRESHOLD:
        return EVENING_SELL_SOC_SUNNY
    if cloud_cover_tomorrow > SUNNY_CLOUD_THRESHOLD:
        return EVENING_SELL_SOC_CLOUDY
    return EVENING_SELL_SOC_DEFAULT


def is_evening() -> bool:
    """Czy jest wieczór (17-24)."""
    hour = datetime.now(WARSAW_TZ).hour
    return EVENING_PEAK_START_HOUR <= hour < EVENING_PEAK_END_HOUR


def is_low_price(price: Optional[float]) -> bool:
    """Czy cena jest poniżej progu opłacalności."""
    return price is not None and price < SELL_THRESHOLD


# === Inverter control ===
@with_retry
def set_inverter_mode(selling: bool) -> bool:
    """Ustawia tryb falownika."""
    from deye_client.auth import DeyeCloudAPI
    from deye_client.data_retriever import DeyeCloudDataRetriever
    from deye_client.config import CONFIG as DEYE_CONFIG
    
    api = DeyeCloudAPI(region=DEYE_CONFIG.get("REGION", "eu"))
    if not api.obtain_token(
        app_id=DEYE_CONFIG.get("APP_ID", ""),
        app_secret=DEYE_CONFIG.get("APP_SECRET", ""),
        email=DEYE_CONFIG.get("EMAIL", ""),
        password=DEYE_CONFIG.get("PASSWORD", ""),
    ):
        raise Exception("Deye auth failed")
    
    retriever = DeyeCloudDataRetriever(api)
    mode = "SELLING_FIRST" if selling else "ZERO_EXPORT_TO_CT"
    resp = retriever.set_system_work_mode(mode)
    
    if resp and resp.get("success"):
        logger.info(f"Falownik: {mode}")
        return True
    raise Exception(f"set_work_mode failed: {resp}")


# === Heater control ===
def control_heater(state: EnergyState) -> None:
    """
    Control heater.
    Turn on when SOC >= 98% AND PV > 500W AND price < threshold
    """
    from smart_life.heater_control import SmartLifePlug, load_config, DEFAULT_CONFIG_PATH
    
    try:
        config = load_config(DEFAULT_CONFIG_PATH)
        plug = SmartLifePlug(config)
        is_on = plug.is_on()
        
        soc = state.soc or 0
        pv = state.pv_power or 0
        price = state.rce_price or 999
        
        logger.info(f"Heater: {'ON' if is_on else 'OFF'}, SOC={soc}%, PV={pv}W, price={price:.4f}")
        
        if not is_on:
            soc_ok = soc >= TRESHOLD_SOC_ON
            price_ok = price < SELL_THRESHOLD
            pv_ok = pv > TRESHOLD_PV_POWER
            
            if soc_ok and price_ok and pv_ok:
                logger.info("Turning heater ON")
                plug.turn_on()
            else:
                logger.info(f"Conditions not met: SOC>={TRESHOLD_SOC_ON}?{soc_ok}, price<{SELL_THRESHOLD}?{price_ok}, PV>{TRESHOLD_PV_POWER}?{pv_ok}")
        else:
            soc_low = soc <= TRESHOLD_SOC_OFF
            pv_low = pv < TRESHOLD_PV_POWER
            
            if soc_low or pv_low:
                logger.info(f"Turning heater OFF: SOC<={TRESHOLD_SOC_OFF}?{soc_low}, PV<{TRESHOLD_PV_POWER}?{pv_low}")
                plug.turn_off()
            else:
                logger.info("Heater stays ON")
                
    except Exception as e:
        logger.error(f"Heater error: {e}")


# === Main logic ===
def manage_energy() -> Optional[float]:
    """
    Main function - auto-detects what to do:
    
    EVENING (17-24):
        Sell if: price >= threshold AND SOC > limit (depends on tomorrow weather)
    
    DAY:
        Price < threshold: don't sell, control heater
        Price >= threshold: sell
    
    Returns SOC or None on error.
    If Deye API fails - no action taken (safety).
    """
    logger.info("=" * 50)
    state = get_state()
    
    # Deye API is critical - without SOC we can't make decisions
    if state.soc is None:
        logger.error("Deye API failed - no action taken (safety)")
        return None
    
    logger.info(f"Hour: {state.current_hour}, SOC: {state.soc}%, Price: {state.rce_price:.4f}, Threshold: {SELL_THRESHOLD}")
    
    # === EVENING ===
    if is_evening():
        soc_limit = get_evening_soc_limit(state.cloud_cover_tomorrow)
        logger.info(f"EVENING - SOC limit: {soc_limit}% (tomorrow cloud: {state.cloud_cover_tomorrow}%)")
        
        if state.soc > soc_limit and state.rce_price >= SELL_THRESHOLD:
            logger.info(f"Selling: SOC {state.soc}% > {soc_limit}%, price {state.rce_price:.4f} >= {SELL_THRESHOLD}")
            set_inverter_mode(selling=True)
        else:
            reason = f"SOC {state.soc}% <= {soc_limit}%" if state.soc <= soc_limit else f"price {state.rce_price:.4f} < {SELL_THRESHOLD}"
            logger.info(f"Stop selling: {reason}")
            set_inverter_mode(selling=False)
        
        return state.soc
    
    # === DAY ===
    if not MORNING_SELL_ENABLED and state.current_hour < EVENING_PEAK_START_HOUR:
        logger.info(f"DAY - morning sell disabled, not selling (MORNING_SELL_ENABLED=False)")
        set_inverter_mode(selling=False)
        control_heater(state)
    elif is_low_price(state.rce_price):
        logger.info(f"DAY - low price ({state.rce_price:.4f} < {SELL_THRESHOLD}), heater control")
        set_inverter_mode(selling=False)
        control_heater(state)
    else:
        logger.info(f"DAY - high price ({state.rce_price:.4f} >= {SELL_THRESHOLD}), selling")
        set_inverter_mode(selling=True)
    
    return state.soc


def calculate_next_check_minutes(state: EnergyState) -> int:
    """Oblicza czas do następnego sprawdzenia."""
    if state.soc is None:
        return MIN_CHECK_INTERVAL_MINUTES
    
    if is_evening():
        soc_limit = get_evening_soc_limit(state.cloud_cover_tomorrow)
        minutes = abs(state.soc - soc_limit) * MINUTES_PER_SOC_PERCENT
    else:
        minutes = abs(state.soc - TRESHOLD_SOC_OFF) * MINUTES_PER_SOC_PERCENT
    
    return max(int(minutes), MIN_CHECK_INTERVAL_MINUTES)


def should_continue_periodic(state: EnergyState) -> bool:
    """Czy kontynuować tryb periodic."""
    if state.soc is None:
        return False
    
    if is_evening():
        soc_limit = get_evening_soc_limit(state.cloud_cover_tomorrow)
        return state.soc > soc_limit
    else:
        return is_low_price(state.rce_price)


# === Self-scheduling ===
def schedule_next_run(minutes: int, end_hour: int) -> None:
    """Schedule next run."""
    script = os.path.abspath(__file__)
    next_time = datetime.now(WARSAW_TZ) + timedelta(minutes=minutes)
    
    if next_time.hour >= end_hour:
        logger.info(f"End of window ({end_hour}:00) - disabling selling")
        set_inverter_mode(selling=False)
        return
    
    args = f"--periodic --until {end_hour}"
    task = "EnergyPeriodicCheck"
    
    if platform.system() == "Windows":
        tr = f'"{PYTHON_EXE}" "{script}" {args}'
        cmd = f'schtasks /create /sc once /tn "{task}" /tr "{tr}" /st {next_time.strftime("%H:%M")} /sd {next_time.strftime("%d/%m/%Y")} /f'
    else:
        tr = f"{shlex.quote(PYTHON_EXE)} {shlex.quote(script)} {args}"
        cmd = f"echo {shlex.quote(tr)} | at {next_time.strftime('%H:%M %Y-%m-%d')}"
    
    logger.info(f"Next check in {minutes} min ({next_time.strftime('%H:%M')})")
    subprocess.run(cmd, shell=True, capture_output=True)


# === CLI ===
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Energy Manager")
    parser.add_argument("--periodic", action="store_true", help="Tryb cykliczny")
    parser.add_argument("--until", type=int, default=24, help="Godzina zakończenia cyklu")
    parser.add_argument("--dry-run", action="store_true", help="Tylko pokaż stan")
    args = parser.parse_args()
    
    # Lock file - zapobiega równoległym uruchomieniom
    from file_lock import FileLock
    lock_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".energy_manager.lock")
    lock = FileLock(lock_file_path)
    if not lock.acquire():
        logger.warning("Another energy_manager instance is running - exiting")
        sys.exit(0)
    
    try:
        logger.info("######### Energy Manager Start ##########")
        
        if args.dry_run:
            state = get_state()
            logger.info(f"SOC={state.soc}%, cena={state.rce_price}, wieczór={is_evening()}, SUMMER_MODE={SUMMER_MODE}")
            sys.exit(0)
        
        soc = manage_energy()
        
        if args.periodic and soc is not None:
            state = get_state()
            if should_continue_periodic(state):
                minutes = calculate_next_check_minutes(state)
                schedule_next_run(minutes, args.until)
            else:
                logger.info("Periodic conditions not met - ending")
                set_inverter_mode(selling=False)
    finally:
        lock.release()
