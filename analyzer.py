import logging
import re
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
            "Return 'PASS' ONLY if damage_approved is True (airbags_deployed is False and "
            "structural_or_beam_damage is False) AND (color_approved is True OR is_modified is True). "
            "Otherwise return 'REJECT'."
        )
    )
    identified_color: str = Field(
        description="The exterior paint color identified from the photos (e.g., 'Pitch Black', 'Granite Gray', 'Plum Crazy Purple', 'White', 'Red')."
    )
    color_approved: bool = Field(
        description="True ONLY if the exterior color is Pitch Black (Black), Granite (Dark/Metallic Gray), or Plum Crazy / Hellraisin (Purple)."
    )
    is_modified: bool = Field(
        description=(
            "True if the car has visible aftermarket tuning or visual/performance modifications "
            "(e.g., custom/upgraded exhaust tips or muffler, rear diffuser, cold air intake under hood, "
            "widebody kit, custom wheels/rims, Hellcat/Shaker hood or bumper conversion, window louvers, "
            "front splitter with rods, big spoiler, custom steering wheel/interior)."
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
            "True if ANY airbag is deployed or blown (steering wheel horn pad torn/open, "
            "passenger dash airbag deployed, side curtain airbags hanging from roof liner, "
            "seat/knee airbags deployed, or yellow/white airbag fabric visible)."
        )
    )
    structural_or_beam_damage: bool = Field(
        description=(
            "True if the car is heavily wrecked: e.g., front/rear bumper reinforcement beam (crash bar / 'belka') "
            "is bent or crushed, frame rails ('podłużnice') are bent, radiator support is pushed into the engine, "
            "the front end is torn off exposing the engine/belts/cooling pack, pillars/roof are deformed, "
            "or suspension/wheels are ripped or crooked."
        )
    )
    damage_approved: bool = Field(
        description=(
            "True ONLY if airbags_deployed is False, structural_or_beam_damage is False, "
            "and damage is strictly minor/superficial bolt-on (bumper cover, grille, headlight/taillight, "
            "minor hood or fender dent without internal structural crush)."
        )
    )
    damage_assessment: str = Field(
        description="Concise 1-2 sentence assessment describing the visible damage, crash beam/engine status, and airbag status."
    )
    rejection_reason: Optional[str] = Field(
        default=None,
        description=(
            "If decision is REJECT, state the exact reason (e.g., 'Deployed airbags', "
            "'Bent front reinforcement beam / exposed engine', 'Rejected color (White) and stock/unmodified')."
        ),
    )


SYSTEM_INSTRUCTION = """You are a strict, expert salvage auto auction inspector specializing in 2019+ Dodge Challengers.
Your task is to filter out heavily damaged cars and cars with blown airbags, while finding clean/lightly damaged Challengers in target colors OR with interesting aftermarket modifications.

Evaluate the provided vehicle photos against these STRICT rules:

1. COLOR & TUNING/MODIFICATION FILTER (color_approved OR is_modified):
   - TARGET COLORS (`color_approved = true`):
     * Pitch Black (Black)
     * Granite / Granite Crystal (Dark Gray / Metallic Charcoal Gray)
     * Plum Crazy or Hellraisin (Purple)
   - MODIFIED / TUNED EXCEPTION (`is_modified = true`):
     * Look closely at all photos (exterior, rear bumper/exhaust, wheels, and under-hood) for aftermarket modifications ("przeróbki / tuning"):
       - Upgraded/aftermarket exhaust system, custom exhaust tips, or aggressive rear diffuser ("lepszy tłumik / wydech / dyfuzor")
       - Cold air intake / cone filter visible in the engine bay ("stożkowy dolot powietrza")
       - Widebody kit / fender flares, Hellcat/SRT bumper conversion, Shaker hood or dual-snorkel hood
       - Custom aftermarket wheels/rims, lowered stance, upgraded brake calipers
       - Window louvers (żaluzje na szybach), front splitter with support rods, large rear wing/spoiler, custom RGB/halos, or custom carbon/leather interior.
     * If the car has noticeable aftermarket modifications (`is_modified = true`), it CAN PASS EVEN IF ITS COLOR IS NOT ON THE TARGET COLOR LIST (as long as it passes the damage and airbag rules below!).

2. AIRBAG FILTER (airbags_deployed) — STRICT REJECT:
   - Inspect all interior and exterior photos carefully for deployed airbags ("wystrzelone poduszki").
   - Look at the steering wheel center cover, dashboard passenger side, A-pillar / roof headliner (side curtain airbags), knee bolster, and seat bolsters.
   - If you see ANY deployed airbag fabric, torn steering wheel cover, or blown curtain/dash airbag -> set `airbags_deployed = true` and IMMEDIATELY REJECT (`decision = "REJECT"`), even if the car is modified!

3. HEAVY CRASH / BENT BEAM / EXPOSED ENGINE FILTER (structural_or_beam_damage) — STRICT REJECT:
   - Immediately REJECT (`structural_or_beam_damage = true`) if the vehicle is heavily wrecked ("mocno rozwalony"), including ANY of the following:
     * Exposed engine / engine bay internals visible from the outside because the front clip, hood, or radiator support is smashed or ripped off.
     * Bent, kinked, twisted, or pushed-in bumper reinforcement beam / crash bar ("skrzywiona belka zderzaka") or bent frame rails ("podłużnice").
     * Crushed radiator / condenser / cooling pack pushed back toward the engine block.
     * Bent or buckled roof, or damaged A, B, or C pillars, or heavy rear quarter-panel crush into the cabin/trunk floor.
     * Ripped, collapsed, or crooked suspension (wheel sitting at an unnatural angle or pushed into the fender well).

4. ACCEPTABLE DAMAGE (damage_approved):
   - Set `damage_approved = true` ONLY when `airbags_deployed == false`, `structural_or_beam_damage == false`, and the damage is genuinely light, superficial, cosmetic, or simple bolt-on outer parts (bumper cover, grille, headlight/taillight, lightly dented fender/hood/trunk lid with straight underlying structure).

5. FINAL DECISION:
   - Return `decision = "PASS"` ONLY if:
     `damage_approved == true` AND `airbags_deployed == false` AND `structural_or_beam_damage == false`
     AND (`color_approved == true` OR `is_modified == true`).
   - Otherwise, return `decision = "REJECT"`.
"""


