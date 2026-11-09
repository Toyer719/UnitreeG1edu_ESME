"""L'analyse d'une séance, sans ROS (vague 6, section 13.3 du plan) : agent Boîte noire.

Sur la séance d'essai de test_seance_communs (repérage, b204 atteinte, ARRÊT en route vers le CDI, « Débloquer »,
retour à l'accueil, puis un mouvement sans demande) : les trajets et leurs causes, les états du pont, les modes,
la batterie, le repérage, les erreurs, les anomalies détectées toutes seules, la chronologie ; et les cas limites
(séance vide, interrompue, enregistrement coupé, verrou posé hors de l'Atelier, visiteur perdu, robot muet,
mouvement à la télécommande, scan, pilotage).
"""
import math
import re
from types import SimpleNamespace

import pytest

from atelier.seance import analyse as A
from atelier.seance.lecture import Donnees
from atelier.seance.manifeste import heure_iso, lire_heure
from . import test_seance_communs as C

T0 = 1794000000.0


@pytest.fixture
def lieu():
    salles = {"accueil": {"nom": "Accueil", "x": 2.5, "y": 10.0, "etage": "rdc"},
              "b204": {"nom": "Salle B204", "x": 21.0, "y": 13.0, "etage": "rdc"},
              "cdi": {"nom": "CDI", "x": 23.0, "y": 7.0, "etage": "rdc"}}
    return A.Lieu(salles=salles, noeuds={"hall_nord": {"x": 2.5, "y": 13.0, "etage": "rdc"}}, principal="accueil",
                  etage="rdc", nom="Lycée démo")


def _manifeste(**plus):
    m = {"id": "2026-11-12_14h03", "etat": "fermee", "mode": "repetition", "lieu": "essai", "etage": "rdc",
         "debut": heure_iso(T0), "fin": heure_iso(T0 + C.DUREE), "duree_s": C.DUREE, "fermeture": "terminer",
         "ouverture": "auto", "enregistrement": {"etat": "arrete", "octets": 1000}, "jetson": []}
    m.update(plus)
    return m


def _string(d):
    import json
    return SimpleNamespace(data=json.dumps(d))


def test_trajets_de_la_seance_d_essai(lieu):
    d = C.donnees_essai(T0)
    trajets = A.trajets(d, C.actions_essai(T0), lieu, fin_seance=T0 + C.DUREE)
    attendus = [("b204", "arrive"), ("cdi", "interrompu"), ("accueil", "arrive")]
    assert [(t["cible"], t["resultat"]) for t in trajets] == attendus
    premier, second, troisieme = trajets
    assert premier["depart"] == "Accueil" and premier["nom"] == "Salle B204"
    assert premier["distance_m"] == pytest.approx(C.DISTANCE_B204, abs=0.3)
    assert premier["duree_s"] == pytest.approx(59.5, abs=0.3)
    assert [a["cause"] for a in premier["arrets"]] == ["bloqué (plus de progrès)"]
    assert second["depart"] == "Salle B204" and second["cause"].startswith("ARRÊT")
    assert second["distance_m"] == pytest.approx(2.0, abs=0.2)
    assert second["arrets"][-1]["cause"].startswith("ARRÊT")
    # parti de l'endroit de l'ARRÊT, à 2 m de la salle B204 : nommé par la salle la plus proche et ses coordonnées
    assert troisieme["depart"] == "près de Salle B204 (21,6 ; 11,1)" and troisieme["nom"] == "Accueil"
    assert troisieme["distance_m"] > 15.0
    assert all(lire_heure(t["debut"]) < lire_heure(t["fin"]) for t in trajets)


