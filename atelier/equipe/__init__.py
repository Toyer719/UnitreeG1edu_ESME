"""Emplacements de l'équipe (vague 4, section 11.6 du plan) : logique sans ROS, agent Équipe.

  dialogue.py  le chatbot à règles de dialogues.yaml (Chatbot.repondre : la règle, la réponse et
               l'action) et decider() (ce que le nœud en fait selon l'instant : robot piloté, visite
               en cours) ; utilisé par l'onglet Dialogues (essai d'une phrase, sans robot) et par le
               nœud dialogue du paquet g1_equipe ;
  relais.py    événements du guide → phrases à dire (/robot/dire), avec les phrases de la
               personnalité active ; salutation d'un visiteur vu par la caméra ;
  camera.py    ce que voit une caméra placée comme dans camera.yaml, et le message de
               /visiteurs/detectes (pour la fausse caméra des essais, et comme modèle).

Tout est un EXEMPLE, que l'équipe peut remplacer : seuls comptent les fichiers du lieu
(atelier.lieu.equipe, avec leurs schémas) et les sujets ROS 2 (SUJETS_EQUIPE), décrits dans
docs/integration-equipe.md.

Attention : l'image du Jetson ne copie que atelier/lieu/ et atelier/scan/slam_client.py (section
10.2) ; pour faire tourner le nœud dialogue dans le conteneur, l'agent Pilotage (propriétaire de
docker/ en vague 4) doit y ajouter atelier/equipe/ et le paquet g1_equipe.
"""
