# Agent ORCHESTRATEUR : observe le plan, en déduit lui-même un plan d'action
# découpé en sous-tâches, délègue chaque sous-tâche à un agent WORKER, puis
# synthétise une DESCRIPTION MACRO du plan.
#
# Les workers sont vus comme un simple outil `deleguer_tache` : l'orchestrateur
# choisit un rôle + un objectif, le worker s'exécute (code + VLM), son résultat
# structuré revient et l'orchestrateur décide de la suite.
# Boucle bornée par ORCH_MAX_TOURS et MAX_TACHES (config.py).

import json
import time
from pathlib import Path

import config
from llm import assistant_dict, creer_client, msg_image
from outils import Blackboard, valider_description_macro
from worker import executer_sous_tache

_ICI = Path(__file__).parent


def _prompt_orchestrateur() -> str:
    return (_ICI / "prompts" / "orchestrateur.md").read_text(encoding="utf-8")


# ------------------------------------------------------------
# Outils de l'orchestrateur (schémas function-calling)
# ------------------------------------------------------------

OUTILS_ORCH = [
    {
        "type": "function",
        "function": {
            "name": "planifier",
            "description": (
                "Déclare (ou met à jour) TON plan d'action : la liste ordonnée des "
                "sous-tâches que tu comptes déléguer, chacune avec son rôle d'agent et "
                "son objectif. Sert de feuille de route ; tu délègues ensuite une à une."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "taches": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "role": {"type": "string",
                                         "description": "Rôle de l'agent (ex. 'lecteur OCR', 'analyste couleurs/lignes', 'cartographe des zones')."},
                                "objectif": {"type": "string",
                                             "description": "Ce que l'agent doit produire."},
                            },
                            "required": ["role", "objectif"],
                        },
                    },
                },
                "required": ["taches"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deleguer_tache",
            "description": (
                "Confie UNE sous-tâche à un agent worker qui écrira et exécutera son "
                "propre code (OCR, crop, isolation couleur avec détection HSV, "
                "squelettisation…) et pourra vérifier par VLM. Renvoie le résultat "
                "structuré de l'agent. Appelle cet outil autant de fois que nécessaire "
                "(dans la limite du budget)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "role": {"type": "string",
                             "description": "Rôle/spécialité de l'agent pour cette tâche."},
                    "objectif": {"type": "string",
                                 "description": "Objectif précis et autonome de la sous-tâche."},
                    "methodes": {"type": "string",
                                 "description": "Méthodes suggérées à l'agent (facultatif)."},
                    "contexte": {"type": "string",
                                 "description": "Infos utiles déjà connues à transmettre (facultatif)."},
                },
                "required": ["role", "objectif"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rendre_description_macro",
            "description": (
                "Rends la DESCRIPTION MACRO finale du plan (JSON), en synthétisant les "
                "résultats de tous les agents. À n'appeler qu'une fois l'analyse aboutie."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "resultat_json": {"type": "string",
                                      "description": "JSON conforme au schéma de sortie macro."},
                },
                "required": ["resultat_json"],
            },
        },
    },
]


def _resume_resultat(res: dict, limite: int = 1200) -> str:
    # JSON du résultat worker, tronqué avant réinjection dans le prompt
    txt = json.dumps(res, ensure_ascii=False)
    return txt if len(txt) <= limite else txt[:limite] + "…[tronqué]"


