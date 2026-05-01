import os
import cv2
import numpy as np
import subprocess
import uuid
import mediapipe as mp
import logging
import shutil
from dotenv import load_dotenv

try:
    from insightface.app import FaceAnalysis
except ImportError:
    FaceAnalysis = None

# Загрузка переменных окружения
load_dotenv()

# Инициализация детекторов лиц
mp_face_detection = mp.solutions.face_detection
face_detector = mp_face_detection.FaceDetection(
    model_selection=1, min_detection_confidence=0.3
)

# Настройка логгера
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("VideoProcessor")

# Параметры вертикального видео
VERTICAL_WIDTH = 1080
VERTICAL_HEIGHT = 1920
TOP_PART_RATIO = 0.3  # 30% для лица
BOTTOM_PART_RATIO = 0.7  # 70% для геймплея

# Настройки баннера из .env
BANNER_ENABLED = os.getenv("BANNER_ENABLED", "false").lower() == "true"
BANNER_PATH = os.getenv("BANNER_PATH", "")
BANNER_TYPE = os.getenv("BANNER_TYPE", "image")  # image/gif/video
BANNER_POSITION = os.getenv(
    "BANNER_POSITION", "top_right"
)  # top_left/top_right/bottom_center
BANNER_SCALE = float(os.getenv("BANNER_SCALE", "0.15"))  # Относительный размер (0-1)
BANNER_OPACITY = float(os.getenv("BANNER_OPACITY", "0.7"))  # Прозрачность (0-1)


def detect_face(frame):
    """Улучшенная детекция лица с тремя уровнями fallback"""
    # 1. Пробуем InsightFace
    try:
        if FaceAnalysis is None:
            raise ImportError("InsightFace не установлен")

        face_app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        face_app.prepare(ctx_id=0, det_size=(320, 320))
        faces = face_app.get(frame)

        if faces:
            largest = max(
                faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])
            )
            x1, y1, x2, y2 = map(int, largest.bbox)
            if x2 > x1 and y2 > y1:  # Проверка валидности
                return x1, y1, x2 - x1, y2 - y1
    except Exception as e:
        pass

    # 2. Пробуем MediaPipe
    with mp_face_detection.FaceDetection(min_detection_confidence=0.5) as detector:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = detector.process(rgb)
        if results.detections:
            best = max(
                results.detections,
                key=lambda d: d.location_data.relative_bounding_box.width
                * d.location_data.relative_bounding_box.height,
            )
            bbox = best.location_data.relative_bounding_box
            return (
                int(bbox.xmin * frame.shape[1]),
                int(bbox.ymin * frame.shape[0]),
                int(bbox.width * frame.shape[1]),
                int(bbox.height * frame.shape[0]),
            )

    # 3. Пробуем OpenCV DNN
    net = cv2.dnn.readNetFromCaffe(
        "deploy.prototxt", "res10_300x300_ssd_iter_140000.caffemodel"
    )
    blob = cv2.dnn.blobFromImage(
        cv2.resize(frame, (300, 300)), 1.0, (300, 300), (104.0, 177.0, 123.0)
    )
    net.setInput(blob)
    detections = net.forward()
    for i in range(detections.shape[2]):
        if detections[0, 0, i, 2] > 0.5:
            box = detections[0, 0, i, 3:7] * np.array(
                [frame.shape[1], frame.shape[0], frame.shape[1], frame.shape[0]]
            )
            return (
                box.astype("int")[0],
                box.astype("int")[1],
                box.astype("int")[2] - box.astype("int")[0],
                box.astype("int")[3] - box.astype("int")[1],
            )
    return None


