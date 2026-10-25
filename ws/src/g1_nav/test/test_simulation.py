"""
Essais de la navigation dans Gazebo, sans fenêtre : critères 4 et 5 du plan (section 7).

  aller  : accueil → b204 ; /guide/etat passe à « arrive », à moins de 0,3 m de la pose de
           la salle, en moins de 90 s de temps simulé ;
  detour : une boîte de 0,5 × 2,9 × 2 m coupe le couloir nord en (12 ; 13) : le guide passe
           par « bloque », puis « detour », puis « arrive » par le couloir sud.

Chaque essai travaille sur une copie du lieu demo dans un dossier temporaire (monde et carte
fabriqués par atelier.monde), lance g1_sim (sans fenêtre) et g1_nav, puis arrête tout.
Il faut g1_sim et g1_nav compilés et sourcés. Choisissez ROS_DOMAIN_ID et IGN_PARTITION pour
ne pas gêner d'autres essais. Durée : environ 5 minutes pour les deux.

  python3 test_simulation.py [aller|detour|tous]
  G1_NAV_SIMULATION=1 python3 -m pytest test_simulation.py -v     (sauté sans la variable)
"""
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import pytest

ACTIVE = os.environ.get('G1_NAV_SIMULATION') == '1'
SAUTE = 'essai long dans Gazebo : G1_NAV_SIMULATION=1 pour le lancer'
# Boîte qui coupe le couloir nord entre amphi (9 ; 13) et couloir_nord_1 (15 ; 13)
BOITE = """<?xml version="1.0"?>
<sdf version="1.9">
  <model name="boite_essai">
    <static>true</static>
    <link name="lien">
      <collision name="c"><geometry><box><size>0.5 2.9 2.0</size></box></geometry></collision>
      <visual name="v"><geometry><box><size>0.5 2.9 2.0</size></box></geometry></visual>
    </link>
  </model>
</sdf>
"""


def preparer_lieu(dossier):
    """Fabrique dans dossier/demo une copie de lieux/demo, avec son monde, sa carte, son masque."""
    from atelier import RACINE
    from atelier.lieu import copier_lieu
    from atelier.monde import generer
    lieu = copier_lieu(RACINE / 'lieux' / 'demo', Path(dossier) / 'demo')
    generer(lieu, 'rdc')
    return lieu


