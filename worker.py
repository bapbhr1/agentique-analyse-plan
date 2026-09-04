# Agent WORKER générique : exécute UNE sous-tâche décidée par l'orchestrateur.
#
# Il reçoit un objectif + des méthodes suggérées + le contexte déjà collecté,
# voit l'image, puis écrit/exécute son propre code (OCR, crop, isolation
# couleur, squelettisation…), vérifie par VLM si besoin, et rend un résultat
# structuré. Boucle bornée par les budgets WORKER_* (config.py).

import json
from pathlib import Path

import config
from llm import msg_image, assistant_dict
from outils import (
    Blackboard, ContexteWorker, OUTILS_WORKER, dispatch_worker, valider_sous_tache,
)

_ICI = Path(__file__).parent


def _prompt_worker() -> str:
    return (_ICI / "prompts" / "worker.md").read_text(encoding="utf-8")


def _consigne(role: str, objectif: str, methodes: str, contexte: str) -> str:
    # message utilisateur d'ouverture du worker (méthodes/contexte optionnels)
    blocs = [
        f"RÔLE : {role}",
        f"OBJECTIF DE TA SOUS-TÂCHE :\n{objectif}",
    ]
    if methodes:
        blocs.append(f"MÉTHODES SUGGÉRÉES (à adapter, non imposées) :\n{methodes}")
    if contexte:
        blocs.append(f"CONTEXTE DÉJÀ COLLECTÉ PAR LES AUTRES AGENTS :\n{contexte}")
    blocs.append(
        "Concentre-toi UNIQUEMENT sur ton objectif. Écris et exécute ton code, "
        "vérifie visuellement/par VLM, puis appelle terminer_sous_tache.")
    return "\n\n".join(blocs)


def executer_sous_tache(bb: Blackboard, client, role: str, objectif: str,
                        methodes: str = "", contexte: str = "") -> dict:
    ctx = ContexteWorker(bb=bb, client=client)
    ctx.memoriser_depart()  # fige l'état du work_dir pour repérer ce que CE worker produit

    messages = [
        {"role": "system", "content": _prompt_worker()},
        msg_image(bb.image_path, _consigne(role, objectif, methodes, contexte)),
    ]

    stagnation = 0  # tours d'affilée sans progrès -> arrêt anticipé
    for tour in range(1, config.WORKER_MAX_TOURS + 1):
        budget_epuise = (
            ctx.nb_exec_code >= config.WORKER_MAX_EXEC
            or ctx.nb_erreurs_code >= config.WORKER_MAX_ERREURS
            or stagnation >= config.WORKER_MAX_STAGN
            or tour == config.WORKER_MAX_TOURS
        )
        forcer = budget_epuise and ctx.resultat_soumis is None

        tool_choice = "auto"
        if forcer:
            # on impose terminer_sous_tache : conclure avec incertitudes plutôt que boucler
            messages.append({
                "role": "user",
                "content": ("Budget de la sous-tâche presque épuisé. Ne lance plus de "
                            "code : appelle MAINTENANT terminer_sous_tache avec le "
                            "meilleur résultat possible, en marquant les incertitudes."),
            })
            tool_choice = {"type": "function",
                           "function": {"name": "terminer_sous_tache"}}

        print(f"    · worker[{role}] tour {tour}/{config.WORKER_MAX_TOURS} "
              f"exec={ctx.nb_exec_code} err={ctx.nb_erreurs_code} stagn={stagnation}")

        reponse = client.chat.completions.create(
            model=config.DEPLOYMENT_NAME,
            messages=messages,
            tools=OUTILS_WORKER,
            tool_choice=tool_choice,
            max_completion_tokens=config.MAX_TOKENS,
        )
        msg = reponse.choices[0].message
        messages.append(assistant_dict(msg))

        if not msg.tool_calls:
            stagnation += 1
            messages.append({
                "role": "user",
                "content": ("Continue : exécute du code utile, vérifie, ou appelle "
                            "terminer_sous_tache. N'écris pas de texte seul."),
            })
            if budget_epuise:
                break
            continue

        images_a_injecter = []
        a_progresse = False
        for tc in msg.tool_calls:
            nom = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            res = dispatch_worker(ctx, nom, args, valider_sous_tache)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": res.texte})

            # un appel outil accepté (non refusé) compte comme un progrès
            if nom in ("run_python", "voir_artefact", "verifier_vlm") \
                    and "[REFUSÉ]" not in res.texte:
                a_progresse = True
            if res.image_path:
                images_a_injecter.append(res.image_path)
            if res.fin:
                ctx.resultat_soumis["_artefacts"] = ctx.artefacts_pour_synthese()
                return ctx.resultat_soumis

        # les images demandées (voir_artefact) sont réinjectées en messages user séparés
        for chemin in images_a_injecter:
            messages.append(msg_image(Path(chemin),
                                      f"Artefact '{Path(chemin).name}'. Juge-le."))
        stagnation = 0 if a_progresse else stagnation + 1

    # worker sorti sans résultat validé : résultat par défaut « faible »
    resultat = ctx.resultat_soumis or {
        "resultat": "Sous-tâche non aboutie dans le budget imparti.",
        "confiance": "faible",
        "incertitudes": ["résultat incomplet"],
    }
    resultat.setdefault("_artefacts", ctx.artefacts_pour_synthese())
    return resultat
