# Bac à sable d'exécution + outils exposés aux AGENTS WORKERS.
#
# Principe : on ne code PAS l'analyse. Chaque worker écrit et exécute son propre
# code Python dans un sous-processus isolé (même interpréteur venv), avec timeout
# et répertoire de travail PARTAGÉ entre agents (les crops/masques produits par
# un worker restent dispo pour les suivants).
#
# Outils worker :
#   - run_python(description, code)       : écrire/exécuter du code (OCR, crop, HSV…)
#   - verifier_vlm(nom_fichier, question) : faire RELIRE un crop par le VLM
#   - voir_artefact(nom_fichier)          : revoir soi-même une image produite
#   - terminer_sous_tache(resultat_json)  : rendre le résultat structuré de la tâche

import hashlib
import json
import os
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

import config
from llm import demander_vlm

# ============================================================
# État partagé entre tous les agents (tableau noir)
# ============================================================

@dataclass
class Blackboard:
    image_path: Path
    work_dir: Path
    plan: list = field(default_factory=list)        # sous-tâches planifiées
    resultats: list = field(default_factory=list)   # résultats des workers
    nb_taches: int = 0
    nb_appels_vlm: int = 0
    resultat_final: dict | None = None


# État sandbox d'UN worker : compteurs de budget + anti-répétition de code.
@dataclass
class ContexteWorker:
    bb: Blackboard
    client: object
    hashes_code: dict = field(default_factory=dict)
    nb_exec_code: int = 0
    nb_erreurs_code: int = 0
    resultat_soumis: dict | None = None
    # empreinte {nom_fichier: mtime} des artefacts existant AVANT ce worker,
    # pour distinguer ceux qu'il produit lui-même (cf. artefacts_produits()).
    empreinte_depart: dict = field(default_factory=dict)
    # images de contrôle VALIDÉES déclarées par le worker à la fin (artefacts_cles) :
    # seules celles-ci alimentent le montage de synthèse (cf. artefacts_pour_synthese()).
    artefacts_valides: list | None = None

    @property
    def image_path(self) -> Path:
        return self.bb.image_path

    @property
    def work_dir(self) -> Path:
        return self.bb.work_dir

    def _empreinte(self) -> dict:
        # {nom_fichier: mtime} du work_dir, hors script injecté et image source
        exclus = {"__snippet__.py"}
        emp = {}
        for p in self.work_dir.iterdir():
            if p.is_file() and p.name not in exclus and p.name != self.image_path.name:
                try:
                    emp[p.name] = p.stat().st_mtime
                except OSError:
                    emp[p.name] = 0.0
        return emp

    def memoriser_depart(self) -> None:
        # à appeler juste avant de lancer le worker
        self.empreinte_depart = self._empreinte()

    def artefacts(self) -> list[str]:
        return sorted(self._empreinte().keys())

    def artefacts_produits(self) -> list[str]:
        # images créées ou modifiées PAR CE worker (absentes au départ, ou mtime changé)
        exts = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
        courant = self._empreinte()
        produits = [
            nom for nom, mt in courant.items()
            if Path(nom).suffix.lower() in exts
            and self.empreinte_depart.get(nom) != mt
        ]
        return sorted(produits)

    def artefacts_pour_synthese(self) -> list[str]:
        # images représentatives pour le montage : les `artefacts_cles` validés par
        # le worker si présents (restreints à ce qu'il a produit), sinon tout ce
        # qu'il a produit. But : écarter les essais ratés du récap.
        produits = self.artefacts_produits()
        if self.artefacts_valides:
            gardes = [a for a in self.artefacts_valides if a in produits]
            if gardes:
                return gardes
        return produits


@dataclass
class ResultatOutil:
    texte: str                       # message role=tool renvoyé au worker
    image_path: str | None = None    # image à ré-injecter (message user séparé)
    fin: bool = False                # True si terminer_sous_tache a réussi


# ============================================================
# Schémas de function-calling exposés aux workers
# ============================================================

