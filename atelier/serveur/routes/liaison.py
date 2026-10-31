"""Liaison avec le robot, pour l'écran d'accueil en mode Réel (vague 5, section 12.4 du plan) : agent Coquille.

  GET /api/robot/liaison
        {interface, cable, adresse_pc, pc1: {adresse, repond, ms}, jetson: {adresse, repond, ms},
         ros: {domaine, cyclonedds, actif}, pret, message, duree_s}
        cable : /sys/class/net/<interface>/carrier (ATELIER_INTERFACE_ROBOT, eno2 par défaut) ;
        adresse_pc : l'adresse IPv4 du PC sur cette interface (ou null) ;
        pc1 (ATELIER_PC1, 192.168.123.161) et jetson (ATELIER_JETSON, 192.168.123.164) : un ping
        (ping -c 1 -W 1), les deux en parallèle, seulement si le câble est branché (sinon repond null) ;
        ros : ROS_DOMAIN_ID du serveur, interface de CYCLONEDDS_URI (setup/robot.sh), pont ROS 2 actif ;
        réponse en 1,5 s au plus ; pret : câble, PC1 qui répond et domaine 0 ; message en français
        qui dit quoi faire. Rien n'est envoyé au robot à part ces deux pings.

Tests : ATELIER_PC1=127.0.0.1, ATELIER_JETSON=127.0.0.1 et ATELIER_INTERFACE_ROBOT=lo (jamais de ping
vers 192.168.123.x pendant les essais).
"""
import asyncio
import fcntl
import os
import re
import socket
import struct
import time

from fastapi import APIRouter, Request

routeur = APIRouter(tags=["robot"])

INTERFACE_DEFAUT = "eno2"
PC1_DEFAUT = "192.168.123.161"
JETSON_DEFAUT = "192.168.123.164"
DELAI_PING_S = 1.3            # garde-fou autour de « ping -W 1 »
SIOCGIFADDR = 0x8915          # ioctl : adresse IPv4 d'une interface
MOTIF_TEMPS = re.compile(r"time[=<]\s*([0-9.]+)\s*ms")
MOTIF_INTERFACE = (re.compile(r"""<NetworkInterface\b[^>]*\bname\s*=\s*["']([^"']+)["']"""),
                   re.compile(r"<NetworkInterfaceAddress>\s*([^<\s]+)\s*</NetworkInterfaceAddress>"))


def interface_du_robot():
    """Nom de l'interface réseau du PC reliée au robot : $ATELIER_INTERFACE_ROBOT, sinon eno2."""
    return os.environ.get("ATELIER_INTERFACE_ROBOT") or INTERFACE_DEFAUT


def cable_present(interface):
    """Vrai si un câble est branché sur l'interface (lecture de /sys/class/net, rien n'est envoyé)."""
    try:
        with open(f"/sys/class/net/{interface}/carrier", encoding="ascii") as f:
            return f.read().strip() == "1"
    except (OSError, ValueError):
        return False        # interface absente ou désactivée


def adresse_ipv4(interface):
    """Adresse IPv4 du PC sur l'interface (ex. 192.168.123.99), ou None."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            brut = fcntl.ioctl(s.fileno(), SIOCGIFADDR, struct.pack("256s", interface[:15].encode()))
        return socket.inet_ntoa(brut[20:24])
    except OSError:
        return None


def interface_cyclonedds(uri=None):
    """Interface réseau choisie par CYCLONEDDS_URI (setup/robot.sh met eno2), ou None."""
    texte = os.environ.get("CYCLONEDDS_URI", "") if uri is None else uri
    for motif in MOTIF_INTERFACE:
        m = motif.search(texte or "")
        if m:
            return m.group(1)
    return None


async def ping(adresse):
    """{adresse, repond, ms} après un « ping -c 1 -W 1 » ; repond faux si pas de réponse en 1 s."""
    debut = time.monotonic()
    try:
        p = await asyncio.create_subprocess_exec("ping", "-n", "-c", "1", "-W", "1", adresse,
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    except (OSError, ValueError):
        return {"adresse": adresse, "repond": False, "ms": None, "erreur": "la commande ping manque"}
    try:
        sortie, _ = await asyncio.wait_for(p.communicate(), DELAI_PING_S)
    except asyncio.TimeoutError:
        try:
            p.kill()
        except ProcessLookupError:
            pass
        try:
            # le processus tué est ramassé et ses tuyaux fermés (pas de zombie)
            await asyncio.wait_for(p.communicate(), 0.15)
        except (asyncio.TimeoutError, OSError, ValueError):
            pass
        return {"adresse": adresse, "repond": False, "ms": None}
    if p.returncode != 0:
        return {"adresse": adresse, "repond": False, "ms": None}
    m = MOTIF_TEMPS.search(sortie.decode("utf-8", "replace"))
    ms = float(m.group(1)) if m else round((time.monotonic() - debut) * 1000.0, 1)
    return {"adresse": adresse, "repond": True, "ms": round(ms, 1)}


def message_liaison(interface, cable, pc1, jetson, domaine, cyclonedds):
    """Phrase qui dit ce qui va, ou quoi faire."""
    if not cable:
        return (f"Câble du robot non détecté ({interface}) : branchez le câble Ethernet entre le PC et le "
                "robot. Pour essayer sans robot, cochez « Répétition sans robot ».")
    if not pc1["repond"]:
        return (f"Le robot ne répond pas ({pc1['adresse']}) : est-il allumé ? Le PC doit avoir une adresse en "
                "192.168.123.x sur ce câble (setup/robot.sh).")
    if domaine != "0" or (cyclonedds is not None and cyclonedds != interface):
        return ("Le robot répond, mais l'Atelier n'a pas été lancé avec robot.sh : fermez-le (Ctrl+C), puis "
                "« source ~/robot-g1/setup/robot.sh » et g1-atelier.")
    suite = "" if jetson["repond"] else " Le Jetson ne répond pas encore : la navigation ne pourra pas démarrer."
    duree = f"{pc1['ms']:g}".replace(".", ",") if isinstance(pc1.get("ms"), (int, float)) else "?"
    return f"Robot relié : il répond en {duree} ms.{suite}"


@routeur.get("/api/robot/liaison")
async def liaison(request: Request):
    """Câble, PC1 et Jetson joignables, domaine ROS : les vérifications de l'accueil en mode Réel."""
    debut = time.monotonic()
    interface = interface_du_robot()
    cable = cable_present(interface)
    adresse_pc1 = os.environ.get("ATELIER_PC1") or PC1_DEFAUT
    adresse_jetson = os.environ.get("ATELIER_JETSON") or JETSON_DEFAUT
    if cable:
        pc1, jetson = await asyncio.gather(ping(adresse_pc1), ping(adresse_jetson))
    else:
        pc1 = {"adresse": adresse_pc1, "repond": None, "ms": None}
        jetson = {"adresse": adresse_jetson, "repond": None, "ms": None}
    domaine = os.environ.get("ROS_DOMAIN_ID", "0") or "0"
    cyclonedds = interface_cyclonedds()
    etat = request.app.state.atelier
    ros = {"domaine": domaine, "cyclonedds": cyclonedds, "actif": bool(etat.pont.actif)}
    pret = bool(cable and pc1["repond"] and domaine == "0")
    return {"interface": interface, "cable": cable, "adresse_pc": adresse_ipv4(interface),
            "pc1": pc1, "jetson": jetson, "ros": ros, "pret": pret,
            "message": message_liaison(interface, cable, pc1, jetson, domaine, cyclonedds),
            "duree_s": round(time.monotonic() - debut, 3)}
