from __future__ import annotations
import argparse
import logging
import os
import platform
import subprocess
import sys
import json
import shlex
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from typing import Optional, Any
from zoneinfo import ZoneInfo

# Configure logging
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

from energy_manager import TRESHOLD_PRICE_POWER_GAS, run_cmd
from rce_data.fetch_rce_pln import fetch_all_from_now, parse_rce_datetime

WARSAW_TZ = ZoneInfo("Europe/Warsaw")
PYTHON_EXE = sys.executable
ENERGY_MANAGER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "energy_manager.py")
ENERGY_SCHEDULER = os.path.abspath(__file__)


def get_price_forecast() -> list[dict[str, Any]]:
    """Fetch all available RCE price data from now into the future."""
    items, _ = fetch_all_from_now()
    return items


def calculate_day_plan() -> dict[str, Optional[datetime]]:
    """
    Calculate the 4 key moments for the day:
    1. morning_sell: 30 mins before highest morning peak (before 12:00)
    2. start_charge: First crossing of PRICE_THRESHOLD (price goes down)
    3. stop_charge: Second crossing of PRICE_THRESHOLD (price goes up)
    4. next_sunrise: Tomorrow's sunrise
    """
    now = datetime.now(ZoneInfo("Europe/Warsaw"))
    prices = get_price_forecast()
    print(f"Fetched {len(prices)} price entries for planning.")
    tomorrow = now + timedelta(days=1)
    sunrise_tomorrow, _ = get_sunrise_sunset(tomorrow)

    plan = {"morning_sell": None, "start_charge": None, "stop_charge": None, "next_sunrise": sunrise_tomorrow}

    if not prices:
        return plan

    # 1. Morning Peak
    morning_prices = []
    for item in prices:
        dtime = parse_rce_datetime(item["dtime"])
        if dtime.hour < 12 and dtime.hour != 0:
            price_kwh = float(item.get("rce_pln") or item.get("rce") or 0) / 1000.0
            morning_prices.append((dtime, price_kwh))

    if morning_prices:
        peak_time, _ = max(morning_prices, key=lambda x: x[1])
        plan["morning_sell"] = peak_time - timedelta(minutes=30)

    # 2 & 3. Threshold crossings
    found_start = False
    for item in prices:
        dtime = parse_rce_datetime(item["dtime"])
        if dtime <= now:
            continue

        price_kwh = float(item.get("rce_pln") or item.get("rce") or 0) / 1000.0
        if not found_start and price_kwh < TRESHOLD_PRICE_POWER_GAS and dtime.hour > 8:
            plan["start_charge"] = dtime
            found_start = True
        elif found_start and price_kwh >= TRESHOLD_PRICE_POWER_GAS and dtime.hour > 14:
            plan["stop_charge"] = dtime
            break

    return plan


def get_sunrise_sunset(date: datetime) -> tuple[Optional[datetime], Optional[datetime]]:
    """Fetch sunrise and sunset times for a specific date using Open-Meteo."""
    # LAT and LON are defined in meteo/open_meteo.py but we can use them here if we import or re-define.
    # Let's import from meteo.open_meteo
    from meteo.open_meteo import LAT, LON

    params = {
        "latitude": LAT,
        "longitude": LON,
        "daily": "sunrise,sunset",
        "timezone": "auto",
        "start_date": date.strftime("%Y-%m-%d"),
        "end_date": date.strftime("%Y-%m-%d"),
    }
    try:
        import requests

        resp = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        daily = data.get("daily", {})

        sunrise_str = daily.get("sunrise", [None])[0]
        sunset_str = daily.get("sunset", [None])[0]

        sunrise = datetime.fromisoformat(sunrise_str).replace(tzinfo=ZoneInfo("Europe/Warsaw")) if sunrise_str else None
        sunset = datetime.fromisoformat(sunset_str).replace(tzinfo=ZoneInfo("Europe/Warsaw")) if sunset_str else None

        return sunrise, sunset
    except Exception as e:
        logger.error(f"Failed to fetch sunrise/sunset: {e}")
        return None, None


