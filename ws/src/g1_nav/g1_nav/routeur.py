"""
Routeur du guide : plus court chemin dans le graphe des itinéraires d'un étage.

Le graphe vient de <lieu>/itineraires.yaml (nœuds et couloirs, section 4.1 du plan). Le
routeur cherche le plus court chemin avec A* (la distance à vol d'oiseau sert d'estimation).
Un couloir peut être marqué bloqué pour un temps (120 s par défaut) : le guide le fait
quand le robot reste coincé, et le routeur propose alors un autre chemin.

Aucune dépendance à ROS : ce module se teste avec pytest seul.

    routeur = Routeur.depuis_lieu('demo', 'rdc')
    routeur.itineraire('accueil', 'b204')   # ['accueil', 'hall_nord', 'amphi', ...]
    routeur.bloquer('amphi', 'couloir_nord_1')
"""
import heapq
import math
import time

from atelier import chemin_lieu
from atelier.lieu import charger_itineraires, charger_salles

# Durée pendant laquelle un couloir reste bloqué, en secondes
DUREE_BLOCAGE_S = 120.0


class CibleInconnue(ValueError):
    """La cible demandée n'est ni une salle ni un nœud de l'étage."""


def cle_couloir(a, b):
    """Clé d'un couloir, la même dans les deux sens."""
    return tuple(sorted((a, b)))


