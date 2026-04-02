# DeyeCloud API Notes

This folder contains helper modules used by the project to authenticate with DeyeCloud, fetch inverter/station data, and set inverter work modes.

## Configuration

Tracked file:
- `config.py`: safe placeholders and optional loader for a local override.

Local private file (not tracked):
- `config.local.py`: real credentials.

Quick setup:
1. Copy `config.local.example.py` to `config.local.py`.
2. Fill in `APP_ID`, `APP_SECRET`, `EMAIL`, `PASSWORD`, `REGION`, and `DEVICE_SN`.

## Main modules

- `auth.py`: authentication and account info API wrapper.
- `data_retriever.py`: device/station data fetch + work mode update.
- `check_heater.py`: quick diagnostic script for SOC/PV and optional mode switch.
- `debug_deye.py`: extra debugging flow for account/station/device endpoints.

## Useful commands

```bash
python deye_client/check_heater.py
python deye_client/check_heater.py --set-mode selling_first
python deye_client/debug_deye.py
```

## Data centers

- EU: `https://eu1-developer.deyecloud.com/v1.0`
- US: `https://us1-developer.deyecloud.com/v1.0`

## Official references

- DeyeCloud developer portal: https://developer.deyecloud.com/app
- DeyeCloud API docs: https://developer.deyecloud.com/api
