"""Offline evidence for one interaction, without inferring cross-layer success."""

from __future__ import annotations

LAYERS = {
    "keyboard_delivery": "Windows-origin keyboard input reaches Linux (not applicable to a braille-only gesture)",
    "linux_focus": "Linux focus and caret match the intended object and position",
    "nvda_speech": "Windows NVDA speech events or audible output match the expected feedback",
    "semantic_braille": "The current Linux semantic snapshot reaches Windows NVDA",
    "physical_braille": "The user confirms the intended content and cursor on the physical display",
}
SOURCES = {
    "keyboard_delivery": ("user-confirmation", "windows-nvda", "remote-protocol", "isolated-test"),
    "linux_focus": ("user-confirmation", "linux-atspi", "isolated-test"),
    "nvda_speech": ("user-confirmation", "windows-nvda", "isolated-test"),
    "semantic_braille": ("user-confirmation", "windows-nvda", "remote-protocol", "isolated-test"),
    "physical_braille": ("user-confirmation",),
}
CONTEXT = (
    "application",
    "gesture",
    "expected",
    "nvda_version",
    "orca_version",
    "companion_version",
    "linux_revision",
    "braille_model",
    "braille_driver",
    "braille_firmware",
)
STATUSES = ("unverified", "pass", "fail", "blocked", "not-tested")


def template() -> dict:
    return {
        "schema_version": 1,
        "kind": "single-interaction-layered-evidence",
        "context": {field: "" for field in CONTEXT},
        "session": {
            "authorization_before_input": "unverified",
            "input_permission": "unverified",
            "transport": "unverified",
            "control": "unverified",
        },
        "layers": [
            {
                "id": layer,
                "expected": expected,
                "status": "unverified",
                "source": "unverified",
                "observed": "",
            }
            for layer, expected in LAYERS.items()
        ],
    }


def validate(report: dict) -> None:
    if (
        not isinstance(report, dict)
        or type(report.get("schema_version")) is not int
        or report["schema_version"] != 1
        or report.get("kind") != "single-interaction-layered-evidence"
    ):
        raise ValueError("invalid layered evidence schema")
    context = report.get("context")
    if not isinstance(context, dict) or set(context) != set(CONTEXT):
        raise ValueError("invalid context fields")
    if any(not isinstance(value, str) or len(value) > 500 for value in context.values()):
        raise ValueError("context values must contain at most 500 characters")
    session = report.get("session")
    allowed = {
        "authorization_before_input": ("unverified", "active", "expired"),
        "input_permission": ("unverified", "user-operated", "explicit-agent-permission"),
        "transport": ("unverified", "connected", "disconnected"),
        "control": ("unverified", "remote", "local"),
    }
    if (
        not isinstance(session, dict)
        or set(session) != set(allowed)
        or any(session[field] not in values for field, values in allowed.items())
    ):
        raise ValueError("invalid session evidence")
    layers = report.get("layers")
    if not isinstance(layers, list) or len(layers) != len(LAYERS):
        raise ValueError("invalid evidence layer list")
    for layer, (layer_id, expected) in zip(layers, LAYERS.items()):
        if not isinstance(layer, dict) or layer.get("id") != layer_id or layer.get("expected") != expected:
            raise ValueError("invalid or reordered evidence layer")
        status, source, observed = layer.get("status"), layer.get("source"), layer.get("observed")
        if status not in STATUSES:
            raise ValueError("invalid layer status")
        if not isinstance(observed, str) or len(observed) > 500:
            raise ValueError("layer observation must contain at most 500 characters")
        if status in ("unverified", "not-tested"):
            if source != "unverified":
                raise ValueError("untested layer cannot claim an evidence source")
        elif source not in SOURCES[layer_id] or not observed.strip():
            raise ValueError("layer result requires a compatible source and observation")
        if status in ("pass", "fail") and any(
            not context[field].strip() for field in ("application", "gesture", "expected")
        ):
            raise ValueError("layer result requires application, gesture and expected behavior")
        if (
            layer_id == "physical_braille"
            and status in ("pass", "fail")
            and not context["braille_model"].strip()
        ):
            raise ValueError("physical output result requires a braille display model")


def summary(report: dict) -> dict:
    validate(report)
    layers = {layer["id"]: layer for layer in report["layers"]}
    counts = {status: sum(layer["status"] == status for layer in layers.values()) for status in STATUSES}

    def human_pass(layer_id):
        layer = layers[layer_id]
        return layer["status"] == "pass" and layer["source"] == "user-confirmation"

    return {
        "kind": report["kind"],
        "scope": "This interaction only; no issue closure or general compatibility acceptance",
        "context": report["context"],
        "session": report["session"],
        "counts": counts,
        "layers": {
            layer_id: {key: layer[key] for key in ("status", "source", "observed")}
            for layer_id, layer in layers.items()
        },
        "nvda_speech_user_confirmed": human_pass("nvda_speech"),
        "physical_braille_user_confirmed": human_pass("physical_braille"),
        "limitations": [
            "Linux focus/caret does not prove Windows keyboard delivery, NVDA output or physical braille",
            "Speech events do not prove audible output; semantic braille events do not prove physical output",
            "Isolated tests do not provide live acceptance; this offline report grants no input permission",
        ],
    }
