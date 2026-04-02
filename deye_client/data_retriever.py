import requests
from datetime import datetime, timedelta
import json

from deye_client.config import CONFIG


class DeyeCloudDataRetriever:
    """
    Helper class for reading different data types from DeyeCloud API.
    """

    def __init__(self, api_instance):
        """
        Initialize with an authenticated API instance.

        Args:
            api_instance: DeyeCloudAPI instance with an active token.
        """
        self.api = api_instance

    def get_device_list(self, page=1, size=20):
        """Fetch list of devices."""
        if not self.api.token:
            print("Authenticate first before calling device endpoints.")
            return None

        url = f"{self.api.baseurl}/device/list?appId={self.api.app_id}"
        data = {"page": page, "size": size}

        response = requests.post(url, headers=self.api.headers, json=data)
        if response.status_code == 200:
            return response.json()
        else:
            # Mask Authorization header for logs
            auth = self.api.headers.get("Authorization", "")
            masked = auth
            if isinstance(masked, str) and len(masked) > 12:
                masked = masked[:6] + "..." + masked[-4:]
            print(f"Error fetching device list: {response.status_code} - {response.text}")
            print(f"Request URL: {url}")
            print(f"Request body: {data}")
            print(f"Request Authorization header (masked): {masked}")
            return response.json()

    def get_station_list(self, page=1, size=10):
        """Fetch list of stations."""
        url = f"{self.api.baseurl}/station/list?appId={self.api.app_id}"
        data = {"page": page, "size": size}

        response = requests.post(url, headers=self.api.headers, json=data)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching station list: {response.status_code}")
            return None

    def get_device_latest_data(self, device_sns):
        """
        Fetch latest data for one or more devices.

        Args:
            device_sns: list of device serial numbers (max 10).
        """
        url = f"{self.api.baseurl}/device/latest?appId={self.api.app_id}"

        if isinstance(device_sns, str):
            device_sns = [device_sns]

        data = {"deviceList": device_sns}

        response = requests.post(url, headers=self.api.headers, json=data)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching latest device data: {response.status_code}")
            return None

    def get_device_history(self, device_sn, granularity, start_date, end_date=None, measure_points=None):
        """
        Fetch historical data for a device.
        """
        url = f"{self.api.baseurl}/device/history?appId={self.api.app_id}"

        data = {"deviceSn": device_sn, "granularity": granularity, "startAt": start_date}

        if end_date:
            data["endAt"] = end_date

        if measure_points:
            data["measurePoints"] = measure_points

        response = requests.post(url, headers=self.api.headers, json=data)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching historical device data: {response.status_code}")
            print(f"Response: {response.text}")
            return None

    def get_station_latest_data(self, station_id):
        """Fetch latest station data."""
        url = f"{self.api.baseurl}/station/latest?appId={self.api.app_id}"
        data = {"stationId": station_id}

        response = requests.post(url, headers=self.api.headers, json=data)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching station data: {response.status_code}")
            return None

    def get_station_history(self, station_id, granularity, start_date, end_date=None):
        """
        Fetch historical station data.
        """
        url = f"{self.api.baseurl}/station/history?appId={self.api.app_id}"

        data = {"stationId": station_id, "granularity": granularity, "startAt": start_date}

        if end_date:
            data["endAt"] = end_date

        response = requests.post(url, headers=self.api.headers, json=data)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching station history: {response.status_code}")
            return None

    def get_device_measure_points(self, device_sn):
        """Fetch available measurement points for a device."""
        url = f"{self.api.baseurl}/device/measurePoints?appId={self.api.app_id}"
        data = {"deviceSn": device_sn}

        response = requests.post(url, headers=self.api.headers, json=data)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching measurement points: {response.status_code}")
            return None

    def get_device_alerts(self, device_sn, start_timestamp=None, end_timestamp=None, page=1, size=20):
        """
        Fetch device alerts.
        """
        url = f"{self.api.baseurl}/device/alertList?appId={self.api.app_id}"

        data = {"deviceSn": device_sn, "page": page, "size": size}

        if start_timestamp:
            data["startAt"] = start_timestamp
        if end_timestamp:
            data["endAt"] = end_timestamp

        response = requests.post(url, headers=self.api.headers, json=data)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching alerts: {response.status_code}")
            return None

    def get_station_devices(self, station_ids, page=1, size=200):
        """
        Fetch devices for a list of station IDs using /station/device.

        Args:
            station_ids: list of station IDs (int).
            page: page number.
            size: page size (max 200).
        Returns:
            Response JSON or None.
        """
        if not self.api.token:
            print("Authenticate first before calling station endpoints.")
            return None

        url = f"{self.api.baseurl}/station/device?appId={self.api.app_id}"
        data = {"stationIds": station_ids, "page": page, "size": size}

        response = requests.post(url, headers=self.api.headers, json=data)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching station devices: {response.status_code} - {response.text}")
            return response.json()

    def set_system_work_mode(self, mode_value, device_sn=None):
        """
        Set inverter system work mode.

        mode_value: API values like "SELLING_FIRST", "ZERO_EXPORT_TO_LOAD", "ZERO_EXPORT_TO_CT".
        device_sn: optional device serial number. If omitted, CONFIG["DEVICE_SN"] is used.
        """
        url = f"{self.api.baseurl}/order/sys/workMode/update?appId={self.api.app_id}"

        # Normalize some common variants (NO_EXPORT -> ZERO_EXPORT)
        normalized_mode = mode_value
        if isinstance(mode_value, str) and mode_value.startswith("NO_EXPORT"):
            normalized_mode = mode_value.replace("NO_EXPORT", "ZERO_EXPORT")

        payload_variants = [{"deviceSn": device_sn or CONFIG.get("DEVICE_SN"), "workMode": normalized_mode}]

        last_response_json = None

        for payload in payload_variants:
            try:
                response = requests.post(url, headers=self.api.headers, json=payload)
            except Exception as e:
                print(f"Request error: {e}")
                continue

            if response.status_code != 200:
                try:
                    last_response_json = response.json()
                except Exception:
                    last_response_json = {"status_code": response.status_code, "text": response.text}
                print(f"Non-200 response: {last_response_json}")
                continue

            try:
                response_json = response.json()
            except Exception:
                print(f"Cannot parse API response: {response.text}")
                last_response_json = {"text": response.text}
                continue

            last_response_json = response_json
            if response_json.get("success") is True:
                return response_json

        return last_response_json
