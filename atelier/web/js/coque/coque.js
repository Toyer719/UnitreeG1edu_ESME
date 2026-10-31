// La coque de l'Atelier (vague 5, section 12.2 du plan) : écran d'accueil (Simulation ou Robot réel),
// puis l'espace de travail à la SolidWorks (barre d'outils, ruban, arbre, vue centrale, panneau de
// tâches, barre d'état). Module de l'agent Coquille ; squelette livré par l'agent Contrats (exports du
// contrat, sans effet tant que app.js ne l'appelle pas).

export const MODES = ['simu', 'reel', 'repetition'];

// Clés du stockage du navigateur (localStorage), toutes préfixées par « atelier. » (section 12.2)
export const CLES_MEMOIRE = {
  mode: 'atelier.mode',                 // simu | reel
  repetition: 'atelier.repetition',     // 1 : Réel sans robot (faux G1) ; 0 sinon
  theme: 'atelier.theme',               // sombre | clair
  lieu: 'atelier.lieu',
  etage: 'atelier.etage',
  onglet: 'atelier.onglet.',            // + simu | reel : dernier onglet du ruban
  vue: 'atelier.vue.',                  // + simu | reel : 3d | plan | camera
  calques: 'atelier.calques',           // JSON {nuage: true, carte2d: false…}
  arbreReplie: 'atelier.arbre.replie',
  rubanReplie: 'atelier.ruban.replie',
  // anciennes clés, encore écrites pour les écrans d'avant
  modeSimulation: 'atelier.mode-simulation',   // simu | repetition | robot
  modeScan: 'atelier.scan.mode',               // simu | robot
  repetitionScan: 'atelier.scan.repetition',
};

// Démarre l'Atelier : l'accueil, ou directement l'espace de travail si l'adresse a un hash (#salles…)
// ou ?recharger. Squelette : à écrire par l'agent Coquille.
export function demarrerCoque(options) {   // eslint-disable-line no-unused-vars
  return Promise.resolve(null);
}

// Ouvre l'espace de travail : {mode: 'simu'|'reel', repetition, lieu, etage}
export function ouvrirEspace(choix) {   // eslint-disable-line no-unused-vars
  return Promise.resolve(null);
}

export function retourAccueil() {}

// 'simu' | 'reel' | 'repetition' (Réel avec la case « Répétition sans robot »)
export function modeCourant() {
  return 'simu';
}

// Exécute une commande du ruban par son identifiant (registre COMMANDES de ruban.js)
export function ouvrirCommande(id) {   // eslint-disable-line no-unused-vars
  return false;
}
