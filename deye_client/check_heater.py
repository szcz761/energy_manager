"""Fetch current PV production and battery SOC, optionally changing work mode.

Usage:
- Status (PV + SOC):
    python deye_client/check_heater.py

- Set "no export to load" mode:
    python deye_client/check_heater.py --set-mode no_export_to_load

- Set "selling first" mode:
    python deye_client/check_heater.py --set-mode selling_first
"""

from __future__ import annotations

import argparse
import sys
import os
from typing import Any, Dict, List, Optional, Tuple

# Add project root to sys.path to allow running as script
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from deye_client.auth import DeyeCloudAPI
from deye_client.data_retriever import DeyeCloudDataRetriever
from deye_client.config import CONFIG

POSSIBLE_PV_KEYS: List[str] = ["PV Power", "PV_POWER", "pv_power", "pvPower", "ppv", "Ppv", "generationPower"]
POSSIBLE_SOC_KEYS: List[str] = ["SOC", "soc", "SoC", "Battery SOC", "batterySoc", "batterySOC"]

MODE_TO_API_VALUE: Dict[str, str] = {
    "no_export_to_load": "ZERO_EXPORT_TO_LOAD",
    "selling_first": "SELLING_FIRST",
}


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_values_from_latest(latest_response: Optional[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float]]:
    """Extract SOC and PV power from `/device/latest` response."""
    if not latest_response:
        return None, None

    records: Any = latest_response.get("data") or latest_response.get("deviceList") or []
    if not isinstance(records, list) or not records:
        return None, None

    first_record: Any = records[0]
    if not isinstance(first_record, dict):
        return None, None

    soc_value: Optional[float] = None
    pv_value: Optional[float] = None

    # Format 1: measurement points list
    data_list: Any = first_record.get("dataList") or first_record.get("data") or []
    if isinstance(data_list, list):
        for item in data_list:
            if not isinstance(item, dict):
                continue
            key: str = str(item.get("key") or item.get("name") or item.get("k") or "")
            value: Any = item.get("value") if "value" in item else item.get("val")

            if key in POSSIBLE_SOC_KEYS and soc_value is None:
                soc_value = _to_float(value)
            if key in POSSIBLE_PV_KEYS and pv_value is None:
                pv_value = _to_float(value)

    # Format 2: flat keys in the record
    if soc_value is None:
        for key in POSSIBLE_SOC_KEYS:
            if key in first_record:
                soc_value = _to_float(first_record.get(key))
                if soc_value is not None:
                    break

    if pv_value is None:
        for key in POSSIBLE_PV_KEYS:
            if key in first_record:
                pv_value = _to_float(first_record.get(key))
                if pv_value is not None:
                    break

    return soc_value, pv_value


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser()
    parser.add_argument(
        "--set-mode",
        choices=["no_export_to_load", "selling_first"],
        default=None,
        help="Optionally change inverter work mode",
    )
    args: argparse.Namespace = parser.parse_args()

    api: DeyeCloudAPI = DeyeCloudAPI(region=CONFIG.get("REGION", "eu"))
    ok: bool = api.obtain_token(
        app_id=CONFIG.get("APP_ID", ""),
        app_secret=CONFIG.get("APP_SECRET", ""),
        email=CONFIG.get("EMAIL", ""),
        password=CONFIG.get("PASSWORD", ""),
    )
    if not ok:
        print("Authentication failed")
        return

    retriever: DeyeCloudDataRetriever = DeyeCloudDataRetriever(api)

    devices_response: Optional[Dict[str, Any]] = retriever.get_device_list()
    device_list: List[Dict[str, Any]] = extract_device_list(devices_response)
    if not device_list:
        print("No devices found on this account")
        print(f"RAW: {devices_response}")
        return

    first_device: Dict[str, Any] = device_list[0]
    device_sn: str = str(first_device.get("deviceSn") or first_device.get("sn") or "")
    if not device_sn:
        print("Device serial number was not found")
        print(f"RAW device: {first_device}")
        return

    latest_response: Optional[Dict[str, Any]] = retriever.get_device_latest_data(device_sn)
    soc: Optional[float]
    pv_power: Optional[float]
    soc, pv_power = extract_values_from_latest(latest_response)

    print(f"Device SN: {device_sn}")
    print(f"SOC: {soc if soc is not None else 'N/A'} %")
    print(f"PV Power: {pv_power if pv_power is not None else 'N/A'} W")

    if args.set_mode is not None:
        mode_key: str = args.set_mode
        mode_value: str = MODE_TO_API_VALUE[mode_key]
        result: Optional[Dict[str, Any]] = retriever.set_system_work_mode(mode_value, device_sn=device_sn)
        print(f"Mode changed to: {mode_key} ({mode_value})")
        print(f"RAW result: {result}")


if __name__ == "__main__":
    main()
