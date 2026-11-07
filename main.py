import argparse
import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Dict, List, Set

from analyzer import GeminiVisionAnalyzer, VisionAnalysisResult
from config import (
    FIREBASE_PROJECT_ID,
    HEADLESS,
    MAX_AGE_HOURS,
    MAX_IMAGES_PER_LISTING,
    MAX_LISTINGS_PER_SOURCE,
    PASSED_CARS_FILE,
    PASSED_CARS_MD_FILE,
    SEEN_LOTS_FILE,
)
import requests
from notifier import notify_result, send_telegram_alert
from scraper import AuctionScraper, VehicleListing

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_seen_lots(filepath: str = SEEN_LOTS_FILE) -> Set[str]:
    path = Path(filepath)
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data if isinstance(data, list) else [])
    except Exception:
        return set()


def save_seen_lots(seen: Set[str], filepath: str = SEEN_LOTS_FILE) -> None:
    path = Path(filepath)
    path.write_text(json.dumps(sorted(seen), indent=2) + "\n", encoding="utf-8")


def save_passed_car(
    listing: VehicleListing,
    result: VisionAnalysisResult,
    json_filepath: str = PASSED_CARS_FILE,
    md_filepath: str = PASSED_CARS_MD_FILE,
) -> None:
    """
    Save every qualifying (PASS) vehicle with its VIN and price-lookup links
    to passed_cars.json and PASSED_CARS.md in the repository.
    """
    json_path = Path(json_filepath)
    existing: List[Dict] = []
    if json_path.exists():
        try:
            loaded = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                existing = loaded
        except Exception:
            existing = []

    vin_val = (listing.vin or result.vin_from_photo or "").strip()
    lookup_query = vin_val if (vin_val and "*" not in vin_val) else listing.lot_id
    bidcars_url = f"https://bid.cars/pl/search/results?search-type=filters&q={lookup_query}"

    entry = {
        "id": f"{listing.source.lower()}_{listing.lot_id}",
        "found_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "source": listing.source,
        "lot_id": listing.lot_id,
        "vin": vin_val or "Ukryty (szukaj po Lot ID)",
        "title": listing.title,
        "color": result.identified_color,
        "color_approved": result.color_approved,
        "is_modified": result.is_modified,
        "modifications": result.modifications_detected or "Brak (seria)",
        "damage_assessment": result.damage_assessment,
        "url": listing.url,
        "price_check_url": bidcars_url,
        "image_urls": listing.image_urls,
    }

    # Optional: Push to free Firebase Spark Firestore (REST API, 0 Cloud Functions needed)
    if FIREBASE_PROJECT_ID:
        try:
            doc_id = entry["id"]
            fs_url = (
                f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}"
                f"/databases/(default)/documents/cars/{doc_id}"
            )
            fs_payload = {
                "fields": {
                    "car_json": {"stringValue": json.dumps(entry, ensure_ascii=False)},
                    "found_at": {"stringValue": entry["found_at"]},
                    "source": {"stringValue": entry["source"]},
                    "lot_id": {"stringValue": str(entry["lot_id"])},
                }
            }
            requests.patch(fs_url, json=fs_payload, timeout=8)
        except Exception as exc:
            logger.debug("Firestore sync skipped: %s", exc)

    # Deduplicate by (source, lot_id)
    updated = [
        item
        for item in existing
        if not (
            str(item.get("source", "")).lower() == listing.source.lower()
            and str(item.get("lot_id", "")) == str(listing.lot_id)
        )
    ]
    updated.insert(0, entry)
    serialized_json = json.dumps(updated, indent=2, ensure_ascii=False) + "\n"
    json_path.write_text(serialized_json, encoding="utf-8")
    web_public_json = Path("web/public/passed_cars.json")
    if web_public_json.parent.exists():
        web_public_json.write_text(serialized_json, encoding="utf-8")

    # Regenerate PASSED_CARS.md table for easy viewing on GitHub
    render_passed_cars_markdown(updated, md_filepath)


