// Panneau des passants dans l'onglet Simulation (vague 4, section 11.3 du plan) : agent Passants
// (piétons crédibles, scènes, contacts). Squelette livré par l'intégrateur : simulation.js appelle
// monter(element, outils) et, en fermant l'onglet, fermer() de l'objet renvoyé. outils : {lieu, etage,
// plan, carte}. Les piétons en direct sont dans le champ pietons de /ws/etat (abonner, direct.js).

export function monter(element, outils) {   // eslint-disable-line no-unused-vars
  element.hidden = true;
  return { fermer: () => {} };
}
