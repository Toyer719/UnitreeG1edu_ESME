"""
Détecteur de personnes au LiDAR (nœud detecteur_personnes, section 11.4 du plan).

Entrée /points (sensor_msgs/PointCloud2, repère lidar ; base_link par TF) ; sortie /personnes/lidar
(std_msgs/String JSON, schéma personnes, source lidar, 10 Hz au plus) : les personnes vues tout
autour du robot (le MID-360 voit aussi derrière : le visiteur), avec un numéro de suivi qui reste
le même d'un message à l'autre, leur vitesse, et derriere pour |angle| > 90°.

Méthode (DetecteurPersonnes, sans ROS, testée avec des nuages fabriqués) :
  1. tranche du tronc : points entre 0,8 et 1,8 m au-dessus du sol (base_link), à portee_m au plus,
     hors du corps du robot (rayon_robot_m) ;
  2. sans les murs ni les meubles : si la carte du lieu et la pose du robot sur la carte sont
     connues, les points qui tombent sur un pixel occupé de la carte (agrandi de marge_carte_m)
     sont retirés. Une personne n'est jamais sur la carte 2D (section 9.4) ;
  3. groupes : cases de cellule_m, voisines par les côtés et les coins ;
  4. une personne : un groupe de 0,25 à 0,8 m de large (étendue + l'écart entre deux rayons du
     LiDAR à cette distance), d'au moins hauteur_min_m de haut, d'au moins points_min points, qui
     fait face au capteur : un bout de mur vu de biais (son grand axe à moins de angle_biais_deg du
     rayon) est écarté ;
  5. suivi dans le repère odom (ou base_link sans lui) : appariement au plus proche (porte_m),
     vitesse lissée, piste oubliée après oubli_s sans être vue.

  ros2 run g1_nav detecteur_personnes --ros-args -p lieu:=demo -p etage:=rdc -p use_sim_time:=true

Limites connues (à vérifier sur le robot, section 11.11) : un poteau ou un portemanteau qui n'est
pas sur la carte ressemble à une personne ; deux personnes collées ne font qu'un groupe ; sans pose
sur la carte, les bouts de murs vus par une porte peuvent passer pour des personnes.
"""
import json
import math
import sys
import time

import numpy as np

# Réglages par défaut (paramètres ROS du nœud du même nom)
REGLAGES_DETECTEUR = {
    'z_min_m': 0.8,              # tranche du tronc, au-dessus du sol (base_link)
    'z_max_m': 1.8,
    'portee_m': 8.0,             # au-delà, ignoré
    'rayon_robot_m': 0.35,       # le corps du robot (et ce qu'il porte) n'est pas une personne
    'largeur_min_m': 0.25,       # largeur d'une personne vue au LiDAR
    'largeur_max_m': 0.8,
    'hauteur_min_m': 0.3,        # étendue verticale minimale des points d'un groupe
    'points_min': 4,
    'cellule_m': 0.15,           # cases du regroupement (voisines : côtés et coins)
    'resolution_lidar_rad': math.radians(1.0),   # écart entre deux rayons voisins
    'angle_biais_deg': 40.0,     # grand axe du groupe à moins de cela du rayon : un mur de biais
    'marge_carte_m': 0.15,       # autour des pixels occupés de la carte
    'porte_m': 0.8,              # appariement d'un message à l'autre
    'oubli_s': 1.0,              # piste oubliée après ce temps sans être vue
    'frequence_max_hz': 10.0,
}


def masque_carte(image, resolution, marge_m):
    """Pixels occupés (valeur < 128) de la carte, agrandis de marge_m : tableau booléen."""
    occupe = np.asarray(image) < 128
    n = int(math.ceil(marge_m / resolution - 1e-9))
    agrandi = occupe.copy()
    for _ in range(max(0, n)):
        voisin = agrandi.copy()
        voisin[1:, :] |= agrandi[:-1, :]
        voisin[:-1, :] |= agrandi[1:, :]
        voisin[:, 1:] |= agrandi[:, :-1]
        voisin[:, :-1] |= agrandi[:, 1:]
        agrandi = voisin
    return agrandi