class GeminiVisionAnalyzer:
    """Analyzes vehicle listing images with Gemini Flash using google-genai SDK."""

    def __init__(self, api_key: str = GEMINI_API_KEY, model_name: str = GEMINI_MODEL) -> None:
        if not api_key or api_key == "your_gemini_api_key_here":
            raise ValueError(
                "GEMINI_API_KEY is missing or not configured in .env. "
                "Please set a valid Gemini API key."
            )
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self._tried_models = {model_name}

    def _select_fallback_model(self, error_text: str) -> Optional[str]:
        """
        If the current Gemini model returns 404 NOT_FOUND, extract the suggested model
        from the API error or query client.models.list() for an available Flash model.
        """
        # 1. Check if the 404 message explicitly recommends a model
        match = re.search(r"use models/([a-zA-Z0-9._-]+)", error_text)
        if match:
            suggested = match.group(1)
            if suggested not in self._tried_models:
                self._tried_models.add(suggested)
                return suggested

        # 2. Query available models from the API key
        try:
            available_flash = []
            for m in self.client.models.list():
                name = (getattr(m, "name", "") or "").replace("models/", "")
                if (
                    "gemini" in name
                    and "flash" in name
                    and "tts" not in name
                    and "image" not in name
                    and "thinking" not in name
                    and name not in self._tried_models
                ):
                    available_flash.append(name)
            if available_flash:
                # Sort descending so newest generation flash model is chosen first
                available_flash.sort(reverse=True)
                chosen = available_flash[0]
                self._tried_models.add(chosen)
                return chosen
        except Exception as exc:
            logger.debug("Could not list Gemini models: %s", exc)

        # 3. Static fallback list
        for candidate in (
            "gemini-3.8-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.0-flash",
        ):
            if candidate not in self._tried_models:
                self._tried_models.add(candidate)
                return candidate

        return None

    def analyze_listing(self, listing: VehicleListing) -> Optional[VisionAnalysisResult]:
        """Download listing images and run Gemini Vision evaluation with Free Tier retry support."""
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
            f"Carefully check all {len(images)} photos for: "
            f"(1) Exterior color (Pitch Black, Granite Gray, or Plum Crazy/Hellraisin Purple), "
            f"(2) Any aftermarket tuning/modifications (custom exhaust/muffler tips, diffuser, cold air intake, "
            f"custom wheels, widebody, splitter, louvers, Hellcat/Shaker conversion — if modified, it passes the color check regardless of paint color!), "
            f"(3) Deployed airbags (steering wheel, dash, curtain, seats -> immediate reject), and "
            f"(4) Heavy front/rear/side crash damage such as exposed engine, bent bumper reinforcement beam (belka), "
            f"pushed-in radiator support, bent frame rails, pillar/roof damage, or suspension damage (-> immediate reject)."
        ]
        for img_bytes, mime_type in images:
            contents.append(
                types.Part.from_bytes(
                    data=img_bytes,
                    mime_type=mime_type,
                )
            )

        max_attempts = 4
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(
                    "[Gemini] Analyzing %d photo(s) for %s Lot #%s using %s...",
                    len(images),
                    listing.source,
                    listing.lot_id,
                    self.model_name,
                )
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0.1,
                        response_mime_type="application/json",
                        response_schema=VisionAnalysisResult,
                        http_options=types.HttpOptions(timeout=90_000),
                    ),
                )

                if response.parsed and isinstance(response.parsed, VisionAnalysisResult):
                    result = response.parsed
                else:
                    result = VisionAnalysisResult.model_validate_json(response.text)

                # Hard safety guard: enforce rejection if airbags deployed, beam/structural damage, or unapproved damage,
                # and require EITHER approved color OR aftermarket modifications (is_modified).
                if (
                    result.airbags_deployed
                    or result.structural_or_beam_damage
                    or not result.damage_approved
                    or not (result.color_approved or result.is_modified)
                ):
                    result.decision = "REJECT"
                else:
                    result.decision = "PASS"

                return result

            except Exception as exc:
                err_str = str(exc)
                if ("404" in err_str or "NOT_FOUND" in err_str) and attempt < max_attempts:
                    fallback = self._select_fallback_model(err_str)
                    if fallback:
                        logger.warning(
                            "[Gemini] Model '%s' returned 404. Switching automatically to '%s'...",
                            self.model_name,
                            fallback,
                        )
                        self.model_name = fallback
                        continue

                if (
                    any(
                        code in err_str
                        for code in (
                            "429",
                            "RESOURCE_EXHAUSTED",
                            "503",
                            "UNAVAILABLE",
                            "500",
                            "504",
                            "DEADLINE_EXCEEDED",
                            "timed out",
                            "Timeout",
                        )
                    )
                    and attempt < max_attempts
                ):
                    wait_sec = 10 * attempt
                    logger.warning(
                        "[Gemini] Temporary API overload/limit (%s). Waiting %ds before retry %d/%d...",
                        "503 UNAVAILABLE" if "503" in err_str else "Rate Limit/Timeout",
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
