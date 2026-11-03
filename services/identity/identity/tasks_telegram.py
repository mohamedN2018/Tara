"""Bot replies run on a worker, so the webhook answers Telegram at once."""

from __future__ import annotations

from celery import shared_task

from .telegram import TelegramError, bot_api


@shared_task(
    name="identity.telegram_send_message",
    autoretry_for=(TelegramError,),
    retry_backoff=5,
    retry_backoff_max=120,
    max_retries=3,
    ignore_result=True,
)
def send_telegram_message(chat_id: str, text: str, reply_markup: dict | None = None) -> None:
    payload: dict = {"chat_id": chat_id, "text": text}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    bot_api("sendMessage", payload)
