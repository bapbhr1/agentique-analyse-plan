# Génération des MONTAGES récapitulatifs du travail multi-agents.
#
# À partir des résultats collectés par l'orchestrateur (rôle, objectif, résultat
# et artefacts produits par CHAQUE worker) + la description macro finale, on
# assemble un ou plusieurs PNG « quel worker a fait quoi » :
#   - une page de garde : type/titre du document + liste des agents et leur apport
#   - une carte par worker : rôle, objectif, confiance, méthode, apport,
#     incertitudes, et une vignette par artefact image produit
#
# Contenu borné (texte tronqué, nb de vignettes plafonné) pour rester lisible ;
# les cartes sont réparties sur plusieurs pages si besoin.

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ------------------------------------------------------------------ style
W = 1600                 # largeur des pages
PAD = 36                 # marge extérieure
GAP = 24                 # espace entre cartes
MAX_PAGE_H = 2200        # hauteur max d'une page avant passage à la suivante
MAX_VIGNETTES = 6        # nb max de vignettes montrées par worker
VIGN_W, VIGN_H = 300, 220
COLS_VIGN = 4            # vignettes par ligne

C_FOND = "#FFFFFF"
C_HEADER = "#1f3a5f"
C_HEADER_TXT = "#FFFFFF"
C_TXT = "#1a1a1a"
C_MUTED = "#555555"
C_CARTE_BG = "#f4f7fb"
C_CARTE_BORD = "#c3d0e0"
C_VIGN_BORD = "#8899aa"
C_ROLE = ["#2d6cdf", "#c0392b", "#1e8449", "#8e44ad", "#d68910", "#16a085",
          "#c0398b", "#34495e"]
BADGE = {"haute": "#1e8449", "moyenne": "#d68910", "faible": "#c0392b"}


def _font(paths: list[str], size: int) -> ImageFont.FreeTypeFont:
    # première police trouvée parmi `paths`, sinon police PIL par défaut
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


F_TITRE = _font(["arialbd.ttf", "Arial_Bold.ttf", "DejaVuSans-Bold.ttf"], 38)
F_H = _font(["arialbd.ttf", "Arial_Bold.ttf", "DejaVuSans-Bold.ttf"], 27)
F_LBL = _font(["arialbd.ttf", "Arial_Bold.ttf", "DejaVuSans-Bold.ttf"], 21)
F_BODY = _font(["arial.ttf", "DejaVuSans.ttf"], 21)
F_SMALL = _font(["arial.ttf", "DejaVuSans.ttf"], 17)


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    # découpe un texte en lignes <= max_w px ; coupe brutalement un mot trop long
    lignes: list[str] = []
    for para in str(text).split("\n"):
        if not para:
            lignes.append("")
            continue
        courant = ""
        for mot in para.split(" "):
            essai = mot if not courant else courant + " " + mot
            if draw.textlength(essai, font=font) <= max_w:
                courant = essai
            else:
                if courant:
                    lignes.append(courant)
                # mot trop long : coupe brutalement
                while draw.textlength(mot, font=font) > max_w and len(mot) > 1:
                    coupe = len(mot)
                    while coupe > 1 and draw.textlength(mot[:coupe], font=font) > max_w:
                        coupe -= 1
                    lignes.append(mot[:coupe])
                    mot = mot[coupe:]
                courant = mot
        lignes.append(courant)
    return lignes


def _tronquer(txt, n: int) -> str:
    # tronque à n caractères, avec un … final si coupé
    txt = "" if txt is None else str(txt)
    return txt if len(txt) <= n else txt[: n - 1].rstrip() + "…"


def _ligne_hauteur(font) -> int:
    return font.size + 6


def _apport_pour_role(resultat_final: dict, role: str) -> str:
    # apport déclaré pour ce rôle dans le JSON macro (agents[].apport), "" sinon
    for a in (resultat_final or {}).get("agents", []) or []:
        if str(a.get("role", "")).strip().lower() == str(role).strip().lower():
            return a.get("apport", "")
    return ""


