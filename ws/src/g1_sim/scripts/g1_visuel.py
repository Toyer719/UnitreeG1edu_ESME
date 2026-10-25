#!/usr/bin/env python3
"""
Habille le robot proxy avec le vrai modèle 3D du Unitree G1 EDU (29 ddl, sans mains Dex3).

Lit le URDF officiel d'Unitree, calcule la position de chaque pièce du robot debout,
pose les pieds au sol, puis réécrit models/g1_proxy/model.sdf :
  - les boîtes de couleur sont remplacées par les maillages du G1 (invisibles pour le LiDAR) ;
  - la boîte de collision prend les vraies dimensions du robot ;
  - le LiDAR est placé à la position réelle du MID-360 (orientation laissée droite).
Le robot reste figé debout : il glisse sans bouger les jambes, comme le robot proxy.

  python3 g1_visuel.py               réécrit le modèle
  python3 g1_visuel.py --image f.png enregistre aussi une vue de face et de profil
"""
import argparse
import math
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

RACINE = Path.home() / 'robot-g1'
DESCRIPTION = RACINE / 'third_party/unitree_rl_gym/resources/robots/g1_description'
URDF = DESCRIPTION / 'g1_29dof_rev_1_0.urdf'
MODELE = Path(__file__).resolve().parents[1] / 'models' / 'g1_proxy' / 'model.sdf'

# Posture debout de la politique de marche d'Unitree (g1.yaml), bras le long du corps
POSTURE = {
    'left_hip_pitch_joint': -0.1, 'right_hip_pitch_joint': -0.1,
    'left_knee_joint': 0.3, 'right_knee_joint': 0.3,
    'left_ankle_pitch_joint': -0.2, 'right_ankle_pitch_joint': -0.2,
    'left_shoulder_roll_joint': 0.15, 'right_shoulder_roll_joint': -0.15,
    'left_shoulder_pitch_joint': 0.0, 'right_shoulder_pitch_joint': 0.0,
    'left_elbow_joint': 1.45, 'right_elbow_joint': 1.45,
}
SOMBRE = {'head_link', 'logo_link', 'pelvis_contour_link'}
COULEUR_CLAIRE = '0.78 0.78 0.80 1'
COULEUR_SOMBRE = '0.15 0.15 0.17 1'


