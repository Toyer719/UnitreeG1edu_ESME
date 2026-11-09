"""Voix du robot (vague 6, section 13.6 du plan) : agent Voix.

Les phrases à dire arrivent sur /robot/dire (personnalités par le relais des événements du guide, démo d'accueil,
chatbot, Atelier « Essayer ») ; le nœud ROS 2 « voix » (commande g1-voix, sur le PC) les dit par une des trois
sorties : le haut-parleur du robot (Piper sur le PC → PCM 16 kHz → service voice, api 1003, comme les exemples du
SDK d'Unitree), la borne (le même son en WAV, joué par la page /borne) ou la synthèse du robot (api 1001, langues à
vérifier). Les formats et valeurs du contrat sont dans atelier.lieu.voix.

  synthese.py  Piper, rééchantillonnage à 16 kHz, WAV ; voix d'essai sans Piper (SyntheseFactice)
  logique.py   file d'attente, priorités (normale, haute, securite), sorties, volume, robot muet : sans ROS
  noeud.py     le nœud rclpy, le fil de synthèse, g1-voix et g1-voix --mesurer

Contrat :
  python -m atelier.voix --lieu L [--sortie robot|borne|robot_tts] [--volume N] [--voix fr_FR-siwis-medium]
      (commande g1-voix, Python du projet avec ROS 2 chargé) : le nœud ROS 2 « voix ». Il écoute /robot/dire
      (schéma robot_dire), /voix/commande et /personnalite/active ; il publie /api/voice/request (seulement
      1001, 1003, 1004, 1005, 1006), /voix/etat et, pour la sortie borne, /voix/son (WAV dans
      atelier.lieu.voix.dossier_sons()). Ctrl+C ou SIGTERM : STOP_PLAY (1004), puis il s'arrête.
"""

MESSAGE_PAS_ENCORE_FAIT = "Pas encore fait : {quoi} (vague 6, agent Voix, section 13.6 du plan)."
