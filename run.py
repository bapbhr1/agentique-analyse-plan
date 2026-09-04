# CLI du système multi-agents : lance l'orchestrateur sur une image puis écrit
# le JSON macro et les montages de synthèse dans output/.

import sys
import json
from pathlib import Path

from orchestrateur import orchestrer
from montage import generer_montages

USAGE = "Usage : python run.py <chemin_image> [chemin_sortie.json]"


def main():
    if len(sys.argv) < 2:
        print(USAGE)
        sys.exit(0)

    image_path = Path(sys.argv[1])
    resultat = orchestrer(str(image_path))

    # _workers : détail par agent, utilisé pour le montage puis retiré du JSON.
    workers = resultat.pop("_workers", [])
    for w in workers:
        res = w.get("resultat", {}) or {}
        w["artefacts"] = res.get("_artefacts", [])

    if len(sys.argv) > 2:
        sortie = Path(sys.argv[2])
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


if __name__ == "__main__":
    main()
