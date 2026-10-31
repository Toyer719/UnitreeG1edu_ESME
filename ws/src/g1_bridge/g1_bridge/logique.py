"""
Logique du pont /cmd_vel → ordres de marche 7105 du G1, sans ROS (section 10.3 du plan).

Le nœud pont_g1 (pont.py) ne fait que passer les messages à la classe Pont et publier ce qu'elle
renvoie. Toutes les règles sont ici, avec une horloge injectable (temps mural monotone, en
secondes ; jamais le temps simulé), pour les tester finement :

  1. Plafonds durs : |vx| ≤ 0,4 m/s, |vy| ≤ 0,25 m/s, |wz| ≤ 0,6 rad/s, avec le signe. Une
     composante non finie (NaN, infini) fait de toute la consigne un arrêt. Des réglages plus
     hauts sont refusés (ErreurReglages) : le nœud ne démarre pas.
  2. Consigne fraîche (dernier /cmd_vel il y a moins de 0,3 s) : envoyée à 10 Hz, avec duration
     0,5 s. Une consigne nulle (toutes les composantes sous 1e-3) part au format de l'arrêt.
     Un départ (repos → mouvement) et un arrêt (mouvement → consigne nulle) partent tout de suite.
  3. Plus de /cmd_vel depuis 0,3 s : un arrêt tout de suite, puis plus rien. Au repos, le pont
     n'envoie rien en continu (sauf la lecture du mode, règle 12).
  4. /guide/stop : arrêt immédiat ; /cmd_vel ignoré pendant 1 s (état arret).
  5. /pont/arret true : arrêt immédiat, envoyé 3 fois en 0,2 s ; état arret_verrouille ;
     /cmd_vel ignoré jusqu'à /pont/arret false, puis le mouvement ne reprend qu'avec un
     /cmd_vel reçu après le déverrouillage.
  6. Repérage exigé (par défaut) : le mouvement n'est permis que si le dernier /reperage/etat
     date de moins de 1 s et a repere vrai ; sinon /cmd_vel est ignoré, et un arrêt part si le
     robot bougeait.
  7. Robot muet : des requêtes sont parties et aucune réponse n'est arrivée depuis 1 s. Le pont
     continue d'envoyer la consigne fraîche (le robot s'arrête seul à la fin de duration) ; il
     revient à la normale à la première réponse.
  8. Refus : la dernière réponse a un code non nul (état refus, avec le code et un message).
  9. Au lancement, un arrêt qui vérifie le lien (état demarrage jusqu'à la réponse, robot_muet
     après 1 s sans réponse) ; à la sortie, un arrêt.
     Vérification du lien : la découverte DDS prend du temps, et un arrêt publié avant que le
     service sport soit vu serait perdu. L'arrêt de vérification part donc dès qu'un abonné à
     /api/sport/request est vu (tout de suite s'il l'est déjà), puis encore deux fois au plus,
     à 0,3 s d'écart, tant qu'aucune réponse n'arrive. Une nouvelle vérification se fait quand
     un nouvel abonné apparaît alors que le robot n'a jamais répondu ou est muet (service
     relancé), si le pont n'est pas en train d'envoyer une consigne. Rien de continu au repos.
 10. Maître des mouvements (vague 4, section 11.5 du plan) : /mouvement/maitre « pilotage » (le
     pilotage de l'Atelier a la main) : état pilotage, mouvement interdit, /cmd_vel ignoré, un
     arrêt tout de suite si le robot bougeait. « guide », ou aucun message : comme avant ; le
     mouvement ne reprend qu'avec un /cmd_vel reçu après le retour de la main.

Vague 5 (section 12.6 du plan) :

 11. Vitesse minimale de marche : le 27/10, le vrai G1 acceptait 7105 à 0,1 m/s sans faire un
     pas, et marchait à 0,2 m/s. Après les plafonds, vitesse_effective (copie exacte de celle
     d'atelier.lieu.robot) : si la norme de (vx, vy) atteint vitesse_min_lin, ou |wz| atteint
     vitesse_min_rot, la consigne passe telle quelle ; sinon toute la consigne est petite :
     zones mortes (zone_morte_lin sur la norme, zone_morte_rot sur |wz| : en dessous, 0), puis
     l'intention dominante : marche portée à la norme minimale dans la même direction, ou
     rotation sur place à ± vitesse_min_rot. 0 désactive un minimum ou une zone. /pont/etat
     donne demande (la consigne après les plafonds, avant le minimum) et minimums.
 12. Mode du robot : le pont lit 7001 (GetFsmId) une fois par seconde, quand le service sport
     a un abonné ou a déjà répondu. Ces lectures ne comptent ni dans envoyees, ni dans reponses,
     ni pour robot_muet et refus. Un mode connu hors de modes_marche (assis, course...) : état
     pas_en_marche, mouvement interdit, un arrêt part si le robot bougeait, /cmd_vel ignoré, et
     un message qui dit quoi faire ; de retour en marche : pret, et le mouvement ne reprend
     qu'avec un /cmd_vel neuf. Un mode lu il y a plus de 3 s, une lecture refusée ou illisible :
     mode inconnu, qui ne bloque rien. Seules les réponses à NOS requêtes comptent (même
     identity.id, et même api_id quand la réponse le donne) : les autres programmes du robot
     lisent aussi 7001 et leurs réponses arrivent sur le même sujet.

Un /cmd_vel ignoré (garde, verrou, repérage, pilotage, mode) n'est pas gardé : il ne sert pas
plus tard.
"""
from collections import OrderedDict, namedtuple
from dataclasses import dataclass, field, fields
import math
import time

