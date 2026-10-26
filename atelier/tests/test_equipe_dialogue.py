"""Le chatbot d'exemple, le relais des événements vers la voix et la géométrie de la caméra
(atelier.equipe, vague 4, section 11.6 du plan), sans ROS. Agent Équipe."""
import math

import pytest

import atelier
from atelier.equipe.camera import dans_le_champ, message_visiteurs, vers_base_link, visibles_depuis_pietons
from atelier.equipe.dialogue import MESSAGES, Chatbot, decider, en_visite
from atelier.equipe.relais import Relais, Salueur
from atelier.lieu import charger_salles, valider_message
from atelier.lieu import equipe as E
from atelier.lieu.comportement import CODES_EVENEMENT, evenement

DEMO = atelier.RACINE / "lieux" / "demo"


@pytest.fixture(scope="module")
def salles():
    return charger_salles(DEMO)


@pytest.fixture
def bot(salles):
    return Chatbot(E.exemple_equipe("dialogues"), salles, etage="rdc")


class Horloge:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


# ---------------------------------------------------------------- chatbot : l'exemple de bout en bout

def test_exemple_du_plan(bot):
    r = bot.repondre("je cherche la salle b204")
    assert r["regle"] == "chercher_salle" and r["action"] == "guider" and r["passe"] == "entiere"
    assert r["reponse"] == "Je vous emmène à Salle B204. Suivez-moi !"
    assert r["guide"] == {"cible": "b204", "accompagner": True, "source": "dialogue"}
    assert valider_message("demande_guide", r["guide"]) == []
    assert (r["salle"], r["nom_salle"]) == ("b204", "Salle B204")


@pytest.mark.parametrize("phrase, cible", [
    ("Je cherche la salle B204, s'il vous plaît.", "b204"),        # majuscules, ponctuation, politesse
    ("b204", "b204"),                                               # motif {salle} seul
    ("la B204 !", "b204"),                                          # article devant la salle
    ("le labo de physique", "b204"),                                # un alias
    ("Où est l'accueil ?", "accueil"),                              # apostrophe
    ("je vais au hall", "accueil"),                                 # « au » + alias
    ("Emmène-moi à l'infirmerie", "infirmerie"),                    # trait d'union, accents
    ("je cherche la bibliothèque", "cdi"),
    ("ou est la vie scolaire", "vie_scolaire"),                     # nom de deux mots
    ("bonjour, je cherche le CDI merci", "cdi"),                    # passe 2 : motif dans la phrase
    ("je vais jusqu'à la salle de conférence", "amphi"),            # « jusqu a la » retirés
])
def test_guider_vers_une_salle(bot, phrase, cible):
    r = bot.repondre(phrase)
    assert r["action"] == "guider" and r["guide"]["cible"] == cible, r


@pytest.mark.parametrize("phrase, regle, passe", [
    ("bonjour", "bonjour", "entiere"),
    ("Salut !", "bonjour", "entiere"),
    ("salut robot", "bonjour", "partielle"),
    ("merci", "merci", "entiere"),
    ("merci beaucoup pour tout", "merci", "entiere"),                # {*}
    ("arrête-toi", "stop", "entiere"),
    ("stop stop", "stop", "partielle"),
    ("sois discret", "discret", "entiere"),
])
def test_autres_regles(bot, phrase, regle, passe):
    r = bot.repondre(phrase)
    assert (r["regle"], r["passe"]) == (regle, passe), r
    assert r["guide"] is None


@pytest.mark.parametrize("phrase", [
    "quelle heure est-il",
    "je cherche mes clés",                      # {salle} sans salle : la règle ne correspond pas
    "je cherche la salle",
    "je ne cherche pas la b204",                # négation : pas de guidage en passe 2
    "la cantine est fermée",
])
def test_repli(bot, phrase):
    r = bot.repondre(phrase)
    assert r["regle"] is None and r["action"] == "repli" and r["guide"] is None
    assert r["reponse"] == E.exemple_equipe("dialogues")["repli"]


