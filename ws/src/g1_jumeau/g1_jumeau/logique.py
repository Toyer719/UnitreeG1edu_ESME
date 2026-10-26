"""
Logique du faux G1, sans ROS (section 10.4 du plan) : le service « sport » et l'odométrie.

FauxSport : ce que fait le service de marche du G1 d'une requête unitree_api/Request.
  - 7105 (SetVelocity), parameter {"velocity": [vx, vy, wz], "duration": d} : la consigne est
    appliquée telle quelle jusqu'à t + d (temps mural), puis zéro. Pas de plafond ici : le vrai
    robot a les siens, plus hauts que ceux du pont. Réponse : code 0.
  - api inconnue : 3203 ; paramètres illisibles : 3204 (codes RPC du SDK d'Unitree).
  - pannes (/g1_jumeau/panne) : « muet » ne répond plus et n'applique plus rien, comme un câble
    coupé (la consigne en cours expire normalement) ; « refus » répond 7301 sans bouger
    (consigne remise à zéro) ; « aucune » : normal.
  Le texte JSON est lu par json.loads, sans dépendre du pont : clés dans n'importe quel ordre
  (le client C++ les trie), nombres entiers ou flottants.

OdometrieDerivee : /state_estimator/odom_pelvis tirée de la vérité terrain de Gazebo, avec une
dérive : déplacements comptés 2 % trop longs, et 0,01 rad de lacet ajouté par mètre parcouru
(DERIVE_ECHELLE, DERIVE_LACET_PAR_M d'atelier.lieu). Origine : la pose du robot au premier
message (au lancement), comme l'odométrie d'un robot qui démarre.
"""
import json
import math
import time

API_SET_VELOCITY = 7105
CODE_OK = 0
CODE_API_INCONNUE = 3203        # RPC_ERR_SERVER_API_NOT_IMPL du SDK
CODE_PARAMETRES = 3204          # RPC_ERR_SERVER_API_PARAMETER
CODE_REFUS = 7301               # UT_ROBOT_LOCO_ERR_LOCOSTATE_NOT_AVAILABLE (pas en mode marche)
PANNES = ('aucune', 'muet', 'refus')

DERIVE_ECHELLE = 0.02
DERIVE_LACET_PAR_M = 0.01


def angle_normal(a):
    """Angle ramené dans [-π, π[."""
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def lire_set_velocity(parametre):
    """(vx, vy, wz, duree) d'un parameter de 7105 ; ValueError s'il est illisible."""
    try:
        donnees = json.loads(parametre)
    except (TypeError, ValueError) as erreur:
        raise ValueError(f'JSON illisible : {erreur}') from None
    if not isinstance(donnees, dict):
        raise ValueError('il faut un objet JSON')
    vitesse, duree = donnees.get('velocity'), donnees.get('duration')
    if not isinstance(vitesse, list) or len(vitesse) != 3:
        raise ValueError('velocity doit être une liste de 3 nombres')
    valeurs = []
    for v in list(vitesse) + [duree]:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f'nombre attendu, pas {v!r}')
        valeurs.append(float(v))
    if valeurs[3] < 0:
        raise ValueError('duration doit être positive')
    return tuple(valeurs)


class FauxSport:
    """Le faux service sport : traite les requêtes, garde la consigne et son échéance."""

    def __init__(self, horloge=time.monotonic):
        self.horloge = horloge
        self.panne = 'aucune'
        self.consigne_en_cours = (0.0, 0.0, 0.0)
        self.fin = None                  # échéance de la consigne, temps mural
        self.requetes = 0
        self.reponses = 0
        self.appliquees = 0
        self.dernier_code = None

    def changer_panne(self, panne):
        """aucune, muet ou refus ; ValueError sinon. refus remet la consigne à zéro."""
        panne = str(panne).strip()
        if panne not in PANNES:
            raise ValueError(f'panne inconnue « {panne} » : {", ".join(PANNES)}')
        self.panne = panne
        if panne == 'refus':
            self.consigne_en_cours, self.fin = (0.0, 0.0, 0.0), None

    def traiter(self, api_id, parametre):
        """Code de la réponse à une requête, ou None si le faux G1 ne répond pas (muet)."""
        self.requetes += 1
        if self.panne == 'muet':
            return None
        if self.panne == 'refus':
            code = CODE_REFUS
        elif api_id != API_SET_VELOCITY:
            code = CODE_API_INCONNUE
        else:
            try:
                vx, vy, wz, duree = lire_set_velocity(parametre)
            except ValueError:
                code = CODE_PARAMETRES
            else:
                self.consigne_en_cours = (vx, vy, wz)
                self.fin = self.horloge() + duree
                self.appliquees += 1
                code = CODE_OK
        self.reponses += 1
        self.dernier_code = code
        return code

    def reste(self, t=None):
        """Secondes avant l'échéance de la consigne (0 si elle est finie)."""
        t = self.horloge() if t is None else t
        return 0.0 if self.fin is None else max(0.0, self.fin - t)

    def consigne(self, t=None):
        """Vitesses à appliquer maintenant : la consigne avant son échéance, sinon zéro."""
        t = self.horloge() if t is None else t
        if self.panne == 'refus' or self.fin is None or t >= self.fin:
            return (0.0, 0.0, 0.0)
        return self.consigne_en_cours


class OdometrieDerivee:
    """Odométrie locale du faux G1 : la vérité, avec une dérive d'échelle et de lacet."""

    def __init__(self, echelle=DERIVE_ECHELLE, lacet_par_m=DERIVE_LACET_PAR_M):
        self.echelle = float(echelle)
        self.lacet_par_m = float(lacet_par_m)
        self.precedente = None           # dernière vérité (x, y, theta) dans le monde
        self.pose = (0.0, 0.0, 0.0)      # pose dans le repère odom (origine : premier message)
        self.parcouru = 0.0              # mètres parcourus (vérité)

    def mettre_a_jour(self, x, y, theta):
        """Nouvelle vérité (repère du monde) → pose (x, y, theta) dans le repère odom."""
        if self.precedente is None:
            self.precedente = (x, y, theta)
            return self.pose
        px, py, pth = self.precedente
        # Déplacement dans le repère du robot à l'instant précédent
        c, s = math.cos(pth), math.sin(pth)
        dx, dy = x - px, y - py
        avant, cote = c * dx + s * dy, -s * dx + c * dy
        dtheta = angle_normal(theta - pth)
        distance = math.hypot(avant, cote)
        self.parcouru += distance
        # Dérive : distance 2 % trop longue, lacet en plus proportionnel à la distance
        avant *= 1.0 + self.echelle
        cote *= 1.0 + self.echelle
        dtheta += self.lacet_par_m * distance
        ox, oy, oth = self.pose
        c, s = math.cos(oth), math.sin(oth)
        self.pose = (ox + c * avant - s * cote, oy + s * avant + c * cote,
                     angle_normal(oth + dtheta))
        self.precedente = (x, y, theta)
        return self.pose
