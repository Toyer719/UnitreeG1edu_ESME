"""
Repérage du robot sur la carte de l'étage (section 10.5 du plan) : la logique, sans ROS.

Repères (REP-105) :
  - odom → base_link vient de l'odométrie locale du robot (/state_estimator/odom_pelvis) :
    continue, sans saut, mais elle dérive ;
  - map → odom est la correction tirée de la relocalisation d'Unitree
    (/unitree/slam_relocation/odom, après la commande 1804), plus lente et qui peut sauter.
Avec R la relocalisation (pose du repère suivi, dans le repère de la carte d'Unitree) à
l'instant t, et O l'odométrie locale du même instant :
    P_map     = repere ∘ R ∘ inverse(pose_suivi)        (base_link dans map)
    map→odom  = P_map ∘ inverse(O)
repere est la pose de l'origine de la carte d'Unitree dans map (atelier.lieu.repere_unitree).
Toutes les poses sont au sol : (x, y, cap), en mètres et en radians.

Le repérage (localisation unitree), à chaque demande {id, x?, y?, theta?} :
  1. pose annoncée P (map) : celle de la demande, sinon la marque au sol ; U = P dans le repère
     d'Unitree. Sans carte enregistrée sur le robot : echec ;
  2. commande 1804 avec U et la carte (formats de atelier.scan.slam_client) ;
  3. réponse attendue DELAI_REPONSE_S au plus ; refusée : echec ;
  4. une relocalisation reçue après la réponse, DELAI_REPERAGE_S au plus après la demande ;
  5. pose trouvée à plus de ECART_MAX_M ou ECART_MAX_RAD de P : echec, sans map → odom ;
  6. sinon repere, et map → odom est publié ;
  7. ensuite, plus de relocalisation depuis DELAI_PERDU_S : perdu (map → odom reste publié,
     mais repere est faux : le pont arrête le robot) ; elle reprend : repere de nouveau.
Le secours amcl (notre carte et le LiDAR) a sa propre classe, ReperageAmcl.

Les deux classes reçoivent une horloge (time.monotonic par défaut, fausse dans les tests) :
tous les délais comptent en temps mural. Le nœud ROS 2 qui les fait tourner est odom_vers_tf.py.
"""
import json
import math
import time
from collections import deque

from atelier.lieu import (API_RELOCALISER, DELAI_PERDU_S, DELAI_REPERAGE_S, ECART_MAX_M,
                          ECART_MAX_RAD, SAUT_M, SAUT_RAD, carte_vers_unitree, composer_poses,
                          inverser_pose, normaliser_angle, quaternion_vers_cap, valider_message)
from atelier.scan import slam_client

# Attente maximale de la réponse à 1804 (comme un appel du SDK, slam_client.DELAI_APPEL)
DELAI_REPONSE_S = slam_client.DELAI_APPEL
# Tampon de l'odométrie locale, pour l'apparier à une relocalisation un peu en retard
DUREE_TAMPON_S = 2.0
# Secours amcl : repéré sous cet écart-type de position, perdu au-dessus (m)
SIGMA_REPERE_AMCL_M = 0.15
SIGMA_PERDU_AMCL_M = 0.5
# Pose initiale donnée à AMCL : écarts-types en position (m) et en cap (rad)
SIGMA_INITIALE_M = 0.25
SIGMA_INITIALE_RAD = 0.2

MESSAGES = {
    'non_repere': 'Robot non repéré : posez-le sur la marque au sol (croix sur la carte), '
                  'tourné dans le sens de la flèche, puis cliquez sur « Repérer le robot ».',
    'sans_carte': 'Ce lieu n\'a pas de carte enregistrée sur le robot : faites d\'abord un scan '
                  'avec le robot (onglet Scan).',
    'muet': 'Le service de cartographie du robot ne répond pas : vérifiez que unitree_slam est '
            'activé dans l\'appli Unitree.',
    'pas_trouve': 'Le robot n\'a pas réussi à se repérer : vérifiez qu\'il est sur la marque, '
                  'tourné dans le bon sens, puis recommencez.',
    'sans_odometrie': 'Le robot ne donne pas son odométrie locale '
                      '(/state_estimator/odom_pelvis) : vérifiez qu\'il est allumé et relié, '
                      'puis recommencez.',
    'en_cours_amcl': 'Repérage en cours avec la carte et le LiDAR : ne bougez pas le robot.',
    'pas_trouve_amcl': 'Le robot n\'a pas réussi à se repérer avec la carte et le LiDAR : '
                       'vérifiez qu\'il est sur la marque, tourné dans le bon sens, puis '
                       'recommencez.',
    'perdu_amcl': 'Repérage perdu : la carte et le LiDAR ne suffisent plus à situer le robot ; '
                  'il est arrêté. Ramenez-le sur la marque, puis cliquez sur « Repérer le '
                  'robot ».',
}


