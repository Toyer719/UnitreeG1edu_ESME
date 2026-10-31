// Écran d'accueil (« Nouveau document » de SolidWorks) : deux grandes cartes Simulation et Robot réel,
// la liste des lieux, « Nouveau lieu », la case « Répétition sans robot (faux G1) » et les
// vérifications du mode Réel (GET /api/robot/liaison), puis « Ouvrir » (vague 5, section 12.2 du
// plan). Module de l'agent Coquille ; squelette livré par l'agent Contrats.

// options : {surOuvrir({mode, repetition, lieu, etage}), surPilotageSansLieu()} ; renvoie {fermer()}
export function afficherAccueil(racine, options) {   // eslint-disable-line no-unused-vars
  return { fermer: () => {} };
}
