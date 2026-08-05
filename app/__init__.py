"""Botik Sonya application package."""

from app import engine as _engine
from app.streaming_prefix import install_static_speaker_prefix

install_static_speaker_prefix(_engine)
