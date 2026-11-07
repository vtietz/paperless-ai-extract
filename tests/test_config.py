import pytest
from pydantic import ValidationError

from paperless_ai_extract.config import ConfigError, ExtractionConfig, load_config


def test_relative_paths_resolve_against_config_dir(config, tmp_path):
    assert config.extraction.prompt_file == (tmp_path / "prompt.txt").resolve()
    assert config.state.path == (tmp_path / "state.sqlite3").resolve()


def test_env_default_and_override(config_factory, monkeypatch):
    assert config_factory().paperless.resolved_token() == "secret-token"
    monkeypatch.setenv("TEST_TOKEN", "from-env")
    assert config_factory().paperless.resolved_token() == "from-env"


def test_missing_env_without_default_is_an_error(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("paperless: {url: x, token: ${NOPE_NOT_SET}}\n")
    with pytest.raises(ConfigError, match="NOPE_NOT_SET"):
        load_config(path)


def test_token_file(config_factory, tmp_path):
    (tmp_path / "token").write_text("file-token\n")
    cfg = config_factory()
    cfg.paperless.token = None
    cfg.paperless.token_file = tmp_path / "token"
    assert cfg.paperless.resolved_token() == "file-token"


def test_unknown_keys_are_rejected(config_factory):
    with pytest.raises(ConfigError, match="typo"):
        config_factory("typo: true\n")


def test_article_kind_must_be_configured():
    with pytest.raises(ValidationError, match="articles.kind"):
        ExtractionConfig(prompt_file="p", kinds=["x"], articles={"enabled": True})


def test_cli_reports_unwritable_state_without_traceback(config_factory, tmp_path, capsys):
    from paperless_ai_extract.cli import main
    config_factory("")
    blocker = tmp_path / "blocker"
    blocker.write_text("file, not a directory")
    path = tmp_path / "config.yaml"
    path.write_text(path.read_text().replace("path: state.sqlite3", f"path: {blocker}/state.sqlite3"))
    assert main(["-c", str(path), "analyse", "1"]) == 2
    assert "state error" in capsys.readouterr().err



def test_removed_storage_paths_setting_explains_the_replacement(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("paperless: {url: http://p, token: t}\n"
                    "llm: {base_url: http://o, model: m}\n"
                    "taxonomy: {storage_paths: {article: Articles}}\n")
    with pytest.raises(ConfigError, match="Paperless workflow"):
        load_config(path, environ={})
