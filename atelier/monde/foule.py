"""Foule simulée : le mouvement des piétons crédibles de g1_sim (vague 4, section 11.3 du plan).

Sans ROS ni Gazebo : le nœud pietons de g1_sim (ws/src/g1_sim/scripts/pietons.py) lit la position
vraie de chaque piéton-corps et du robot, appelle Foule.pas() 20 fois par seconde, puis envoie à
chaque corps la vitesse rendue (plugin VelocityControl de Gazebo) et publie /pietons/etat.

Un piéton suit son horaire (atelier.monde.pietons : trajet, pauses, départ, répétition). Il a un
« avancement » dans cet horaire, qui suit le temps de la scène tant que rien ne le gêne, et qui
ralentit ou s'arrête quand il réagit au robot. Réaction (champ reaction, défaut ecart), quand le
robot est à moins de distance_reaction_m bord à bord, devant lui (±60° autour de sa direction) :
  - arret : il s'arrête, et repart 1 s après que le robot s'est éloigné (au-delà de
    distance_reaction_m, de quelque côté qu'il soit) ;
  - ecart : il ralentit à 0,5 m/s et s'écarte de 0,6 m au plus, du côté opposé au robot (à droite si
    le robot arrive droit devant), dans l'espace libre de la carte du monde ; s'il ne peut pas
    s'écarter d'au moins 0,15 m, il s'arrête. Il revient sur son trajet 1 s après que le robot
    s'est éloigné (au-delà de distance_reaction_m + 0,4 m) ;
  - aucune : il ne voit pas le robot (scènes « pire cas »).
Un piéton « pilote: externe » ne suit pas d'horaire : il suit /pietons/consigne ({vx, vy, theta?},
valable 0,5 s, 1,5 m/s au plus) et s'arrête devant un mur.

Les vitesses rendues sont dans le repère map (celui du monde Gazebo) : vitesse prévue par l'horaire,
plus un rappel vers la position prévue (le corps a pu être poussé par le robot).
"""
import math
from dataclasses import dataclass

import numpy as np

from atelier.lieu import monde_vers_pixel
from atelier.lieu.passants import (DUREE_CONSIGNE_S, RAYON_ROBOT_CONTACT, VITESSE_PIETON_MAX, distance_bord,
                                   reglages_pieton)

from .carte import LIBRE, fabriquer_carte
from .pietons import etat_horaire, etat_prevu, horaire

ANGLE_DEVANT = math.radians(60.0)   # le piéton voit le robot dans ce demi-angle autour de sa direction
DELAI_REPRISE_S = 1.0               # il repart (ou revient sur son trajet) 1 s après que le robot s'est éloigné
VITESSE_ECART = 0.5                 # m/s : vitesse de marche pendant un écart
ECART_MAX_M = 0.6                   # m : écart au plus, sur le côté
ECART_MIN_M = 0.15                  # m : s'il ne peut pas s'écarter autant, il s'arrête
PAS_ECART_M = 0.05
VITESSE_LATERALE = 0.6              # m/s : il s'écarte à cette vitesse
VITESSE_RETOUR = 0.4                # m/s : il revient sur son trajet à cette vitesse
MARGE_ECART_M = 0.4                 # l'écart dure tant que le robot est à moins de distance_reaction_m + 0,4 m
GAIN_RAPPEL = 2.0                   # 1/s : rappel vers la position prévue
MARGE_MUR_M = 0.05                  # m : distance gardée aux murs et aux objets de la carte
ANTICIPATION_MUR_S = 0.25           # s : il s'arrête si cette avance le mettrait dans un mur


@dataclass
class Commande:
    """Ce qu'un piéton doit faire maintenant : vitesse (repère map), direction, état, cible."""
    vx: float
    vy: float
    theta: float
    etat: str
    cible: tuple


class CarteLibre:
    """Espace libre d'un monde, pour un piéton : la carte 2D du monde (murs et objets, tranche de
    0,1 à 1,5 m, sans les piétons ni les personnes), comme Nav2 la voit. Hors de l'emprise : occupé."""

    def __init__(self, monde=None, info=None, image=None):
        if monde is not None:
            info, image = fabriquer_carte(monde)
        self.info = info
        self.occupe = np.asarray(image) != LIBRE
        self._disques = {}

    def _disque(self, r):
        if r not in self._disques:
            i, j = np.mgrid[-r:r + 1, -r:r + 1]
            self._disques[r] = (i * i + j * j) <= (r + 0.5) ** 2
        return self._disques[r]

    def encombrement(self, x, y, rayon):
        """Nombre de pixels occupés que touche un disque de ce rayon (m) centré en (x, y) ; hors de
        la carte, tout le disque compte comme occupé."""
        colonne, ligne = monde_vers_pixel(x, y, self.info)
        r = int(math.ceil(rayon / self.info.resolution))
        disque = self._disque(r)
        h, w = self.occupe.shape
        if ligne - r < 0 or colonne - r < 0 or ligne + r >= h or colonne + r >= w:
            return int(disque.sum())
        fenetre = self.occupe[ligne - r:ligne + r + 1, colonne - r:colonne + r + 1]
        return int(np.count_nonzero(fenetre & disque))

    def libre(self, x, y, rayon):
        """Vrai si un disque de ce rayon (m) centré en (x, y) ne touche aucun pixel occupé."""
        return self.encombrement(x, y, rayon) == 0


