import asyncio
from datetime import datetime, timezone
import logging
import random
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set
from urllib.parse import urljoin

import requests
from playwright.async_api import BrowserContext, Page, Response, async_playwright

from config import (
    COPART_SEARCH_URL,
    DEFAULT_HEADERS,
    DEFAULT_USER_AGENT,
    HEADLESS,
    IAAI_SEARCH_URL,
    MAX_IMAGES_PER_LISTING,
    MAX_LISTINGS_PER_SOURCE,
)

logger = logging.getLogger(__name__)


@dataclass
class VehicleListing:
    source: str  # "Copart" or "IAAI"
    lot_id: str
    url: str
    title: str = "Dodge Challenger"
    vin: str = ""
    created_at: Optional[datetime] = None
    image_urls: List[str] = field(default_factory=list)


def extract_vin_from_text(text: str) -> str:
    """Extract a 17-character Dodge Challenger VIN (2C3C..., full or partially masked with *) from text."""
    if not text:
        return ""
    # Prefer unmasked 17-char Challenger VIN first
    full_match = re.search(r"\b(2C3C[A-HJ-NPR-Z0-9]{13})\b", text)
    if full_match:
        return full_match.group(1)
    # Fallback to masked Challenger VIN (e.g. 2C3CDZAG*LH******)
    masked_match = re.search(r"(2C3C[A-HJ-NPR-Z0-9\*]{13})", text)
    if masked_match:
        return masked_match.group(1)
    # Generic VIN label match
    label_match = re.search(r"VIN\s*[:#-]?\s*([A-HJ-NPR-Z0-9\*]{11,17})", text, re.IGNORECASE)
    if label_match:
        return label_match.group(1).strip()
    return ""


def parse_copart_timestamp(item: dict) -> Optional[datetime]:
    """
    Attempt to extract a lot creation timestamp from Copart's Solr/JSON lot object.
    Common Copart fields: 'lcd' (lot created date), 'createDate', 'lotCreatedDate', 'fcdd'.
    """
    for key in ("lcd", "createDate", "lotCreatedDate", "fcdd"):
        raw = item.get(key)
        if not raw:
            continue
        try:
            if isinstance(raw, (int, float)):
                # Epoch milliseconds or seconds
                ts = raw / 1000.0 if raw > 1e11 else float(raw)
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            if isinstance(raw, str):
                cleaned = raw.strip().replace("Z", "+00:00")
                return datetime.fromisoformat(cleaned)
        except Exception:
            continue
    return None


STEALTH_INIT_SCRIPT = """
// Mask navigator.webdriver
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
});

// Provide realistic window.chrome object
window.chrome = {
    runtime: {},
    loadTimes: function() {},
    csi: function() {},
    app: {}
};

// Spoof plugins and languages
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});

Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
});

// Mask permissions query
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);
"""


async def apply_stealth(page: Page) -> None:
    """Apply playwright-stealth (supporting both v1 and v2 APIs) plus custom init scripts."""
    await page.add_init_script(STEALTH_INIT_SCRIPT)
    try:
        import playwright_stealth

        if hasattr(playwright_stealth, "stealth_async"):
            await playwright_stealth.stealth_async(page)
        elif hasattr(playwright_stealth, "Stealth"):
            stealth_obj = playwright_stealth.Stealth()
            if hasattr(stealth_obj, "apply_stealth_async"):
                await stealth_obj.apply_stealth_async(page)
    except Exception as exc:
        logger.debug("Optional playwright-stealth hook skipped: %s", exc)


async def human_delay(min_sec: float = 1.5, max_sec: float = 3.5) -> None:
    """Sleep for a randomized human-like interval."""
    await asyncio.sleep(random.uniform(min_sec, max_sec))