from .requete import (API_GET_FSM_ID, API_SET_VELOCITY, DUREE_ARRET_S, Identifiants, lire_mode,
                      parametre_arret, parametre_lecture_mode, parametre_vitesse)

# Plafonds durs du pont (atelier.lieu.LIMITES_PONT) : un réglage plus haut est refusé
PLAFONDS = {'vx': 0.4, 'vy': 0.25, 'wz': 0.6}
# Une consigne dont toutes les composantes sont sous ce seuil est un arrêt
SEUIL_NUL = 1e-3
# Durée maximale d'une consigne : si le pont meurt, le robot s'arrête seul au plus tard après
DUREE_CONSIGNE_MAX_S = 0.5
# Écart entre les arrêts répétés d'un verrouillage (3 envois en 0,2 s)
ECART_ARRETS_VERROU_S = 0.1
NOMBRE_ARRETS_VERROU = 3
# Vérification du lien : arrêts envoyés tant qu'aucune réponse n'arrive (3 au plus, 0,3 s d'écart)
ECART_VERIFICATION_S = 0.3
NOMBRE_VERIFICATIONS = 3
# Requêtes dont on attend encore la réponse (au-delà, les plus anciennes sont oubliées)
MEMOIRE_IDENTIFIANTS = 1000
MEMOIRE_LECTURES = 20
# Un envoi périodique part au premier pas() qui tombe à moins de ce temps avant son heure
# (pas() est appelé toutes les 20 ms par le nœud : la cadence reste de 10 Hz malgré le jitter)
TOLERANCE_ENVOI_S = 0.008

# Vitesse minimale (règle 11) : valeurs du contrat (atelier.lieu.VITESSES_MIN_PONT,
# ZONES_MORTES_PONT, VITESSE_MIN_LIN_MAX, VITESSE_MIN_ROT_MAX ; test/test_reglages.py compare)
VITESSES_MIN = {'lin': 0.20, 'rot': 0.30}
ZONES_MORTES = {'lin': 0.05, 'rot': 0.10}
VITESSE_MIN_LIN_MAX = 0.30      # un réglage plus haut est refusé (une faute de frappe ne fait
VITESSE_MIN_ROT_MAX = 0.50      # pas courir le robot)
# Lecture du mode (règle 12) : atelier.lieu.PERIODE_LECTURE_MODE_S et DELAI_MODE_PERIME_S
PERIODE_LECTURE_MODE_S = 1.0
DELAI_MODE_PERIME_S = 3.0

# 'pilotage' (vague 4, section 11.5 du plan) : le pilotage de l'Atelier a la main
# (/mouvement/maitre), /cmd_vel est ignoré (règle 10)
MAITRES = ('guide', 'pilotage')
# 'pas_en_marche' (vague 5, section 12.6 du plan) : le mode lu par 7001 n'est pas un mode de
# marche (règle 12)
ETATS = ('demarrage', 'attente_reperage', 'pret', 'en_mouvement', 'arret', 'arret_verrouille',
         'robot_muet', 'refus', 'pilotage', 'pas_en_marche')
# Modes du robot (7001) où il marche : copie exacte de atelier.lieu.pilotage.MODES_MARCHE (le pont
# tourne sans atelier ; atelier/tests/test_contrats_vague5.py compare les deux)
MODES_MARCHE = (500, 501, 801)
# Copies de atelier.lieu.pilotage (MODES_COURSE, NOMS_MODES, DANSE_PREFIXE), pour les messages ;
# test/test_reglages.py compare nom_mode et message_pas_en_marche à ceux d'atelier
MODES_COURSE = (802,)
NOMS_MODES = {0: 'pas démarré', 1: 'amorti', 2: 'accroupi', 3: 'assis', 4: 'debout, verrouillé',
              500: 'démarrage', 501: 'marche', 702: 'se relève', 706: 'accroupi ↔ debout',
              801: 'marche', 802: 'course'}
DANSE_PREFIXE = 550000

# Messages des refus connus du service sport (codes d'unitree_ros2 et du SDK)
MESSAGES_REFUS = {
    7301: 'mettez-le en mode marche avec la télécommande',
    7302: 'mode de marche invalide : vérifiez son mode avec la télécommande',
    3203: "il ne connaît pas l'ordre de marche 7105 : vérifiez la version de son logiciel",
    3204: "il ne comprend pas les paramètres de l'ordre de marche : format à vérifier",
    3205: "il réserve la marche à un autre programme (bail refusé) : fermez l'appli ou "
          "l'autre programme qui le pilote",
}


class ErreurReglages(ValueError):
    """Réglage du pont refusé ; le message dit quoi corriger."""


def _fr(nombre):
    """Nombre écrit à la française (virgule), pour les messages."""
    return f'{nombre:g}'.replace('.', ',')


