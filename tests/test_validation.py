# Validation des JSON rendus par les agents (schémas maison, sans dépendance).

import pytest

from outils import _charger_json, valider_description_macro, valider_sous_tache

MACRO_OK = {
    "type_document": "plan mécanique",
    "titre": "BRACKET",
    "resume_macro": "…",
    "elements_cles": [],
}


def test_macro_valide():
    import json
    ok, data, erreurs = valider_description_macro(json.dumps(MACRO_OK))
    assert ok and erreurs == []
    assert data["titre"] == "BRACKET"


def test_macro_cle_manquante():
    import json
    brut = json.dumps({k: v for k, v in MACRO_OK.items() if k != "resume_macro"})
    ok, _, erreurs = valider_description_macro(brut)
    assert not ok
    assert any("resume_macro" in e for e in erreurs)


def test_macro_elements_cles_doit_etre_liste():
    import json
    brut = json.dumps({**MACRO_OK, "elements_cles": {"pas": "une liste"}})
    ok, _, erreurs = valider_description_macro(brut)
    assert not ok
    assert any("elements_cles" in e for e in erreurs)


def test_macro_racine_non_objet():
    ok, _, erreurs = valider_description_macro("[1, 2, 3]")
    assert not ok and erreurs


def test_macro_json_invalide():
    ok, data, erreurs = valider_description_macro("{pas du json")
    assert not ok and data is None and erreurs


def test_sous_tache_valide():
    ok, data, erreurs = valider_sous_tache('{"resultat": "x", "confiance": "haute"}')
    assert ok and erreurs == []
    assert data["confiance"] == "haute"


@pytest.mark.parametrize("brut", [
    '{"confiance": "haute"}',           # resultat manquant
    '{"resultat": "x"}',                # confiance manquante
])
def test_sous_tache_cles_requises(brut):
    ok, _, erreurs = valider_sous_tache(brut)
    assert not ok and erreurs


def test_charger_json_tolere_les_fences_markdown():
    assert _charger_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _charger_json('```\n{"a": 1}\n```') == {"a": 1}
    assert _charger_json('{"a": 1}') == {"a": 1}