def calculate_regions(frame, green_area_width=400):
    """Вычисление областей с поиском лица только в краевых зонах"""
    h, w = frame.shape[:2]

    # Размеры зоны, где НЕ ищем лица (центральная часть)
    exclude_zone_width = int(w * 0.6)  # 40% ширины
    exclude_zone_height = int(h * 0.6)  # 40% высоты
    exclude_x = (w - exclude_zone_width) // 2
    exclude_y = (h - exclude_zone_height) // 2

    # Автоматический расчет высоты для соотношения 16:9
    green_area_height = int(green_area_width * 9 / 16)

    # Создаем маску для краевых зон
    mask = np.ones(frame.shape[:2], dtype=np.uint8) * 255
    cv2.rectangle(
        mask,
        (exclude_x, exclude_y),
        (exclude_x + exclude_zone_width, exclude_y + exclude_zone_height),
        0,
        -1,
    )

    # Детекция лица только в краевых зонах (3 попытки)
    face_rect = None
    for attempt in range(3):
        try:
            modified_frame = frame.copy()
            if attempt == 1:
                modified_frame = cv2.convertScaleAbs(modified_frame, alpha=1.2, beta=10)
            elif attempt == 2:
                modified_frame = cv2.rotate(modified_frame, cv2.ROTATE_90_CLOCKWISE)

            # Применяем маску перед детекцией
            masked_frame = cv2.bitwise_and(modified_frame, modified_frame, mask=mask)
            face_rect = detect_face(masked_frame)

            if face_rect:
                break
        except Exception as e:
            logger.warning(f"Попытка распознавания лица {attempt + 1} не удалась: {e}")

    # Если лицо найдено - возвращаем обе области
    if face_rect:
        x, y, fw, fh = face_rect
        face_center_x = x + fw // 2
        face_center_y = y + fh // 2

        # Центрируем по лицу с небольшим смещением вверх
        top_x = max(0, face_center_x - green_area_width // 2)
        top_y = max(0, face_center_y - green_area_height // 2 - int(fh * 0.2))

        # Корректировка границ
        if top_x + green_area_width > w:
            top_x = w - green_area_width
        if top_y + green_area_height > h:
            top_y = h - green_area_height

        # Нижняя область (55% ширины)
        bottom_crop_percent = 0.50
        bottom_crop_width = int(w * bottom_crop_percent)
        bottom_x = (w - bottom_crop_width) // 2
        bottom_y = 0

        return (
            (top_x, top_y, green_area_width, green_area_height),
            (bottom_x, bottom_y, bottom_crop_width, h),
        )
    else:
        # Если лицо не найдено - используем ТОЛЬКО нижнюю область (55% ширины на всю высоту)
        bottom_crop_percent = 0.55
        bottom_crop_width = int(w * bottom_crop_percent)
        bottom_x = (w - bottom_crop_width) // 2

        return None, (bottom_x, 0, bottom_crop_width, h)


def enhance_frame(frame):
    """Улучшение качества кадра перед обработкой"""
    # CLAHE для улучшения контраста
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    limg = cv2.merge((clahe.apply(l), a, b))
    enhanced = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)

    # Легкое размытие для уменьшения шума
    enhanced = cv2.GaussianBlur(enhanced, (3, 3), 0)

    # Увеличение резкости
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    enhanced = cv2.filter2D(enhanced, -1, kernel)

    return enhanced


def _apply_banner(input_path: str, output_path: str) -> bool:
    """Применяет баннер к видео с настройками из ENV"""
    if not BANNER_ENABLED or not os.path.exists(BANNER_PATH):
        return False

    try:
        # Определение размера баннера
        size_filter = ""
        if os.getenv("BANNER_WIDTH") and os.getenv("BANNER_HEIGHT"):
            size_filter = f"scale={os.getenv('BANNER_WIDTH')}:{os.getenv('BANNER_HEIGHT')}:flags=lanczos"
        else:
            size_filter = f"scale=iw*{BANNER_SCALE}:-1:flags=lanczos"

        # Определение позиции на основе настроек
        if BANNER_POSITION == "custom":
            x_pos = os.getenv("BANNER_X", "0")
            y_pos = os.getenv("BANNER_Y", "0")
        elif BANNER_POSITION == "top_left":
            x_pos = f"{os.getenv('BANNER_MARGIN_X', '5')}"
            y_pos = f"{os.getenv('BANNER_MARGIN_Y', '5')}"
        elif BANNER_POSITION == "top_right":
            x_pos = f"W-overlay_w-{os.getenv('BANNER_MARGIN_X', '5')}"
            y_pos = f"{os.getenv('BANNER_MARGIN_Y', '5')}"
        elif BANNER_POSITION == "bottom_center":
            x_pos = f"(W-overlay_w)/2"
            y_pos = f"H-overlay_h-{os.getenv('BANNER_MARGIN_Y', '5')}"
        else:  # default to top_right
            x_pos = f"W-overlay_w-{os.getenv('BANNER_MARGIN_X', '5')}"
            y_pos = f"{os.getenv('BANNER_MARGIN_Y', '5')}"

        # Поддержка формул в позиционировании (W, H, overlay_w, overlay_h)
        x_pos = x_pos.replace("W", "main_w").replace("H", "main_h")
        y_pos = y_pos.replace("W", "main_w").replace("H", "main_h")

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            input_path,
            "-i",
            BANNER_PATH,
            "-filter_complex",
            f"[1]{size_filter}[banner];"
            f"[0][banner]overlay={x_pos}:{y_pos}:format=auto:alpha=premultiplied",
            "-c:v",
            "libx264",
            "-profile:v",
            "main",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "fast",
            "-crf",
            "23",
            "-c:a",
            "copy",
            output_path,
        ]

        logger.info(f"Применение баннера через FFmpeg: {' '.join(cmd)}")
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="ignore",
            timeout=600,
        )
        return True
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg не завершил наложение баннера за 10 минут")
        return False
    except subprocess.CalledProcessError as e:
        logger.error(f"Ошибка FFmpeg при наложении баннера: {e.stderr}")
        return False
    except Exception as e:
        logger.error(f"Ошибка применения баннера: {e}")
        return False


