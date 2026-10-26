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
     n'envoie rien en continu.
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

Un /cmd_vel ignoré (garde, verrou, repérage, pilotage) n'est pas gardé : il ne sert pas plus tard.
"""
from collections import OrderedDict, namedtuple
from dataclasses import dataclass, fields
import math
import time

from .requete import (DUREE_ARRET_S, Identifiants, parametre_arret, parametre_vitesse)

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
# Un envoi périodique part au premier pas() qui tombe à moins de ce temps avant son heure
# (pas() est appelé toutes les 20 ms par le nœud : la cadence reste de 10 Hz malgré le jitter)
TOLERANCE_ENVOI_S = 0.008

# 'pilotage' (vague 4, section 11.5 du plan) : le pilotage de l'Atelier a la main
# (/mouvement/maitre), /cmd_vel est ignoré (règle 10)
MAITRES = ('guide', 'pilotage')
ETATS = ('demarrage', 'attente_reperage', 'pret', 'en_mouvement', 'arret', 'arret_verrouille',
         'robot_muet', 'refus', 'pilotage')

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

    @classmethod
    def noms(cls):
        return [f.name for f in fields(cls)]

    def verifier(self):
        """Lève ErreurReglages si un réglage est dangereux ou absurde ; renvoie self sinon."""
        erreurs = []
        for nom in self.noms():
            valeur = getattr(self, nom)
            if nom == 'exiger_reperage':
                if not isinstance(valeur, bool):
                    erreurs.append(f'exiger_reperage doit valoir true ou false, pas {valeur!r}')
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
        if erreurs:
            raise ErreurReglages(' ; '.join(erreurs))
        return self


# Une requête 7105 à publier : identity.id, vitesses envoyées, duration, raison, texte JSON
Envoi = namedtuple('Envoi', 'identifiant vx vy wz duree raison parametre')


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


def message_refus(code):
    """Phrase en français pour un code de refus du service sport."""
    conseil = MESSAGES_REFUS.get(code, 'vérifiez son mode avec la télécommande')
    return f'Le robot refuse de marcher (code {code}) : {conseil}.'


class Pont:
    """Règles du pont ; chaque entrée renvoie la liste des requêtes (Envoi) à publier."""

    def __init__(self, reglages=None, horloge=time.monotonic, identifiants=None):
        self.reglages = (reglages or Reglages()).verifier()
        self.horloge = horloge
        self.identifiants = identifiants or Identifiants()
        # Consigne acceptée en cours (plafonnée) et instant de sa réception
        self.consigne = (0.0, 0.0, 0.0)
        self.t_consigne = None
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

    def mouvement_permis(self, t=None):
        """Vrai si un /cmd_vel non nul reçu maintenant serait envoyé au robot."""
        t = self.maintenant() if t is None else t
        if self.verrou or self.en_garde(t) or self.maitre == 'pilotage':
            return False
        return self.reperage_valable(t) or not self.reglages.exiger_reperage

    def robot_muet(self, t=None):
        """Des requêtes sont parties, et aucune réponse depuis delai_muet."""
        t = self.maintenant() if t is None else t
        return self.t_attente is not None and t - self.t_attente >= self.reglages.delai_muet

    def bouge(self):
        """Vrai si le dernier envoi était une consigne non nulle : le robot peut bouger."""
        return not est_nulle(self.derniere)

    def nom_etat(self, t=None):
        """État du schéma etat_pont ; ordre de priorité du contrat."""
        t = self.maintenant() if t is None else t
        if self.verrou:
            return 'arret_verrouille'
        if self.robot_muet(t):
            return 'robot_muet'
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

    def message(self, etat, t):
        if etat == 'arret_verrouille':
            return ('Robot bloqué (arrêt verrouillé) : cliquez sur « Débloquer » pour qu\'il '
                    'puisse repartir.')
        if etat == 'robot_muet':
            return (f'Le robot ne répond plus aux ordres de marche depuis '
                    f'{t - self.t_attente:.1f} s : vérifiez le câble, et que le robot est '
                    f'allumé et debout en mode marche.')
        if etat == 'refus':
            return message_refus(self.code)
        if etat == 'pilotage':
            return ('Le robot est piloté depuis l\'onglet Pilotage : la navigation ne le commande '
                    'pas (/cmd_vel ignoré) tant que la main n\'est pas rendue.')
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
            return 'Le robot suit la navigation.'
        return 'Prêt : le robot attend un ordre de déplacement.'

    def etat(self, t=None):
        """Renvoie le message de /pont/etat, conforme au schéma etat_pont."""
        t = self.maintenant() if t is None else t
        nom = self.nom_etat(t)
        r = self.reglages

        def age(instant):
            return None if instant is None else round(max(0.0, t - instant), 3)

        vx, vy, wz = self.derniere
        return {
            'version': 1, 'etat': nom, 'message': self.message(nom, t),
            'mouvement_permis': self.mouvement_permis(t),
            'reperage': bool(self.reperage_valable(t)),
            'exiger_reperage': bool(r.exiger_reperage), 'verrou': bool(self.verrou),
            'consigne': {'vx': round(vx, 4), 'vy': round(vy, 4), 'wz': round(wz, 4)},
            'limites': {'vx': r.vx_max, 'vy': r.vy_max, 'wz': r.wz_max},
            'duree_consigne_s': r.duree_consigne, 'age_cmd_vel_s': age(self.t_cmd_vel),
            'envoyees': self.envoyees, 'reponses': self.reponses,
            'age_reponse_s': age(self.t_reponse), 'code': self.code,
        }

    # ------------------------------------------------------------ envois

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
        if not self.mouvement_permis(t):
            # Ignoré ; si le robot bougeait encore (ne devrait pas arriver), on l'arrête
            if self.bouge():
                return [self._arret(t, 'mouvement_interdit')]
            return []
        consigne = plafonner(vx, vy, wz, self.reglages)
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

    def sur_reponse(self, identifiant, code):
        """Réponse sur /api/sport/response ; False si elle n'est pas à une de nos requêtes."""
        if identifiant not in self.envoyes:
            return False
        del self.envoyes[identifiant]
        self.reponses += 1
        self.t_reponse = self.maintenant()
        self.t_attente = None
        self.code = int(code)
        self.verifications = []                  # le lien est vérifié
        return True

    def pas(self):
        """À appeler souvent (50 Hz) : envois à 10 Hz, chien de garde, arrêts prévus."""
        t = self.maintenant()
        envois = []
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
            envois.append(self._arret(t, 'reperage'))
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