class CarteStatique:
    """Murs et meubles de la carte du lieu : pour retirer leurs points avant le regroupement."""

    def __init__(self, info, image, marge_m=REGLAGES_DETECTEUR['marge_carte_m']):
        self.info = info
        self.masque = masque_carte(image, info.resolution, marge_m)

    @classmethod
    def depuis_lieu(cls, lieu, etage, marge_m=REGLAGES_DETECTEUR['marge_carte_m']):
        """Carte <lieu>/cartes/<etage>.yaml, ou None si elle manque."""
        from atelier.lieu import chemin_carte, charger_carte
        chemin = chemin_carte(lieu, etage)
        if not chemin.is_file():
            return None
        info, image = charger_carte(chemin)
        return cls(info, image, marge_m)

    def occupes(self, xy, dehors=False):
        """
        Dit, pour chaque point (x, y) de map, s'il tombe sur un pixel occupé (agrandi) de la carte.

        dehors : ce que vaut un point hors de la carte.
        """
        from atelier.lieu.conversions import monde_vers_pixel
        xy = np.asarray(xy, dtype=float).reshape(-1, 2)
        if len(xy) == 0:
            return np.zeros(0, dtype=bool)
        colonnes, lignes = monde_vers_pixel(xy[:, 0], xy[:, 1], self.info)
        colonnes, lignes = np.atleast_1d(colonnes), np.atleast_1d(lignes)
        h, w = self.masque.shape
        dedans = (colonnes >= 0) & (colonnes < w) & (lignes >= 0) & (lignes < h)
        resultat = np.full(len(xy), bool(dehors))
        resultat[dedans] = self.masque[lignes[dedans], colonnes[dedans]]
        return resultat


def regrouper(xy, cellule):
    """
    Regroupe les points voisins (cases de cellule m, voisines par les côtés et les coins).

    Renvoie une liste de tableaux d'indices.
    """
    if len(xy) == 0:
        return []
    cases = np.floor(xy / cellule).astype(np.int64)
    par_case = {}
    for i, (cx, cy) in enumerate(map(tuple, cases)):
        par_case.setdefault((cx, cy), []).append(i)
    vues, groupes = set(), []
    for depart in par_case:
        if depart in vues:
            continue
        pile, indices = [depart], []
        vues.add(depart)
        while pile:
            cx, cy = pile.pop()
            indices.extend(par_case[(cx, cy)])
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    voisin = (cx + dx, cy + dy)
                    if voisin in par_case and voisin not in vues:
                        vues.add(voisin)
                        pile.append(voisin)
        groupes.append(np.array(indices))
    return groupes


def etendue(xy, axe=False):
    """
    Longueur et largeur d'un groupe de points (axes principaux), en mètres.

    axe : renvoie aussi la direction (vecteur unitaire) de la longueur.
    """
    if len(xy) < 2:
        return (0.0, 0.0, np.array([1.0, 0.0])) if axe else (0.0, 0.0)
    centre = xy - xy.mean(axis=0)
    _, vecteurs = np.linalg.eigh(np.cov(centre.T) + 1e-12 * np.eye(2))
    projections = centre @ vecteurs
    tailles = projections.max(axis=0) - projections.min(axis=0)
    grand = int(np.argmax(tailles))
    if axe:
        return float(tailles[grand]), float(tailles[1 - grand]), vecteurs[:, grand]
    return float(tailles[grand]), float(tailles[1 - grand])


class Piste:
    """Une personne suivie : position (repère fixe), vitesse lissée, dernière vue, vues."""

    __slots__ = ('id', 'x', 'y', 'vx', 'vy', 't', 'vues')

    def __init__(self, ident, x, y, t):
        self.id, self.x, self.y, self.t = ident, x, y, t
        self.vx = self.vy = 0.0
        self.vues = 1

    def prevoir(self, t):
        dt = max(0.0, t - self.t)
        return self.x + self.vx * dt, self.y + self.vy * dt

    def mettre_a_jour(self, x, y, t):
        dt = t - self.t
        if dt > 1e-3:
            vx, vy = (x - self.x) / dt, (y - self.y) / dt
            n = math.hypot(vx, vy)
            if n > 3.0:                          # saut d'appariement : vitesse bornée
                vx, vy = vx * 3.0 / n, vy * 3.0 / n
            self.vx = 0.6 * self.vx + 0.4 * vx
            self.vy = 0.6 * self.vy + 0.4 * vy
        self.x, self.y, self.t = x, y, t
        self.vues += 1


