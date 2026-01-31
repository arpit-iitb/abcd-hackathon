from pathlib import Path
from typing import Any, Dict

import yaml


def load_yaml(path: str) -> Dict[str, Any]:
    content = Path(path).read_text(encoding="utf-8")
    return yaml.safe_load(content) or {}