def test_phrase_vide(bot):
    assert bot.repondre("") is None and bot.repondre("  ?! ") is None


def test_negation_couverte_par_un_motif_entier(salles):
    d = E.exemple_equipe("dialogues")
    d["regles"].insert(0, {"id": "refus", "motifs": ["je ne cherche pas {salle}"], "action": "dire",
                           "reponse": "D'accord."})
    r = Chatbot(d, salles).repondre("je ne cherche pas la b204")
    assert r["regle"] == "refus" and r["guide"] is None


def test_l_ordre_des_regles_compte(salles):
    d = E.exemple_equipe("dialogues")
    d["regles"].insert(0, {"id": "fermee", "motifs": ["je cherche {salle}"], "action": "dire",
                           "reponse": "{nom_salle} est fermée aujourd'hui."})
    r = Chatbot(d, salles).repondre("je cherche la b204")
    assert r["regle"] == "fermee" and r["guide"] is None
    assert r["reponse"] == "{nom_salle} est fermée aujourd'hui."      # remplacé seulement pour guider


def test_passe_entiere_avant_la_passe_dans_la_phrase(salles):
    d = {"version": 1, "repli": "?", "regles": [
        {"id": "a", "motifs": ["bonjour"], "action": "dire", "reponse": "A"},
        {"id": "b", "motifs": ["bonjour robot"], "action": "dire", "reponse": "B"}]}
    bot = Chatbot(d, salles)
    assert bot.repondre("bonjour robot")["regle"] == "b"           # toute la phrase : b
    assert bot.repondre("bonjour robot gentil")["regle"] == "a"    # dans la phrase : la première, a


def test_motif_seulement_de_reperes_pas_dans_la_phrase(salles):
    d = {"version": 1, "repli": "?", "regles": [
        {"id": "tout", "motifs": ["{*}"], "action": "dire", "reponse": "tout"}]}
    assert Chatbot(d, salles).repondre("n'importe quoi")["regle"] == "tout"      # passe 1 : oui
    d = E.exemple_equipe("dialogues")
    assert Chatbot(d, salles).repondre("la b204 est loin")["regle"] is None      # {salle} pas cherché dedans


def test_la_plus_longue_salle(salles):
    s = [x.vers_dict() for x in salles] + [
        {"id": "hall", "nom": "Hall", "alias": [], "etage": "rdc", "pose": {"x": 1, "y": 1, "theta": 0}},
        {"id": "hall_nord", "nom": "Hall nord", "alias": [], "etage": "rdc", "pose": {"x": 2, "y": 1, "theta": 0}}]
    bot = Chatbot(E.exemple_equipe("dialogues"), s)
    assert bot.repondre("je cherche le hall nord")["guide"]["cible"] == "hall_nord"
    assert bot.repondre("je cherche le hall")["guide"]["cible"] == "accueil"     # alias « hall » de l'accueil, avant


def test_autre_etage(salles):
    s = [x.vers_dict() for x in salles] + [
        {"id": "labo_1", "nom": "Labo du premier", "alias": [], "etage": "etage1",
         "pose": {"x": 1, "y": 1, "theta": 0}}]
    r = Chatbot(E.exemple_equipe("dialogues"), s, etage="rdc").repondre("je cherche le labo du premier")
    assert r["action"] == "guider" and r["guide"] is None and r["raison"] == "autre_etage"
    assert r["reponse"] == MESSAGES["autre_etage"].replace("{nom_salle}", "Labo du premier")
    r = Chatbot(E.exemple_equipe("dialogues"), s).repondre("je cherche le labo du premier")
    assert r["guide"]["cible"] == "labo_1"          # sans étage donné : toutes les salles


