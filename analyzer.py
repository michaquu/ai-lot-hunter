import logging
import time
from typing import List, Literal, Optional
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL
from scraper import VehicleListing, download_images

logger = logging.getLogger(__name__)
logging.getLogger("google_genai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


class VisionAnalysisResult(BaseModel):
    decision: Literal["PASS", "REJECT"] = Field(
        description=(
            "Return 'PASS' if airbags_deployed is False, structural_or_beam_damage is False, "
            "AND (color_approved is True OR is_modified is True). Otherwise return 'REJECT'."
        )
    )
    identified_color: str = Field(
        description="The exterior paint color identified from the photos (e.g., 'Pitch Black', 'Granite Gray', 'Plum Crazy Purple', 'White', 'Red')."
    )
    color_approved: bool = Field(
        description="True ONLY if the exterior color is Pitch Black (Black), Granite / Destroyer / Smoke Show (Gray / Dark Gray), or Plum Crazy / Hellraisin (Purple)."
    )
    is_modified: bool = Field(
        description=(
            "True if the car has visible aftermarket tuning or visual/performance modifications "
            "(e.g., custom/upgraded exhaust tips or muffler, rear diffuser, cold air intake under hood, "
            "widebody kit, custom wheels/rims, Hellcat/Shaker hood or bumper conversion, window louvers, "
            "front splitter with rods, big spoiler/wicker bill, stripes/wraps, custom steering wheel/interior)."
        )
    )
    modifications_detected: Optional[str] = Field(
        default=None,
        description=(
            "If is_modified is True, list the visible modifications (e.g., 'Aftermarket quad exhaust + rear diffuser, "
            "K&N cold air intake, custom 20-inch wheels'). Otherwise None or 'Brak (seria)'."
        ),
    )
    airbags_deployed: bool = Field(
        description=(
            "True ONLY if you can clearly see a deployed/blown airbag (torn steering wheel horn cover with airbag out, "
            "passenger dash airbag deployed, side curtain airbags hanging down from the headliner, "
            "or deployed seat/knee airbag fabric)."
        )
    )
    structural_or_beam_damage: bool = Field(
        description=(
            "True ONLY if the car is SEVERELY / CATASTROPHICALLY wrecked ('mega mocno rozwalony'): "
            "e.g., the impact crushed deep into the engine block itself, the main frame rails ('podłużnice') or front crossmember "
            "are visibly mangled/twisted, the roof or A/B/C pillars are buckled, or a wheel/suspension is completely ripped off / folded under. "
            "Set to FALSE if the bumper cover or fender was simply removed/damaged exposing the normal crash bar or radiator!"
        )
    )
    damage_approved: bool = Field(
        description=(
            "True whenever airbags_deployed is False and structural_or_beam_damage is False "
            "(repairable front, rear, or side body damage)."
        )
    )
    damage_assessment: str = Field(
        description="Concise 1-2 sentence assessment describing the visible damage, airbag status, and why it is repairable or rejected."
    )
    rejection_reason: Optional[str] = Field(
        default=None,
        description=(
            "If decision is REJECT, state the exact reason (e.g., 'Deployed airbags', "
            "'Severe frame/engine crush', 'Rejected color (White) and stock/unmodified')."
        ),
    )
    vin_from_photo: Optional[str] = Field(
        default=None,
        description=(
            "If a 17-character VIN (starting with 2C3C...) is visible on a sticker, screen, or plate in any photo, "
            "extract it here. Otherwise None."
        ),
    )


SYSTEM_INSTRUCTION = """You are a practical salvage auto auction buyer specializing in 2019+ Dodge Challengers on Copart and IAAI.
Keep in mind that EVERY vehicle on Copart and IAAI is a salvage/collision car — you are looking for repairable project cars!
Do NOT be overly pedantic: insurance yards routinely unbolt/remove plastic bumper covers, headlights, or fenders for inspection, which exposes the metal bumper bar or radiator support underneath. That is NORMAL and MUST NOT be rejected as "exposed engine/structural damage"!

Evaluate the provided vehicle photos against these rules:

1. COLOR & TUNING/MODIFICATION FILTER (`color_approved` OR `is_modified`):
   - TARGET COLORS (`color_approved = true`):
     * Pitch Black (Black)
     * Granite / Granite Crystal / Destroyer Gray / Smoke Show (Dark Gray, Metallic Gray, or Charcoal Gray)
     * Plum Crazy or Hellraisin (Purple)
   - MODIFIED / TUNED EXCEPTION (`is_modified = true`):
     * Look for any aftermarket tuning or visual modifications ("przeróbki / tuning"):
       - Upgraded/aftermarket exhaust tips, muffler, or rear diffuser ("lepszy tłumik / wydech / dyfuzor")
       - Cold air intake / cone filter visible under the hood ("stożkowy dolot powietrza")
       - Widebody kit, Hellcat/SRT bumper conversion, Shaker hood or dual-snorkel hood
       - Custom aftermarket wheels/rims, painted brake calipers, lowered stance
       - Window louvers (żaluzje na szybach), front splitter, wicker bill / rear spoiler, racing stripes/wrap, custom halo lights, or custom interior.
     * If `is_modified = true`, the car PASSES the color requirement regardless of its paint color!

2. AIRBAG FILTER (`airbags_deployed`) — STRICT REJECT:
   - Check interior photos for deployed airbags ("wystrzelone poduszki"): steering wheel, dashboard, side curtain hanging from roof liner, or knee/seat airbags.
   - Only set `airbags_deployed = true` if an airbag is visibly deployed/blown. If airbags are intact, set `airbags_deployed = false`.

3. SEVERE WRECK FILTER (`structural_or_beam_damage`):
   - Set `structural_or_beam_damage = true` ONLY if the car is HEAVILY / CATASTROPHICALLY SMASHED ("mega mocno rozwalony"):
     * Front impact is so deep that the radiator/cooling pack and front structure are crushed right into the engine block/pulleys, or the engine is displaced/broken.
     * The main steel bumper reinforcement beam ("belka zderzaka") or frame rails ("podłużnice") are visibly bent in half, V-shaped, or torn off.
     * The roof is buckled/caved in, or A/B/C pillars are severely deformed.
     * A wheel is completely ripped off the car or folded at an extreme unnatural angle (broken control arms/knuckle).
   - IMPORTANT — SET `structural_or_beam_damage = false` AND `damage_approved = true` FOR NORMAL REPAIRABLE SALVAGE DAMAGE:
     * Missing, cracked, or removed plastic bumper cover (even if you can see the metal bumper beam, crash bar, radiator, or inner fender behind it!).
     * Dented, scratched, or missing bolt-on fender, hood, grille, headlight, taillight, trunk lid, door, or moderate quarter-panel dent where the car still holds its normal shape and stance.

4. FINAL DECISION:
   - Return `decision = "PASS"` whenever:
     `airbags_deployed == false` AND `structural_or_beam_damage == false` AND (`color_approved == true` OR `is_modified == true`).
   - Otherwise, return `decision = "REJECT"`.
"""

# Proven fast Vision Flash models available on the API key (ordered by speed & reliability)
FALLBACK_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
]


