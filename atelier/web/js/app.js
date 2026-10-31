// Atelier G1 : point d'entrée de la page. Vague 5 (section 12.2 du plan) : tout passe par la coque
// (js/coque/coque.js) : l'écran d'accueil (Simulation ou Robot réel), puis l'espace de travail à la
// SolidWorks (barre d'outils, ruban, arbre, vue centrale, panneau de tâches, barre d'état). Les écrans
// (js/ecrans/*.js) sont chargés à la demande par la coque (table ECRANS de coque.js).

import { demarrerCoque } from './coque/coque.js';

demarrerCoque();
