# Energy Manager - Logic Documentation

## Overview

System manages PV installation with battery storage. Goals:
1. **Sell energy** when RCE price is high (morning & evening peaks)
2. **Heat water** when price is low and battery full (midday)
3. **Control evening SOC** - don't drain below limit based on tomorrow's weather

## Architecture

```
Scheduler (daily at sunrise / 4:00 fallback)
    |
    +---> Morning Sell (single run) --> 1h before morning peak (fallback 6:00)
    |
    +---> Midday Periodic -----------> when price < threshold (fallback 10:00)
    |                                  heater control, runs until evening
    |
    +---> Evening Periodic ----------> 1h before evening peak (fallback 20:00)
    |                                  sell with SOC monitoring until 24:00
    |
    +---> Summer Heater (if SUMMER_MODE) --> plans ON/OFF around price minimum
```

## Files

| File | Purpose |
|------|---------|
| `CONFIG.py` | All configuration constants |
| `energy_scheduler.py` | Plans daily tasks at sunrise |
| `energy_manager.py` | Makes decisions: sell/heater control |
| `summer_heater.py` | Summer mode: heat water at lowest price |
| `meteo/open_meteo.py` | Weather API (cloud cover) |
| `rce_data/fetch_rce_pln.py` | RCE price API |
| `deye_client/` | Deye inverter API |
| `smart_life/` | Smart plug API (heater) |

---

## Scheduler (`energy_scheduler.py`)

**Runs:** Daily at sunrise (or 4:00 fallback)

**Plans based on RCE prices:**

| Task | When | Args | Fallback |
|------|------|------|----------|
| `EnergyMorningSell` | 1h before morning peak (6-12) | (none) | 6:00 |
| `EnergyMiddayPeriodic` | First hour when price < 0.39 | `--periodic --until {evening}` | 10:00 |
| `EnergyEveningPeriodic` | 1h before evening peak (17-24) | `--periodic --until 24` | 20:00 |
| `SummerHeaterPlan` | 6:00 (if SUMMER_MODE) | (none) | - |
| `EnergyDailyPlan` | Tomorrow sunrise | (scheduler) | 4:00 |

---

## Manager (`energy_manager.py`)

**Auto-detects mode based on time and price:**

```
EVENING (17-24):
    if price >= 0.39 AND SOC > limit:
        SELL
    else:
        STOP (don't drain below limit)

DAY:
    if price < 0.39:
        DON'T SELL
        if SOC >= 98% AND PV > 500W:
            HEATER ON
    else:
        SELL
```

### Run modes

```bash
python energy_manager.py              # Single run
python energy_manager.py --periodic --until 17   # Periodic until 17:00
python energy_manager.py --dry-run    # Show state only
```

---

## Summer Heater (`summer_heater.py`)

**Separate script for summer water heating.**

When `SUMMER_MODE = True` in CONFIG:
- Scheduler runs `summer_heater.py` at 6:00
- It finds lowest price hour (8:00-16:00)
- Schedules heater ON 1h before, OFF 1h after
- **Does not check SOC** - just uses cheapest electricity

```bash
python summer_heater.py          # Plan for today
python summer_heater.py --on     # Turn heater ON now
python summer_heater.py --off    # Turn heater OFF now
```

**Use case:** Turn off gas boiler in summer, heat water electrically at lowest price.

---

## Thresholds & Limits

### Sell Threshold (constant)
```
SELL_THRESHOLD = 0.39 PLN/kWh
```
- Price >= threshold: SELL
- Price < threshold: DON'T SELL

### Evening SOC Limit (depends on tomorrow's weather)

| Tomorrow weather | Cloud cover | SOC limit |
|------------------|-------------|-----------|
| Sunny | < 35% | 30% |
| Moderate | 35-85% | 50% |
| Cloudy | > 85% | 70% |
| API failed | - | 50% |

### Heater Control

**Turn ON when:**
- SOC >= 98%
- AND PV > 500W
- AND price < 0.39

**Turn OFF when:**
- SOC <= 90%
- OR PV < 500W

---

## Fallbacks (when APIs fail)

| Component | API | Fallback |
|-----------|-----|----------|
| Scheduler | RCE prices | 6:00, 10:00, 20:00 |
| Scheduler | Sunrise | 4:00 |
| Manager | Deye (SOC) | **No action** (safety) |
| Manager | RCE price | 0.39 (threshold) |
| Manager | Weather | 50% cloud = 50% SOC limit |
| Summer Heater | RCE prices | 12:00 as minimum |

---

## Configuration (`CONFIG.py`)

```python
# Location
LAT, LON = 51.64, 17.79
TIMEZONE = "Europe/Warsaw"

# Prices
SELL_THRESHOLD = 0.39  # PLN/kWh

# Weather thresholds (for evening SOC limit)
VERY_SUNNY_CLOUD_THRESHOLD = 35
SUNNY_CLOUD_THRESHOLD = 85

# Battery / heater
TRESHOLD_SOC_ON = 98
TRESHOLD_SOC_OFF = 90
TRESHOLD_PV_POWER = 500

# Evening sell
EVENING_PEAK_START_HOUR = 17
EVENING_PEAK_END_HOUR = 24
EVENING_SELL_SOC_SUNNY = 30
EVENING_SELL_SOC_DEFAULT = 50
EVENING_SELL_SOC_CLOUDY = 70

# Summer mode
SUMMER_MODE = False  # Set True for summer

# Timing
MINUTES_PER_SOC_PERCENT = 2
MIN_CHECK_INTERVAL_MINUTES = 4
API_RETRY_ATTEMPTS = 3
API_RETRY_DELAY_SECONDS = 5
```

---

## Example Day

```
04:00  Scheduler runs (sunrise API failed)
       RCE prices: peak 8:00, low 11-14, peak 20:00
       Plans: 6:00, 11:00, 19:00

06:00  Morning Sell (single)
       Price 0.55 >= 0.39 -> SELL
       Done

11:00  Midday Periodic starts
       Price 0.10 < 0.39 -> DON'T SELL
       SOC=60% < 98% -> heater OFF
       Next check in (98-60)*2 = 76 min

12:16  Price 0.05, SOC=85% -> heater OFF, next in 26 min

12:42  Price 0.08, SOC=98%, PV=2000W -> HEATER ON

...continues until 19:00...

19:00  Evening Periodic starts
       Tomorrow cloud: 45% -> SOC limit 50%
       SOC=95%, price 0.65 -> SELL
       Next in (95-50)*2 = 90 min

20:30  SOC=55%, price 0.70 -> SELL

20:45  SOC=50% <= limit -> STOP
       Periodic ends, inverter set to ZERO_EXPORT
```

---

## Summer Mode Example

```
CONFIG: SUMMER_MODE = True

04:00  Scheduler runs
       Plans normal tasks + SummerHeaterPlan at 6:00

06:00  summer_heater.py runs
       Finds minimum at 12:00 @ 0.02 PLN/kWh
       Schedules: ON at 11:00, OFF at 13:00

11:00  Heater ON (regardless of SOC/PV)

13:00  Heater OFF

       Water heated using cheapest electricity!
```

---

## Inverter Modes

| Mode | API value | Description |
|------|-----------|-------------|
| Sell | `SELLING_FIRST` | Export to grid |
| Zero export | `ZERO_EXPORT_TO_CT` | Self-consumption only |