class GeminiVisionAnalyzer:
    """Analyzes vehicle listing images with Gemini Flash using google-genai SDK."""

    def __init__(self, api_key: str = GEMINI_API_KEY, model_name: str = GEMINI_MODEL) -> None:
        if not api_key or api_key == "your_gemini_api_key_here":
            raise ValueError(
                "GEMINI_API_KEY is missing or not configured in .env. "
                "Please set a valid Gemini API key."
            )
        self.client = genai.Client(api_key=api_key)
        self.model_pool: List[str] = list(FALLBACK_MODELS)
        if model_name and model_name not in self.model_pool:
            self.model_pool.insert(0, model_name)
        logger.info("[Gemini] Ready with model pool: %s", self.model_pool)

    def analyze_listing(self, listing: VehicleListing) -> Optional[VisionAnalysisResult]:
        """Download listing images and run Gemini Vision evaluation with automatic fallback on 503."""
        if not listing.image_urls:
            logger.warning("No image URLs found for %s (%s)", listing.title, listing.url)
            return None

        images = download_images(listing.image_urls)
        if not images:
            logger.warning(
                "Could not download any valid images for %s (%s)",
                listing.title,
                listing.url,
            )
            return None

        contents: List = [
            f"Inspect this {listing.source} Dodge Challenger listing ({listing.title}, URL: {listing.url}). "
            f"Check these {len(images)} salvage auction photos for: "
            f"(1) Exterior color (Black, Gray/Granite/Destroyer, or Purple), "
            f"(2) Any aftermarket tuning/modifications (custom exhaust/tips, diffuser, cold air intake, "
            f"custom wheels, widebody, splitter, louvers, spoiler/wicker bill, stripes/wrap, Hellcat/Shaker parts — if modified, it passes color regardless of paint color!), "
            f"(3) Deployed airbags (if airbags are blown -> REJECT), and "
            f"(4) Whether the damage is repairable bolt-on/body damage (PASS) vs a catastrophic structural/engine/frame-rail wreck (REJECT). "
            f"Remember: removed bumper covers or fenders exposing the normal crash bar or radiator are normal insurance teardowns and should PASS!"
        ]
        for img_bytes, mime_type in images:
            contents.append(
                types.Part.from_bytes(
                    data=img_bytes,
                    mime_type=mime_type,
                )
            )

        max_attempts = len(self.model_pool)

        for attempt in range(1, max_attempts + 1):
            current_model = self.model_pool[(attempt - 1) % len(self.model_pool)]
            try:
                logger.info(
                    "[Gemini] Analyzing %d photo(s) for %s Lot #%s using %s (attempt %d/%d)...",
                    len(images),
                    listing.source,
                    listing.lot_id,
                    current_model,
                    attempt,
                    max_attempts,
                )

                response = self.client.models.generate_content(
                    model=current_model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0.1,
                        response_mime_type="application/json",
                        response_schema=VisionAnalysisResult,
                        http_options=types.HttpOptions(timeout=75_000),
                    ),
                )

                if response.parsed and isinstance(response.parsed, VisionAnalysisResult):
                    result = response.parsed
                else:
                    result = VisionAnalysisResult.model_validate_json(response.text)

                if result.vin_from_photo and (not listing.vin or "*" in listing.vin):
                    listing.vin = result.vin_from_photo.strip()

                if (
                    result.airbags_deployed
                    or result.structural_or_beam_damage
                    or not result.damage_approved
                    or not (result.color_approved or result.is_modified)
                ):
                    result.decision = "REJECT"
                else:
                    result.decision = "PASS"

                if current_model != self.model_pool[0]:
                    self.model_pool.remove(current_model)
                    self.model_pool.insert(0, current_model)

                return result

            except Exception as exc:
                err_str = str(exc)
                next_model = self.model_pool[attempt % len(self.model_pool)]

                if attempt < max_attempts:
                    wait_sec = 4
                    logger.warning(
                        "[Gemini] '%s' returned error (%s). Switching to '%s' in %ds (retry %d/%d)...",
                        current_model,
                        err_str[:120],
                        next_model,
                        wait_sec,
                        attempt + 1,
                        max_attempts,
                    )
                    time.sleep(wait_sec)
                    continue

                logger.error(
                    "[Gemini] Vision analysis failed for %s (%s): %s",
                    listing.lot_id,
                    listing.url,
                    exc,
                )
                return None

        return None