class DetecteurPersonnes:
    """Détecteur et suivi des personnes dans un nuage de points (sans ROS)."""

    def __init__(self, carte=None, **reglages):
        self.r = dict(REGLAGES_DETECTEUR, **{k: v for k, v in reglages.items() if v is not None})
        self.carte = carte
        self.pistes = []
        self._prochain = 1

    def candidats(self, points, robot_carte=None):
        """
        Renvoie les groupes de points qui ressemblent à une personne, dans base_link.

        points : (N, 3) dans base_link (z au-dessus du sol) ; robot_carte : pose (x, y, theta) du
        robot dans map, pour retirer les points de la carte statique. Renvoie [(x, y, rayon)].
        """
        r = self.r
        p = np.asarray(points, dtype=float).reshape(-1, 3)
        distance = np.hypot(p[:, 0], p[:, 1])
        garde = ((p[:, 2] >= r['z_min_m']) & (p[:, 2] <= r['z_max_m'])
                 & (distance <= r['portee_m']) & (distance >= r['rayon_robot_m']))
        p = p[garde]
        if len(p) and self.carte is not None and robot_carte is not None:
            p = p[~self.carte.occupes(vers_carte(p[:, :2], robot_carte))]
        resultat = []
        for indices in regrouper(p[:, :2], r['cellule_m']):
            if len(indices) < r['points_min']:
                continue
            groupe = p[indices]
            if groupe[:, 2].max() - groupe[:, 2].min() < r['hauteur_min_m']:
                continue
            centre = groupe[:, :2].mean(axis=0)
            distance_centre = float(np.hypot(*centre))
            longueur, epaisseur, axe = etendue(groupe[:, :2], axe=True)
            largeur = longueur + distance_centre * r['resolution_lidar_rad']
            if not r['largeur_min_m'] <= largeur <= r['largeur_max_m']:
                continue
            # Un bout de mur vu de biais s'allonge le long du rayon ; une personne lui fait face
            if longueur > 2.0 * epaisseur and distance_centre > 1e-6:
                cos_biais = abs(float(axe @ (centre / distance_centre)))
                if cos_biais > math.cos(math.radians(r['angle_biais_deg'])):
                    continue
            # Les points sont sur la face vue : le centre du corps est un peu plus loin (en
            # moyenne 2r/π derrière les points d'un demi-cercle de rayon r)
            rayon = largeur / 2.0
            recul = (2.0 / math.pi) * min(rayon, 0.3)
            centre = centre + centre / max(distance_centre, 1e-6) * recul
            resultat.append((float(centre[0]), float(centre[1]), rayon))
        return resultat

    def suivre(self, candidats, t, robot_fixe=None, robot_carte=None):
        """
        Apparie les candidats aux pistes ; renvoie les personnes vues (schéma personnes).

        candidats : [(x, y, rayon)] dans base_link ; t : temps (s) ; robot_fixe : pose du robot
        dans le repère du suivi (odom), None : suivi dans base_link ; robot_carte : pose dans map.
        """
        r = self.r
        fixes = [vers_carte(np.array([[x, y]]), robot_fixe)[0] if robot_fixe is not None
                 else np.array([x, y]) for x, y, _ in candidats]
        self.pistes = [q for q in self.pistes if t - q.t <= r['oubli_s']]
        paires = sorted((math.dist(f, q.prevoir(t)), i, j) for i, f in enumerate(fixes)
                        for j, q in enumerate(self.pistes))
        prises_c, prises_p, attribution = set(), set(), {}
        for d, i, j in paires:
            if d > r['porte_m']:
                break
            if i in prises_c or j in prises_p:
                continue
            prises_c.add(i)
            prises_p.add(j)
            attribution[i] = self.pistes[j]
        personnes = []
        for i, (x, y, rayon) in enumerate(candidats):
            piste = attribution.get(i)
            if piste is None:
                piste = Piste(self._prochain, float(fixes[i][0]), float(fixes[i][1]), t)
                self._prochain += 1
                self.pistes.append(piste)
            else:
                piste.mettre_a_jour(float(fixes[i][0]), float(fixes[i][1]), t)
            vx, vy = piste.vx, piste.vy
            if robot_fixe is not None:            # vitesse exprimée dans les axes de base_link
                c, s = math.cos(robot_fixe[2]), math.sin(robot_fixe[2])
                vx, vy = c * piste.vx + s * piste.vy, -s * piste.vx + c * piste.vy
            angle = math.atan2(y, x)
            personne = {'id': piste.id, 'x': round(x, 3), 'y': round(y, 3),
                        'distance_m': round(math.hypot(x, y), 3), 'angle_rad': round(angle, 4),
                        'confiance': round(min(1.0, 0.3 + 0.1 * piste.vues), 2),
                        'vx': round(vx, 3), 'vy': round(vy, 3), 'rayon_m': round(rayon, 3),
                        'derriere': abs(angle) > math.pi / 2}
            if robot_carte is not None:
                xm, ym = vers_carte(np.array([[x, y]]), robot_carte)[0]
                personne.update(x_map=round(float(xm), 3), y_map=round(float(ym), 3))
            personnes.append(personne)
        return personnes

    def detecter(self, points, t, robot_fixe=None, robot_carte=None):
        """Nuage (N, 3) dans base_link → liste des personnes vues (schéma personnes)."""
        return self.suivre(self.candidats(points, robot_carte), t, robot_fixe, robot_carte)


def vers_carte(xy, pose):
    """Points (N, 2) de base_link → repère de la pose (x, y, theta) du robot."""
    x, y, theta = pose
    c, s = math.cos(theta), math.sin(theta)
    xy = np.asarray(xy, dtype=float).reshape(-1, 2)
    return np.column_stack([x + c * xy[:, 0] - s * xy[:, 1], y + s * xy[:, 0] + c * xy[:, 1]])


