import json
from pathlib import Path
from typing import Any, Dict, Type, TypeVar

from pydantic import BaseModel, ValidationError


ModelT = TypeVar("ModelT", bound=BaseModel)


def load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=True, indent=2)


def load_model(path: str, model: Type[ModelT]) -> ModelT:
    payload = load_json(path)
    return model.model_validate(payload)


def parse_model(payload: Any, model: Type[ModelT]) -> ModelT:
    return model.model_validate(payload)


def dump_model(model: BaseModel) -> Dict[str, Any]:
    return model.model_dump(mode="json")


def dump_model_json(model: BaseModel) -> str:
    return dump_json(dump_model(model))


def validation_error_to_dict(error: ValidationError) -> Dict[str, Any]:
    return {
        "errors": error.errors(),
    }
