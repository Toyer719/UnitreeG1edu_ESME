"""
Relais de la relocalisation du vrai G1 : odométrie → /odom et TF odom → base_link.

Sur le robot, la position dans la carte vient de la relocalisation d'Unitree
(/unitree/slam_relocation/odom, après la commande 1804). Le lancement de g1_nav publie
map → odom en identité ; ce relais publie odom → base_link à partir de cette odométrie,
et la recopie sur /odom pour Nav2 (section 4.2 du plan). Il ne sert pas en simulation.

  ros2 run g1_nav odom_vers_tf --ros-args -p entree:=/unitree/slam_relocation/odom
"""
import signal
import sys

try:
    import rclpy
    from rclpy.node import Node
except ImportError:      # conversion seule, sans ROS (tests)
    rclpy = None
    Node = object


def odom_vers_transformation(odom, transformation, repere_odom='odom', repere_robot='base_link'):
    """Recopie la pose d'un nav_msgs/Odometry dans un geometry_msgs/TransformStamped."""
    transformation.header.stamp = odom.header.stamp
    transformation.header.frame_id = repere_odom
    transformation.child_frame_id = repere_robot
    p, q = odom.pose.pose.position, odom.pose.pose.orientation
    t = transformation.transform
    t.translation.x, t.translation.y, t.translation.z = p.x, p.y, p.z
    t.rotation.x, t.rotation.y, t.rotation.z, t.rotation.w = q.x, q.y, q.z, q.w
    return transformation


class OdomVersTf(Node):
    """Abonné à l'odométrie de la relocalisation ; publie /odom et TF odom → base_link."""

    def __init__(self):
        super().__init__('odom_vers_tf')
        from geometry_msgs.msg import TransformStamped
        from nav_msgs.msg import Odometry
        import tf2_ros

        entree = self.declare_parameter('entree', '/unitree/slam_relocation/odom').value
        self.repere_odom = self.declare_parameter('repere_odom', 'odom').value
        self.repere_robot = self.declare_parameter('repere_robot', 'base_link').value
        self.TransformStamped = TransformStamped
        self.diffuseur = tf2_ros.TransformBroadcaster(self)
        self.pub_odom = self.create_publisher(Odometry, '/odom', 10)
        self.create_subscription(Odometry, entree, self._sur_odom, 10)
        self.get_logger().info(f'relais {entree} → /odom et TF {self.repere_odom} → '
                               f'{self.repere_robot}')

    def _sur_odom(self, odom):
        self.diffuseur.sendTransform(odom_vers_transformation(
            odom, self.TransformStamped(), self.repere_odom, self.repere_robot))
        odom.header.frame_id = self.repere_odom
        odom.child_frame_id = self.repere_robot
        self.pub_odom.publish(odom)


def main(args=None):
    from rclpy.executors import ExternalShutdownException

    rclpy.init(args=args)
    noeud = OdomVersTf()
    try:
        rclpy.spin(noeud)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)     # un second Ctrl+C ne coupe pas l'arrêt
        noeud.destroy_node()
        rclpy.try_shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
