// Bouton ARRÊT unique de la barre d'outils, dans les deux modes, et la touche Échap :
// POST /api/arret, puis « Débloquer » (POST /api/arret/debloquer) quand un verrou est posé (vague 5,
// section 12.4 du plan). Module de l'agent Coquille ; squelette livré par l'agent Contrats.

// options : {mode: 'simu'|'reel'|'repetition'} ; repère : [data-role=arret] (data-etat=pret|bloque)
export function monterArret(element, options) {   // eslint-disable-line no-unused-vars
  return { arreter: () => Promise.resolve(null), debloquer: () => Promise.resolve(null), detruire: () => {} };
}
