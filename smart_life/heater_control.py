"""Smart Life/Tuya smart plug controller.

This script uses the TinyTuya library to talk directly to a Smart Life
compatible smart plug over the local network. Review the README for setup
instructions or run ``python heater_control.py --help`` for usage.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import tinytuya
import logging

# Configure logging
logger = logging.getLogger(__name__)


DEFAULT_CONFIG_PATH = Path(__file__).with_name("smart_plug_config.local.json")


@dataclass
class SmartPlugConfig:
    """Configuration needed to talk to the plug over the LAN."""

    device_id: str
    ip_address: str
    local_key: str
    protocol_version: float = 3.3
    dps_index: int = 1

    @classmethod
    def from_mapping(cls, data: Dict[str, Any]) -> "SmartPlugConfig":
        required = ("device_id", "ip_address", "local_key")
        missing = [key for key in required if not data.get(key)]
        if missing:
            raise ValueError(f"Missing config keys: {', '.join(missing)}")
        return cls(
            device_id=str(data["device_id"]),
            ip_address=str(data["ip_address"]),
            local_key=str(data["local_key"]),
            protocol_version=float(data.get("protocol_version", 3.3)),
            dps_index=int(data.get("dps_index", 1)),
        )

    @classmethod
    def from_file(cls, path: Path) -> "SmartPlugConfig":
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        config = cls.from_mapping(data)
        config._path = path  # Store path for potential updates
        return config

    def save(self) -> None:
        """Saves the current configuration back to the file it was loaded from."""
        path = getattr(self, "_path", None)
        if not path:
            return
        data = {
            "device_id": self.device_id,
            "ip_address": self.ip_address,
            "local_key": self.local_key,
            "protocol_version": self.protocol_version,
            "dps_index": self.dps_index,
        }
        with path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=4)


class SmartLifePlug:
    """Wrapper around a TinyTuya outlet for easier status and toggles."""

    def __init__(
        self,
        config: SmartPlugConfig,
        *,
        persist: bool = False,
        retry_limit: int = 5,
        retry_delay: int = 5,
    ) -> None:
        self.config = config
        self._retry_limit = retry_limit
        self._retry_delay = retry_delay
        self._persist = persist
        self._init_device()

    def _init_device(self) -> None:
        self._device = tinytuya.OutletDevice(
            dev_id=self.config.device_id,
            address=self.config.ip_address,
            local_key=self.config.local_key,
            version=self.config.protocol_version,
        )
        self._device.set_socketRetryLimit(self._retry_limit)
        self._device.set_socketRetryDelay(self._retry_delay)
        if self._persist:
            self._device.set_socketPersistent(True)

    def discover_ip(self) -> bool:
        """Tries to find the device on the network and update its IP."""
        logger.info(f"Attempting to discover device {self.config.device_id}...")
        devices = tinytuya.deviceScan()
        for ip, dev in devices.items():
            if dev.get("gwId") == self.config.device_id:
                logger.info(f"Found device at {ip}. Updating configuration.")
                self.config.ip_address = ip
                self.config.save()
                self._init_device()
                return True
        logger.warning("Device not found during scan.")
        return False

    def get_status_payload(self) -> Dict[str, Any]:
        try:
            payload = self._device.status()
        except Exception:
            payload = None

        if not payload or payload.get("Err"):
            # If failed, try to discover the IP once
            if self.discover_ip():
                payload = self._device.status()

        if not payload:
            raise RuntimeError("Brak odpowiedzi od urządzenia.")

        if isinstance(payload, dict) and payload.get("Err"):
            raise RuntimeError(
                f"TinyTuya Err={payload.get('Err')}, "
                f"Error={payload.get('Error')}, "
                f"Payload={payload.get('Payload')}"
            )

        if "dps" not in payload:
            raise RuntimeError(f"Brak DPS w odpowiedzi: {payload!r}")

        return payload

    def is_on(self) -> bool:
        payload = self.get_status_payload()
        return bool(payload["dps"].get(str(self.config.dps_index), False))

    def turn_on(self) -> Dict[str, Any]:
        return self._device.set_status(True, self.config.dps_index)

    def turn_off(self) -> Dict[str, Any]:
        return self._device.set_status(False, self.config.dps_index)

    def toggle(self) -> Dict[str, Any]:
        return self.turn_off() if self.is_on() else self.turn_on()


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("status", "on", "off", "toggle"),
        help="Command to run against the plug",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=("Path to JSON file with device_id, ip_address, local_key, " "protocol_version, dps_index"),
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Keep the TCP session open for rapid successive commands",
    )
    parser.add_argument(
        "--retry-limit",
        type=int,
        default=5,
        help="Number of socket retries before failing",
    )
    parser.add_argument(
        "--retry-delay",
        type=int,
        default=5,
        help="Seconds to wait between retries",
    )
    return parser.parse_args(argv)


def load_config(path: Path) -> SmartPlugConfig:
    if not path.exists():
        raise FileNotFoundError(
            f"Could not locate config file at {path}. "
            "Copy smart_plug_config.example.json to smart_plug_config.local.json and fill your values first."
        )
    return SmartPlugConfig.from_file(path)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    try:
        config = load_config(args.config)
    except Exception as exc:  # noqa: BLE001 - show helpful message to user
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    plug = SmartLifePlug(
        config,
        persist=args.persist,
        retry_limit=args.retry_limit,
        retry_delay=args.retry_delay,
    )

    try:
        if args.action == "status":
            state = plug.is_on()
            payload = plug.get_status_payload()
            print(json.dumps({"on": state, "payload": payload}, indent=2))
        elif args.action == "on":
            plug.turn_on()
            print("Plug switched ON.")
        elif args.action == "off":
            plug.turn_off()
            print("Plug switched OFF.")
        else:  # toggle
            new_payload = plug.toggle()
            print("Plug toggled.")
            if new_payload:
                print(json.dumps(new_payload, indent=2))
    except Exception as exc:  # noqa: BLE001 - allow TinyTuya errors to surface
        print(f"Device error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
