"""Botik Sonya application package."""

from app import engine as _engine
from app.media_retry import install_media_retry
from app.photo_normalization import install_photo_normalization
from app.streaming_prefix import install_static_speaker_prefix
from app.video_normalization import install_video_normalization

install_static_speaker_prefix(_engine)
install_photo_normalization(_engine)
install_video_normalization(_engine)
install_media_retry(_engine)
