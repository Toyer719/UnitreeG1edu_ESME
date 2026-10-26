"""
Nuages de points et repères 3D du relais odom_vers_tf (section 10.5 du plan), avec numpy.

  lire_xyz(msg)                          sensor_msgs/PointCloud2 → tableau (N, 3) des points finis
  creer_nuage(points, repere, horodatage) tableau (N, 3) → PointCloud2 (x, y, z en float32)
  matrice(x, y, z, roulis, tangage, lacet)   transformation homogène 4 × 4
  matrice_sol(pose, z)                   pose au sol (x, y, cap) → 4 × 4, à la hauteur z
  appliquer(m, points)                   points (N, 3) passés par la transformation m

Les champs autres que x, y et z (intensité, anneau...) sont lus sans être décodés : ils peuvent
être de n'importe quel type, ce que read_points_numpy de Humble refuse (nuage de Gazebo).
"""
import math

import numpy as np

# Types des champs de sensor_msgs/PointField → types numpy
TYPES_CHAMPS = {1: 'i1', 2: 'u1', 3: 'i2', 4: 'u2', 5: 'i4', 6: 'u4', 7: 'f4', 8: 'f8'}


def lire_xyz(msg):
    """PointCloud2 → tableau (N, 3) des points finis. ValueError si x, y ou z manque."""
    champs = {f.name: f for f in msg.fields}
    if not all(n in champs for n in 'xyz'):
        raise ValueError('le nuage n\'a pas de champs x, y et z')
    if msg.width * msg.height == 0:
        return np.zeros((0, 3))
    ordre = '>' if msg.is_bigendian else '<'
    type_point = np.dtype({'names': list('xyz'),
                           'formats': [ordre + TYPES_CHAMPS[champs[n].datatype] for n in 'xyz'],
                           'offsets': [champs[n].offset for n in 'xyz'],
                           'itemsize': msg.point_step})
    donnees = np.frombuffer(bytes(msg.data), dtype=np.uint8)
    if msg.height > 1:
        lignes = [donnees[i * msg.row_step:i * msg.row_step + msg.width * msg.point_step]
                  for i in range(msg.height)]
        donnees = np.concatenate(lignes)
    else:
        donnees = donnees[:msg.width * msg.point_step]
    brut = donnees.view(type_point)
    points = np.column_stack([brut['x'], brut['y'], brut['z']]).astype(float)
    return points[np.isfinite(points).all(axis=1)]


def creer_nuage(points, repere, horodatage=None):
    """Tableau (N, 3) → sensor_msgs/PointCloud2 non organisé, champs x, y, z en float32."""
    from sensor_msgs.msg import PointCloud2, PointField
    points = np.ascontiguousarray(np.asarray(points, dtype=np.float32).reshape(-1, 3))
    msg = PointCloud2()
    msg.header.frame_id = repere
    if horodatage is not None:
        msg.header.stamp = horodatage
    msg.height, msg.width = 1, len(points)
    msg.fields = [PointField(name=n, offset=4 * i, datatype=PointField.FLOAT32, count=1)
                  for i, n in enumerate('xyz')]
    msg.is_bigendian = False
    msg.point_step, msg.row_step = 12, 12 * len(points)
    msg.is_dense = True
    msg.data = points.tobytes()
    return msg


def matrice(x=0.0, y=0.0, z=0.0, roulis=0.0, tangage=0.0, lacet=0.0):
    """Matrice homogène 4 × 4 : rotation lacet · tangage · roulis (axes fixes), translation."""
    cr, sr = math.cos(roulis), math.sin(roulis)
    ct, st = math.cos(tangage), math.sin(tangage)
    cl, sl = math.cos(lacet), math.sin(lacet)
    m = np.eye(4)
    m[:3, :3] = np.array([[cl * ct, cl * st * sr - sl * cr, cl * st * cr + sl * sr],
                          [sl * ct, sl * st * sr + cl * cr, sl * st * cr - cl * sr],
                          [-st, ct * sr, ct * cr]])
    m[:3, 3] = (x, y, z)
    return m


def matrice_quaternion(translation, quaternion):
    """4 × 4 depuis une translation (x, y, z) et un quaternion (x, y, z, w) normé ou non."""
    qx, qy, qz, qw = (float(v) for v in quaternion)
    n = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw) or 1.0
    qx, qy, qz, qw = qx / n, qy / n, qz / n, qw / n
    m = np.eye(4)
    m[:3, :3] = np.array([
        [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
        [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
        [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)]])
    m[:3, 3] = [float(v) for v in translation]
    return m


def matrice_sol(pose, z=0.0):
    """Pose au sol (x, y, cap) → 4 × 4, à la hauteur z."""
    return matrice(pose[0], pose[1], z, 0.0, 0.0, pose[2])


def inverser(m):
    """Inverse d'une transformation rigide 4 × 4."""
    r = m[:3, :3]
    inverse = np.eye(4)
    inverse[:3, :3] = r.T
    inverse[:3, 3] = -r.T @ m[:3, 3]
    return inverse


def appliquer(m, points):
    """Points (N, 3) passés par la transformation m (4 × 4)."""
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    return points @ m[:3, :3].T + m[:3, 3]
