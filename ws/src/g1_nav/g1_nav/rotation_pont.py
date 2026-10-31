"""
Rotation sur place à travers le pont : simulation de la chaîne, sans ROS (vague 5, section 12.6).

Le pont ne fait pas tourner le vrai G1 sous 0,3 rad/s (vitesse_min_rot) : une rotation finit à
0,3 rad/s au moins, et le robot dépasse la flèche d'un angle presque constant, quel que soit
l'angle demandé. Une seconde rotation dépasse d'autant dans l'autre sens. Cette simulation
chiffre ce dépassement et ce que fait le guide au point principal (jusqu'à 3 rotations tant que
l'écart dépasse tolerance_orientation_rad, chacune raccourcie de anticipation_rotation_rad, au
plus la moitié de l'écart). Elle justifie la tolérance que navigation.launch.py donne au guide
avec le pont (TOLERANCE_ORIENTATION_PONT_RAD), et sert à la séance 2 avec le retard mesuré :

  python3 -m g1_nav.rotation_pont [--retard 0.2] [--constante 0.2] [--odometrie 0.05]
                                  [--tolerance 0.4] [--anticipation 0.0]

La chaîne, pas à pas (1 ms) :
  - Spin de Nav2 Humble (behavior_server, 10 Hz) : vitesse = min(max(√(2 a reste), 0,3), 0,6),
    arrêt dès que l'angle tourné, lu sur l'odométrie, atteint l'angle demandé ;
  - velocity_smoother (20 Hz, boucle ouverte, ±1,6 rad/s²) ;
  - pont : vitesse_effective d'atelier.lieu.robot (minimum 0,3 rad/s, zone morte 0,1 rad/s) ;
    départ et arrêt envoyés tout de suite, sinon la consigne à 10 Hz ;
  - robot : retard pur (réseau, contrôleur), puis premier ordre (constante de temps) ;
  - odométrie en retard (relais, TF).
Les valeurs de la chaîne sont celles de config/nav2_g1_reel.yaml et du pont
(test/test_rotation_pont.py le vérifie).
"""
from collections import deque
import math
import sys

from atelier.lieu.robot import LIMITES_PONT, vitesse_effective

from .commande import Analyseur

# Spin du behavior_server (config/nav2_g1_reel.yaml)
FREQUENCE_SPIN_HZ = 10.0
ROTATION_MIN_SPIN = 0.3
ROTATION_MAX_SPIN = 0.6
ACCELERATION_SPIN = 1.6
# velocity_smoother (config/nav2_g1_reel.yaml)
FREQUENCE_LISSEUR_HZ = 20.0
ACCELERATION_LISSEUR = 1.6
# Pont (g1_bridge, config/pont.yaml) : envoi de la consigne en cours
FREQUENCE_PONT_HZ = 10.0
SEUIL_NUL = 1e-3
# Guide (g1_nav/guide.py, ESSAIS_ORIENTATION)
ESSAIS = 3
PAS_S = 0.001
DUREE_MAX_S = 30.0
# Cas de la simulation : (retard pur, constante de temps) du robot, en secondes
CAS = ((0.1, 0.1), (0.15, 0.15), (0.2, 0.2), (0.2, 0.3), (0.3, 0.3))


def consigne_pont(wz):
    """Rotation que le pont envoie pour une consigne wz seule (plafond, minimum, zone morte)."""
    wz = max(-LIMITES_PONT['wz'], min(LIMITES_PONT['wz'], wz))
    return vitesse_effective(0.0, 0.0, wz)[2]


def rotation(angle, retard_s, constante_s, odometrie_s=0.05, anticipation=0.0):
    """
    Angle (rad) dont le robot tourne vraiment quand le guide demande une rotation de angle.

    La demande à Spin est raccourcie de anticipation (au plus la moitié de angle), comme dans
    Guide._orienter.
    """
    demande = angle - math.copysign(min(max(0.0, anticipation), abs(angle) / 2.0), angle)
    t = cap = w = cible = 0.0
    caps = deque([(0.0, 0.0)])      # (instant, cap réel) : l'odométrie en retard
    ordres = deque()                # (instant d'effet, wz) : 7105 reçus par le robot
    spin_cmd, spin_fini = None, False
    relatif = precedent = 0.0
    lisseur = 0.0
    actif, envoye, prochain_envoi = False, 0.0, 0.0
    t_spin = t_lisseur = 0.0
    arrete = None
    while t < DUREE_MAX_S:
        caps.append((t, cap))
        while len(caps) > 1 and caps[1][0] <= t - odometrie_s:
            caps.popleft()
        cap_vu = caps[0][1]
        if not spin_fini and t >= t_spin - 1e-9:
            t_spin += 1.0 / FREQUENCE_SPIN_HZ
            relatif += cap_vu - precedent
            precedent = cap_vu
            reste = abs(demande) - abs(relatif)
            if reste < 1e-6:
                spin_cmd, spin_fini = 0.0, True
            else:
                v = math.sqrt(2.0 * ACCELERATION_SPIN * reste)
                spin_cmd = math.copysign(min(max(v, ROTATION_MIN_SPIN), ROTATION_MAX_SPIN),
                                         demande)
        if t >= t_lisseur - 1e-9:
            t_lisseur += 1.0 / FREQUENCE_LISSEUR_HZ
            pas = ACCELERATION_LISSEUR / FREQUENCE_LISSEUR_HZ
            lisseur += max(-pas, min(pas, (spin_cmd or 0.0) - lisseur))
            wz = consigne_pont(lisseur)
            nulle = abs(wz) < SEUIL_NUL
            if nulle != (abs(envoye) < SEUIL_NUL) or (not actif and not nulle):
                ordres.append((t + retard_s, wz))          # départ ou arrêt : tout de suite
                envoye, prochain_envoi = wz, t + 1.0 / FREQUENCE_PONT_HZ
            actif, consigne = not nulle, wz
        if actif and t >= prochain_envoi - 1e-9:
            ordres.append((t + retard_s, consigne))
            envoye = consigne
            prochain_envoi += 1.0 / FREQUENCE_PONT_HZ
        while ordres and ordres[0][0] <= t:
            cible = ordres.popleft()[1]
        w += (cible - w) * (1.0 - math.exp(-PAS_S / max(constante_s, 1e-6)))
        cap += w * PAS_S
        t += PAS_S
        if spin_fini and not ordres and cible == 0.0 and abs(w) < 1e-4:
            arrete = t if arrete is None else arrete
            if t - arrete > 0.5:
                break
    return cap


