"""Plan du sol d'un nuage de scan (vague 5, section 12.5 du plan) : RANSAC à graine fixe, puis moindres carrés.

Dans le repère map du vrai G1, le sol n'est pas horizontal : ce repère part de l'IMU du LiDAR au départ
du scan, un peu penché (0,58° le 27/10, soit 1 cm par mètre). Un seul niveau de sol (l'ancien 1er
centile des z) faisait entrer le sol de la moitié du bâtiment dans la tranche des obstacles : le
« damier » noir de la carte 2D. On ajuste donc un plan z = a·x + b·y + c, et l'on travaille en
hauteur au-dessus de ce plan. On soustrait le plan, on ne tourne pas le nuage : x et y restent
exactement ceux du repère map (les salles déjà placées restent justes).

    sol = trouver_sol(points)              # {plan: [a, b, c], inclinaison_deg, methode, points, niveau}
    h = hauteurs(points, sol["plan"])      # hauteur de chaque point au-dessus du sol

Méthode : parmi les points bas (moins de BANDE m au-dessus du 1er centile des z), RANSAC d'un plan
presque horizontal (normale à moins de INCLINAISON_MAX degrés de z), tirages à graine fixe (même
résultat à chaque appel) ; puis deux ajustements par moindres carrés sur tous les points du nuage à
moins de DISTANCE m du plan. Sans plan assez grand (sol jamais vu), le sol est le 1er centile des z,
à plat (methode « centile ») ; avec un niveau imposé (--sol), un plan horizontal (methode « impose »).
Revue de la vague 5 : un sol d'intérieur n'est pas penché de plusieurs degrés (le repère du G1 l'est de
0,6°). Un plan plus penché que INCLINAISON_ACCEPTEE (un scan court qui a vu peu de sol a donné 6,8°, et des
hauteurs fausses de plusieurs dizaines de centimètres) est refusé : le sol est pris à plat, au 1er centile
des z comme quand il n'est pas vu (methode « centile »), et « raison » le dit (le rapport du scan aussi).

Seulement numpy (pas d'Open3D : son RANSAC, parallèle, ne rend pas deux fois le même plan).
"""
import math

import numpy as np

GRAINE = 0                 # graine du hasard : résultat reproductible
BANDE = 0.4                # m : sol cherché parmi les points à moins de 0,4 m au-dessus du 1er centile des z
DISTANCE = 0.03            # m : écart maximal d'un point au plan
ITERATIONS = 1000          # tirages du RANSAC
ECHANTILLON = 20000        # points au plus pour compter les points d'un plan (tirés à graine fixe)
INCLINAISON_MAX = 10.0     # degrés : un plan plus incliné n'est pas le sol (recherche du RANSAC)
INCLINAISON_ACCEPTEE = 3.0  # degrés : un plan trouvé plus penché est refusé (sol mal vu) : pris à plat
POINTS_MIN = 100           # points du plan au moins ; sinon le sol est le 1er centile des z
METHODES = ("ransac", "centile", "impose")


class ErreurSol(Exception):
    """Nuage vide : pas de sol à trouver."""


def plan_horizontal(points, distance=DISTANCE, iterations=ITERATIONS, inclinaison_max=INCLINAISON_MAX,
                    graine=GRAINE, echantillon_max=ECHANTILLON):
    """RANSAC d'un plan presque horizontal dans des points (N, 3) : tirages de 3 points à graine fixe,
    le plan qui a le plus de points à moins de « distance » gagne. Renvoie (normale unitaire avec
    n_z > 0, décalage d) du plan n·p + d = 0, ou None."""
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    n = len(points)
    if n < 3:
        return None
    rng = np.random.default_rng(int(graine))
    echantillon = points if n <= echantillon_max else points[np.sort(rng.choice(n, echantillon_max, replace=False))]
    triplets = rng.integers(0, len(echantillon), size=(int(iterations), 3))
    p0, p1, p2 = (echantillon[triplets[:, k]] for k in range(3))
    normales = np.cross(p1 - p0, p2 - p0)
    normes = np.linalg.norm(normales, axis=1)
    ok = normes > 1e-9
    normales[ok] /= normes[ok, None]
    ok &= np.abs(normales[:, 2]) >= math.cos(math.radians(inclinaison_max))
    if not ok.any():
        return None
    normales = normales[ok] * np.sign(normales[ok][:, 2])[:, None]
    d = -(normales * p0[ok]).sum(axis=1)
    meilleur, compte_max = 0, -1
    for debut in range(0, len(normales), 100):
        comptes = (np.abs(echantillon @ normales[debut:debut + 100].T + d[debut:debut + 100]) <= distance).sum(axis=0)
        k = int(np.argmax(comptes))
        if comptes[k] > compte_max:
            meilleur, compte_max = debut + k, int(comptes[k])
    return normales[meilleur], float(d[meilleur])


