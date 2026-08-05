"""
Energy Scheduler - planuje uruchomienia energy_manager.

Uruchamiany raz dziennie o wschodzie słońca.
Planuje 3 zadania:
1. Morning sell - pojedyncze, 1h przed porannym pikiem
2. Midday periodic - gdy cena spada < próg (start okresu grzałki)
3. Evening periodic - 1h przed wieczornym pikiem
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import shlex
import subprocess
import sys
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from typing import Any, Optional
from zoneinfo import ZoneInfo

from CONFIG import *

# === Logging ===
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "energy_automation.log")
log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] (Scheduler) %(message)s")

file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=2)
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO)

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(log_formatter)
stream_handler.setLevel(logging.INFO)

logging.basicConfig(level=logging.INFO, handlers=[file_handler, stream_handler])
logger = logging.getLogger(__name__)

# === Paths ===
WARSAW_TZ = ZoneInfo(TIMEZONE)
PYTHON_EXE = sys.executable
ENERGY_MANAGER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "energy_manager.py")
ENERGY_SCHEDULER = os.path.abspath(__file__)
SUMMER_HEATER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "summer_heater.py")

TASK_NAMES = ["EnergyMorningSell", "EnergyMiddayPeriodic", "EnergyEveningPeriodic", "EnergyDailyPlan", "EnergyPeriodicCheck", "SummerHeaterOn", "SummerHeaterOff", "SummerHeaterPlan"]


def run_cmd(cmd: str) -> bool:
    """Wykonuje komendę."""
    logger.info(f"Exec: {cmd}")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Cmd failed: {e}")
        return False


def cleanup_tasks() -> None:
    """Usuwa zaplanowane taski."""
    if platform.system() == "Windows":
        for task in TASK_NAMES:
            subprocess.run(f'schtasks /delete /tn "{task}" /f', shell=True, capture_output=True)
    else:
        try:
            atq = subprocess.check_output(["atq"], text=True)
            for line in atq.splitlines():
                if not line.strip():
                    continue
                job_id = line.split()[0]
                try:
                    content = subprocess.check_output(["at", "-c", job_id], text=True)
                    if "energy_manager.py" in content or "energy_scheduler.py" in content or "summer_heater.py" in content:
                        subprocess.run(["atrm", job_id], capture_output=True)
                except Exception:
                    pass
        except Exception:
            pass


def schedule_task(run_time: datetime, task_name: str, script: str = None, args: str = "") -> bool:
    """Planuje task."""
    target = script or ENERGY_MANAGER
    
    if platform.system() == "Windows":
        tr = f'"{PYTHON_EXE}" "{target}" {args}'.strip()
        cmd = f'schtasks /create /sc once /tn "{task_name}" /tr "{tr}" /st {run_time.strftime("%H:%M")} /sd {run_time.strftime("%d/%m/%Y")} /f'
    else:
        tr = f"{shlex.quote(PYTHON_EXE)} {shlex.quote(target)} {args}".strip()
        cmd = f"echo {shlex.quote(tr)} | at {run_time.strftime('%H:%M %Y-%m-%d')}"
    
    return run_cmd(cmd)


def get_sunrise(date: datetime) -> Optional[datetime]:
    """Pobiera wschód słońca."""
    import requests
    try:
        resp = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": LAT, "longitude": LON, "daily": "sunrise",
            "timezone": "auto", "start_date": date.strftime("%Y-%m-%d"),
            "end_date": date.strftime("%Y-%m-%d"),
        }, timeout=10)
        sunrise_str = resp.json().get("daily", {}).get("sunrise", [None])[0]
        if sunrise_str:
            return datetime.fromisoformat(sunrise_str).replace(tzinfo=WARSAW_TZ)
    except Exception as e:
        logger.error(f"Sunrise fetch failed: {e}")
    return None


def get_rce_prices() -> list[dict[str, Any]]:
    """Pobiera ceny RCE."""
    from rce_data.fetch_rce_pln import fetch_all_from_now
    items, _ = fetch_all_from_now()
    return items


def get_sell_threshold() -> float:
    """Stały próg sprzedaży."""
    return SELL_THRESHOLD


def calculate_plan() -> dict[str, Optional[datetime]]:
    """
    Oblicza plan dnia na podstawie cen RCE.
    Uzywa okienek 2h (sumaryczna cena) zamiast pojedynczych godzin.
    Jesli API nie dziala, uzywa domyslnych godzin.
    """
    from rce_data.fetch_rce_pln import parse_rce_datetime
    from price_utils import find_cheapest_window, find_most_expensive_window, filter_prices_by_hour_range
    
    now = datetime.now(WARSAW_TZ)
    tomorrow = now + timedelta(days=1)
    threshold = get_sell_threshold()
    
    # Domyslne wartosci gdy API nie dziala
    plan = {
        "morning_sell": now.replace(hour=6, minute=0, second=0, microsecond=0),
        "midday_start": now.replace(hour=10, minute=0, second=0, microsecond=0),
        "evening_start": now.replace(hour=20, minute=0, second=0, microsecond=0),
        "next_sunrise": datetime(tomorrow.year, tomorrow.month, tomorrow.day, 4, 0, tzinfo=WARSAW_TZ),
    }
    
    # Proba pobrania wschodu slonca
    sunrise = get_sunrise(tomorrow)
    if sunrise:
        plan["next_sunrise"] = sunrise
    
    try:
        prices = get_rce_prices()
        if not prices:
            logger.warning("No RCE prices - using default times")
            return plan
        
        # Parse cen na dzis
        today_prices = []
        for p in prices:
            dt = parse_rce_datetime(p["dtime"])
            if dt.date() == now.date():
                price = float(p.get("rce_pln") or p.get("rce") or 0) / 1000
                today_prices.append((dt, price))
        
        today_prices.sort(key=lambda x: x[0])
        
        if not today_prices:
            logger.warning("No prices for today - using defaults")
            return plan
        
        # --- Morning sell: najdrozsze 2h okno w zakresie 6-12 ---
        morning = filter_prices_by_hour_range(today_prices, 6, 12)
        result = find_most_expensive_window(morning)
        if result:
            best_start, best_sum = result
            plan["morning_sell"] = best_start
            logger.info(f"Morning sell window: {best_start.strftime('%H:%M')}-{(best_start + timedelta(hours=2)).strftime('%H:%M')} (sum={best_sum:.4f})")
        elif morning:
            plan["morning_sell"] = morning[0][0]
            logger.info(f"Morning sell (single hour): {morning[0][0].strftime('%H:%M')}")
        
        # --- Midday start: najtansze 2h okno w zakresie 10-17 (start grzalki) ---
        midday = filter_prices_by_hour_range(today_prices, 10, 17)
        result = find_cheapest_window(midday)
        if result:
            best_start, best_sum = result
            # Tylko jesli srednia cena okienka < threshold
            if best_sum / 2 < threshold:
                plan["midday_start"] = best_start
                logger.info(f"Midday cheapest window: {best_start.strftime('%H:%M')}-{(best_start + timedelta(hours=2)).strftime('%H:%M')} (avg={best_sum/2:.4f})")
            else:
                logger.info(f"No cheap midday window (best avg={best_sum/2:.4f} >= {threshold})")
        
        # --- Evening sell: najdrozsze 2h okno w zakresie 17-24 ---
        evening = filter_prices_by_hour_range(today_prices, EVENING_PEAK_START_HOUR, EVENING_PEAK_END_HOUR)
        result = find_most_expensive_window(evening)
        if result:
            best_start, best_sum = result
            plan["evening_start"] = best_start
            logger.info(f"Evening sell window: {best_start.strftime('%H:%M')}-{(best_start + timedelta(hours=2)).strftime('%H:%M')} (sum={best_sum:.4f})")
        elif evening:
            plan["evening_start"] = evening[0][0]
            logger.info(f"Evening sell (single hour): {evening[0][0].strftime('%H:%M')}")
            
    except Exception as e:
        logger.error(f"Plan calculation failed: {e} - using defaults")
    
    return plan


def plan_day() -> None:
    """Glowna funkcja planowania."""
    cleanup_tasks()
    
    plan = calculate_plan()
    now = datetime.now(WARSAW_TZ)
    
    logger.info(f"Plan for {now.strftime('%Y-%m-%d')} (SUMMER_MODE={SUMMER_MODE}):")
    logger.info(json.dumps({k: v.strftime('%H:%M') if v else None for k, v in plan.items()}, indent=2))
    
    # 1. Morning sell - pojedyncze uruchomienie
    if plan["morning_sell"] > now:
        schedule_task(plan["morning_sell"], "EnergyMorningSell")
        logger.info(f"Scheduled morning sell: {plan['morning_sell'].strftime('%H:%M')}")
    
    # 2. Midday periodic - kontrola grzalki do wieczora
    if plan["midday_start"] > now:
        until_hour = plan["evening_start"].hour if plan["evening_start"] else EVENING_PEAK_START_HOUR
        schedule_task(plan["midday_start"], "EnergyMiddayPeriodic", args=f"--periodic --until {until_hour}")
        logger.info(f"Scheduled midday periodic: {plan['midday_start'].strftime('%H:%M')} until {until_hour}:00")
    
    # 3. Evening periodic - sprzedaz z kontrola SOC
    if plan["evening_start"] > now:
        schedule_task(plan["evening_start"], "EnergyEveningPeriodic", args="--periodic --until 24")
        logger.info(f"Scheduled evening periodic: {plan['evening_start'].strftime('%H:%M')}")
    
    # 4. Summer heater (jesli SUMMER_MODE wlaczony)
    if SUMMER_MODE:
        summer_time = now.replace(hour=6, minute=0, second=0, microsecond=0)
        if summer_time > now:
            logger.info("SUMMER_MODE enabled - scheduling summer_heater.py")
            schedule_task(summer_time, "SummerHeaterPlan", script=SUMMER_HEATER)
        else:
            # Jesli juz po 6:00, uruchom od razu
            logger.info("SUMMER_MODE enabled - running summer_heater.py now")
            result = subprocess.run([PYTHON_EXE, SUMMER_HEATER], capture_output=True, text=True)
            if result.stdout:
                for line in result.stdout.strip().split('\n'):
                    logger.info(f"[SummerHeater] {line}")
            if result.stderr:
                for line in result.stderr.strip().split('\n'):
                    logger.warning(f"[SummerHeater] {line}")
    
    # 5. Scheduler na jutro (zawsze 4:00 lub wschod slonca)
    schedule_task(plan["next_sunrise"], "EnergyDailyPlan", script=ENERGY_SCHEDULER)
    logger.info(f"Scheduled next day: {plan['next_sunrise'].strftime('%H:%M')}")


def main():
    parser = argparse.ArgumentParser(description="Energy Scheduler")
    parser.add_argument("--cleanup", action="store_true", help="Remove all scheduled tasks and exit")
    args = parser.parse_args()
    
    # Lock file - zapobiega równoległym uruchomieniom
    from file_lock import FileLock
    lock_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".scheduler.lock")
    lock = FileLock(lock_file_path)
    if not lock.acquire():
        # Inny proces schedulera już działa - wychodzimy cicho
        sys.exit(0)
    
    try:
        logger.info("=" * 50)
        logger.info("######### Energy Scheduler Start ##########")
        
        if args.cleanup:
            logger.info("Cleanup mode - removing all scheduled tasks")
            cleanup_tasks()
            logger.info("All tasks removed")
            return
        
        try:
            plan_day()
        except Exception as e:
            logger.error(f"Scheduler failed: {e}", exc_info=True)
            # Fallback - podstawowe godziny
            now = datetime.now(WARSAW_TZ)
            fallbacks = [
                (now.replace(hour=7, minute=0), "EnergyMorningSell", ""),
                (now.replace(hour=12, minute=0), "EnergyMiddayPeriodic", "--periodic --until 17"),
                (now.replace(hour=17, minute=0), "EnergyEveningPeriodic", "--periodic --until 24"),
            ]
            for time, name, fall_args in fallbacks:
                if time > now:
                    schedule_task(time, name, args=fall_args)
    finally:
        lock.release()


if __name__ == "__main__":
    main()
