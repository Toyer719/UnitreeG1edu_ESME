"""Les passants (vague 4, section 11.3 du plan) : piétons crédibles, mesure des contacts, banc.

Piétons crédibles (monde.yaml, champs facultatifs de la vague 4) : un corps qui gêne le robot dans
Gazebo, et une réaction simple quand le robot est très près (reaction : aucune, arret, ecart).
reglages_pieton(pieton) donne leurs valeurs, défauts compris.

Mesures, toutes « bord à bord » : distance entre les centres moins le rayon de contact du robot
(RAYON_ROBOT_CONTACT, le cercle qui contient la boîte de collision du robot proxy, 0,208 × 0,477 m)
et le rayon du corps du piéton (rayon_m, 0,25 m par défaut).
  - contact : la distance bord à bord passe sous SEUIL_CONTACT_M ; il finit quand elle repasse
    au-dessus de SEUIL_FIN_CONTACT_M (pas de contacts en rafale) ;
  - cause, au début du contact : « robot » si le robot avançait vers le piéton (vitesse du robot
    projetée sur la direction robot → piéton > VITESSE_APPROCHE_M_S), même si le piéton avançait
    aussi ; sinon « pieton » si le piéton avançait vers le robot ; sinon « aucun » (tous deux
    arrêtés, ou qui s'éloignent).
Les vitesses sont celles du repère map (vérité terrain : /odom en simulation, /g1_jumeau/odom en
répétition ; /pietons/etat pour les piétons).

Fichier de l'agent Passants (vague 4). Les fonctions et valeurs marquées « contrat » sont livrées et
testées par l'intégrateur (atelier/tests/test_contrats_vague4.py) : elles gardent leur nom, leurs
arguments et leur comportement.
"""
import math

# ---------------------------------------------------------------- valeurs du contrat

RAYON_ROBOT_CONTACT = 0.26      # m : cercle qui contient la boîte de collision du robot proxy (g1_proxy)
RAYON_PIETON = 0.25             # m : rayon_m par défaut d'un piéton
SEUIL_CONTACT_M = 0.05          # m bord à bord : en dessous, c'est un contact
SEUIL_FIN_CONTACT_M = 0.15      # m bord à bord : au-dessus, le contact est fini
VITESSE_APPROCHE_M_S = 0.05     # m/s vers l'autre : au-delà, on « avance vers lui »
CAUSES = ("robot", "pieton", "aucun")

REACTIONS = ("aucune", "arret", "ecart")
PILOTES = ("trajet", "externe")
ETATS_PIETON = ("marche", "pause", "arret", "ecart", "pilote", "fini")
DEFAUTS_PIETON = {"reaction": "ecart", "distance_reaction_m": 0.8, "corps": True, "rayon_m": RAYON_PIETON,
                  "pauses": [], "depart_s": 0.0, "repeter": True, "pilote": "trajet"}

SUJET_ETAT = "/pietons/etat"            # g1_sim → , 10 Hz, schéma pietons_etat
SUJET_CONSIGNE = "/pietons/consigne"    # → g1_sim, schéma pietons_consigne
FREQUENCE_ETAT_HZ = 10.0
DUREE_CONSIGNE_S = 0.5                  # une consigne de piéton vaut 0,5 s
VITESSE_PIETON_MAX = 1.5                # m/s, consigne d'un piéton piloté

# Colonnes ajoutées au CSV de g1-banc (après celles de la vague 1, dans cet ordre)
COLONNES_BANC_V4 = ("scene", "distance_min_bord_m", "contacts", "contacts_robot", "contacts_pieton",
                    "contacts_aucun", "temps_arret_pres_s", "attentes_passage", "duree_attente_passage_s",
                    "longueur_m", "longueur_directe_m")
DISTANCE_PRES_M = 1.5           # temps_arret_pres_s : robot arrêté (< 0,02 m/s) à moins de 1,5 m bord à bord

EXEMPLE_PIETONS_ETAT = {
    "version": 1, "temps_sim": 42.3,
    "pietons": [{"id": "pieton_nord", "x": 12.4, "y": 13.8, "theta": 3.1416, "vx": -1.0, "vy": 0.0,
                 "rayon_m": 0.25, "etat": "marche", "reaction": "ecart", "corps": True},
                {"id": "visiteur", "x": 1.4, "y": 10.0, "theta": 0.0, "vx": 0.3, "vy": 0.0,
                 "rayon_m": 0.25, "etat": "pilote", "reaction": "aucune", "corps": True}]}
