"""Fixed, text-free semantic caret diagnostics. No input or runtime collection."""

from enum import Enum


class CaretReason(str, Enum):
    SETTER_RETURNED = "setter_returned"
    INVALID_OBJECT = "invalid_object"
    INVALID_OFFSET = "invalid_offset"
    NO_CONTEXT = "no_context"
    STALE_CONTEXT = "stale_context"
    STALE_FOCUS = "stale_focus"
    UNKNOWN_OBJECT = "unknown_object"
    TARGET_UNAVAILABLE = "target_unavailable"
    TEXT_INTERFACE_UNAVAILABLE = "text_interface_unavailable"
    CHARACTER_COUNT_UNAVAILABLE = "character_count_unavailable"
    OFFSET_OUT_OF_RANGE = "offset_out_of_range"
    SETTER_UNAVAILABLE = "setter_unavailable"
    PROVIDER_REFUSED = "provider_refused"
    PROVIDER_ERROR = "provider_error"
    BEFORE_ROUTE_ERROR = "before_route_error"
    ADAPTER_ERROR = "adapter_error"
    INPUT_HELP = "input_help"
    STALE_SESSION = "stale_session"
    SEMANTIC_UNAVAILABLE = "semantic_unavailable"
    INVALID_VERSION = "invalid_version"
    SCHEDULE_FAILED = "schedule_failed"
    UNKNOWN = "unknown"


def report_caret_reason(diagnostic, reason: CaretReason) -> None:
    """An absent or failing observer cannot affect the existing operation."""
    if diagnostic is not None:
        try:
            diagnostic(reason)
        except Exception:
            pass
