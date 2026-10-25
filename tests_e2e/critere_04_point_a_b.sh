#!/usr/bin/env bash
# Critère 4, point A → point B : une salle placée depuis l'API, puis POST /api/guide/aller :
# /guide/etat passe à « arrive », et le robot est à moins de 0,3 m de la salle.
source "$(dirname "$0")/commun.sh"
exiger_commande g1-monde g1-guide g1-atelier
exiger_paquet_ros g1_sim g1_nav
copier_demo essai
generer essai
serveur

# Une nouvelle salle dans le couloir nord, entre couloir_nord_1 et b204, placée par l'API
"$PY" - "$API" <<'PYTHON' || echoue "placement de la salle par l'API impossible"
import json, sys, urllib.request
api = sys.argv[1] + "/api/lieux/essai"
def appel(methode, chemin, corps=None):
    r = urllib.request.Request(api + chemin, method=methode, data=None if corps is None else json.dumps(corps).encode(),
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=30) as reponse:
        return json.loads(reponse.read())
salles = appel("GET", "/salles")
salles.append({"id": "salle_e2e", "nom": "Salle de bout en bout", "alias": [], "etage": "rdc",
               "pose": {"x": 18.0, "y": 13.0, "theta": 1.5708}, "phrase_arrivee": ""})
appel("PUT", "/salles?synchroniser=true", salles)
itineraires = appel("GET", "/itineraires")
assert "salle_e2e" in itineraires["noeuds"], "le nœud de la salle n'a pas été créé"
itineraires["couloirs"] = [c for c in itineraires["couloirs"] if sorted(c) != ["b204", "couloir_nord_1"]]
itineraires["couloirs"] += [["couloir_nord_1", "salle_e2e"], ["salle_e2e", "b204"]]
r = appel("PUT", "/itineraires", itineraires)
print("salle_e2e placée en (18 ; 13) ; rapport :", json.dumps(r.get("rapport", {}), ensure_ascii=False)[:300])
PYTHON

http POST /api/simulation/demarrer '{"lieu": "essai", "etage": "rdc"}' > "$TRAVAIL/journaux/demarrer.log" \
  || echoue "POST /api/simulation/demarrer refusé : $(cat "$TRAVAIL/journaux/demarrer.log")"
"$PY" "$OUTILS" attendre-sujets /odom /points /guide/etat --delai 90 || echoue "simulation ou guide absents"
sleep 5   # que Nav2 finisse de démarrer

# On écoute /guide/etat avant d'envoyer la cible
"$PY" "$OUTILS" etat-guide --attendre arrive --delai 240 > "$TRAVAIL/journaux/guide.log" 2>&1 &
ECOUTE=$!
sleep 2
http POST /api/guide/aller '{"cible": "salle_e2e"}' || echoue "POST /api/guide/aller refusé"
wait $ECOUTE; CODE=$?
cat "$TRAVAIL/journaux/guide.log"
[ $CODE -eq 0 ] || echoue "le guide n'est pas arrivé à salle_e2e"
"$PY" "$OUTILS" pres-de --lieu essai --salle salle_e2e --max 0.3 || echoue "le robot est à plus de 0,3 m de la salle"
http POST /api/simulation/arreter > /dev/null
reussi "arrivé à salle_e2e, à moins de 0,3 m"