def test_cause_d_une_fin_de_trajet():
    actions = [{"genre": "bloquer", "t": heure_iso(T0, ms=True)}]
    assert A.cause_fin(T0 + 0.5, {}, [], actions, []) == "« Bloquer »"
    assert A.cause_fin(T0 + 10, {}, [], actions, []) == "arrêt sans cause connue"        # trop loin
    assert A.cause_fin(T0, {"immobilise": "pas_en_marche"}, [], [], []) == "robot pas en mode marche"
    assert A.cause_fin(T0, {}, [(T0 - 0.2, {"code": "immobilise", "raison": "robot_muet"})], [], []) \
        == "robot qui ne répond plus"
    assert A.cause_fin(T0, {}, [], [], [(T0 - 0.1, True)]) == "verrou posé hors de l'Atelier"
    assert A.cause_fin(T0, {}, [(T0, {"code": "arret"})], [], []).startswith("arrêt demandé par un programme")
    assert A.cause_fin(T0, {}, [], [{"genre": "stop", "t": heure_iso(T0)}], []) == "« Arrêter le trajet »"


def test_visiteur_perdu_nouvelle_demande_et_seance_finie_en_route(lieu):
    d = Donnees()
    etats = [(0, "en_route", "b204", "visite"), (5, "attente_visiteur", "b204", "visite"),
             (10, "retour", "accueil", "retour"), (20, "attente", None, None),
             (30, "en_route", "cdi", "visite"), (35, "en_route", "b204", "visite"), (40, "en_route", "b204", "visite")]
    for t, etat, cible, mission in etats:
        d.ajouter("/guide/etat", "std_msgs/msg/String", T0 + t,
                  _string({"etat": etat, "cible": cible, "mission": mission}))
    d.ajouter("/guide/evenement", "std_msgs/msg/String", T0 + 20, _string({"code": "retour_arrive"}))
    trajets = A.trajets(d, [], lieu, fin_seance=T0 + 50)
    assert [(t["cible"], t["resultat"]) for t in trajets] == [
        ("b204", "abandonne"), ("accueil", "arrive"), ("cdi", "remplace"), ("b204", "en_cours")]
    assert trajets[0]["arrets"][0]["cause"] == "il attend le visiteur"
    assert trajets[1]["mission"] == "retour" and trajets[3]["duree_s"] == 15.0


def test_robot_perdu_puis_echec(lieu):
    d = Donnees()
    for t, etat in ((0, "en_route"), (3, "perdu"), (18, "echec")):
        d.ajouter("/guide/etat", "std_msgs/msg/String", T0 + t,
                  _string({"etat": etat, "cible": "b204", "mission": "visite"}))
    (t,) = A.trajets(d, [], lieu)
    assert t["resultat"] == "echec" and t["cause"] == "robot perdu (repérage)"
    assert t["arrets"][0]["cause"] == "perdu (repérage)"


def test_positions_longueur_et_vitesses():
    pts = [(T0 + i * 0.1, i * 0.03, 0.0) for i in range(50)]           # 0,3 m/s pendant 5 s
    assert A.longueur(pts) == pytest.approx(1.47, abs=0.01)
    v = A.vitesses(pts)
    assert v and all(x[1] == pytest.approx(0.3, abs=0.01) for x in v)
    # un saut de repérage (3 m d'un coup) et les tremblements ne comptent pas dans la distance
    saut = [(T0, 0.0, 0.0), (T0 + 0.2, 3.0, 0.0), (T0 + 0.4, 3.005, 0.0), (T0 + 0.6, 3.5, 0.0)]
    assert A.longueur(saut) == pytest.approx(0.5, abs=0.01)
    d = C.donnees_essai(T0)
    assert A.positions(d)[0] == "/reperage/etat"
    assert A.positions(d, A.SOURCES_VITESSE)[0] == "/g1_jumeau/odom"
    assert A.positions(Donnees()) == (None, [])
    assert A.position_a(pts, T0 + 1.04)[0] == pytest.approx(T0 + 1.0)
    assert A.position_a(pts, T0 + 100) is None


