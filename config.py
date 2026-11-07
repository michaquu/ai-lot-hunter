import json
import logging
import os
from pathlib import Path
from urllib.parse import quote
import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

SEARCH_CONFIG_FILE = "search_config.json"
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "ai-lot-hunter").strip() or "ai-lot-hunter"
FIREBASE_API_KEY = (
    os.getenv("FIREBASE_API_KEY", "").strip()
    or os.getenv("VITE_FIREBASE_API_KEY", "").strip()
    or os.getenv("FIREBASE_KEY", "").strip()
)
FIREBASE_DATABASE_URL = (
    os.getenv("FIREBASE_DATABASE_URL", "").strip()
    or os.getenv("VITE_FIREBASE_DATABASE_URL", "").strip()
)
FIREBASE_USER_ID = os.getenv("FIREBASE_USER_ID", "").strip()


def get_rtdb_urls() -> list:
    if FIREBASE_DATABASE_URL:
        return [FIREBASE_DATABASE_URL.rstrip("/")]
    return [
        f"https://{FIREBASE_PROJECT_ID}-default-rtdb.europe-west1.firebasedatabase.app",
        f"https://{FIREBASE_PROJECT_ID}-default-rtdb.firebaseio.com",
    ]


def build_copart_url_from_filters(cfg: dict) -> str:
    """Dynamically construct a Copart searchCriteria URL from structured filter settings."""
    make = str(cfg.get("make", "DODGE")).upper().strip()
    model = str(cfg.get("model", "CHALLENGER")).upper().strip()
    year_from = int(cfg.get("year_from", 2019))
    year_to = int(cfg.get("year_to", 2027))
    max_odo = int(cfg.get("max_odometer", 76300))
    cylinders = str(cfg.get("cylinders", "6")).strip()
    run_and_drive = bool(cfg.get("run_and_drive_only", True))

    filters = {
        "PRID": [
            "damage_type_code:DAMAGECODE_FR",
            "damage_type_code:DAMAGECODE_RR",
            "damage_type_code:DAMAGECODE_SD",
            "damage_type_code:DAMAGECODE_MN",
        ],
        "ODM": [f"odometer_reading_received:[0 TO {max_odo}]"],
        "MAKE": [f'search_lot_make_desc:"{make}"'],
        "MODL": [f'lot_model_desc:"{model}"'],
        "YEAR": [f"lot_year:[{year_from} TO {year_to}]"],
    }
    if run_and_drive:
        filters["FETI"] = ["lot_condition_code:CERT-D"]
    if cylinders and cylinders.lower() not in ("any", "all", "dowolny", ""):
        filters["CYLN"] = [f'cylinders:"{cylinders}"']

    criteria = {
        "query": ["*"],
        "filter": filters,
        "sort": ["lot_number desc"],
        "searchName": "",
        "watchListOnly": False,
        "freeFormSearch": False,
        "exclusions": [],
    }
    encoded_criteria = quote(json.dumps(criteria, separators=(",", ":")))
    query_str = quote(f"{make.lower()} {model.lower()}")
    return (
        f"https://www.copart.com/lotSearchResults?free=true&query={query_str}"
        f"&index=null&searchCriteria={encoded_criteria}"
    )


def build_iaai_url_from_filters(cfg: dict) -> str:
    """Construct an IAAI keyword search URL if custom encrypted URL is not used."""
    make = str(cfg.get("make", "DODGE")).strip()
    model = str(cfg.get("model", "CHALLENGER")).strip()
    query_str = quote(f"{make} {model}")
    return f"https://www.iaai.com/Search?keyword={query_str}"


def load_active_search_config() -> dict:
    """
    Load scraper filter configuration from search_config.json,
    and override with live Firebase Firestore settings/scraper document if FIREBASE_PROJECT_ID is set.
    """
    cfg = {}
    path = Path(SEARCH_CONFIG_FILE)
    if path.exists():
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass

    if FIREBASE_PROJECT_ID:
        # 1. Try Firebase Realtime Database first (`/{userId}/config.json` or `/active_config/config.json`)
        rtdb_paths = []
        if FIREBASE_USER_ID:
            rtdb_paths.append(f"/{FIREBASE_USER_ID}/config.json")
        rtdb_paths.append("/active_config/config.json")

        loaded_from_rtdb = False
        for base_url in get_rtdb_urls():
            if loaded_from_rtdb:
                break
            for rtdb_path in rtdb_paths:
                try:
                    resp = requests.get(f"{base_url}{rtdb_path}", timeout=6)
                    if resp.ok:
                        remote_cfg = resp.json()
                        if isinstance(remote_cfg, dict) and remote_cfg:
                            cfg.update(remote_cfg)
                            logger.info("[Config] Loaded live search filters from Firebase Realtime DB (%s).", rtdb_path)
                            loaded_from_rtdb = True
                            break
                except Exception:
                    pass

        # 2. Fallback to Cloud Firestore (`users/{userId}` or `settings/scraper`)
        if not loaded_from_rtdb:
            key_param = f"?key={FIREBASE_API_KEY}" if FIREBASE_API_KEY else ""
            doc_paths = []
            if FIREBASE_USER_ID:
                doc_paths.append(f"users/{FIREBASE_USER_ID}")
            doc_paths.append("settings/scraper")

            for doc_path in doc_paths:
                try:
                    url = (
                        f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}"
                        f"/databases/(default)/documents/{doc_path}{key_param}"
                    )
                    resp = requests.get(url, timeout=6)
                    if resp.ok:
                        doc = resp.json().get("fields", {})
                        if "config_json" in doc and "stringValue" in doc["config_json"]:
                            remote_cfg = json.loads(doc["config_json"]["stringValue"])
                            if isinstance(remote_cfg, dict):
                                cfg.update(remote_cfg)
                                logger.info("[Config] Loaded live search filters from Firebase Firestore (%s).", doc_path)
                                break
                except Exception as exc:
                    logger.debug("[Config] Could not fetch Firestore settings (%s): %s", doc_path, exc)

    return cfg


ACTIVE_CONFIG = load_active_search_config()

# Target Search URLs (uses custom URLs if enabled, otherwise generates dynamically from filters)
if ACTIVE_CONFIG.get("use_custom_urls", True) and ACTIVE_CONFIG.get("copart_url"):
    COPART_SEARCH_URL = ACTIVE_CONFIG["copart_url"]
else:
    COPART_SEARCH_URL = build_copart_url_from_filters(ACTIVE_CONFIG)

if ACTIVE_CONFIG.get("use_custom_urls", True) and ACTIVE_CONFIG.get("iaai_url"):
    IAAI_SEARCH_URL = ACTIVE_CONFIG["iaai_url"]
else:
    IAAI_SEARCH_URL = build_iaai_url_from_filters(ACTIVE_CONFIG)

# API Keys & Credentials
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# Gemini Model Configuration (gemini-3.5-flash-lite responds in ~3-4s per car)
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
