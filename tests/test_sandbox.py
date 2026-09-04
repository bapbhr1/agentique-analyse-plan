# Bac à sable worker : compteurs de budget, refus du code identique, env filtré.

from pathlib import Path

from outils import (
    Blackboard,
    ContexteWorker,
    _env_sous_processus,
    dispatch_worker,
    valider_sous_tache,
)


def _ctx(tmp_path: Path) -> ContexteWorker:
    bb = Blackboard(image_path=tmp_path / "image.png", work_dir=tmp_path)
    return ContexteWorker(bb=bb, client=None)


def test_code_identique_refuse_a_la_deuxieme_execution(tmp_path):
    ctx = _ctx(tmp_path)
    args = {"description": "test", "code": "print('hello')"}

    r1 = dispatch_worker(ctx, "run_python", args, valider_sous_tache)
    assert "[REFUSÉ]" not in r1.texte
    assert ctx.nb_exec_code == 1

    r2 = dispatch_worker(ctx, "run_python", dict(args), valider_sous_tache)
    assert "[REFUSÉ]" in r2.texte
    assert ctx.nb_exec_code == 1  # non incrémenté sur un refus


def test_erreur_dans_le_code_compte_comme_erreur(tmp_path):
    ctx = _ctx(tmp_path)
    r = dispatch_worker(ctx, "run_python",
                        {"description": "boom", "code": "raise ValueError('boom')"},
                        valider_sous_tache)
    assert "[ERREUR" in r.texte
    assert ctx.nb_erreurs_code == 1


def test_terminer_sous_tache_refuse_un_schema_invalide(tmp_path):
    ctx = _ctx(tmp_path)
    r = dispatch_worker(ctx, "terminer_sous_tache",
                        {"resultat_json": '{"confiance": "haute"}'}, valider_sous_tache)
    assert "[RÉSULTAT REFUSÉ]" in r.texte
    assert ctx.resultat_soumis is None and not r.fin


def test_terminer_sous_tache_accepte_un_resultat_valide(tmp_path):
    ctx = _ctx(tmp_path)
    r = dispatch_worker(ctx, "terminer_sous_tache",
                        {"resultat_json": '{"resultat": "ok", "confiance": "moyenne"}'},
                        valider_sous_tache)
    assert r.fin and ctx.resultat_soumis["resultat"] == "ok"


def test_env_sous_processus_retire_les_secrets(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "secret")
    monkeypatch.setenv("SOME_TOKEN", "secret")
    monkeypatch.setenv("PATH_HARMLESS", "ok")
    env = _env_sous_processus()
    assert "AZURE_OPENAI_API_KEY" not in env
    assert "SOME_TOKEN" not in env
    assert env.get("PATH_HARMLESS") == "ok"
