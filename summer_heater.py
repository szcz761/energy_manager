"""
Summer Heater - prosty skrypt do grzania wody latem.

Uruchamia grzalke 1h przed dziennym minimum ceny i wylacza 1h po.
Niezalezny od energy_manager - mozna uruchamiac rownolegle.
Pozwala wylaczyc piec gazowy latem.

Uzycie:
    python summer_heater.py          # Zaplanuj na dzis
    python summer_heater.py --on     # Wlacz grzalke teraz
    python summer_heater.py --off    # Wylacz grzalke teraz
"""
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
from typing import Optional
from zoneinfo import ZoneInfo

from CONFIG import TIMEZONE, SELL_THRESHOLD

WARSAW_TZ = ZoneInfo(TIMEZONE)
PYTHON_EXE = sys.executable

# Logging
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "energy_automation.log")
log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] (SummerHeater) %(message)s")

file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=2)
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO)

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(log_formatter)
stream_handler.setLevel(logging.INFO)

if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, handlers=[file_handler, stream_handler])

logger = logging.getLogger(__name__)


def get_heater():
    """Get heater plug instance."""
    from smart_life.heater_control import SmartLifePlug, load_config, DEFAULT_CONFIG_PATH
    config = load_config(DEFAULT_CONFIG_PATH)
    return SmartLifePlug(config)


def heater_on() -> bool:
    """Turn heater ON."""
    try:
        plug = get_heater()
        plug.turn_on()
        logger.info("Heater turned ON")
        return True
    except Exception as e:
        logger.error(f"Failed to turn heater ON: {e}")
        return False


def heater_off() -> bool:
    """Turn heater OFF."""
    try:
        plug = get_heater()
        plug.turn_off()
        logger.info("Heater turned OFF")
        return True
    except Exception as e:
        logger.error(f"Failed to turn heater OFF: {e}")
        return False


def find_daily_minimum() -> Optional[datetime]:
    """
    Find the hour with lowest price during day (8:00-16:00).
    Returns datetime of the minimum price hour.
    Fallback: 12:00 (typical minimum time)
    """
    from rce_data.fetch_rce_pln import fetch_all_from_now, parse_rce_datetime
    
    now = datetime.now(WARSAW_TZ)
    today = now.date()
    fallback = now.replace(hour=12, minute=0, second=0, microsecond=0)
    
    try:
        items, _ = fetch_all_from_now()
        if not items:
            logger.warning("No RCE data - using fallback 12:00")
            return fallback
        
        # Find minimum in 8:00-16:00 range
        day_prices = []
        for item in items:
            dt = parse_rce_datetime(item["dtime"])
            if dt.date() == today and 8 <= dt.hour < 16:
                price = float(item.get("rce_pln") or item.get("rce") or 0) / 1000.0
                day_prices.append((dt, price))
        
        if not day_prices:
            logger.warning("No prices found for today 8:00-16:00 - using fallback 12:00")
            return fallback
        
        min_time, min_price = min(day_prices, key=lambda x: x[1])
        logger.info(f"Daily minimum: {min_time.strftime('%H:%M')} @ {min_price:.4f} PLN/kWh")
        return min_time
        
    except Exception as e:
        logger.error(f"Failed to find daily minimum: {e} - using fallback 12:00")
        return fallback


def schedule_task(run_time: datetime, task_name: str, action: str) -> bool:
    """Schedule heater ON or OFF at specified time."""
    script = os.path.abspath(__file__)
    
    if platform.system() == "Windows":
        tr = f'"{PYTHON_EXE}" "{script}" --{action}'
        cmd = f'schtasks /create /sc once /tn "{task_name}" /tr "{tr}" /st {run_time.strftime("%H:%M")} /sd {run_time.strftime("%d/%m/%Y")} /f'
    else:
        tr = f"{shlex.quote(PYTHON_EXE)} {shlex.quote(script)} --{action}"
        cmd = f"echo {shlex.quote(tr)} | at {run_time.strftime('%H:%M %Y-%m-%d')}"
    
    logger.info(f"Scheduling {action} at {run_time.strftime('%H:%M')}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.returncode == 0


def cleanup_tasks() -> None:
    """Remove summer heater scheduled tasks."""
    tasks = ["SummerHeaterOn", "SummerHeaterOff"]
    if platform.system() == "Windows":
        for task in tasks:
            subprocess.run(f'schtasks /delete /tn "{task}" /f', shell=True, capture_output=True)


def plan_summer_heating() -> None:
    """
    Plan summer heating for today:
    - Turn ON 1 hour before daily price minimum
    - Turn OFF 1 hour after daily price minimum
    Always schedules (uses fallback 12:00 if API fails)
    """
    logger.info("=" * 50)
    logger.info("Planning summer heating")
    
    cleanup_tasks()
    
    min_time = find_daily_minimum()  # Always returns a time (fallback 12:00)
    now = datetime.now(WARSAW_TZ)
    
    # ON: 1 hour before minimum
    on_time = min_time - timedelta(hours=1)
    if on_time > now:
        schedule_task(on_time, "SummerHeaterOn", "on")
        logger.info(f"Scheduled heater ON at {on_time.strftime('%H:%M')}")
    else:
        logger.info(f"ON time {on_time.strftime('%H:%M')} already passed")
    
    # OFF: 1 hour after minimum
    off_time = min_time + timedelta(hours=1)
    if off_time > now:
        schedule_task(off_time, "SummerHeaterOff", "off")
        logger.info(f"Scheduled heater OFF at {off_time.strftime('%H:%M')}")
    else:
        logger.info(f"OFF time {off_time.strftime('%H:%M')} already passed")


def main():
    parser = argparse.ArgumentParser(description="Summer heater scheduler")
    parser.add_argument("--on", action="store_true", help="Turn heater ON now")
    parser.add_argument("--off", action="store_true", help="Turn heater OFF now")
    args = parser.parse_args()
    
    logger.info("######### Summer Heater Start ##########")
    
    if args.on:
        heater_on()
    elif args.off:
        heater_off()
    else:
        plan_summer_heating()


if __name__ == "__main__":
    main()
