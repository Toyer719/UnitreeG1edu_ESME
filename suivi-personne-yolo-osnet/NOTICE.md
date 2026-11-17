# Provenance et licences

Le code d'intégration de ce dépôt est distribué sous GNU AGPL version 3
(voir `LICENSE`), pour la distribution open source de l'application avec
Ultralytics. Ultralytics et les modèles YOLO sont proposés par leur auteur
sous AGPL-3.0 ou licence commerciale distincte :
https://www.ultralytics.com/license

L'implémentation OSNet intégrée dans `suivi_personne/vendor/osnet.py`
provient de Kaiyang Zhou, sous licence MIT. Son copyright et son texte de
licence sont conservés dans `suivi_personne/vendor/LICENSE`.
Le code original est inchangé ; le wrapper de prétraitement est propre à ce dépôt.

Les poids ne sont pas inclus dans le dépôt Git. Ils sont téléchargés depuis
leurs auteurs, avec versions et empreintes épinglées dans `modeles.py`.
Les conditions des poids et données d'entraînement restent celles de leurs
auteurs ; la licence MIT du code OSNet n'est pas présentée comme une licence
universelle des données MSMT17.

- YOLO11n : https://github.com/ultralytics/assets/releases/tag/v8.3.0
- OSNet x0.25 MSMT17 : https://huggingface.co/kaiyangzhou/osnet
- OSNet : https://github.com/KaiyangZhou/deep-person-reid

Les autres bibliothèques sont installées via pip et conservent leurs licences
respectives. Aucun binaire de dépendance, secret SSH ou fichier vidéo n'est embarqué.