def _norme(vx, vy, plafond):
    n = math.hypot(vx, vy)
    if n > plafond > 0:
        return vx * plafond / n, vy * plafond / n
    return vx, vy


def _angle(a):
    return math.atan2(math.sin(a), math.cos(a))


class Passant:
    """Un piéton crédible : son horaire, son avancement, sa réaction au robot, sa consigne externe."""

    def __init__(self, pieton, carte=None, rayon_robot=RAYON_ROBOT_CONTACT):
        self.pieton = pieton
        self.id = pieton.id
        self.reglages = reglages_pieton(pieton)
        self.rayon = float(self.reglages["rayon_m"])
        self.externe = self.reglages["pilote"] == "externe"
        self.horaire = horaire(pieton)
        self.carte = carte
        self.rayon_robot = rayon_robot
        self.plafond = max(VITESSE_PIETON_MAX, 1.3 * float(pieton.vitesse))
        self.reinitialiser()

    def reinitialiser(self):
        """Retour au début de la scène : trajet[0], avancement nul, aucune réaction."""
        self.avancement = 0.0
        self.ecart = (0.0, 0.0)
        self.reaction = None            # {cote, normale, derniere} pendant une réaction
        self.consigne = None            # (vx, vy, theta, t) d'un piéton piloté
        x, y = self.pieton.trajet[0]
        self.cible = (float(x), float(y))
        self.theta = self.horaire.cap_depart
        self.etat = "pilote" if self.externe else etat_horaire(self.horaire, 0.0)[5]

    def consigner(self, vx, vy, theta, t):
        """Consigne d'un piéton « pilote: externe » (repère map), reçue au temps t de la scène."""
        vx, vy = _norme(float(vx), float(vy), VITESSE_PIETON_MAX)
        self.consigne = (vx, vy, theta, t)

    def _libre(self, x, y, rayon=None):
        if self.carte is None:
            return True
        return self.carte.libre(x, y, (self.rayon if rayon is None else rayon) + MARGE_MUR_M)

    # ------------------------------------------------------------ réaction au robot

    def _voit(self, position, direction, robot):
        """(devant, distance bord à bord) : le robot est-il devant lui (±60°), et à quelle distance."""
        d = distance_bord(robot, position, self.rayon, self.rayon_robot)
        vers = math.atan2(robot[1] - position[1], robot[0] - position[0])
        return abs(_angle(vers - direction)) <= ANGLE_DEVANT, d

    def _suivre_reaction(self, t, position, direction, robot):
        """Met à jour la réaction en cours ; renvoie son type (arret, ecart) ou None."""
        genre = self.reglages["reaction"]
        if genre == "aucune" or robot is None:
            self.reaction = None
            return None
        devant, d = self._voit(position, direction, robot)
        seuil = float(self.reglages["distance_reaction_m"])
        if self.reaction is None:
            if not (devant and d < seuil):
                return None
            croix = math.cos(direction) * (robot[1] - position[1]) - math.sin(direction) * (robot[0] - position[0])
            # robot à gauche (croix > 0) : il s'écarte à droite ; droit devant : à droite aussi
            cote = 1.0 if croix < -1e-3 else -1.0
            self.reaction = {"cote": cote, "normale": (-math.sin(direction), math.cos(direction)), "derniere": t}
            return genre
        tenue = seuil + (MARGE_ECART_M if genre == "ecart" else 0.0)
        if d < tenue:
            self.reaction["derniere"] = t
        elif t - self.reaction["derniere"] > DELAI_REPRISE_S:
            self.reaction = None
            return None
        return genre

    def _ecart_possible(self, base):
        """Plus grand écart libre (m, ECART_MAX_M au plus) du côté choisi, depuis le point prévu."""
        nx, ny = self.reaction["normale"]
        cote = self.reaction["cote"]
        o = ECART_MAX_M
        while o >= ECART_MIN_M - 1e-9:
            if self._libre(base[0] + cote * nx * o, base[1] + cote * ny * o):
                return o
            o -= PAS_ECART_M
        return 0.0

    # ------------------------------------------------------------ un pas

    def pas(self, t, dt, position=None, robot=None):
        """Un pas de dt secondes au temps t de la scène. position : (x, y) vraie du corps (None :
        on la suppose à sa cible) ; robot : (x, y, ...) du robot, ou None. Renvoie une Commande."""
        position = tuple(position[:2]) if position is not None else self.cible
        if self.externe:
            return self._pas_externe(t, position)
        dt = max(0.0, float(dt))
        x, y, cap, vx, vy, etat = etat_horaire(self.horaire, self.avancement)
        genre = self._suivre_reaction(t, position, cap, robot)
        rythme, ecart_voulu, arret = 1.0, (0.0, 0.0), False
        if genre == "arret":
            arret = True
        elif genre == "ecart":
            o = self._ecart_possible((x, y))
            deja = math.hypot(*self.ecart)
            if o <= 0.0 and deja < ECART_MIN_M:
                arret = True
            else:
                nx, ny = self.reaction["normale"]
                o = max(o, deja)
                ecart_voulu = (self.reaction["cote"] * nx * o, self.reaction["cote"] * ny * o)
                if etat == "marche" and self.pieton.vitesse > VITESSE_ECART:
                    rythme = VITESSE_ECART / self.pieton.vitesse
        if arret:
            # il s'arrête là où il est (même s'il a été poussé) ; son avancement attend
            self.cible = position
            self.etat = "arret"
            return Commande(0.0, 0.0, self.theta, "arret", self.cible)
        cible_maintenant = self.cible      # position prévue à l'instant t (calculée au pas d'avant)
        # écart : vers l'écart voulu en s'écartant, vers zéro en revenant (si c'est libre)
        ex, ey = self.ecart
        dx, dy = ecart_voulu[0] - ex, ecart_voulu[1] - ey
        vitesse = VITESSE_LATERALE if genre == "ecart" else VITESSE_RETOUR
        pas_max = vitesse * dt
        n = math.hypot(dx, dy)
        if n > pas_max > 0:
            dx, dy = dx * pas_max / n, dy * pas_max / n
        self.avancement += dt * rythme
        x2, y2, cap2, vx2, vy2, etat2 = etat_horaire(self.horaire, self.avancement)
        nouveau = (ex + dx, ey + dy)
        if genre is None and not self._libre(x2 + nouveau[0], y2 + nouveau[1]):
            nouveau = self.ecart          # le retour n'est pas libre : il garde son écart
        vex, vey = ((nouveau[0] - ex) / dt, (nouveau[1] - ey) / dt) if dt > 0 else (0.0, 0.0)
        self.ecart = nouveau
        self.cible = (x2 + nouveau[0], y2 + nouveau[1])
        # vitesse prévue, plus le rappel vers la position prévue de l'instant présent : le corps la suit
        # sans retard ni avance, et revient sur son trajet s'il a été poussé. Pas de garde des murs : le
        # trajet est dans l'espace libre (dessiné), et l'écart a été choisi libre.
        cvx = vx2 * rythme + vex + GAIN_RAPPEL * (cible_maintenant[0] - position[0])
        cvy = vy2 * rythme + vey + GAIN_RAPPEL * (cible_maintenant[1] - position[1])
        cvx, cvy = _norme(cvx, cvy, self.plafond)
        self.theta = cap2
        self.etat = "ecart" if genre == "ecart" else etat2
        return Commande(cvx, cvy, self.theta, self.etat, self.cible)

    def _sans_mur(self, position, vx, vy):
        """Vitesse nulle si elle le mettait dans un mur ou un objet de la carte (contre un mur, il
        peut le longer ou s'en éloigner, jamais s'y enfoncer)."""
        if (vx == 0.0 and vy == 0.0) or self.carte is None:
            return vx, vy
        rayon = self.rayon + MARGE_MUR_M
        devant = self.carte.encombrement(position[0] + vx * ANTICIPATION_MUR_S,
                                         position[1] + vy * ANTICIPATION_MUR_S, rayon)
        if devant == 0 or devant <= self.carte.encombrement(position[0], position[1], rayon):
            return vx, vy
        return 0.0, 0.0

    def _pas_externe(self, t, position):
        vx = vy = 0.0
        if self.consigne is not None and t - self.consigne[3] <= DUREE_CONSIGNE_S + 1e-9:
            vx, vy, theta, _ = self.consigne
            if theta is not None:
                self.theta = float(theta)
            elif math.hypot(vx, vy) > 0.05:
                self.theta = math.atan2(vy, vx)
        vx, vy = self._sans_mur(position, vx, vy)
        self.cible = position
        self.etat = "pilote"
        return Commande(vx, vy, self.theta, "pilote", position)


