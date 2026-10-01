from kalshi_edge.config import anthropic_api_key


def test_falls_back_to_kalshi_anthropic_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("KALSHI_ANTHROPIC_KEY", "k2")
    assert anthropic_api_key() == "k2"


def test_prefers_anthropic_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k1")
    monkeypatch.setenv("KALSHI_ANTHROPIC_KEY", "k2")
    assert anthropic_api_key() == "k1"