@dataclass
class Reglages:
    """Réglages du pont (config/pont.yaml), avec les valeurs du contrat par défaut."""

    vx_max: float = 0.4
    vy_max: float = 0.25
    wz_max: float = 0.6
    duree_consigne: float = 0.5
    duree_arret: float = DUREE_ARRET_S
    delai_cmd_vel: float = 0.3
    frequence: float = 10.0
    garde_stop: float = 1.0
    exiger_reperage: bool = True
    delai_reperage: float = 1.0
    delai_muet: float = 1.0
    # Vague 5 (section 12.6) : vitesse minimale (règle 11) et lecture du mode (règle 12)
    vitesse_min_lin: float = VITESSES_MIN['lin']
    vitesse_min_rot: float = VITESSES_MIN['rot']
    zone_morte_lin: float = ZONES_MORTES['lin']
    zone_morte_rot: float = ZONES_MORTES['rot']
    lire_mode: bool = True
    modes_marche: list = field(default_factory=lambda: list(MODES_MARCHE))

    BOOLEENS = ('exiger_reperage', 'lire_mode')

    @classmethod
    def noms(cls):
        return [f.name for f in fields(cls)]

    def verifier(self):
        """Lève ErreurReglages si un réglage est dangereux ou absurde ; renvoie self sinon."""
        erreurs = []
        for nom in self.noms():
            valeur = getattr(self, nom)
            if nom in self.BOOLEENS:
                if not isinstance(valeur, bool):
                    erreurs.append(f'{nom} doit valoir true ou false, pas {valeur!r}')
                continue
            if nom == 'modes_marche':
                if not isinstance(valeur, (list, tuple)) or not valeur or not all(
                        isinstance(m, int) and not isinstance(m, bool) and m >= 0 for m in valeur):
                    erreurs.append(f'modes_marche doit être une liste de modes (nombres entiers, '
                                   f'ex. [500, 501, 801]), pas {valeur!r}')
                continue
            if isinstance(valeur, bool) or not isinstance(valeur, (int, float)) \
                    or not math.isfinite(valeur):
                erreurs.append(f'{nom} doit être un nombre fini, pas {valeur!r}')
        if erreurs:
            raise ErreurReglages(' ; '.join(erreurs))
        for axe, plafond in PLAFONDS.items():
            valeur = getattr(self, f'{axe}_max')
            if valeur > plafond + 1e-9:
                erreurs.append(f'{axe}_max = {valeur:g} dépasse le plafond dur du pont '
                               f'({plafond:g}) : mettez au plus {plafond:g}')
            elif valeur <= 0:
                erreurs.append(f'{axe}_max = {valeur:g} doit être positif')
        if not 0 < self.duree_consigne <= DUREE_CONSIGNE_MAX_S:
            erreurs.append(f'duree_consigne = {self.duree_consigne:g} s : il faut entre 0 et '
                           f'{DUREE_CONSIGNE_MAX_S:g} s (le robot s\'arrête seul après)')
        if not 0 < self.duree_arret <= 5.0:
            erreurs.append(f'duree_arret = {self.duree_arret:g} s : il faut entre 0 et 5 s')
        if not 0 < self.delai_cmd_vel <= DUREE_CONSIGNE_MAX_S:
            erreurs.append(f'delai_cmd_vel = {self.delai_cmd_vel:g} s : il faut entre 0 et '
                           f'{DUREE_CONSIGNE_MAX_S:g} s')
        if erreurs:
            raise ErreurReglages(' ; '.join(erreurs))
        if self.frequence <= 0 or 1.0 / self.frequence >= self.duree_consigne:
            erreurs.append(f'frequence = {self.frequence:g} Hz : un envoi doit partir avant la '
                           f'fin du précédent ({self.duree_consigne:g} s), il faut plus de '
                           f'{1.0 / self.duree_consigne:g} Hz')
        elif self.frequence > 50:
            erreurs.append(f'frequence = {self.frequence:g} Hz : 50 Hz au plus')
        if self.garde_stop < 0:
            erreurs.append(f'garde_stop = {self.garde_stop:g} s doit être positif ou nul')
        for nom in ('delai_reperage', 'delai_muet'):
            if getattr(self, nom) <= 0:
                erreurs.append(f'{nom} = {getattr(self, nom):g} s doit être positif')
        erreurs += self._verifier_minimums()
        if erreurs:
            raise ErreurReglages(' ; '.join(erreurs))
        return self

    def _verifier_minimums(self):
        """Erreurs des réglages de la vitesse minimale (règle 11)."""
        erreurs = []
        for nom in ('vitesse_min_lin', 'vitesse_min_rot', 'zone_morte_lin', 'zone_morte_rot'):
            if getattr(self, nom) < 0:
                erreurs.append(f'{nom} = {_fr(getattr(self, nom))} doit être positif ou nul '
                               '(0 désactive)')
        if erreurs:
            return erreurs
        for genre, maximum, plafond, unite, mesure in (
                ('lin', VITESSE_MIN_LIN_MAX, 'vx_max', 'm/s', 'de marche'),
                ('rot', VITESSE_MIN_ROT_MAX, 'wz_max', 'rad/s', 'de rotation')):
            minimum = getattr(self, f'vitesse_min_{genre}')
            zone = getattr(self, f'zone_morte_{genre}')
            if minimum > maximum + 1e-9:
                erreurs.append(f'vitesse_min_{genre} = {_fr(minimum)} {unite} : {_fr(maximum)} '
                               f'{unite} au plus (une faute de frappe ne doit pas faire courir '
                               'le robot)')
            elif minimum > getattr(self, plafond) + 1e-9:
                erreurs.append(f'{plafond} {_fr(getattr(self, plafond))} est sous la vitesse '
                               f'minimale {mesure} {_fr(minimum)} : le robot ne ferait aucun pas '
                               f'; mettez {plafond} ≥ {_fr(minimum)}, ou vitesse_min_{genre}:=0 '
                               'pour une mesure')
            borne = minimum if minimum > 0 else maximum
            if zone > borne + 1e-9:
                erreurs.append(f'zone_morte_{genre} = {_fr(zone)} {unite} : pas plus que '
                               + (f'la vitesse minimale ({_fr(minimum)})' if minimum > 0
                                  else f'{_fr(maximum)} {unite}'))
        return erreurs

    def avertissements(self):
        """Réglages permis mais à signaler (journal du nœud), en français."""
        messages = []
        if 0 < self.vy_max < self.vitesse_min_lin:
            messages.append(f'vy_max {_fr(self.vy_max)} est sous la vitesse minimale de marche '
                            f'{_fr(self.vitesse_min_lin)} : un pas de côté seul ne l\'atteindra '
                            'pas (le vrai robot risque de ne pas bouger de côté)')
        if self.vitesse_min_lin == 0 or self.vitesse_min_rot == 0:
            messages.append('vitesse minimale désactivée (vitesse_min_lin ou vitesse_min_rot à 0) '
                            ': sous 0,2 m/s, le vrai robot ne fait aucun pas (mesures seulement)')
        return messages


