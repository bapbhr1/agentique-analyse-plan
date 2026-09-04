# Utilitaires LLM/VLM partagés : client Azure, encodage d'images, construction
# des messages de tool-calling, et appel de vérification VLM sur un crop.

import base64
from pathlib import Path

from openai import OpenAI

import config


def creer_client() -> OpenAI:
    return OpenAI(base_url=config.ENDPOINT, api_key=config.API_KEY)


def encoder_image(chemin: Path) -> tuple[str, str]:
    # renvoie (contenu_base64, type_mime) ; défaut png si extension inconnue
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".webp": "image/webp", ".bmp": "image/bmp"}.get(
        Path(chemin).suffix.lower(), "image/png")
    b64 = base64.b64encode(Path(chemin).read_bytes()).decode("utf-8")
    return b64, mime


def msg_image(chemin: Path, texte: str, detail: str = "high") -> dict:
    # message role=user = image inline (data URI) + texte
    b64, mime = encoder_image(chemin)
    return {
        "role": "user",
        "content": [
            {"type": "image_url",
             "image_url": {"url": f"data:{mime};base64,{b64}", "detail": detail}},
            {"type": "text", "text": texte},
        ],
    }


def assistant_dict(msg) -> dict:
    # recompose le message assistant + ses tool_calls pour le réinjecter dans
    # l'historique : l'API exige ce message avant les messages role=tool
    d = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        d["tool_calls"] = [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name,
                          "arguments": tc.function.arguments}}
            for tc in msg.tool_calls
        ]
    return d


# Prompt du VLM de vérification : lecture fidèle, aucune invention.
_SYS_VLM = (
    "Tu es un lecteur EXPERT de plans et schémas techniques. On te montre un "
    "extrait d'image (crop) et une question précise. Réponds de façon concise et "
    "FIDÈLE : recopie les textes exactement tels qu'ils apparaissent, n'invente "
    "rien, et si c'est illisible dis-le explicitement."
)


def demander_vlm(client: OpenAI, image_path: Path, question: str,
                 detail: str = "high") -> str:
    # appel VLM à contexte vierge : contre-vérification d'un crop quand l'OCR
    # d'un worker est douteux (on soumet le crop + une question ciblée)
    b64, mime = encoder_image(image_path)
    reponse = client.chat.completions.create(
        model=config.DEPLOYMENT_NAME,
        messages=[
            {"role": "system", "content": _SYS_VLM},
            {"role": "user", "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{b64}", "detail": detail}},
                {"type": "text", "text": question},
            ]},
        ],
        max_completion_tokens=config.VLM_MAX_TOKENS,
    )
    return reponse.choices[0].message.content or "(réponse VLM vide)"
