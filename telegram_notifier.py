from aiogram import Bot, Dispatcher, types
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    BufferedInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router
import logging

logger = logging.getLogger("TelegramNotifier")


class TelegramNotifier:
    def __init__(self, token, chat_id, command_handler=None, callback_handler=None):
        self.token = token
        self.chat_id = chat_id
        self.command_handler = command_handler
        self.callback_handler = callback_handler
        self.bot = Bot(token=self.token)
        self.router = Router()
        self.dp = Dispatcher(storage=MemoryStorage())
        self.dp.include_router(self.router)
        self.waiting_approval = False

        # Инициализация клавиатур
        self.main_keyboard = self._create_main_keyboard()
        self.approval_keyboard = self._create_approval_keyboard()

    def set_handlers(self, command_handler, callback_handler):
        self.command_handler = command_handler
        self.callback_handler = callback_handler

    def _create_main_keyboard(self):
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="/start"), KeyboardButton(text="/stop")],
                [KeyboardButton(text="/status"), KeyboardButton(text="/post_now")],
                [
                    KeyboardButton(text="/channel_on"),
                    KeyboardButton(text="/channel_off"),
                ],
            ],
            resize_keyboard=True,
        )

    def _create_approval_keyboard(self):
        return ReplyKeyboardMarkup(
            keyboard=[
                [
                    KeyboardButton(text="✅ Загрузить"),
                    KeyboardButton(text="❌ Отклонить"),
                ],
                [KeyboardButton(text="🔄 Обработать снова")],
            ],
            resize_keyboard=True,
        )

    def _create_inline_approval_keyboard(self):
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Загрузить", callback_data="approve"),
                    InlineKeyboardButton(text="❌ Отклонить", callback_data="reject"),
                    InlineKeyboardButton(
                        text="🔄 Обработать снова", callback_data="reprocess"
                    ),
                ]
            ]
        )

    async def send_message(self, text, keyboard_type="main"):
        reply_markup = {
            "main": self.main_keyboard,
            "approval": self.approval_keyboard,
            "remove": ReplyKeyboardRemove(),
        }.get(keyboard_type, self.main_keyboard)

        await self.bot.send_message(
            chat_id=self.chat_id, text=text, reply_markup=reply_markup
        )

    async def send_video_for_approval(self, file_path, caption):
        try:
            with open(file_path, "rb") as video_file:
                await self.bot.send_video(
                    chat_id=self.chat_id,
                    video=BufferedInputFile(video_file.read(), filename="preview.mp4"),
                    caption=caption,
                    reply_markup=self._create_inline_approval_keyboard(),
                )
            self.waiting_approval = True
            return True
        except Exception as e:
            logging.error(f"Ошибка отправки видео: {e}")
            return False

    async def start_bot(self):
        """Запускает бота и обработчики сообщений"""

        @self.router.message()
        async def message_handler(msg: Message):
            if msg.chat.id == self.chat_id:
                if not self.command_handler:
                    logger.error("Обработчик команд Telegram не зарегистрирован")
                    await msg.answer("⚠️ Бот запущен не полностью. Перезапустите сервис.")
                    return
                await self.command_handler(msg.text)
            else:
                await msg.answer("❌ Недопустимый пользователь")

        @self.router.callback_query()
        async def callback_handler(callback: types.CallbackQuery):
            if not self.callback_handler:
                logger.error("Обработчик inline-кнопок Telegram не зарегистрирован")
                await callback.answer("⚠️ Бот запущен не полностью")
                return
            await self.callback_handler(callback)

        await self.dp.start_polling(self.bot)
