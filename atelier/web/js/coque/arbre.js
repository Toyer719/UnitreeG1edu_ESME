// Arbre du lieu (FeatureManager de SolidWorks) : Lieu ▸ Étage ▸ Carte, Monde, Points (★ Accueil
// d'abord), Itinéraires, Zones, Scans, Équipe ; pastilles ⚠ de « Vérifier le lieu » (vague 5,
// section 12.2 du plan). Module de l'agent Coquille ; squelette livré par l'agent Contrats.

// options : {lieu, etage, mode, surChoix({genre, id}), surDoubleClic({genre, id})}
// Repères : chaque nœud porte data-noeud="<genre>:<id>" (salle:b204, etage:rdc, carte:rdc…).
export function construireArbre(element, options) {   // eslint-disable-line no-unused-vars
  return { rafraichir: () => Promise.resolve(), choisir: () => {}, detruire: () => {} };
}
