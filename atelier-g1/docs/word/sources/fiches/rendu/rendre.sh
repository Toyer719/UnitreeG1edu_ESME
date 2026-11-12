#!/usr/bin/env bash
# Rend les deux fiches en PDF puis en images (vérification de la mise en page).
# À lancer depuis le dossier de travail : ~/robot-g1-donnees/vague5/documents/fiches/rendu/rendre.sh
# (la copie de ~/robot-g1/docs/word/sources/ sert de sauvegarde : lancée là, elle écrirait dans le dépôt).
# Polices : rendu/fonts.conf (Calibri → Lato, comme pour le document du logiciel) ; profil LibreOffice à part,
# dans le dossier de travail persistant (pas dans /tmp).
set -e
ICI="$(cd "$(dirname "$0")/.." && pwd)"
PROFIL="file://$ICI/rendu/profil_libreoffice"
cd "$ICI"
/home/joonho/robot-g1-donnees/venv-docx/bin/python generer_fiches.py
for nom in Seance2_A_faire Seance2_A_remplir; do
  FONTCONFIG_FILE="$ICI/rendu/fonts.conf" soffice -env:UserInstallation="$PROFIL" --headless --convert-to pdf \
    --outdir rendu "$nom.docx" >/dev/null 2>&1
  rm -f rendu/"$nom"-*.png
  pdftoppm -png -r 70 rendu/"$nom".pdf rendu/"$nom"
  echo "$nom : $(pdfinfo rendu/$nom.pdf | grep Pages)"
done