class Simulation:
    """Gazebo sans fenêtre, navigation Nav2 et client du guide ; tout s'arrête à la sortie."""

    def __init__(self, lieu, journaux):
        self.lieu, self.journaux = Path(lieu), Path(journaux)
        self.processus = []
        self.client = None

    def __enter__(self):
        from g1_nav.banc import ClientRos, lancer
        import rclpy
        self.processus.append(lancer(
            ['ros2', 'launch', 'g1_sim', 'simulation.launch.py', f'lieu:={self.lieu}',
             'etage:=rdc', 'sans_fenetre:=true'], self.journaux / 'simulation.log'))
        time.sleep(5.0)
        self.processus.append(lancer(
            ['ros2', 'launch', 'g1_nav', 'navigation.launch.py', f'lieu:={self.lieu}',
             'etage:=rdc', 'simu:=true', 'moteur:=nav2'], self.journaux / 'navigation.log'))
        rclpy.init()
        self.client = ClientRos(simu=True)
        probleme = self.client.attendre_guide(120.0)
        if probleme:
            self.__exit__(None, None, None)
            raise RuntimeError(f'la navigation n\'a pas démarré : {probleme} '
                               f'(journaux dans {self.journaux})')
        return self

    def __exit__(self, *_):
        from g1_nav.banc import arreter
        import rclpy
        if self.client is not None:
            self.client.stop()
            self.client.attendre(0.3)
            self.client.fermer()
            self.client = None
        rclpy.try_shutdown()
        for proc in reversed(self.processus):
            arreter(proc)
        self.processus = []

    def poser_boite(self):
        fichier = self.journaux / 'boite.sdf'
        fichier.write_text(BOITE, encoding='utf-8')
        subprocess.run(['ros2', 'run', 'ros_gz_sim', 'create', '-file', str(fichier),
                        '-name', 'boite_essai', '-x', '12', '-y', '13', '-z', '1.0'],
                       check=True, timeout=30, capture_output=True)

    def cout_global(self, points, delai_s=20.0):
        """Coût de la carte globale de Nav2 (0 à 100, -1 inconnu) en chaque point (x, y)."""
        from nav_msgs.msg import OccupancyGrid
        from rclpy.qos import DurabilityPolicy, QoSProfile
        recus = []
        abonnement = self.client.noeud.create_subscription(
            OccupancyGrid, '/global_costmap/costmap', recus.append,
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        fin = time.monotonic() + delai_s
        while not recus and time.monotonic() < fin:
            self.client.attendre(0.2)
        self.client.noeud.destroy_subscription(abonnement)
        if not recus:
            return None
        carte = recus[-1]
        info = carte.info
        couts = []
        for x, y in points:
            i = int((x - info.origin.position.x) / info.resolution)
            j = int((y - info.origin.position.y) / info.resolution)
            couts.append(carte.data[j * info.width + i])
        return couts

    def trajet(self, cible, delai_s):
        """Envoie le robot ; renvoie (suite des états, position finale, durée simulée)."""
        client = self.client
        t0 = client.temps()
        client.aller(cible)
        etats = []
        while client.temps() - t0 < delai_s:
            client.attendre(0.2)
            e = client.etat()
            if e is None or e.get('cible') != cible:
                continue
            if not etats or etats[-1] != e['etat']:
                etats.append(e['etat'])
                print(f'  {client.temps() - t0:6.1f} s  {e["etat"]:8s} reste {e["reste_m"]} m',
                      flush=True)
            if e['etat'] in ('arrive', 'echec'):
                break
        return etats, client.position(), client.temps() - t0


def ecart(position, pose):
    return math.inf if position is None else math.dist(position[:2], pose[:2])


def essai_aller(dossier):
    """Critère 4 : accueil → b204, à moins de 0,3 m, en moins de 90 s ; zone interdite."""
    lieu = preparer_lieu(dossier)
    with Simulation(lieu, dossier) as sim:
        # Filtre Keepout : le pied de l'escalier (zone interdite du demo) est infranchissable,
        # le milieu du couloir nord est libre
        couts = sim.cout_global([(0.9, 13.2), (12.0, 13.0)])
        print(f'carte globale : coût {couts} (escalier, couloir nord)')
        etats, position, duree = sim.trajet('b204', 150.0)
    erreur = ecart(position, (21.0, 13.0))
    print(f'aller : {" → ".join(etats)} ; {duree:.0f} s ; à {erreur:.2f} m de b204')
    keepout = couts is not None and couts[0] == 100 and couts[1] == 0
    reussi = keepout and etats[-1:] == ['arrive'] and erreur < 0.3 and duree < 90.0
    return reussi, etats, erreur, duree


def essai_detour(dossier):
    """Critère 5 : boîte dans le couloir nord → bloque, detour, arrive (par le sud)."""
    lieu = preparer_lieu(dossier)
    with Simulation(lieu, dossier) as sim:
        sim.poser_boite()
        etats, position, duree = sim.trajet('b204', 300.0)
    erreur = ecart(position, (21.0, 13.0))
    print(f'détour : {" → ".join(etats)} ; {duree:.0f} s ; à {erreur:.2f} m de b204')
    ordre = [e for e in etats if e in ('bloque', 'detour', 'arrive')]
    reussi = (etats[-1:] == ['arrive'] and erreur < 0.3 and 'bloque' in ordre
              and 'detour' in ordre and ordre.index('bloque') < ordre.index('detour'))
    return reussi, etats, erreur, duree


@pytest.mark.skipif(not ACTIVE, reason=SAUTE)
def test_accueil_vers_b204(tmp_path):
    reussi, etats, erreur, duree = essai_aller(tmp_path)
    assert reussi, (etats, erreur, duree)


@pytest.mark.skipif(not ACTIVE, reason=SAUTE)
def test_boite_dans_le_couloir_nord(tmp_path):
    reussi, etats, erreur, duree = essai_detour(tmp_path)
    assert reussi, (etats, erreur, duree)


def main():
    choix = sys.argv[1] if len(sys.argv) > 1 else 'tous'
    essais = {'aller': [('Critère 4, point A → point B', essai_aller)],
              'detour': [('Critère 5, chemin de secours', essai_detour)]}
    essais['tous'] = essais['aller'] + essais['detour']
    if choix not in essais:
        print('usage : test_simulation.py [aller|detour|tous]', file=sys.stderr)
        return 2
    bilan = []
    for titre, essai in essais[choix]:
        print(f'== {titre}', flush=True)
        dossier = Path(tempfile.mkdtemp(prefix='g1_nav_essai_'))
        print(f'   dossier : {dossier}')
        reussi = essai(dossier)[0]
        bilan.append(reussi)
        print(f'   {"RÉUSSI" if reussi else "RATÉ"}', flush=True)
    print(f'{sum(bilan)} / {len(bilan)} essais réussis')
    return 0 if all(bilan) else 1


if __name__ == '__main__':
    sys.exit(main())
