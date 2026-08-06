"""Botik Sonya application package."""

from app import engine as _engine
from app import storage as _storage
from app.media_retry import install_media_retry
from app.memory_modes import install_memory_modes
from app.memory_read_ack import install_memory_read_ack
from app.memory_storage_order import install_memory_storage_order
from app.photo_normalization import install_photo_normalization
from app.streaming_prefix import install_static_speaker_prefix
from app.video_normalization import install_video_normalization

install_memory_storage_order(_storage)
install_memory_modes(_engine)
install_memory_read_ack(_engine)
install_static_speaker_prefix(_engine)
install_photo_normalization(_engine)
install_video_normalization(_engine)
install_media_retry(_engine)