def schedule_manager(time: datetime, task_name: str, extra_args: str = "", script_path: Optional[str] = None) -> bool:
    target_script = script_path if script_path else ENERGY_MANAGER
    st = time.strftime("%H:%M")
    sd = time.strftime("%d/%m/%Y")

    if platform.system() == "Windows":
        tr = f'"{PYTHON_EXE}" "{target_script}" {extra_args}'.strip()
        cmd = f'schtasks /create /sc once /tn "{task_name}" /tr "{tr}" /st {st} /sd {sd} /f'
    else:
        # Use shlex for robust Linux scheduling
        # target_script should already be absolute path
        # extra_args might contain multiple arguments, so we split and quote if needed,
        # but for now we assume they are already formatted or we quote the whole command
        # Better: if extra_args exists, we can split it.
        tr = f"{shlex.quote(PYTHON_EXE)} {shlex.quote(target_script)} {extra_args}".strip()
        cmd = f"echo {shlex.quote(tr)} | at {time.strftime('%H:%M %Y-%m-%d')}"
    return run_cmd(cmd)


def cleanup_tasks() -> None:
    """Remove all scheduled energy tasks before creating new ones."""
    tasks = ["EnergyMorningSell", "EnergyStartCharge", "EnergyStopCharge", "EnergyDailyPlan"]
    if platform.system() == "Windows":
        for task in tasks:
            # /delete /tn "task" /f  - /f forces deletion without confirmation
            # We ignore errors if the task doesn't exist
            cmd = f'schtasks /delete /tn "{task}" /f'
            subprocess.run(cmd, shell=True, capture_output=True)
    else:
        # On Linux, we'd need to find jobs in 'at' queue.
        # This is trickier as 'at' doesn't easily support names.
        # However, we can try to find them by the script names in the command.
        try:
            atq_output = subprocess.check_output(["atq"], text=True)
            for line in atq_output.splitlines():
                job_id = line.split()[0]
                job_content = subprocess.check_output(["at", "-c", job_id], text=True)
                if "energy_manager.py" in job_content or "energy_scheduler.py" in job_content:
                    subprocess.run(["atrm", job_id])
        except Exception as e:
            logger.warning(f"Failed to cleanup 'at' jobs: {e}")


def plan_day() -> None:
    cleanup_tasks()
    plan = calculate_day_plan()
    now_dt = datetime.now(WARSAW_TZ)
    now = now_dt.isoformat()
    if not plan:
        logger.error("Scheduler: No plan received.")
        return
    else:
        logger.info(
            f"Scheduler: Plan for the day ({now_dt.strftime('%Y-%m-%d')}): {json.dumps({k: v.strftime('%H:%M') if v else None for k, v in plan.items()}, indent=2)}"
        )

    if plan["morning_sell"] and plan["morning_sell"] > now_dt:
        schedule_manager(plan["morning_sell"], "EnergyMorningSell")
    else:
        logger.info(
            f"Scheduler: No suitable morning_sell time found or it's already passed. for plan['morning_sell']: {plan['morning_sell'].strftime('%H:%M') if plan['morning_sell'] else None}"
        )

    if plan["start_charge"] and plan["start_charge"] > now_dt:
        start_str = plan["start_charge"].strftime("%H:%M")
        end_str = plan["stop_charge"].strftime("%H:%M") if plan["stop_charge"] else "20:00"
        schedule_manager(plan["start_charge"], "EnergyStartCharge", f"--period {start_str} {end_str}")
    else:
        logger.info(
            f"Scheduler: No suitable start_charge time found or it's already passed. for plan['start_charge']: {plan['start_charge'].strftime('%H:%M') if plan['start_charge'] else None}"
        )

    if plan["stop_charge"] and plan["stop_charge"] > now_dt:
        schedule_manager(plan["stop_charge"], "EnergyStopCharge")
    else:
        logger.info(
            f"Scheduler: No suitable stop_charge time found or it's already passed. for plan['stop_charge']: {plan['stop_charge'].strftime('%H:%M') if plan['stop_charge'] else None}"
        )

    if not plan["next_sunrise"]:
        plan["next_sunrise"] = now_dt + timedelta(days=1, hours=5 - now_dt.hour)
        logger.info(f"Scheduler: No next_sunrise time found for tomorrow.")

    if plan["next_sunrise"] > now_dt:
        schedule_manager(plan["next_sunrise"], "EnergyDailyPlan", script_path=ENERGY_SCHEDULER)
    else:
        logger.info(
            f"Scheduler: No suitable next_sunrise time found or it's already passed. for plan['next_sunrise']: {plan['next_sunrise'].strftime('%H:%M') if plan['next_sunrise'] else None}"
        )


def main() -> None:
    logger.info(f"######### Starting Energy Scheduler ##########")
    plan_day()


if __name__ == "__main__":
    main()
