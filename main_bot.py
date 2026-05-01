# main_bot.py
import asyncio
import logging
import os
from dotenv import load_dotenv
from telegram_notifier import TelegramNotifier
from twitch_fetcher import TwitchClipFetcher
from video_processor import process_clip_to_vertical
from youtube_uploader import upload_to_youtube
from models import PendingClip
from dataclasses import dataclass
from typing import Optional
import json
import time
import tensorflow as tf
from aiogram import types
from aiogram.types import BufferedInputFile, Message, CallbackQuery
from channel_manager import ChannelManager
from datetime import datetime, timedelta


os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
os.environ["NO_ALBUMENTATIONS_UPDATE"] = "1"
load_dotenv()

tf.get_logger().setLevel("ERROR")
# Настройка логгера
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MainBot")


class BotState:
    def __init__(self):
        self.is_running = False
        self._wakeup_event = asyncio.Event()
        self.sleep_task = None
        self.pending_clip = None
        self.waiting_approval = False
        self.current_status = "stopped"
        self.channel_manager = None

    async def sleep(self, seconds: float):
        self._wakeup_event.clear()
        try:
            await asyncio.wait_for(self._wakeup_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    def wakeup(self):
        self._wakeup_event.set()


bot_state = BotState()

CLIPS_JSON = "clips.json"
OUTPUT_DIR = "processed_clips"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Загрузка сохраненного состояния
if os.path.exists(CLIPS_JSON):
    try:
        with open(CLIPS_JSON, "r") as f:
            data = json.load(f)
            processed_ids = set(data.get("processed_ids", []))

            if data.get("pending_clip"):
                bot_state.pending_clip = PendingClip(
                    file_path=data["pending_clip"]["file_path"],
                    clip_data=data["pending_clip"]["clip_data"],
                    processed_path=data["pending_clip"]["processed_path"],
                )
                bot_state.waiting_approval = data.get("waiting_approval", False)

                if bot_state.waiting_approval:
                    logger.info(
                        f"Восстановлен клип на проверке: {bot_state.pending_clip.clip_data['title']}"
                    )
    except Exception as e:
        logger.error(f"Ошибка загрузки состояния: {e}")
        processed_ids = set()
        bot_state.pending_clip = None
        bot_state.waiting_approval = False
else:
    processed_ids = set()

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID"))
KEEP_FILES = os.getenv("KEEP_FILES", "True").lower() == "true"
REFERRAL_LINK = os.getenv("REFERRAL_LINK")
tg = TelegramNotifier(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)
twitch = TwitchClipFetcher()


def save_processed():
    data = {
        "processed_ids": list(processed_ids),
        "pending_clip": (
            bot_state.pending_clip.to_dict() if bot_state.pending_clip else None
        ),
        "waiting_approval": bot_state.waiting_approval,
        "current_status": bot_state.current_status,
    }

    try:
        with open(CLIPS_JSON, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения состояния: {e}")


async def initialize_channel_manager():
    """Инициализация менеджера канала с проверкой ошибок"""
    try:
        mistral_api_key = os.getenv("MISTRAL_API_KEY")
        channel_id = os.getenv("CHANNEL_ID")
        referral_link = os.getenv("REFERRAL_LINK")

        if not all([mistral_api_key, channel_id, referral_link]):
            missing = []
            if not mistral_api_key: missing.append("MISTRAL_API_KEY")
            if not channel_id: missing.append("CHANNEL_ID")
            if not referral_link: missing.append("REFERRAL_LINK")
            logger.warning(f"Отсутствуют обязательные переменные: {', '.join(missing)}")
            return False

        bot_state.channel_manager = ChannelManager(
            bot=tg.bot, 
            channel_id=channel_id, 
            mistral_api_key=mistral_api_key,
            referral_link=referral_link
        )

        # Проверяем подключение
        if not await bot_state.channel_manager.check_bot_permissions():
            logger.error("Бот не имеет прав на публикацию в канале")
            return False

        logger.info("Менеджер канала успешно инициализирован")
        return True

    except Exception as e:
        logger.error(f"Ошибка инициализации менеджера канала: {e}", exc_info=True)
        return False


async def process_approved_clip(pending_clip: PendingClip):
    try:
        if os.getenv("UPLOAD_VID", "True").lower() == "true":
            yt_url = upload_to_youtube(
                pending_clip.processed_path, pending_clip.clip_data["title"]
            )
            processed_ids.add(pending_clip.clip_data["id"])
            save_processed()
            await tg.send_message(
                f"✅ Видео загружено на YouTube:\n{yt_url}\n"
                f"🔔 Закрепленный комментарий с ссылкой на Telegram добавлен"
            )
        else:
            await tg.send_message(
                "✅ Видео одобрено (режим тестирования - загрузка отключена)"
            )
            processed_ids.add(pending_clip.clip_data["id"])
            save_processed()

        if not os.getenv("KEEP_FILES", "True").lower() == "true":
            for path in [pending_clip.file_path, pending_clip.processed_path]:
                try:
                    if path and os.path.exists(path):
                        os.remove(path)
                except Exception as e:
                    logger.warning(f"Не удалось удалить файл {path}: {e}")

    except Exception as e:
        logger.error(f"Ошибка загрузки на YouTube: {e}")
        await tg.send_message("❌ Не удалось загрузить видео на YouTube. Подробности записаны в журнал.")


async def process_rejected_clip(pending_clip: PendingClip):
    try:
        clip_id = pending_clip.clip_data["id"]
        processed_ids.add(clip_id)

        if not os.getenv("KEEP_FILES", "True").lower() == "true":
            for path in [pending_clip.file_path, pending_clip.processed_path]:
                try:
                    if path and os.path.exists(path):
                        os.remove(path)
                        logger.info(f"Удален файл: {path}")
                    else:
                        logger.warning(f"Файл не найден, не удален: {path}")
                except Exception as e:
                    logger.error(f"Ошибка удаления файла {path}: {e}")

        bot_state.pending_clip = None
        bot_state.waiting_approval = False
        bot_state.current_status = "processing"
        save_processed()

        await tg.send_message(
            "❌ Клип отклонен. Ищу следующий клип...", keyboard_type="main"
        )

        if not bot_state.is_running:
            logger.info("Перезапуск основного цикла обработки...")
            bot_state.is_running = True
            bot_state.sleep_task = asyncio.create_task(main_loop())

        bot_state.wakeup()
        await asyncio.sleep(0.1)
        bot_state.wakeup()

    except Exception as e:
        logger.error("Критическая ошибка при отклонении клипа", exc_info=True)
        await tg.send_message(
            "⚠️ Системная ошибка: не удалось отклонить клип. Подробности записаны в журнал.",
            keyboard_type="main",
        )
        raise


async def process_cycle():
    logger.info("Запуск цикла обработки клипов...")
    bot_state.current_status = "processing"
    save_processed()

    try:
        if bot_state.pending_clip and bot_state.waiting_approval:
            logger.info(
                f"Обнаружен клип в состоянии ожидания: {bot_state.pending_clip.clip_data['title']}"
            )
            await tg.send_message(
                f"📹 Восстановлен клип на проверке:\n{bot_state.pending_clip.clip_data['title']}",
                keyboard_type="approval",
            )

            with open(bot_state.pending_clip.processed_path, "rb") as video_file:
                await tg.bot.send_video(
                    chat_id=tg.chat_id,
                    video=BufferedInputFile(video_file.read(), filename="preview.mp4"),
                    caption="Оцените восстановленный клип:",
                    reply_markup=tg._create_inline_approval_keyboard(),
                )
            return True

        clips = twitch.fetch_top_clips()
        new_clips = [clip for clip in clips if clip["id"] not in processed_ids]

        if not new_clips:
            await tg.send_message("❗️Новых клипов не найдено")
            bot_state.current_status = "sleeping"
            save_processed()
            return False

        for clip in new_clips:
            filepath = None
            outpath = None
            try:
                filepath = twitch.download_clip(clip)
                outpath = await asyncio.to_thread(
                    process_clip_to_vertical, filepath, OUTPUT_DIR
                )

                bot_state.pending_clip = PendingClip(
                    file_path=filepath, clip_data=clip, processed_path=outpath
                )
                bot_state.waiting_approval = True
                bot_state.current_status = "waiting_approval"
                save_processed()

                sent_for_approval = await tg.send_video_for_approval(
                    file_path=outpath, caption=f"📹 {clip['title']}\nОцените клип:"
                )

                if not sent_for_approval:
                    raise RuntimeError("Не удалось отправить клип на проверку в Telegram")

                bot_state.pending_clip.sent_for_approval = True
                save_processed()

                return True

            except Exception as e:
                logger.error(f"Ошибка при обработке клипа {clip['id']}: {e}")
                processed_ids.add(clip["id"])
                save_processed()

                if not os.getenv("KEEP_FILES", "True").lower() == "true":
                    for path in [filepath, outpath]:
                        try:
                            if path and os.path.exists(path):
                                os.remove(path)
                        except Exception as clean_err:
                            logger.warning(
                                f"Не удалось удалить файл {path}: {clean_err}"
                            )
                continue

        return False
    except Exception as e:
        logger.error(f"Критическая ошибка в process_cycle: {e}")
        await tg.send_message("⚠️ Системная ошибка: не удалось завершить цикл обработки клипов.")
        raise
    finally:
        if not bot_state.waiting_approval:
            bot_state.current_status = "sleeping"
            save_processed()


async def resend_pending_clip_for_approval():
    if not (bot_state.pending_clip and bot_state.waiting_approval):
        return False

    processed_path = bot_state.pending_clip.processed_path
    if not processed_path or not os.path.exists(processed_path):
        await tg.send_message("⚠️ Клип на проверке не найден на диске. Запустите поиск заново.")
        bot_state.pending_clip = None
        bot_state.waiting_approval = False
        bot_state.current_status = "stopped"
        save_processed()
        return False

    sent = await tg.send_video_for_approval(
        file_path=processed_path,
        caption=f"📹 Восстановленный клип на проверке:\n{bot_state.pending_clip.clip_data['title']}",
    )
    if sent:
        bot_state.pending_clip.sent_for_approval = True
        bot_state.current_status = "waiting_approval"
        save_processed()
    return sent


async def main_loop():
    while bot_state.is_running:
        try:
            if not bot_state.waiting_approval:
                processed = await process_cycle()
                if not processed:
                    sleep_time = int(os.getenv("SLEEP_TIMER", 3600))
                    bot_state.current_status = "sleeping"
                    save_processed()
                    await tg.send_message(
                        f"⏳ Бот засыпает на {sleep_time//3600} часов..."
                    )
                    await bot_state.sleep(sleep_time)
            else:
                await bot_state.sleep(10)

        except asyncio.CancelledError:
            continue
        except Exception as e:
            logger.error(f"Ошибка в основном цикле: {e}")
            bot_state.waiting_approval = False
            save_processed()
            await tg.send_message("⚠️ Системная ошибка: основной цикл временно остановлен.")
            await bot_state.sleep(60)


async def handle_callback(callback: CallbackQuery):
    """Обработчик inline-кнопок"""
    try:
        if callback.data == "approve":
            if bot_state.waiting_approval and bot_state.pending_clip:
                bot_state.current_status = "uploading"
                await process_approved_clip(bot_state.pending_clip)
                bot_state.pending_clip = None
                bot_state.waiting_approval = False
                bot_state.current_status = "sleeping"
                bot_state.wakeup()
                await callback.answer("Видео одобрено и загружается")

        elif callback.data == "reject":
            if bot_state.waiting_approval and bot_state.pending_clip:
                await process_rejected_clip(bot_state.pending_clip)
                await callback.answer("Видео отклонено")

        elif callback.data == "reprocess":
            if bot_state.waiting_approval and bot_state.pending_clip:
                clip_data = bot_state.pending_clip.clip_data
                original_path = bot_state.pending_clip.file_path

                outpath = await asyncio.to_thread(
                    process_clip_to_vertical, original_path, OUTPUT_DIR
                )

                bot_state.pending_clip = PendingClip(
                    file_path=original_path, clip_data=clip_data, processed_path=outpath
                )

                await tg.send_video_for_approval(
                    file_path=outpath,
                    caption=f"📹 {clip_data['title']}\nПовторно обработанный клип:",
                )
                await callback.answer("Видео обрабатывается заново")

    except Exception as e:
        logger.error(f"Ошибка обработки callback: {e}")
        await callback.answer("⚠️ Произошла ошибка")


async def handle_command(cmd: str):
    logger.info(f"Получена команда: {cmd}")
    cmd = cmd.strip().lower()
    try:
        if cmd in ["/start", "start"]:
            if not bot_state.is_running:
                bot_state.is_running = True
                bot_state.current_status = "processing"
                if bot_state.sleep_task:
                    bot_state.sleep_task.cancel()
                bot_state.sleep_task = asyncio.create_task(main_loop())
                if bot_state.waiting_approval and bot_state.pending_clip:
                    await tg.send_message("🔄 Бот активирован. Возвращаю клип на проверку...")
                    await resend_pending_clip_for_approval()
                    return
                await tg.send_message("🔄 Бот активирован. Начинаю обработку клипов...")
            else:
                await tg.send_message("🔔 Бот уже работает")

        elif cmd in ["/stop", "stop"]:
            if bot_state.is_running:
                bot_state.is_running = False
                bot_state.current_status = "stopped"
                if bot_state.sleep_task:
                    bot_state.sleep_task.cancel()
                await tg.send_message("🛑 Бот остановлен")
            else:
                await tg.send_message("ℹ️ Бот уже остановлен")

        elif cmd in ["/status", "status"]:
            status_messages = {
                "stopped": "🛑 Остановлен",
                "processing": "🔄 Обрабатывает клипы",
                "waiting_approval": "⏳ Ожидает подтверждения",
                "uploading": "📤 Загружает на YouTube",
                "sleeping": "💤 Спит",
            }
            status = status_messages.get(
                bot_state.current_status, "❓ Неизвестный статус"
            )
            last_clip = list(processed_ids)[-1][:20] + "..." if processed_ids else "нет"

            keyboard_type = "approval" if bot_state.waiting_approval else "main"
            await tg.send_message(
                f"Статус: {status}\n"
                f"Последний клип: {last_clip}\n"
                f"Ожидает проверки: {'да' if bot_state.waiting_approval else 'нет'}",
                keyboard_type=keyboard_type,
            )

        elif cmd in ["✅ загрузить", "✅", "approve"]:
            if bot_state.waiting_approval and bot_state.pending_clip:
                bot_state.current_status = "uploading"
                await process_approved_clip(bot_state.pending_clip)
                bot_state.pending_clip = None
                bot_state.waiting_approval = False
                bot_state.current_status = "sleeping"
                bot_state.wakeup()

        elif cmd in ["❌ отклонить", "❌", "reject"]:
            if bot_state.waiting_approval and bot_state.pending_clip:
                await process_rejected_clip(bot_state.pending_clip)

        elif cmd in ["🔄 обработать снова", "🔄", "reprocess"]:
            if bot_state.waiting_approval and bot_state.pending_clip:
                clip_data = bot_state.pending_clip.clip_data
                original_path = bot_state.pending_clip.file_path

                outpath = await asyncio.to_thread(
                    process_clip_to_vertical, original_path, OUTPUT_DIR
                )

                bot_state.pending_clip = PendingClip(
                    file_path=original_path, clip_data=clip_data, processed_path=outpath
                )

                await tg.send_video_for_approval(
                    file_path=outpath,
                    caption=f"📹 {clip_data['title']}\nПовторно обработанный клип:",
                )

        elif cmd in ["🔄 пропустить и спать", "sleep"]:
            if bot_state.waiting_approval:
                bot_state.pending_clip = None
                bot_state.waiting_approval = False
                bot_state.current_status = "sleeping"
                await tg.send_message("⏳ Перехожу в режим ожидания...")
                await bot_state.sleep(int(os.getenv("SLEEP_TIMER", 3600)))

        elif cmd in ["/post_now", "post_now"]:
            try:
                if not bot_state.channel_manager:
                    await tg.send_message("🔄 Попытка инициализации менеджера канала...")
                    success = await initialize_channel_manager()
                    if not success:
                        error_msg = ("❌ Не удалось инициализировать менеджер канала.")
                        await tg.send_message(error_msg)
                        return

                await tg.send_message("🔐 Проверка прав бота в канале...")
                if not await bot_state.channel_manager.check_bot_permissions():
                    await tg.send_message("❌ Бот не имеет прав на публикацию!")
                    return

                await tg.send_message("🔄 Генерация контента через Mistral AI...")
                post_result = await bot_state.channel_manager.send_post()

                if post_result:
                    await tg.send_message(f"✅ Пост успешно опубликован в канале!")
                else:
                    await tg.send_message("❌ Не удалось отправить пост")
            except Exception as e:
                logger.error("Критическая ошибка при ручной публикации поста", exc_info=True)
                await tg.send_message("⚠️ Системная ошибка: не удалось опубликовать пост.")

        elif cmd in ["/channel_on", "channel_on"]:
            try:
                if not bot_state.channel_manager:
                    await tg.send_message("🔄 Попытка инициализации менеджера канала...")
                    success = await initialize_channel_manager()
                    if not success:
                        error_msg = ("❌ Не удалось инициализировать менеджер канала.")
                        await tg.send_message(error_msg)
                        return

                await tg.send_message("🔐 Проверка прав бота в канале...")
                if not await bot_state.channel_manager.check_bot_permissions():
                    await tg.send_message("❌ Бот не имеет прав на публикацию!")
                    return

                bot_state.channel_manager.schedule_posts()
                await tg.send_message("📢 Автопостинг в канал включен")
            except Exception as e:
                logger.error("Критическая ошибка при включении автопостинга", exc_info=True)
                await tg.send_message("⚠️ Системная ошибка: не удалось включить автопостинг.")

        elif cmd in ["/channel_off", "channel_off"]:
            try:
                if bot_state.channel_manager:
                    bot_state.channel_manager.stop_scheduler()
                    await tg.send_message("🔇 Автопостинг в канал выключен")
                else:
                    await tg.send_message("❌ Менеджер канала не инициализирован")
            except Exception as e:
                logger.error(f"Ошибка при выключении автопостинга: {e}")
                await tg.send_message("⚠️ Системная ошибка: не удалось выключить автопостинг.")

    except Exception as e:
        logger.error(f"Ошибка обработки команды: {e}")
        await tg.send_message("⚠️ Системная ошибка: команда не выполнена. Подробности записаны в журнал.")


async def send_post(self, referral_link: str):
    """Отправка поста в канал"""
    try:
        if not self.channel_id:
            logging.error("Идентификатор канала не установлен")
            return False

        post = await self.generate_post(referral_link)
        await self.bot.send_message(chat_id=self.channel_id, text=post)
        logging.info(f"Пост отправлен в {datetime.now()}")
        return True
    except Exception as e:
        logging.error(f"Ошибка отправки поста: {e}")
        return False


async def start_bot_handlers():
    """Запускает обработчики бота"""

    @tg.router.callback_query()
    async def callback_handler(callback: CallbackQuery):
        await handle_callback(callback)

    @tg.router.message()
    async def message_handler(msg: Message):
        if msg.chat.id == tg.chat_id:
            command = msg.text
            await handle_command(command)
        else:
            await msg.answer(
                "❌ Недопустимый пользователь", reply_markup=tg.main_keyboard
            )


async def main():
    load_dotenv()
    tg.set_handlers(handle_command, handle_callback)
    await initialize_channel_manager()
    await tg.start_bot()
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    finally:
        # Остановка всех процессов
        if bot_state.channel_manager:
            bot_state.channel_manager.stop_scheduler()
        bot_state.is_running = False
        if bot_state.sleep_task:
            bot_state.sleep_task.cancel()
        await tg.send_message("🔴 Бот завершил работу")


if __name__ == "__main__":
    asyncio.run(main())
