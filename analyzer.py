import logging
import time
from typing import List, Literal, Optional
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL
from scraper import VehicleListing, download_images

logger = logging.getLogger(__name__)


class VisionAnalysisResult(BaseModel):
    decision: Literal["PASS", "REJECT"] = Field(
        description=(
            "Return 'PASS' ONLY if color_approved is True, damage_approved is True, "
            "airbags_deployed is False, and structural_or_beam_damage is False. "
            "Otherwise return 'REJECT'."
        )
    )
    identified_color: str = Field(
        description="The exterior paint color identified from the photos (e.g., 'Pitch Black', 'Granite Gray', 'Plum Crazy Purple', 'White', 'Red')."
    )
    color_approved: bool = Field(
        description="True ONLY if the exterior color is Pitch Black (Black), Granite (Dark/Metallic Gray), or Plum Crazy / Hellraisin (Purple)."
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
            "'Bent front reinforcement beam / exposed engine', 'Rejected color: White')."
        ),
    )


SYSTEM_INSTRUCTION = """You are a strict, conservative salvage auto auction inspector specializing in 2020+ Dodge Challengers.
Your task is to filter out heavily damaged cars, cars with blown airbags, and cars in unwanted colors.
When in doubt, always err on the side of caution and REJECT the vehicle.

Evaluate the provided vehicle photos against these STRICT rules:

1. COLOR FILTER (color_approved):
   - ONLY PASS these 3 colors:
     * Pitch Black (Black)
     * Granite / Granite Crystal (Dark Gray / Metallic Charcoal Gray)
     * Plum Crazy or Hellraisin (Purple)
   - REJECT ALL OTHER COLORS immediately (White, Red, Blue, Green, Silver, Yellow, Orange, etc.).

2. AIRBAG FILTER (airbags_deployed):
   - Inspect all interior and exterior photos carefully for deployed airbags ("wystrzelone poduszki").
   - Look at the steering wheel center cover, dashboard passenger side, A-pillar / roof headliner (side curtain airbags), knee bolster, and seat bolsters.
   - If you see ANY deployed airbag fabric, torn steering wheel cover, or blown curtain/dash airbag -> set `airbags_deployed = true` and IMMEDIATELY REJECT (`decision = "REJECT"`).

3. HEAVY CRASH / BENT BEAM / EXPOSED ENGINE FILTER (structural_or_beam_damage):
   - Immediately REJECT (`structural_or_beam_damage = true`) if the vehicle is heavily wrecked ("mocno rozwalony"), including ANY of the following:
     * Exposed engine / engine bay internals visible from the outside because the front clip, hood, or radiator support is smashed or ripped off.
     * Bent, kinked, twisted, or pushed-in bumper reinforcement beam / crash bar ("skrzywiona belka zderzaka") or bent frame rails ("podłużnice").
     * Crushed radiator / condenser / cooling pack pushed back toward the engine block.
     * Bent or buckled roof, or damaged A, B, or C pillars, or heavy rear quarter-panel crush into the cabin/trunk floor.
     * Ripped, collapsed, or crooked suspension (wheel sitting at an unnatural angle or pushed into the fender well).

4. ACCEPTABLE DAMAGE (damage_approved):
   - Set `damage_approved = true` ONLY when the damage is genuinely light, superficial, cosmetic, or simple bolt-on outer parts:
     * Scratched, cracked, or detached plastic bumper cover (with the metal crash beam behind it still straight and intact)
     * Broken headlight, taillight, or plastic grille
     * Lightly dented bolt-on fender, hood, or trunk lid where panel gaps show the underlying structure is straight.

5. FINAL DECISION:
   - Return `decision = "PASS"` ONLY if:
     `color_approved == true` AND `damage_approved == true` AND `airbags_deployed == false` AND `structural_or_beam_damage == false`.
   - Otherwise, return `decision = "REJECT"`.
"""


class GeminiVisionAnalyzer:
    """Analyzes vehicle listing images with Gemini 2.5 Flash using google-genai SDK."""

    def __init__(self, api_key: str = GEMINI_API_KEY, model_name: str = GEMINI_MODEL) -> None:
        if not api_key or api_key == "your_gemini_api_key_here":
            raise ValueError(
                "GEMINI_API_KEY is missing or not configured in .env. "
                "Please set a valid Gemini API key."
            )
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name

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
            f"(1) Exterior color (only Pitch Black, Granite Gray, or Plum Crazy/Hellraisin Purple allowed), "
            f"(2) Deployed airbags (steering wheel, dash, curtain, seats), and "
            f"(3) Heavy front/rear/side crash damage such as exposed engine, bent bumper reinforcement beam (belka), "
            f"pushed-in radiator support, bent frame rails, pillar/roof damage, or suspension damage."
        ]
        for img_bytes, mime_type in images:
            contents.append(
                types.Part.from_bytes(
                    data=img_bytes,
                    mime_type=mime_type,
                )
            )

        max_Attempts = 3
        for attempt in range(1, max_Attempts + 1):
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
                    ),
                )

                if response.parsed and isinstance(response.parsed, VisionAnalysisResult):
                    result = response.parsed
                else:
                    result = VisionAnalysisResult.model_validate_json(response.text)

                # Hard safety guard: enforce rejection if airbags deployed, beam/structural damage, or unapproved color/damage
                if (
                    result.airbags_deployed
                    or result.structural_or_beam_damage
                    or not result.color_approved
                    or not result.damage_approved
                ):
                    result.decision = "REJECT"

                return result

            except Exception as exc:
                err_str = str(exc)
                if ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str) and attempt < max_Attempts:
                    wait_sec = 15 * attempt
                    logger.warning(
                        "[Gemini] Free Tier rate limit reached (429). Waiting %ds before retry %d/%d...",
                        wait_sec,
                        attempt + 1,
                        max_Attempts,
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