class Foule:
    """Tous les piétons d'un monde. Les piétons-corps sont conduits (pas) ; les autres (<actor>)
    suivent leur horaire dans Gazebo, et ne sont qu'annoncés dans /pietons/etat."""

    def __init__(self, monde, corps=None, carte=None):
        self.monde = monde
        self.carte = carte if carte is not None else CarteLibre(monde)
        ids_corps = [p.id for p in monde.pietons if reglages_pieton(p)["corps"]] if corps is None else list(corps)
        self.passants = {p.id: Passant(p, self.carte) for p in monde.pietons if p.id in ids_corps}
        self.acteurs = [p for p in monde.pietons if p.id not in self.passants]

    def reinitialiser(self):
        for passant in self.passants.values():
            passant.reinitialiser()

    def consigner(self, ident, vx, vy, theta, t):
        """Consigne d'un piéton piloté ; ValueError en français si ce n'est pas possible."""
        passant = self.passants.get(ident)
        if passant is None:
            raise ValueError(f"/pietons/consigne : pas de piéton-corps « {ident} » dans ce monde")
        if not passant.externe:
            raise ValueError(f"/pietons/consigne : le piéton « {ident} » suit son trajet (il n'a pas pilote: externe)")
        passant.consigner(vx, vy, theta, t)

    def pas(self, t, dt, positions, robot=None):
        """{id: Commande} des piétons-corps. positions : {id: (x, y)} vraies (absentes : supposées à la cible)."""
        return {ident: passant.pas(t, dt, positions.get(ident), robot) for ident, passant in self.passants.items()}

    def message_etat(self, temps_sim, t_scene, mesures):
        """Message /pietons/etat (schéma pietons_etat). mesures : {id: (x, y, vx, vy)} vraies des corps ;
        temps_sim : temps simulé (les <actor> de Gazebo suivent leur horaire depuis 0)."""
        pietons = []
        for p in self.monde.pietons:
            reglages = reglages_pieton(p)
            passant = self.passants.get(p.id)
            if passant is not None:
                x, y, vx, vy = mesures.get(p.id) or (*passant.cible, 0.0, 0.0)
                theta, etat = passant.theta, passant.etat
            else:
                x, y, theta, vx, vy, etat = etat_prevu(p, temps_sim or 0.0)
            pietons.append({"id": p.id, "x": round(float(x), 3), "y": round(float(y), 3),
                            "theta": round(_angle(float(theta)), 4),
                            "vx": round(max(-3.0, min(3.0, float(vx))), 3),
                            "vy": round(max(-3.0, min(3.0, float(vy))), 3),
                            "rayon_m": float(reglages["rayon_m"]), "etat": etat,
                            "reaction": reglages["reaction"], "corps": passant is not None})
        return {"version": 1, "temps_sim": None if temps_sim is None else round(max(0.0, float(temps_sim)), 3),
                "temps_scene": round(max(0.0, float(t_scene)), 3), "pietons": pietons}


