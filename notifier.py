import logging
import requests

from analyzer import VisionAnalysisResult
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from scraper import VehicleListing

logger = logging.getLogger(__name__)


def send_telegram_alert(listing: VehicleListing, analysis: VisionAnalysisResult) -> bool:
    """
    Send a Telegram message when a vehicle passes inspection.
    Silently skips if TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not configured.
    """
    if (
        not TELEGRAM_BOT_TOKEN
        or TELEGRAM_BOT_TOKEN == "your_telegram_bot_token_here"
        or not TELEGRAM_CHAT_ID
        or TELEGRAM_CHAT_ID == "your_telegram_chat_id_here"
    ):
        logger.debug("Telegram credentials not configured; skipping Telegram push alert.")
        return False

    message = (
        f"✅ *DODGE CHALLENGER MATCH ({listing.source})*\n\n"
        f"*Title:* {listing.title}\n"
        f"*Lot ID:* `{listing.lot_id}`\n"
        f"*Identified Color:* {analysis.identified_color}\n"
        f"*Damage Assessment:* {analysis.damage_assessment}\n\n"
        f"🔗 [View Listing]({listing.url})"
    )

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }

    try:
        response = requests.post(api_url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("[Telegram] Notification sent for %s Lot #%s", listing.source, listing.lot_id)
        return True
    except Exception as exc:
        logger.error("[Telegram] Failed to send notification: %s", exc)
        return False


def notify_result(listing: VehicleListing, analysis: VisionAnalysisResult) -> None:
    """
    Print terminal evaluation summary and trigger a PASS notification (terminal + Telegram).
    """
    divider = "=" * 72
    if analysis.decision == "PASS":
        print(f"\n{divider}")
        print(f"🚨 [PASS] QUALIFYING DODGE CHALLENGER FOUND ON {listing.source.upper()}!")
        print(divider)
        print(f"  Title             : {listing.title}")
        print(f"  Listing URL       : {listing.url}")
        print(f"  Identified Color  : {analysis.identified_color}")
        print(f"  Damage Assessment : {analysis.damage_assessment}")
        print(f"{divider}\n")
        send_telegram_alert(listing, analysis)
    else:
        print(
            f"❌ [REJECT] {listing.source} #{listing.lot_id} ({listing.title})\n"
            f"   URL               : {listing.url}\n"
            f"   Color             : {analysis.identified_color} (Approved: {analysis.color_approved})\n"
            f"   Airbags Deployed? : {analysis.airbags_deployed}\n"
            f"   Heavy/Beam Crush? : {analysis.structural_or_beam_damage}\n"
            f"   Damage Assessment : {analysis.damage_assessment}\n"
            f"   Rejection Reason  : {analysis.rejection_reason or 'Did not meet strict color/damage criteria'}\n"
        )
