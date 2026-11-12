#!/usr/bin/env bash
# Critère 2, carte sans scan : la génération produit .sdf, .pgm, .yaml et le masque.
# Les tests de pixels de l'agent Monde passent.
source "$(dirname "$0")/commun.sh"
exiger_commande g1-monde
copier_demo essai
rm -f "$ATELIER_LIEUX"/essai/cartes/* "$ATELIER_LIEUX"/essai/mondes/*.sdf
generer essai
L="$ATELIER_LIEUX/essai"
for f in mondes/rdc.sdf cartes/rdc.pgm cartes/rdc.yaml cartes/rdc_interdit.pgm cartes/rdc_interdit.yaml; do
  [ -s "$L/$f" ] || echoue "fichier manquant après la génération : $f"
done

# Quelques pixels connus du lieu demo : un mur à 0, le milieu des couloirs à 254
"$PY" - "$L" <<'PYTHON' || echoue "pixels inattendus dans la carte générée"
import sys
from atelier.lieu import charger_carte, monde_vers_pixel
info, image = charger_carte(f"{sys.argv[1]}/cartes/rdc.yaml")
info_m, masque = charger_carte(f"{sys.argv[1]}/cartes/rdc_interdit.yaml")
assert image.shape == masque.shape and info.origin == info_m.origin, "le masque n'a pas la taille de la carte"
for x, y, attendu in ((10.0, 5.5, 0), (15.0, 0.0, 0), (15.0, 7.0, 254), (15.0, 13.0, 254), (2.5, 10.0, 254)):
    c, l = monde_vers_pixel(x, y, info)
    assert image[l, c] == attendu, f"pixel ({x}, {y}) = {image[l, c]}, attendu {attendu}"
print("pixels vérifiés : murs à 0, couloirs à 254 ; masque de même taille que la carte")
PYTHON

TESTS=$(ls "$RACINE"/atelier/tests/test_monde*.py 2>/dev/null)
[ -n "$TESTS" ] || en_attente "pas encore de tests de l'agent Monde (atelier/tests/test_monde*.py)"
"$PY" -m pytest -q -p no:cacheprovider $TESTS 2>&1 | tail -n 5
[ "${PIPESTATUS[0]}" -eq 0 ] || echoue "des tests de l'agent Monde échouent"
reussi "génération complète, tests de pixels de l'agent Monde réussis"
