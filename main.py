import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Set

from analyzer import GeminiVisionAnalyzer
from config import (
    HEADLESS,
    MAX_AGE_HOURS,
    MAX_IMAGES_PER_LISTING,
    MAX_LISTINGS_PER_SOURCE,
    SEEN_LOTS_FILE,
)
from notifier import notify_result
from scraper import AuctionScraper

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
    path.write_text(json.dumps(sorted(seen), indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automated Copart & IAAI Dodge Challenger Scraper + Gemini 2.5 Flash Vision Analyzer"
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
    return parser.parse_args()


async def run_pipeline() -> None:
    args = parse_args()
    headless_mode = False if args.headful else args.headless
    sources = ["copart", "iaai"] if args.source == "all" else [args.source]
    seen_lots = set() if args.ignore_seen else load_seen_lots()

    # If --mark-existing-seen is used, grab up to 100 current listings per source and save to seen_lots.json
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

    # Initialize Gemini Vision Analyzer early to validate GEMINI_API_KEY
    analyzer = GeminiVisionAnalyzer()

    scraper = AuctionScraper(
        headless=headless_mode,
        max_listings=args.limit,
        max_images=args.max_images,
        max_age_hours=MAX_AGE_HOURS if args.only_today else None,
    )

    logger.info(
        "Starting scraper (sources=%s, newest_limit=%d, only_today=%s, headless=%s)...",
        sources,
        args.limit,
        args.only_today,
        headless_mode,
    )
    listings = await scraper.scrape_all(sources=sources, seen_lot_ids=seen_lots)

    if not listings:
        logger.info("No new vehicle listings found since last check.")
        return

    passed_matches = []
    rejected_count = 0

    for listing in listings:
        result = analyzer.analyze_listing(listing)
        if result is None:
            continue

        notify_result(listing, result)

        unique_key = f"{listing.source.lower()}:{listing.lot_id}"
        seen_lots.add(unique_key)
        save_seen_lots(seen_lots)

        if result.decision == "PASS":
            passed_matches.append((listing, result))
        else:
            rejected_count += 1

    print("\n" + "#" * 72)
    print(
        f"RUN SUMMARY: Inspected {len(listings)} newest listing(s) | "
        f"✅ PASS: {len(passed_matches)} | ❌ REJECT: {rejected_count}"
    )
    for listing, res in passed_matches:
        mods_tag = f" | 🔥 MODS: {res.modifications_detected}" if res.is_modified else ""
        print(
            f"  -> [{listing.source}] {listing.url} | {res.identified_color}{mods_tag} | {res.damage_assessment}"
        )
    print("#" * 72 + "\n")


if __name__ == "__main__":
    asyncio.run(run_pipeline())