# ---------------------------------------------------------------- poses au sol

def pose_au_sol(x, y, orientation):
    """
    Pose au sol (x, y, cap) d'une pose 3D : le cap est celui de l'axe x tourné.

    orientation : quaternion (x, y, z, w), dict ou objet geometry_msgs/Quaternion. Le cap de
    l'axe x tourné marche aussi avec un capteur monté à l'envers (roulis de π). z, roulis et
    tangage sont oubliés : base_link est au sol.
    """
    return (float(x), float(y), quaternion_vers_cap(orientation))


def ecart_poses(a, b):
    """(distance en m, écart de cap en rad, en valeur absolue) entre deux poses au sol."""
    return (math.hypot(a[0] - b[0], a[1] - b[1]), abs(normaliser_angle(a[2] - b[2])))


def correction_map_odom(relocalisation, odometrie, repere, pose_suivi=(0.0, 0.0, 0.0)):
    """Correction map → odom et base_link dans map, pour une relocalisation et son odométrie."""
    pose_carte = composer_poses(composer_poses(repere, relocalisation), inverser_pose(pose_suivi))
    return composer_poses(pose_carte, inverser_pose(odometrie)), pose_carte


def precision_covariance(covariance):
    """Écart-type de position √((cov[0] + cov[7]) / 2) ; None si la covariance est nulle."""
    if covariance is None or len(covariance) < 8:
        return None
    variance = (float(covariance[0]) + float(covariance[7])) / 2.0
    if not math.isfinite(variance) or variance <= 0.0:
        return None
    return math.sqrt(variance)


def pose_json(pose):
    if pose is None:
        return None
    return {'x': round(float(pose[0]), 4), 'y': round(float(pose[1]), 4),
            'theta': round(normaliser_angle(float(pose[2])), 4)}


def lire_demande(demande):
    """(id de la demande ou None, liste des erreurs) d'une demande de /reperage/demander."""
    if not isinstance(demande, dict):
        return None, ['/reperage/demander : il faut un objet JSON {"id": ...}']
    ident = demande.get('id')
    return (str(ident) if ident else None), valider_message('demande_reperage', demande)


def pose_annoncee(demande, marque):
    """Pose annoncée (map) : celle de la demande, sinon la marque au sol."""
    if 'x' in demande:
        return (float(demande['x']), float(demande['y']),
                normaliser_angle(float(demande['theta'])))
    return tuple(float(v) for v in marque)


class TamponOdometrie:
    """Les odométries locales des dernières DUREE_TAMPON_S secondes, par horodatage."""

    def __init__(self, duree=DUREE_TAMPON_S):
        self.duree = duree
        self._poses = deque()          # (horodatage en s ou None, pose)

    def ajouter(self, horodatage, pose):
        self._poses.append((horodatage, tuple(float(v) for v in pose)))
        if horodatage is not None:
            while (len(self._poses) > 1 and self._poses[0][0] is not None
                   and self._poses[0][0] < horodatage - self.duree):
                self._poses.popleft()
        while len(self._poses) > 500:
            self._poses.popleft()

    def derniere(self):
        return self._poses[-1][1] if self._poses else None

    def vide(self):
        return not self._poses

    def a_l_instant(self, horodatage):
        """
        Pose la plus proche de l'horodatage, en secondes.

        La dernière s'ils ne se comparent pas : horloges différentes, horodatage nul, hors du
        tampon de plus d'une demi-seconde.
        """
        if not self._poses:
            return None
        datees = [(t, p) for t, p in self._poses if t is not None and t > 0.0]
        if horodatage is None or horodatage <= 0.0 or not datees:
            return self._poses[-1][1]
        if horodatage < datees[0][0] - 0.5 or horodatage > datees[-1][0] + 0.5:
            return self._poses[-1][1]
        return min(datees, key=lambda tp: abs(tp[0] - horodatage))[1]


