# g1_accueil : la démo d'accueil

Le nœud `accueil` mène la démo d'accueil du G1 (vague 6, section 13.4 du plan) : un visiteur s'approche
(ou touche la borne), le robot le salue, le visiteur choisit une salle sur la borne, le robot l'y
accompagne, annonce l'arrivée et revient seul à l'accueil. Après un arrêt, un blocage ou une panne, la
démo se met en pause et ne repart jamais seule.

```bash
g1-accueil --lieu demo --etage rdc       # lancé par l'Atelier : Équipe › Démo › Lancer la démo
```

Squelette livré par l'agent Contrats ; paquet de l'agent Borne et orchestrateur.
