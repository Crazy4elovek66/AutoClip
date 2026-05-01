import os
import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import Tuple
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from mistralai.client import Mistral
import re
from aiogram.types import BufferedInputFile

# Настройка логгера
logger = logging.getLogger("ChannelManager")


class ChannelManager:
    def __init__(self, bot: Bot, channel_id: str, mistral_api_key: str, referral_link: str):
        self.bot = bot
        self.channel_id = channel_id
        self.referral_link = referral_link
        self.scheduler = AsyncIOScheduler()
        self.client = Mistral(api_key=mistral_api_key)
        self.is_scheduler_running = False
        self.assets_dir = "assets"  # Папка с картинками
        self.promocodes = [
        "twitchcutt",
    ]  # Ваш список промокодов

        # Конфигурация контента
        self.topics = [
            "стратегии ставок на футбол",
            "разбор новых слотов в казино",
            "анализ коэффициентов live-ставок",
            "истории крупных выигрышей",
            "обзор кешбэк программ",
            "промокоды и акции",
            "психология успешного беттинга",
            "разбор ошибок новичков",
        ]

        self.bonuses = [
            "500% на первый депозит",
            "200% кэшбэк за неделю",
            "фрибет 1500₽",
            "экстра 75 фриспинов",
            "дополнительные 100% к депозиту",
        ]

    def get_random_asset(self) -> str:
        """Получает случайный файл из папки assets"""
        if not os.path.exists(self.assets_dir):
            os.makedirs(self.assets_dir, exist_ok=True)
            logger.warning(f"Папка {self.assets_dir} не существует, создана пустая")
            return None

        files = [f for f in os.listdir(self.assets_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        if not files:
            logger.warning(f"В папке {self.assets_dir} нет подходящих изображений")
            return None

        return os.path.join(self.assets_dir, random.choice(files))

    @staticmethod
    def escape_markdown(text: str) -> str:
        """Экранирование специальных символов для MarkdownV2 с сохранением форматирования"""
        # Символы, которые нужно экранировать (кроме используемых в форматировании)
        escape_chars = r'[]()>#+-={}.!'
        
        # Экранируем только нужные символы
        for char in escape_chars:
            text = text.replace(char, f'\\{char}')
        
        return text

    async def check_bot_permissions(self) -> bool:
        """Проверка прав бота с подробным логированием"""
        try:
            # Проверяем что канал существует
            chat = await self.bot.get_chat(self.channel_id)

            # Получаем информацию о боте
            me = await self.bot.get_me()

            # Получаем список администраторов
            admins = await self.bot.get_chat_administrators(self.channel_id)

            # Проверяем права
            is_admin = any(admin.user.id == me.id for admin in admins)

            if not is_admin:
                logger.error(f"Бот не является администратором канала {self.channel_id}")
                return False

            logger.info(f"Права бота в канале {self.channel_id} подтверждены")
            return True

        except Exception as e:
            logger.error(f"Ошибка проверки прав: {str(e)}")
            return False

    async def generate_post(self) -> Tuple[str, str]:
        """Генерация поста с Markdown-разметкой и текстом кнопки"""
        topic = random.choice(self.topics)
        promocode = random.choice(self.promocodes)  # Выбираем случайный промокод
        
        prompt = f"""Создай пост для Telegram канала о ставках и казино. Тема: {topic}.
    Требования:
    1. Используй промокод: {promocode}
    2. Конкретная полезная информация (не просто "узнайте")
    3. Длина 3-5 предложений
    4. Практические примеры
    5. Используй эмодзи для структуры
    6. Используй Markdown разметку: **жирный**, __курсив__, `моноширинный`, ~~перечеркнутый~~, ```код```, ||скрытый текст||
    7. В конце укажи, что промокод {promocode} дает особые бонусы
    8. Не упоминай другие проекты кроме 1win"""
        
        try:
            response = await self.client.chat.complete_async(
                model="mistral-large-latest",
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.choices[0].message.content

            # Генерация текста кнопки с промокодом
            button_templates = [
                f"🎰 Активировать {promocode}",
                f"💰 Получить бонус по коду {promocode}",
                f"🔥 {promocode} - экстра-кешбэк",
                f"💎 Промокод {promocode}",
                f"🚀 Использовать {promocode}"
            ]
            button_text = random.choice(button_templates)

            return content, button_text
        except Exception as e:
            logger.error(f"Ошибка генерации поста: {e}")
            return await self._generate_backup_post(promocode)

    async def _generate_backup_post(self, promocode: str) -> Tuple[str, str]:
        """Резервный генератор с промокодом"""
        topic = random.choice(self.topics)
        
        templates = [
            (f"📊 **{topic}**: ключевые моменты\n"
            f"1. Используйте промокод `{promocode}` для особых бонусов\n"
            "2. В live-ставках обращайте внимание на замены\n"
            "3. Пример: при удалении игрока коэффициенты растут на __10-15%__\n\n"
            f"🎁 Промокод {promocode} дает +500% к первому депозиту!"),
            
            (f"🔍 __{topic}__ - разбор стратегии:\n"
            f"• Активируйте промокод ||{promocode}|| для бонусов\n"
            "• Начинайте с малых ставок (`1-2%` от банка)\n"
            "• В теннисе обращайте внимание на статистику подач\n\n"
            f"💎 Промокод {promocode} работает ограниченное время!")
        ]
        
        button_texts = [
            f"🎰 Активировать {promocode}",
            f"💰 Получить бонус по коду {promocode}",
            f"🔥 {promocode} - экстра-кешбэк"
        ]
        
        return random.choice(templates), random.choice(button_texts)

    async def send_post(self) -> bool:
        """Отправка поста в канал с кнопкой и случайной картинкой"""
        try:
            if not await self.check_bot_permissions():
                logger.error("Бот не имеет прав на публикацию")
                return False

            post_content, button_text = await self.generate_post()
            asset_path = self.get_random_asset()
            
            # Экранируем контент поста (сохраняя форматирование)
            escaped_content = self.escape_markdown(post_content)
            
            # Создаем inline-клавиатуру с кнопкой
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=button_text, url=self.referral_link)]
            ])

            if asset_path:
                # Отправляем пост с картинкой
                with open(asset_path, 'rb') as photo:
                    # Используем BufferedInputFile для создания InputFile
                    input_file = BufferedInputFile(photo.read(), filename=os.path.basename(asset_path))
                    await self.bot.send_photo(
                        chat_id=self.channel_id,
                        photo=input_file,
                        caption=escaped_content,
                        parse_mode="MarkdownV2",
                        reply_markup=keyboard
                    )
            else:
                # Отправляем пост без картинки, если нет доступных
                await self.bot.send_message(
                    chat_id=self.channel_id,
                    text=escaped_content,
                    parse_mode="MarkdownV2",
                    disable_web_page_preview=True,
                    reply_markup=keyboard
                )

            logger.info(f"Пост успешно отправлен в {datetime.now()}")
            return True
        except Exception as e:
            logger.error(f"Ошибка отправки поста: {e}")
            return False

    def schedule_posts(self):
        """Настройка расписания постов"""
        if self.is_scheduler_running:
            logger.warning("Планировщик уже запущен")
            return

        # Очищаем все существующие задания
        self.scheduler.remove_all_jobs()

        # Основные посты в разное время дня
        post_times = [
            {"hour": 10, "minute": 15, "id": "morning_post"},
            {"hour": 15, "minute": 30, "id": "afternoon_post"},
            {"hour": 20, "minute": 45, "id": "evening_post"},
        ]

        for time_slot in post_times:
            self.scheduler.add_job(
                self.send_post,
                "cron",
                hour=time_slot["hour"],
                minute=time_slot["minute"],
                id=time_slot["id"],
            )

        # Случайные дополнительные посты (2 в день)
        for i in range(2):
            hour = random.randint(11, 22)
            minute = random.randint(0, 59)
            self.scheduler.add_job(
                self.send_post,
                "cron",
                hour=hour,
                minute=minute,
                id=f"random_post_{i}",
            )

        self.scheduler.start()
        self.is_scheduler_running = True
        logger.info("Планировщик постов запущен")

    def stop_scheduler(self):
        """Остановка планировщика"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            self.is_scheduler_running = False
            logger.info("Планировщик постов остановлен")