OUTILS_WORKER = [
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": (
                "Écris et exécute du code Python adapté à CETTE image pour ta "
                "sous-tâche (OCR, recadrage par région d'intérêt, détection des "
                "plages HSV puis isolation par couleur, squelettisation, contours, "
                "mesures…). Le code tourne dans un sous-processus isolé avec timeout. "
                "Variables disponibles : IMG_PATH (image d'origine), WORK_DIR (dossier "
                "PARTAGÉ entre agents). Bibliothèques : cv2, numpy, easyocr, PIL, "
                "scikit-image. Pour l'OCR, utilise la fonction prête à l'emploi "
                "ocr(source, langs=('fr','en')) DÉJÀ INJECTÉE (EasyOCR hors-ligne, "
                "modèle latin en cache) : n'instancie pas easyocr.Reader toi-même. "
                "Sauvegarde tes images de contrôle/crops dans WORK_DIR "
                "(cv2.imwrite) puis vérifie-les (voir_artefact / verifier_vlm). "
                "Réutilise le MÊME nom de fichier quand tu refais un crop/masque raté "
                "(l'essai précédent est écrasé, pas d'images parasites). "
                "Affiche tes résultats avec print(). Ne relance jamais un code identique."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string",
                                    "description": "But de ce code en une phrase."},
                    "code": {"type": "string", "description": "Code Python à exécuter."},
                },
                "required": ["description", "code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verifier_vlm",
            "description": (
                "Fais RELIRE/VÉRIFIER un extrait d'image (crop que tu as produit dans "
                "WORK_DIR) par le VLM, avec une question précise. À utiliser quand "
                "l'OCR est douteux, un texte est petit/ambigu, ou pour confirmer un "
                "symbole. Renvoie la lecture du VLM (à recouper avec ton OCR)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nom_fichier": {"type": "string",
                                    "description": "Nom du crop dans WORK_DIR à faire relire."},
                    "question": {"type": "string",
                                 "description": "Question précise posée au VLM sur ce crop."},
                },
                "required": ["nom_fichier", "question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "voir_artefact",
            "description": (
                "Ré-injecte une image produite par ton code (dans WORK_DIR) pour que "
                "tu la VOIES toi-même et juges visuellement ton résultat (masque, "
                "crop, annotation…)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nom_fichier": {"type": "string",
                                    "description": "Nom du fichier image dans WORK_DIR."},
                },
                "required": ["nom_fichier"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "terminer_sous_tache",
            "description": (
                "Rends le RÉSULTAT structuré (JSON) de TA sous-tâche uniquement, une "
                "fois l'objectif atteint. Ne décris que ce que TU as trouvé."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "resultat_json": {"type": "string",
                                      "description": "JSON du résultat de la sous-tâche (cf. schéma)."},
                    "artefacts_cles": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Noms des 1 à 4 images de contrôle VALIDÉES et représentatives "
                            "(meilleur crop, masque propre, vue annotée correcte) à conserver "
                            "pour la synthèse. N'inclus PAS les essais ratés / intermédiaires."),
                    },
                },
                "required": ["resultat_json"],
            },
        },
    },
]


# ============================================================
# Exécution du code d'un worker (sous-processus)
# ============================================================

PREAMBULE = """\
# --- préambule injecté par le système (ne pas reproduire) ---
import os, sys, json, math
IMG_PATH = {img!r}
WORK_DIR = {work!r}
os.chdir(WORK_DIR)
# --- code du modèle ci-dessous ---
"""


def _env_sous_processus() -> dict:
    # environnement filtré pour le code écrit par le modèle : on retire les
    # secrets du process parent (clés API…) — ce code n'a aucune raison d'y toucher.
    interdits = ("API_KEY", "_KEY", "SECRET", "TOKEN", "AZURE_OPENAI")
    return {k: v for k, v in os.environ.items()
            if not any(motif in k.upper() for motif in interdits)}


