# === Lokalizacja ===
LAT = 51.6397598763277
LON = 17.78994335885742
TIMEZONE = "Europe/Warsaw"

# === Ceny energii ===
PRICE_POWER_I_BUY = 1.38  # cena kupna prądu PLN/kWh
SELL_THRESHOLD = 0.39  # próg opłacalności sprzedaży (= próg grzałki vs gaz)

# === Progi pogodowe (% zachmurzenia) - tylko dla limitu SOC wieczorem ===
VERY_SUNNY_CLOUD_THRESHOLD = 35  # poniżej = jutro słonecznie
SUNNY_CLOUD_THRESHOLD = 85  # powyżej = jutro pochmurno

# === Bateria / grzałka ===
TRESHOLD_SOC_ON = 98  # włącz grzałkę gdy SOC >=
TRESHOLD_SOC_OFF = 90  # wyłącz grzałkę gdy SOC <=
TRESHOLD_PV_POWER = 500  # min moc PV do włączenia grzałki

# === Wieczorna sprzedaż - limity SOC w zależności od pogody jutro ===
EVENING_PEAK_START_HOUR = 17
EVENING_PEAK_END_HOUR = 24
EVENING_SELL_SOC_SUNNY = 30  # jutro słonecznie - sprzedaj więcej
EVENING_SELL_SOC_DEFAULT = 50  # jutro umiarkowanie / brak danych
EVENING_SELL_SOC_CLOUDY = 70  # jutro pochmurno - zachowaj więcej

# === Tryb letni ===
# Gdy True: scheduler uruchamia summer_heater.py (grzanie wody w minimum cenowym)
# Pozwala wylaczyc piec gazowy latem
SUMMER_MODE = True

# === Poranna sprzedaz ===
# Gdy False: pomija poranna sprzedaz i obniza wieczorny limit SOC do 35%
# Przydatne latem gdy bateria nie zdazy sie naladowac do wieczora
MORNING_SELL_ENABLED = False

# === Retry ===
API_RETRY_ATTEMPTS = 3
API_RETRY_DELAY_SECONDS = 5

# === Interwał sprawdzania ===
MINUTES_PER_SOC_PERCENT = 2  # 1% SOC = 2 minuty
MIN_CHECK_INTERVAL_MINUTES = 4
