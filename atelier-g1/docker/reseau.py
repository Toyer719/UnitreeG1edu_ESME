#!/usr/bin/env python3
"""Réseau du conteneur g1-jetson : choix des interfaces et configuration CycloneDDS (section 10.2).

Python du système, sans ROS ni paquet en plus : ce module tourne dans l'image (demarrer.sh), et
sur le PC (docker/jetson.py, pour « g1-jetson verifier », et les tests de docker/tests).

  python3 reseau.py cyclonedds [--sortie /tmp/cyclonedds.xml] [--modele cyclonedds.xml.modele]
                               [--ip FICHIER]
      lit G1_INTERFACES, G1_WIFI et G1_PAIRS, et la sortie de « ip -o -4 addr » (ou FICHIER),
      écrit la configuration CycloneDDS et affiche, sur la sortie standard :
        interfaces=eth0,wlan0
        uri=file:///tmp/cyclonedds.xml        (vide : pas de CYCLONEDDS_URI, CycloneDDS choisit)
      Avertissements sur la sortie d'erreur. Code 1, avec un message en français qui dit quoi
      faire, si le réseau du robot est introuvable ou si une variable est fausse.

G1_INTERFACES :
  auto     les interfaces qui ont une adresse 192.168.123.x (réseau interne du robot) ; aucune :
           « réseau du robot introuvable » ;
  defaut   pas de configuration : CycloneDDS choisit comme sur l'hôte (essais sur le PC) ;
  a,b      ces interfaces-là, qui doivent exister et avoir une adresse IPv4.
G1_WIFI    interface ajoutée pour joindre l'Atelier sans câble, multicast désactivé dessus.
G1_PAIRS   adresses unicast des pairs DDS (le PC de l'Atelier), séparées par des virgules ;
           avec des pairs, MaxAutoParticipantIndex vaut 100 (Nav2 lance une quinzaine de processus).
"""
import argparse
import ipaddress
import os
import re
import subprocess
import sys
from pathlib import Path

# Réseau interne du G1 : PC1 du robot, Jetson en .164, LiDAR en .120, PC de l'Atelier en .99
RESEAU_ROBOT = ipaddress.ip_network('192.168.123.0/24')
# Nom d'une interface Linux : 15 caractères au plus ; rien qui puisse casser le XML
MOTIF_INTERFACE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,14}$')
# Avec des pairs unicast, CycloneDDS sonde les numéros de participant 0 à N sur chaque pair
MAX_PARTICIPANTS_PAIRS = 100
MODELE = Path(__file__).resolve().parent / 'cyclonedds.xml.modele'
SORTIE = '/tmp/cyclonedds.xml'


class ErreurReseau(Exception):
    """Configuration réseau impossible ; le message dit à l'utilisateur quoi faire."""


def lire_adresses(texte):
    """[(interface, adresse IPv4)] tirées de la sortie de « ip -o -4 addr », dans l'ordre."""
    adresses = []
    for ligne in texte.splitlines():
        champs = ligne.split()
        # « 3: eth0    inet 192.168.123.164/24 brd ... scope global eth0\ ... »
        if len(champs) < 4 or champs[2] != 'inet':
            continue
        nom = champs[1].split('@')[0].rstrip(':')
        try:
            adresse = ipaddress.ip_interface(champs[3]).ip
        except ValueError:
            continue
        adresses.append((nom, adresse))
    return adresses


def interfaces_robot(adresses):
    """Interfaces qui ont une adresse du réseau du robot (192.168.123.x), sans doublon, sans lo."""
    noms = []
    for nom, adresse in adresses:
        if nom != 'lo' and adresse in RESEAU_ROBOT and nom not in noms:
            noms.append(nom)
    return noms


def _noms(texte, variable):
    """Liste de noms d'interfaces séparés par des virgules ; ErreurReseau pour un nom invalide."""
    noms = [n.strip() for n in str(texte).split(',') if n.strip()]
    for nom in noms:
        if not MOTIF_INTERFACE.match(nom):
            raise ErreurReseau(f'{variable} : « {nom} » n\'est pas un nom d\'interface réseau '
                               '(lettres, chiffres, « _ . : - », 15 caractères au plus)')
    return noms


def lire_pairs(texte):
    """Adresses IP des pairs DDS, séparées par des virgules ; ErreurReseau si l'une est fausse."""
    pairs = []
    for morceau in str(texte or '').split(','):
        morceau = morceau.strip()
        if not morceau:
            continue
        try:
            pairs.append(str(ipaddress.ip_address(morceau)))
        except ValueError:
            raise ErreurReseau(f'G1_PAIRS : « {morceau} » n\'est pas une adresse IP '
                               '(exemple : G1_PAIRS=192.168.1.50)') from None
    return pairs


