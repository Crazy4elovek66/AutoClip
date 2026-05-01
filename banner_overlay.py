import os
import cv2
import numpy as np
import subprocess
from dotenv import load_dotenv
from typing import Union, Optional, Tuple
import logging

# Настройка логгера
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BannerOverlay")


class BannerOverlay:
    def __init__(self):
        load_dotenv()
        self.enabled = os.getenv("BANNER_ENABLED", "false").lower() == "true"
        self.banner_path = os.getenv("BANNER_PATH", "")
        self.banner_type = os.getenv("BANNER_TYPE", "image")  # image/gif/video
        self.position = os.getenv(
            "BANNER_POSITION", "top_right"
        )  # top_left/top_right/bottom_center
        self.scale = float(
            os.getenv("BANNER_SCALE", "0.15")
        )  # Относительный размер (0-1)
        self.opacity = float(os.getenv("BANNER_OPACITY", "0.7"))  # Прозрачность (0-1)

        # Проверка доступности файла
        if self.enabled and not os.path.exists(self.banner_path):
            logger.warning(f"Banner file not found: {self.banner_path}")
            self.enabled = False

    def _calculate_position(
        self, frame_width: int, frame_height: int, banner_width: int, banner_height: int
    ) -> Tuple[int, int]:
        """Вычисляет позицию для баннера на основе настроек"""
        if self.position == "top_left":
            x = int(frame_width * 0.05)  # 5% от ширины слева
            y = int(frame_height * 0.35)  # 35% от высоты (под областью лица)
        elif self.position == "top_right":
            x = int(frame_width * 0.95 - banner_width)  # 5% от ширины справа
            y = int(frame_height * 0.35)  # 35% от высоты
        elif self.position == "bottom_center":
            x = int((frame_width - banner_width) / 2)  # По центру горизонтали
            y = int(frame_height * 0.75)  # 75% от высоты (центр нижней области)
        else:
            x, y = 0, 0

        return max(0, x), max(0, y)

    def _process_banner(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """Обрабатывает баннер для наложения"""
        try:
            if self.banner_type == "image":
                banner = cv2.imread(self.banner_path, cv2.IMREAD_UNCHANGED)
            elif self.banner_type == "gif":
                cap = cv2.VideoCapture(self.banner_path)
                ret, banner = cap.read()
                cap.release()
                if not ret:
                    return None
            else:  # video
                cap = cv2.VideoCapture(self.banner_path)
                ret, banner = cap.read()
                cap.release()
                if not ret:
                    return None

            # Масштабирование
            target_width = int(frame.shape[1] * self.scale)
            if banner.shape[3] == 4:  # Если есть альфа-канал
                h, w = banner.shape[:2]
                aspect = w / h
                banner = cv2.resize(banner, (target_width, int(target_width / aspect)))
            else:
                h, w = banner.shape[:2]
                aspect = w / h
                banner = cv2.resize(banner, (target_width, int(target_width / aspect)))

            return banner
        except Exception as e:
            logger.error(f"Error processing banner: {e}")
            return None

    def apply_to_frame(self, frame: np.ndarray) -> np.ndarray:
        """Накладывает баннер на кадр"""
        if not self.enabled:
            return frame

        banner = self._process_banner(frame)
        if banner is None:
            return frame

        # Вычисляем позицию
        x, y = self._calculate_position(
            frame.shape[1], frame.shape[0], banner.shape[1], banner.shape[0]
        )

        # Наложение с учетом прозрачности
        if banner.shape[2] == 4:  # Если есть альфа-канал
            alpha = banner[:, :, 3] / 255.0 * self.opacity
            for c in range(3):
                frame[y : y + banner.shape[0], x : x + banner.shape[1], c] = (
                    frame[y : y + banner.shape[0], x : x + banner.shape[1], c]
                    * (1 - alpha)
                    + banner[:, :, c] * alpha
                )
        else:
            overlay = cv2.addWeighted(
                frame[y : y + banner.shape[0], x : x + banner.shape[1]],
                1 - self.opacity,
                banner,
                self.opacity,
                0,
            )
            frame[y : y + banner.shape[0], x : x + banner.shape[1]] = overlay

        return frame

    def apply_to_video(self, input_path: str, output_path: str) -> bool:
        """Обрабатывает видео с наложением баннера"""
        if not self.enabled:
            return False

        try:
            # Создаем временный файл
            temp_path = output_path + ".temp.mp4"

            # Команда FFmpeg для обработки
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                input_path,
                "-vf",
                f"movie={self.banner_path},scale=iw*{self.scale}:-1[watermark];[in][watermark]overlay",
                "-c:a",
                "copy",
                temp_path,
            ]

            subprocess.run(cmd, check=True)

            # Перемещаем временный файл в выходной
            os.replace(temp_path, output_path)
            return True
        except Exception as e:
            logger.error(f"Error applying banner to video: {e}")
            return False
