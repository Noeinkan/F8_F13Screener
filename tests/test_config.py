import os

from src.core.config import Config


class _SecretsModule:
    TELEGRAM_BOT_TOKEN = 'bot-token'
    TELEGRAM_CHAT_ID = 'chat-id'
    SEC_USER_AGENT = 'test@example.com'


def test_config_from_env_applies_runtime_overrides(monkeypatch):
    monkeypatch.setitem(__import__('sys').modules, 'config_secret', _SecretsModule)
    monkeypatch.setenv('F13F_POLL_INTERVAL_SECONDS', '45')
    monkeypatch.setenv('F13F_SUBMISSIONS_RECENT_LIMIT', '7')
    monkeypatch.setenv('F13F_SUBMISSIONS_REQUEST_DELAY_SECONDS', '2.5')
    monkeypatch.setenv('F13F_ENABLE_ATOM_FALLBACK', 'false')
    monkeypatch.setenv('F13F_AUTO_LAUNCH_VIEWER', '0')
    monkeypatch.setenv('F13F_ENABLE_FILTERED_DAILY_SUMMARY', '1')

    config = Config.from_env()

    assert config.poll_interval == 45
    assert config.submissions_recent_limit == 7
    assert config.submissions_request_delay_seconds == 2.5
    assert config.enable_atom_fallback is False
    assert config.auto_launch_viewer is False
    assert config.enable_filtered_daily_summary is True


def test_config_filtered_daily_summary_disabled_by_default(monkeypatch):
    monkeypatch.setitem(__import__('sys').modules, 'config_secret', _SecretsModule)
    monkeypatch.delenv('F13F_ENABLE_FILTERED_DAILY_SUMMARY', raising=False)

    config = Config.from_env()

    assert config.enable_filtered_daily_summary is False