EXEMPLE_CONSIGNE = {"id": "visiteur", "vx": 0.35, "vy": 0.0}


# ---------------------------------------------------------------- contrat (livré par l'intégrateur)

def reglages_pieton(pieton):
    """Contrat. Réglages d'un piéton (Pieton ou dict de monde.yaml), défauts compris (DEFAUTS_PIETON)."""
    lire = (lambda c: pieton.get(c)) if isinstance(pieton, dict) else (lambda c: getattr(pieton, c, None))
    return {c: (lire(c) if lire(c) is not None else (list(v) if isinstance(v, list) else v))
            for c, v in DEFAUTS_PIETON.items()}


def distance_bord(robot, pieton, rayon_pieton=RAYON_PIETON, rayon_robot=RAYON_ROBOT_CONTACT):
    """Contrat. Distance bord à bord (m) entre le robot et un piéton : |centres| − rayons.
    robot, pieton : (x, y, ...) ; négative quand les corps se chevauchent."""
    return math.dist(robot[:2], pieton[:2]) - rayon_robot - rayon_pieton


def _vers(depuis, vers):
    dx, dy = vers[0] - depuis[0], vers[1] - depuis[1]
    n = math.hypot(dx, dy)
    return (dx / n, dy / n) if n > 1e-9 else (0.0, 0.0)


def cause_contact(robot, v_robot, pieton, v_pieton, seuil=VITESSE_APPROCHE_M_S):
    """Contrat. Qui avançait vers l'autre au moment du contact : « robot », « pieton » ou « aucun ».
    robot, pieton : positions (x, y) ; v_robot, v_pieton : vitesses (vx, vy) dans le même repère.
    Le robot est en cause dès qu'il avançait vers le piéton, même si le piéton avançait aussi."""
    u = _vers(robot, pieton)
    if v_robot[0] * u[0] + v_robot[1] * u[1] > seuil:
        return "robot"
    if -(v_pieton[0] * u[0] + v_pieton[1] * u[1]) > seuil:
        return "pieton"
    return "aucun"


class SuiviContacts:
    """Contrat. Suit les contacts entre le robot et les piétons pendant un trajet.

    noter(t, robot, pietons) à chaque mesure (20 Hz au moins) :
      robot   : (x, y, vx, vy) dans map ;
      pietons : [(id, x, y, vx, vy, rayon_m)].
    contacts : [{pieton, debut, fin, cause, distance_min_m}] (fin None tant qu'il dure) ;
    distance_min_bord_m : plus petite distance bord à bord vue (None sans piéton) ;
    resume() : {contacts, contacts_robot, contacts_pieton, contacts_aucun, distance_min_bord_m}.
    """

    def __init__(self, rayon_robot=RAYON_ROBOT_CONTACT):
        self.rayon_robot = rayon_robot
        self.contacts = []
        self.distance_min_bord_m = None
        self._en_cours = {}          # id du piéton → contact en cours (dict de self.contacts)

    def noter(self, t, robot, pietons):
        for ident, x, y, vx, vy, rayon in pietons:
            d = distance_bord(robot, (x, y), rayon, self.rayon_robot)
            if self.distance_min_bord_m is None or d < self.distance_min_bord_m:
                self.distance_min_bord_m = d
            contact = self._en_cours.get(ident)
            if contact is None and d < SEUIL_CONTACT_M:
                contact = {"pieton": ident, "debut": t, "fin": None, "distance_min_m": d,
                           "cause": cause_contact(robot[:2], robot[2:4], (x, y), (vx, vy))}
                self.contacts.append(contact)
                self._en_cours[ident] = contact
            elif contact is not None:
                contact["distance_min_m"] = min(contact["distance_min_m"], d)
                if d > SEUIL_FIN_CONTACT_M:
                    contact["fin"] = t
                    del self._en_cours[ident]

    def resume(self):
        compte = {c: sum(1 for k in self.contacts if k["cause"] == c) for c in CAUSES}
        return {"contacts": len(self.contacts), "contacts_robot": compte["robot"],
                "contacts_pieton": compte["pieton"], "contacts_aucun": compte["aucun"],
                "distance_min_bord_m": (None if self.distance_min_bord_m is None
                                        else round(self.distance_min_bord_m, 3))}