async def wait_for_cloudflare_or_waf(page: Page, timeout_sec: int = 25) -> None:
    """
    Detect Cloudflare Turnstile / Imperva Incapsula challenge pages and wait
    for them to resolve automatically or via user interaction in headful mode.
    """
    for _ in range(timeout_sec):
        try:
            title = (await page.title()).lower()
            content_snippet = (await page.content())[:4000].lower()
        except Exception:
            await asyncio.sleep(1)
            continue

        is_challenge = (
            "just a moment" in title
            or "attention required" in title
            or "cf-browser-verification" in content_snippet
            or "challenge-platform" in content_snippet
            or "incapsula incident" in content_snippet
            or "verify you are human" in content_snippet
        )
        if not is_challenge:
            return
        logger.info("Anti-bot challenge detected on %s; waiting for resolution...", page.url)
        await asyncio.sleep(1)


async def auto_scroll(page: Page, steps: int = 4) -> None:
    """Scroll down gradually to trigger lazy-loaded search results and images."""
    for _ in range(steps):
        await page.mouse.wheel(0, random.randint(450, 800))
        await asyncio.sleep(random.uniform(0.6, 1.2))


def normalize_copart_image_url(url: str) -> str:
    """Upgrade Copart thumbnail URLs (_thb.jpg) to full-resolution (_ful.jpg)."""
    if not url:
        return ""
    return re.sub(r"_(thb|sml)\.(jpg|jpeg|png)$", r"_ful.\2", url, flags=re.IGNORECASE)


def normalize_iaai_image_url(url: str) -> str:
    """Ensure IAAI vis.iaai.com resize URLs request a clear resolution for vision analysis."""
    if not url:
        return ""
    url = re.sub(r"width=\d+", "width=800", url, flags=re.IGNORECASE)
    url = re.sub(r"height=\d+", "height=600", url, flags=re.IGNORECASE)
    return url


