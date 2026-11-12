# La voix du robot (`atelier/voix/`, vague 6, section 13.6 du plan)

Le nœud ROS 2 **`voix`** dit les phrases du robot. Elles arrivent toutes sur `/robot/dire` : les personnalités
(événements du guide relayés, salutation), la démo d'accueil (`source: accueil`), le chatbot de l'équipe, et
« Essayer » de l'Atelier (`source: atelier`). Il tourne sur le PC : le câble porte DDS jusqu'au robot.

```bash
g1-voix --lieu demo                          # réglages de départ : voix de demo.yaml (sortie, volume, nom, vitesse)
g1-voix --lieu demo --sortie borne --volume 80 --voix fr_FR-tom-medium --vitesse 1.1
g1-voix --mesurer                            # temps de synthèse de Piper sur ce PC, sans ROS ni robot
g1-voix --factice …                          # voix d'essai sans Piper (un bip), pour les essais
```

Depuis l'Atelier : `POST /api/voix/demarrer {lieu, sortie?, volume?, voix?, vitesse?}` (rôle `voix`, la démo le
lance aussi), `/arreter`, `/essayer {texte, priorite?, voix?}`, `/commande {action, …}`, `GET /api/voix/etat` et
`GET /api/voix/son/<id>` (le WAV d'une phrase, permis depuis la borne).

## Les trois sorties

| Sortie | Ce qui part | Remarque |
|---|---|---|
| `robot` | Piper sur le PC → PCM **16 000 Hz mono 16 bits petit-boutiste** → requêtes **1003** sur `/api/voice/request` | `parameter` = `{"app_name": "atelier", "stream_id": "<id de la phrase>"}`, `binary` = un morceau de 96 000 octets (3 s) au plus, nombre pair ; tous les morceaux d'une phrase ont le même `stream_id`, dans l'ordre, au moins 1 s entre deux (comme `unitree_sdk2/example/g1/audio` et `play_pcm_stream` de `unitree_sdk2_python`) |
| `borne` | rien vers le robot ; le WAV de la phrase (fréquence de la voix : 22 050 Hz) annoncé sur `/voix/son` | la page de la borne le joue (`GET /api/voix/son/<id>`) ; le volume de la voix baisse aussi le WAV |
| `robot_tts` | **1001** `{"index", "speaker_id", "text"}` | synthèse intégrée d'Unitree ; `speaker_id` 0 chinois, 1 anglais (SDK) ; **le français est à vérifier** ; `--locuteur` (1 par défaut) |

Couper : **1004** `{"app_name": "atelier"}` (comme `PlayStop` du SDK, dont la réponse est ignorée). Volume :
**1006** `{"volume": n}` (0 à 100) au démarrage si un volume est réglé, à chaque commande « volume » et au retour du
robot, puis **1005** `{}` pour le relire. Le nœud n'envoie rien d'autre : jamais 1002 (micro), jamais 1010
(lumière : le pilotage). Chaque requête est revérifiée avant de partir (`erreurs_requete_voix`).

La fin d'une phrase est estimée par la durée de son PCM, plus 0,3 s (le SDK n'a pas de « fin de lecture ») ; le nœud
n'envoie pas de 1004 à la fin naturelle d'une phrase (l'exemple Python du SDK le fait juste après le dernier
morceau : s'il coupait vraiment, la fin de la phrase serait perdue ; à vérifier à la séance 2).

## La file et les priorités

- une phrase à la fois ; `normale` attend son tour ; `haute` coupe la phrase en cours (1004, puis elle), sauf une
  phrase de sécurité ; `securite` coupe et **vide la file** ; `taire` : 1004 et file vide ;
- jamais deux flux en même temps : 0,2 s après un 1004 avant la phrase suivante ; une phrase normale qui a attendu
  plus de 30 s est oubliée ; 10 phrases en attente au plus ;
- le son est calculé dans un fil à part (Piper prend le processeur), d'avance pour les 3 premières phrases de la
  file ; une phrase dont les réglages changent (voix, sortie, volume de la borne) est recalculée ;
- robot muet (personne n'écoute `/api/voice/request`, ou pas de réponse en 1,5 s) : `robot.abonne` ou
  `robot.repond` faux dans `/voix/etat`, une erreur par phrase, jamais d'arrêt du nœud ; une phrase qui attend un
  abonné plus de 2 s est abandonnée ;
- Ctrl+C ou SIGTERM : 1004 si le robot a parlé, puis arrêt.

## Les réglages d'une phrase

Voix (`nom`) et vitesse : celles du message (`voix` de `/robot/dire`), sinon celles de la personnalité active
(`/personnalite/active`), sinon celles du nœud (`demo.yaml`, options, commande « voix »). Le **volume d'une
personnalité** (0 à 100) baisse le son de ses phrases (« Discret », à 50, parle plus bas) ; le **volume du nœud** est
celui du haut-parleur du robot (1006) et, pour la borne, celui du WAV. La `hauteur` d'une personnalité est ignorée :
Piper ne la règle pas.

Chaque phrase dite par Piper est gardée en WAV dans `journaux/voix/sons/` (`ATELIER_VOIX_SONS`, les 200
dernières) : celles de la borne sont jouées par la page, celles du robot sont la trace de ce qui a été dit.

## Temps de synthèse (mesuré le 09/11/2026, `g1-voix --mesurer`, Intel i7-12650H)

| Voix | Chargement | « Bonjour, suivez-moi ! » | « Je vous accompagne à la Salle B204. » | Phrase de 3 phrases (4 à 5 s de son) |
|---|---|---|---|---|
| Siwis (femme, 22 050 Hz) | 0,73 s | 1,74 s de son en 0,048 s | 2,81 s en 0,077 s | 4,35 s en 0,119 s |
| Tom (homme, 44 100 Hz) | 0,82 s | 1,84 s en 0,100 s | 2,99 s en 0,139 s | 5,49 s en 0,257 s |

Piper calcule 20 à 37 fois plus vite que la parole ; le rééchantillonnage à 16 kHz prend 2 ms. La voix du nœud
est chargée dès son démarrage : au critère 40, le premier morceau de « Bonjour, suivez-moi ! » part **0,09 s** après
la phrase reçue sur `/robot/dire` (0,79 s avant ce préchargement). La durée d'une
même phrase varie de quelques % d'un calcul à l'autre (le hasard de Piper : rythme plus naturel) ; le critère 40
compare donc le son reçu par le faux G1 au WAV réellement calculé par le nœud.

## Tests

- `atelier/tests/test_voix_logique.py` : file, priorités, morceaux, sorties, volume, robot muet, à fausse horloge ;
- `atelier/tests/test_voix_synthese.py` : Piper, rééchantillonnage, WAV ;
- `atelier/tests/test_voix_serveur.py` : les routes `/api/voix/*` (sans ROS) ;
- `atelier/tests/test_voix_noeud.py` : le vrai nœud contre un service voice de test (ROS 2, domaine 144) ;
- `ws/src/g1_jumeau/test/test_audio.py` : le service voice du faux G1 (requêtes vérifiées, flux suivis) ;
- critère 40 : `tests_e2e/critere_40_voix.sh` (faux G1 seul, Atelier, `g1-voix`).

## À vérifier sur le robot (séance 2)

Le son net d'un PCM 16 kHz par 1003 ; la latence entre l'envoi et le son ; que 1004 coupe tout de suite ; deux
phrases de suite avec deux `stream_id` (faut-il un 1004 entre les deux ?) ; ce que fait un 1004 envoyé juste après
le dernier morceau (comme l'exemple du SDK) ; le volume (1005, 1006) ; 1001 en français (`speaker_id` 0 et 1) ; le
code rendu par 1003 et 1004.
