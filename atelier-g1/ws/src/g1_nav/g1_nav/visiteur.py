"""
Personnes vues par le guide (vague 4, section 11.4 du plan) : le visiteur suivi et les passants.

Logique sans ROS, utilisée par guide.py. Les personnes viennent du détecteur au LiDAR
(/personnes/lidar, schéma personnes : positions dans base_link, x vers l'avant, y à gauche).

  lire_personnes(donnees)        message JSON (dict) → liste de Personne (les entrées fausses
                                 sont ignorées) ;
  SuiviVisiteur                  choisit le visiteur au départ (la personne la plus proche du
                                 robot, à moins de 2,5 m), puis le retrouve d'un message à
                                 l'autre : même numéro de suivi, sinon la personne la plus proche
                                 de sa dernière position sur la carte ; dit s'il est vu, à quelle
                                 distance, et depuis quand il ne l'est plus ;
  personne_devant(personnes, …)  la personne la plus proche dans le cône avant du robot, ou
                                 autour d'une autre direction (cap : celle du couloir), ou None :
                                 un passant qui bouche le passage.
"""
import math

# Le visiteur est « vu » s'il l'a été il y a moins de cela (schéma etat_guide, champ visiteur)
DELAI_VU_S = 2.0
# Pour le retrouver sous un autre numéro : à moins de PORTE_M de sa dernière position, plus ce
# qu'il a pu parcourir depuis (VITESSE_PERSONNE_MAX), PORTE_MAX_M au plus
PORTE_M = 0.8
PORTE_MAX_M = 2.5
VITESSE_PERSONNE_MAX = 1.5
# Cône avant d'un passant qui bouche le passage : ±60° autour de l'avant du robot
DEMI_ANGLE_DEVANT_RAD = math.pi / 3


class Personne:
    """Une personne vue : numéro de suivi, position dans base_link et, si connue, sur la carte."""

    __slots__ = ('id', 'x', 'y', 'distance', 'angle', 'x_map', 'y_map', 'derriere', 'confiance',
                 'vx', 'vy')

    def __init__(self, ident, x, y, distance=None, angle=None, x_map=None, y_map=None,
                 derriere=None, confiance=1.0, vx=None, vy=None):
        self.id = int(ident)
        self.x, self.y = float(x), float(y)
        self.distance = math.hypot(self.x, self.y) if distance is None else float(distance)
        self.angle = math.atan2(self.y, self.x) if angle is None else float(angle)
        self.x_map = None if x_map is None else float(x_map)
        self.y_map = None if y_map is None else float(y_map)
        self.derriere = abs(self.angle) > math.pi / 2 if derriere is None else bool(derriere)
        self.confiance = float(confiance)
        self.vx = None if vx is None else float(vx)      # vitesse (m/s), axes de base_link
        self.vy = None if vy is None else float(vy)

    def s_eloigne(self, seuil=0.3):
        """Vrai si la personne s'éloigne du robot à plus de seuil m/s (vitesse connue)."""
        if self.vx is None or self.vy is None or self.distance < 1e-6:
            return False
        return (self.x * self.vx + self.y * self.vy) / self.distance > seuil

    def sur_la_carte(self, robot=None):
        """(x, y) dans map : celle du message, sinon depuis la pose du robot, sinon None."""
        if self.x_map is not None and self.y_map is not None:
            return self.x_map, self.y_map
        if robot is None:
            return None
        rx, ry, rtheta = robot[:3]
        c, s = math.cos(rtheta), math.sin(rtheta)
        return rx + c * self.x - s * self.y, ry + s * self.x + c * self.y

    def __repr__(self):
        return f'Personne({self.id}, {self.x:.2f}, {self.y:.2f}, {self.distance:.2f} m)'