HELPERS_OCR = '''
_OCR_READERS = {}
def _reader_ocr(langs):
    import easyocr
    cle = tuple(langs)
    if cle not in _OCR_READERS:
        _OCR_READERS[cle] = easyocr.Reader(list(langs), gpu=False, verbose=False,
                                           download_enabled=False)
    return _OCR_READERS[cle]

def ocr(source, langs=("fr", "en"), detail=1, **kw):
    # OCR hors-ligne prêt à l'emploi (EasyOCR, modèle latin en cache).
    # source : chemin d'image OU tableau numpy (BGR ou RGB).
    # detail=1 -> [(bbox, texte, confiance), ...] ; detail=0 -> [texte, ...].
    # Repli sur le modèle latin (fr+en) si la combinaison demandée n'est pas en cache.
    tentatives = []
    if langs:
        tentatives.append(tuple(langs))
    if ("fr", "en") not in tentatives:
        tentatives.append(("fr", "en"))   # latin_g2, garanti en cache
    dernier = None
    for lg in tentatives:
        try:
            return _reader_ocr(lg).readtext(source, detail=detail, **kw)
        except Exception as e:
            dernier = e
    raise RuntimeError(
        "OCR indisponible (%s). Modèle latin requis en cache ~/.EasyOCR/model." % dernier)
'''


def _executer_code(ctx: ContexteWorker, code: str) -> str:
    # exécute le code worker dans un sous-processus isolé (venv courant), avec
    # timeout, et renvoie un compte rendu texte : [OK] / [ERREUR] / [TIMEOUT]
    script = (PREAMBULE.format(img=str(ctx.image_path), work=str(ctx.work_dir))
              + HELPERS_OCR + "\n# --- code du modèle ---\n" + code)
    fichier = ctx.work_dir / "__snippet__.py"
    fichier.write_text(script, encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, str(fichier)],
            capture_output=True, text=True,
            timeout=config.TIMEOUT_CODE, cwd=str(ctx.work_dir),
            env=_env_sous_processus(),
        )
    except subprocess.TimeoutExpired:
        ctx.nb_erreurs_code += 1
        return (f"[TIMEOUT] Le code a dépassé {config.TIMEOUT_CODE}s. "
                "Optimise-le (réduis la résolution, restreins la zone) puis relance.")

    sortie = proc.stdout or ""
    erreur = proc.stderr or ""
    if len(sortie) > config.STDOUT_MAX_CHARS:
        sortie = sortie[:config.STDOUT_MAX_CHARS] + "\n...[sortie tronquée]"
    if len(erreur) > config.STDOUT_MAX_CHARS:
        erreur = erreur[-config.STDOUT_MAX_CHARS:]

    if proc.returncode != 0:
        ctx.nb_erreurs_code += 1
        return (f"[ERREUR d'exécution — code retour {proc.returncode}]\n"
                f"STDOUT:\n{sortie}\n\nTRACEBACK:\n{erreur}\nCorrige ton code et relance.")

    arts = ctx.artefacts()
    msg = f"[OK]\nSTDOUT:\n{sortie or '(vide)'}"
    if erreur.strip():
        msg += f"\n[stderr]:\n{erreur}"
    if arts:
        msg += f"\nArtefacts présents dans WORK_DIR : {arts}"
    return msg


# ============================================================
# Dispatch des appels d'outils d'un worker
# ============================================================