def test_accompagner_faux_et_reponse_avec_id(salles):
    d = {"version": 1, "repli": "?", "regles": [
        {"id": "va", "motifs": ["va {salle}"], "action": "guider", "accompagner": False,
         "reponse": "Je vais à {salle} ({nom_salle})."}]}
    r = Chatbot(d, salles).repondre("va à la b204")
    assert r["guide"] == {"cible": "b204", "accompagner": False, "source": "dialogue"}
    assert r["reponse"] == "Je vais à b204 (Salle B204)."


def test_phrase_tres_longue(bot):
    r = bot.repondre("bla " * 400 + "je cherche la b204")
    assert r["regle"] is None          # coupée à 60 mots : la fin n'est pas lue
    assert bot.repondre("je cherche la b204 " + "x" * 2000)["guide"]["cible"] == "b204"


def test_salles_en_dicts_ou_objets(salles):
    a = Chatbot(E.exemple_equipe("dialogues"), salles).repondre("ou est le cdi")
    b = Chatbot(E.exemple_equipe("dialogues"), [s.vers_dict() for s in salles]).repondre("ou est le cdi")
    assert a == b


def test_sans_salle(bot):
    vide = Chatbot(E.exemple_equipe("dialogues"), [])
    assert vide.repondre("je cherche la b204")["regle"] is None
    assert vide.repondre("bonjour")["regle"] == "bonjour"


# ---------------------------------------------------------------- decider : ce que fait le nœud

def test_decider_guider(bot):
    d = decider(bot, bot.repondre("je cherche la b204"))
    assert d["guide"] == {"cible": "b204", "accompagner": True, "source": "dialogue"} and not d["stop"]
    assert d["dire"] == "Je vous emmène à Salle B204. Suivez-moi !" and d["raison"] is None


def test_decider_robot_pilote(bot):
    maitre = {"version": 1, "maitre": "pilotage", "par": "atelier", "depuis": "x", "message": "m"}
    d = decider(bot, bot.repondre("je cherche la b204"), maitre=maitre)
    assert d["guide"] is None and d["raison"] == "pilotage" and d["dire"] == CODES_EVENEMENT["pilotage"]
    d = decider(bot, bot.repondre("je cherche la b204"), maitre=maitre, phrases={"pilotage": "On me pilote."})
    assert d["dire"] == "On me pilote."
    assert decider(bot, bot.repondre("stop"), maitre=maitre)["stop"]          # l'arrêt passe toujours
    assert decider(bot, bot.repondre("je cherche la b204"), maitre=dict(maitre, maitre="guide"))["guide"]


@pytest.mark.parametrize("etat, mission, guide", [
    ("en_route", "visite", False), ("attente_visiteur", "visite", False), ("bloque", None, False),
    ("retour", "retour", True), ("detour", "retour", True), ("attente", None, True), ("arrive", "visite", True),
    ("echec", None, True)])
def test_decider_pendant_une_mission(bot, etat, mission, guide):
    e = {"etat": etat, "cible": "cdi", "mission": mission}
    assert en_visite(e) is not guide
    d = decider(bot, bot.repondre("je cherche la b204"), etat_guide=e)
    assert (d["guide"] is not None) is guide
    if not guide:
        assert d["raison"] == "visite_en_cours" and "CDI" in d["dire"]
        assert decider(bot, bot.repondre("je cherche la b204"), etat_guide=e, remplacer_visite=True)["guide"]


def test_decider_personnalite(bot):
    persos = E.exemple_equipe("personnalites")
    d = decider(bot, bot.repondre("mode discret"), personnalites=persos)
    assert d["personnalite"]["id"] == "discret" and d["dire"] == "D'accord, je me fais discret."
    d = decider(bot, bot.repondre("mode discret"), personnalites=None)
    assert d["personnalite"] is None and d["raison"] == "personnalite_inconnue"


def test_decider_rien(bot):
    assert decider(bot, None) == {"dire": None, "guide": None, "stop": False, "personnalite": None, "raison": None}
    d = decider(bot, bot.repondre("quelle heure est-il"))
    assert d["dire"] and d["guide"] is None and not d["stop"]


