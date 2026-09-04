# Configuration du système multi-agents de description de plans.
# Un orchestrateur planifie et délègue à des workers qui écrivent/exécutent leur
# propre code (OCR, crop, isolation couleur, squelettisation…) avec vérif VLM.
# Identifiants du modèle + budgets stricts anti-bouclage.

import os
from pathlib import Path

from dotenv import load_dotenv

# .env : d'abord à la racine de CE repo, puis (repli) un cran au-dessus — ce
# projet a d'abord vécu comme sous-dossier d'un benchmark plus large.
_ICI = Path(__file__).resolve().parent
load_dotenv(_ICI / ".env")
load_dotenv(_ICI.parents[0] / ".env")

# ---- Modèle (API compatible OpenAI : Azure OpenAI ou passerelle équivalente) ----
ENDPOINT        = os.getenv("AZURE_OPENAI_ENDPOINT")
API_KEY         = os.getenv("AZURE_OPENAI_API_KEY")
DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
# Renseigné uniquement pour un vrai endpoint Azure (active le client AzureOpenAI).
API_VERSION     = os.getenv("AZURE_OPENAI_API_VERSION")
MAX_TOKENS      = 8000     # max_completion_tokens des appels orchestrateur/worker

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


def verifier_identifiants() -> None:
    """Échoue tôt, avec un message clair, si la config modèle est absente."""
    manquants = [nom for nom, val in (
        ("AZURE_OPENAI_ENDPOINT", ENDPOINT),
        ("AZURE_OPENAI_API_KEY", API_KEY),
    ) if not val]
    if manquants:
        raise SystemExit(
            "Configuration modèle incomplète : "
            + ", ".join(manquants)
            + ".\nCrée un fichier .env (voir README, section « Lancement ») avec au "
            "minimum AZURE_OPENAI_ENDPOINT et AZURE_OPENAI_API_KEY."
        )
