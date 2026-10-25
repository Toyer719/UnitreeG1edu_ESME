"""
Les piétons (<actor> des mondes générés par atelier.monde) sont-ils vus par le gpu_lidar.

Le monde de test est fabriqué ici par atelier.monde, comme pour un vrai lieu : un couloir de
10 × 4 m, le robot en (1 ; 0) qui regarde vers +x, et deux piétons qui traversent devant lui,
h1 en x = 3 et h2 en x = 6. Pour chaque nuage, on compte les points proches de la position
attendue du piéton à cet instant (atelier.monde.position_pieton, temps simulé du nuage).

Résultat (25/10/2026) : oui, Fortress dessine les actor dans le rendu du LiDAR, avec leur
animation ; il n'y a pas besoin de cylindre qui suit chaque piéton. h2 peut être caché par h1.
Ignoré si le paquet atelier (agent Monde) n'est pas disponible.
"""
import time

import numpy as np
import pytest

from outils_sim import Ecoute, Simulation, lidar_vers_odom, points_xyz, temps

lieu_api = pytest.importorskip('atelier.lieu')
monde_api = pytest.importorskip('atelier.monde')

MONDE = {
    'version': 1,
    'emprise': {'min': [-0.5, -2.5], 'max': [10.5, 2.5]},
    'murs': [
        {'id': 'sud', 'de': [0, -2], 'a': [10, -2], 'epaisseur': 0.15, 'hauteur': 2.5},
        {'id': 'nord', 'de': [0, 2], 'a': [10, 2], 'epaisseur': 0.15, 'hauteur': 2.5},
        {'id': 'ouest', 'de': [0, -2], 'a': [0, 2], 'epaisseur': 0.15, 'hauteur': 2.5},
        {'id': 'est', 'de': [10, -2], 'a': [10, 2], 'epaisseur': 0.15, 'hauteur': 2.5},
    ],
    'pietons': [
        {'id': 'h1', 'trajet': [[3, -1.5], [3, 1.5]], 'vitesse': 0.5, 'aller_retour': True},
        {'id': 'h2', 'trajet': [[6, 1.2], [6, -1.2]], 'vitesse': 0.3, 'aller_retour': True},
    ],
    'depart_robot': {'x': 1.0, 'y': 0.0, 'theta': 0.0},
}
RAYON = 0.45   # m autour de la position attendue du piéton


@pytest.fixture(scope='module')
def sim_pietons(tmp_path_factory):
    dossier = tmp_path_factory.mktemp('lieu_pietons') / 'pietons'
    lieu = lieu_api.creer_lieu(dossier, 'Essai des piétons')
    lieu_api.enregistrer_lieu(lieu)
    monde = lieu_api.Monde.depuis_dict(MONDE)
    lieu_api.enregistrer_monde(dossier, 'rdc', monde)
    monde_api.generer(dossier, 'rdc')
    simulation = Simulation(dossier, 'rdc', nom='pietons')
    simulation.demarrer()
    ecoute = Ecoute('test_g1_sim_pietons')
    try:
        ecoute.attendre_pret(simulation)
        yield ecoute, monde
    finally:
        ecoute.fermer()
        simulation.arreter()


def _points_du_pieton(nuage, pieton, pose):
    """Points du nuage à moins de RAYON de la position attendue du piéton, entre 0,3 et 1,8 m."""
    x, y, theta = pose
    p = lidar_vers_odom(points_xyz(nuage), x, y, theta)
    px, py, _ = monde_api.position_pieton(pieton, temps(nuage.header))
    proches = (np.hypot(p[:, 0] - px, p[:, 1] - py) < RAYON) & (p[:, 2] > 0.3) & (p[:, 2] < 1.8)
    return p[proches], (px, py)


def test_pietons_vus_par_le_lidar(sim_pietons):
    ecoute, monde = sim_pietons
    debut = time.monotonic()
    time.sleep(6.0)
    nuages = ecoute.nuages_depuis(debut)[::5]   # un nuage toutes les 0,5 s
    x, y, theta, _ = ecoute.pose()
    vus = {p.id: 0 for p in monde.pietons}
    ecarts_y = []
    for nuage in nuages:
        ligne = f't = {temps(nuage.header):5.1f} s'
        for pieton in monde.pietons:
            points, (px, py) = _points_du_pieton(nuage, pieton, (x, y, theta))
            ligne += f' | {pieton.id} en ({px:.1f} ; {py:+.1f}) : {len(points):3d} points'
            if len(points) >= 5:
                vus[pieton.id] += 1
                if pieton.id == 'h1':
                    ecarts_y.append(abs(points[:, 1].mean() - py))
        print(ligne)
    print(f'nuages où chaque piéton est vu : {vus} sur {len(nuages)}')
    # h1 est toujours dans le champ, sans rien devant lui
    assert vus['h1'] >= 0.9 * len(nuages)
    # h2 est plus loin, et h1 le cache parfois
    assert vus['h2'] >= 0.5 * len(nuages)
    # Les points suivent le piéton : leur centre est à moins de 0,25 m de sa position attendue
    assert ecarts_y and np.mean(ecarts_y) < 0.25, ecarts_y