# ---------------------------------------------------------------- relais des événements du guide

def test_relais_textes_et_personnalite():
    relais = Relais()
    perso = E.exemple_equipe("personnalites")["personnalites"][0]
    ev = evenement("depart", salle="b204", nom="Salle B204", mission="visite")
    m = relais.message(ev, perso)
    assert m["texte"] == "Avec plaisir ! Suivez-moi jusqu'à Salle B204." and m["source"] == "guide"
    assert m["code"] == "depart" and m["personnalite"] == "accueillant" and m["voix"]["volume"] == 80
    assert valider_message("robot_dire", m) == []
    # sans phrase pour ce code : le texte du guide
    assert relais.texte(evenement("detour", salle="b204", nom="Salle B204")) == CODES_EVENEMENT["detour"]
    assert relais.texte(evenement("ralentir"), perso) == CODES_EVENEMENT["ralentir"]
    # sans personnalité
    assert relais.texte(ev) == "Suivez-moi, je vous emmène à Salle B204."


def test_relais_arrivee_propre_a_la_salle():
    relais = Relais()
    perso = E.exemple_equipe("personnalites")["personnalites"][0]
    propre = evenement("arrivee", salle="infirmerie", nom="Infirmerie", texte="Voici l'infirmerie. Frappez avant d'entrer.")
    assert relais.texte(propre, perso) == "Voici l'infirmerie. Frappez avant d'entrer."
    generique = evenement("arrivee", salle="x", nom="Salle X")
    assert relais.texte(generique, perso) == "Et voilà : Salle X. Bonne journée !"


def test_relais_depart_tu_apres_le_chatbot():
    h = Horloge()
    relais = Relais(taire_depart_s=10.0, horloge=h)
    relais.noter_guidage("b204")
    h.t += 2
    assert relais.message(evenement("depart", salle="b204", nom="Salle B204")) is None
    assert relais.message(evenement("depart", salle="b204", nom="Salle B204")) is not None    # une fois seulement
    relais.noter_guidage("b204")
    assert relais.message(evenement("seul", salle="b204", nom="Salle B204")) is not None     # « seul » se dit
    relais.noter_guidage("cdi")
    h.t += 11
    assert relais.message(evenement("depart", salle="cdi", nom="CDI")) is not None           # trop tard
    relais.noter_guidage("cdi")
    assert relais.message(evenement("depart", salle="b204", nom="Salle B204")) is not None   # autre salle


def test_relais_priorite_et_inconnus():
    relais = Relais()
    assert relais.message(evenement("arret"))["priorite"] == "haute"
    assert relais.message(evenement("perdu"))["priorite"] == "normale"
    assert relais.message({"code": "inconnu"}) is None
    assert relais.message({"code": "inconnu", "texte": "Bonjour."})["texte"] == "Bonjour."
    for code in CODES_EVENEMENT:
        assert valider_message("robot_dire", relais.message(evenement(code, salle="b204", nom="B204"))) == []


# ---------------------------------------------------------------- salutation d'un visiteur vu par la caméra

def _vus(*personnes):
    return message_visiteurs(1.0, [dict(id=i, x=x, y=0.0, **autres) for i, x, autres in personnes])


def test_salueur():
    h = Horloge()
    s = Salueur(distance_m=1.5, vu_s=1.0, delai_s=30.0, horloge=h)
    perso = E.exemple_equipe("personnalites")["personnalites"][0]
    repos = {"etat": "attente"}
    assert s.recevoir(_vus((1, 1.2, {})), repos, perso) is None          # pas encore 1 s
    h.t += 1.2
    m = s.recevoir(_vus((1, 1.2, {})), repos, perso)
    assert m["texte"] == perso["salutation"] and m["source"] == "personnalite"
    assert valider_message("robot_dire", m) == []
    h.t += 40
    assert s.recevoir(_vus((1, 1.2, {})), repos, perso) is None          # le même, jamais deux fois
    s.recevoir(_vus((2, 1.0, {})), repos, perso)
    h.t += 1.5
    assert s.recevoir(_vus((2, 1.0, {})), repos, perso) is not None      # un nouveau
    s.recevoir(_vus((3, 1.0, {})), repos, perso)
    h.t += 1.5
    assert s.recevoir(_vus((3, 1.0, {})), repos, perso) is None          # moins de 30 s après


