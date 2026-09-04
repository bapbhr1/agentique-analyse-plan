# Configuration du système multi-agents de description de plans.
# Un orchestrateur planifie et délègue à des workers qui écrivent/exécutent leur
# propre code (OCR, crop, isolation couleur, squelettisation…) avec vérif VLM.
# Identifiants Azure communs au repo parent + budgets stricts anti-bouclage.

import os
from pathlib import Path

from dotenv import load_dotenv

# .env attendu à la racine du REPO PARENT (ce projet est un sous-dossier).
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# ---- Modèle (Azure OpenAI, déploiement du repo) ----
ENDPOINT        = os.getenv("AZURE_OPENAI_ENDPOINT")
API_KEY         = os.getenv("AZURE_OPENAI_API_KEY")
DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5.4")
MAX_TOKENS      = 8000

# ---- Budgets ORCHESTRATEUR (garde-fous anti-bouclage) ----
ORCH_MAX_TOURS   = 14      # nb max d'aller-retours de l'orchestrateur
MAX_TACHES       = 5       # nb max de sous-tâches déléguées au total

# ---- Budgets WORKER (par sous-tâche) ----
WORKER_MAX_TOURS   = 10    # nb max d'aller-retours d'un worker
WORKER_MAX_EXEC    = 7     # nb max d'exécutions de code d'un worker
WORKER_MAX_ERREURS = 4     # nb max d'exécutions en erreur avant arrêt du worker
WORKER_MAX_STAGN   = 3     # nb de tours stériles avant arrêt du worker

# ---- Vérification VLM ----
MAX_APPELS_VLM   = 15      # nb max d'appels de vérification VLM (toutes tâches)
VLM_MAX_TOKENS   = 1500    # tokens max d'une réponse de vérification VLM

# ---- Exécution de code (sandbox) ----
TIMEOUT_CODE     = 75      # secondes max pour UNE exécution de code
TEMPS_MAX_TOTAL  = 900     # secondes max pour toute la session (wall clock)

# ---- Sorties ----
STDOUT_MAX_CHARS = 6000    # troncature de la sortie renvoyée au modèle
