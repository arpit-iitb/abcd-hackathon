from typing import Any, Dict, List, Tuple, Type

from pydantic import BaseModel, ValidationError

from .models import ErrorDetail


def validate_model(model: Type[BaseModel], data: Dict[str, Any]) -> Tuple[BaseModel, List[ErrorDetail]]:
    try:
        parsed = model.model_validate(data)
        return parsed, []
    except ValidationError as exc:
        errors = []
        for err in exc.errors():
            errors.append(
                ErrorDetail(
                    code=err.get("type", "validation_error"),
                    message=err.get("msg", "Invalid input"),
                    field=".".join(str(item) for item in err.get("loc", [])),
                )
            )
        return None, errors