def render_passed_cars_markdown(records: List[Dict], md_filepath: str = PASSED_CARS_MD_FILE) -> None:
    lines = [
        "# ✅ Wybrane Auta (PASS) — Lista VIN i Historia Sprzedaży",
        "",
        "Plik aktualizowany automatycznie przez GitHub Actions po każdym znalezionym aucie.",
        "Kliknij w **Sprawdź cenę (Bid.Cars)**, aby zobaczyć za ile auto zostało wylicytowane po zakończeniu aukcji.",
        "",
        "| Data | Źródło & Lot | Tytuł | VIN | Kolor | Tuning / Modyfikacje | Ocena Uszkodzeń | Linki |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for r in records:
        date_str = r.get("found_at", "-")
        source = r.get("source", "-")
        lot_id = r.get("lot_id", "-")
        title = str(r.get("title", "-")).replace("|", "/")
        vin = r.get("vin", "-")
        color = str(r.get("color", "-")).replace("|", "/")
        mods = str(r.get("modifications", "Brak")).replace("|", "/")
        dmg = str(r.get("damage_assessment", "-")).replace("|", "/").replace("\n", " ")
        url = r.get("url", "#")
        price_url = r.get("price_check_url", "#")
        lines.append(
            f"| {date_str} | **{source}** `{lot_id}` | {title} | `{vin}` | {color} | {mods} | {dmg} | [Aukcja]({url}) • [Sprawdź cenę (Bid.Cars)]({price_url}) |"
        )

    Path(md_filepath).write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automated Copart & IAAI Dodge Challenger Scraper + Gemini Vision Analyzer"
    )
    parser.add_argument(
        "--source",
        choices=["all", "copart", "iaai"],
        default="all",
        help="Which auction site(s) to scrape (default: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=MAX_LISTINGS_PER_SOURCE,
        help=f"Max newest listings to inspect per auction site (default: {MAX_LISTINGS_PER_SOURCE})",
    )
    parser.add_argument(
        "--max-images",
        type=int,
        default=MAX_IMAGES_PER_LISTING,
        help=f"Max photos per vehicle sent to Gemini Vision (default: {MAX_IMAGES_PER_LISTING})",
    )
    parser.add_argument(
        "--only-today",
        action="store_true",
        help=f"Filter out listings older than {MAX_AGE_HOURS} hours when creation date is available",
    )
    parser.add_argument(
        "--mark-existing-seen",
        action="store_true",
        help=(
            "Baseline snapshot: record all currently visible listings into seen_lots.json "
            "WITHOUT calling Gemini AI, so future runs only analyze brand-new listings added after now."
        ),
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=HEADLESS,
        help="Run Playwright browser in headless mode",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Force visible browser window (recommended against Cloudflare/WAF)",
    )
    parser.add_argument(
        "--ignore-seen",
        action="store_true",
        help="Re-analyze listings even if they are recorded in seen_lots.json",
    )
    parser.add_argument(
        "--test-telegram",
        action="store_true",
        help="Send a test notification to Telegram and exit immediately",
    )
    return parser.parse_args()


