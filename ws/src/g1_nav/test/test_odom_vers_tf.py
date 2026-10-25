"""
Test du relais odom_vers_tf (vrai robot) : odométrie → transformation odom → base_link.

Il faut les messages ROS 2 (source ~/robot-g1/setup/env.sh) ; sinon le test est sauté.

  python3 -m pytest ~/robot-g1/ws/src/g1_nav/test/test_odom_vers_tf.py -v
"""
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
    odom.pose.pose.orientation.z, odom.pose.pose.orientation.w = 0.7071, 0.7071
    t = odom_vers_transformation(odom, TransformStamped())
    assert (t.header.frame_id, t.child_frame_id) == ('odom', 'base_link')
    assert t.header.stamp.sec == 12
    assert (t.transform.translation.x, t.transform.translation.y) == (3.5, -1.25)
    assert (t.transform.rotation.z, t.transform.rotation.w) == (0.7071, 0.7071)
