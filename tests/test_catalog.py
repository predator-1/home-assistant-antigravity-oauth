from custom_components.antigravity.api.catalog import parse_catalog


def test_models_from_routing_lists(models_payload):
    catalog = parse_catalog(models_payload)
    assert [m.id for m in catalog.models] == [
        "gemini-4-argon",
        "gemini-3.8-flash",
        "claude-opus-5-5",
        "claude-sonnet-5-5",
        "gpt-oss-120b",
        "gemini-3.5-flash-lite",
    ]
    assert catalog.default_model == "gemini-4-argon"
    assert catalog.image_models == ("gemini-3.1-flash-image",)
    assert catalog.flash_model == "gemini-3.8-flash-tiered"
    assert catalog.search_model == "gemini-3.5-flash-lite"


def test_effort_variants_and_names(models_payload):
    catalog = parse_catalog(models_payload)
    sonnet = catalog.get("claude-sonnet-5-5")
    assert sonnet.name == "Claude Sonnet 5.5"
    assert sonnet.efforts == ("low", "medium", "high")
    assert sonnet.upstream_id("high") == "claude-sonnet-5-5-high"
    assert sonnet.upstream_id(None) == "claude-sonnet-5-5-medium"
    assert sonnet.upstream_id("max") == "claude-sonnet-5-5-medium"
    assert sonnet.context_window == 1_000_000
    assert not sonnet.uses_thought_signatures
    gpt = catalog.get("gpt-oss-120b")
    assert gpt.efforts == ("medium",)
    assert gpt.upstream_id("low") == "gpt-oss-120b-medium"
    lite = catalog.get("gemini-3.5-flash-lite")
    assert lite.efforts == ()
    assert lite.upstream_id("high") == "gemini-3.5-flash-lite"
    assert lite.name == "Gemini 3.5 Flash Lite"


def test_media_flags(models_payload):
    flash = parse_catalog(models_payload).get("gemini-3.8-flash")
    assert flash.supports_images
    assert flash.accepts("audio/mpeg")
    assert flash.accepts("APPLICATION/PDF")
    assert flash.uses_thought_signatures
    assert flash.supports_structured_output


def test_disabled_and_deprecated_dropped(models_payload):
    models_payload["models"]["gpt-oss-120b-medium"]["disabled"] = True
    models_payload["deprecatedModelIds"] = ["gemini-4-argon"]
    ids = [m.id for m in parse_catalog(models_payload).models]
    assert "gpt-oss-120b" not in ids
    assert "gemini-4-argon" not in ids


def test_empty_payload_invents_nothing():
    catalog = parse_catalog({})
    assert catalog.models == ()
    assert catalog.default_model is None
    assert catalog.flash_model is None
    assert catalog.search_model is None
