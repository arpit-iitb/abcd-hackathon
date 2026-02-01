from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

from jinja2 import Template
import yaml


def _load_yaml(path: Path) -> Dict[str, Any]:
    content = path.read_text(encoding="utf-8")
    return yaml.safe_load(content) or {}


def load_prompts(prompt_dir: str) -> Dict[str, Dict[str, str]]:
    base = Path(prompt_dir)
    raw: Dict[str, Dict[str, Any]] = {}
    for path in sorted(base.glob("*.yaml")):
        raw[path.stem] = _load_yaml(path)

    common = raw.get("common", {})
    common_system = "\n".join(
        part for part in [common.get("system", ""), common.get("output_schema", "")] if part
    ).strip()

    merged: Dict[str, Dict[str, str]] = {}
    for name, content in raw.items():
        if name == "common":
            continue
        system = content.get("system", "").strip()
        if common_system:
            system = f"{common_system}\n\n{system}" if system else common_system
        merged[name] = {
            "system": system,
            "user_template": content.get("user_template", ""),
        }

    return merged


def render_prompt(
    prompts: Dict[str, Dict[str, str]],
    agent_name: str,
    input_json: str,
    config_json: str,
) -> Tuple[str, str]:
    if agent_name not in prompts:
        raise ValueError(f"Unknown agent prompt: {agent_name}")

    system_prompt = prompts[agent_name]["system"]
    template = Template(prompts[agent_name]["user_template"])
    user_prompt = template.render(input_json=input_json, config_json=config_json)
    return system_prompt, user_prompt