def lire_consigne(texte):
    """Consigne /pietons/consigne (JSON, schéma pietons_consigne) → (id, vx, vy, theta ou None).
    ValueError en français si elle est illisible ou hors du schéma."""
    import json

    from atelier.lieu import valider_message
    try:
        donnees = json.loads(texte)
    except (TypeError, ValueError):
        raise ValueError("/pietons/consigne : ce n'est pas du JSON") from None
    erreurs = valider_message("pietons_consigne", donnees)
    if erreurs:
        raise ValueError("; ".join(erreurs))
    return donnees["id"], float(donnees["vx"]), float(donnees["vy"]), donnees.get("theta")


def vitesse_dans_le_corps(vx, vy, lacet):
    """Vitesse du repère map → repère du corps (VelocityControl prend la vitesse dans le corps)."""
    c, s = math.cos(lacet), math.sin(lacet)
    return c * vx + s * vy, -s * vx + c * vy


def vitesse_dans_la_carte(vx, vy, lacet):
    """Vitesse du repère du corps (odométrie de Gazebo) → repère map."""
    c, s = math.cos(lacet), math.sin(lacet)
    return c * vx - s * vy, s * vx + c * vy


__all__ = ["Foule", "Passant", "CarteLibre", "Commande", "lire_consigne", "vitesse_dans_le_corps",
           "vitesse_dans_la_carte", "ANGLE_DEVANT", "DELAI_REPRISE_S", "VITESSE_ECART", "ECART_MAX_M",
           "ECART_MIN_M"]
