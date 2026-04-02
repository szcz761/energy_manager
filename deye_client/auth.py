import requests
import hashlib


class DeyeCloudAPI:
    def __init__(self, region="eu"):
        # Select data center.
        if region == "eu":
            self.baseurl = "https://eu1-developer.deyecloud.com/v1.0"
        elif region == "us":
            self.baseurl = "https://us1-developer.deyecloud.com/v1.0"

        self.token = None
        self.app_id = None
        self.headers = {"Content-Type": "application/json"}

    def obtain_token(self, app_id, app_secret, email, password, company_id="0"):
        """
        Obtain authentication token.
        """
        self.app_id = app_id
        # Hash password using SHA256.
        sha256_hash = hashlib.sha256()
        sha256_hash.update(password.encode("utf-8"))
        password_hash = sha256_hash.hexdigest()

        url = f"{self.baseurl}/account/token?appId={self.app_id}"

        data = {"appSecret": app_secret, "email": email, "companyId": company_id, "password": password_hash}

        try:
            response = requests.post(url, headers=self.headers, json=data)
            response.raise_for_status()

            result = response.json()

            # Try several common places for token
            token = None
            token = result.get("accessToken") or result.get("access_token") or token
            if not token and isinstance(result.get("data"), dict):
                token = result.get("data").get("accessToken") or result.get("data").get("access_token") or token
                token = result.get("data").get("token") or token

            # Some API variants return token under 'data'->'accessToken'
            self.token = token

            if self.token:
                # Update headers with bearer token.
                self.headers["Authorization"] = f"Bearer {self.token}"
                return True
            else:
                print("Error: token was not returned by API")
                print(result)
                return False

        except requests.exceptions.RequestException as e:
            print(f"Request error: {e}")
            return False

    def get_account_info(self):
        """Get account information."""
        if not self.token:
            print("Authenticate first before calling account endpoints.")
            return None

        url = f"{self.baseurl}/account/info"
        response = requests.post(url, headers=self.headers, json={})

        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error {response.status_code}: {response.text}")
            return None


if __name__ == "__main__":
    # Quick module test (set your real values before running).
    APP_ID = "your_app_id_here"
    APP_SECRET = "your_app_secret_here"
    EMAIL = "your_email@example.com"
    PASSWORD = "your_password"

    api = DeyeCloudAPI(region="eu")
    if api.obtain_token(APP_ID, APP_SECRET, EMAIL, PASSWORD):
        print(f"Token: {api.token[:50]}...")
        info = api.get_account_info()
        print(info)