def test_pont_modes_batterie_reperage():
    d = C.donnees_essai(T0)
    etats = A.etats_pont(d)
    assert etats["arret_verrouille"] == pytest.approx(10.0, abs=0.6)
    assert sum(etats.values()) == pytest.approx(C.DUREE, abs=1.0)
    assert set(etats) == {"pret", "en_mouvement", "arret_verrouille"}
    (mode,) = A.modes_robot(d)
    assert mode["fsm"] == 501 and mode["nom"] == "marche" and mode["secondes"] > 150
    assert A.batterie(d) == {"debut": 87, "fin": 85}
    r = A.reperage(d)
    assert r["precision_moyenne_m"] == pytest.approx(0.03, abs=0.002) and r["precision_max_m"] == 0.04
    assert r["reperages"] == 1 and r["pertes"] == 0
    # sans /pont/etat : les modes viennent des réponses 7001
    d2 = Donnees()
    from atelier.seance.analyse import modes_robot
    reponse = SimpleNamespace(header=SimpleNamespace(identity=SimpleNamespace(id=1, api_id=7001),
                                                     status=SimpleNamespace(code=0)), data='{"data": 3}')
    d2.ajouter("/api/sport/response", "unitree_api/msg/Response", T0, reponse)
    assert modes_robot(d2)[0]["fsm"] == 3 and modes_robot(d2)[0]["nom"] == "assis"


def test_erreurs():
    d = C.donnees_essai(T0)
    liste = A.erreurs(d, C.actions_essai(T0), [("journaux/serveur.log", "ERROR boom"),
                                               ("journaux/serveur.log", "ERROR boom")])
    textes = [e["texte"] for e in liste]
    assert any("refusé (422)" in t and "salles.yaml" in t for t in textes)
    (nav2,) = [e for e in liste if "Failed to make progress" in (e.get("technique") or "")]   # /rosout ERROR
    assert nav2["source"] == "La navigation (Nav2)" and nav2["texte"].startswith("La navigation n'avançait plus")
    assert nav2["technique"] == "nœud controller_server : Failed to make progress"
    assert not any("Begin navigating" in (e.get("technique") or "") for e in liste)       # l'INFO n'y est pas
    (journal,) = [e for e in liste if e["source"] == "Journal du serveur de l'Atelier"]
    assert journal["nombre"] == 2                                   # lignes identiques regroupées
    assert journal["technique"] == "journaux/serveur.log : ERROR boom"
    assert A.lignes_erreur("ok\n[ERROR] [x]: boum\nTraceback (most recent call last):\nrien", "f") == [
        ("f", "[ERROR] [x]: boum", False), ("f", "Traceback (most recent call last):", False)]


def test_anomalies_de_la_seance_d_essai(lieu):
    d = C.donnees_essai(T0)
    actions = C.actions_essai(T0)
    trajets = A.trajets(d, actions, lieu)
    anomalies = A.anomalies(d, actions, _manifeste(), trajets)
    genres = [a["genre"] for a in anomalies]
    assert genres.count("mouvement_sans_demande") == 1
    # l'ARRÊT ; son verrou n'est pas compté deux fois, et le verrou faux d'avant la séance n'est pas un événement
    assert genres.count("arret_urgence") == 1
    (m,) = [a for a in anomalies if a["genre"] == "mouvement_sans_demande"]
    assert m["gravite"] == "probleme" and "ordres de marche" in m["texte"]
    assert lire_heure(m["t"]) == pytest.approx(T0 + 160.0, abs=0.7)
    assert m["distance_m"] == pytest.approx(1.5, abs=0.2) and m["duree_s"] == pytest.approx(5.0, abs=0.7)
    assert m["position"][0] == pytest.approx(2.5, abs=0.3)
    assert "7105" in m["technique"]                    # le détail technique, pas dans la phrase
    assert "7105" not in m["texte"] and "/cmd_vel" not in m["texte"]


