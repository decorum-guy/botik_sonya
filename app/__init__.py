"""Botik Sonya application package."""

from app import engine as _engine
from app.photo_normalization import install_photo_normalization
from app.streaming_prefix import install_static_speaker_prefix

install_static_speaker_prefix(_engine)
install_photo_normalization(_engine)