def plan_en_z(normale, decalage):
    """Plan n·p + d = 0 (n_z non nul) → [a, b, c] de z = a·x + b·y + c."""
    nx, ny, nz = (float(v) for v in normale)
    return [-nx / nz, -ny / nz, -float(decalage) / nz]


def niveau(plan, x, y):
    """Hauteur z du sol en (x, y) : a·x + b·y + c (nombres ou tableaux)."""
    a, b, c = plan
    return a * np.asarray(x, dtype=float) + b * np.asarray(y, dtype=float) + c


def hauteurs(points, plan):
    """Hauteur de chaque point (N, 3) au-dessus du plan du sol : z − (a·x + b·y + c)."""
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    return points[:, 2] - niveau(plan, points[:, 0], points[:, 1])


def inclinaison_deg(plan):
    """Pente du plan, en degrés (0 : horizontal)."""
    return math.degrees(math.atan(math.hypot(plan[0], plan[1])))


def ajuster(points, plan, distance=DISTANCE, tours=2):
    """Moindres carrés z = a·x + b·y + c sur les points à moins de « distance » (en z) du plan.
    Renvoie (plan ajusté, nombre de points utilisés au dernier tour)."""
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    plan = [float(v) for v in plan]
    n = 0
    for _ in range(tours):
        dedans = np.abs(hauteurs(points, plan)) <= distance
        n = int(dedans.sum())
        if n < 3:
            break
        p = points[dedans]
        a = np.column_stack([p[:, 0], p[:, 1], np.ones(len(p))])
        coef, *_ = np.linalg.lstsq(a, p[:, 2], rcond=None)
        plan = [float(v) for v in coef]
    return plan, n


def plan_plat(z):
    """Plan horizontal z = constante."""
    return [0.0, 0.0, float(z)]


def trouver_sol(points, sol=None, bande=BANDE, distance=DISTANCE, iterations=ITERATIONS,
                inclinaison_max=INCLINAISON_MAX, points_min=POINTS_MIN, graine=GRAINE, echantillon=ECHANTILLON,
                inclinaison_acceptee=INCLINAISON_ACCEPTEE):
    """Plan du sol d'un nuage (N, 3). sol : niveau imposé (plan horizontal), sinon trouvé seul.

    Renvoie {plan: [a, b, c], inclinaison_deg, methode (ransac, centile ou impose), points (points du
    plan), niveau (hauteur du sol au milieu du nuage)}, et raison (phrase en français) quand un plan trouvé
    a été refusé, trop penché pour un sol : le sol est alors pris à plat. ErreurSol si le nuage est vide."""
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    if len(points) == 0:
        raise ErreurSol("nuage vide : pas de sol à trouver")
    cx, cy = (float(v) for v in np.median(points[:, :2], axis=0))
    if sol is not None:
        plan, methode, n = plan_plat(sol), "impose", 0
    else:
        bas = float(np.percentile(points[:, 2], 1.0))
        candidats = points[points[:, 2] <= bas + bande]
        trouve = plan_horizontal(candidats, distance, iterations, inclinaison_max, graine, echantillon)
        plan, methode, n = plan_plat(bas), "centile", 0
        raison = None
        if trouve is not None:
            essai, compte = ajuster(points, plan_en_z(*trouve), distance)
            pente = inclinaison_deg(essai)
            if compte >= points_min and pente <= min(inclinaison_max, inclinaison_acceptee):
                plan, methode, n = essai, "ransac", compte
            elif compte >= points_min:
                # trop penché pour un sol d'intérieur (peu de sol vu) : à plat, au plus bas des points, comme
                # un sol pas vu (le plan penché passait par le pied des murs ou des meubles bas)
                raison = (f"sol mal vu (un plan penché de {pente:.1f}° sur {compte} points : scan trop court ?) ; "
                          "pris à plat")
    resultat = {"plan": [round(v, 6) for v in plan], "inclinaison_deg": round(inclinaison_deg(plan), 3),
                "methode": methode, "points": int(n), "niveau": round(float(niveau(plan, cx, cy)), 3)}
    if sol is None and raison:
        resultat["raison"] = raison
    return resultat


def resume_sol(sol):
    """Ce qu'on écrit dans rapport.json et dans l'en-tête d'un nuage : {plan, inclinaison_deg, methode}."""
    return {"plan": [float(v) for v in sol["plan"]], "inclinaison_deg": float(sol["inclinaison_deg"]),
            "methode": sol["methode"]}
