import os
from dotenv import load_dotenv

load_dotenv()

# Target Search URLs (Updated with 2019-2027, 6-cyl, Front/Rear/Side damage filters + newest lot sort)
COPART_SEARCH_URL = (
    "https://www.copart.com/lotSearchResults?free=true&query=dodge%20challenger"
    "&qId=623c1d07-ca78-4193-b4ba-028e053de722-1793537611275&index=null"
    "&searchCriteria=%7B%22query%22:%5B%22*%22%5D,%22filter%22:%7B%22FETI%22:%5B%22lot_condition_code:CERT-D%22%5D,"
    "%22PRID%22:%5B%22damage_type_code:DAMAGECODE_FR%22,%22damage_type_code:DAMAGECODE_RR%22,%22damage_type_code:DAMAGECODE_SD%22%5D,"
    "%22ODM%22:%5B%22odometer_reading_received:%5B0%20TO%2076300%5D%22%5D,"
    "%22MAKE%22:%5B%22search_lot_make_desc:%5C%22DODGE%5C%22%22%5D,"
    "%22MODL%22:%5B%22lot_model_desc:%5C%22CHALLENGER%5C%22%22%5D,"
    "%22CYLN%22:%5B%22cylinders:%5C%226%5C%22%22%5D,"
    "%22YEAR%22:%5B%22lot_year:%5B2019%20TO%202027%5D%22%5D%7D,"
    "%22sort%22:%5B%22lot_number%20desc%22%5D,"
    "%22searchName%22:%22%22,%22watchListOnly%22:false,%22freeFormSearch%22:false,%22exclusions%22:%5B%5D%7D"
)

IAAI_SEARCH_URL = (
    "https://www.iaai.com/Search?url=Tg%2fLxBEbpfSDJmuUBF%2bXu3xGxjiM2wLOeSmr8pTVcxc%3d"
)

# API Keys & Credentials
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# Gemini Model Configuration (automatically falls back to newest available Flash model if 404)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

# Scraper Settings
HEADLESS = os.getenv("HEADLESS", "false").lower() in ("true", "1", "yes")
MAX_LISTINGS_PER_SOURCE = int(os.getenv("MAX_LISTINGS_PER_SOURCE", "10"))
MAX_IMAGES_PER_LISTING = int(os.getenv("MAX_IMAGES_PER_LISTING", "6"))
MAX_AGE_HOURS = int(os.getenv("MAX_AGE_HOURS", "24"))
SEEN_LOTS_FILE = "seen_lots.json"
PASSED_CARS_FILE = "passed_cars.json"
PASSED_CARS_MD_FILE = "PASSED_CARS.md"

# Realistic Browser Fingerprint Settings
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Upgrade-Insecure-Requests": "1",
}
