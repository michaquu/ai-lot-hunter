import logging
from typing import Optional
import requests

from analyzer import VisionAnalysisResult
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from scraper import VehicleListing

logger = logging.getLogger(__name__)


def _discover_chat_id_from_updates(bot_token: str) -> Optional[str]:
    """
    Query Telegram getUpdates API to automatically find the chat_id of the user
    who most recently messaged the bot (e.g., sent /start).
    """
    try:
        url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
        resp = requests.get(url, timeout=10)
        if not resp.ok:
            return None
        data = resp.json()
        results = data.get("result", [])
        for update in reversed(results):
            for key in ("message", "edited_message", "my_chat_member", "channel_post"):
                msg = update.get(key)
                if isinstance(msg, dict) and "chat" in msg and "id" in msg["chat"]:
                    discovered = str(msg["chat"]["id"])
                    logger.info(
                        "[Telegram] Automatycznie wykryto prawidłowe TELEGRAM_CHAT_ID z getUpdates: %s",
                        discovered,
                    )
                    return discovered
    except Exception as exc:
        logger.debug("[Telegram] Nie udało się pobrać getUpdates: %s", exc)
    return None


def send_telegram_alert(listing: VehicleListing, analysis: VisionAnalysisResult) -> bool:
    """
    Send a Telegram message when a vehicle passes inspection.
    If TELEGRAM_CHAT_ID is invalid or returns 'chat not found', automatically
    queries /getUpdates to find the user's active chat with the bot.
    """
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_telegram_bot_token_here":
        logger.info(
            "[Telegram] Pominięto wysyłkę na Telegram (brak TELEGRAM_BOT_TOKEN) — auto zapisane w logach."
        )
        return False

    mods_line = (
        f"🔥 Przeróbki / Tuning: TAK ({analysis.modifications_detected})\n"
        if analysis.is_modified
        else "Przeróbki / Tuning: Brak (seria)\n"
    )

    message = (
        f"✅ DODGE CHALLENGER MATCH ({listing.source})\n\n"
        f"Title: {listing.title}\n"
        f"Lot ID: {listing.lot_id}\n"
        f"Identified Color: {analysis.identified_color}\n"
        f"{mods_line}"
        f"Damage Assessment: {analysis.damage_assessment}\n\n"
        f"🔗 Link: {listing.url}"
    )

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chat_id = (
        TELEGRAM_CHAT_ID
        if (TELEGRAM_CHAT_ID and TELEGRAM_CHAT_ID != "your_telegram_chat_id_here")
        else _discover_chat_id_from_updates(TELEGRAM_BOT_TOKEN)
    )

    if not chat_id:
        logger.error(
            "[Telegram] Brak TELEGRAM_CHAT_ID oraz brak wiadomości w getUpdates! "
            "Wejdź na Telegramie w rozmowę ze swoim botem, kliknij START (wyślij mu np. 'hej') i uruchom ponownie."
        )
        return False

    payload = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": False,
    }

    try:
        response = requests.post(api_url, json=payload, timeout=10)
        if not response.ok and "chat not found" in response.text.lower():
            logger.warning(
                "[Telegram] Podane TELEGRAM_CHAT_ID (%s) zwróciło 'chat not found'. "
                "Próbuję automatycznie wykryć Twoje ID czatu z getUpdates...",
                chat_id,
            )
            discovered_id = _discover_chat_id_from_updates(TELEGRAM_BOT_TOKEN)
            if discovered_id and discovered_id != str(chat_id):
                payload["chat_id"] = discovered_id
                response = requests.post(api_url, json=payload, timeout=10)

        if not response.ok:
            logger.error(
                "[Telegram] Błąd wysyłania powiadomienia (%s): %s -> "
                "WAŻNE: Otwórz swojego bota w aplikacji Telegram, kliknij przycisk START (wyślij mu dowolną wiadomość np. 'start') "
                "i sprawdź czy TELEGRAM_CHAT_ID to Twój numer ID użytkownika (np. z @userinfobot).",
                response.status_code,
                response.text,
            )
            return False

        logger.info(
            "📨 [Telegram] Wysłano powiadomienie dla %s Lot #%s (%s)",
            listing.source,
            listing.lot_id,
            listing.url,
        )
        return True
    except Exception as exc:
        logger.error("[Telegram] Błąd połączenia z Telegram API: %s", exc)
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
