import sys
import os
import re
import requests
import subprocess
import cv2
import numpy as np
import logging
import mediapipe as mp
import math
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem, QLineEdit, 
    QHeaderView, QMessageBox, QFileDialog, QCheckBox, QFrame, 
    QProgressBar, QToolBar, QStatusBar, QStyle, QStackedLayout,QGraphicsView,
    QGraphicsScene, QGraphicsItem, QGraphicsRectItem, QGraphicsPixmapItem, QSlider,
    QSizePolicy, QSplitter, QGroupBox, QTextEdit, QComboBox
)
from PyQt6.QtGui import (
    QColor, QPainter, QPen, QImage, QPixmap, QIcon, 
    QAction, QDesktopServices
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget, QGraphicsVideoItem
from PyQt6.QtCore import Qt, QRect, QPoint, QUrl, QThread, pyqtSignal, QSize, QTimer, QSizeF, QRectF
from PyQt6.QtGui import QBrush, QColor
from dotenv import load_dotenv
import vlc
import mediapipe as mp
import shutil
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request


# Настройка логгирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("TwitchVideoSuite")

# Загрузка переменных окружения
load_dotenv()
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
DEFAULT_CHANNELS = os.getenv('CHANNELS', '')

mp_pose = mp.solutions.pose
pose = mp_pose.Pose(static_image_mode=True)

def sanitize_filename(name):
    return re.sub(r'[\\/:"*?<>|]+', '_', name)   
        
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Twitch Video Suite")
        self.setGeometry(100, 100, 1200, 800)
        
        # Иконка приложения
        self.setWindowIcon(QIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)))
        
        # Создаем вкладки
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.tabs.setMovable(False)
        
        # Создаем стиль для вкладок
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #444;
                border-radius: 4px;
                background: #2a2a2a;
            }
            QTabBar::tab {
                background: #333;
                color: #ddd;
                padding: 8px 15px;
                border: 1px solid #444;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background: #444;
                color: #fff;
                border-color: #555;
            }
            QTabBar::tab:hover {
                background: #3a3a3a;
            }
        """)
        
        # Добавляем вкладки
        self.clip_finder_tab = TwitchClipFinderTab()
        self.video_editor_tab = VideoEditorTab()
        self.youtube_upload_tab = YouTubeUploadTab()
        
        self.tabs.addTab(self.clip_finder_tab, "Twitch Clip Finder")
        self.tabs.addTab(self.video_editor_tab, "Video Editor")
        self.tabs.addTab(self.youtube_upload_tab, "YouTube Upload")
        
        self.setCentralWidget(self.tabs)
        
        # Создаем статус бар
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # Создаем тулбар
        self.create_toolbar()
        
        # Применяем стили
        self.apply_styles()
    
    def create_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(24, 24))
        
        # Действия для тулбара
        exit_action = QAction(QIcon.fromTheme("application-exit"), "Exit", self)
        exit_action.triggered.connect(self.close)
        
        about_action = QAction(QIcon.fromTheme("help-about"), "About", self)
        about_action.triggered.connect(self.show_about)
        
        toolbar.addAction(exit_action)
        toolbar.addSeparator()
        toolbar.addAction(about_action)
        
        self.addToolBar(toolbar)
    
    def show_about(self):
        QMessageBox.about(self, "About Twitch Video Suite", 
                         "Twitch Video Suite v1.0\n\n"
                         "A powerful tool for Twitch clip discovery and video editing.")
    
    def apply_styles(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2a2a2a;
            }
            QWidget {
                color: #eee;
                font-size: 14px;
            }
            QLineEdit, QPushButton {
                padding: 8px;
                border-radius: 4px;
                border: 1px solid #444;
                background: #333;
                min-width: 80px;
            }
            QPushButton:hover {
                background: #3a3a3a;
            }
            QPushButton:pressed {
                background: #2a2a2a;
            }
            QTableWidget {
                background: #333;
                border: 1px solid #444;
                gridline-color: #444;
            }
            QHeaderView::section {
                background: #3a3a3a;
                padding: 5px;
                border: none;
            }
            QProgressBar {
                border: 1px solid #444;
                border-radius: 3px;
                text-align: center;
            }
            QProgressBar::chunk {
                background: #4a90e2;
                width: 10px;
            }
        """)
        
class TwitchClipFinderTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setup_ui()
        self.setup_vlc()
    
    def setup_vlc(self):
        try:
            # Проверяем несколько возможных путей к VLC
            possible_vlc_paths = [
                "C:\\Program Files\\VideoLAN\\VLC",
                "C:\\Program Files (x86)\\VideoLAN\\VLC",
                os.path.expanduser("~\\AppData\\Local\\Programs\\VideoLAN\\VLC"),
                "/usr/bin/vlc",  # для Linux
                "/usr/local/bin/vlc",  # для MacOS
                os.environ.get("VLC_PATH", "")  # если путь задан в переменных окружения
            ]
            
            vlc_found = False
            for vlc_path in possible_vlc_paths:
                if vlc_path and os.path.exists(vlc_path):
                    os.add_dll_directory(vlc_path)
                    os.environ["PATH"] += os.pathsep + vlc_path
                    vlc_found = True
                    break
            
            if not vlc_found:
                logger.warning("VLC not found in standard locations. Trying default PATH...")
            
            # Инициализация VLC
            self.instance = vlc.Instance()
            self.mediaplayer = self.instance.media_player_new()
            self.token = self.get_access_token()
            
        except Exception as e:
            logger.error(f"Ошибка инициализации VLC: {str(e)}")
            self.instance = None
            self.mediaplayer = None
            
            # Показываем пользователю инструкцию по установке VLC
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setWindowTitle("VLC Not Found")
            msg.setText("VLC media player is required for clip preview functionality.")
            msg.setInformativeText(
                "Please install VLC from https://www.videolan.org/vlc/\n\n"
                "After installation, restart the application."
            )
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()  
    
    def setup_ui(self):
        # Основной вертикальный макет
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # Верхняя панель с поиском
        search_layout = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Enter channels separated by commas (e.g. shroud,xqc,pokimane)")
        self.input.setText(DEFAULT_CHANNELS)
        search_layout.addWidget(self.input, stretch=1)
        
        self.search_btn = QPushButton("Find Clips")
        self.search_btn.setIcon(QIcon.fromTheme("edit-find"))
        self.search_btn.clicked.connect(self.fetch_clips)
        search_layout.addWidget(self.search_btn)
        
        layout.addLayout(search_layout)
        
        # Статус лейбл
        self.status_label = QLabel("Ready")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)
        
        # Кнопка скачивания
        self.download_btn = QPushButton("Download Selected Clips")
        self.download_btn.setIcon(QIcon.fromTheme("document-save"))
        self.download_btn.clicked.connect(self.download_selected_clips)
        layout.addWidget(self.download_btn)
        
        # Таблица с клипами
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Select", "Channel", "Title", "Views", 
            "Created At", "Download", "Preview"  # Убрали "URL", добавили "Created At"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        # Новые стили для таблицы и кнопок
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #2a2a2a;
                border: 1px solid #444;
                gridline-color: #444;
            }
            QHeaderView::section {
                background-color: #3a3a3a;
                padding: 5px;
                border: none;
            }
            QTableWidget::item {
                padding: 5px;
            }
            /* Устанавливаем минимальную высоту строк */
            QTableWidget::item {
                min-height: 20px;
            }
            /* Стили для кнопок в таблице */
            QPushButton {
                min-height: 17px;
                padding: 5px 10px;
                margin: 3px;
                border-radius: 4px;
                background: #444;
                color: white;
            }
            QPushButton:hover {
                background: #555;
            }
            QPushButton:pressed {
                background: #333;
            }
        """)
        
        self.table.verticalHeader().setDefaultSectionSize(40)
        layout.addWidget(self.table, 1)  # stretch=1 для заполнения пространства
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def get_access_token(self):
        url = 'https://id.twitch.tv/oauth2/token'
        params = {
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'grant_type': 'client_credentials'
        }
        response = requests.post(url, params=params).json()
        return response['access_token']

    def get_user_id(self, username, headers):
        url = f'https://api.twitch.tv/helix/users'
        params = {'login': username}
        response = requests.get(url, headers=headers, params=params).json()
        return response['data'][0]['id'] if response['data'] else None

    def get_clips(self, user_id, headers):
        start_time = datetime.utcnow() - timedelta(days=14)
        started_at = start_time.isoformat("T") + "Z"
        url = f'https://api.twitch.tv/helix/clips'
        params = {
            'broadcaster_id': user_id,
            'first': 20,
            'started_at': started_at,
            'sort': 'views'
        }
        response = requests.get(url, headers=headers, params=params).json()
        return response['data']

    def fetch_clips(self):
        self.table.setRowCount(0)
        self.status_label.setText("Загрузка...")
        QApplication.processEvents()

        headers = {
            'Client-ID': CLIENT_ID,
            'Authorization': f'Bearer {self.token}'
        }

        channels = [c.strip() for c in self.input.text().split(',') if c.strip()]
        if not channels:
            QMessageBox.warning(self, "Ошибка", "Введите хотя бы один канал.")
            return

        all_clips = []

        for channel in channels:
            user_id = self.get_user_id(channel, headers)
            if not user_id:
                continue
            clips = self.get_clips(user_id, headers)
            for clip in clips:
                clip['channel'] = channel
                all_clips.append(clip)

        sorted_clips = sorted(all_clips, key=lambda x: x['view_count'], reverse=True)

        for clip in sorted_clips:
            row_pos = self.table.rowCount()
            self.table.insertRow(row_pos)

            # NEW: Добавляем чекбокс в первый столбец
            checkbox = QCheckBox()
            checkbox_widget = QWidget()
            layout_cb = QHBoxLayout(checkbox_widget)
            layout_cb.addWidget(checkbox)
            layout_cb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout_cb.setContentsMargins(0, 0, 0, 0)
            checkbox_widget.setLayout(layout_cb)
            self.table.setCellWidget(row_pos, 0, checkbox_widget)

            self.table.setItem(row_pos, 1, QTableWidgetItem(clip['channel']))
            self.table.setItem(row_pos, 2, QTableWidgetItem(clip['title']))
            self.table.setItem(row_pos, 3, QTableWidgetItem(str(clip['view_count'])))

            created_at = clip.get('created_at', '')
            if created_at:
                try:
                    dt = datetime.strptime(created_at, '%Y-%m-%dT%H:%M:%SZ')
                    formatted_date = dt.strftime('%d-%m-%Y %H:%M')
                except:
                    formatted_date = created_at
            else:
                formatted_date = 'N/A'
            
            self.table.setItem(row_pos, 4, QTableWidgetItem(formatted_date))

            download_button = QPushButton("Скачать")
            download_button.setProperty('clip_url', clip['url'])  # Сохраняем URL в свойство
            download_button.clicked.connect(lambda _, url=clip['url'], ch=clip['channel'], title=clip['title']: 
                       self.download_clip(url, {"channel": ch, "title": title}))
            self.table.setCellWidget(row_pos, 5, download_button)
            download_button.setStyleSheet("""
                QPushButton {
                    min-width: 80px;
                    background: #5a5a5a;  /* Twitch purple */
                }
            """)

            # Кнопка предпросмотра
            preview_button = QPushButton("▶️")
            preview_button.clicked.connect(lambda _, url=clip['url']: self.preview_clip(url))
            self.table.setCellWidget(row_pos, 6, preview_button)
            preview_button.setStyleSheet("""
                QPushButton {
                    min-width: 80px;
                    background: #5a5a5a;
                }
            """)
            
        self.status_label.setText(f"Найдено клипов: {len(sorted_clips)}")      
    
    def download_selected_clips(self):
        selected_clips = []
        for row in range(self.table.rowCount()):
            checkbox_widget = self.table.cellWidget(row, 0)
            if checkbox_widget:
                checkbox = checkbox_widget.findChild(QCheckBox)
                if checkbox and checkbox.isChecked():
                    # Получаем канал и название из таблицы
                    channel_item = self.table.item(row, 1)
                    title_item = self.table.item(row, 2)
                    
                    if channel_item and title_item:
                        # Получаем URL из данных кнопки скачивания
                        download_button = self.table.cellWidget(row, 5)
                        if download_button:
                            # Получаем URL из свойства кнопки
                            url = download_button.property('clip_url')
                            if url:
                                selected_clips.append({
                                    'url': url,
                                    'channel': channel_item.text(),
                                    'title': title_item.text()
                                })

        if not selected_clips:
            QMessageBox.information(self, "Информация", "Не выбраны клипы для скачивания.")
            return

        save_dir = QFileDialog.getExistingDirectory(self, "Выберите папку для сохранения")
        if not save_dir:
            return

        self.status_label.setText("Скачивание выбранных клипов...")
        QApplication.processEvents()

        errors = []
        for clip in selected_clips:
            try:
                filename = f"{clip['channel']} - {clip['title']}.mp4"
                filename = sanitize_filename(filename)
                save_path = os.path.join(save_dir, filename)
                subprocess.run(["yt-dlp", "-o", save_path, clip['url']], check=True)
            except subprocess.CalledProcessError as e:
                errors.append(f"{clip['title']} ({e})")

        if errors:
            QMessageBox.warning(self, "Ошибка", f"Не удалось скачать клипы:\n" + "\n".join(errors))
        else:
            QMessageBox.information(self, "Готово", "Выбранные клипы успешно скачаны.")
        
        self.status_label.setText("Готово.")
   
    
    def preview_clip(self, clip_url):
        try:
            self.status_label.setText("Получение прямой ссылки...")
            QApplication.processEvents()

            result = subprocess.run(
                ["yt-dlp", "-f", "mp4", "-g", clip_url],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True
            )
            direct_url = result.stdout.strip()

            # Открываем отдельное окно предпросмотра
            self.preview_window = PreviewWindow(self.instance, direct_url)
            self.preview_window.show()
            self.setWindowIcon(QIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)))

            self.status_label.setText("Предпросмотр открыт.")
        except subprocess.CalledProcessError as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось получить ссылку на видео:\n{e.stderr}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

        
    def download_clip(self, clip_url, clip_info):
        # Формируем предложенное имя файла
        suggested_name = f"{clip_info['channel']} - {clip_info['title']}.mp4"
        
        # Запускаем диалог сохранения с предложенным именем
        save_path, _ = QFileDialog.getSaveFileName(self, "Сохранить клип как", suggested_name, "Видео (*.mp4)")
        if not save_path:
            return

        try:
            # yt-dlp принимает путь с расширением, поэтому если пользователь не дописал .mp4, добавим
            if not save_path.lower().endswith(".mp4"):
                save_path += ".mp4"

            # Скачиваем с помощью yt-dlp
            subprocess.run(["yt-dlp", "-o", save_path, clip_url], check=True)
            QMessageBox.information(self, "Готово", "Клип успешно скачан.")
        except subprocess.CalledProcessError as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось скачать клип:\n{e}")
          
class PreviewWindow(QWidget):
    def __init__(self, vlc_instance, direct_url):
        super().__init__()
        self.setWindowTitle("Предпросмотр клипа")
        self.resize(640, 360)
        self.setStyleSheet("background-color: black;")
        self.playing = False

        self.vlc_instance = vlc_instance
        self.direct_url = direct_url
        self.mediaplayer = self.vlc_instance.media_player_new()

        layout = QVBoxLayout()
        self.video_frame = QFrame()
        self.video_frame.setStyleSheet("background-color: black;")
        layout.addWidget(self.video_frame)
        self.setLayout(layout)

    def showEvent(self, event):
        super().showEvent(event)
        if sys.platform.startswith('win'):
            self.mediaplayer.set_hwnd(int(self.video_frame.winId()))

        media = self.vlc_instance.media_new(self.direct_url)
        media.add_option('--network-caching=500')
        media.add_option('--http-continuous')
        media.add_option('--no-video-title-show')
        self.mediaplayer.set_media(media)
        self.mediaplayer.play()
        self.playing = True

    def closeEvent(self, event):
        # Останавливаем воспроизведение
        if self.playing:
            self.mediaplayer.stop()
            self.playing = False
        
        # Освобождаем ресурсы медиаплеера
        if hasattr(self, 'mediaplayer') and self.mediaplayer:
            self.mediaplayer.release()
        
        event.accept()

class NoWheelGraphicsView(QGraphicsView):
    def wheelEvent(self, event):
        # Игнорируем событие прокрутки колесика мыши
        event.ignore()
        
class VideoEditorTab(QWidget):
    class CustomRectItem(QGraphicsRectItem):
        def __init__(self, rect, color, controller):
            super().__init__(rect)
            self.controller = controller
            self.setPen(QPen(color.darker(), 2))
            self.setBrush(QBrush(color))
            self.setAcceptHoverEvents(True)
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
            
        def itemChange(self, change, value):
            if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
                self.controller.on_rect_changed()
            return super().itemChange(change, value)
            
    def __init__(self):
        super().__init__()
        self.video_path = None
        self.cap = None
        self.frame = None
        self.save_folder = None
        self.cutting_thread = None
        self.frame_for_display = None
        self.playing = False
        self.timer = QTimer()
        self.draggable_rect_item = None
        self.GREEN_AREA_SETTINGS = {
            'width': 200,  # Меняйте только это значение
            'height': None  # Вычисляется автоматически
        }
        self.GREEN_AREA_SETTINGS['height'] = int(self.GREEN_AREA_SETTINGS['width'] / (16/9))
        
        # Инициализация прямоугольников
        self.rect1 = QRectF(0, 0, 300, 200)  # Зеленая область будет установлена при загрузке видео
        self.rect2 = QRectF(0, 0, 300, 200)  # Красная область будет центрирована
        
        # Минимальные размеры для зеленой области (16:9)
        self.MIN_RECT1_WIDTH = 100  # минимальная ширина
        self.MIN_RECT1_HEIGHT = int(self.MIN_RECT1_WIDTH / (16/9))  # высота для соотношения 16:9
        
        # Текущий минимальный размер (будет увеличиваться при изменении)
        self.current_min_width = self.MIN_RECT1_WIDTH
        self.current_min_height = self.MIN_RECT1_HEIGHT
        
        # Добавляем флаг для отслеживания изменений
        self.rect_changed = False
        
        self.face_analyser = None
        try:
            from insightface.app import FaceAnalysis
            self.face_analyser = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
            self.face_analyser.prepare(ctx_id=0, det_size=(320, 320))
        except ImportError as e:
            print(f"InsightFace initialization failed: {e}")
            self.face_analyser = None
        
        self.setup_ui()
        self.init_media_player()
        self.canvas_view.setSceneRect(0, 0, 960, 540)  # Фиксируем размер сцены
        
    def init_media_player(self):
        try:
            if hasattr(self, 'media_player'):
                self.media_player.stop()
                
            if hasattr(self, 'video_item'):
                self.scene.removeItem(self.video_item)
            
            # Устанавливаем правильный размер видеоэлемента
            self.video_item = QGraphicsVideoItem()
            self.video_item.setSize(QSizeF(960, 540))
            self.video_item.setPos(0, 0)
            self.scene.addItem(self.video_item)
            
            self.media_player = QMediaPlayer()
            self.audio_output = QAudioOutput()
            self.media_player.setAudioOutput(self.audio_output)
            self.audio_output.setVolume(0.3)
            self.media_player.setVideoOutput(self.video_item)
            
            # Добавляем второй видеоэлемент для вертикального превью
            self.vertical_video_item = QGraphicsVideoItem()
            self.vertical_video_item.setSize(QSizeF(360, 640))
            self.vertical_video_item.setPos(960 + 20, 0)  # разместить справа от основного видео
            self.vertical_video_item.setVisible(True)
            self.scene.addItem(self.vertical_video_item)
            
            # Создаем второй медиаплеер
            self.vertical_media_player = QMediaPlayer()
            self.vertical_audio_output = QAudioOutput()
            self.vertical_media_player.setAudioOutput(self.vertical_audio_output)
            self.vertical_audio_output.setVolume(0.0)
            self.vertical_media_player.setVideoOutput(self.vertical_video_item)

            # Включение аппаратного ускорения
            self.media_player.setProperty("videoOutput", "direct2d")

            # Устанавливаем режим сохранения пропорций
            self.video_item.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)            
            
            return True
            
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось инициализировать плеер: {str(e)}")
            return False   
    
    def get_scale_factors(self):
        """Возвращает коэффициенты масштабирования между оригинальным видео и холстом"""
        if not hasattr(self, 'original_video_size'):
            return 1.0, 1.0
            
        orig_w, orig_h = self.original_video_size
        canvas_w = self.canvas_view.width()
        canvas_h = self.canvas_view.height()
        
        # Коэффициенты масштабирования
        scale_x = orig_w / canvas_w
        scale_y = orig_h / canvas_h
        
        return scale_x, scale_y

    def canvas_to_original(self, point):
        """Преобразует координаты из холста в оригинальные координаты видео"""
        scale_x, scale_y = self.get_scale_factors()
        return QPoint(int(point.x() * scale_x), int(point.y() * scale_y))

    def original_to_canvas(self, point):
        """Преобразует координаты из оригинального видео в координаты холста"""
        scale_x, scale_y = self.get_scale_factors()
        return QPoint(int(point.x() / scale_x), int(point.y() / scale_y))
    
    def clear_scene(self):
        """Очищает сцену, кроме видео и прямоугольников"""
        items_to_remove = []
        for item in self.scene.items():
            if not isinstance(item, (QGraphicsVideoItem, QGraphicsRectItem)):
                if item and item.scene() is self.scene:
                    items_to_remove.append(item)
        
        for item in items_to_remove:
            try:
                self.scene.removeItem(item)
            except:
                pass  # Если элемент уже удален
                
    def init_areas(self):
        """Инициализирует области с проверкой масштабирования"""
        if not hasattr(self, 'scale_params'):
            return
            
        canvas_width = self.canvas_view.width()
        canvas_height = self.canvas_view.height()
        
        # Зеленая область (16:9)
        green_width = min(400, canvas_width)
        green_height = int(green_width * 9/16)
        
        # Красная область (9:16)
        red_width = min(300, canvas_width)
        red_height = int(red_width * 16/9)
        
        # Центрируем с учётом масштабирования
        self.rect1 = QRectF(
            max(0, (canvas_width - green_width) // 2),
            max(0, (canvas_height - green_height) // 4),
            green_width,
            green_height
        )
        
        self.rect2 = QRectF(
            max(0, (canvas_width - red_width) // 2),
            max(0, canvas_height - (canvas_height - red_height) // 4 - red_height),
            red_width,
            red_height
        )
        
        self.area1_item.setRect(self.rect1)
        self.area2_item.setRect(self.rect2)           

    def setup_ui(self):
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(15)

        # Левая панель (16:9)
        left_panel = QVBoxLayout()
        left_panel.setSpacing(15)

        # Панель инструментов
        tool_panel = QHBoxLayout()
        self.load_btn = QPushButton("Load Video")
        self.load_btn.setIcon(QIcon.fromTheme("document-open"))
        self.load_btn.clicked.connect(self.load_video)
        tool_panel.addWidget(self.load_btn)

        self.save_btn = QPushButton("Set Output")
        self.save_btn.setIcon(QIcon.fromTheme("folder"))
        self.save_btn.clicked.connect(self.selectSaveFolder)
        self.save_btn.setEnabled(False)
        tool_panel.addWidget(self.save_btn)

        # Кнопки управления воспроизведением
        self.play_btn = QPushButton()
        self.play_btn.setIcon(QIcon.fromTheme("media-playback-start"))  # Иконка воспроизведения
        self.play_btn.clicked.connect(self.toggle_playback)
        self.play_btn.setEnabled(False)
        tool_panel.addWidget(self.play_btn)
        
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(30)  # дефолт 50%
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.valueChanged.connect(self.set_volume)
        tool_panel.addWidget(QLabel("Volume:"))
        tool_panel.addWidget(self.volume_slider)

        left_panel.addLayout(tool_panel)

        # Основной холст для видео 16:9
        self.scene = QGraphicsScene()
        self.canvas_view = NoWheelGraphicsView(self.scene)
        self.canvas_view.setFixedSize(960, 540)
        self.canvas_view.setStyleSheet("background-color: black;")
        
        # Настройки для устранения ползунков прокрутки
        self.canvas_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.canvas_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.canvas_view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.canvas_view.setInteractive(False) 
        self.canvas_view.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.canvas_view.setOptimizationFlag(QGraphicsView.OptimizationFlag.DontAdjustForAntialiasing, True)
        self.canvas_view.setOptimizationFlag(QGraphicsView.OptimizationFlag.DontSavePainterState, True)
        
        # Видеоэлемент
        self.video_item = QGraphicsVideoItem()
        self.video_item.setPos(0, 0)
        self.video_item.setSize(QSizeF(960, 540))
        self.scene.addItem(self.video_item)
        self.video_item.setVisible(False)

        # Прямоугольники для выделения областей
        self.area1_item = self.scene.addRect(QRectF(0, 0, 300, 200), 
                                           QPen(QColor(0, 255, 0, 180), 2),
                                           QBrush(QColor(0, 255, 0, 60)))
        self.area2_item = self.scene.addRect(QRectF(0, 0, 300, 200),
                                           QPen(QColor(255, 0, 0, 180), 2),
                                           QBrush(QColor(255, 0, 0, 60)))
        # Устанавливаем Z-порядок
        self.video_item.setZValue(0)      # Видео - самый нижний слой
        self.area1_item.setZValue(1)      # Прямоугольники поверх видео
        self.area2_item.setZValue(1)

        # Сделаем прямоугольники перемещаемыми
        self.area1_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.area1_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.area2_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.area2_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)

        left_panel.addWidget(self.canvas_view)

        # Панель управления обработкой
        control_panel = QHBoxLayout()
        self.start_btn = QPushButton("Start Processing")
        self.start_btn.setIcon(QIcon.fromTheme("media-playback-start"))
        self.start_btn.clicked.connect(self.startCutting)
        self.start_btn.setEnabled(False)
        control_panel.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setIcon(QIcon.fromTheme("media-playback-stop"))
        self.stop_btn.clicked.connect(self.stopCutting)
        self.stop_btn.setEnabled(False)
        control_panel.addWidget(self.stop_btn)

        left_panel.addLayout(control_panel)

        # Прогресс бар с фиолетовым цветом
        self.progress = QProgressBar()
        self.progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #444;
                border-radius: 3px;
                text-align: center;
                background: #333;
                height: 20px;
            }
            QProgressBar::chunk {
                background: #9b59b6;
                width: 10px;
            }
        """)
        left_panel.addWidget(self.progress)

        # Правая панель - предпросмотр 9:16
        right_panel = QVBoxLayout()
        right_panel.setSpacing(10)

        preview_label = QLabel("Preview (9:16)")
        preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_panel.addWidget(preview_label)

        self.preview_canvas = QLabel()
        self.preview_canvas.setFixedSize(360, 640)  # 9:16
        self.preview_canvas.setStyleSheet("background-color: black;")
        right_panel.addWidget(self.preview_canvas)

        # Добавляем панели в основной макет
        main_layout.addLayout(left_panel, 70)  # 70% ширины
        main_layout.addLayout(right_panel, 30)  # 30% ширины
        self.setLayout(main_layout)
        
        self.debug_btn = QPushButton("Показать границы")
        self.debug_btn.clicked.connect(self.debug_bounds)
        tool_panel.addWidget(self.debug_btn)
        
        self.init_areas()

        # Подключаем сигналы изменения прямоугольников
        self.scene.selectionChanged.connect(self.update_preview)
        
    def debug_bounds(self):
        if hasattr(self, 'pixmap_item'):
            print(f"Позиция изображения: {self.pixmap_item.pos().x()}, {self.pixmap_item.pos().y()}")
            print(f"Размер изображения: {self.pixmap_item.pixmap().width()}x{self.pixmap_item.pixmap().height()}")
        print(f"Размер сцены: {self.scene.width()}x{self.scene.height()}")
        print(f"Размер view: {self.canvas_view.width()}x{self.canvas_view.height()}")        

    def detect_face_area(self, frame):
        # Инициализация модели insightface (один раз при создании класса)
        if not hasattr(self, 'face_analyser'):
            from insightface.app import FaceAnalysis
            self.face_analyser = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
            self.face_analyser.prepare(ctx_id=0, det_size=(640, 640))
        
       
        # Первый проход - InsightFace RetinaFace (если инициализирован)
        if self.face_analyser is not None:
            try:
                faces = self.face_analyser.get(frame)
                if len(faces) > 0:
                    largest_face = max(faces, key=lambda face: (face.bbox[2]-face.bbox[0])*(face.bbox[3]-face.bbox[1]))
                    x1, y1, x2, y2 = map(int, largest_face.bbox)
                    x1 = max(0, x1)
                    y1 = max(0, y1)
                    x2 = min(frame.shape[1], x2)
                    y2 = min(frame.shape[0], y2)
                    return x1, y1, x2-x1, y2-y1
            except Exception as e:
                print(f"InsightFace detection error: {e}")

        # Второй проход - MediaPipe (fallback)
        with mp.solutions.face_detection.FaceDetection(
            model_selection=1,
            min_detection_confidence=0.3
        ) as face_detector:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = face_detector.process(rgb_frame)
            
            if results.detections:
                largest_face = max(
                    results.detections,
                    key=lambda det: (
                        det.location_data.relative_bounding_box.width * 
                        det.location_data.relative_bounding_box.height
                    )
                )
                bbox = largest_face.location_data.relative_bounding_box
                x = int(bbox.xmin * frame.shape[1])
                y = int(bbox.ymin * frame.shape[0])
                w = int(bbox.width * frame.shape[1])
                h = int(bbox.height * frame.shape[0])
                return x, y, w, h

        # Третий проход - OpenCV DNN (если предыдущие методы не сработали)
        net = cv2.dnn.readNetFromCaffe(
            "deploy.prototxt",
            "res10_300x300_ssd_iter_140000.caffemodel"
        )
        blob = cv2.dnn.blobFromImage(
            cv2.resize(frame, (300, 300)), 1.0,
            (300, 300), (104.0, 177.0, 123.0))
        net.setInput(blob)
        detections = net.forward()
        
        for i in range(detections.shape[2]):
            confidence = detections[0, 0, i, 2]
            if confidence > 0.5:
                box = detections[0, 0, i, 3:7] * np.array([frame.shape[1], frame.shape[0], frame.shape[1], frame.shape[0]])
                x, y, x2, y2 = box.astype("int")
                return x, y, x2-x, y2-y

        return None
        
    def set_green_area_size(self, width):
        """Изменяет размер зеленой области (только ширина, высота вычисляется автоматически)"""
        self.GREEN_AREA_SETTINGS['width'] = width
        self.GREEN_AREA_SETTINGS['height'] = int(width / (16/9))
        
        # Обновляем отображение
        if hasattr(self, 'area1_item'):
            center = self.area1_item.rect().center()
            self.rect1 = QRectF(
                center.x() - width/2,
                center.y() - self.GREEN_AREA_SETTINGS['height']/2,
                width,
                self.GREEN_AREA_SETTINGS['height']
            )
            self.area1_item.setRect(self.rect1)
            self.update_preview()    
        
    def find_face_with_retry(self, frame, attempts=3):
        for i in range(attempts):
            face_rect = self.detect_face_area(frame)
            if face_rect:
                return face_rect
            # Небольшое изменение кадра может помочь
            frame = cv2.convertScaleAbs(frame, alpha=1.2, beta=10)
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE) if i % 2 else frame
        return None    
    
    def process_video_frame(self, frame):
        # Улучшаем качество изображения перед поиском лица
        enhanced = self.enhance_image(frame)
        
        # Пробуем найти лицо
        face_rect = self.find_face_with_retry(enhanced, attempts=5)
        
        if face_rect:
            x, y, w, h = map(int, face_rect)
            
            # Используем настройки из self.GREEN_AREA_SETTINGS
            fixed_width = self.GREEN_AREA_SETTINGS['width']
            fixed_height = self.GREEN_AREA_SETTINGS['height']
            
            # Центрируем прямоугольник по лицу
            face_center_x = x + w//2
            face_center_y = y + h//2
            
            # Вычисляем координаты для фиксированного прямоугольника
            x = int(face_center_x - fixed_width//2)
            y = int(face_center_y - fixed_height//2)
            
            # Проверяем границы кадра
            x = max(0, x)
            y = max(0, y)
            if x + fixed_width > frame.shape[1]:
                x = frame.shape[1] - fixed_width
            if y + fixed_height > frame.shape[0]:
                y = frame.shape[0] - fixed_height
                
            return x, y, fixed_width, fixed_height
        
        return None

    def enhance_image(self, frame):
        # Улучшение контраста
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
        limg = cv2.merge((clahe.apply(l), a, b))
        enhanced = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
        
        # Легкое размытие для уменьшения шума
        enhanced = cv2.GaussianBlur(enhanced, (3,3), 0)
        return enhanced
        
    def draw_draggable_rect(self, rect):
        if self.draggable_rect_item:
            self.scene.removeItem(self.draggable_rect_item)
        self.draggable_rect_item = DraggableRect(rect)
        self.scene.addItem(self.draggable_rect_item)  

    def reset_rectangles(self):
        """Сбрасывает прямоугольники с проверкой границ"""
        canvas_width = self.canvas_view.width()
        canvas_height = self.canvas_view.height()
        
        # Удаляем старые прямоугольники
        if hasattr(self, 'area1_item'):
            self.scene.removeItem(self.area1_item)
        if hasattr(self, 'area2_item'):
            self.scene.removeItem(self.area2_item)
        
        # Зеленая область (горизонтальная 16:9)
        rect1_width = min(400, canvas_width)
        rect1_height = int(rect1_width * 9/16)
        self.rect1 = QRectF(
            max(0, (canvas_width - rect1_width) / 2),
            max(0, (canvas_height - rect1_height) / 4),  # Смещаем немного вверх
            rect1_width,
            rect1_height
        )
        
        # Красная область (вертикальная 9:16)
        rect2_width = min(300, canvas_width)
        rect2_height = int(rect2_width * 16/9)
        self.rect2 = QRectF(
            max(0, (canvas_width - rect2_width) / 2),
            canvas_height - rect2_height - ((canvas_height - rect2_height) / 4),  # Смещаем немного вниз
            rect2_width,
            rect2_height
        )
        
        # Создаём элементы
        self.area1_item = self.CustomRectItem(self.rect1, QColor(0, 255, 0, 180), self)
        self.area2_item = self.CustomRectItem(self.rect2, QColor(255, 0, 0, 180), self)
        
        # Добавляем на сцену
        self.scene.addItem(self.area1_item)
        self.scene.addItem(self.area2_item)
        
        # Настройки элементов
        self.area1_item.setZValue(1)
        self.area2_item.setZValue(1)
        self.area1_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.area1_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.area2_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.area2_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)       
        
    
    def load_video(self):
        # Полная очистка предыдущего состояния
        self.clear()        
        # Очищаем preview
        self.preview_canvas.clear()
        if not self.init_media_player():
            return
        # Удаляем предыдущий pixmap_item, если он существует
        if hasattr(self, 'pixmap_item'):
            self.scene.removeItem(self.pixmap_item)
            del self.pixmap_item
        
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите видео", "", 
            "Видео файлы (*.mp4 *.avi *.mov)"
        )
        if not path:
            return
        
        if self.playing:
            self.toggle_playback()
        
        if hasattr(self, 'cap') and self.cap is not None:
            self.cap.release()
        
        try:
            self.video_path = path
            self.cap = cv2.VideoCapture(path, cv2.CAP_FFMPEG)
            
            if not self.cap.isOpened():
                raise Exception("Не удалось открыть видеофайл")
                
            ret, frame = self.cap.read()
            if not ret:
                raise Exception("Не удалось прочитать кадр из видео")
                
            self.original_video_size = (frame.shape[1], frame.shape[0])
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            
            # Масштабируем с сохранением пропорций
            h, w = frame.shape[:2]
            target_width = 960  # Ширина холста
            target_height = 540  # Высота холста
            
            # Рассчитываем коэффициенты масштабирования
            target_ratio = target_width / target_height
            video_ratio = w / h

            if video_ratio > target_ratio:  # Видео шире, чем холст
                scale_factor = target_width / w
            else:  # Видео уже или такое же
                scale_factor = target_height / h
            new_w = int(w * scale_factor)
            new_h = int(h * scale_factor)
            
            # Масштабируем кадр
            frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
            
            # Создаем черный фон и центрируем видео
            self.frame = np.zeros((target_height, target_width, 3), dtype=np.uint8)
            x_offset = (target_width - new_w) // 2
            y_offset = (target_height - new_h) // 2
            
            self.frame[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = frame
            
            # Сохраняем параметры масштабирования
            self.scale_params = {
                'scale_factor': scale_factor,
                'x_offset': x_offset,
                'y_offset': y_offset,
                'new_w': new_w,
                'new_h': new_h
            }
            
            # Очищаем сцену и инициализируем прямоугольники
            self.clear_scene()
            self.reset_rectangles()
            self.current_min_width = self.MIN_RECT1_WIDTH
            self.current_min_height = self.MIN_RECT1_HEIGHT
            
            # Отображаем кадр на холсте
            self.show_frame_on_canvas(self.frame)
            
            # Пытаемся найти лицо для автоматической настройки зеленой области
            face_rect = self.process_video_frame(frame)
            if face_rect:
                x, y, w, h = map(int, face_rect)
                # Учитываем смещение при позиционировании
                x += self.scale_params['x_offset']
                y += self.scale_params['y_offset']
                self.rect1 = QRectF(x, y, w, h)
                self.area1_item.setRect(self.rect1)
                
            # Настраиваем красную область
            self.set_red_area_center()
            
            # Обновляем превью
            self.update_preview_with_frame(self.frame)
            
            # Активируем кнопки
            self.save_btn.setEnabled(True)
            self.play_btn.setEnabled(True)
            self.start_btn.setEnabled(True)
            self.progress.setValue(0)
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка при загрузке видео: {str(e)}")
            logger.error(f"Ошибка при загрузке видео: {str(e)}")
            self.video_path = None
            if hasattr(self, 'cap') and self.cap is not None:
                self.cap.release()
                self.cap = None
                    
    def get_scaled_rectangles(self):
        if not hasattr(self, 'original_video_size') or not hasattr(self, 'scale_params'):
            return None, None
            
        orig_w, orig_h = self.original_video_size
        canvas_w = self.canvas_view.width()
        canvas_h = self.canvas_view.height()
        
        # Коэффициенты масштабирования
        scale_x = orig_w / canvas_w
        scale_y = orig_h / canvas_h
        
        def scale_rect(rect):
            # Преобразуем координаты из холста в оригинальные координаты видео
            x = max(0, int(rect.x() * scale_x))
            y = max(0, int(rect.y() * scale_y))
            width = min(orig_w - x, int(rect.width() * scale_x))
            height = min(orig_h - y, int(rect.height() * scale_y))
            
            # Минимальный размер 10x10 пикселей
            if width < 10 or height < 10:
                return None
                
            return QRect(x, y, width, height)
        
        rect1 = scale_rect(self.area1_item.rect())
        rect2 = scale_rect(self.area2_item.rect())
        
        print(f"Scaled rect1: {rect1.x() if rect1 else None}, {rect1.y() if rect1 else None}, "
              f"{rect1.width() if rect1 else None}, {rect1.height() if rect1 else None}")
        print(f"Scaled rect2: {rect2.x() if rect2 else None}, {rect2.y() if rect2 else None}, "
              f"{rect2.width() if rect2 else None}, {rect2.height() if rect2 else None}")
        
        return rect1, rect2

    def safe_scale_rect(rect):
        # Преобразуем координаты из холста в оригинальные координаты видео
        try:
            x = max(0, int((rect.x() - x_offset) * (orig_w / new_w)))
            y = max(0, int((rect.y() - y_offset) * (orig_h / new_h)))
            width = min(orig_w - x, int(rect.width() * (orig_w / new_w)))
            height = min(orig_h - y, int(rect.height() * (orig_h / new_h)))
            return QRect(x, y, width, height)
        except:
            return None
    
        rect1 = safe_scale_rect(self.area1_item.rect())
        rect2 = safe_scale_rect(self.area2_item.rect())
        
        if rect1 is None or rect2 is None:
            QMessageBox.warning(self, "Ошибка", "Не удалось преобразовать координаты прямоугольников")
            return None, None
        
        return rect1, rect2     
        
    def show_frame_on_canvas(self, frame):
        try:
            if frame is None or frame.size == 0:
                return
                
            # Удаляем предыдущий pixmap_item, если он существует
            if hasattr(self, 'pixmap_item'):
                self.scene.removeItem(self.pixmap_item)
                del self.pixmap_item                
            
            # Если размеры совпадают - просто отображаем
            if frame.shape[1] == self.canvas_view.width() and frame.shape[0] == self.canvas_view.height():
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_frame.shape
                bytes_per_line = ch * w
                qt_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                pixmap = QPixmap.fromImage(qt_image)
                
                if hasattr(self, 'pixmap_item'):
                    self.scene.removeItem(self.pixmap_item)
                    
                self.pixmap_item = QGraphicsPixmapItem(pixmap)
                self.pixmap_item.setZValue(-1)
                self.scene.addItem(self.pixmap_item)
                self.pixmap_item.setPos(0, 0)
            else:
                # Масштабируем под размер холста
                scaled_frame = cv2.resize(frame, 
                                        (self.canvas_view.width(), self.canvas_view.height()),
                                        interpolation=cv2.INTER_AREA)
                rgb_frame = cv2.cvtColor(scaled_frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_frame.shape
                bytes_per_line = ch * w
                qt_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                pixmap = QPixmap.fromImage(qt_image)
                
                if hasattr(self, 'pixmap_item'):
                    self.scene.removeItem(self.pixmap_item)
                    
                self.pixmap_item = QGraphicsPixmapItem(pixmap)
                self.pixmap_item.setZValue(-1)
                self.scene.addItem(self.pixmap_item)
                self.pixmap_item.setPos(0, 0)
                
        except Exception as e:
            print(f"Ошибка при отображении кадра: {str(e)}")
                
    def on_rect_changed(self):
        if not hasattr(self, 'original_video_size'):
            return
            
        canvas_width = self.canvas_view.width()
        canvas_height = self.canvas_view.height()
        orig_w, orig_h = self.original_video_size
        
        # Для зелёной области
        rect = self.area1_item.rect()
        new_rect = QRectF(
            max(0, min(rect.x(), canvas_width - rect.width())),
            max(0, min(rect.y(), canvas_height - rect.height())),
            min(rect.width(), canvas_width),
            min(rect.height(), canvas_height)
        )
        self.area1_item.setRect(new_rect)
        
        # Для красной области
        rect = self.area2_item.rect()
        new_rect = QRectF(
            max(0, min(rect.x(), canvas_width - rect.width())),
            max(0, min(rect.y(), canvas_height - rect.height())),
            rect.width(),
            rect.height()
        )
        self.area2_item.setRect(new_rect)
        
        # Обновляем превью
        self.update_preview()
             
    def set_volume(self, value):
        linear_volume = (value / 100.0)
        adjusted_volume = math.pow(linear_volume, 2.0)  # или 3.0
        self.audio_output.setVolume(adjusted_volume)           

    def update_preview_with_frame(self, frame):
        """Обновляет превью с заданным кадром с правильным растяжением обеих областей"""
        try:
            # Получаем текущие прямоугольники
            rect1 = self.area1_item.rect()  # Зеленая область
            rect2 = self.area2_item.rect()  # Красная область
            
            preview_w = self.preview_canvas.width()
            preview_h = self.preview_canvas.height()
            
            # Фиксированные пропорции (верх 30%, низ 70%)
            top_h = int(preview_h * 0.3)
            bottom_h = preview_h - top_h
            
            # Обработка верхней области (зеленой) - растягиваем на всю ширину
            x, y, w, h = int(rect1.x()), int(rect1.y()), int(rect1.width()), int(rect1.height())
            x = max(0, min(x, frame.shape[1] - 1))
            y = max(0, min(y, frame.shape[0] - 1))
            w = min(w, frame.shape[1] - x)
            h = min(h, frame.shape[0] - y)
            
            if w > 0 and h > 0:
                crop = frame[y:y+h, x:x+w]
                if crop.size > 0:
                    # Растягиваем на всю ширину превью и 30% высоты
                    top_img = cv2.resize(crop, (preview_w, top_h), interpolation=cv2.INTER_AREA)
                else:
                    top_img = np.zeros((top_h, preview_w, 3), dtype=np.uint8)
            else:
                top_img = np.zeros((top_h, preview_w, 3), dtype=np.uint8)
            
            # Обработка нижней области (красной) - растягиваем на всю ширину
            x, y, w, h = int(rect2.x()), int(rect2.y()), int(rect2.width()), int(rect2.height())
            x = max(0, min(x, frame.shape[1] - 1))
            y = max(0, min(y, frame.shape[0] - 1))
            w = min(w, frame.shape[1] - x)
            h = min(h, frame.shape[0] - y)
            
            if w > 0 and h > 0:
                crop = frame[y:y+h, x:x+w]
                if crop.size > 0:
                    # Растягиваем на всю ширину превью и 70% высоты
                    bottom_img = cv2.resize(crop, (preview_w, bottom_h), interpolation=cv2.INTER_AREA)
                else:
                    bottom_img = np.zeros((bottom_h, preview_w, 3), dtype=np.uint8)
            else:
                bottom_img = np.zeros((bottom_h, preview_w, 3), dtype=np.uint8)
            
            # Объединяем изображения
            combined = np.vstack((top_img, bottom_img))
            combined_rgb = cv2.cvtColor(combined, cv2.COLOR_BGR2RGB)
            
            # Отображаем
            h, w, ch = combined_rgb.shape
            qimg = QImage(combined_rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
            self.preview_canvas.setPixmap(QPixmap.fromImage(qimg))
        
        except Exception as e:
            print(f"Ошибка обработки кадра: {str(e)}")
            
    def clear(self):
        """Очищает все состояние редактора"""
        if hasattr(self, 'cap') and self.cap is not None:
            self.cap.release()
            self.cap = None
            
        if hasattr(self, 'pixmap_item'):
            self.scene.removeItem(self.pixmap_item)
            del self.pixmap_item
            
        if hasattr(self, 'preview_timer'):
            self.preview_timer.stop()
            del self.preview_timer
            
        if hasattr(self, 'media_player'):
            self.media_player.stop()
            self.media_player.setSource(QUrl())  # Очищаем источник
            
        self.preview_canvas.clear()
        self.frame = None
        self.video_path = None
        self.progress.setValue(0)
        
        # Сбрасываем кнопки
        self.play_btn.setIcon(QIcon.fromTheme("media-playback-start"))
        self.playing = False
        self.play_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.save_btn.setEnabled(False)       
             
    def toggle_playback(self):
        if not self.video_path:
            return
            
        if not self.playing:
            # Если видео не воспроизводится, начинаем воспроизведение
            if not hasattr(self, 'preview_timer'):
                # Очищаем предыдущее состояние только при первом запуске
                if hasattr(self, 'pixmap_item'):
                    self.scene.removeItem(self.pixmap_item)
                    del self.pixmap_item
                
                # Загружаем видео
                self.media_player.setSource(QUrl.fromLocalFile(self.video_path))
                self.media_player.setVideoOutput(self.video_item)
                self.video_item.setVisible(True)
                
                # Создаем таймер для обновления превью
                self.preview_timer = QTimer()
                self.preview_timer.timeout.connect(self.update_live_preview)
                self.preview_timer.start(33)  # ~30 FPS
            
            # Запускаем/возобновляем воспроизведение
            self.media_player.play()
            self.play_btn.setIcon(QIcon.fromTheme("media-playback-pause"))  # Иконка паузы
            self.playing = True
        else:
            # Если видео воспроизводится, ставим на паузу
            self.media_player.pause()
            self.play_btn.setIcon(QIcon.fromTheme("media-playback-start"))  # Иконка воспроизведения
            self.playing = False
            
            # Показываем текущий кадр (без сброса позиции)
            position = self.media_player.position()
            self.cap.set(cv2.CAP_PROP_POS_MSEC, position)
            ret, frame = self.cap.read()
            if ret:
                # Масштабируем кадр под размер холста (960x540)
                h, w = frame.shape[:2]
                scale_factor = min(960/w, 540/h)
                new_w = int(w * scale_factor)
                new_h = int(h * scale_factor)
                frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
                
                self.show_frame_on_canvas(frame)

    def update_live_preview(self):
        """Обновляет превью при воспроизведении - теперь работает так же как экспорт"""
        if not self.playing:
            return
        
        position = self.media_player.position()
        self.cap.set(cv2.CAP_PROP_POS_MSEC, position)
        ret, frame = self.cap.read()
        if not ret:
            return
        
        try:
            # Получаем размеры оригинального кадра
            h, w = frame.shape[:2]
            target_width = 960
            target_height = 540
            
            # Масштабируем с сохранением пропорций
            scale_factor = min(target_width/w, target_height/h)
            new_w = int(w * scale_factor)
            new_h = int(h * scale_factor)
            
            # Масштабируем кадр
            scaled_frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
            
            # Создаем черный фон и центрируем видео
            self.frame = np.zeros((target_height, target_width, 3), dtype=np.uint8)
            x_offset = (target_width - new_w) // 2
            y_offset = (target_height - new_h) // 2
            self.frame[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = scaled_frame
            
            # Обновляем превью (используем новый метод)
            self.update_preview_with_frame(self.frame)
            
            # Обновляем отображение на основном холсте
            self.show_frame_on_canvas(self.frame)
        
        except Exception as e:
            print(f"Ошибка обработки кадра: {str(e)}")
        
    def set_red_area_center(self):
        """Устанавливает красную область по центру"""
        canvas_width = self.canvas_view.width()
        canvas_height = self.canvas_view.height()
        
        # Ширина - 55% от ширины превью (как у вас было)
        preview_width = self.preview_canvas.width()
        area_width = int((preview_width * 0.55) * (canvas_width / preview_width))
        
        # Высота - вся доступная высота холста
        area_height = canvas_height
        
        # Центрируем по горизонтали
        x = (canvas_width - area_width) // 2
        y = 0  # Начинаем с верхнего края
        
        self.rect2 = QRectF(x, y, area_width, area_height)
        self.area2_item.setRect(self.rect2)
        self.update_preview()

    def update_preview(self):
        if self.frame is None:
            return
            
        # Получаем вырезанные области из исходного видео
        def crop_area(rect):
            x = int(rect.x())
            y = int(rect.y())
            w = int(rect.width())
            h = int(rect.height())
            return self.frame[y:y+h, x:x+w]
        
        top_area = crop_area(self.area1_item.rect())  # Зеленая область
        bottom_area = crop_area(self.area2_item.rect())  # Красная область
        
        # Размеры для превью (9:16)
        preview_width = self.preview_canvas.width()
        preview_height = self.preview_canvas.height()
        
        # Верхняя часть - 30% высоты
        top_height = int(preview_height * 0.3)
        top_img = cv2.resize(top_area, (preview_width, top_height))
        
        # Нижняя часть - 70% высоты
        bottom_height = preview_height - top_height
        bottom_img = cv2.resize(bottom_area, (preview_width, bottom_height))
        
        # Объединяем части
        combined = np.vstack((top_img, bottom_img))
        combined_rgb = cv2.cvtColor(combined, cv2.COLOR_BGR2RGB)
        
        # Отображаем
        h, w, ch = combined_rgb.shape
        qimg = QImage(combined_rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        self.preview_canvas.setPixmap(QPixmap.fromImage(qimg))

    def selectSaveFolder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку для сохранения")
        if folder:
            self.save_folder = folder
            logger.info(f"Папка для сохранения: {folder}")

    def updateRect(self, area_widget, new_rect, was_resized=False):
        if area_widget == self.area1:
            self.current_rect1 = QRect(new_rect)
        elif area_widget == self.area2:
            self.current_rect2 = QRect(new_rect)
        
        self.updatePreview()

    def updatePreview(self):
        if self.frame is None:
            return

        frame_h, frame_w = self.frame.shape[:2]
        disp_w = self.canvas.width()
        disp_h = self.canvas.height()

        scale_w = frame_w / disp_w
        scale_h = frame_h / disp_h

        # Корректируем координаты с учетом масштаба
        def scale_rect(rect):
            return QRect(
                int(rect.left() * scale_w),
                int(rect.top() * scale_h),
                int(rect.width() * scale_w),
                int(rect.height() * scale_h),
            )

        r1 = scale_rect(self.current_rect1)
        r2 = scale_rect(self.current_rect2)

        preview_width = self.preview_canvas.width()
        preview_height = self.preview_canvas.height()

        # Определяем порядок — меньший по высоте сверху
        if r1.height() < r2.height():
            top_rect, bottom_rect = r1, r2
        else:
            top_rect, bottom_rect = r2, r1

        total_h = top_rect.height() + bottom_rect.height()
        if total_h == 0:
            return

        # Распределяем высоту пропорционально
        top_scaled_h = int(preview_height * (top_rect.height() / total_h))
        bottom_scaled_h = preview_height - top_scaled_h

        def crop_and_resize(r, target_w, target_h):
            x, y, w, h = r.left(), r.top(), r.width(), r.height()
            # Защита от выхода за рамки исходного кадра
            x = max(0, min(x, frame_w - 1))
            y = max(0, min(y, frame_h - 1))
            w = min(w, frame_w - x)
            h = min(h, frame_h - y)
            if w <= 0 or h <= 0:
                return None
            crop = self.frame[y:y + h, x:x + w]
            if crop.size == 0:
                return None
            return cv2.resize(crop, (target_w, target_h), interpolation=cv2.INTER_AREA)

        top_img = crop_and_resize(top_rect, preview_width, top_scaled_h)
        bottom_img = crop_and_resize(bottom_rect, preview_width, bottom_scaled_h)

        if top_img is None or bottom_img is None:
            return

        combined = np.vstack((top_img, bottom_img))
        combined_rgb = cv2.cvtColor(combined, cv2.COLOR_BGR2RGB)

        h, w, ch = combined_rgb.shape
        bytes_per_line = ch * w
        qimg = QImage(combined_rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)

        self.preview_canvas.setPixmap(QPixmap.fromImage(qimg))

    def startCutting(self):
        if not self.video_path or not self.save_folder:
            QMessageBox.warning(self, "Внимание", "Выберите видео и папку для сохранения")
            return

        rects = self.get_scaled_rectangles()
        if rects is None or None in rects:
            QMessageBox.warning(self, "Ошибка", "Не удалось получить координаты областей для обработки")
            return
            
        rect1, rect2 = rects
        
        # Проверяем, что прямоугольники были получены
        if rect1 is None or rect2 is None:
            QMessageBox.warning(self, "Ошибка", "Неверные координаты областей")
            return
        
        # Выводим отладочную информацию
        print(f"Зеленая область (scaled): x={rect1.x()}, y={rect1.y()}, w={rect1.width()}, h={rect1.height()}")
        print(f"Красная область (scaled): x={rect2.x()}, y={rect2.y()}, w={rect2.width()}, h={rect2.height()}")
        print(f"Размер видео: {self.original_video_size[0]}x{self.original_video_size[1]}")
        
        def check_bounds(rect, name):
            if (rect.x() < 0 or rect.y() < 0 or 
                rect.x() + rect.width() > self.original_video_size[0] or
                rect.y() + rect.height() > self.original_video_size[1]):
                QMessageBox.warning(self, "Ошибка", 
                                  f"{name} область выходит за границы кадра\n"
                                  f"X: {rect.x()}, Y: {rect.y()}\n"
                                  f"Ширина: {rect.width()}, Высота: {rect.height()}\n"
                                  f"Размер видео: {self.original_video_size[0]}x{self.original_video_size[1]}")
                return False
            return True

        if not check_bounds(rect1, "Зеленая") or not check_bounds(rect2, "Красная"):
            return
        
        # Определяем выходное разрешение 9:16 (1080x1920)
        out_width, out_height = 1080, 1920
        
        # Принудительно устанавливаем порядок - зеленая область сверху
        top_rect, bottom_rect = rect1, rect2
        
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.load_btn.setEnabled(False)
        self.save_btn.setEnabled(False)

        self.cutting_thread = VideoCuttingThread(
            self.video_path,
            self.save_folder,
            top_rect,  # Зеленая область теперь всегда сверху
            bottom_rect,  # Красная область теперь всегда снизу
            out_width,
            out_height
        )
        self.cutting_thread.progress_update.connect(self.progress.setValue)
        self.cutting_thread.finished.connect(self.cuttingFinished)
        self.cutting_thread.start()

    def stopCutting(self):
        if self.cutting_thread and self.cutting_thread.isRunning():
            self.cutting_thread.terminate()
            self.cutting_thread.wait()
            logger.info("Нарезка видео остановлена пользователем")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.load_btn.setEnabled(True)
            self.save_btn.setEnabled(True)

    def cuttingFinished(self):
        if hasattr(self.cutting_thread, 'error') and self.cutting_thread.error:
            QMessageBox.critical(self, "Ошибка", f"Не удалось обработать видео:\n{self.cutting_thread.error}")
        else:
            QMessageBox.information(self, "Готово", "Видео успешно обработано!")
        
        # Сбрасываем состояние кнопок
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.load_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        self.progress.setValue(0)

class DraggableRect(QWidget):
    def __init__(self, parent, rect: QRect, controller=None, color=QColor(0, 255, 0, 120)):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.controller = controller
        self.color = color
        self.dragging = False
        self.resizing = False
        self.resize_margin = 10
        self.drag_start_pos = QPoint()
        self.rect_start_pos = QPoint()
        self.setGeometry(rect)
        
        # Эффекты для красоты
        self.setStyleSheet("""
            border: 2px dashed rgba(255, 255, 255, 0.5);
            border-radius: 4px;
        """)
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self.color.darker(), 2)
        painter.setPen(pen)
        painter.setBrush(self.color)

        rect = QRect(0, 0, self.width(), self.height())
        painter.drawRect(rect)

        resize_rect = QRect(
            rect.right() - self.resize_margin,
            rect.bottom() - self.resize_margin,
            self.resize_margin,
            self.resize_margin
        )
        painter.fillRect(resize_rect, self.color.darker(200))
        
    def mousePressEvent(self, event):
        """Обработка нажатия мыши для изменения размера прямоугольников"""
        pos = event.position()
        for item in [self.area1_item, self.area2_item]:
            if item.contains(item.mapFromScene(pos)):
                # Проверяем, было ли нажатие в углу для изменения размера
                rect = item.rect()
                corner_rect = QRectF(rect.right()-10, rect.bottom()-10, 10, 10)
                if corner_rect.contains(item.mapFromScene(pos)):
                    self.resizing_item = item
                    self.resize_start_pos = pos
                    self.resize_start_rect = rect
                    return
                
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Обработка перемещения мыши для изменения размера прямоугольников"""
        if hasattr(self, 'resizing_item') and self.resizing_item:
            pos = event.position()
            delta = pos - self.resize_start_pos
            
            # Определяем, это зеленая или красная область
            is_green_area = (self.resizing_item == self.controller.area1_item)
            
            if is_green_area:
                # Для зеленой области - только увеличение с сохранением пропорций
                new_width = max(
                    self.controller.current_min_width,
                    self.resize_start_rect.width() + delta.x()
                )
                new_height = new_width / (16/9)
            else:
                # Для красной области - обычное изменение размера
                new_width = max(50, self.resize_start_rect.width() + delta.x())
                new_height = max(50, self.resize_start_rect.height() + delta.y())
            
            new_rect = QRectF(
                self.resize_start_rect.x(),
                self.resize_start_rect.y(),
                new_width,
                new_height
            )
            
            self.resizing_item.setRect(new_rect)
            self.controller.on_rect_changed()
            return
            
        super().mouseMoveEvent(event)


    def mouseReleaseEvent(self, event):
        """Обработка отпускания мыши после изменения размера"""
        if hasattr(self, 'resizing_item'):
            del self.resizing_item
        super().mouseReleaseEvent(event)

class VideoCuttingThread(QThread):
    progress_update = pyqtSignal(int)
    
    def __init__(self, video_path, save_folder, rect1, rect2, out_width=1080, out_height=1920):
        super().__init__()
        self.video_path = video_path
        self.save_folder = save_folder
        self.rect1 = rect1  # Зеленая область (верх)
        self.rect2 = rect2  # Красная область (низ)
        self.out_width = out_width
        self.out_height = out_height
        self.top_height = int(out_height * 0.3)  # 30% высоты
        self.bottom_height = out_height - self.top_height  # 70% высоты
        self.error = None
        self.running = True

    def run(self):
        try:
            # Проверяем наличие FFmpeg
            try:
                subprocess.run(['ffmpeg', '-version'], check=True, 
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except FileNotFoundError:
                raise Exception("FFmpeg не найден. Установите FFmpeg и добавьте в PATH")

            # Генерируем уникальное имя файла
            base_name = os.path.splitext(os.path.basename(self.video_path))[0]
            output_name = f"vertical_{base_name}.mp4"
            output_path = os.path.join(self.save_folder, output_name)

            # Создаем фильтр FFmpeg
            filter_complex = (
                f"[0:v]crop={self.rect1.width()}:{self.rect1.height()}:{self.rect1.x()}:{self.rect1.y()}," +
                f"scale={self.out_width}:{self.top_height}," +
                f"setsar=1[top];" +
                f"[0:v]crop={self.rect2.width()}:{self.rect2.height()}:{self.rect2.x()}:{self.rect2.y()}," +
                f"scale={self.out_width}:{self.bottom_height}," +
                f"setsar=1[bottom];" +
                f"[top][bottom]vstack=inputs=2," +
                f"format=yuv420p[outv]"
            )
            
            cmd = [
                'ffmpeg',
                '-y',
                '-i', self.video_path,
                '-filter_complex', filter_complex,
                '-map', '[outv]',
                '-c:v', 'libx264',
                '-preset', 'fast',
                '-crf', '23',
                '-movflags', '+faststart',
                '-map', '0:a?',  # Опциональный аудиопоток
                '-c:a', 'copy',
                output_path
            ]
            
            logger.info(f"Запуск команды FFmpeg: {' '.join(cmd)}")
            
            # Запускаем процесс
            process = subprocess.Popen(cmd, 
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE,
                                     universal_newlines=True,
                                     encoding='utf-8',
                                     errors='replace')
            
            # Отслеживаем прогресс
            duration = None
            while self.running:
                line = process.stderr.readline()
                if not line and process.poll() is not None:
                    break
                    
                # Парсим длительность видео
                if duration is None and 'Duration:' in line:
                    try:
                        time_str = line.split('Duration:')[1].split(',')[0].strip()
                        h, m, s = time_str.split(':')
                        duration = float(h) * 3600 + float(m) * 60 + float(s)
                    except:
                        pass
                
                # Парсим текущее время
                elif 'time=' in line:
                    try:
                        time_str = line.split('time=')[1].split(' ')[0]
                        h, m, s = time_str.split(':')
                        current_time = float(h) * 3600 + float(m) * 60 + float(s)
                        if duration:
                            progress = int((current_time / duration) * 100)
                            self.progress_update.emit(progress)
                    except:
                        pass
            
            if process.returncode != 0:
                raise Exception(f"Ошибка FFmpeg: {process.stderr.read()}")
            
            logger.info(f"Видео успешно сохранено: {output_path}")
            self.progress_update.emit(100)
            
        except Exception as e:
            self.error = str(e)
            logger.error(f"Ошибка обработки видео: {self.error}")
            self.progress_update.emit(0)
        
    def stop(self):
        self.running = False
        
    def add_audio(self, input_path, output_path, start_time):
        cmd = [
            'ffmpeg',
            '-y',
            '-i', input_path,  # Видео без звука
            '-ss', str(start_time),
            '-i', self.video_path,  # Оригинальное видео с звуком
            '-t', str(self.part_duration),
            '-c:v', 'copy',  # Копируем видео без перекодировки
            '-c:a', 'aac', '-b:a', '192k',  # Кодируем аудио в AAC
            '-map', '0:v:0',  # Берем видео из первого файла
            '-map', '1:a:0',  # Берем аудио из второго файла
            '-shortest',  # Обрезаем по длительности самого короткого потока
            output_path
        ]
        logger.info(f"Добавление аудио к видео: {output_path} (время начала: {start_time} сек)")
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            logger.info("Аудио успешно добавлено")
        except subprocess.CalledProcessError as e:
            logger.error(f"Ошибка при добавлении аудио: {e.stderr.decode()}")
            # Альтернативная команда на случай ошибки
            alt_cmd = [
                'ffmpeg',
                '-y',
                '-i', input_path,
                '-i', self.video_path,
                '-ss', str(start_time),
                '-t', str(self.part_duration),
                '-c:v', 'copy',
                '-c:a', 'copy',
                '-map', '0:v:0',
                '-map', '1:a:0',
                output_path
            ]
            subprocess.run(alt_cmd, check=True)
            
class YouTubeUploadTab(QWidget):
    def __init__(self):
        super().__init__()
        self.token_file = 'token.json'  # Выносим путь к файлу в переменную
        self.setup_ui()
        self.youtube_service = None
        self.credentials = None
        self.check_existing_credentials()  # Проверяем авторизацию при старте
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # Авторизация
        auth_group = QGroupBox("YouTube Authorization")
        auth_layout = QVBoxLayout()
        
        self.auth_btn = QPushButton("Authorize with YouTube")
        self.auth_btn.clicked.connect(self.authenticate_youtube)
        auth_layout.addWidget(self.auth_btn)
        
        self.auth_status = QLabel("Not authenticated")
        auth_layout.addWidget(self.auth_status)
        
        auth_group.setLayout(auth_layout)
        layout.addWidget(auth_group)
        
        # Загрузка видео
        upload_group = QGroupBox("Video Upload")
        upload_layout = QVBoxLayout()
        
        self.select_video_btn = QPushButton("Select Video")
        self.select_video_btn.clicked.connect(self.select_video)
        upload_layout.addWidget(self.select_video_btn)
        
        self.video_path_label = QLabel("No video selected")
        upload_layout.addWidget(self.video_path_label)
        
        # Поля для метаданных
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Video title")
        upload_layout.addWidget(self.title_edit)
        
        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Video description")
        upload_layout.addWidget(self.description_edit)
        
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("Tags (comma separated)")
        upload_layout.addWidget(self.tags_edit)
        
        # Категории YouTube
        self.category_combo = QComboBox()
        self.category_combo.addItem("Gaming", "20")  # 20 - категория Gaming
        self.category_combo.addItem("Entertainment", "24")
        self.category_combo.addItem("Education", "27")
        upload_layout.addWidget(self.category_combo)
        
        # Настройки приватности
        self.privacy_combo = QComboBox()
        self.privacy_combo.addItem("Public", "public")
        self.privacy_combo.addItem("Private", "private")
        self.privacy_combo.addItem("Unlisted", "unlisted")
        upload_layout.addWidget(self.privacy_combo)
        
        self.upload_btn = QPushButton("Upload Video")
        self.upload_btn.clicked.connect(self.upload_video)
        self.upload_btn.setEnabled(False)
        upload_layout.addWidget(self.upload_btn)
        
        self.progress_bar = QProgressBar()
        upload_layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("Ready")
        upload_layout.addWidget(self.status_label)
        
        upload_group.setLayout(upload_layout)
        layout.addWidget(upload_group)
        
        # Проверяем существующие учетные данные
        self.check_existing_credentials()
    
    def check_existing_credentials(self):
        """Проверяем и обновляем учетные данные при необходимости"""
        try:
            if os.path.exists(self.token_file):
                self.credentials = Credentials.from_authorized_user_file(self.token_file)
                
                # Если токен истек, но есть refresh token - обновляем
                if self.credentials and self.credentials.expired and self.credentials.refresh_token:
                    try:
                        self.credentials.refresh(Request())
                        self.save_credentials()  # Сохраняем обновленные учетные данные
                    except Exception as refresh_error:
                        logger.error(f"Error refreshing token: {refresh_error}")
                        os.remove(self.token_file)
                        return False
                
                if self.credentials and not self.credentials.expired:
                    self.auth_status.setText("Authenticated")
                    self.upload_btn.setEnabled(True)
                    return True
        except Exception as e:
            logger.error(f"Error loading credentials: {e}")
            # Если что-то пошло не так - удаляем битый файл
            if os.path.exists(self.token_file):
                os.remove(self.token_file)
        return False
        
    def save_credentials(self):
        """Сохраняем учетные данные в файл"""
        try:
            with open(self.token_file, 'w') as token:
                token.write(self.credentials.to_json())
        except Exception as e:
            logger.error(f"Error saving credentials: {e}")       
    
    def authenticate_youtube(self):
        # Загружаем клиентские секреты из файла .env
        client_id = os.getenv('YOUTUBE_CLIENT_ID')
        client_secret = os.getenv('YOUTUBE_CLIENT_SECRET')
        
        if not client_id or not client_secret:
            QMessageBox.critical(self, "Error", "YouTube API credentials not found in .env file")
            return
            
        # Настройки OAuth 2.0
        scopes = ["https://www.googleapis.com/auth/youtube.upload"]
        
        # Создаем поток для аутентификации
        self.auth_thread = YouTubeAuthThread(client_id, client_secret, scopes)
        self.auth_thread.finished.connect(self.handle_auth_result)
        self.auth_thread.start()
        self.auth_status.setText("Authenticating...")
        self.auth_btn.setEnabled(False)

    def handle_auth_result(self, success, credentials, error_message):
        if success:
            self.credentials = credentials
            # Сохраняем учетные данные для будущего использования
            with open('token.json', 'w') as token:
                token.write(self.credentials.to_json())
                
            self.auth_status.setText("Authenticated")
            self.upload_btn.setEnabled(True)
            QMessageBox.information(self, "Success", "Successfully authenticated with YouTube")
        else:
            if "Authorization cancelled" in error_message or "access_denied" in error_message:
                self.auth_status.setText("Authentication cancelled")
            else:
                QMessageBox.critical(self, "Error", f"Authentication failed: {error_message}")
                self.auth_status.setText("Authentication failed")
        
        self.auth_btn.setEnabled(True)
    
    def get_youtube_service(self):
        if not self.credentials:
            return None
            
        if self.credentials.expired and self.credentials.refresh_token:
            self.credentials.refresh(Request())
            
        return build('youtube', 'v3', credentials=self.credentials)
    
    def select_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Video", "", 
            "Video Files (*.mp4 *.avi *.mov)"
        )
        
        if path:
            self.video_path = path
            self.video_path_label.setText(os.path.basename(path))
            
            # Предлагаем название по имени файла
            filename = os.path.splitext(os.path.basename(path))[0]
            self.title_edit.setText(filename.replace('_', ' '))
            
            # Включаем кнопку загрузки если есть авторизация
            if self.check_existing_credentials():
                self.upload_btn.setEnabled(True)
    
    def upload_video(self):
        if not hasattr(self, 'video_path') or not self.video_path:
            QMessageBox.warning(self, "Warning", "Please select a video first")
            return
            
        # Получаем метаданные
        title = self.title_edit.text()
        description = self.description_edit.toPlainText()
        tags = [tag.strip() for tag in self.tags_edit.text().split(',') if tag.strip()]
        category_id = self.category_combo.currentData()
        privacy_status = self.privacy_combo.currentData()
        
        if not title:
            QMessageBox.warning(self, "Warning", "Please enter a title for the video")
            return
            
        # Создаем YouTube сервис
        self.youtube_service = self.get_youtube_service()
        if not self.youtube_service:
            QMessageBox.critical(self, "Error", "Not authenticated with YouTube")
            return
            
        # Запускаем поток для загрузки
        self.upload_thread = YouTubeUploadThread(
            self.youtube_service,
            self.video_path,
            title,
            description,
            tags,
            category_id,
            privacy_status
        )
        self.upload_thread.progress_updated.connect(self.update_progress)
        self.upload_thread.finished.connect(self.upload_finished)
        self.upload_thread.start()
        
        self.upload_btn.setEnabled(False)
        self.status_label.setText("Uploading...")
    
    def update_progress(self, progress):
        self.progress_bar.setValue(progress)
    
    def upload_finished(self, success, message):
        if success:
            QMessageBox.information(self, "Success", "Video uploaded successfully!")
            self.status_label.setText("Upload complete")
        else:
            QMessageBox.critical(self, "Error", f"Upload failed: {message}")
            self.status_label.setText("Upload failed")
            
        self.upload_btn.setEnabled(True)
        self.progress_bar.setValue(0)            

class YouTubeAuthThread(QThread):
    finished = pyqtSignal(bool, object, str)  # success, credentials, error_message
    def __init__(self, client_id, client_secret, scopes):
        super().__init__()
        self.client_id = client_id
        self.client_secret = client_secret
        self.scopes = scopes
    
    def run(self):
        try:
            # Поток аутентификации
            flow = InstalledAppFlow.from_client_config(
                {
                    "installed": {
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://accounts.google.com/o/oauth2/token",
                        "redirect_uris": ["http://localhost"]
                    }
                },
                scopes=self.scopes
            )
            
            credentials = flow.run_local_server(port=0, open_browser=True)
            self.finished.emit(True, credentials, "")
            
        except Exception as e:
            self.finished.emit(False, None, str(e))
 
class YouTubeUploadThread(QThread):
    progress_updated = pyqtSignal(int)
    finished = pyqtSignal(bool, str)
    
    def __init__(self, youtube_service, video_path, title, description, tags, category_id, privacy_status):
        super().__init__()
        self.youtube_service = youtube_service
        self.video_path = video_path
        self.title = title
        self.description = description
        self.tags = tags
        self.category_id = category_id
        self.privacy_status = privacy_status
        self.running = True
        
    def run(self):
        try:
            # Создаем тело запроса
            body = {
                'snippet': {
                    'title': self.title,
                    'description': self.description,
                    'tags': self.tags,
                    'categoryId': self.category_id
                },
                'status': {
                    'privacyStatus': self.privacy_status,
                    'selfDeclaredMadeForKids': False
                }
            }
            
            # Создаем медиа объект для загрузки
            media = MediaFileUpload(
                self.video_path,
                chunksize=-1,
                resumable=True,
                mimetype='video/*'
            )
            
            # Запускаем загрузку
            request = self.youtube_service.videos().insert(
                part=','.join(body.keys()),
                body=body,
                media_body=media
            )
            
            response = None
            while self.running and response is None:
                status, response = request.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    self.progress_updated.emit(progress)
            
            if response:
                self.finished.emit(True, "Upload completed")
            else:
                self.finished.emit(False, "Upload was cancelled")
                
        except Exception as e:
            self.finished.emit(False, str(e))
    
    def stop(self):
        self.running = False
        
if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Устанавливаем стиль Fusion для красивого темного интерфейса
    app.setStyle("Fusion")
    
    # Создаем и показываем главное окно
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())