def dispatch_worker(ctx: ContexteWorker, nom: str, args: dict,
                    valider_fn) -> ResultatOutil:
    # aiguille un appel d'outil worker : run_python / verifier_vlm / voir_artefact / terminer
    if nom == "run_python":
        code = args.get("code", "")
        # empreinte du code : on refuse une 2e exécution strictement identique
        h = hashlib.sha1(textwrap.dedent(code).strip().encode()).hexdigest()
        ctx.hashes_code[h] = ctx.hashes_code.get(h, 0) + 1
        if ctx.hashes_code[h] > 1:
            return ResultatOutil(
                "[REFUSÉ] Tu as déjà exécuté EXACTEMENT ce code. Change d'approche "
                "(autre méthode, autres paramètres) ou termine la sous-tâche.")
        ctx.nb_exec_code += 1
        return ResultatOutil(_executer_code(ctx, code))

    if nom == "verifier_vlm":
        nom_f = args.get("nom_fichier", "")
        question = args.get("question", "").strip()
        p = ctx.work_dir / nom_f
        if not p.exists():
            return ResultatOutil(f"Crop introuvable : {nom_f}. "
                                 f"Disponibles : {ctx.artefacts()}")
        if ctx.bb.nb_appels_vlm >= config.MAX_APPELS_VLM:
            return ResultatOutil("[REFUSÉ] Budget de vérifications VLM épuisé. "
                                 "Conclus avec ce que tu as.")
        ctx.bb.nb_appels_vlm += 1
        lecture = demander_vlm(ctx.client, p, question or "Décris précisément le contenu.")
        return ResultatOutil(f"[VÉRIFICATION VLM sur '{nom_f}']\n{lecture}")

    if nom == "voir_artefact":
        nom_f = args.get("nom_fichier", "")
        p = ctx.work_dir / nom_f
        if not p.exists():
            return ResultatOutil(f"Artefact introuvable : {nom_f}. "
                                 f"Disponibles : {ctx.artefacts()}")
        return ResultatOutil(f"Image '{nom_f}' jointe ci-dessous.", image_path=str(p))

    if nom == "terminer_sous_tache":
        brut = args.get("resultat_json", "")
        ok, data, erreurs = valider_fn(brut)
        if not ok:
            return ResultatOutil(
                "[RÉSULTAT REFUSÉ] Le JSON ne respecte pas le schéma :\n"
                + "\n".join(f"- {e}" for e in erreurs)
                + "\nCorrige et rappelle terminer_sous_tache.")
        # Sélection des images représentatives à conserver pour la synthèse.
        cles = args.get("artefacts_cles") or []
        if isinstance(cles, str):
            cles = [c.strip() for c in cles.replace(";", ",").split(",") if c.strip()]
        produits = set(ctx.artefacts_produits())
        ctx.artefacts_valides = [c for c in cles
                                 if c in produits and (ctx.work_dir / c).exists()]
        ctx.resultat_soumis = data
        return ResultatOutil("[SOUS-TÂCHE TERMINÉE]", fin=True)

    return ResultatOutil(f"Outil inconnu : {nom}")


# ============================================================
# Validation légère des JSON (sans dépendance externe)
# ============================================================

def _charger_json(brut: str):
    # parse un JSON en tolérant un encadrement Markdown ```json ... ```
    txt = brut.strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        txt = txt[4:] if txt.lower().startswith("json") else txt
    return json.loads(txt)


def valider_sous_tache(brut: str):
    # résultat worker -> (ok, data, erreurs) ; clés requises : resultat, confiance
    try:
        data = _charger_json(brut)
    except json.JSONDecodeError as e:
        return False, None, [f"JSON invalide : {e}"]
    if not isinstance(data, dict):
        return False, None, ["La racine doit être un objet JSON."]
    erreurs = []
    if "resultat" not in data:
        erreurs.append("clé requise manquante : 'resultat'")
    if "confiance" not in data:
        erreurs.append("clé requise manquante : 'confiance' (haute|moyenne|faible)")
    return (len(erreurs) == 0), data, erreurs


CLES_MACRO = ["type_document", "titre", "resume_macro", "elements_cles"]


def valider_description_macro(brut: str):
    # description macro finale -> (ok, data, erreurs) ; cf. CLES_MACRO
    try:
        data = _charger_json(brut)
    except json.JSONDecodeError as e:
        return False, None, [f"JSON invalide : {e}"]
    if not isinstance(data, dict):
        return False, None, ["La racine doit être un objet JSON."]
    erreurs = [f"clé requise manquante : '{c}'" for c in CLES_MACRO if c not in data]
    if "elements_cles" in data and not isinstance(data["elements_cles"], list):
        erreurs.append("'elements_cles' doit être une liste.")
    return (len(erreurs) == 0), data, erreurs