def test_mouvement_sans_ordre_du_pc_pendant_un_scan_et_pendant_le_pilotage(lieu):
    def seance(avec_ordres, extra=None):
        d = Donnees()
        for i in range(60):
            t = T0 + i * 0.1
            x = 0.0 if i < 10 else 0.04 * (i - 10)          # 0,4 m/s à partir de 1 s
            d.ajouter("/g1_jumeau/odom", "nav_msgs/msg/Odometry", t, C._faux_message("odom", (x, 0.0)))
            d.ajouter("/guide/etat", "std_msgs/msg/String", t, _string({"etat": "attente", "cible": None}))
            if avec_ordres and i >= 10:
                d.ajouter("/api/sport/request", "unitree_api/msg/Request", t,
                          C._faux_message("requete", (7105, '{"velocity": [0.4, 0, 0], "duration": 0.5}')))
        if extra:
            extra(d)
        return d
    (a,) = A.mouvements_sans_demande(seance(False), [])
    assert a["gravite"] == "attention" and "sans ordre du PC" in a["texte"]
    (b,) = A.mouvements_sans_demande(seance(True), [])
    assert b["gravite"] == "probleme"
    # pendant un scan (la télécommande promène le robot), pendant le pilotage : pas d'anomalie
    scan = [{"genre": "scan", "chemin": "/api/scan/demarrer", "statut": 200, "t": heure_iso(T0, ms=True)}]
    assert A.mouvements_sans_demande(seance(False), scan) == []

    def pilotage(d):
        d.ajouter("/mouvement/maitre", "std_msgs/msg/String", T0, _string({"maitre": "pilotage"}))
    assert A.mouvements_sans_demande(seance(True, pilotage), []) == []

    def joystick(d):
        for i in range(60):
            d.ajouter("/pilotage/etat", "std_msgs/msg/String", T0 + i * 0.5,
                      _string({"maitre": "guide", "consigne": {"vx": 0.4, "vy": 0, "wz": 0}, "age_ordre_s": 0.1}))
    assert A.mouvements_sans_demande(seance(True, joystick), []) == []
    # le robot qui freine juste après une mission n'est pas une anomalie (2 s de grâce)
    d = Donnees()
    for i in range(40):
        t = T0 + i * 0.1
        d.ajouter("/g1_jumeau/odom", "nav_msgs/msg/Odometry", t, C._faux_message("odom", (0.03 * min(i, 25), 0.0)))
        etat = "en_route" if i < 20 else "attente"
        d.ajouter("/guide/etat", "std_msgs/msg/String", t, _string({"etat": etat, "cible": "b204"}))
    assert A.mouvements_sans_demande(d, []) == []


def test_autres_anomalies():
    d = Donnees()
    for i, etat in enumerate(["pret", "robot_muet", "robot_muet", "robot_muet", "pret"]):
        d.ajouter("/pont/etat", "std_msgs/msg/String", T0 + i, _string({"etat": etat}))
    d.ajouter("/pont/arret", "std_msgs/msg/Bool", T0 + 10, SimpleNamespace(data=True))
    d.ajouter("/reperage/etat", "std_msgs/msg/String", T0 + 11, _string({"etat": "repere", "repere": True}))
    d.ajouter("/reperage/etat", "std_msgs/msg/String", T0 + 12, _string({"etat": "perdu", "repere": False}))
    actions = [{"genre": "y_aller", "texte": "Y aller : b204", "statut": 500, "t": heure_iso(T0 + 2, ms=True),
                "reponse": {"detail": "Internal Server Error"}}]
    m = _manifeste(etat="interrompue", fermeture="plantage",
                   enregistrement={"etat": "coupe", "message": "Enregistrement arrêté : il ne reste que 1,2 Go"})
    genres = {a["genre"]: a for a in A.anomalies(d, actions, m)}
    assert set(genres) == {"robot_muet", "arret_urgence", "seance_interrompue", "enregistrement_coupe",
                           "erreur_serveur", "reperage_perdu"}
    assert genres["robot_muet"]["gravite"] == "attention" and "au repos" in genres["robot_muet"]["texte"]
    assert "hors de l'Atelier" in genres["arret_urgence"]["texte"]
    assert genres["enregistrement_coupe"]["texte"].startswith("Enregistrement arrêté")
    assert genres["erreur_serveur"]["gravite"] == "probleme"


