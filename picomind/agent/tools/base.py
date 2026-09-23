"""Base class and validation for agent tools."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    timeout_seconds: float | None = 60.0

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any:
        raise NotImplementedError

    def timeout_for(self, params: dict[str, Any]) -> float | None:
        """Return the maximum execution time for this call."""

        return self.timeout_seconds

    def to_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def cast_params(self, params: dict[str, Any]) -> dict[str, Any]:
        schema = self.parameters
        properties = schema.get("properties", {})
        result = dict(params)
        for key, value in list(result.items()):
            target = properties.get(key, {}).get("type")
            if target == "integer" and isinstance(value, str):
                try:
                    result[key] = int(value)
                except ValueError:
                    pass
            elif target == "number" and isinstance(value, str):
                try:
                    result[key] = float(value)
                except ValueError:
                    pass
            elif target == "boolean" and isinstance(value, str):
                if value.lower() in {"true", "1", "yes"}:
                    result[key] = True
                elif value.lower() in {"false", "0", "no"}:
                    result[key] = False
            elif target == "string" and value is not None:
                result[key] = str(value)
        return result

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        if not isinstance(params, dict):
            return ["参数必须是 JSON 对象"]
        schema = self.parameters
        errors: list[str] = []
        for key in schema.get("required", []):
            if key not in params:
                errors.append(f"缺少必填参数：{key}")
        properties = schema.get("properties", {})
        for key, value in params.items():
            expected = properties.get(key, {}).get("type")
            if expected == "string" and not isinstance(value, str):
                errors.append(f"{key} 必须是字符串")
            elif expected == "integer" and (
                not isinstance(value, int) or isinstance(value, bool)
            ):
                errors.append(f"{key} 必须是整数")
            elif expected == "number" and (
                not isinstance(value, (int, float)) or isinstance(value, bool)
            ):
                errors.append(f"{key} 必须是数字")
            elif expected == "boolean" and not isinstance(value, bool):
                errors.append(f"{key} 必须是布尔值")
            elif expected == "array" and not isinstance(value, list):
                errors.append(f"{key} 必须是数组")
            elif expected == "object" and not isinstance(value, dict):
                errors.append(f"{key} 必须是对象")
            if "minimum" in properties.get(key, {}):
                minimum = properties[key]["minimum"]
                if isinstance(value, (int, float)) and value < minimum:
                    errors.append(f"{key} 必须大于等于 {minimum}")
            if "maximum" in properties.get(key, {}):
                maximum = properties[key]["maximum"]
                if isinstance(value, (int, float)) and value > maximum:
                    errors.append(f"{key} 必须小于等于 {maximum}")
        return errors
