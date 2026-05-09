from sheela.llm.router import FLASH, FLASH_LITE, PRO, ModelRouter


def test_default_routes_to_flash():
    r = ModelRouter()
    assert r.route("respond", 0) == FLASH


def test_summarize_classify_extract_route_to_flash_lite():
    r = ModelRouter()
    assert r.route("summarize", 0) == FLASH_LITE
    assert r.route("classify", 0) == FLASH_LITE
    assert r.route("extract", 0) == FLASH_LITE


def test_complex_reasoning_routes_to_pro():
    r = ModelRouter()
    assert r.route("complex_reasoning", 0) == PRO


def test_high_context_routes_to_pro():
    r = ModelRouter()
    assert r.route("respond", 100_001) == PRO
    assert r.route("respond", 100_000) == FLASH  # boundary: > not >=


def test_fallback_chains():
    r = ModelRouter()
    assert r.fallbacks_for(FLASH) == [PRO]
    assert r.fallbacks_for(FLASH_LITE) == [FLASH]
    assert r.fallbacks_for(PRO) == []
    assert r.fallbacks_for("unknown-model") == []
