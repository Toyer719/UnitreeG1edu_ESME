"""Voix du robot (vague 6, section 13.6 du plan) : agent Voix.

Squelette livré par l'agent Contrats ; l'agent Voix écrit ce paquet (synthèse Piper, PCM 16 kHz, file et
priorités, sorties robot, borne et robot_tts, nœud ROS 2). Les formats sont dans atelier.lieu.voix.

Contrat :
  python -m atelier.voix --lieu L [--sortie robot|borne|robot_tts] [--volume N] [--voix fr_FR-siwis-medium]
      (commande g1-voix, Python du projet avec ROS 2 chargé) : le nœud ROS 2 « voix ». Il écoute /robot/dire
      (schéma robot_dire), /voix/commande et /personnalite/active ; il publie /api/voice/request (seulement
      1001, 1003, 1004, 1005, 1006), /voix/etat et, pour la sortie borne, /voix/son (WAV dans
      atelier.lieu.voix.dossier_sons()). Ctrl+C ou SIGTERM : STOP_PLAY (1004), puis il s'arrête.
"""

MESSAGE_PAS_ENCORE_FAIT = "Pas encore fait : {quoi} (vague 6, agent Voix, section 13.6 du plan)."