def choisir_interfaces(valeur, adresses):
    """Interfaces DDS du robot selon G1_INTERFACES : liste de noms, ou None pour « defaut »."""
    valeur = (valeur or 'auto').strip()
    connues = [nom for nom, _ in adresses]
    if valeur == 'defaut':
        return None
    if valeur == 'auto':
        noms = interfaces_robot(adresses)
        if not noms:
            vues = ', '.join(f'{n} ({a})' for n, a in adresses if n != 'lo') or 'aucune'
            raise ErreurReseau(
                'réseau du robot introuvable : aucune interface n\'a d\'adresse 192.168.123.x '
                f'(interfaces vues : {vues}). Sur le robot, vérifiez que le Jetson est bien '
                'relié au réseau interne ; pour un essai sur le PC, utilisez G1_INTERFACES=defaut')
        return noms
    noms = _noms(valeur, 'G1_INTERFACES')
    if not noms:
        raise ErreurReseau('G1_INTERFACES est vide : mettez auto, defaut ou des noms d\'interfaces')
    absentes = [n for n in noms if n not in connues]
    if absentes:
        raise ErreurReseau(
            f'G1_INTERFACES : interface {", ".join(absentes)} introuvable ou sans adresse IPv4 '
            f'(interfaces vues : {", ".join(connues) or "aucune"})')
    return noms


def element_interface(nom, multicast='default'):
    return f'        <NetworkInterface name="{nom}" priority="default" multicast="{multicast}"/>'


def config_cyclonedds(interfaces, wifi=None, pairs=(), modele=None):
    """Texte de la configuration CycloneDDS : interfaces du robot, Wi-Fi sans multicast, pairs."""
    texte_modele = modele if modele is not None else MODELE.read_text(encoding='utf-8')
    lignes = [element_interface(nom) for nom in interfaces]
    if wifi and wifi not in interfaces:
        lignes.append(element_interface(wifi, multicast='false'))
    decouverte = ''
    if pairs:
        pairs_xml = '\n'.join(f'        <Peer address="{p}"/>' for p in pairs)
        decouverte = ('    <Discovery>\n'
                      '      <ParticipantIndex>auto</ParticipantIndex>\n'
                      f'      <MaxAutoParticipantIndex>{MAX_PARTICIPANTS_PAIRS}</MaxAutoParticipantIndex>\n'
                      '      <Peers>\n'
                      f'{pairs_xml}\n'
                      '      </Peers>\n'
                      '    </Discovery>')
    return (texte_modele.replace('@INTERFACES@', '\n'.join(lignes))
                        .replace('@DECOUVERTE@', decouverte))


def preparer(environ, texte_ip, modele=None, sortie=SORTIE):
    """Choisit les interfaces et écrit la configuration.

    Renvoie (interfaces, uri, avertissements) : interfaces utilisées (liste, vide pour « defaut »),
    uri pour CYCLONEDDS_URI (None pour « defaut ») et messages à afficher.
    ErreurReseau si c'est impossible.
    """
    avertissements = []
    adresses = lire_adresses(texte_ip)
    interfaces = choisir_interfaces(environ.get('G1_INTERFACES'), adresses)
    wifi = (environ.get('G1_WIFI') or '').strip()
    pairs = lire_pairs(environ.get('G1_PAIRS'))
    if interfaces is None:
        if wifi or pairs:
            avertissements.append('G1_INTERFACES=defaut : G1_WIFI et G1_PAIRS sont ignorés')
        if sortie and Path(sortie).exists():
            Path(sortie).unlink()
        return [], None, avertissements
    if wifi:
        _noms(wifi, 'G1_WIFI')
        if wifi not in [nom for nom, _ in adresses]:
            avertissements.append(
                f'G1_WIFI : interface {wifi} introuvable ou sans adresse : l\'Atelier ne pourra '
                'joindre le robot que par le câble')
            wifi = ''
    if pairs and not wifi:
        avertissements.append('G1_PAIRS sans G1_WIFI : les pairs sont cherchés sur les '
                              'interfaces du robot')
    texte = config_cyclonedds(interfaces, wifi, pairs, modele)
    if sortie:
        chemin = Path(sortie)
        temporaire = chemin.with_name(chemin.name + '.tmp')
        temporaire.write_text(texte, encoding='utf-8')
        temporaire.replace(chemin)
    utilisees = interfaces + ([wifi] if wifi and wifi not in interfaces else [])
    return utilisees, f'file://{sortie}' if sortie else None, avertissements


def sortie_ip():
    """Sortie de « ip -o -4 addr » (adresses IPv4 de toutes les interfaces de l'hôte)."""
    return subprocess.run(['ip', '-o', '-4', 'addr'], capture_output=True, text=True,
                          check=True).stdout


def main(argv=None):
    analyseur = argparse.ArgumentParser(description='Configuration CycloneDDS du conteneur g1-jetson')
    sous = analyseur.add_subparsers(dest='action', required=True)
    cyclone = sous.add_parser('cyclonedds', help='choisit les interfaces et écrit la configuration')
    cyclone.add_argument('--sortie', default=SORTIE)
    cyclone.add_argument('--modele', default=str(MODELE))
    cyclone.add_argument('--ip', help='fichier contenant une sortie de « ip -o -4 addr » (essais)')
    args = analyseur.parse_args(argv)

    try:
        texte_ip = Path(args.ip).read_text(encoding='utf-8') if args.ip else sortie_ip()
        modele = Path(args.modele).read_text(encoding='utf-8')
        interfaces, uri, avertissements = preparer(os.environ, texte_ip, modele, args.sortie)
    except (ErreurReseau, OSError, subprocess.CalledProcessError) as erreur:
        print(f'g1-jetson : {erreur}', file=sys.stderr)
        return 1
    for message in avertissements:
        print(f'g1-jetson : attention, {message}', file=sys.stderr)
    print(f'interfaces={",".join(interfaces)}')
    print(f'uri={uri or ""}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