class Routeur:
    """Graphe des couloirs d'un étage, avec A* et couloirs bloqués pour un temps."""

    def __init__(self, noeuds, couloirs, salles=None, horloge=time.monotonic):
        """
        Prépare le graphe.

        noeuds   : {id: (x, y)} en mètres, dans le repère map ;
        couloirs : liste de paires (a, b), parcourues dans les deux sens ;
        salles   : {id: {'pose': (x, y, theta), 'alias': [...]}}, facultatif ;
        horloge  : fonction qui donne le temps en secondes (fausse horloge des tests).
        """
        self.noeuds = {i: (float(x), float(y)) for i, (x, y) in noeuds.items()}
        self.voisins = {i: set() for i in self.noeuds}
        for a, b in couloirs:
            if a not in self.noeuds or b not in self.noeuds:
                raise ValueError(f'couloir [{a}, {b}] : nœud inconnu')
            if a != b:
                self.voisins[a].add(b)
                self.voisins[b].add(a)
        self.salles = dict(salles or {})
        self.horloge = horloge
        self._bloques = {}    # clé du couloir -> instant de fin du blocage

    @classmethod
    def depuis_lieu(cls, lieu, etage, horloge=time.monotonic):
        """Charge itineraires.yaml et salles.yaml du lieu, en gardant l'étage demandé."""
        dossier = chemin_lieu(lieu)
        itineraires = charger_itineraires(dossier)
        noeuds = {i: (n.x, n.y) for i, n in itineraires.noeuds.items() if n.etage == etage}
        couloirs = [(c.a, c.b) for c in itineraires.couloirs
                    if c.a in noeuds and c.b in noeuds]
        salles = {s.id: {'pose': (s.pose.x, s.pose.y, s.pose.theta),
                         'alias': list(s.alias), 'nom': s.nom}
                  for s in charger_salles(dossier) if s.etage == etage}
        return cls(noeuds, couloirs, salles, horloge)

    # ------------------------------------------------------------ cibles

    def resoudre(self, cible):
        """
        Renvoie l'id du nœud qui correspond à la cible.

        La cible est un id de salle ou de nœud (section 4.2). À défaut, on accepte un alias
        de salle, sans tenir compte des majuscules. Lève CibleInconnue sinon.
        """
        texte = str(cible).strip()
        if texte in self.noeuds:
            return texte
        bas = texte.lower()
        for id_salle, salle in self.salles.items():
            if id_salle in self.noeuds and bas in (a.lower() for a in salle.get('alias', [])):
                return id_salle
        raise CibleInconnue(f'« {texte} » n\'est ni une salle ni un nœud de cet étage')

    def pose_arrivee(self, noeud, cap_par_defaut=0.0):
        """Pose (x, y, theta) où s'arrêter : celle de la salle s'il y en a une, sinon le nœud."""
        salle = self.salles.get(noeud)
        if salle is not None:
            return tuple(float(v) for v in salle['pose'])
        x, y = self.noeuds[noeud]
        return (x, y, cap_par_defaut)

    def noeud_proche(self, x, y):
        """Id du nœud le plus proche du point (x, y), ou None si le graphe est vide."""
        if not self.noeuds:
            return None
        return min(self.noeuds, key=lambda i: math.dist(self.noeuds[i], (x, y)))

    # ------------------------------------------------------------ couloirs bloqués

    def bloquer(self, a, b, duree=DUREE_BLOCAGE_S):
        """Marque le couloir a-b bloqué pendant duree secondes."""
        if b not in self.voisins.get(a, ()):
            raise ValueError(f'pas de couloir entre « {a} » et « {b} »')
        self._bloques[cle_couloir(a, b)] = self.horloge() + duree

    def debloquer(self, a=None, b=None):
        """Libère le couloir a-b, ou tous les couloirs si a et b sont omis."""
        if a is None:
            self._bloques.clear()
        else:
            self._bloques.pop(cle_couloir(a, b), None)

    def est_bloque(self, a, b):
        """Vrai si le couloir a-b est bloqué en ce moment."""
        fin = self._bloques.get(cle_couloir(a, b))
        if fin is None:
            return False
        if self.horloge() >= fin:
            del self._bloques[cle_couloir(a, b)]
            return False
        return True

    def couloirs_bloques(self):
        """Renvoie les couloirs bloqués en ce moment, avec les secondes restantes."""
        maintenant = self.horloge()
        return [(a, b, fin - maintenant) for (a, b), fin in sorted(self._bloques.items())
                if fin > maintenant]

    # ------------------------------------------------------------ chemins

    def distance(self, a, b):
        """Distance à vol d'oiseau entre deux nœuds, en mètres."""
        return math.dist(self.noeuds[a], self.noeuds[b])

    def longueur(self, itineraire):
        """Longueur d'une suite de nœuds, en mètres."""
        return sum(self.distance(a, b) for a, b in zip(itineraire, itineraire[1:]))

    def itineraire(self, depart, arrivee):
        """
        Plus court chemin de depart à arrivee (A*), en évitant les couloirs bloqués.

        Renvoie la liste des ids, départ et arrivée compris ([depart] si ce sont les mêmes),
        ou None s'il n'existe aucun chemin libre. Lève CibleInconnue pour un nœud inconnu.
        """
        for n in (depart, arrivee):
            if n not in self.noeuds:
                raise CibleInconnue(f'nœud inconnu : « {n} »')
        if depart == arrivee:
            return [depart]
        # File de priorité : (coût estimé total, coût depuis le départ, nœud)
        ouverts = [(self.distance(depart, arrivee), 0.0, depart)]
        meilleurs = {depart: 0.0}
        precedents = {}
        while ouverts:
            _, cout, noeud = heapq.heappop(ouverts)
            if noeud == arrivee:
                chemin = [noeud]
                while chemin[-1] in precedents:
                    chemin.append(precedents[chemin[-1]])
                return chemin[::-1]
            if cout > meilleurs.get(noeud, math.inf):
                continue    # entrée périmée de la file
            for voisin in sorted(self.voisins[noeud]):
                if self.est_bloque(noeud, voisin):
                    continue
                nouveau = cout + self.distance(noeud, voisin)
                if nouveau < meilleurs.get(voisin, math.inf):
                    meilleurs[voisin] = nouveau
                    precedents[voisin] = noeud
                    heapq.heappush(ouverts,
                                   (nouveau + self.distance(voisin, arrivee), nouveau, voisin))
        return None

    def poses(self, itineraire, sauter_depart=False):
        """
        Poses (x, y, theta) à donner au moteur pour suivre l'itinéraire.

        Chaque nœud est tourné vers le suivant ; la dernière pose est celle de la salle (ou
        le nœud, tourné dans le sens de la marche). sauter_depart : le premier nœud est omis
        (le robot est déjà sur le premier couloir), sauf si l'itinéraire n'a qu'un nœud.
        """
        poses = []
        cap = 0.0
        for i, noeud in enumerate(itineraire):
            x, y = self.noeuds[noeud]
            if i + 1 < len(itineraire):
                xs, ys = self.noeuds[itineraire[i + 1]]
                cap = math.atan2(ys - y, xs - x)
                poses.append((x, y, cap))
            else:
                poses.append(self.pose_arrivee(noeud, cap))
        if sauter_depart and len(poses) > 1:
            poses = poses[1:]
        return poses
