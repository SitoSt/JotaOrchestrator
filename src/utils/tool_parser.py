import re
import json
import logging

logger = logging.getLogger(__name__)

TOOL_CALL_PATTERN = re.compile(
    r'<tool_call>\s*(\{.*?\})\s*</tool_call>',
    re.DOTALL
)

_VALID_TOOL_NAME = re.compile(r'^[a-zA-Z0-9_]+$')


def extract_tool_calls(text: str) -> list[dict]:
    """Parse all <tool_call>...</tool_call> blocks from text.

    Each block must contain valid JSON with a "name" (str) and
    "arguments" (dict) field. Invalid or malformed blocks are skipped
    with a warning log.

    Args:
        text: Raw model output that may contain tool_call blocks.

    Returns:
        List of dicts with keys "name" and "arguments". Empty list if
        no valid tool calls are found.
    """
    results = []
    for match in TOOL_CALL_PATTERN.finditer(text):
        raw = match.group(1)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning(f"tool_parser: failed to parse tool_call JSON: {e} — raw={raw!r}")
            continue

        name = data.get("name")
        arguments = data.get("arguments")

        if not isinstance(name, str):
            logger.warning(f"tool_parser: 'name' must be a str, got {type(name).__name__!r} — skipping")
            continue

        if not _VALID_TOOL_NAME.match(name):
            logger.warning(f"tool_parser: invalid tool name {name!r} (only letters, digits, underscore allowed) — skipping")
            continue

        if not isinstance(arguments, dict):
            logger.warning(f"tool_parser: 'arguments' must be a dict, got {type(arguments).__name__!r} for tool {name!r} — skipping")
            continue

        results.append({"name": name, "arguments": arguments})

    return results


def validate_tool_call(tool_call: dict, available_tools: list[str]) -> tuple[bool, str]:
    """Validate a parsed tool call against the list of registered tools.

    Args:
        tool_call: Dict with at least "name" and "arguments" keys.
        available_tools: List of tool names currently registered.

    Returns:
        (True, "") if the tool call is valid.
        (False, error_message) if validation fails.
    """
    name = tool_call.get("name")
    arguments = tool_call.get("arguments")

    if not isinstance(name, str) or not name:
        return False, f"Tool call is missing a valid 'name' field (got {name!r})"

    if name not in available_tools:
        return False, f"Tool '{name}' is not available. Available tools: {available_tools}"

    if not isinstance(arguments, dict):
        return False, f"'arguments' for tool '{name}' must be a dict, got {type(arguments).__name__!r}"

    return True, ""


def remove_tool_calls_from_text(text: str) -> str:
    """Remove all <tool_call>...</tool_call> blocks from text.

    Also collapses any blank lines left behind when a tool call occupied
    its own line, so the returned text is clean and readable.

    Args:
        text: Raw model output that may contain tool_call blocks.

    Returns:
        Cleaned text with all tool_call blocks removed.
    """
    cleaned = TOOL_CALL_PATTERN.sub("", text)
    # Collapse 3+ consecutive newlines (left by a standalone tool_call line)
    # down to a single blank line, then strip leading/trailing whitespace.
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()
