from __future__ import annotations

import json
from pathlib import Path

from app.models import Roadmap


def load_roadmap(path: Path) -> Roadmap:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return Roadmap.model_validate(payload)
