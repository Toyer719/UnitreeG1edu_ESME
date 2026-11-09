"""Le code QR de l'adresse de la borne (js/borne/qr.js, vague 6, section 13.5 du plan) : agent Borne et orchestrateur.

Le module est chargé dans Firefox sans fenêtre ; ses grilles (adresses de la borne, textes courts et longs, accents,
versions 1 à 13, niveaux L, M, Q, H) sont dessinées en image et relues par OpenCV (cv2.QRCodeDetector) : le texte
relu doit être exactement celui encodé. Le SVG a sa marge de 4 modules et ses classes de couleur.
"""
import shutil

import numpy as np
import pytest

from .test_borne_communs import ServeurDemo, client_demo
from .test_serveur_navigateur import arreter_navigateur, demarrer_navigateur

cv2 = pytest.importorskip("cv2")
pytestmark = pytest.mark.skipif(shutil.which("geckodriver") is None or shutil.which("firefox") is None,
                                reason="geckodriver ou Firefox absent")

TEXTES = [
    ("http://192.168.0.12:8143/borne", "M"),
    ("http://127.0.0.1:8000/borne", "M"),
    ("http://10.0.0.5:8000/borne", "L"),
    ("Borne du lycée : salle B204, à droite après l'amphithéâtre", "Q"),
    ("http://192.168.178.100:8000/borne?langue=fr&salle=" + "x" * 90, "M"),      # version 7 et plus
    ("H" * 200, "H"),
    ("a", "M"),
]

GRILLES = """
const [textes, fini] = arguments;
import('/js/borne/qr.js').then((Q) => {
  fini(textes.map((t) => {
    const q = Q.codeQR(t[0], t[1]);
    return { lignes: Q.lignesQR(t[0], t[1]), version: q.version, masque: q.masque };
  }));
}).catch((e) => fini(String(e)));
"""

SVG = """
const fini = arguments[arguments.length - 1];
import('/js/borne/qr.js').then((Q) => {
  const s = Q.svgQR('http://192.168.0.12:8143/borne', { titre: 'Adresse de la borne' });
  fini([s.getAttribute('viewBox'), s.querySelector('.qr-fond') !== null, s.querySelector('.qr-modules') !== null,
        s.getAttribute('aria-label'), s.getAttribute('data-version')]);
}).catch((e) => fini(String(e)));
"""


def relire(lignes, echelle=8, marge=4):
    """Le texte d'une grille de modules (« 1 » sombre), relu par OpenCV."""
    grille = np.array([[c == "1" for c in ligne] for ligne in lignes], dtype=bool)
    image = np.where(grille, 0, 255).astype(np.uint8)
    image = np.pad(image, marge, constant_values=255)
    image = np.kron(image, np.ones((echelle, echelle), dtype=np.uint8))
    texte, points, _ = cv2.QRCodeDetector().detectAndDecode(image)
    return texte if points is not None else None


@pytest.fixture(scope="module")
def nav():
    gecko, n = demarrer_navigateur()
    try:
        yield n
    finally:
        arreter_navigateur(gecko, n)


def test_codes_relus_par_opencv(nav, tmp_path, monkeypatch):
    app, pont, _ = client_demo(tmp_path, monkeypatch, ros=False)
    with ServeurDemo(app, pont) as serveur:
        nav.ouvrir(serveur.base + "/borne")
        resultats = nav.js_async(GRILLES, [list(t) for t in TEXTES])
        svg = nav.js_async(SVG)
    assert isinstance(resultats, list), resultats
    versions = []
    for (texte, niveau), r in zip(TEXTES, resultats):
        taille = r["version"] * 4 + 17
        assert len(r["lignes"]) == taille and all(len(x) == taille for x in r["lignes"])
        assert relire(r["lignes"]) == texte, (texte, niveau, r["version"])
        versions.append(r["version"])
    assert versions[0] == 3 and max(versions) >= 7, versions
    assert svg[0] == "0 0 37 37" and svg[1] and svg[2] and svg[3] == "Adresse de la borne" and svg[4] == "3"
