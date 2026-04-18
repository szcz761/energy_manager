import logging
from zoneinfo import ZoneInfo
import requests
from datetime import datetime

# Configure logging
logger = logging.getLogger(__name__)


def fetch_weather_forecast(lat: float, lon: float, tz: str = "Europe/Warsaw") -> dict:
    """Fetch weather forecast using open_meteo.py."""
    now = datetime.now(ZoneInfo(tz))

    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "cloud_cover,shortwave_radiation",
        "timezone": "auto",
        "start_date": now.strftime("%Y-%m-%d"),
        "end_date": now.strftime("%Y-%m-%d"),
    }

    try:
        resp = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Failed to fetch weather forecast: {e}")
        return {}


def how_sunny_day(weather_data: dict) -> float:
    """Check if it's sunny for the entire day (7 AM to 6 PM) and return average cloud cover."""
    if not weather_data or "hourly" not in weather_data:
        logger.warning("No weather data available for sunniness check.")
        return 100.0

    hourly = weather_data["hourly"]
    times = hourly["time"]
    clouds = hourly["cloud_cover"]

    relevant_clouds = []
    for t, cloud in zip(times, clouds):
        hour = int(t.split("T")[1].split(":")[0])
        if 7 <= hour <= 18:
            relevant_clouds.append(cloud)

    if not relevant_clouds:
        return 100.0

    avg_cloud = sum(relevant_clouds) / len(relevant_clouds)
    logger.info(f"Average cloud cover for the day (07-18): {avg_cloud:.1f}%")
    return avg_cloud