# Une requête à publier : identity.id, vitesses envoyées, duration, raison, texte JSON, api_id
# (7105 SetVelocity, ou 7001 GetFsmId pour une lecture du mode : vitesses et duration à 0)
Envoi = namedtuple('Envoi', 'identifiant vx vy wz duree raison parametre api_id',
                   defaults=(API_SET_VELOCITY,))


def est_nulle(consigne):
    """Vrai si toutes les composantes (vx, vy, wz) sont sous le seuil : c'est un arrêt."""
    return all(abs(v) < SEUIL_NUL for v in consigne)


def plafonner(vx, vy, wz, reglages):
    """Consigne ramenée sous les plafonds, avec son signe ; non finie : (0, 0, 0)."""
    valeurs = []
    for v in (vx, vy, wz):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return (0.0, 0.0, 0.0)
        if not math.isfinite(v):
            return (0.0, 0.0, 0.0)
        valeurs.append(v)
    limites = (reglages.vx_max, reglages.vy_max, reglages.wz_max)
    return tuple(max(-m, min(m, v)) for v, m in zip(valeurs, limites))


def vitesse_effective(vx, vy, wz, plafonds=None, minimums=None, zones=None):
    """
    Consigne déjà plafonnée → consigne envoyée au robot (règle 11).

    Copie exacte de atelier.lieu.robot.vitesse_effective (le pont tourne sans atelier ;
    test/test_reglages.py compare les deux sur des milliers de consignes au hasard).
    1. Le robot marche déjà franchement (norme de (vx, vy) ≥ minimum linéaire, ou |wz| ≥ minimum
       de rotation) : la consigne passe telle quelle, petites corrections comprises.
    2. Sinon, toute la consigne est petite : zones mortes (norme de (vx, vy) sous la zone
       linéaire → (vx, vy) = 0 ; |wz| sous la zone de rotation → wz = 0). Tout à 0 : un arrêt.
    3. Puis l'intention dominante (norme / minimum linéaire comparée à |wz| / minimum de
       rotation) : marche : (vx, vy) porté à la norme du minimum, même direction (borné pour
       qu'aucune composante ne dépasse son plafond), wz gardé ; rotation : (0, 0, ±minimum de
       rotation), borné par wz_max.
    Un minimum (ou une zone) à 0 est désactivé. Une valeur non finie donne un arrêt.
    plafonds : {"vx", "vy", "wz"} ; minimums, zones : {"lin", "rot"}. Renvoie (vx, vy, wz).
    """
    p = PLAFONDS if plafonds is None else plafonds
    m = VITESSES_MIN if minimums is None else minimums
    z = ZONES_MORTES if zones is None else zones
    if not all(math.isfinite(v) for v in (vx, vy, wz)):
        return (0.0, 0.0, 0.0)
    smin, wmin = m['lin'], m['rot']
    n, a = math.hypot(vx, vy), abs(wz)
    if (smin > 0 and n >= smin) or (wmin > 0 and a >= wmin):
        return (vx, vy, wz)
    if n < z['lin']:
        vx = vy = n = 0.0
    if a < z['rot']:
        wz = a = 0.0
    lin_petit = 0.0 < n < smin
    rot_petit = 0.0 < a < wmin
    if (n > 0.0 and not lin_petit) or (a > 0.0 and not rot_petit) \
            or not (lin_petit or rot_petit):
        return (vx, vy, wz)        # minimum désactivé sur cet axe, ou consigne nulle
    if lin_petit and (not rot_petit or n / smin >= a / wmin):
        k = smin / n
        if vx:
            k = min(k, p['vx'] / abs(vx))
        if vy:
            k = min(k, p['vy'] / abs(vy))
        return (vx * k, vy * k, wz)
    return (0.0, 0.0, math.copysign(min(wmin, p['wz']), wz))