def test_chronologie(lieu):
    d = C.donnees_essai(T0)
    actions = C.actions_essai(T0)
    trajets = A.trajets(d, actions, lieu)
    anomalies = A.anomalies(d, actions, _manifeste(), trajets)
    chrono = A.chronologie(d, actions, _manifeste(), anomalies, lieu)
    assert chrono[0]["texte"].startswith("Séance ouverte") and chrono[-1]["texte"].startswith("Séance terminée")
    assert [lire_heure(c["t"]) for c in chrono] == sorted(lire_heure(c["t"]) for c in chrono)
    textes = [c["texte"] for c in chrono]
    assert "ARRÊT" in textes and "Y aller : Salle B204" in textes and "Débloquer" in textes
    assert "Guide : arrivé : Salle B204" in textes and "Guide : départ vers CDI" in textes
    assert "Pont vers la marche : bloqué (verrou)" in textes
    assert "Mode du robot : marche (501)" in textes
    assert any(t.startswith("Repérage : repéré (précision") for t in textes)
    assert "Verrou du pont posé : robot bloqué" in textes
    assert any(t.startswith("Anomalie : Le robot a bougé") for t in textes)
    assert any("refusé (422)" in t for t in textes)
    # les passages pret ↔ en_mouvement du pont ne remplissent pas la chronologie
    assert not any(t == "Pont vers la marche : en mouvement" for t in textes)
    assert chrono[0]["depuis_s"] == 0.0


def test_analyser_rend_le_format_de_rapport_json(lieu):
    d = C.donnees_essai(T0)
    r = A.analyser(_manifeste(), C.actions_essai(T0), d, lieu, [("journaux/serveur.log", "ERROR x")],
                   {"sujets": {"/guide/etat": {"nombre": 851}}, "octets": 1234, "metadata": True},
                   {"etat": "probleme", "a_regler": []}, fichiers=["seance.json"])
    for cle in ("version", "seance", "mode", "lieu", "debut", "fin", "duree_s", "batterie", "actions", "trajets",
                "etats_pont", "modes", "erreurs", "reperage", "anomalies", "fichiers"):
        assert cle in r, cle
    assert r["seance"] == "2026-11-12_14h03" and r["actions"] == 8 and r["duree_s"] == C.DUREE
    assert set(r["trajets"][0]) >= {"depart", "cible", "nom", "resultat", "duree_s", "distance_m", "arrets"}
    assert not any(k.startswith("_") for t in r["trajets"] for k in t)
    assert set(r["reperage"]) >= {"precision_moyenne_m", "precision_max_m"}
    assert all(set(a) >= {"t", "genre", "texte"} for a in r["anomalies"])
    assert r["resume"]["trajets"] == 3 and r["resume"]["par_resultat"] == {"arrive": 2, "interrompu": 1}
    assert r["resume"]["distance_totale_m"] > r["resume"]["distance_m"]          # le mouvement sans demande
    assert r["trajet_source"] == "/reperage/etat" and r["nom_lieu"] == "Lycée démo"
    import json
    json.dumps(r)                                                                 # tout est sérialisable


def test_seance_vide_sans_rien_enregistre():
    d = Donnees()
    d.erreur = "pas d'enregistrement ROS 2 dans cette séance"
    r = A.analyser(_manifeste(enregistrement={"etat": "absent", "message": "pas de ROS 2"}), [], d)
    assert r["trajets"] == [] and r["batterie"] == {"debut": None, "fin": None}
    assert r["reperage"]["precision_moyenne_m"] is None and r["etats_pont"] == {} and r["modes"] == []
    assert r["resume"]["trajets"] == 0 and r["enregistrement"]["lecture"].startswith("pas d'enregistrement")
    assert [c["genre"] for c in r["chronologie"]] == ["seance", "seance"]


