from custom_components.antigravity.api.schema import (
    ToolNameMapper,
    clean_response_schema,
    clean_tool_parameters,
)


def test_type_array_becomes_nullable():
    assert clean_tool_parameters({"type": "object", "properties": {"a": {"type": ["string", "null"]}}}) == {
        "type": "object",
        "properties": {"a": {"type": "string", "nullable": True}},
    }


def test_union_with_null_branch_keeps_description():
    node = clean_tool_parameters(
        {
            "properties": {
                "a": {
                    "description": "outer",
                    "anyOf": [{"type": "null"}, {"type": "integer"}],
                }
            }
        }
    )["properties"]["a"]
    assert node == {"type": "integer", "nullable": True, "description": "outer"}


def test_other_union_takes_first_viable_branch():
    node = clean_tool_parameters({"properties": {"a": {"oneOf": [{"type": "number"}, {"type": "string"}]}}})
    assert node["properties"]["a"] == {"type": "number"}


def test_enum_stringified_and_deduplicated():
    node = clean_tool_parameters({"properties": {"a": {"enum": [1, "1", 2, None]}}})["properties"]["a"]
    assert node == {"type": "string", "enum": ["1", "2"]}


def test_type_inferred_and_unknown_keys_dropped():
    schema = clean_tool_parameters(
        {
            "$schema": "x",
            "additionalProperties": False,
            "properties": {"o": {"properties": {"x": {"const": 1}}}, "l": {"items": {"type": "boolean"}}},
            "required": ["o", 3],
        }
    )
    assert schema == {
        "type": "object",
        "required": ["o"],
        "properties": {
            "o": {"type": "object", "properties": {"x": {"type": "string"}}},
            "l": {"type": "array", "items": {"type": "boolean"}},
        },
    }


def test_tool_root_forced_to_object_response_root_kept():
    assert clean_tool_parameters({"type": "array"}) == {"type": "object", "properties": {}}
    assert clean_response_schema({"type": "array", "items": {"type": "string"}}) == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert clean_tool_parameters(None) == {"type": "object", "properties": {}}


def test_tool_name_mapper():
    mapper = ToolNameMapper()
    assert mapper.to_safe("HassTurnOn") == "HassTurnOn"
    assert mapper.to_safe("my-tool.v2") == "my_tool_v2"
    assert mapper.to_safe("my_tool_v2") == "my_tool_v2_1"
    assert mapper.to_safe("1st") == "_1st"
    long = "a" * 70 + "-"
    assert len(mapper.to_safe(long)) == 64
    assert mapper.to_original("my_tool_v2") == "my-tool.v2"
    assert mapper.to_original("my_tool_v2_1") == "my_tool_v2"
    assert "HassTurnOn" in mapper
    assert "unknown" not in mapper
