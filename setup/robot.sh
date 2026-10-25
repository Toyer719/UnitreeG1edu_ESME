# À charger quand le robot est branché en Ethernet :  source ~/robot-g1/setup/robot.sh
# Met le PC en 192.168.123.99 sur le port du robot, y attache CycloneDDS et vérifie que le robot répond.
IFACE_ROBOT=eno2
IP_JETSON=192.168.123.164

if [ "$(cat /sys/class/net/$IFACE_ROBOT/carrier 2>/dev/null)" != "1" ]; then
  echo "Câble non détecté sur $IFACE_ROBOT : branchez le câble Ethernet entre le PC et le robot."
  return 1
fi

if ! nmcli -t -f NAME connection show | grep -qx robot-g1; then
  nmcli connection add type ethernet ifname "$IFACE_ROBOT" con-name robot-g1 \
    ipv4.method manual ipv4.addresses 192.168.123.99/24 ipv4.never-default yes ipv6.method ignore \
    connection.autoconnect no >/dev/null   # Internet reste sur le Wi-Fi
fi

if ! nmcli connection up robot-g1 >/dev/null 2>&1; then
  echo "Impossible d'activer la connexion robot-g1 sur $IFACE_ROBOT."
  return 1
fi

export CYCLONEDDS_URI="<CycloneDDS><Domain><General><Interfaces><NetworkInterface name=\"$IFACE_ROBOT\" priority=\"default\" multicast=\"default\"/></Interfaces></General></Domain></CycloneDDS>"

if ping -c 2 -W 1 "$IP_JETSON" >/dev/null 2>&1; then
  echo "ROS 2 relié au robot par $IFACE_ROBOT (PC en 192.168.123.99) : le robot répond."
else
  echo "Câble branché, mais le robot ne répond pas : attendez la fin de son démarrage, puis relancez cette commande."
  return 1
fi