# ------------------------------------------------------------------ vignettes
def _charger_vignette(chemin: Path) -> Image.Image | None:
    # image contenue dans un cadre VIGN_W x VIGN_H (ratio gardé), None si illisible
    try:
        im = Image.open(chemin).convert("RGB")
    except Exception:
        return None
    r = min(VIGN_W / im.width, VIGN_H / im.height)
    im = im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))),
                   Image.Resampling.LANCZOS)
    fond = Image.new("RGB", (VIGN_W, VIGN_H), "#ffffff")
    fond.paste(im, ((VIGN_W - im.width) // 2, (VIGN_H - im.height) // 2))
    return fond


# ------------------------------------------------------------------ cartes
def _render_carte(idx: int, work_dir: Path, worker: dict,
                  resultat_final: dict) -> Image.Image:
    # carte d'un worker : bandeau rôle + badge confiance, blocs texte, vignettes.
    # hauteur calculée en 2 passes (pré-calcul du texte, puis rendu réel).
    role = worker.get("role", f"agent {idx}")
    objectif = worker.get("objectif", "")
    res = worker.get("resultat", {}) or {}
    confiance = str(res.get("confiance", "?")).lower()
    methode = res.get("methode", "")
    incertitudes = res.get("incertitudes", []) or []
    apport = _apport_pour_role(resultat_final, role) or res.get("resultat", "")
    artefacts = worker.get("artefacts") or res.get("_artefacts", []) or []

    couleur = C_ROLE[(idx - 1) % len(C_ROLE)]
    inner = W - 2 * PAD
    tx = PAD + 20
    tw = inner - 40

    # --- pré-calcul du texte pour connaître la hauteur ---
    canvas = Image.new("RGB", (W, 40), C_CARTE_BG)
    d0 = ImageDraw.Draw(canvas)

    blocs: list[tuple[str, str, ImageFont.FreeTypeFont]] = []
    if objectif:
        blocs.append(("Objectif", _tronquer(objectif, 320), F_BODY))
    if apport:
        blocs.append(("Apport", _tronquer(apport, 360), F_BODY))
    if methode:
        blocs.append(("Méthode", _tronquer(methode, 260), F_SMALL))
    if incertitudes:
        txt = " • ".join(_tronquer(str(i), 120) for i in incertitudes[:3])
        blocs.append(("Incertitudes", _tronquer(txt, 300), F_SMALL))

    h = 0
    h += 56                                   # bandeau titre
    h += 12
    lignes_par_bloc = []
    for label, contenu, font in blocs:
        lignes = _wrap(d0, contenu, font, tw - 130)
        lignes_par_bloc.append((label, lignes, font))
        h += max(_ligne_hauteur(F_LBL), len(lignes) * _ligne_hauteur(font)) + 10

    vignettes = [a for a in artefacts][:MAX_VIGNETTES]
    reste = max(0, len(artefacts) - len(vignettes))
    if vignettes:
        h += 40                               # sous-titre "Artefacts produits"
        n_lignes_v = (len(vignettes) + COLS_VIGN - 1) // COLS_VIGN
        h += n_lignes_v * (VIGN_H + 30) + 6
    else:
        h += 34                               # mention "aucun artefact image"
    h += 24                                   # marge basse

    # --- rendu réel ---
    carte = Image.new("RGB", (W, h), C_CARTE_BG)
    d = ImageDraw.Draw(carte)
    d.rectangle([0, 0, W - 1, h - 1], outline=C_CARTE_BORD, width=2)

    # bandeau rôle
    d.rectangle([0, 0, W, 52], fill=couleur)
    titre = f"Agent {idx} — {role}"
    d.text((PAD, 26 - F_H.size // 2 - 2), _tronquer(titre, 70),
           font=F_H, fill="#ffffff")
    # badge confiance
    bcol = BADGE.get(confiance, "#555555")
    btxt = f"confiance : {confiance}"
    bw = int(d.textlength(btxt, font=F_SMALL)) + 24
    d.rectangle([W - PAD - bw, 12, W - PAD, 40], fill=bcol)
    d.text((W - PAD - bw + 12, 26 - F_SMALL.size // 2 - 1), btxt,
           font=F_SMALL, fill="#ffffff")

    y = 52 + 14
    for label, lignes, font in lignes_par_bloc:
        d.text((tx, y), label, font=F_LBL, fill=couleur)
        yy = y
        for ln in lignes:
            d.text((tx + 130, yy), ln, font=font, fill=C_TXT)
            yy += _ligne_hauteur(font)
        y = max(y + _ligne_hauteur(F_LBL), yy) + 10

    # vignettes
    if vignettes:
        d.text((tx, y), "Artefacts produits", font=F_LBL, fill=couleur)
        if reste:
            d.text((tx + 260, y + 2), f"(+{reste} autre(s) non affiché(s))",
                   font=F_SMALL, fill=C_MUTED)
        y += 34
        for i, nom in enumerate(vignettes):
            col = i % COLS_VIGN
            row = i // COLS_VIGN
            vx = tx + col * (VIGN_W + 20)
            vy = y + row * (VIGN_H + 30)
            vig = _charger_vignette(work_dir / nom)
            if vig is not None:
                carte.paste(vig, (vx, vy))
            else:
                d.rectangle([vx, vy, vx + VIGN_W, vy + VIGN_H], fill="#eeeeee")
                d.text((vx + 10, vy + 10), "(illisible)", font=F_SMALL, fill=C_MUTED)
            d.rectangle([vx, vy, vx + VIGN_W, vy + VIGN_H],
                        outline=C_VIGN_BORD, width=1)
            d.text((vx + 2, vy + VIGN_H + 4), _tronquer(nom, 40),
                   font=F_SMALL, fill=C_MUTED)
    else:
        d.text((tx, y), "Aucun artefact image produit par cet agent.",
               font=F_SMALL, fill=C_MUTED)

    return carte


def _render_cover(stem: str, resultat_final: dict,
                  workers: list[dict]) -> Image.Image:
    # page de garde : document/type/titre + liste des agents et leur apport.
    # on dessine sur un canvas large puis on recadre à la hauteur utilisée.
    inner = W - 2 * PAD
    canvas = Image.new("RGB", (W, 4000), C_FOND)
    d = ImageDraw.Draw(canvas)

    y = 0
    d.rectangle([0, 0, W, 84], fill=C_HEADER)
    d.text((PAD, 42 - F_TITRE.size // 2 - 2),
           "Synthèse du travail multi-agents", font=F_TITRE, fill=C_HEADER_TXT)
    y = 84 + 24

    type_doc = (resultat_final or {}).get("type_document", "?")
    titre = (resultat_final or {}).get("titre") or "(titre non lu)"
    for label, val in [("Document", stem), ("Type", type_doc), ("Titre", titre)]:
        d.text((PAD, y), f"{label} :", font=F_LBL, fill=C_HEADER)
        for ln in _wrap(d, _tronquer(val, 160), F_BODY, inner - 150):
            d.text((PAD + 140, y), ln, font=F_BODY, fill=C_TXT)
            y += _ligne_hauteur(F_BODY)
        y += 8
    y += 8

    d.rectangle([PAD, y + 4, PAD + 8, y + F_H.size + 4], fill=C_HEADER)
    d.text((PAD + 20, y), "Agents mobilisés", font=F_H, fill=C_HEADER)
    y += F_H.size + 16

    for i, wk in enumerate(workers, 1):
        role = wk.get("role", f"agent {i}")
        res = wk.get("resultat", {}) or {}
        apport = _apport_pour_role(resultat_final, role) or res.get("resultat", "")
        conf = str(res.get("confiance", "?")).lower()
        nb_art = len(wk.get("artefacts") or res.get("_artefacts", []) or [])
        couleur = C_ROLE[(i - 1) % len(C_ROLE)]
        d.rectangle([PAD, y + 2, PAD + 26, y + 26], fill=couleur)
        d.text((PAD + 6, y + 3), str(i), font=F_LBL, fill="#ffffff")
        d.text((PAD + 40, y), _tronquer(role, 70), font=F_LBL, fill=C_TXT)
        d.text((W - PAD - 260, y), f"[{conf}] · {nb_art} artefact(s)",
               font=F_SMALL, fill=C_MUTED)
        y += _ligne_hauteur(F_LBL)
        for ln in _wrap(d, _tronquer(apport, 300), F_BODY, inner - 60):
            d.text((PAD + 40, y), ln, font=F_BODY, fill=C_MUTED)
            y += _ligne_hauteur(F_BODY)
        y += 12

    return canvas.crop((0, 0, W, min(y + PAD, 4000)))


def _paginer(cartes: list[Image.Image]) -> list[Image.Image]:
    # regroupe les cartes en pages sans dépasser MAX_PAGE_H
    pages: list[Image.Image] = []
    lot: list[Image.Image] = []
    htot = PAD
    for c in cartes:
        besoin = c.height + GAP
        if lot and htot + besoin > MAX_PAGE_H:
            pages.append(_assembler_page(lot))
            lot, htot = [], PAD
        lot.append(c)
        htot += besoin
    if lot:
        pages.append(_assembler_page(lot))
    return pages


def _assembler_page(cartes: list[Image.Image]) -> Image.Image:
    # empile verticalement les cartes, centrées, sur une page
    h = PAD + sum(c.height + GAP for c in cartes)
    page = Image.new("RGB", (W, h), C_FOND)
    y = PAD
    for c in cartes:
        page.paste(c, ((W - c.width) // 2, y))
        y += c.height + GAP
    return page


def generer_montages(work_dir: Path, output_dir: Path, stem: str,
                     resultat_final: dict, workers: list[dict]) -> list[Path]:
    # point d'entrée : page de garde + cartes paginées -> PNG dans output_dir.
    # workers : [{role, objectif, resultat}] ; `resultat` peut porter
    # confiance/methode/incertitudes/_artefacts, et une clé `artefacts` au
    # niveau worker est aussi acceptée.
    work_dir = Path(work_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    workers = workers or []

    pages: list[Image.Image] = [_render_cover(stem, resultat_final, workers)]
    cartes = [_render_carte(i, work_dir, wk, resultat_final)
              for i, wk in enumerate(workers, 1)]
    pages.extend(_paginer(cartes))

    chemins: list[Path] = []
    n = len(pages)
    for i, page in enumerate(pages, 1):
        nom = f"{stem}_synthese_{i:02d}.png" if n > 1 else f"{stem}_synthese.png"
        chemin = output_dir / nom
        page.save(chemin, format="PNG")
        chemins.append(chemin)
    return chemins
