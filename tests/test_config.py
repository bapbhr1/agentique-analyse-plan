# Garde-fou : configuration modèle absente -> échec explicite et précoce.

import pytest

import config


def test_verifier_identifiants_echoue_si_absent(monkeypatch):
    monkeypatch.setattr(config, "ENDPOINT", None)
    monkeypatch.setattr(config, "API_KEY", None)
    with pytest.raises(SystemExit) as exc:
        config.verifier_identifiants()
    assert "AZURE_OPENAI_ENDPOINT" in str(exc.value)
    assert "AZURE_OPENAI_API_KEY" in str(exc.value)


def test_verifier_identifiants_ok_si_present(monkeypatch):
    monkeypatch.setattr(config, "ENDPOINT", "https://exemple/")
    monkeypatch.setattr(config, "API_KEY", "k")
    config.verifier_identifiants()  # ne lève pas
