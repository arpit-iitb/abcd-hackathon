from typing import Any, Dict

from .config_loader import load_yaml


def load_prompts(path: str) -> Dict[str, Any]:
    return load_yaml(path)