def nom_mode(fsm):
    """Nom en français d'un mode du robot (copie de atelier.lieu.pilotage.nom_mode)."""
    if fsm is None:
        return 'inconnu'
    if DANSE_PREFIXE < fsm < DANSE_PREFIXE + 1000:
        return f'danse {fsm - DANSE_PREFIXE}'
    return NOMS_MODES.get(fsm, f'mode {fsm} inconnu')


def message_pas_en_marche(fsm):
    """Ce qui se passe, puis quoi faire (copie de atelier.lieu.pilotage.message_pas_en_marche)."""
    if fsm in MODES_COURSE:
        return (f'Le robot est en mode course ({fsm}) : passez en marche normale à la '
                'télécommande. La navigation ne marche pas en mode course.')
    suite = ' : il ignore les ordres de marche. '
    if fsm in (0, 1):
        return (f'Le robot n\'est pas démarré (mode {fsm}, {nom_mode(fsm)})' + suite
                + 'Démarrez-le avec la télécommande (ou « Démarrer » dans Piloter).')
    if fsm == 3:
        return ('Le robot est assis (mode 3)' + suite
                + 'Mettez-le debout puis en marche avec la télécommande (ou « Démarrer » dans '
                  'Piloter).')
    return (f'Le robot n\'est pas en mode marche (mode {fsm}, {nom_mode(fsm)})' + suite
            + 'Mettez-le en marche avec la télécommande (ou « Démarrer » dans Piloter).')


def message_refus(code):
    """Phrase en français pour un code de refus du service sport."""
    conseil = MESSAGES_REFUS.get(code, 'vérifiez son mode avec la télécommande')
    return f'Le robot refuse de marcher (code {code}) : {conseil}.'


