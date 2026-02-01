from __future__ import annotations

import json
from typing import Any, Dict, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from app.openai_client import get_llm_client, get_model_config
from app.prompt_loader import render_prompt
from app.state import AgentResultBase, ErrorItem


def _extract_json(content: str) -> Optional[Dict[str, Any]]:
    if not content:
        return None
    content = content.strip()
    if content.startswith("{") and content.endswith("}"):
        try:
            return json.loads(content)
        except Exception:
            pass
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = content[start : end + 1]
        try:
            return json.loads(snippet)
        except Exception:
            return None
    return None


def _strip_image_fields(obj: Any) -> Any:
    if isinstance(obj, dict):
        cleaned: Dict[str, Any] = {}
        for key, value in obj.items():
            if str(key).lower() in {"image_base64"}:
                cleaned[key] = "<image_attached>"
            else:
                cleaned[key] = _strip_image_fields(value)
        return cleaned
    if isinstance(obj, list):
        return [_strip_image_fields(item) for item in obj]
    return obj


def llm_enabled(config: Dict[str, Any], agent_name: str) -> bool:
    llm_cfg = config.get("llm") if isinstance(config, dict) else {}
    if not isinstance(llm_cfg, dict):
        return False
    agents_cfg = llm_cfg.get("agents")
    if isinstance(agents_cfg, dict) and agent_name in agents_cfg:
        return bool(agents_cfg.get(agent_name))
    return bool(llm_cfg.get("default_use_llm", False))


def resolve_model_config(config: Dict[str, Any], agent_name: str) -> Dict[str, Any]:
    base = get_model_config()
    models_cfg = config.get("models") if isinstance(config, dict) else {}
    if isinstance(models_cfg, dict):
        agent_cfg = models_cfg.get(agent_name)
        default_cfg = models_cfg.get("default")
        if isinstance(default_cfg, dict):
            base = {**base, **default_cfg}
        if isinstance(agent_cfg, dict):
            base = {**base, **agent_cfg}
    return base


def run_llm_agent(
    agent_name: str,
    input_payload: Dict[str, Any],
    config: Dict[str, Any],
    prompts: Dict[str, Dict[str, str]],
    llm_client: Optional[Any] = None,
) -> Dict[str, Any]:
    try:
        prompt_input = input_payload
        if agent_name == "id_verification":
            prompt_input = _strip_image_fields(input_payload)

        system_prompt, user_prompt = render_prompt(
            prompts,
            agent_name,
            input_json=json.dumps(prompt_input, ensure_ascii=True),
            config_json=json.dumps(config, ensure_ascii=True),
        )
        model_cfg = resolve_model_config(config, agent_name)
        llm = llm_client or get_llm_client(model=model_cfg.get("model"), temperature=model_cfg.get("temperature"))
        if agent_name == "id_verification":
            docs = input_payload.get("documents", {}) if isinstance(input_payload, dict) else {}
            aadhaar_b64 = (docs.get("aadhaar_doc") or {}).get("image_base64")
            selfie_b64 = (docs.get("selfie_doc") or {}).get("image_base64")
            content_parts = [{"type": "text", "text": user_prompt}]
            if aadhaar_b64:
                content_parts.append(
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{aadhaar_b64}"}}
                )
            if selfie_b64:
                content_parts.append(
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{selfie_b64}"}}
                )
            response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=content_parts)])
        else:
            response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
        content = response.content if hasattr(response, "content") else str(response)
        parsed = _extract_json(content)
        if not parsed:
            error = ErrorItem(
                code="llm_parse_error",
                message="Failed to parse JSON output from LLM",
                where="llm_response",
                severity="fatal",
            )
            result = AgentResultBase(
                agent_name=agent_name,
                status="error",
                errors=[error],
                missing_data=[],
                rationale_summary=["LLM output was not valid JSON."],
                evidence={},
                calculations={},
                confidence=0.0,
                output={},
            )
            return result.model_dump(mode="json")

        parsed["agent_name"] = agent_name
        validated = AgentResultBase.model_validate(parsed)
        return validated.model_dump(mode="json")
    except ValidationError as exc:
        error = ErrorItem(
            code="llm_validation_error",
            message=str(exc),
            where="llm_response",
            severity="fatal",
        )
        result = AgentResultBase(
            agent_name=agent_name,
            status="error",
            errors=[error],
            missing_data=[],
            rationale_summary=["LLM output failed schema validation."],
            evidence={},
            calculations={},
            confidence=0.0,
            output={},
        )
        return result.model_dump(mode="json")
    except Exception as exc:
        error = ErrorItem(
            code="llm_runtime_error",
            message=str(exc),
            where="llm_call",
            severity="fatal",
        )
        result = AgentResultBase(
            agent_name=agent_name,
            status="error",
            errors=[error],
            missing_data=[],
            rationale_summary=["LLM invocation failed."],
            evidence={},
            calculations={},
            confidence=0.0,
            output={},
        )
        return result.model_dump(mode="json")