def process_clip_to_vertical(in_path, out_dir, green_area_width=400):
    """Улучшенная функция обработки видео в вертикальный формат (9:16)"""
    OUTPUT_WIDTH = 1080
    OUTPUT_HEIGHT = 1920

    # Создаем уникальные имена файлов
    out_path = os.path.join(out_dir, f"VERT_{uuid.uuid4().hex[:8]}.mp4")
    temp_video_path = os.path.join(out_dir, f"temp_{uuid.uuid4().hex[:8]}.mp4")
    os.makedirs(out_dir, exist_ok=True)

    try:
        # Проверка FFmpeg
        if not shutil.which("ffmpeg"):
            raise Exception("FFmpeg не найден в PATH. Установите FFmpeg")

        # Получаем информацию о видео
        cap = cv2.VideoCapture(in_path)
        if not cap.isOpened():
            raise Exception(f"Не удалось открыть видео: {in_path}")

        # Читаем первый кадр
        ret, frame = cap.read()
        if not ret:
            raise Exception("Не удалось прочитать кадр из видео")

        # Улучшаем кадр для детекции
        enhanced = enhance_frame(frame)

        # Получаем регионы
        top_region, bottom_region = calculate_regions(enhanced, green_area_width)
        bottom_x, bottom_y, bottom_w, bottom_h = bottom_region

        # Валидация регионов
        h, w = frame.shape[:2]
        if (
            bottom_x < 0
            or bottom_y < 0
            or bottom_x + bottom_w > w
            or bottom_y + bottom_h > h
        ):
            raise Exception("Регионы обработки выходят за границы кадра")

        # Создаем FFmpeg фильтр
        if top_region:
            TOP_PART_HEIGHT = int(OUTPUT_HEIGHT * 0.3)
            BOTTOM_PART_HEIGHT = OUTPUT_HEIGHT - TOP_PART_HEIGHT
            top_x, top_y, top_w, top_h = top_region

            filter_complex = f"""
                [0:v]crop={top_w}:{top_h}:{top_x}:{top_y},
                scale={OUTPUT_WIDTH}:{TOP_PART_HEIGHT},
                setsar=1[top];
                [0:v]crop={bottom_w}:{bottom_h}:{bottom_x}:{bottom_y},
                scale={OUTPUT_WIDTH}:{BOTTOM_PART_HEIGHT},
                setsar=1[bottom];
                [top][bottom]vstack=inputs=2,
                format=yuv420p[outv]
            """.replace(
                "\n", ""
            ).replace(
                " ", ""
            )
        else:
            filter_complex = f"""
                [0:v]crop={bottom_w}:{bottom_h}:{bottom_x}:{bottom_y},
                scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT},
                setsar=1,
                format=yuv420p[outv]
            """.replace(
                "\n", ""
            ).replace(
                " ", ""
            )

        # Команда FFmpeg с совместимыми параметрами для Windows
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            in_path,
            "-filter_complex",
            filter_complex,
            "-map",
            "[outv]",
            "-c:v",
            "libx264",
            "-profile:v",
            "main",  # Используем основной профиль для совместимости
            "-pix_fmt",
            "yuv420p",  # Обязательный формат пикселей для Windows
            "-preset",
            "fast",
            "-crf",
            "23",
            "-movflags",
            "+faststart",
            "-map",
            "0:a?",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "44100",  # Стандартная частота дискретизации
            out_path,
        ]

        # Запускаем обработку
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            encoding="utf-8",
            errors="ignore",
            timeout=600,
        )
        if result.returncode != 0:
            error_msg = result.stderr.strip().split("\n")[-1]
            raise Exception(f"FFmpeg завершился с ошибкой: {error_msg}")

        # Проверка результата
        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            raise Exception("Не удалось создать выходной файл")

        # Применяем баннер если нужно
        if BANNER_ENABLED:
            temp_banner_path = os.path.join(
                out_dir, f"temp_banner_{uuid.uuid4().hex[:8]}.mp4"
            )
            os.rename(out_path, temp_banner_path)

            if not _apply_banner(temp_banner_path, out_path):
                logger.warning("Баннер не применен, используется исходное обработанное видео")
                os.rename(temp_banner_path, out_path)
            else:
                try:
                    os.remove(temp_banner_path)
                except Exception as e:
                    logger.warning(f"Не удалось удалить временный файл: {e}")

        return out_path

    except subprocess.TimeoutExpired as e:
        logger.error("FFmpeg не завершил обработку видео за 10 минут", exc_info=True)
        raise Exception("Не удалось обработать видеофайл: превышено время рендера") from e
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg завершился с ошибкой при обработке видео: {e.stderr}")
        raise Exception("Не удалось обработать видеофайл") from e
    except Exception as e:
        # Очистка временных файлов
        for f in [temp_video_path, out_path]:
            try:
                if f and os.path.exists(f):
                    os.remove(f)
            except Exception as clean_err:
                logger.warning(f"Ошибка удаления {f}: {clean_err}")

        logger.error(f"Ошибка обработки видео: {e}")
        raise Exception("Не удалось обработать видеофайл") from e
    finally:
        if "cap" in locals():
            cap.release()