class Pont:
    """Règles du pont ; chaque entrée renvoie la liste des requêtes (Envoi) à publier."""

    def __init__(self, reglages=None, horloge=time.monotonic, identifiants=None):
        self.reglages = (reglages or Reglages()).verifier()
        r = self.reglages
        self.plafonds = {'vx': r.vx_max, 'vy': r.vy_max, 'wz': r.wz_max}
        self.minimums = {'lin': r.vitesse_min_lin, 'rot': r.vitesse_min_rot}
        self.zones = {'lin': r.zone_morte_lin, 'rot': r.zone_morte_rot}
        self.horloge = horloge
        self.identifiants = identifiants or Identifiants()
        # Consigne acceptée en cours (après plafonds et vitesse minimale), instant de sa réception
        self.consigne = (0.0, 0.0, 0.0)
        self.t_consigne = None
        self.demande = (0.0, 0.0, 0.0)     # dernier /cmd_vel, après les plafonds (règle 11)
        self.actif = False                 # envoi à 10 Hz en cours (consigne fraîche)
        self.t_cmd_vel = None              # dernier /cmd_vel reçu, même ignoré
        self.derniere = (0.0, 0.0, 0.0)    # vitesses du dernier envoi (arrêt : 0, 0, 0)
        self.t_dernier_envoi = None
        self.prochain_envoi = None         # heure prévue du prochain envoi périodique
        self.garde_jusqua = None           # /guide/stop : /cmd_vel ignoré jusque-là
        self.verrou = False
        self.arrets_prevus = []            # instants des arrêts répétés du verrouillage
        self.repere = False
        self.t_reperage = None
        self.envoyes = OrderedDict()       # identity.id → instant d'envoi, en attente de réponse
        self.envoyees = 0
        self.reponses = 0
        self.t_attente = None              # premier envoi depuis la dernière réponse
        self.t_reponse = None
        self.code = None
        self.abonnes = 0                   # abonnés vus à /api/sport/request (le service sport)
        self.verifications = []            # instants des arrêts de vérification du lien à venir
        self.t_verification = None         # début de la vérification en cours
        self.maitre = 'guide'              # /mouvement/maitre (vague 4) ; aucun message : le guide
        # Mode du robot (règle 12) : dernier mode lu (None : inconnu) et instant de la lecture
        self.mode = None
        self.t_mode = None
        self.code_mode = None              # code de la dernière réponse à une lecture
        self.lectures = OrderedDict()      # identity.id des lectures 7001 en attente de réponse
        self.lectures_envoyees = 0
        self.t_lecture = None
        self.t_premiere_lecture = None

    # ------------------------------------------------------------ état

    def maintenant(self):
        return float(self.horloge())

    def reperage_valable(self, t=None):
        """Dernier /reperage/etat récent (moins de delai_reperage) et repere vrai."""
        t = self.maintenant() if t is None else t
        return (self.repere and self.t_reperage is not None
                and t - self.t_reperage < self.reglages.delai_reperage)

    def en_garde(self, t):
        return self.garde_jusqua is not None and t < self.garde_jusqua

    def mode_connu(self, t=None):
        """Le mode du robot lu il y a moins de 3 s (lecture permise), sinon None (inconnu)."""
        t = self.maintenant() if t is None else t
        if not self.reglages.lire_mode or self.mode is None or self.t_mode is None:
            return None
        if t - self.t_mode > DELAI_MODE_PERIME_S:
            return None
        return self.mode

    def en_marche(self, t=None):
        """Dit si le robot marche d'après le mode lu (modes_marche) ; None si mode inconnu."""
        fsm = self.mode_connu(t)
        if fsm is None:
            return None
        return fsm in self.reglages.modes_marche

    def mouvement_permis(self, t=None):
        """Vrai si un /cmd_vel non nul reçu maintenant serait envoyé au robot."""
        t = self.maintenant() if t is None else t
        if self.verrou or self.en_garde(t) or self.maitre == 'pilotage':
            return False
        if self.en_marche(t) is False:
            return False
        return self.reperage_valable(t) or not self.reglages.exiger_reperage

    def _raison_interdit(self, t):
        """Pourquoi le mouvement est interdit (raison de l'arrêt envoyé)."""
        if self.verrou:
            return 'verrou'
        if self.maitre == 'pilotage':
            return 'pilotage'
        if self.en_marche(t) is False:
            return 'mode'
        if self.en_garde(t):
            return 'stop_guide'
        return 'reperage'

    def robot_muet(self, t=None):
        """Des requêtes sont parties, et aucune réponse depuis delai_muet."""
        t = self.maintenant() if t is None else t
        return self.t_attente is not None and t - self.t_attente >= self.reglages.delai_muet

    def bouge(self):
        """Vrai si le dernier envoi était une consigne non nulle : le robot peut bouger."""
        return not est_nulle(self.derniere)

    def nom_etat(self, t=None):
        """État du schéma etat_pont ; ordre de priorité du contrat (PRIORITE_ETATS_PONT)."""
        t = self.maintenant() if t is None else t
        if self.verrou:
            return 'arret_verrouille'
        if self.robot_muet(t):
            return 'robot_muet'
        if self.en_marche(t) is False:
            return 'pas_en_marche'
        if self.code not in (None, 0):
            return 'refus'
        if self.maitre == 'pilotage':
            return 'pilotage'
        if self.reglages.exiger_reperage and not self.reperage_valable(t):
            return 'attente_reperage'
        if self.en_garde(t):
            return 'arret'
        if self.t_reponse is None:
            return 'demarrage'
        if self.actif and self.bouge() and self.mouvement_permis(t):
            return 'en_mouvement'
        return 'pret'

    def _mode_inconnu(self, t):
        """Phrase à ajouter si le mode reste inconnu depuis 3 s malgré les lectures, sinon ''."""
        if not self.reglages.lire_mode or self.t_premiere_lecture is None \
                or t - self.t_premiere_lecture <= DELAI_MODE_PERIME_S \
                or self.mode_connu(t) is not None:
            return ''
        if self.code_mode not in (None, 0):
            return (f' (Mode du robot inconnu : il refuse la lecture 7001, code '
                    f'{self.code_mode} ; la marche n\'est pas bloquée.)')
        return (' (Mode du robot inconnu : pas de réponse lisible à 7001 ; la marche n\'est '
                'pas bloquée.)')

    def message(self, etat, t):
        if etat == 'arret_verrouille':
            return ('Robot bloqué (arrêt verrouillé) : cliquez sur « Débloquer » pour qu\'il '
                    'puisse repartir.')
        if etat == 'robot_muet':
            return (f'Le robot ne répond plus aux ordres de marche depuis '
                    f'{t - self.t_attente:.1f} s : vérifiez le câble, et que le robot est '
                    f'allumé et debout en mode marche.')
        if etat == 'pas_en_marche':
            return message_pas_en_marche(self.mode)
        if etat == 'refus':
            return message_refus(self.code)
        if etat == 'pilotage':
            return ('Le robot est piloté depuis l\'Atelier (Réel › Piloter) : la navigation ne le '
                    'commande pas tant que la main n\'est pas rendue.')
        if etat == 'attente_reperage':
            if self.t_reperage is None:
                return ('Robot non repéré : cliquez sur « Repérer le robot ». En attendant, '
                        'il ne bouge pas.')
            if not self.repere:
                return ('Robot non repéré (ou repérage perdu) : il ne bouge pas. Cliquez sur '
                        '« Repérer le robot ».')
            return (f'Le repérage ne donne plus de nouvelles depuis {t - self.t_reperage:.1f} s '
                    f': le robot ne bouge pas.')
        if etat == 'arret':
            return (f'Arrêt demandé : le robot attend {self.reglages.garde_stop:g} s avant de '
                    f'pouvoir repartir.')
        if etat == 'demarrage':
            return 'Vérification du lien avec le robot (arrêt envoyé au lancement)…'
        if etat == 'en_mouvement':
            return 'Le robot suit la navigation.' + self._mode_inconnu(t)
        return 'Prêt : le robot attend un ordre de déplacement.' + self._mode_inconnu(t)

    def etat_mode(self, t=None):
        """Champ mode_robot de /pont/etat ; None si la lecture du mode est désactivée."""
        t = self.maintenant() if t is None else t
        if not self.reglages.lire_mode:
            return None
        fsm = self.mode_connu(t)
        return {'fsm': fsm, 'nom': nom_mode(fsm), 'en_marche': self.en_marche(t),
                'age_s': None if self.t_mode is None else round(max(0.0, t - self.t_mode), 3),
                'modes_marche': [int(m) for m in self.reglages.modes_marche],
                'lectures': self.lectures_envoyees}

    def etat(self, t=None):
        """Renvoie le message de /pont/etat, conforme au schéma etat_pont."""
        t = self.maintenant() if t is None else t
        nom = self.nom_etat(t)
        r = self.reglages

        def age(instant):
            return None if instant is None else round(max(0.0, t - instant), 3)

        def vitesses(v):
            return {'vx': round(v[0], 4), 'vy': round(v[1], 4), 'wz': round(v[2], 4)}

        return {
            'version': 1, 'etat': nom, 'message': self.message(nom, t),
            'mouvement_permis': self.mouvement_permis(t),
            'reperage': bool(self.reperage_valable(t)),
            'exiger_reperage': bool(r.exiger_reperage), 'verrou': bool(self.verrou),
            'consigne': vitesses(self.derniere),
            'limites': {'vx': r.vx_max, 'vy': r.vy_max, 'wz': r.wz_max},
            'duree_consigne_s': r.duree_consigne, 'age_cmd_vel_s': age(self.t_cmd_vel),
            'envoyees': self.envoyees, 'reponses': self.reponses,
            'age_reponse_s': age(self.t_reponse), 'code': self.code,
            # vague 5 (section 12.6) : règles 11 et 12
            'demande': vitesses(self.demande),
            'minimums': {'vitesse_min_lin': r.vitesse_min_lin,
                         'vitesse_min_rot': r.vitesse_min_rot,
                         'zone_morte_lin': r.zone_morte_lin, 'zone_morte_rot': r.zone_morte_rot},
            'mode_robot': self.etat_mode(t),
        }

    # ------------------------------------------------------------ envois

    def effective(self, consigne):
        """Consigne plafonnée → consigne envoyée : zones mortes et vitesse minimale (règle 11)."""
        return vitesse_effective(*consigne, plafonds=self.plafonds, minimums=self.minimums,
                                 zones=self.zones)

    def _envoyer(self, t, consigne, raison):
        nulle = est_nulle(consigne)
        if nulle:
            vx = vy = wz = 0.0
            duree = self.reglages.duree_arret
            parametre = parametre_arret(duree)
        else:
            vx, vy, wz = consigne
            duree = self.reglages.duree_consigne
            parametre = parametre_vitesse(vx, vy, wz, duree)
        identifiant = self.identifiants()
        self.envoyes[identifiant] = t
        while len(self.envoyes) > MEMOIRE_IDENTIFIANTS:
            self.envoyes.popitem(last=False)
        self.envoyees += 1
        if self.t_attente is None:
            self.t_attente = t
        self.t_dernier_envoi = t
        self.prochain_envoi = t + 1.0 / self.reglages.frequence
        self.derniere = (vx, vy, wz)
        return Envoi(identifiant, vx, vy, wz, duree, raison, parametre)

    def _arret(self, t, raison):
        """Un arrêt ; la consigne en cours est oubliée."""
        self.actif = False
        self.consigne = (0.0, 0.0, 0.0)
        return self._envoyer(t, (0.0, 0.0, 0.0), raison)

    def _lire_mode(self, t):
        """Une lecture du mode (7001) ; elle ne touche ni aux envois, ni au robot muet."""
        identifiant = self.identifiants()
        self.lectures[identifiant] = t
        while len(self.lectures) > MEMOIRE_LECTURES:
            self.lectures.popitem(last=False)
        self.lectures_envoyees += 1
        self.t_lecture = t
        if self.t_premiere_lecture is None:
            self.t_premiere_lecture = t
        return Envoi(identifiant, 0.0, 0.0, 0.0, 0.0, 'lecture_mode', parametre_lecture_mode(),
                     API_GET_FSM_ID)

    def lecture_due(self, t):
        """Vrai s'il faut lire le mode maintenant : une fois par seconde, service sport vu."""
        if not self.reglages.lire_mode:
            return False
        if self.abonnes <= 0 and self.t_reponse is None:
            return False
        return self.t_lecture is None \
            or t - self.t_lecture >= PERIODE_LECTURE_MODE_S - TOLERANCE_ENVOI_S

    # ------------------------------------------------------------ entrées

    def demarrer(self, abonnes=None):
        """
        Au lancement : un arrêt, qui vérifie le lien avec le robot (voir la règle 9).

        abonnes : nombre d'abonnés vus à /api/sport/request (None : inconnu, l'arrêt part).
        Sans abonné, l'arrêt attend qu'un abonné apparaisse (sur_abonnes) ; robot_muet après
        delai_muet si rien ne répond d'ici là.
        """
        t = self.maintenant()
        self.t_attente = t
        if abonnes is not None:
            self.abonnes = int(abonnes)
            if self.abonnes == 0:
                return []
        return self._verifier_lien(t, 'lancement')

    def _verifier_lien(self, t, raison):
        """Premier arrêt de vérification ; les suivants sont prévus, annulés à la réponse."""
        self.t_verification = t
        self.verifications = [t + i * ECART_VERIFICATION_S for i in range(1, NOMBRE_VERIFICATIONS)]
        # _envoyer ne touche pas à t_attente s'il court déjà : le délai du robot muet compte
        # depuis le lancement (ou depuis la première requête restée sans réponse)
        return [self._arret(t, raison)]

    def sur_abonnes(self, nombre):
        """Abonnés vus à /api/sport/request ; un nouveau peut relancer la vérification du lien."""
        t = self.maintenant()
        nombre = int(nombre)
        nouveau = nombre > self.abonnes
        self.abonnes = nombre
        if not nouveau or self.actif:
            return []
        if self.t_reponse is not None and not self.robot_muet(t):
            return []
        if self.verifications:
            return []                            # vérification déjà en cours
        return self._verifier_lien(t, 'lien')

    def quitter(self):
        """À la sortie (Ctrl+C, SIGTERM) : un arrêt, envoyé avant de quitter."""
        return [self._arret(self.maintenant(), 'sortie')]

    def sur_cmd_vel(self, vx, vy, wz):
        """Nouveau /cmd_vel (Twist : linear.x, linear.y, angular.z)."""
        t = self.maintenant()
        self.t_cmd_vel = t
        self.demande = plafonner(vx, vy, wz, self.reglages)
        if not self.mouvement_permis(t):
            # Ignoré ; si le robot bougeait encore (ne devrait pas arriver), on l'arrête
            if self.bouge():
                return [self._arret(t, 'mouvement_interdit')]
            return []
        consigne = self.effective(self.demande)
        etait_actif = self.actif
        changement = est_nulle(consigne) != est_nulle(self.derniere)
        self.consigne, self.t_consigne, self.actif = consigne, t, True
        if not etait_actif or changement:
            return [self._envoyer(t, consigne, 'consigne')]
        return []

    def sur_guide_stop(self):
        """/guide/stop : arrêt immédiat, puis /cmd_vel ignoré pendant garde_stop."""
        t = self.maintenant()
        self.garde_jusqua = t + self.reglages.garde_stop
        return [self._arret(t, 'stop_guide')]

    def sur_verrou(self, actif):
        """/pont/arret : true verrouille (3 arrêts en 0,2 s), false déverrouille."""
        t = self.maintenant()
        if not actif:
            self.verrou = False
            self.arrets_prevus = []
            self.consigne, self.actif = (0.0, 0.0, 0.0), False
            return []
        self.verrou = True
        self.arrets_prevus = [t + i * ECART_ARRETS_VERROU_S
                              for i in range(1, NOMBRE_ARRETS_VERROU)]
        return [self._arret(t, 'verrou')]

    def sur_maitre(self, maitre):
        """Maître des mouvements (/mouvement/maitre) ; ValueError pour une valeur inconnue."""
        if maitre not in MAITRES:
            raise ValueError(f'maître inconnu « {maitre} » : guide ou pilotage')
        t = self.maintenant()
        ancien, self.maitre = self.maitre, maitre
        if maitre == ancien:
            return []
        if maitre == 'pilotage':
            if self.actif or self.bouge():
                return [self._arret(t, 'pilotage')]
            self.actif = False
            return []
        self.consigne, self.actif = (0.0, 0.0, 0.0), False      # reprise au prochain /cmd_vel
        return []

    def sur_reperage(self, repere):
        """/reperage/etat reçu (champ repere) ; repérage perdu en marche : arrêt tout de suite."""
        t = self.maintenant()
        self.repere = bool(repere)
        self.t_reperage = t
        if self.actif and not self.mouvement_permis(t):
            return [self._arret(t, 'reperage')]
        return []

    def sur_reponse(self, identifiant, code, data='', api_id=None):
        """
        Réponse sur /api/sport/response : 'marche' (à un 7105), 'lecture' (à un 7001), ou False.

        False : elle n'est pas à une de nos requêtes (autre programme du robot). api_id : celui
        de la réponse, s'il est donné et non nul, doit être celui de la requête.
        """
        if identifiant in self.lectures:
            if api_id and int(api_id) != API_GET_FSM_ID:
                return False
            del self.lectures[identifiant]
            self.code_mode = int(code)
            fsm = lire_mode(data) if self.code_mode == 0 else None
            if fsm is None:
                self.mode = None                 # lecture refusée ou illisible : inconnu
            else:
                self.mode, self.t_mode = fsm, self.maintenant()
            return 'lecture'
        if identifiant not in self.envoyes:
            return False
        if api_id and int(api_id) != API_SET_VELOCITY:
            return False
        del self.envoyes[identifiant]
        self.reponses += 1
        self.t_reponse = self.maintenant()
        self.t_attente = None
        self.code = int(code)
        self.verifications = []                  # le lien est vérifié
        return 'marche'

    def pas(self):
        """À appeler souvent (50 Hz) : envois à 10 Hz, chien de garde, arrêts prévus, mode."""
        t = self.maintenant()
        envois = []
        if self.lecture_due(t):
            envois.append(self._lire_mode(t))
        prevus = [a for a in self.arrets_prevus if a <= t]
        if prevus:
            self.arrets_prevus = [a for a in self.arrets_prevus if a > t]
            envois.append(self._arret(t, 'verrou'))
        verifications = [a for a in self.verifications if a <= t]
        if verifications:
            self.verifications = [a for a in self.verifications if a > t]
            if not self.actif:
                envois.append(self._arret(t, 'verification'))
        if not self.actif:
            return envois
        if not self.mouvement_permis(t):
            envois.append(self._arret(t, self._raison_interdit(t)))
        elif t - self.t_consigne >= self.reglages.delai_cmd_vel:
            envois.append(self._arret(t, 'delai_cmd_vel'))
        elif t >= self.prochain_envoi - TOLERANCE_ENVOI_S:
            # Cadence calée sur l'heure prévue (pas sur l'heure réelle) : 10 Hz en moyenne
            prevu = self.prochain_envoi
            envois.append(self._envoyer(t, self.consigne, 'consigne'))
            periode = 1.0 / self.reglages.frequence
            if t - prevu < periode:
                self.prochain_envoi = prevu + periode
        return envois