class _Machine:
    """État commun : etat, message, compteur de changements."""

    def __init__(self, horloge):
        self.horloge = horloge
        self.changements = 0
        self.sauts = 0
        self.relocalisations = 0
        self._etat = 'non_repere'
        self._message = MESSAGES['non_repere']
        self._demande = None

    @property
    def repere_ok(self):
        return self._etat == 'repere'

    def _changer(self, etat, message):
        if (etat, message) != (self._etat, self._message):
            self.changements += 1
        self._etat, self._message = etat, message

    @staticmethod
    def _age(instant, maintenant):
        return None if instant is None else round(max(0.0, maintenant - instant), 3)


# ---------------------------------------------------------------- repérage par 1804 (unitree)

class Reperage(_Machine):
    """
    Repérage par la relocalisation d'Unitree (localisation unitree), sans ROS.

    Entrées, à appeler par le nœud : demander(demande), sur_reponse(...), sur_relocalisation(...),
    sur_odometrie(...), pas() (délais, une dizaine de fois par seconde). Sorties : etat()
    (message /reperage/etat), map_odom() (correction à publier, ou None), pose_carte(), et
    changements (compteur, augmente à chaque changement d'état ou de message).
    """

    def __init__(self, repere, carte, pose_suivi=(0.0, 0.0, 0.0), horloge=time.monotonic,
                 delai_reponse=DELAI_REPONSE_S, delai_reperage=DELAI_REPERAGE_S,
                 delai_perdu=DELAI_PERDU_S, ecart_max_m=ECART_MAX_M, ecart_max_rad=ECART_MAX_RAD):
        super().__init__(horloge)
        self.repere = tuple(float(v) for v in repere)
        self.carte = carte or None
        self.pose_suivi = tuple(float(v) for v in pose_suivi)
        self.delai_reponse = delai_reponse
        self.delai_reperage = delai_reperage
        self.delai_perdu = delai_perdu
        self.ecart_max_m = ecart_max_m
        self.ecart_max_rad = ecart_max_rad
        self.odometries = TamponOdometrie()
        self.ecart = None              # (m, rad) : pose trouvée / pose annoncée, au repérage
        self._annoncee = None          # pose annoncée P (map)
        self._requete = None           # id de la requête 1804 en attente de réponse
        self._dernier_id = 0
        self._instant_demande = None
        self._instant_reponse = None   # réponse positive reçue : on attend la relocalisation
        self._map_odom = None
        self._pose_carte = None
        self._precision = None
        self._derniere_reloc = None    # instant (horloge) de la dernière relocalisation utilisée

    # ------------------------------------------------------------ entrées

    def demander(self, demande):
        """
        Traite une nouvelle demande (dict du schéma demande_reperage).

        Renvoie la requête 1804 à envoyer, {id, api_id, parameter, pose_unitree}, ou None si la
        demande échoue tout de suite (etat() dit pourquoi).
        """
        self._demande, erreurs = lire_demande(demande)
        self._requete = self._instant_reponse = None
        self._instant_demande = self.horloge()
        if erreurs:
            self._echouer('Demande de repérage refusée : ' + ' ; '.join(erreurs))
            return None
        self._annoncee = pose_annoncee(demande, self.repere)   # marque : (0, 0, 0) d'Unitree
        if not self.carte:
            self._echouer(MESSAGES['sans_carte'])
            return None
        u = carte_vers_unitree(self._annoncee, self.repere)
        parametres = slam_client.parametres_relocaliser(u[0], u[1], u[2], self.carte)
        self._dernier_id = max(self._dernier_id + 1, time.monotonic_ns())
        self._requete = self._dernier_id
        self._changer('en_cours', f'Repérage en cours sur la carte « {self.carte} » : ne bougez '
                                  'pas le robot (quelques secondes).')
        return {'id': self._requete, 'api_id': API_RELOCALISER,
                'parameter': json.dumps(parametres), 'pose_unitree': u}

    def sur_reponse(self, identite, code, donnees):
        """
        Traite une réponse de slam_operate : header.identity.id, status.code, texte JSON (data).

        Renvoie True si c'était la réponse attendue.
        """
        if self._requete is None or int(identite) != self._requete:
            return False             # réponse à un autre client du robot, ou trop tard
        self._requete = None
        reponse = slam_client.lire_reponse(int(code), donnees)
        if not reponse.ok:
            if int(code) != 0:
                self._echouer('Le service de cartographie du robot a refusé 1804 '
                              f'({reponse.message}).')
            else:
                info = reponse.donnees.get('info') if isinstance(reponse.donnees, dict) else None
                self._echouer(f'Le robot refuse de se repérer : {info or reponse.message}.')
            return True
        self._instant_reponse = self.horloge()
        return True

    def sur_odometrie(self, pose, horodatage=None):
        """Odométrie locale (odom → base_link au sol), avec son horodatage en secondes."""
        self.odometries.ajouter(horodatage, pose)
        if self._map_odom is not None:
            self._pose_carte = composer_poses(self._map_odom, pose)

    def sur_relocalisation(self, pose_unitree, horodatage=None, covariance=None):
        """Relocalisation : pose au sol du repère suivi, dans le repère de la carte d'Unitree."""
        maintenant = self.horloge()
        self.relocalisations += 1
        odometrie = self.odometries.a_l_instant(horodatage)
        if odometrie is None:
            return                   # pas encore d'odométrie : on attend (délai du repérage)
        correction, pose_carte = correction_map_odom(pose_unitree, odometrie, self.repere,
                                                     self.pose_suivi)
        if self._etat == 'en_cours':
            if self._instant_reponse is None:
                return               # avant la réponse à 1804 : ancienne relocalisation
            self.ecart = ecart_poses(pose_carte, self._annoncee)
            if self.ecart[0] > self.ecart_max_m or self.ecart[1] > self.ecart_max_rad:
                self._echouer(f'Le robot s\'est repéré à {self.ecart[0]:.1f} m (et '
                              f'{math.degrees(self.ecart[1]):.0f}°) de la position annoncée : '
                              'vérifiez qu\'il est bien sur la marque, tourné dans le sens de la '
                              'flèche, puis recommencez.')
                return
            self.sauts = 0
            self._accepter(correction, covariance, maintenant)
            self._changer('repere', self._message_repere())
        elif self._etat in ('repere', 'perdu'):
            saut = ecart_poses(correction, self._map_odom)
            if saut[0] > SAUT_M or saut[1] > SAUT_RAD:
                self.sauts += 1      # appliquée quand même : la relocalisation fait foi
            self._accepter(correction, covariance, maintenant)
            if self._etat == 'perdu':
                self._changer('repere', self._message_repere())

    def pas(self):
        """Délais : réponse, relocalisation après la demande, perte de la relocalisation."""
        maintenant = self.horloge()
        if self._etat == 'en_cours':
            ecoule = maintenant - self._instant_demande
            if self._requete is not None and ecoule > self.delai_reponse:
                self._requete = None
                self._echouer(MESSAGES['muet'])
            elif ecoule > self.delai_reperage:
                sans_odometrie = self._instant_reponse is not None and self.odometries.vide()
                self._echouer(MESSAGES['sans_odometrie' if sans_odometrie else 'pas_trouve'])
        elif self._etat == 'repere' and maintenant - self._derniere_reloc > self.delai_perdu:
            self._changer('perdu', 'Repérage perdu : le robot ne reçoit plus sa position sur la '
                                   f'carte depuis {self.delai_perdu:.0f} s ; il est arrêté. Il '
                                   'repartira dès qu\'elle reviendra.')

    # ------------------------------------------------------------ sorties

    def map_odom(self):
        """Correction map → odom à publier (pose au sol), ou None : pas repéré, ou échec."""
        return self._map_odom

    def pose_carte(self):
        return self._pose_carte

    def etat(self):
        """
        Renvoie le message de /reperage/etat, au format du schéma etat_reperage.

        Deux champs en plus : correction (map → odom) et relocalisations (nombre reçu).
        """
        precision = None if self._precision is None else round(self._precision, 4)
        return {'version': 1, 'etat': self._etat, 'repere': self._etat == 'repere',
                'localisation': 'unitree', 'message': self._message,
                'pose': pose_json(self._pose_carte), 'precision_m': precision,
                'age_s': self._age(self._derniere_reloc, self.horloge()),
                'demande': self._demande, 'carte': self.carte,
                'repere_unitree': pose_json(self.repere), 'sauts': self.sauts,
                'correction': pose_json(self._map_odom), 'relocalisations': self.relocalisations}

    # ------------------------------------------------------------ interne

    def _accepter(self, correction, covariance, maintenant):
        self._map_odom = correction
        self._derniere_reloc = maintenant
        self._precision = precision_covariance(covariance)
        derniere = self.odometries.derniere()
        if derniere is not None:
            self._pose_carte = composer_poses(correction, derniere)

    def _message_repere(self):
        if self._precision is None:
            return 'Robot repéré sur la carte.'
        return f'Robot repéré sur la carte (précision {max(1, round(self._precision * 100))} cm).'

    def _echouer(self, message):
        self._map_odom = None          # plus de map → odom : la navigation ne doit pas partir
        self._instant_reponse = None
        self._changer('echec', message)