def test_lieu_nom_et_endroit(lieu):
    assert lieu.nom_de("b204") == "Salle B204" and lieu.nom_de("principal") == "Accueil"
    assert lieu.nom_de("hall_nord") == "Hall nord" and lieu.nom_de("inconnu") == "inconnu" and lieu.nom_de(None) == "?"
    assert lieu.endroit(21.3, 12.8) == "Salle B204" and lieu.endroit(2.6, 12.9) == "Hall nord"
    assert lieu.endroit(12.0, 2.0) is None
    assert math.isclose(len(lieu.noms()), 3)


def test_verrou_garde_d_avant_la_seance():
    """/pont/arret garde son dernier message (transient_local) : le premier, reçu à l'ouverture, est l'état d'avant
    la séance, pas un verrou posé pendant la séance."""
    def seance(premier):
        d = Donnees()
        d.ajouter("/guide/etat", "std_msgs/msg/String", T0, _string({"etat": "attente", "cible": None}))
        d.ajouter("/pont/arret", "std_msgs/msg/Bool", T0 + 0.8, SimpleNamespace(data=premier))
        return d
    deja = A.anomalies(seance(True), [], _manifeste())
    assert [a["texte"] for a in deja] == ["Le robot était déjà bloqué au début de la séance (verrou du pont posé "
                                          "avant)."]
    assert A.anomalies(seance(False), [], _manifeste()) == []
    textes = [c["texte"] for c in A.chronologie(seance(True), [], _manifeste())]
    assert "Au début, le robot est bloqué (verrou du pont)" in textes and "Verrou du pont posé : robot bloqué" \
        not in textes
    # posé plus tard (au-delà de 3 s), sans ARRÊT ni « Bloquer » de l'Atelier : hors de l'Atelier
    d = seance(False)
    d.ajouter("/pont/arret", "std_msgs/msg/Bool", T0 + 30, SimpleNamespace(data=True))
    (a,) = A.anomalies(d, [], _manifeste())
    assert "hors de l'Atelier" in a["texte"] and a["gravite"] == "attention"
    bloquer = [{"genre": "bloquer", "t": heure_iso(T0 + 29.5, ms=True)}]
    (a,) = A.anomalies(d, bloquer, _manifeste())
    assert a["texte"].startswith("Robot bloqué par « Bloquer »") and a["gravite"] == "info"


def test_nombres_a_la_francaise():
    assert A.fr(1.5) == "1,5" and A.fr(0.304, 2) == "0,30" and A.fr(12, 0) == "12"


def test_erreur_d_un_noeud_recopiee_dans_un_journal_comptee_une_fois():
    d = Donnees()
    d.ajouter("/rosout", "rcl_interfaces/msg/Log", T0,
              SimpleNamespace(level=40, name="bt_navigator", msg="Failed to get result for follow_path"))
    ligne = "[bt_navigator-11] [ERROR] [1794183646.4] [bt_navigator]: Failed to get result for follow_path"
    liste = A.erreurs(d, [], [("journaux/atelier_navigation.log", ligne), ("journaux/serveur.log", "ERROR autre")])
    assert [(e["source"], e["technique"]) for e in liste] == [
        ("La navigation (Nav2)", "nœud bt_navigator : Failed to get result for follow_path"),
        ("Journal du serveur de l'Atelier", "journaux/serveur.log : ERROR autre")]


