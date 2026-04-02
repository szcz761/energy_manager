# Smart Home Energy Manager

Python automation for home energy decisions based on:
- Deye inverter/battery data (SOC, PV power)
- Polish RCE market prices
- Local weather forecast
- Smart Life/Tuya smart plug control (heater on/off)

The project was developed on Windows and tested on Raspberry Pi.

## What it does

- Reads current battery SOC and PV production from DeyeCloud.
- Reads current/future RCE prices from PSE API.
- Switches inverter work mode (for example `SELLING_FIRST` vs `ZERO_EXPORT_TO_CT`).
- Turns a smart plug (heater) on/off based on SOC/PV/price thresholds.
- Supports periodic scheduling.

## Requirements

- Python 3.10+
- Internet access for DeyeCloud, Open-Meteo, and PSE API
- Smart Life device configured for local TinyTuya control (optional, for plug control)

Install dependencies:

```bash
pip install -r requirements.txt
```

## Quick setup

### 1. Create a virtual environment (recommended)

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Linux / Raspberry Pi:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Deye credentials

Create local private config:

Windows (PowerShell):

```powershell
Copy-Item deye_client/config.local.example.py deye_client/config.local.py
```

Linux / Raspberry Pi:

```bash
cp deye_client/config.local.example.py deye_client/config.local.py
```

Fill `deye_client/config.local.py` with your real:
- `APP_ID`
- `APP_SECRET`
- `EMAIL`
- `PASSWORD`
- `REGION`
- `DEVICE_SN`

### 3. Configure Smart Life plug (optional, needed for heater control)

Create local private config:

Windows (PowerShell):

```powershell
Copy-Item smart_life/smart_plug_config.example.json smart_life/smart_plug_config.local.json
```

Linux / Raspberry Pi:

```bash
cp smart_life/smart_plug_config.example.json smart_life/smart_plug_config.local.json
```

Fill `smart_life/smart_plug_config.local.json` with your real:
- `device_id`
- `ip_address`
- `local_key`
- optional `protocol_version`
- optional `dps_index`

## Usage

Run one decision cycle:

```bash
python energy_manager.py
```

Run scheduler planning flow:

```bash
python energy_scheduler.py
```

Run periodic manager mode in a window:

```bash
python energy_manager.py --period 08:00 20:00
```

Deye diagnostics:

```bash
python deye_client/check_heater.py
python deye_client/check_heater.py --set-mode selling_first
python deye_client/debug_deye.py
```

Smart plug direct control:

```bash
python smart_life/heater_control.py status
python smart_life/heater_control.py on
python smart_life/heater_control.py off
```

## Scheduling notes

- Windows: scheduling uses `schtasks`.
- Linux/Raspberry Pi: scheduling uses the `at` command in current scripts.

If you run on Raspberry Pi, make sure `at` is installed and enabled if you want automatic scheduling.

## Repository hygiene

This repo intentionally ignores:
- local credentials (`config.local.py`, `smart_plug_config.local.json`)
- runtime snapshots and cache JSON files
- logs
- Python cache files

Only template config files are tracked.

## Safety notes

- Never commit real credentials.
- Do a dry run before enabling unattended scheduling.
- Validate threshold constants in `energy_manager.py` for your tariff and hardware.
