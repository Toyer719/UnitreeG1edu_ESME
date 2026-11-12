"""Relais vers la voix (vague 4, section 11.6 du plan), sans ROS : ce que le robot dit de lui-même.

EXEMPLE, utilisé par le nœud dialogue (paquet g1_equipe), que l'équipe remplacera ou complétera.

  - Relais : un événement du guide (/guide/evenement, schéma evenement_guide) → la phrase à dire
    (/robot/dire, schéma robot_dire), avec les phrases de la personnalité active
    (personnalites.yaml : phrases, par code d'événement) :
      * le texte de la personnalité remplace celui du guide pour ce code ({nom} : nom de la salle) ;
      * sauf pour l'arrivée dans une salle qui a sa propre phrase_arrivee (salles.yaml) : le guide
        l'a mise dans l'événement, et elle est plus précise (« Frappez avant d'entrer ») ;
      * « depart » est tu s'il suit de moins de taire_depart_s une demande du chatbot vers la même
        salle : le chatbot vient de dire « Je vous emmène à … » (pas de phrase en double) ;
      * « arret » part en priorité haute (il coupe la phrase en cours).
  - Salueur : un visiteur vu par la caméra (/visiteurs/detectes, schéma personnes), proche et
    tourné vers le robot, alors que le guide est au repos → la salutation de la personnalité
    active, une fois par visiteur et pas plus d'une fois toutes les delai_s.

Horloge injectable (tests) : horloge() rend des secondes croissantes.
"""
import time

from atelier.lieu.comportement import CODES_EVENEMENT, texte_evenement, texte_par_defaut
from atelier.lieu.equipe import message_robot_dire

PRIORITE_HAUTE = frozenset({"arret"})
TAIRE_DEPART_S = 10.0
ETATS_REPOS = (None, "attente")          # au repos au point principal (ou sans guide : essais)


class Relais:
    """Événements du guide → messages de /robot/dire."""

    def __init__(self, taire_depart_s=TAIRE_DEPART_S, horloge=time.monotonic):
        self.taire_depart_s = taire_depart_s
        self.horloge = horloge
        self._guidage = None            # (cible demandée par le chatbot, instant)

    def noter_guidage(self, cible):
        """Le chatbot vient de demander au guide d'aller à cible (et l'a annoncé au visiteur)."""
        self._guidage = (cible, self.horloge())

    def texte(self, evenement, personnalite=None):
        """Texte à dire pour un événement, ou None s'il faut se taire."""
        code = evenement.get("code")
        if code == "depart" and self._guidage is not None:
            cible, instant = self._guidage
            if cible == evenement.get("salle") and self.horloge() - instant <= self.taire_depart_s:
                self._guidage = None
                return None
        phrases = (personnalite or {}).get("phrases") or {}
        du_guide = evenement.get("texte")
        nom = evenement.get("nom")
        if code in phrases and code in CODES_EVENEMENT:
            propre = code == "arrivee" and du_guide and not texte_par_defaut("arrivee", du_guide, nom)
            if not propre:
                return texte_evenement(code, nom, phrases)
        if du_guide and texte_par_defaut(code, du_guide, nom):
            # un texte par défaut, peut-être celui d'avant (image du Jetson pas encore refaite) : celui d'aujourd'hui
            return texte_evenement(code, nom)
        if du_guide:
            return du_guide
        return texte_evenement(code, evenement.get("nom")) if code in CODES_EVENEMENT else None

    def message(self, evenement, personnalite=None):
        """Message de /robot/dire pour un événement du guide, ou None (rien à dire)."""
        texte = self.texte(evenement, personnalite)
        if not texte:
            return None
        code = evenement.get("code")
        return message_robot_dire(texte, "guide", code=code,
                                  priorite="haute" if code in PRIORITE_HAUTE else "normale", personnalite=personnalite)


class Salueur:
    """Salue un visiteur vu par la caméra, quand le guide est au repos."""

    def __init__(self, distance_m=1.5, vu_s=1.0, delai_s=30.0, horloge=time.monotonic):
        self.distance_m = distance_m
        self.vu_s = vu_s
        self.delai_s = delai_s
        self.horloge = horloge
        self._vus = {}              # id de suivi → instant où il est entré dans la zone
        self._salues = set()
        self._dernier = None

    def recevoir(self, message, etat_guide=None, personnalite=None):
        """message : /visiteurs/detectes (dict). Renvoie le message de /robot/dire à publier, ou None."""
        maintenant = self.horloge()
        proches = set()
        for p in (message or {}).get("personnes") or []:
            try:
                ident, distance = int(p["id"]), float(p["distance_m"])
            except (KeyError, TypeError, ValueError):
                continue
            if distance <= self.distance_m and p.get("regarde_robot", True) is not False:
                proches.add(ident)
                self._vus.setdefault(ident, maintenant)
        for ident in list(self._vus):
            if ident not in proches:
                del self._vus[ident]          # sorti de la zone : il recommencera à compter
        etat = (etat_guide or {}).get("etat")
        if not personnalite or not personnalite.get("salutation") or etat not in ETATS_REPOS:
            return None
        if self._dernier is not None and maintenant - self._dernier < self.delai_s:
            return None
        prets = [i for i, t in self._vus.items() if maintenant - t >= self.vu_s and i not in self._salues]
        if not prets:
            return None
        self._salues.update(prets)
        if len(self._salues) > 1000:
            self._salues = set(prets)
        self._dernier = maintenant
        return message_robot_dire(personnalite["salutation"], "personnalite", personnalite=personnalite)


__all__ = ["ETATS_REPOS", "PRIORITE_HAUTE", "Relais", "Salueur", "TAIRE_DEPART_S"]
