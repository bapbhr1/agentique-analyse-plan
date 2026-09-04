"""Helpers de mise en page du montage de synthèse (pur, sans I/O)."""

from PIL import Image, ImageDraw

from montage import _tronquer, _wrap


def test_tronquer():
    assert _tronquer("abcdef", 10) == "abcdef"
    assert _tronquer("abcdef", 4) == "abc…"
    assert _tronquer(None, 5) == ""


def test_wrap_respecte_la_largeur_max():
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    from montage import F_BODY
    lignes = _wrap(d, "un texte assez long qui doit forcément passer à la ligne", F_BODY, 120)
    assert len(lignes) > 1
    assert all(d.textlength(ln, font=F_BODY) <= 120 for ln in lignes)


def test_wrap_coupe_un_mot_trop_long():
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    from montage import F_BODY
    lignes = _wrap(d, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", F_BODY, 80)
    assert all(d.textlength(ln, font=F_BODY) <= 80 for ln in lignes)
