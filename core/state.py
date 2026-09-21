"""Persistent State Manager — per-component verified status, not "didn't crash = success"."""
import json
import time
from pathlib import Path


class ModuleState:
    def __init__(self, state_dir):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def save(self, component_id, status, checks=None, detail=""):
        payload = {"status": status, "checks": checks or {}, "detail": detail,
                   "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        (self.state_dir / f"{component_id}.json").write_text(json.dumps(payload, indent=2))
        return payload

    def load(self, component_id):
        path = self.state_dir / f"{component_id}.json"
        if not path.exists():
            return {"status": "not_installed", "checks": {}, "detail": "never run"}
        try:
            return json.loads(path.read_text())
        except Exception:
            return {"status": "unknown", "checks": {}, "detail": "state file unreadable"}

    def all_status(self):
        return {f.stem: self.load(f.stem) for f in sorted(self.state_dir.glob("*.json"))}
