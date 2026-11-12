#!/usr/bin/env bash
# Critère 1, monde inventé : créer le lieu « essai », y dessiner 6 murs, un passage, 3 objets et
# 2 piétons, puis enregistrer. g1-lieu valider ne signale aucune erreur.
source "$(dirname "$0")/commun.sh"
exiger_commande g1-lieu

g1-lieu creer essai --nom "Essai de bout en bout" || echoue "g1-lieu creer a échoué"

# Le dessin, tel que l'interface l'enregistre : par atelier.lieu
"$PY" - <<'PYTHON' || echoue "enregistrement du monde impossible"
from atelier.lieu import Mur, Objet, Pieton, charger_monde, enregistrer_monde
monde = charger_monde("essai", "rdc")
e = monde.emprise
monde.murs = [
    Mur("ext_sud", (e.xmin, e.ymin), (e.xmax, e.ymin)), Mur("ext_est", (e.xmax, e.ymin), (e.xmax, e.ymax)),
    Mur("ext_nord", (e.xmax, e.ymax), (e.xmin, e.ymax)), Mur("ext_ouest", (e.xmin, e.ymax), (e.xmin, e.ymin)),
    # Une cloison en deux morceaux alignés : le passage d'un mètre est l'écart entre eux
    Mur("cloison_a", (8.0, e.ymin), (8.0, 6.0)), Mur("cloison_b", (8.0, 7.0), (8.0, e.ymax)),
]
monde.objets = [Objet.boite("table_1", (4.0, 3.0), (1.2, 0.8, 0.75), 0.0),
                Objet.cylindre("poteau_1", (12.0, 5.0), 0.2, 2.5),
                Objet.meuble("chaise_1", "chaise", (4.0, 4.0), 1.57)]
monde.pietons = [Pieton("pieton_1", [(2.0, 10.0), (6.0, 10.0)], 0.8, True),
                 Pieton("pieton_2", [(10.0, 2.0), (16.0, 2.0), (16.0, 10.0)], 1.0, False)]
enregistrer_monde("essai", "rdc", monde)
m = charger_monde("essai", "rdc")
assert (len(m.murs), len(m.objets), len(m.pietons)) == (6, 3, 2), (len(m.murs), len(m.objets), len(m.pietons))
print(f"monde enregistré : {len(m.murs)} murs, {len(m.objets)} objets, {len(m.pietons)} piétons")
PYTHON

SORTIE=$(g1-lieu valider --lieu essai 2>&1); CODE=$?
echo "$SORTIE"
[ $CODE -eq 0 ] || echoue "g1-lieu valider signale des erreurs (code $CODE)"
reussi "lieu essai valide, avec 6 murs, un passage, 3 objets et 2 piétons"
