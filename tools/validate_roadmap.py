from __future__ import annotations

import argparse
from pathlib import Path

from app.roadmap import load_roadmap


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default="roadmap/quest.json")
    args = parser.parse_args()
    roadmap = load_roadmap(Path(args.path))
    action_count = sum(len(step.actions) for step in roadmap.steps)
    print(f"OK: {roadmap.meta.title!r}, steps={len(roadmap.steps)}, actions={action_count}")


if __name__ == "__main__":
    main()