# ------------------------------------------------ corrections de la vague 6 (revue de l'interface, défaut 6)
# Les messages normaux d'un arrêt étaient comptés comme « Erreurs », en anglais, avec les noms des nœuds : la fin du
# journal de la navigation arrêtée par Simuler › Arrêter (séance 2026-11-09_20h38 du relecteur, raccourcie), et le
# message de Nav2 juste après « Bloquer » (séance 2026-11-09_06h34).
JOURNAL_ARRET = """[guide-15] [INFO] [1794254400.1] [guide]: en route
[ERROR] [faux_lidar-3]: process has died [pid 6800, exit code -11, cmd '/x/faux_lidar'].
[WARNING] [launch]: user interrupted with ctrl-c (SIGINT)
[controller_server-6] [INFO] [1794254427.911022851] [rclcpp]: signal_handler(SIGINT/SIGTERM)
[INFO] [guide-15]: sending signal 'SIGINT' to process[guide-15]
[INFO] [detecteur_personnes-14]: sending signal 'SIGINT' to process[detecteur_personnes-14]
[ERROR] [detecteur_personnes-14]: process has died [pid 6890, exit code -2, cmd '/x/detecteur_personnes --ros-args'].
[ERROR] [static_transform_publisher-5]: process has died [pid 6872, exit code -2, cmd '/opt/ros/humble/lib/tf2_ros/x'].
[pilotage-9] Traceback (most recent call last):
[pilotage-9]   File "/x/pilotage", line 33, in <module>
[controller_server-6] [INFO] [1794254427.95] [controller_server]: Destroying
[pilotage-9]     rclpy.spin(noeud)
[pilotage-9] KeyboardInterrupt
[ERROR] [pilotage-9]: process has died [pid 6895, exit code 1, cmd '/x/pilotage'].
[guide-16] Traceback (most recent call last):
[guide-16]   File "/x/guide", line 33, in <module>
[guide-16] RuntimeError: Unable to convert call argument to Python object
[ERROR] [guide-16]: process has died [pid 6896, exit code 1, cmd '/x/guide'].
[ERROR] [gazebo-1]: process[gazebo-1] failed to terminate '5' seconds after receiving 'SIGINT', escalating to 'SIGTERM'
[ERROR] [launch]: using SIGTERM can result in orphaned processes
[INFO] [guide-15]: process has finished cleanly [pid 6892]
"""


def test_un_arret_demande_n_est_pas_une_erreur_dans_les_journaux():
    lignes = A.lignes_erreur(JOURNAL_ARRET, "journaux/atelier_navigation_2026-11-09_20h4409.log")
    assert [(re.search(r"\[([a-z_]+-\d+)\]", ligne).group(1), pendant) for _, ligne, pendant in lignes] == [
        ("faux_lidar-3", False),                     # planté avant l'arrêt : une vraie erreur
        ("guide-16", True), ("guide-16", True)]      # mal fini pendant l'arrêt (RuntimeError, code 1) : gardé
    erreurs = A.erreurs(Donnees(), [], lignes)
    assert [(e["source"], e["texte"]) for e in erreurs] == [
        ("Journal de la navigation", "Le programme « faux_lidar » s'est arrêté seul (code -11)."),
        ("Journal de la navigation", "Erreur Python dans le programme « guide » pendant l'arrêt demandé (la suite du "
                                     "journal dit laquelle)."),
        ("Journal de la navigation", "Le programme « guide » a mal fini pendant l'arrêt demandé (code 1).")]
    assert all(e["technique"].startswith("journaux/atelier_navigation_2026-11-09_20h4409.log : [") for e in erreurs)
    # sans arrêt demandé, le même programme mort de SIGINT reste une erreur
    seul = "[ERROR] [detecteur_personnes-14]: process has died [pid 6890, exit code -2, cmd 'x']."
    assert A.lignes_erreur(seul, "f") == [("f", seul, False)]