# ---------------------------------------------------------------- secours amcl

class ReperageAmcl(_Machine):
    """
    Repérage de secours par AMCL (notre carte et le LiDAR), sans ROS.

    demander(demande) renvoie la pose initiale à publier sur /initialpose : {pose, covariance}
    (6 × 6 à plat). sur_pose_amcl(pose, covariance) suit /amcl_pose. Repéré quand l'écart-type de
    position descend sous sigma_repere (en delai_reperage au plus), perdu au-dessus de
    sigma_perdu, ou sans nouvelle pose d'AMCL depuis delai_muet. AMCL publie lui-même map → odom.
    """

    def __init__(self, repere, horloge=time.monotonic, delai_reperage=DELAI_REPERAGE_S,
                 sigma_repere=SIGMA_REPERE_AMCL_M, sigma_perdu=SIGMA_PERDU_AMCL_M,
                 delai_muet=None):
        super().__init__(horloge)
        self.repere = tuple(float(v) for v in repere)
        self.delai_reperage = delai_reperage
        self.sigma_repere = sigma_repere
        self.sigma_perdu = sigma_perdu
        self.delai_muet = delai_muet
        self._instant_demande = None
        self._pose = None
        self._sigma = None
        self._derniere = None

    def demander(self, demande):
        self._demande, erreurs = lire_demande(demande)
        self._instant_demande = self.horloge()
        if erreurs:
            self._changer('echec', 'Demande de repérage refusée : ' + ' ; '.join(erreurs))
            return None
        covariance = [0.0] * 36
        covariance[0] = covariance[7] = SIGMA_INITIALE_M ** 2
        covariance[35] = SIGMA_INITIALE_RAD ** 2
        self._changer('en_cours', MESSAGES['en_cours_amcl'])
        return {'pose': pose_annoncee(demande, self.repere), 'covariance': covariance}

    def sur_odometrie(self, pose, horodatage=None):
        """Odométrie locale : AMCL la lit lui-même par TF (odom → base_link), rien à faire ici."""

    def sur_pose_amcl(self, pose, covariance):
        self._pose = tuple(float(v) for v in pose)
        self._derniere = self.horloge()
        self.relocalisations += 1
        self._sigma = precision_covariance(covariance)
        if self._sigma is None:
            return
        if self._etat in ('en_cours', 'perdu') and self._sigma < self.sigma_repere:
            self._changer('repere', 'Robot repéré avec la carte et le LiDAR (précision '
                                    f'{max(1, round(self._sigma * 100))} cm).')
        elif self._etat == 'repere' and self._sigma > self.sigma_perdu:
            self._changer('perdu', MESSAGES['perdu_amcl'])

    def pas(self):
        maintenant = self.horloge()
        if self._etat == 'en_cours' and maintenant - self._instant_demande > self.delai_reperage:
            self._changer('echec', MESSAGES['pas_trouve_amcl'])
        elif (self._etat == 'repere' and self.delai_muet and self._derniere is not None
              and maintenant - self._derniere > self.delai_muet):
            self._changer('perdu', MESSAGES['perdu_amcl'])

    def map_odom(self):
        return None                    # publié par AMCL

    def pose_carte(self):
        return self._pose

    def etat(self):
        precision = None if self._sigma is None else round(self._sigma, 4)
        return {'version': 1, 'etat': self._etat, 'repere': self._etat == 'repere',
                'localisation': 'amcl', 'message': self._message, 'pose': pose_json(self._pose),
                'precision_m': precision, 'age_s': self._age(self._derniere, self.horloge()),
                'demande': self._demande, 'carte': None,
                'repere_unitree': pose_json(self.repere), 'sauts': self.sauts,
                'relocalisations': self.relocalisations}
