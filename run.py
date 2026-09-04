# CLI du système multi-agents : lance l'orchestrateur sur une image puis écrit
# le JSON macro et les montages de synthèse dans output/.

import argparse
import json
import sys
from pathlib import Path

from montage import generer_montages
from orchestrateur import orchestrer


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run.py",
        description="Décrit un plan/schéma technique via un système multi-agents "
                    "(orchestrateur + workers qui écrivent leur propre code).",
    )
    p.add_argument("image", type=Path, help="Chemin de l'image du plan à analyser.")
    p.add_argument("-o", "--output", type=Path, default=None,
                   help="Chemin du JSON de sortie (défaut : output/<image>_macro.json).")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    image_path = args.image

    if not image_path.exists():
        print(f"Image introuvable : {image_path}", file=sys.stderr)
        return 2

    try:
        resultat = orchestrer(str(image_path))
    except KeyboardInterrupt:
        print("\nInterrompu.", file=sys.stderr)
        return 130
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 — CLI : message lisible plutôt que traceback
        print(f"\n✖ Échec de l'analyse : {e}", file=sys.stderr)
        return 1

    # _workers : détail par agent, utilisé pour le montage puis retiré du JSON.
    workers = resultat.pop("_workers", [])
    for w in workers:
        res = w.get("resultat", {}) or {}
        w["artefacts"] = res.get("_artefacts", [])

    if args.output is not None:
        sortie = args.output
    else:
        dossier = Path(__file__).parent / "output"
        dossier.mkdir(exist_ok=True)
        sortie = dossier / f"{image_path.stem}_macro.json"
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps(resultat, ensure_ascii=False, indent=2),
                      encoding="utf-8")

    print(f"\n✔ Résultat enregistré : {sortie}")
    print("\nRÉSUMÉ MACRO :", resultat.get("resume_macro", ""))

    # Montage récapitulatif « quel worker a fait quoi » : ne doit jamais faire
    # échouer l'analyse, d'où le try/except large.
    try:
        work_dir = Path(__file__).parent / "travail" / image_path.stem
        montages = generer_montages(
            work_dir, sortie.parent, image_path.stem, resultat, workers)
        print("\n🖼 Montage(s) de synthèse :")
        for m in montages:
            print("  -", m)
    except Exception as e:
        print(f"\n⚠ Montage non généré : {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
