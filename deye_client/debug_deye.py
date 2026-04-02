import os
import sys

# allow running this script directly from the package folder
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from deye_client.auth import DeyeCloudAPI
from deye_client.data_retriever import DeyeCloudDataRetriever
from deye_client.config import CONFIG


def run_diagnostics():
    api = DeyeCloudAPI(region=CONFIG.get("REGION", "eu"))
    ok = api.obtain_token(
        app_id=CONFIG.get("APP_ID", ""),
        app_secret=CONFIG.get("APP_SECRET", ""),
        email=CONFIG.get("EMAIL", ""),
        password=CONFIG.get("PASSWORD", ""),
    )
    print("Token present:", bool(api.token))

    print("\n== account/info ==")
    try:
        info = api.get_account_info()
        print(info)
    except Exception as e:
        print("account/info error:", e)

    retriever = DeyeCloudDataRetriever(api)

    print("\n== device/list ==")
    try:
        devs = retriever.get_device_list()
        print(devs)
    except Exception as e:
        print("device/list error:", e)

    # If device list failed or returned auth error, try station/device using station list
    print("\n== fallback: station/device ==")
    try:
        stations = retriever.get_station_list()
        s_list = stations.get("stationList") if isinstance(stations, dict) else None
        if s_list and len(s_list) > 0:
            sid = s_list[0].get("id")
            print("Using station id for station/device:", sid)
            sdev = retriever.get_station_devices([sid])
            print(sdev)
        else:
            print("No stations available to query station/device")
    except Exception as e:
        print("station/device error:", e)

    print("\n== station/list ==")
    try:
        stations = retriever.get_station_list()
        print(stations)
    except Exception as e:
        print("station/list error:", e)

    # Try setting system work mode (several values)
    test_modes = ["SELLING_FIRST", "ZERO_EXPORT_TO_LOAD", "ZERO_EXPORT_TO_CT"]
    print("\n== set_system_work_mode tests ==")
    device_sn = None
    # Prefer device list from /device/list
    if isinstance(devs, dict):
        data = devs.get("data") or devs.get("deviceList") or []
        if isinstance(data, list) and data:
            first = data[0]
            device_sn = str(first.get("deviceSn") or first.get("sn") or "")

    # If not found, prefer station/device result
    if not device_sn:
        try:
            # station/device call was printed earlier as sdev in fallback section; reuse logic
            stations = retriever.get_station_list()
            s_list = stations.get("stationList") if isinstance(stations, dict) else None
            if s_list and len(s_list) > 0:
                sid = s_list[0].get("id")
                sdev = retriever.get_station_devices([sid])
                if isinstance(sdev, dict):
                    dev_items = sdev.get("deviceListItems") or sdev.get("deviceList") or sdev.get("data") or []
                    # prefer inverter
                    inv = None
                    for it in dev_items:
                        if it.get("deviceType") == "INVERTER":
                            inv = it
                            break
                    pick = inv or (dev_items[0] if dev_items else None)
                    if pick:
                        device_sn = str(pick.get("deviceSn") or pick.get("sn") or "")
        except Exception:
            pass

    print("Using deviceSn:", device_sn)
    if not device_sn:
        print("No device SN found; set_system_work_mode tests skipped")
    else:
        for m in test_modes:
            print(f"-> Testing set_system_work_mode {m}")
            try:
                r = retriever.set_system_work_mode(m, device_sn=device_sn)
                print(r)
            except Exception as e:
                print("error:", e)

    # Try battery mode control
    print("\n== battery/modeControl tests ==")
    # Do not test /order/battery/modeControl here: it's for battery charge-mode actions
    print("\nSkipping battery '/order/battery/modeControl' tests — use set_system_work_mode for system work modes.")


if __name__ == "__main__":
    run_diagnostics()
