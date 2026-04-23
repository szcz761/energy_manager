PRICE_POWER_I_BUY = 1.38  # current electricity buy price
TRESHOLD_PRICE_POWER_GAS = 0.39  #  calculated threshold price for buying electricity vs using gas for heating
UNDER_TRHESHOLD_FOR_LONGER_SELL = 0.2  # if it's very sunny, we can be more aggressive in selling to the grid, so we lower the threshold by this amount

SUNNY_CLOUD_THRESHOLD: int = 85  # % cloud cover
VERY_SUNNY_CLOUD_THRESHOLD: int = 35  # % cloud cover
LAT = 51.6397598763277
LON = 17.78994335885742
TIMEZONE = "Europe/Warsaw"

TRESHOLD_SOC_ON = 98
TRESHOLD_SOC_OFF = 90
TRESHOLD_PV_POWER = 500