def test_le_message_de_nav2_juste_apres_un_arret_n_est_pas_une_erreur():
    halt = "Failed to get result for follow_path in node halt!"
    noeud = "bt_navigator_navigate_through_poses_rclcpp_node"
    for cause in ("bloquer", "arret", "stop", "guide_stop", "pont_arret", "nouveau_but"):
        d, actions = Donnees(), []
        if cause in ("bloquer", "arret", "stop"):
            actions = [{"genre": cause, "texte": cause, "statut": 200, "t": heure_iso(T0 + 10.0, ms=True)}]
        elif cause == "guide_stop":
            d.ajouter("/guide/stop", "std_msgs/msg/Empty", T0 + 10.0, SimpleNamespace())
        elif cause == "pont_arret":
            d.ajouter("/pont/arret", "std_msgs/msg/Bool", T0 + 10.0, SimpleNamespace(data=True))
        else:
            d.ajouter("/guide/aller", "std_msgs/msg/String", T0 + 10.0, _string({"cible": "cdi"}))
        # le journal de la navigation seul (ros2 launch date ses lignes) : 0,5 s après l'arrêt, rien ; 50 s après,
        # sans arrêt, une erreur en français
        lignes = [("journaux/atelier_navigation.log", f"[bt_navigator-10] [ERROR] [{T0 + s:.6f}] [{noeud}]: {halt}")
                  for s in (10.5, 60.0)]
        liste = A.erreurs(d, actions, lignes)
        assert [(lire_heure(e["t"]), e["source"], e["texte"]) for e in liste] == [
            (T0 + 60.0, "La navigation (Nav2)", "La navigation a mis du temps à annuler un trajet.")], cause
        # /rosout : 0,4 s après l'arrêt, rien (ni sa copie dans le journal) ; 30 s après, une erreur
        d.ajouter("/rosout", "rcl_interfaces/msg/Log", T0 + 10.4, SimpleNamespace(level=40, name=noeud, msg=halt))
        assert A.erreurs(d, actions, lignes[:1]) == [], cause
        d.ajouter("/rosout", "rcl_interfaces/msg/Log", T0 + 40.0, SimpleNamespace(level=40, name=noeud, msg=halt))
        (e,) = A.erreurs(d, actions, lignes[:1])
        assert (lire_heure(e["t"]), e["technique"]) == (T0 + 40.0, f"nœud {noeud} : {halt}"), cause


def test_une_ligne_d_un_journal_d_avant_la_seance_n_est_pas_comptee():
    avant = f"[controller_server-6] [ERROR] [{T0 - 30.0:.3f}] [controller_server]: Failed to make progress"
    pendant = f"[controller_server-6] [ERROR] [{T0 + 5.0:.3f}] [controller_server]: Failed to make progress (2)"
    liste = A.erreurs(Donnees(), [], [("journaux/atelier_navigation.log", avant),
                                      ("journaux/atelier_navigation.log", pendant)], debut=T0)
    assert [lire_heure(e["t"]) for e in liste] == [T0 + 5.0]


def test_phrases_des_erreurs_en_francais():
    assert A.de("le serveur de l'Atelier") == "du serveur de l'Atelier" and A.de("la voix") == "de la voix"
    assert A.de("les programmes") == "des programmes" and A.de("l'Atelier") == "de l'Atelier"
    assert A.partie_du_journal("journaux/atelier_demo_2026-11-09_20h5129.log") == "la démo d'accueil"
    assert A.partie_du_journal("journaux/jetson/conteneur_x_avant_arret.log") == "le conteneur du Jetson"
    assert A.partie_du_journal("journaux/atelier_autre_x.log") == "un programme lancé par l'Atelier"
    assert A.programme("bt_navigator_navigate_through_poses_rclcpp_node") == "La navigation (Nav2)"
    assert A.programme("pont_g1") == "Le pont vers la marche" and A.programme("inconnu") == "Un programme"
    assert A.phrase_erreur("Traceback (most recent call last):", source="journaux/serveur.log") == (
        "Journal du serveur de l'Atelier", "Erreur Python dans le serveur de l'Atelier (la suite du journal dit "
                                           "laquelle).")
    assert A.phrase_erreur("[voix-3] [ERROR] [1.0] [voix]: boum", source="journaux/atelier_voix_x.log") == (
        "La voix", "Une erreur a été signalée (voir le détail technique).")
    assert A.phrase_erreur("Planning algorithm GridBased failed to generate a valid path", noeud="planner_server") \
        == ("La navigation (Nav2)", "La navigation n'a pas trouvé de chemin.")


def test_un_etat_de_passage_du_pont_n_a_pas_de_duree():
    d = Donnees()
    for t, etat in ((0.0, "pret"), (1.0, "arret"), (1.0, "arret_verrouille"), (3.0, "pret")):
        d.ajouter("/pont/etat", "std_msgs/msg/String", T0 + t, _string({"etat": etat}))
    assert A.etats_pont(d) == {"arret_verrouille": 2.0, "pret": 1.5}
