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
        logger.info(
            "[Telegram] Pominięto wysyłkę na Telegram (brak TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID) — auto zapisane w logach i podsumowaniu."
        )
        return False

    mods_line = (
        f"🔥 *Przeróbki / Tuning:* TAK ({analysis.modifications_detected})\n"
        if analysis.is_modified
        else "*Przeróbki / Tuning:* Brak (seria)\n"
    )

    message = (
        f"✅ *DODGE CHALLENGER MATCH ({listing.source})*\n\n"
        f"*Title:* {listing.title}\n"
        f"*Lot ID:* `{listing.lot_id}`\n"
        f"*Identified Color:* {analysis.identified_color}\n"
        f"{mods_line}"
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
        logger.info(
            "📨 [Telegram] Wysłano powiadomienie dla %s Lot #%s (%s)",
            listing.source,
            listing.lot_id,
            listing.url,
        )
        return True
    except Exception as exc:
        logger.error("[Telegram] Błąd wysyłania powiadomienia: %s", exc)
        return False


def notify_result(listing: VehicleListing, analysis: VisionAnalysisResult) -> None:
    """
    Log live evaluation result immediately (for GitHub Actions real-time logs)
    and trigger Telegram alert when a car is selected (PASS).
    """
    divider = "=" * 72
    mods_info = (
        f"TAK ({analysis.modifications_detected or 'Wykryto modyfikacje'})"
        if analysis.is_modified
        else "Nie (seria)"
    )

    if analysis.decision == "PASS":
        pass_type = (
            "🔥 WYBRANO DO WYSŁANIA (TUNING/MODYFIKACJE)"
            if (analysis.is_modified and not analysis.color_approved)
            else "✅ WYBRANO DO WYSŁANIA (PASS)"
        )
        logger.info(
            "%s | %s #%s | URL: %s | Kolor: %s | Tuning: %s | Stan: %s",
            pass_type,
            listing.source,
            listing.lot_id,
            listing.url,
            analysis.identified_color,
            mods_info,
            analysis.damage_assessment,
        )
        print(
            f"\n{divider}\n"
            f"🚨 {pass_type}: {listing.source.upper()} #{listing.lot_id}\n"
            f"{divider}\n"
            f"  Title             : {listing.title}\n"
            f"  Listing URL       : {listing.url}\n"
            f"  Identified Color  : {analysis.identified_color} (Color OK: {analysis.color_approved})\n"
            f"  Modified / Tuning : {mods_info}\n"
            f"  Damage Assessment : {analysis.damage_assessment}\n"
            f"{divider}\n",
            flush=True,
        )
        send_telegram_alert(listing, analysis)
    else:
        logger.info(
            "❌ ODRZUCONO (REJECT) | %s #%s (%s) | Kolor: %s (OK=%s) | Tuning: %s | Poduszki: %s | Belka/Dzwon: %s | Powód: %s",
            listing.source,
            listing.lot_id,
            listing.url,
            analysis.identified_color,
            analysis.color_approved,
            mods_info,
            analysis.airbags_deployed,
            analysis.structural_or_beam_damage,
            analysis.rejection_reason or analysis.damage_assessment,
        )