async def run_pipeline() -> None:
    args = parse_args()

    if args.test_telegram:
        logger.info("Wysyłanie testowego powiadomienia na Telegram (wraz z 2 autami znalezionymi wcześniej)...")
        sample_cars = [
            (
                VehicleListing(
                    source="Copart",
                    lot_id="71903086",
                    url="https://www.copart.com/lot/71903086",
                    title="2019 DODGE CHALLENGER SXT",
                ),
                VisionAnalysisResult(
                    decision="PASS",
                    identified_color="Pitch Black",
                    color_approved=True,
                    is_modified=False,
                    airbags_deployed=False,
                    structural_or_beam_damage=False,
                    damage_approved=True,
                    damage_assessment=(
                        "Damage is limited to bolt-on components (front bumper cover, passenger headlight, "
                        "passenger front fender). Cooling pack and radiator support are straight, airbags intact."
                    ),
                ),
            ),
            (
                VehicleListing(
                    source="IAAI",
                    lot_id="46932215",
                    url="https://www.iaai.com/VehicleDetail/46932215~US",
                    title="2023 DODGE CHALLENGER SXT",
                ),
                VisionAnalysisResult(
                    decision="PASS",
                    identified_color="Granite Gray",
                    color_approved=True,
                    is_modified=False,
                    airbags_deployed=False,
                    structural_or_beam_damage=False,
                    damage_approved=True,
                    damage_assessment=(
                        "Side impact damage affecting right front fender and passenger door; "
                        "airbags are intact and no major structural or frame rail damage visible."
                    ),
                ),
            ),
        ]
        for listing, res in sample_cars:
            send_telegram_alert(listing, res)
        return

    headless_mode = False if args.headful else args.headless
    sources = ["copart", "iaai"] if args.source == "all" else [args.source]
    seen_lots = set() if args.ignore_seen else load_seen_lots()

    if args.mark_existing_seen:
        scraper = AuctionScraper(
            headless=headless_mode,
            max_listings=100,
            max_images=0,
        )
        logger.info("Creating baseline snapshot of existing listings (--mark-existing-seen)...")
        existing = await scraper.scrape_all(
            sources=sources,
            seen_lot_ids=seen_lots,
            search_only=True,
        )
        for item in existing:
            seen_lots.add(f"{item.source.lower()}:{item.lot_id}")
        save_seen_lots(seen_lots)
        logger.info(
            "Saved %d existing listing(s) to %s. Next runs will ONLY inspect newly added cars!",
            len(existing),
            SEEN_LOTS_FILE,
        )
        return

    analyzer = GeminiVisionAnalyzer()

    scraper = AuctionScraper(
        headless=headless_mode,
        max_listings=args.limit,
        max_images=args.max_images,
        max_age_hours=MAX_AGE_HOURS if args.only_today else None,
    )

    passed_matches = []
    rejected_count = 0

    def process_listing_immediately(listing: VehicleListing) -> None:
        nonlocal rejected_count
        result = analyzer.analyze_listing(listing)
        if result is None:
            return

        notify_result(listing, result)

        unique_key = f"{listing.source.lower()}:{listing.lot_id}"
        seen_lots.add(unique_key)
        save_seen_lots(seen_lots)

        if result.decision == "PASS":
            save_passed_car(listing, result)
            passed_matches.append((listing, result))
        else:
            rejected_count += 1

    logger.info(
        "Starting scraper (sources=%s, newest_limit=%d, only_today=%s, headless=%s)...",
        sources,
        args.limit,
        args.only_today,
        headless_mode,
    )
    listings = await scraper.scrape_all(
        sources=sources,
        seen_lot_ids=seen_lots,
        on_listing_ready=process_listing_immediately,
    )

    if not listings:
        logger.info("No new vehicle listings found since last check.")
        return

    print("\n" + "#" * 72, flush=True)
    print(
        f"RUN SUMMARY: Inspected {len(listings)} newest listing(s) | "
        f"✅ PASS: {len(passed_matches)} | ❌ REJECT: {rejected_count}",
        flush=True,
    )
    for listing, res in passed_matches:
        vin_tag = f" | VIN: {listing.vin or res.vin_from_photo or 'Ukryty'}"
        mods_tag = f" | 🔥 MODS: {res.modifications_detected}" if res.is_modified else ""
        print(
            f"  -> [{listing.source}] {listing.url}{vin_tag} | {res.identified_color}{mods_tag} | {res.damage_assessment}",
            flush=True,
        )
    print("#" * 72 + "\n", flush=True)


if __name__ == "__main__":
    asyncio.run(run_pipeline())