def depassement(retard_s, constante_s, odometrie_s=0.05, angle=math.pi / 2):
    """Angle (rad) tourné en trop pour une rotation de angle (90° par défaut)."""
    tourne = rotation(angle, retard_s, constante_s, odometrie_s)
    return abs(tourne) - abs(angle)


def guide(ecart, retard_s, constante_s, tolerance, anticipation=0.0, odometrie_s=0.05,
          essais=ESSAIS):
    """Le guide au point principal : (rotations faites, écart final en rad) depuis ecart."""
    n = 0
    while n < essais and abs(ecart) > tolerance:
        ecart -= rotation(ecart, retard_s, constante_s, odometrie_s, anticipation)
        n += 1
    return n, ecart


def pire_cas(retard_s, constante_s, tolerance, anticipation=0.0, odometrie_s=0.05,
             ecarts_deg=range(5, 181, 5)):
    """(rotations au plus, écart final au plus en rad) pour des écarts de départ de 5° à 180°."""
    rotations, pire = 0, 0.0
    for d in ecarts_deg:
        n, e = guide(math.radians(d), retard_s, constante_s, tolerance, anticipation,
                     odometrie_s)
        rotations, pire = max(rotations, n), max(pire, abs(e))
    return rotations, pire


def _deg(x):
    return f'{math.degrees(x):.1f}°'.replace('.', ',')


def _rotations(n):
    return f'{n} rotation' + ('s' if n > 1 else '')


def main(argv=None):
    p = Analyseur(prog='python3 -m g1_nav.rotation_pont',
                  description='Rotation finale du guide à travers le pont (simulation de la '
                              'chaîne, vague 5).')
    p.add_argument('--retard', type=float,
                   help='retard pur du robot, s ; avec « python3 -m g1_bridge.mesure rotation » : '
                        'retard − 0,3 × montée ; sans : les cas types')
    p.add_argument('--constante', type=float, default=0.2,
                   help='constante de temps du robot, s ; avec la mesure : montée ÷ 2,2 (défaut '
                        '0.2)')
    p.add_argument('--odometrie', type=float, default=0.05,
                   help='retard de l\'odométrie, s (défaut 0.05)')
    p.add_argument('--tolerance', type=float, default=0.4,
                   help='tolerance_orientation_rad du guide (défaut 0.4)')
    p.add_argument('--anticipation', type=float, default=0.0,
                   help='anticipation_rotation_rad du guide (défaut 0)')
    a = p.parse_args(argv)
    cas = CAS if a.retard is None else ((a.retard, a.constante),)
    print(f'Tolérance {a.tolerance:g} rad ({_deg(a.tolerance)}), anticipation '
          f'{a.anticipation:g} rad ; odométrie en retard de {a.odometrie:g} s'.replace('.', ','))
    for retard, constante in cas:
        d = depassement(retard, constante, a.odometrie)
        n, pire = pire_cas(retard, constante, a.tolerance, a.anticipation, a.odometrie)
        texte = f'retard {retard:g} s, constante {constante:g} s'.replace('.', ',')
        print(f'{texte} : dépassement d\'une rotation de 90° {_deg(d)} ; guide : {_rotations(n)} '
              f'au plus, {_deg(pire)} au plus de la flèche (écarts de départ de 5° à 180°)')
        if a.retard is not None:
            n2, pire2 = pire_cas(retard, constante, 0.6 * d, d, a.odometrie)
            print(f'conseil ({_rotations(n2)} au plus, {_deg(pire2)} au plus de la flèche), à '
                  'taper tel quel :')
            print(f'  ros2 param set /guide anticipation_rotation_rad {d:.3f}')
            print(f'  ros2 param set /guide tolerance_orientation_rad {0.6 * d:.3f}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
