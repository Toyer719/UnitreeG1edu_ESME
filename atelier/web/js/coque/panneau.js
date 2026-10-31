// Panneau de tâches à droite (PropertyManager de SolidWorks) : propriétés de l'élément choisi, ou
// formulaire de la commande en cours, avec ✓ OK et ✗ Annuler ; il défile seul (vague 5, section 12.2
// du plan). Module de l'agent Coquille ; squelette livré par l'agent Contrats.

// options : {titre, aide, ok(), annuler()} ; renvoie {corps (élément où écrire), fermer()}
export function ouvrirPanneau(element, options) {   // eslint-disable-line no-unused-vars
  return { corps: element, fermer: () => {} };
}