def matrice(xyz, rpy):
    """Matrice 4×4 d'une position et d'angles roulis, tangage, lacet."""
    r, p, y = rpy
    cr, sr = math.cos(r), math.sin(r)
    cp, sp = math.cos(p), math.sin(p)
    cy, sy = math.cos(y), math.sin(y)
    m = np.eye(4)
    m[:3, :3] = [[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
                 [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
                 [-sp, cp * sr, cp * cr]]
    m[:3, 3] = xyz
    return m


def rotation_axe(axe, angle):
    """Matrice de rotation 4×4 d'un angle autour d'un axe (formule de Rodrigues)."""
    axe = np.asarray(axe, float) / np.linalg.norm(axe)
    k = np.array([[0, -axe[2], axe[1]], [axe[2], 0, -axe[0]], [-axe[1], axe[0], 0]])
    m = np.eye(4)
    m[:3, :3] = np.eye(3) + math.sin(angle) * k + (1 - math.cos(angle)) * k @ k
    return m


def vers_rpy(m):
    """Retrouve roulis, tangage et lacet d'une matrice de rotation (convention SDF et URDF)."""
    tangage = math.asin(max(-1.0, min(1.0, -m[2, 0])))
    return math.atan2(m[2, 1], m[2, 2]), tangage, math.atan2(m[1, 0], m[0, 0])


def lire_origine(element):
    """Lit la balise origin d'un élément URDF (identité si elle est absente)."""
    origine = element.find('origin') if element is not None else None
    if origine is None:
        return np.eye(4)
    xyz = [float(v) for v in origine.get('xyz', '0 0 0').split()]
    rpy = [float(v) for v in origine.get('rpy', '0 0 0').split()]
    return matrice(xyz, rpy)


def poses_des_liens(urdf):
    """Position de chaque lien dans le repère du bassin, robot dans la POSTURE."""
    articulations = {j.find('child').get('link'): j for j in urdf.findall('joint')}
    poses = {}

    def pose(lien):
        if lien in poses:
            return poses[lien]
        j = articulations.get(lien)
        if j is None:
            poses[lien] = np.eye(4)                     # le bassin : racine de l'arbre
        else:
            parent = pose(j.find('parent').get('link'))
            mouvement = np.eye(4)
            if j.get('type') == 'revolute':
                axe = [float(v) for v in j.find('axis').get('xyz').split()]
                mouvement = rotation_axe(axe, POSTURE.get(j.get('name'), 0.0))
            poses[lien] = parent @ lire_origine(j) @ mouvement
        return poses[lien]

    for lien in urdf.findall('link'):
        pose(lien.get('name'))
    return poses


def sommets_stl(chemin):
    """Lit les sommets d'un fichier STL binaire (tableau n × 3)."""
    donnees = chemin.read_bytes()
    n = struct.unpack_from('<I', donnees, 80)[0]
    format_triangle = np.dtype([('n', '<3f4'), ('v', '<3f4', (3,)), ('a', '<u2')])
    triangles = np.frombuffer(donnees, dtype=format_triangle, count=n, offset=84)
    return triangles['v'].reshape(-1, 3).astype(float)


def visuels(urdf, poses):
    """Pièces visibles : (lien, maillage, transformation dans le repère du bassin)."""
    liste = []
    for lien in urdf.findall('link'):
        nom = lien.get('name')
        for v in lien.findall('visual'):
            mesh = v.find('geometry/mesh')
            if mesh is not None:
                liste.append((nom, mesh.get('filename'), poses[nom] @ lire_origine(v)))
    return liste


def enregistrer_image(chemin, nuages, hauteur_bassin, lidar):
    """Enregistre une vue de face et de profil des sommets, pour vérifier la posture."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, (face, profil) = plt.subplots(1, 2, figsize=(8, 7))
    for s in nuages:
        s = s[::5]
        face.scatter(s[:, 1], s[:, 2] + hauteur_bassin, s=0.2, c='0.3')
        profil.scatter(s[:, 0], s[:, 2] + hauteur_bassin, s=0.2, c='0.3')
    for ax, axe, titre in ((face, 1, 'De face (y, z)'), (profil, 0, 'De profil (x, z)')):
        ax.scatter([lidar[axe, 3]], [lidar[2, 3]], c='tab:red', s=30, label='MID-360')
        ax.axhline(0, c='tab:green', lw=1)
        ax.set_aspect('equal')
        ax.set_title(titre)
        ax.legend(loc='lower right')
    fig.savefig(chemin, dpi=110)
    print(f'Image enregistrée : {chemin}')


def main():
    p = argparse.ArgumentParser(description="Habiller le robot proxy avec le modèle 3D du G1 EDU.")
    p.add_argument('--image', type=Path, help='vue de face et de profil enregistrée dans ce PNG')
    args = p.parse_args()

    urdf = ET.parse(URDF).getroot()
    poses = poses_des_liens(urdf)
    pieces = visuels(urdf, poses)

    # Tous les sommets dans le repère du bassin, pour poser les pieds au sol et mesurer le robot
    nuages = []
    for _, fichier, m in pieces:
        s = sommets_stl(DESCRIPTION / fichier)
        nuages.append((s @ m[:3, :3].T) + m[:3, 3])
    tous = np.vstack(nuages)
    hauteur_bassin = -tous[:, 2].min()
    mini, maxi = tous.min(axis=0), tous.max(axis=0)
    taille = maxi - mini
    centre = (mini + maxi) / 2
    print(f'G1 debout : hauteur {taille[2]:.3f} m, largeur {taille[1]:.3f} m, '
          f'profondeur {taille[0]:.3f} m, bassin à {hauteur_bassin:.3f} m')

    sol = matrice([0, 0, hauteur_bassin], [0, 0, 0])
    lidar = sol @ poses['mid360_link']
    camera = sol @ poses['d435_link']
    print(f'MID-360 à x {lidar[0, 3]:+.3f}, y {lidar[1, 3]:+.3f}, z {lidar[2, 3]:.3f} m ; '
          f'D435 à x {camera[0, 3]:+.3f}, z {camera[2, 3]:.3f} m')

    # Réécriture du modèle, en gardant ses commentaires
    arbre = ET.parse(MODELE, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    base = arbre.getroot().find('model/link[@name="base_link"]')
    for v in base.findall('visual'):
        base.remove(v)
    collision = base.find('collision')
    z_centre = centre[2] + hauteur_bassin
    collision.find('pose').text = f'{centre[0]:.3f} {centre[1]:.3f} {z_centre:.3f} 0 0 0'
    collision.find('geometry/box/size').text = f'{taille[0]:.3f} {taille[1]:.3f} {taille[2]:.3f}'
    capteur = base.find('sensor[@type="gpu_lidar"]')
    capteur.find('pose').text = f'{lidar[0, 3]:.3f} {lidar[1, 3]:.3f} {lidar[2, 3]:.3f} 0 0 0'

    position = list(base).index(collision) + 1
    for i, (lien, fichier, m) in enumerate(pieces):
        m = sol @ m
        roulis, tangage, lacet = vers_rpy(m)
        v = ET.Element('visual', name=f'g1_{lien}')
        ET.SubElement(v, 'pose').text = (f'{m[0, 3]:.5f} {m[1, 3]:.5f} {m[2, 3]:.5f} '
                                         f'{roulis:.5f} {tangage:.5f} {lacet:.5f}')
        ET.SubElement(ET.SubElement(ET.SubElement(v, 'geometry'), 'mesh'), 'uri').text = fichier
        couleur = COULEUR_SOMBRE if lien in SOMBRE else COULEUR_CLAIRE
        materiau = ET.SubElement(v, 'material')
        ET.SubElement(materiau, 'ambient').text = couleur
        ET.SubElement(materiau, 'diffuse').text = couleur
        ET.SubElement(v, 'visibility_flags').text = '2'     # le LiDAR ne voit pas le robot
        base.insert(position + i, v)
    ET.indent(arbre, space='  ')
    arbre.write(MODELE, encoding='unicode', xml_declaration=True)
    print(f'{len(pieces)} pièces écrites dans {MODELE}')

    if args.image:
        enregistrer_image(args.image, nuages, hauteur_bassin, lidar)


if __name__ == '__main__':
    main()
