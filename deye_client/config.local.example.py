"""Local Deye Cloud credentials example.

Copy this file to `config.local.py` and fill in real values.
Do not commit `config.local.py`.
"""

CONFIG: dict[str, str] = {
    "APP_ID": "YOUR_APP_ID",  # from DeyeCloud developer portal (https://developer.deyecloud.com/applications) - "API Credentials" section
    "APP_SECRET": "YOUR_APP_SECRET",  # from DeyeCloud developer portal (https://developer.deyecloud.com/applications) - "API Credentials" section
    "EMAIL": "your_email@example.com",  # Email for your DeyeCloud account
    "PASSWORD": "your_deye_password",  # Password for your DeyeCloud account
    "REGION": "eu",  # "eu" for Europe, "us" for USA
    "DEVICE_SN": "YOUR_DEVICE_SN",  # Serial number of your Deye device (can be found in the DeyeCloud app, in the device details)
}