@pytest.mark.parametrize("cas", ["loin", "dos", "en_route", "sans_salutation"])
def test_salueur_se_tait(cas):
    h = Horloge()
    s = Salueur(horloge=h)
    perso = dict(E.exemple_equipe("personnalites")["personnalites"][0])
    etat = {"etat": "en_route" if cas == "en_route" else "attente"}
    autres = {"regarde_robot": False} if cas == "dos" else {}
    x = 3.0 if cas == "loin" else 1.0
    if cas == "sans_salutation":
        perso.pop("salutation")
    for _ in range(3):
        assert s.recevoir(_vus((1, x, autres)), etat, perso) is None
        h.t += 1.0


def test_salueur_message_faux():
    s = Salueur()
    assert s.recevoir(None) is None and s.recevoir({"personnes": [{"id": "x"}]}) is None


# ---------------------------------------------------------------- géométrie de la caméra

CAMERA = {"camera": {"position": {"x": 0.1, "y": 0.0, "z": 1.0, "roulis": 0.0, "tangage": 0.0, "lacet": 0.0},
                     "champ_horizontal_deg": 90.0}, "detection": {"distance_max_m": 4.0}}


@pytest.mark.parametrize("x, y, vu", [(2, 0, True), (2, 1.8, True), (2, 2.2, False), (-1, 0, False), (4.5, 0, False),
                                      (0.1, 0, False)])
def test_dans_le_champ(x, y, vu):
    assert dans_le_champ(x, y, CAMERA) is vu


def test_lacet_de_la_camera():
    gauche = {"camera": dict(CAMERA["camera"], position=dict(CAMERA["camera"]["position"], lacet=math.pi / 2)),
              "detection": CAMERA["detection"]}
    assert dans_le_champ(0.1, 2.0, gauche) and not dans_le_champ(2.0, 0.0, gauche)
    assert dans_le_champ(2.0, 0.0, None)          # sans camera.yaml : 90° droit devant, 4 m


def test_vers_base_link():
    x, y = vers_base_link(3.0, 11.0, (2.0, 10.0, math.pi / 2))
    assert (round(x, 6), round(y, 6)) == (1.0, -1.0)


def test_visibles_depuis_les_pietons():
    pietons = [{"id": "devant", "x": 4.5, "y": 10.0, "vx": -1.0, "vy": 0.0},
               {"id": "derriere", "x": 0.5, "y": 10.0, "vx": 0.0, "vy": 0.0},
               {"id": "part", "x": 4.0, "y": 10.5, "vx": 1.0, "vy": 0.0}, {"faux": True}]
    vus = visibles_depuis_pietons(pietons, (2.5, 10.0, 0.0), CAMERA)
    assert [(v["pieton"], v["regarde_robot"]) for v in vus] == [("devant", True), ("part", False)]
    m = message_visiteurs(12.5, vus)
    assert valider_message("personnes", m) == [] and m["source"] == "camera"
    assert m["personnes"][0]["distance_m"] == 2.0 and m["personnes"][0]["angle_rad"] == 0.0


def test_message_visiteurs_borne():
    m = message_visiteurs(-1, [{"id": i, "x": 1.0, "y": 0.0, "confiance": 7} for i in range(150)])
    assert m["temps"] == 0.0 and len(m["personnes"]) == 100 and m["personnes"][0]["confiance"] == 1.0
    assert valider_message("personnes", m) == []
