from pathlib import Path

from app.roadmap import load_roadmap


def test_sample_roadmap_is_valid() -> None:
    roadmap = load_roadmap(Path("roadmap/quest.json"))
    assert roadmap.meta.intro_step_id == "intro"
    assert len(roadmap.steps) == 3