def _nombre(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def lire_personnes(donnees):
    """
    Message /personnes/lidar (dict, schéma personnes) → liste de Personne.

    Une entrée sans id, x ou y numériques est ignorée (le reste du message sert quand même).
    """
    if not isinstance(donnees, dict) or not isinstance(donnees.get('personnes'), list):
        return []
    personnes = []
    for p in donnees['personnes']:
        if not isinstance(p, dict) or not all(_nombre(p.get(c)) for c in ('id', 'x', 'y')):
            continue
        facultatif = {c: p[c] for c in ('x_map', 'y_map', 'vx', 'vy') if _nombre(p.get(c))}
        personnes.append(Personne(
            p['id'], p['x'], p['y'],
            distance=p['distance_m'] if _nombre(p.get('distance_m')) else None,
            angle=p['angle_rad'] if _nombre(p.get('angle_rad')) else None,
            derriere=p.get('derriere') if isinstance(p.get('derriere'), bool) else None,
            confiance=p['confiance'] if _nombre(p.get('confiance')) else 1.0, **facultatif))
    return personnes


def personne_devant(personnes, distance_max=1.5, demi_angle=DEMI_ANGLE_DEVANT_RAD, sauf=None,
                    cap=0.0):
    """
    Renvoie la personne la plus proche dans le cône avant du robot, ou None.

    Cône : écart à cap ≤ demi_angle et distance ≤ distance_max. cap : direction de l'axe du cône
    dans base_link (rad ; 0 : l'avant du robot ; le guide donne aussi la direction du couloir).
    sauf : numéro de suivi à ignorer (le visiteur).
    """
    def ecart(angle):
        return abs(math.atan2(math.sin(angle - cap), math.cos(angle - cap)))
    candidats = [p for p in personnes or ()
                 if p.id != sauf and p.distance <= distance_max and ecart(p.angle) <= demi_angle]
    return min(candidats, key=lambda p: p.distance) if candidats else None


class SuiviVisiteur:
    """
    Le visiteur suivi pendant une visite accompagnée.

    choisir(...) au départ ; observer(...) à chaque pas du guide ; reprendre(...) pendant que le
    robot l'attend (il peut revenir sous un autre numéro de suivi). instant : horloge du guide.
    """

    def __init__(self):
        self.id = None             # numéro de suivi actuel
        self.position = None       # dernière position connue (map si possible, sinon base_link)
        self.vu_a = None           # instant où il a été vu pour la dernière fois
        self.distance = None       # distance au robot quand il a été vu pour la dernière fois

    @property
    def choisi(self):
        return self.id is not None

    def oublier(self):
        self.__init__()

    def _adopter(self, personne, instant, robot):
        self.id = personne.id
        self.position = personne.sur_la_carte(robot) or (personne.x, personne.y)
        self.vu_a = instant
        self.distance = personne.distance

    def choisir(self, personnes, instant, robot=None, distance_max=2.5):
        """
        Choisit le visiteur : la personne vue la plus proche du robot, à distance_max au plus.

        Renvoie True si quelqu'un a été choisi.
        """
        candidats = [p for p in personnes or () if p.distance <= distance_max]
        if not candidats:
            return False
        self._adopter(min(candidats, key=lambda p: p.distance), instant, robot)
        return True

    def observer(self, personnes, instant, robot=None):
        """
        Met à jour le visiteur avec les personnes vues maintenant (None : pas de message frais).

        Renvoie {vu, distance_m, age_s} (champ visiteur de /guide/etat).
        """
        if self.id is not None and personnes:
            meme = next((p for p in personnes if p.id == self.id), None)
            if meme is None:
                meme = self._le_plus_proche(personnes, instant, robot)
            if meme is not None:
                self._adopter(meme, instant, robot)
        return self.resume(instant)

    def reprendre(self, personnes, instant, robot=None, distance_max=2.0):
        """
        Pendant l'attente : dit si le visiteur est revenu, vu à distance_max au plus.

        Sous un autre numéro, on prend la personne la plus proche du robot. Renvoie True s'il est
        là.
        """
        self.observer(personnes, instant, robot)
        resume = self.resume(instant)
        if resume['vu'] and resume['age_s'] < 0.5 and resume['distance_m'] <= distance_max:
            return True
        proches = [p for p in personnes or () if p.distance <= distance_max]
        if not proches:
            return False
        self._adopter(min(proches, key=lambda p: p.distance), instant, robot)
        return True

    def resume(self, instant):
        """{vu, distance_m, age_s} : vu s'il a été vu il y a moins de DELAI_VU_S."""
        if self.vu_a is None:
            return {'vu': False, 'distance_m': None, 'age_s': None}
        age = max(0.0, instant - self.vu_a)
        return {'vu': age < DELAI_VU_S, 'distance_m': round(self.distance, 2),
                'age_s': round(age, 2)}

    def _le_plus_proche(self, personnes, instant, robot):
        """Le visiteur sous un autre numéro : la personne la plus proche de sa position."""
        if self.position is None:
            return None
        age = max(0.0, instant - (self.vu_a or instant))
        porte = min(PORTE_MAX_M, PORTE_M + VITESSE_PERSONNE_MAX * age)
        meilleur, distance_meilleur = None, porte
        for p in personnes:
            ou = p.sur_la_carte(robot) or (p.x, p.y)
            d = math.dist(ou, self.position)
            if d <= distance_meilleur:
                meilleur, distance_meilleur = p, d
        return meilleur