class AuctionScraper:
    """Playwright-based stealth scraper for Copart and IAAI vehicle listings."""

    def __init__(
        self,
        headless: bool = HEADLESS,
        max_listings: int = MAX_LISTINGS_PER_SOURCE,
        max_images: int = MAX_IMAGES_PER_LISTING,
        max_age_hours: Optional[int] = None,
    ) -> None:
        self.headless = headless
        self.max_listings = max_listings
        self.max_images = max_images
        self.max_age_hours = max_age_hours

    async def _create_context(self, playwright_instance) -> tuple:
        browser = await playwright_instance.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-infobars",
                "--window-size=1440,900",
            ],
        )
        context = await browser.new_context(
            user_agent=DEFAULT_USER_AGENT,
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers=DEFAULT_HEADERS,
        )
        return browser, context

    # -------------------------------------------------------------------------
    # COPART SCRAPING
    # -------------------------------------------------------------------------
    async def scrape_copart_search(
        self, context: BrowserContext, search_url: str = COPART_SEARCH_URL
    ) -> List[VehicleListing]:
        """Navigate to Copart search results and extract individual lot URLs."""
        page = await context.new_page()
        await apply_stealth(page)

        listings_by_lot: Dict[str, VehicleListing] = {}
        captured_api: Dict[str, object] = {"url": "", "post_data": "", "headers": {}, "total": 0}

        def ingest_copart_items(content_list: list) -> None:
            for item in content_list:
                if not isinstance(item, dict):
                    continue
                lot_num = str(
                    item.get("ln") or item.get("lotNumberStr") or ""
                ).strip()
                if lot_num and lot_num.isdigit():
                    title = (
                        item.get("ld")
                        or f"{item.get('lcy', '')} {item.get('mkn', 'DODGE')} {item.get('lm', 'CHALLENGER')}".strip()
                    )
                    created_dt = parse_copart_timestamp(item)
                    lot_url = f"https://www.copart.com/lot/{lot_num}"
                    thumb_url = normalize_copart_image_url(str(item.get("tims") or ""))
                    initial_imgs = [thumb_url] if thumb_url.startswith("http") else []
                    raw_vin = str(
                        item.get("fv") or item.get("vin") or item.get("vn") or ""
                    ).strip()
                    listings_by_lot[lot_num] = VehicleListing(
                        source="Copart",
                        lot_id=lot_num,
                        url=lot_url,
                        title=title,
                        vin=raw_vin,
                        created_at=created_dt,
                        image_urls=initial_imgs,
                    )

        async def handle_response(response: Response) -> None:
            if "search-results" in response.url or "lotSearchResults" in response.url:
                if "application/json" in response.headers.get("content-type", ""):
                    try:
                        data = await response.json()
                        results_obj = data.get("data", {}).get("results", {})
                        total_el = results_obj.get("totalElements")
                        if isinstance(total_el, int) and total_el > int(captured_api["total"] or 0):
                            captured_api["total"] = total_el
                        if not captured_api["url"] and response.request.method == "POST":
                            captured_api["url"] = response.url
                            captured_api["post_data"] = response.request.post_data or ""
                            req_headers = response.request.headers
                            captured_api["headers"] = {
                                k: v
                                for k, v in req_headers.items()
                                if k.lower() in ("content-type", "x-xsrf-token", "accept")
                            }
                        content_list = results_obj.get("content", [])
                        ingest_copart_items(content_list)
                    except Exception:
                        pass

        page.on("response", handle_response)

        try:
            logger.info("[Copart] Navigating to search URL...")
            await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            await wait_for_cloudflare_or_waf(page)
            await human_delay(3.0, 5.0)

            try:
                await page.wait_for_selector(
                    'a[href*="/lot/"], span[data-uname="lotsearchLotnumber"]',
                    timeout=20000,
                )
            except Exception:
                logger.debug("[Copart] Primary table selector timed out, scrolling...")

            # 1. If Copart's internal search-results POST endpoint was captured and there are more results,
            # fetch all remaining pages (up to 6 pages x 100 items) directly inside the browser session
            total_expected = int(captured_api["total"] or 0)
            if captured_api["url"] and captured_api["post_data"] and (total_expected == 0 or len(listings_by_lot) < total_expected):
                try:
                    base_payload = json.loads(str(captured_api["post_data"]))
                    if isinstance(base_payload, dict):
                        max_api_pages = min(6, ((total_expected or 200) + 49) // 50 + 1)
                        for api_page in range(0, max_api_pages):
                            if total_expected > 0 and len(listings_by_lot) >= total_expected:
                                break
                            payload_copy = dict(base_payload)
                            payload_copy["page"] = api_page
                            payload_copy["size"] = max(int(payload_copy.get("size", 50) or 50), 100)
                            payload_copy["sort"] = ["lot_number desc"]
                            await page.evaluate(
                                """async ({ url, headers, bodyStr }) => {
                                    try {
                                        const res = await fetch(url, {
                                            method: 'POST',
                                            headers: headers,
                                            body: bodyStr,
                                            credentials: 'include'
                                        });
                                        return res.status;
                                    } catch (e) {
                                        return 0;
                                    }
                                }""",
                                {
                                    "url": captured_api["url"],
                                    "headers": captured_api["headers"],
                                    "bodyStr": json.dumps(payload_copy),
                                },
                            )
                            await human_delay(0.8, 1.4)
                except Exception as api_exc:
                    logger.debug("[Copart] In-page API pagination fallback: %s", api_exc)

            # 2. Also paginate through DOM pages (up to 6 pages) to capture all results when DOM paginator is used
            for page_num in range(1, 7):
                await auto_scroll(page, steps=4)
                await human_delay(1.2, 2.0)

                hrefs = await page.eval_on_selector_all(
                    'a[href*="/lot/"]',
                    "elements => elements.map(el => ({href: el.href, text: (el.innerText || '').trim()}))",
                )
                for item in hrefs:
                    href = item.get("href", "")
                    match = re.search(r"/lot/(\d{6,10})", href)
                    if match:
                        lot_num = match.group(1)
                        if lot_num not in listings_by_lot:
                            listings_by_lot[lot_num] = VehicleListing(
                                source="Copart",
                                lot_id=lot_num,
                                url=f"https://www.copart.com/lot/{lot_num}",
                                title=item.get("text") or f"Copart Lot #{lot_num}",
                            )

                total_expected = int(captured_api["total"] or 0)
                if total_expected > 0 and len(listings_by_lot) >= total_expected:
                    logger.info(
                        "[Copart] Collected all %d/%d listings across search pages.",
                        len(listings_by_lot),
                        total_expected,
                    )
                    break

                if page_num < 6:
                    try:
                        next_btn = page.locator(
                            'button.p-paginator-next:not(.p-disabled):not([disabled]), '
                            'a.p-paginator-next:not(.p-disabled), '
                            '[aria-label="Next Page"]:not([disabled]):not(.p-disabled), '
                            'li.paginate_button.next:not(.disabled) a'
                        ).first
                        if await next_btn.count() > 0 and await next_btn.is_visible():
                            prev_count = len(listings_by_lot)
                            logger.info(
                                "[Copart] Navigating to page %d of search results (collected %d so far)...",
                                page_num + 1,
                                prev_count,
                            )
                            await next_btn.click()
                            await human_delay(2.5, 4.0)
                        else:
                            break
                    except Exception:
                        break
        except Exception as exc:
            logger.error("[Copart] Error scraping search results: %s", exc)
        finally:
            await page.close()

        # Sort Copart listings by newest first:
        # Higher Copart lot numbers (or newer created_at timestamps) correspond to the most recently added lots.
        all_listings = list(listings_by_lot.values())
        all_listings.sort(
            key=lambda x: (
                x.created_at.timestamp() if x.created_at else 0.0,
                int(x.lot_id) if x.lot_id.isdigit() else 0,
            ),
            reverse=True,
        )

        # If max_age_hours is set and Copart provided creation timestamps, filter out older lots
        if self.max_age_hours is not None:
            now_utc = datetime.now(timezone.utc)
            filtered: List[VehicleListing] = []
            for item in all_listings:
                if item.created_at is not None:
                    age_hours = (now_utc - item.created_at).total_seconds() / 3600.0
                    if age_hours > self.max_age_hours:
                        logger.info(
                            "[Copart] Skipping Lot #%s (added %.1fh ago > %dh limit)",
                            item.lot_id,
                            age_hours,
                            self.max_age_hours,
                        )
                        continue
                filtered.append(item)
            all_listings = filtered

        logger.info("[Copart] Found %d total listing(s) on search page.", len(all_listings))
        return all_listings

    async def extract_copart_images(
        self, context: BrowserContext, listing: VehicleListing
    ) -> List[str]:
        """Navigate to a Copart lot detail page and extract primary vehicle image URLs."""
        page = await context.new_page()
        await apply_stealth(page)
        fallback_urls = list(listing.image_urls)
        collected_urls: List[str] = []
        seen: Set[str] = set()

        def add_image(url: str) -> None:
            clean = normalize_copart_image_url(url.strip())
            if (
                clean
                and clean.startswith("http")
                and clean not in seen
                and any(ext in clean.lower() for ext in (".jpg", ".jpeg", ".png", ".webp"))
            ):
                seen.add(clean)
                collected_urls.append(clean)

        async def handle_response(response: Response) -> None:
            if (
                "lotImages" in response.url
                or "lotdetails" in response.url.lower()
                or "solr/lotDetails" in response.url
            ):
                if "application/json" in response.headers.get("content-type", ""):
                    try:
                        payload = await response.json()
                        text_dump = str(payload)
                        found_vin = extract_vin_from_text(text_dump)
                        if found_vin and (not listing.vin or "*" in listing.vin):
                            listing.vin = found_vin
                        for match in re.findall(
                            r"https?://[^\s'\"<>]+?_ful\.(?:jpg|jpeg|png)",
                            text_dump,
                            flags=re.IGNORECASE,
                        ):
                            add_image(match)
                        for match in re.findall(
                            r"https?://cs\.copart\.com[^\s'\"<>]+?\.(?:jpg|jpeg|png)",
                            text_dump,
                            flags=re.IGNORECASE,
                        ):
                            add_image(match)
                    except Exception:
                        pass

        page.on("response", handle_response)

        try:
            logger.info("[Copart] Extracting images from %s", listing.url)
            await page.goto(listing.url, wait_until="domcontentloaded", timeout=45000)
            await wait_for_cloudflare_or_waf(page, timeout_sec=10)
            await human_delay(2.0, 3.5)

            try:
                await page.wait_for_selector(
                    'img[src*="copart"], .p-galleria-item img, #show-img',
                    timeout=10000,
                )
            except Exception:
                pass

            await auto_scroll(page, steps=2)

            try:
                page_title = await page.locator("h1.title, h1").first.inner_text(timeout=3000)
                if page_title and page_title.strip():
                    listing.title = page_title.strip()
            except Exception:
                pass

            try:
                body_text = await page.locator("body").inner_text(timeout=3000)
                dom_vin = extract_vin_from_text(body_text)
                if dom_vin and (not listing.vin or "*" in listing.vin):
                    listing.vin = dom_vin
            except Exception:
                pass

            dom_images = await page.eval_on_selector_all(
                "img",
                """imgs => imgs.map(img => (
                    img.getAttribute('full-url') ||
                    img.getAttribute('hd-url') ||
                    img.getAttribute('data-src') ||
                    img.src || ''
                ))""",
            )
            for img_url in dom_images:
                if "copart.com" in img_url and not any(
                    skip in img_url.lower()
                    for skip in ("logo", "icon", "flag", "banner", "avatar", "svg")
                ):
                    add_image(img_url)

        except Exception as exc:
            logger.error("[Copart] Error extracting images for %s: %s", listing.url, exc)
        finally:
            await page.close()

        if not collected_urls and fallback_urls:
            logger.info(
                "[Copart] Detail page WAF blocked; using %d fallback image(s) from search results for lot %s",
                len(fallback_urls),
                listing.lot_id,
            )
            collected_urls = fallback_urls

        listing.image_urls = collected_urls[: self.max_images]
        logger.info(
            "[Copart] Extracted %d image(s) for lot %s",
            len(listing.image_urls),
            listing.lot_id,
        )
        return listing.image_urls

    # -------------------------------------------------------------------------
    # IAAI SCRAPING
    # -------------------------------------------------------------------------
    async def scrape_iaai_search(
        self, context: BrowserContext, search_url: str = IAAI_SEARCH_URL
    ) -> List[VehicleListing]:
        """Navigate to IAAI search results and extract individual VehicleDetail URLs."""
        page = await context.new_page()
        await apply_stealth(page)

        listings_by_id: Dict[str, VehicleListing] = {}

        try:
            logger.info("[IAAI] Navigating to search URL...")
            await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            await wait_for_cloudflare_or_waf(page)
            await human_delay(3.0, 5.0)

            try:
                await page.wait_for_selector(
                    'a[href*="/VehicleDetail/"], a[href*="/vehicledetail/"]',
                    timeout=20000,
                )
            except Exception:
                logger.debug("[IAAI] Primary vehicle detail selector timed out, scrolling...")

            for page_num in range(1, 6):
                await auto_scroll(page, steps=8)
                await human_delay(1.5, 2.5)

                anchors = await page.eval_on_selector_all(
                    'a[href*="VehicleDetail"], a[href*="vehicledetail"]',
                    """elements => elements.map(el => {
                        const card = el.closest('.table-row, .card, tr, li, div.row') || el.parentElement;
                        const img = card ? card.querySelector('img[src*="vis.iaai.com"], img[data-src*="vis.iaai.com"]') : null;
                        const imgSrc = img ? (img.getAttribute('data-src') || img.src || '') : '';
                        const cardText = card ? (card.innerText || '') : '';
                        return {
                            href: el.href,
                            text: (el.innerText || '').trim(),
                            imgSrc: imgSrc,
                            cardText: cardText
                        };
                    })""",
                )
                for item in anchors:
                    href = item.get("href", "")
                    match = re.search(r"/VehicleDetail/([A-Za-z0-9_~-]+)", href, re.IGNORECASE)
                    if match:
                        raw_id = match.group(1)
                        lot_id = raw_id.split("~")[0]
                        full_url = urljoin("https://www.iaai.com", href)
                        img_src = item.get("imgSrc", "")
                        card_vin = extract_vin_from_text(item.get("cardText", ""))
                        if lot_id not in listings_by_id:
                            listings_by_id[lot_id] = VehicleListing(
                                source="IAAI",
                                lot_id=lot_id,
                                url=full_url,
                                title=item.get("text") or f"IAAI Vehicle #{lot_id}",
                                vin=card_vin,
                            )
                        else:
                            if item.get("text") and listings_by_id[lot_id].title.startswith("IAAI Vehicle"):
                                listings_by_id[lot_id].title = item["text"]
                            if card_vin and not listings_by_id[lot_id].vin:
                                listings_by_id[lot_id].vin = card_vin

                        if img_src and "vis.iaai.com" in img_src and not listings_by_id[lot_id].image_urls:
                            base_img = normalize_iaai_image_url(img_src)
                            if "~I1" in base_img:
                                listings_by_id[lot_id].image_urls = [
                                    base_img.replace("~I1", f"~I{idx}")
                                    for idx in range(1, self.max_images + 1)
                                ]
                            else:
                                listings_by_id[lot_id].image_urls = [base_img]

                # Check if a Next Page button is present and enabled on IAAI
                if page_num < 5:
                    try:
                        next_btn = page.locator(
                            'button.btn-next:not([disabled]), a[aria-label*="Next"]:not(.disabled), li.pagination-next:not(.disabled) a'
                        ).first
                        if await next_btn.count() > 0 and await next_btn.is_visible():
                            logger.info("[IAAI] Navigating to page %d of search results...", page_num + 1)
                            await next_btn.click()
                            await human_delay(3.0, 4.5)
                        else:
                            break
                    except Exception:
                        break
        except Exception as exc:
            logger.error("[IAAI] Error scraping search results: %s", exc)
        finally:
            await page.close()

        # Sort IAAI listings by numeric ID descending (higher stock/item IDs are newer)
        all_listings = list(listings_by_id.values())
        all_listings.sort(
            key=lambda x: int(re.sub(r"\D", "", x.lot_id) or "0"),
            reverse=True,
        )

        logger.info("[IAAI] Found %d total listing(s) on search page.", len(all_listings))
        return all_listings

    async def extract_iaai_images(
        self, context: BrowserContext, listing: VehicleListing
    ) -> List[str]:
        """
        Extract primary vehicle image URLs for an IAAI listing.
        Uses image keys already captured on the Search page or IAAI's CDN resizer endpoint
        (vis.iaai.com/resizer?imageKeys={lot_id}~SID~I{1..N}) directly to bypass Imperva WAF
        blocks on /VehicleDetail/ pages from datacenter IPs.
        """
        if listing.image_urls:
            logger.info(
                "[IAAI] Using %d CDN image(s) extracted from search page for vehicle %s",
                len(listing.image_urls),
                listing.lot_id,
            )
            return listing.image_urls

        collected_urls: List[str] = []

        # Construct direct high-res CDN URLs for camera angles I1..I{max_images}
        primary_test_url = (
            f"https://vis.iaai.com/resizer?imageKeys={listing.lot_id}~SID~I1&width=800&height=600"
        )
        try:
            resp = requests.get(
                primary_test_url,
                headers={"User-Agent": DEFAULT_USER_AGENT},
                timeout=10,
            )
            if resp.status_code == 200 and len(resp.content) > 2048:
                for idx in range(1, self.max_images + 1):
                    collected_urls.append(
                        f"https://vis.iaai.com/resizer?imageKeys={listing.lot_id}~SID~I{idx}&width=800&height=600"
                    )
                listing.image_urls = collected_urls
                logger.info(
                    "[IAAI] Prepared %d direct CDN image(s) for vehicle %s",
                    len(listing.image_urls),
                    listing.lot_id,
                )
                return listing.image_urls
        except Exception as exc:
            logger.debug("[IAAI] Direct CDN probe failed for %s: %s", listing.lot_id, exc)

        # Fallback: attempt DOM extraction only if direct CDN URLs were unavailable
        page = await context.new_page()
        await apply_stealth(page)
        seen: Set[str] = set()

        def add_image(url: str) -> None:
            clean = normalize_iaai_image_url(url.strip())
            if clean and clean.startswith("http") and clean not in seen:
                seen.add(clean)
                collected_urls.append(clean)

        try:
            logger.info("[IAAI] Extracting images from %s", listing.url)
            await page.goto(listing.url, wait_until="domcontentloaded", timeout=30000)
            await wait_for_cloudflare_or_waf(page, timeout_sec=6)
            await human_delay(1.5, 2.5)

            dom_images = await page.eval_on_selector_all(
                "img",
                """imgs => imgs.map(img => (
                    img.getAttribute('data-src') ||
                    img.getAttribute('data-lazy') ||
                    img.src || ''
                ))""",
            )
            for img_url in dom_images:
                if "vis.iaai.com" in img_url or "iaai.com/Images" in img_url:
                    if not any(
                        skip in img_url.lower() for skip in ("logo", "icon", "sprite", "svg")
                    ):
                        add_image(img_url)
        except Exception as exc:
            logger.error("[IAAI] Error extracting images for %s: %s", listing.url, exc)
        finally:
            await page.close()

        listing.image_urls = collected_urls[: self.max_images]
        logger.info(
            "[IAAI] Extracted %d image(s) for vehicle %s",
            len(listing.image_urls),
            listing.lot_id,
        )
        return listing.image_urls

    # -------------------------------------------------------------------------
    # FULL PIPELINE RUNNER
    # -------------------------------------------------------------------------
    async def scrape_all(
        self,
        sources: Optional[List[str]] = None,
        seen_lot_ids: Optional[Set[str]] = None,
        search_only: bool = False,
        on_listing_ready: Optional[Callable[[VehicleListing], None]] = None,
    ) -> List[VehicleListing]:
        """
        Run the scraper across Copart and IAAI, skipping already-seen lots,
        and populate image_urls for each discovered vehicle listing.
        If on_listing_ready is provided, it is called immediately after each vehicle's images are extracted.
        """
        active_sources = [s.lower() for s in (sources or ["copart", "iaai"])]
        seen_ids = seen_lot_ids or set()
        populated_listings: List[VehicleListing] = []

        async with async_playwright() as p:
            browser, context = await self._create_context(p)
            try:
                if "copart" in active_sources:
                    copart_listings = await self.scrape_copart_search(context)
                    new_copart = [
                        item
                        for item in copart_listings
                        if f"copart:{item.lot_id}" not in seen_ids
                    ]
                    logger.info(
                        "[Copart] %d new listing(s) out of %d total (skipped %d already in seen_lots.json).",
                        len(new_copart),
                        len(copart_listings),
                        len(copart_listings) - len(new_copart),
                    )
                    for listing in new_copart[: self.max_listings]:
                        if search_only:
                            populated_listings.append(listing)
                            continue
                        await self.extract_copart_images(context, listing)
                        if listing.image_urls:
                            populated_listings.append(listing)
                            if on_listing_ready:
                                on_listing_ready(listing)
                        await human_delay(1.5, 3.0)

                if "iaai" in active_sources:
                    iaai_listings = await self.scrape_iaai_search(context)
                    new_iaai = [
                        item
                        for item in iaai_listings
                        if f"iaai:{item.lot_id}" not in seen_ids
                    ]
                    logger.info(
                        "[IAAI] %d new listing(s) out of %d total (skipped %d already in seen_lots.json).",
                        len(new_iaai),
                        len(iaai_listings),
                        len(iaai_listings) - len(new_iaai),
                    )
                    for listing in new_iaai[: self.max_listings]:
                        if search_only:
                            populated_listings.append(listing)
                            continue
                        await self.extract_iaai_images(context, listing)
                        if listing.image_urls:
                            populated_listings.append(listing)
                            if on_listing_ready:
                                on_listing_ready(listing)
                        await human_delay(1.5, 3.0)
            finally:
                await context.close()
                await browser.close()

        return populated_listings


def download_images(image_urls: List[str]) -> List[tuple[bytes, str]]:
    """
    Download vehicle images into memory as (bytes, mime_type) tuples for Gemini Vision.
    """
    downloaded: List[tuple[bytes, str]] = []
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )

    for url in image_urls:
        try:
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
            if not content_type.startswith("image/"):
                content_type = "image/jpeg"
            if len(resp.content) > 1024:
                downloaded.append((resp.content, content_type))
        except Exception as exc:
            logger.warning("Failed to download image %s: %s", url, exc)

    return downloaded
