from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.social.registry import SocialRegistry


def test_register_and_get():
    r = SocialRegistry()
    source = MagicMock()
    source.source_name = "test_source"
    r.register(source)
    assert r.get("test_source") is source


def test_get_unknown():
    r = SocialRegistry()
    assert r.get("nonexistent") is None


def test_get_active_empty():
    r = SocialRegistry()
    assert r.get_active() == []


@patch("src.social.registry.personal", {"social_sources": {"enabled_source": {"enabled": True}, "disabled_source": {"enabled": False}}})
def test_get_active_filters():
    r = SocialRegistry()
    s1 = MagicMock()
    s1.source_name = "enabled_source"
    s2 = MagicMock()
    s2.source_name = "disabled_source"
    r.register(s1)
    r.register(s2)
    active = r.get_active()
    names = [s.source_name for s in active]
    assert "enabled_source" in names
    assert "disabled_source" not in names


@patch("src.social.registry.personal", {})
def test_build_from_config_empty():
    r = SocialRegistry()
    r.build_from_config()
    assert r.get("pulse") is None
    assert r.get("vk") is None



