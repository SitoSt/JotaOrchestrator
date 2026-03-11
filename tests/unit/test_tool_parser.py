"""
test_tool_parser.py
~~~~~~~~~~~~~~~~~~~
Unit tests for src/utils/tool_parser.py covering the updated regex pattern,
web_search argument validation, and XML-removal helper.
"""
import pytest
from src.utils.tool_parser import (
    extract_tool_calls,
    remove_tool_calls_from_text,
    TOOL_CALL_PATTERN,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wrap(content: str) -> str:
    """Wrap content in <tool_call> tags."""
    return f"<tool_call>{content}</tool_call>"


# ---------------------------------------------------------------------------
# TOOL_CALL_PATTERN — whitespace / newline tolerance
# ---------------------------------------------------------------------------

class TestToolCallPattern:
    def test_match_compact(self):
        text = _wrap('{"name":"web_search","arguments":{"query":"test"}}')
        assert TOOL_CALL_PATTERN.search(text) is not None

    def test_match_leading_newline(self):
        text = "<tool_call>\n{\"name\":\"web_search\",\"arguments\":{\"query\":\"test\"}}</tool_call>"
        assert TOOL_CALL_PATTERN.search(text) is not None

    def test_match_trailing_newline(self):
        text = "<tool_call>{\"name\":\"web_search\",\"arguments\":{\"query\":\"test\"}}\n</tool_call>"
        assert TOOL_CALL_PATTERN.search(text) is not None

    def test_match_surrounding_newlines_and_spaces(self):
        text = "<tool_call>\n  {\"name\":\"web_search\",\"arguments\":{\"query\":\"test\"}}  \n</tool_call>"
        assert TOOL_CALL_PATTERN.search(text) is not None

    def test_no_match_without_tags(self):
        text = '{"name":"web_search","arguments":{"query":"test"}}'
        assert TOOL_CALL_PATTERN.search(text) is None


# ---------------------------------------------------------------------------
# extract_tool_calls — happy path
# ---------------------------------------------------------------------------

class TestExtractToolCallsHappy:
    def test_valid_web_search(self):
        text = _wrap('{"name":"web_search","arguments":{"query":"capital of France"}}')
        calls = extract_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "web_search"
        assert calls[0]["arguments"]["query"] == "capital of France"

    def test_valid_generic_tool(self):
        text = _wrap('{"name":"set_timer","arguments":{"seconds":300}}')
        calls = extract_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "set_timer"

    def test_multiple_calls(self):
        text = (
            _wrap('{"name":"web_search","arguments":{"query":"foo"}}')
            + " some text "
            + _wrap('{"name":"set_timer","arguments":{"seconds":60}}')
        )
        calls = extract_tool_calls(text)
        assert len(calls) == 2

    def test_extra_whitespace_around_json(self):
        text = "<tool_call>\n  {\"name\":\"web_search\",\"arguments\":{\"query\":\"hello\"}}  \n</tool_call>"
        calls = extract_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "web_search"


# ---------------------------------------------------------------------------
# extract_tool_calls — web_search validation
# ---------------------------------------------------------------------------

class TestExtractToolCallsWebSearchValidation:
    def test_missing_query_key_skipped(self):
        """web_search without 'query' must be rejected."""
        text = _wrap('{"name":"web_search","arguments":{"q":"no query key"}}')
        calls = extract_tool_calls(text)
        assert calls == []

    def test_empty_query_skipped(self):
        """web_search with empty string query must be rejected."""
        text = _wrap('{"name":"web_search","arguments":{"query":""}}')
        calls = extract_tool_calls(text)
        assert calls == []

    def test_whitespace_only_query_skipped(self):
        """web_search with whitespace-only query must be rejected."""
        text = _wrap('{"name":"web_search","arguments":{"query":"   "}}')
        calls = extract_tool_calls(text)
        assert calls == []

    def test_non_string_query_skipped(self):
        """web_search with a non-string query (e.g. null) must be rejected."""
        text = _wrap('{"name":"web_search","arguments":{"query":null}}')
        calls = extract_tool_calls(text)
        assert calls == []

    def test_valid_query_accepted(self):
        """web_search with a valid non-empty query is accepted."""
        text = _wrap('{"name":"web_search","arguments":{"query":"Madrid weather"}}')
        calls = extract_tool_calls(text)
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# extract_tool_calls — malformed inputs
# ---------------------------------------------------------------------------

class TestExtractToolCallsMalformed:
    def test_invalid_json_skipped(self):
        text = _wrap("{not valid json}")
        calls = extract_tool_calls(text)
        assert calls == []

    def test_missing_name_skipped(self):
        text = _wrap('{"arguments":{"query":"foo"}}')
        calls = extract_tool_calls(text)
        assert calls == []

    def test_numeric_name_skipped(self):
        text = _wrap('{"name":42,"arguments":{}}')
        calls = extract_tool_calls(text)
        assert calls == []

    def test_arguments_not_dict_skipped(self):
        text = _wrap('{"name":"web_search","arguments":"not_a_dict"}')
        calls = extract_tool_calls(text)
        assert calls == []


# ---------------------------------------------------------------------------
# remove_tool_calls_from_text
# ---------------------------------------------------------------------------

class TestRemoveToolCallsFromText:
    def test_removes_single_block(self):
        text = 'Before <tool_call>{"name":"web_search","arguments":{"query":"x"}}</tool_call> After'
        result = remove_tool_calls_from_text(text)
        assert "<tool_call>" not in result
        assert "Before" in result
        assert "After" in result

    def test_removes_multiline_block(self):
        text = "text\n<tool_call>\n{\"name\":\"x\",\"arguments\":{}}\n</tool_call>\nmore text"
        result = remove_tool_calls_from_text(text)
        assert "<tool_call>" not in result
        assert "more text" in result

    def test_removes_multiple_blocks(self):
        text = (
            _wrap('{"name":"a","arguments":{}}')
            + " middle "
            + _wrap('{"name":"b","arguments":{}}')
        )
        result = remove_tool_calls_from_text(text)
        assert "<tool_call>" not in result

    def test_no_blocks_unchanged(self):
        text = "Hello, this is a clean response."
        result = remove_tool_calls_from_text(text)
        assert result == text

    def test_returns_empty_for_only_block(self):
        text = _wrap('{"name":"web_search","arguments":{"query":"test"}}')
        result = remove_tool_calls_from_text(text)
        assert result == ""
