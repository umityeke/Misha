from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any


class RiskLevel(str, Enum):
    READ_ONLY = "read_only"
    WRITE = "write"
    EXTERNAL_IMPACT = "external_impact"
    DESTRUCTIVE = "destructive"


_JSON_TYPES: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    required: MappingProxyType[str, type]
    optional: MappingProxyType[str, type]
    risk: RiskLevel
    timeout_seconds: int
    external_impact: bool = False
    verifier: str = "output_contract"
    approval_required: bool = False
    idempotent: bool = False
    max_attempts: int = 1
    rollback: str = "not_supported"

    @classmethod
    def create(
        cls,
        name: str,
        *,
        required: dict[str, type] | None = None,
        optional: dict[str, type] | None = None,
        risk: RiskLevel = RiskLevel.READ_ONLY,
        timeout_seconds: int = 30,
        external_impact: bool = False,
        verifier: str = "output_contract",
        approval_required: bool | None = None,
        idempotent: bool = False,
        max_attempts: int | None = None,
        rollback: str = "not_supported",
    ) -> "ToolSpec":
        verifier_name = (
            "external_confirmation"
            if external_impact and verifier == "output_contract"
            else verifier
        )
        return cls(
            name=name,
            required=MappingProxyType(dict(required or {})),
            optional=MappingProxyType(dict(optional or {})),
            risk=risk,
            timeout_seconds=max(1, min(int(timeout_seconds), 900)),
            external_impact=bool(external_impact),
            verifier=str(verifier_name),
            approval_required=(
                risk is not RiskLevel.READ_ONLY or bool(external_impact)
                if approval_required is None else bool(approval_required)
            ),
            idempotent=bool(idempotent),
            max_attempts=max(
                1,
                min(
                    int(max_attempts if max_attempts is not None else (3 if idempotent else 1)),
                    3,
                ),
            ),
            rollback=str(rollback or "not_supported"),
        )

    @property
    def allowed_fields(self) -> frozenset[str]:
        return frozenset((*self.required, *self.optional))

    def json_schema(self) -> dict[str, Any]:
        properties = {
            field: {"type": _JSON_TYPES[value_type]}
            for field, value_type in {**self.required, **self.optional}.items()
        }
        return {
            "type": "object",
            "properties": properties,
            "required": list(self.required),
            "additionalProperties": False,
        }

    def validate(self, parameters: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(parameters, dict):
            raise ValueError(f"{self.name} parameters must be an object.")
        unknown = sorted(set(parameters) - self.allowed_fields)
        if unknown:
            raise ValueError(
                f"Unknown parameter(s) for {self.name}: {', '.join(unknown)}"
            )
        missing = [field for field in self.required if field not in parameters]
        if missing:
            raise ValueError(
                f"Missing required parameter(s) for {self.name}: {', '.join(missing)}"
            )
        result = dict(parameters)
        for field, expected in {**self.required, **self.optional}.items():
            if field not in result:
                continue
            value = result[field]
            if expected is int:
                valid = isinstance(value, int) and not isinstance(value, bool)
            elif expected is float:
                valid = isinstance(value, (int, float)) and not isinstance(value, bool)
            else:
                valid = isinstance(value, expected)
            if not valid:
                raise ValueError(
                    f"Invalid type for {self.name}.{field}; expected "
                    f"{_JSON_TYPES[expected]}."
                )
            if field in self.required and isinstance(value, str) and not value.strip():
                raise ValueError(f"{self.name}.{field} cannot be empty.")
        return result


def _spec(
    name: str,
    required: dict[str, type],
    optional: dict[str, type] | None = None,
    *,
    risk: RiskLevel = RiskLevel.READ_ONLY,
    timeout: int = 30,
    external: bool = False,
    verifier: str = "output_contract",
    approval_required: bool | None = None,
    idempotent: bool = False,
    max_attempts: int | None = None,
    rollback: str = "not_supported",
) -> ToolSpec:
    return ToolSpec.create(
        name,
        required=required,
        optional=optional,
        risk=risk,
        timeout_seconds=timeout,
        external_impact=external,
        verifier=verifier,
        approval_required=approval_required,
        idempotent=idempotent,
        max_attempts=max_attempts,
        rollback=rollback,
    )


TOOL_REGISTRY = MappingProxyType({
    "respond": _spec(
        "respond", {"message": str}, verifier="exact_response", idempotent=True
    ),
    "remember_rule": _spec(
        "remember_rule", {"rule": str}, {"scope": str}, risk=RiskLevel.WRITE,
        verifier="learning_store",
    ),
    "open_app": _spec(
        "open_app", {"app_name": str}, risk=RiskLevel.EXTERNAL_IMPACT,
        verifier="process_state",
    ),
    "web_search": _spec(
        "web_search", {"query": str}, {"mode": str, "items": list, "aspect": str},
        timeout=60, idempotent=True,
    ),
    "game_updater": _spec(
        "game_updater", {"action": str},
        {"platform": str, "game_name": str, "app_id": str, "shutdown_when_done": bool},
        risk=RiskLevel.EXTERNAL_IMPACT, timeout=900, external=True,
    ),
    "browser_control": _spec(
        "browser_control", {"action": str},
        {"browser": str, "target": str, "url": str, "query": str, "engine": str,
         "selector": str, "text": str, "clear_first": bool, "direction": str,
         "amount": int, "fields": dict, "description": str, "key": str, "path": str,
         "verify_selector": str, "verify_property": str, "expected_value": str},
        risk=RiskLevel.EXTERNAL_IMPACT, timeout=120, external=True,
    ),
    "file_controller": _spec(
        "file_controller", {"action": str},
        {"path": str, "name": str, "content": str, "destination": str,
         "new_name": str, "append": bool, "extension": str, "max_results": int,
         "count": int, "recursive": bool, "transaction_id": str},
        risk=RiskLevel.WRITE, timeout=120, verifier="filesystem_state",
        rollback="encrypted_snapshot",
    ),
    "computer_settings": _spec(
        "computer_settings", {"action": str},
        {"description": str, "value": str, "confirmed": str, "text": str,
         "press_enter": bool, "key": str},
        risk=RiskLevel.EXTERNAL_IMPACT, external=True,
    ),
    "computer_control": _spec(
        "computer_control", {"action": str},
        {"text": str, "clear_first": bool, "x": int, "y": int, "x1": int,
         "y1": int, "x2": int, "y2": int, "keys": str, "key": str,
         "direction": str, "amount": int, "path": str, "description": str,
         "seconds": float, "title": str, "type": str, "field": str},
        risk=RiskLevel.EXTERNAL_IMPACT, timeout=60, external=True,
    ),
    "screen_process": _spec(
        "screen_process", {"text": str}, {"user_text": str, "angle": str},
        timeout=120, idempotent=True,
    ),
    "send_message": _spec(
        "send_message", {"receiver": str, "message_text": str, "platform": str},
        {"action": str, "allow_duplicate": bool},
        risk=RiskLevel.EXTERNAL_IMPACT, timeout=120, external=True,
    ),
    "reminder": _spec(
        "reminder", {"action": str},
        {"date": str, "time": str, "message": str, "timezone": str,
         "repeat": str, "fold": int, "reminder_id": str, "include_terminal": bool},
        risk=RiskLevel.EXTERNAL_IMPACT, external=True, verifier="scheduler_state",
    ),
    "desktop_control": _spec(
        "desktop_control", {"action": str},
        {"path": str, "task": str, "url": str, "mode": str},
        risk=RiskLevel.WRITE, timeout=120,
    ),
    "youtube_video": _spec(
        "youtube_video", {"action": str},
        {"query": str, "url": str, "save": bool, "region": str},
        risk=RiskLevel.EXTERNAL_IMPACT, timeout=120, external=True,
    ),
    "weather_report": _spec(
        "weather_report", {"city": str}, {"time": str}, timeout=60,
        idempotent=True,
    ),
    "flight_finder": _spec(
        "flight_finder", {"origin": str, "destination": str, "date": str},
        {"return_date": str, "passengers": int, "cabin": str, "save": bool},
        risk=RiskLevel.EXTERNAL_IMPACT, timeout=120, external=True,
    ),
    "code_helper": _spec(
        "code_helper", {"action": str, "description": str},
        {"language": str, "output_path": str, "file_path": str},
        risk=RiskLevel.WRITE, timeout=300,
    ),
    "developer_tools": _spec(
        "developer_tools", {"action": str},
        {"workspace": str, "file_path": str, "content": str, "query": str,
         "limit": int, "transaction_id": str},
        risk=RiskLevel.READ_ONLY, timeout=300, verifier="developer_state",
        rollback="encrypted_snapshot",
    ),
    "db_manager": _spec(
        "db_manager", {"action": str, "workspace": str, "db_path": str},
        {"query": str, "verify_query": str, "expected_json": str},
        risk=RiskLevel.WRITE, timeout=30, verifier="database_state",
        rollback="sqlite_transaction",
    ),
})


def get_tool_spec(name: str) -> ToolSpec:
    try:
        return TOOL_REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f"Unknown or disabled tool: {name}") from exc


def validate_tool_parameters(name: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return get_tool_spec(name).validate(parameters)


def planner_catalog() -> dict[str, dict[str, Any]]:
    return {
        name: {
            "parameters": spec.json_schema(),
            "risk": spec.risk.value,
            "timeout_seconds": spec.timeout_seconds,
            "external_impact": spec.external_impact,
            "verifier": spec.verifier,
            "approval_required": spec.approval_required,
            "idempotent": spec.idempotent,
            "max_attempts": spec.max_attempts,
            "rollback": spec.rollback,
        }
        for name, spec in TOOL_REGISTRY.items()
    }
