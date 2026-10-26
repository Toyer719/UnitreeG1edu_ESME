"""
Test du relais odom_vers_tf : odométrie → transformation au sol (section 10.5 du plan).

La logique du repérage est testée sans ROS dans test_reperage.py ; le nœud complet, avec le faux
service slam_operate de la répétition, dans atelier/tests/test_robot_reperage_ros.py.
Il faut les messages ROS 2 (source ~/robot-g1/setup/env.sh) ; sinon le test est sauté.

  python3 -m pytest ~/robot-g1/ws/src/g1_nav/test/test_odom_vers_tf.py -v
"""
import math

import pytest

pytest.importorskip('nav_msgs.msg')
from geometry_msgs.msg import TransformStamped  # noqa: E402
from g1_nav.odom_vers_tf import odom_vers_transformation  # noqa: E402
from nav_msgs.msg import Odometry  # noqa: E402


def test_odometrie_vers_transformation():
    odom = Odometry()
    odom.header.frame_id = 'map'
    odom.header.stamp.sec = 12
    odom.pose.pose.position.x, odom.pose.pose.position.y = 3.5, -1.25
    odom.pose.pose.position.z = 0.75
    odom.pose.pose.orientation.z, odom.pose.pose.orientation.w = 0.7071, 0.7071
    t = odom_vers_transformation(odom, TransformStamped())
    assert (t.header.frame_id, t.child_frame_id) == ('odom', 'base_link')
    assert t.header.stamp.sec == 12
    assert (t.transform.translation.x, t.transform.translation.y) == (3.5, -1.25)
    # au sol : z oublié, quaternion normé autour de z
    assert t.transform.translation.z == 0.0
    assert t.transform.rotation.z == pytest.approx(math.sqrt(0.5))
    assert t.transform.rotation.w == pytest.approx(math.sqrt(0.5))


def test_capteur_retourne_garde_le_cap():
    """Roulis de π (MID-360 monté à l'envers) : le cap de l'axe x reste le bon."""
    odom = Odometry()
    cap = 0.8
    # rotation lacet 0,8 puis roulis π : q = q_lacet · q_roulis
    cz, sz = math.cos(cap / 2), math.sin(cap / 2)
    q = odom.pose.pose.orientation
    q.x, q.y, q.z, q.w = cz * 1.0, sz * 1.0, 0.0, 0.0
    t = odom_vers_transformation(odom, TransformStamped())
    lacet = 2 * math.atan2(t.transform.rotation.z, t.transform.rotation.w)
    assert lacet == pytest.approx(cap, abs=1e-6)
