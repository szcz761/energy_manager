import logging
import os
import sys
from zoneinfo import ZoneInfo

import requests
from datetime import datetime, timedelta, timezone

# --- Constants / Variables ---
PROJECT_ROOT: str = os.path.dirname(os.path.abspath(__file__))
SUNNY_CLOUD_THRESHOLD: int = 70  # % cloud cover
SUNNY_RADIATION_THRESHOLD: int = 200  # W/m² (optional extra check)
PRICE_DROP_PERCENTAGE: float = 0.7  # 70% drop from morning peak towards daily min
MIN_SELL_PRICE: float = 0.39  # PLN/kWh - Minimum price to sell energy
MAX_STOP_TIME: str = "12:00"  # Latest time to stop selling
MORNING_PEAK_RANGE: tuple[int, int] = (5, 10)  # Hours to look for morning peak (5 AM to 10 AM)
WARSAW_TZ: ZoneInfo = ZoneInfo("Europe/Warsaw")

# Configure logging
logger = logging.getLogger(__name__)

# Home location
LAT = 51.6397598763277
LON = 17.78994335885742


def cload_in_home_open():
    now = datetime.now(timezone.utc)
    tomorrow = now + timedelta(hours=24)

    params = {
        "latitude": LAT,
        "longitude": LON,
        "hourly": "cloud_cover,shortwave_radiation",
        "start_hour": now.strftime("%Y-%m-%dT%H:00"),
        "end_hour": tomorrow.strftime("%Y-%m-%dT%H:00"),
        "timezone": "auto",
    }

    resp = requests.get("https://api.open-meteo.com/v1/forecast", params=params)
    data = resp.json()

    times = data["hourly"]["time"]
    clouds = data["hourly"]["cloud_cover"]
    radiation = data["hourly"]["shortwave_radiation"]

    for t, c, r in zip(times, clouds, radiation):
        print(t, "cloud cover:", c, "%", "radiation:", r, "W/m2")


def fetch_weather_forecast() -> dict:
    """Fetch weather forecast using open_meteo.py (mocking/adapting the logic)."""
    # The existing open_meteo.py just prints. We need to adapt it or call it.
    # For now, let's implement a minimal version that returns data for today.

    now = datetime.now(WARSAW_TZ)

    params = {
        "latitude": LAT,
        "longitude": LON,
        "hourly": "cloud_cover,shortwave_radiation",
        "timezone": "auto",
        "start_date": now.strftime("%Y-%m-%d"),
        "end_date": now.strftime("%Y-%m-%d"),
    }
    try:
        resp = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=10)
        # logger.error(f"response {resp.json()}")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Failed to fetch weather: {e}")
        return {}


def is_sunny_day(weather_data: dict) -> bool:
    """Check if it's sunny for the entire day (7 AM to 6 PM)."""
    if not weather_data or "hourly" not in weather_data:
        logger.warning("No weather data available for sunniness check.")
        return False

    hourly = weather_data["hourly"]
    times = hourly["time"]
    clouds = hourly["cloud_cover"]

    relevant_clouds = []
    for t_str, cloud in zip(times, clouds):
        dt = datetime.fromisoformat(t_str)
        if 7 <= dt.hour <= 18:
            relevant_clouds.append(cloud)

    if not relevant_clouds:
        return False

    avg_cloud = sum(relevant_clouds) / len(relevant_clouds)

    is_sunny = avg_cloud < SUNNY_CLOUD_THRESHOLD
    if not is_sunny:
        logger.info(
            f"Not sunny enough for the whole day (Avg: {avg_cloud:.1f}% >= Threshold: {SUNNY_CLOUD_THRESHOLD}%)"
        )
    else:
        logger.info(f"Average full-day (07-18) cloud cover for day {times[0][:10]}: {avg_cloud:.1f}% - is sunny day")

    return is_sunny


# ############alternative service############
# from pyowm import OWM


# def cload_in_home_owm():
#     API_KEY = "TWOJ_KLUCZ"
#     owm = OWM(API_KEY)
#     mgr = owm.weather_manager()

#     one_call = mgr.one_call(lat=LAT, lon=LON, units="metric")
#     for hour in one_call.forecast_hourly[:24]:
#         ts = hour.reference_time("iso")
#         clouds = hour.clouds  # cloud cover percentage
#         print(ts, "cloud cover:", clouds, "%")
