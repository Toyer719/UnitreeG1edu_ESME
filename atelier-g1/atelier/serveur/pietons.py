"""Position des piétons pendant la simulation, pour l'affichage en direct.

Vague 4 (section 11.3 du plan) : avec les piétons crédibles (pietons:=corps, le défaut de g1_sim),
le nœud pietons publie leurs positions vraies sur /pietons/etat, et l'écran les prend là
(atelier/serveur/etat.py). Ce module ne sert plus que sans /pietons/etat frais (pietons:=acteurs,
ou simulation d'avant la vague 4).

Les piétons de Gazebo (<actor>) suivent leur horaire depuis le temps simulé 0 (contrat 4.1) :
départ à trajet[0] ; aller_retour vrai : va-et-vient ; faux : boucle, avec retour direct du
dernier point au premier ; vague 4 : pauses, départ différé et un seul parcours
(atelier.monde.pietons). On recalcule donc leur position à partir du monde et du temps simulé
(/clock), sans sujet ROS supplémentaire.

Le calcul de référence est celui de l'agent Monde (atelier.monde.pietons.position_pieton), qui
écrit aussi les points de passage du SDF : l'écran montre donc ce que fait Gazebo. S'il manque,
position_simple() fait le même calcul en ligne droite.
"""
import math

try:
    from atelier.monde.pietons import position_pieton as _position_monde
except ImportError:          # atelier.monde absent ou incomplet : on garde le calcul simple
    _position_monde = None


def _circuit(pieton):
    """Liste des points parcourus pendant un tour complet, retour au départ compris."""
    trajet = [tuple(p) for p in pieton.trajet]
    if len(trajet) < 2:
        return trajet
    if pieton.aller_retour:
        return trajet + trajet[-2::-1]
    return trajet + [trajet[0]]


def position_simple(pieton, t):
    """(x, y, theta) du piéton au temps t (s), theta = direction de marche."""
    points = _circuit(pieton)
    if len(points) < 2:
        x, y = points[0] if points else (0.0, 0.0)
        return (float(x), float(y), 0.0)
    longueurs = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:])]
    total = sum(longueurs)
    if total <= 0 or pieton.vitesse <= 0:
        return (float(points[0][0]), float(points[0][1]), 0.0)
    s = (pieton.vitesse * max(t, 0.0)) % total
    for (a, b), l in zip(zip(points, points[1:]), longueurs):
        if s <= l and l > 0:
            k = s / l
            return (a[0] + k * (b[0] - a[0]), a[1] + k * (b[1] - a[1]),
                    math.atan2(b[1] - a[1], b[0] - a[0]))
        s -= l
    a, b = points[-2], points[-1]
    return (float(b[0]), float(b[1]), math.atan2(b[1] - a[1], b[0] - a[0]))


def position_pieton(pieton, t):
    """(x, y, theta) du piéton au temps t, avec le calcul de l'agent Monde s'il est là."""
    if _position_monde is not None:
        try:
            x, y, theta = _position_monde(pieton, max(t, 0.0))
            return (float(x), float(y), float(theta))
        except Exception:       # noqa: BLE001 : l'affichage ne doit jamais tomber pour un piéton
            pass
    return position_simple(pieton, t)


def positions_pietons(monde, t):
    """[{id, x, y, theta}] de tous les piétons du monde au temps t."""
    if monde is None or t is None:
        return []
    resultat = []
    for p in monde.pietons:
        x, y, theta = position_pieton(p, t)
        resultat.append({"id": p.id, "x": round(x, 3), "y": round(y, 3), "theta": round(theta, 3)})
    return resultat