def message_personnes(personnes, temps):
    """Message /personnes/lidar (dict, schéma personnes)."""
    return {'version': 1, 'source': 'lidar', 'temps': round(max(0.0, float(temps)), 3),
            'personnes': list(personnes)[:100]}


# ---------------------------------------------------------------- nœud ROS 2

def main(args=None):
    """Point d'entrée de ros2 run g1_nav detecteur_personnes."""
    import rclpy
    from rclpy.executors import ExternalShutdownException
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import PointCloud2
    from std_msgs.msg import String
    import tf2_ros

    from g1_nav.nuages import appliquer, lire_xyz, matrice_quaternion

    class NoeudDetecteur(Node):
        def __init__(self):
            super().__init__('detecteur_personnes')
            from atelier.lieu.comportement import SUJET_PERSONNES
            lieu = self.declare_parameter('lieu', '').value
            etage = self.declare_parameter('etage', '').value
            self.sujet_nuage = self.declare_parameter('nuage', '/points').value
            self.repere_robot = self.declare_parameter('repere_robot', 'base_link').value
            self.repere_fixe = self.declare_parameter('repere_fixe', 'odom').value
            self.repere_carte = self.declare_parameter('repere_carte', 'map').value
            from rcl_interfaces.msg import ParameterDescriptor
            libre = ParameterDescriptor(dynamic_typing=True)     # 8 ou 8.0 : les deux vont
            reglages = {nom: type(defaut)(self.declare_parameter(nom, defaut, libre).value)
                        for nom, defaut in REGLAGES_DETECTEUR.items()}
            carte = None
            if lieu and etage:
                try:
                    carte = CarteStatique.depuis_lieu(lieu, etage, reglages['marge_carte_m'])
                except Exception as e:     # noqa: BLE001 : carte illisible, on s'en passe
                    self.get_logger().warn(f'carte du lieu illisible ({e}) : sans elle, les murs '
                                           'vus par les portes peuvent passer pour des personnes')
            self.detecteur = DetecteurPersonnes(carte, **reglages)
            self.periode = 1.0 / max(0.1, float(reglages['frequence_max_hz']))
            self.dernier_envoi = 0.0
            self.tampon = tf2_ros.Buffer()
            self.ecoute = tf2_ros.TransformListener(self.tampon, self)
            self.pub = self.create_publisher(String, SUJET_PERSONNES, 10)
            self.create_subscription(PointCloud2, self.sujet_nuage, self.sur_nuage,
                                     qos_profile_sensor_data)
            self.erreurs = 0
            self.get_logger().info(
                f'détecteur de personnes prêt : {self.sujet_nuage} → {SUJET_PERSONNES}, carte '
                f'{"du lieu" if carte is not None else "absente"}')

        def _matrice(self, cible, source):
            from rclpy.time import Time
            t = self.tampon.lookup_transform(cible, source, Time())
            tr, q = t.transform.translation, t.transform.rotation
            return matrice_quaternion((tr.x, tr.y, tr.z), (q.x, q.y, q.z, q.w))

        def _pose(self, repere):
            try:
                m = self._matrice(repere, self.repere_robot)
            except Exception:      # noqa: BLE001 : repère pas (encore) publié
                return None
            return (float(m[0, 3]), float(m[1, 3]), math.atan2(m[1, 0], m[0, 0]))

        def sur_nuage(self, msg):
            maintenant = time.monotonic()
            if maintenant - self.dernier_envoi < self.periode * 0.8:
                return
            try:
                points = lire_xyz(msg)
                repere = msg.header.frame_id or 'lidar'
                if repere != self.repere_robot:
                    points = appliquer(self._matrice(self.repere_robot, repere), points)
            except Exception as e:     # noqa: BLE001 : TF pas encore là, nuage illisible
                self.erreurs += 1
                if self.erreurs in (1, 50) or self.erreurs % 500 == 0:
                    self.get_logger().warn(f'nuage ignoré ({e})')
                return
            t = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
            personnes = self.detecteur.detecter(points, t, self._pose(self.repere_fixe),
                                                self._pose(self.repere_carte))
            self.dernier_envoi = maintenant
            self.pub.publish(String(data=json.dumps(message_personnes(personnes, t),
                                                    ensure_ascii=False)))

    rclpy.init(args=args)
    try:
        noeud = NoeudDetecteur()
    except Exception as e:     # noqa: BLE001 : message clair, sans trace
        print(f'detecteur_personnes : {e}', file=sys.stderr)
        rclpy.try_shutdown()
        return 1
    try:
        rclpy.spin(noeud)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        noeud.destroy_node()
        rclpy.try_shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
