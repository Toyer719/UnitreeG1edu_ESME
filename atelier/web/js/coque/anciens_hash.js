// Anciennes adresses de l'Atelier (#salles, #simulation…) : elles mènent toujours au bon endroit
// (vague 5, section 12.2 du plan). Module de l'agent Coquille ; table livrée par l'agent Contrats.
// mode : 'simu' ou 'reel' imposé ; 'memoire' : le mode retenu (atelier.mode, et pour #simulation
// atelier.mode-simulation : simu → Simulation, repetition → Réel avec la répétition, robot → Réel ;
// pour #scan atelier.scan.mode : simu → Simulation › Avancé › Scan simulé, robot → Réel › Scanner).
// commande : identifiant du registre COMMANDES de ruban.js ; null : l'écran seul. accueil : l'écran
// d'accueil. sansLieu : s'ouvre même sans lieu choisi.

export const ANCIENS_HASH = {
  lieux: { accueil: true },
  monde: { mode: 'simu', ecran: 'monde', commande: 'monde.choisir' },
  carte: { mode: 'memoire', ecran: 'carte', commande: null },
  salles: { mode: 'memoire', ecran: 'salles', commande: 'salles.salle' },
  itineraires: { mode: 'memoire', ecran: 'itineraires', commande: 'itineraires.noeud' },
  zones: { mode: 'memoire', ecran: 'zones', commande: 'zones.interdite' },
  simulation: { mode: 'memoire', ecran: 'simulation', commande: null },
  scan: { mode: 'memoire', ecran: 'scan', commande: null },
  pilotage: { mode: 'reel', ecran: 'pilotage', commande: null, sansLieu: true },
  personnalites: { mode: 'memoire', ecran: 'personnalites', commande: 'personnalites.ouvrir' },
  dialogues: { mode: 'memoire', ecran: 'dialogues', commande: 'dialogues.ouvrir' },
  camera: { mode: 'memoire', ecran: 'camera', commande: 'camera.ouvrir' },
};

// {mode, ecran, commande, accueil, sansLieu} d'un hash (« #salles » ou « salles »), ou null s'il est inconnu
export function destinationDuHash(hash) {
  const nom = String(hash || '').replace(/^#/, '');
  return Object.prototype.hasOwnProperty.call(ANCIENS_HASH, nom) ? ANCIENS_HASH[nom] : null;
}
