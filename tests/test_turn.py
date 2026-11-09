from custom_components.antigravity.api.catalog import parse_catalog
from custom_components.antigravity.api.turn import (
    THOUGHT_SIGNATURE_SENTINEL,
    ToolSpec,
    build_request,
    build_tools,
    function_call_part,
    function_response_part,
)


def test_build_tools_maps_names():
    tools, mapper = build_tools([ToolSpec("light.turn-on", "Turn on", {"type": "object"})])
    assert tools == [
        {
            "functionDeclarations": [
                {
                    "name": "light_turn_on",
                    "description": "Turn on",
                    "parameters": {"type": "object", "properties": {}},
                },
            ]
        }
    ]
    assert mapper.to_original("light_turn_on") == "light.turn-on"
    assert build_tools([])[0] == []


def test_signature_replay(models_payload):
    catalog = parse_catalog(models_payload)
    _, mapper = build_tools([ToolSpec("t", None, {})])
    gemini, claude = catalog.get("gemini-3.8-flash"), catalog.get("claude-opus-5-5")
    assert function_call_part(gemini, mapper, "c1", "t", {}, "sig")["thoughtSignature"] == "sig"
    assert function_call_part(gemini, mapper, "c1", "t", {}, None)["thoughtSignature"] == THOUGHT_SIGNATURE_SENTINEL
    assert "thoughtSignature" not in function_call_part(claude, mapper, "c1", "t", {"a": 1}, "sig")
    assert function_response_part(mapper, "c1", "t", "ok") == {
        "functionResponse": {"id": "c1", "name": "t", "response": {"output": "ok"}},
    }


def test_structured_output_gemini_only_without_tools(models_payload):
    catalog = parse_catalog(models_payload)
    gemini, claude = catalog.get("gemini-3.8-flash"), catalog.get("claude-opus-5-5")
    schema = {"type": "object", "properties": {"n": {"type": ["integer", "null"]}}}
    request = build_request(gemini, [], system_instruction="sys", response_schema=schema)
    assert request["systemInstruction"] == {"parts": [{"text": "sys"}]}
    assert request["generationConfig"] == {
        "thinkingConfig": {"includeThoughts": True},
        "responseMimeType": "application/json",
        "responseSchema": {"type": "object", "properties": {"n": {"type": "integer", "nullable": True}}},
    }
    with_tools = build_request(gemini, [], tools=[{"functionDeclarations": []}], response_schema=schema)
    assert "responseSchema" not in with_tools["generationConfig"]
    assert "responseMimeType" not in build_request(claude, [], json_output=True)["generationConfig"]