def orchestrer(image_path: str) -> dict:
    image_path = Path(image_path).resolve()
    if not image_path.exists():
        raise FileNotFoundError(image_path)

    # dossier de travail partagé entre tous les workers de cette image
    work_dir = (_ICI / "travail" / image_path.stem).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    client = creer_client()
    bb = Blackboard(image_path=image_path, work_dir=work_dir)

    messages = [
        {"role": "system", "content": _prompt_orchestrateur()},
        msg_image(image_path,
                  "Voici le plan à décrire au niveau MACRO. Analyse-le, planifie tes "
                  "sous-tâches, délègue-les à des agents, puis rends la description "
                  "macro finale."),
    ]

    debut = time.time()
    for tour in range(1, config.ORCH_MAX_TOURS + 1):
        ecoule = time.time() - debut
        # budget épuisé = plus de temps, plus de sous-tâches, ou dernier tour
        budget_epuise = (
            ecoule > config.TEMPS_MAX_TOTAL
            or bb.nb_taches >= config.MAX_TACHES
            or tour == config.ORCH_MAX_TOURS
        )
        # forcer = on doit conclure mais aucune description finale n'a été rendue
        forcer = budget_epuise and bb.resultat_final is None

        tool_choice = "auto"
        if forcer:
            # on impose l'appel de rendre_description_macro (fin propre plutôt que boucle)
            messages.append({
                "role": "user",
                "content": ("Budget d'orchestration presque épuisé. Ne délègue plus : "
                            "appelle MAINTENANT rendre_description_macro avec la "
                            "meilleure synthèse possible des résultats collectés."),
            })
            tool_choice = {"type": "function",
                           "function": {"name": "rendre_description_macro"}}

        print(f"\n[ORCHESTRATEUR tour {tour}/{config.ORCH_MAX_TOURS}] "
              f"taches={bb.nb_taches}/{config.MAX_TACHES} "
              f"vlm={bb.nb_appels_vlm} t={int(ecoule)}s")

        reponse = client.chat.completions.create(
            model=config.DEPLOYMENT_NAME,
            messages=messages,
            tools=OUTILS_ORCH,
            tool_choice=tool_choice,
            max_completion_tokens=config.MAX_TOKENS,
        )
        msg = reponse.choices[0].message
        messages.append(assistant_dict(msg))

        # texte seul sans tool_call : on relance, ou on sort si le budget est fini
        if not msg.tool_calls:
            if msg.content:
                print("   (orchestrateur) " + msg.content[:200].replace("\n", " "))
            messages.append({
                "role": "user",
                "content": ("Continue : planifie, délègue une sous-tâche, ou rends la "
                            "description macro. N'écris pas de texte seul."),
            })
            if budget_epuise:
                break
            continue

        for tc in msg.tool_calls:
            nom = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            if nom == "planifier":
                bb.plan = args.get("taches", [])
                apercu = "; ".join(f"{t.get('role','?')} → {t.get('objectif','')[:60]}"
                                   for t in bb.plan)
                print(f"   → planifier : {len(bb.plan)} sous-tâche(s)")
                contenu = f"Plan enregistré ({len(bb.plan)} sous-tâches) : {apercu}"

            elif nom == "deleguer_tache":
                if bb.nb_taches >= config.MAX_TACHES:
                    contenu = ("[REFUSÉ] Budget de sous-tâches épuisé. Rends la "
                               "description macro finale.")
                else:
                    bb.nb_taches += 1
                    role = args.get("role", "agent")
                    objectif = args.get("objectif", "")
                    print(f"   → deleguer_tache #{bb.nb_taches} [{role}] : {objectif[:70]}")
                    # bloquant : le worker déroule toute sa boucle avant de rendre
                    res = executer_sous_tache(
                        bb, client, role, objectif,
                        args.get("methodes", ""), args.get("contexte", ""))
                    bb.resultats.append({"role": role, "objectif": objectif,
                                         "resultat": res})
                    contenu = (f"Résultat de la sous-tâche [{role}] "
                               f"(confiance={res.get('confiance','?')}) :\n"
                               + _resume_resultat(res))

            elif nom == "rendre_description_macro":
                brut = args.get("resultat_json", "")
                ok, data, erreurs = valider_description_macro(brut)
                if not ok:
                    # schéma non respecté : on renvoie les erreurs et on laisse réessayer
                    contenu = ("[RÉSULTAT REFUSÉ] Le JSON ne respecte pas le schéma :\n"
                               + "\n".join(f"- {e}" for e in erreurs)
                               + "\nCorrige et rappelle rendre_description_macro.")
                else:
                    bb.resultat_final = data
                    messages.append({"role": "tool", "tool_call_id": tc.id,
                                     "content": "[DESCRIPTION MACRO ACCEPTÉE]"})
                    print("\n✔ Description macro finale acceptée.")
                    bb.resultat_final["_workers"] = bb.resultats
                    return bb.resultat_final

            else:
                contenu = f"Outil inconnu : {nom}"

            messages.append({"role": "tool", "tool_call_id": tc.id, "content": contenu})

    # sortie de boucle sans description validée : filet de sécurité
    print("\n⚠ Budget épuisé sans description macro validée.")
    return bb.resultat_final or {
        "type_document": "inconnu",
        "titre": None,
        "resume_macro": "Analyse non aboutie dans le budget imparti.",
        "elements_cles": [],
        "_incomplet": True,
        "_workers": bb.resultats,
    }
