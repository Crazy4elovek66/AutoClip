# models.py
from dataclasses import dataclass
from typing import Optional

@dataclass
class PendingClip:
    file_path: str
    clip_data: dict
    processed_path: str
    original_path: Optional[str] = None  # Добавляем новое поле
    sent_for_approval: bool = False
    
    def to_dict(self):
        return {
            "file_path": self.file_path,
            "clip_data": self.clip_data,
            "processed_path": self.processed_path,
            "original_path": self.original_path,
            "sent_for_approval": self.sent_for_approval
        }