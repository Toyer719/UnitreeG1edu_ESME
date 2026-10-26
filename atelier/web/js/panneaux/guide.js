// Panneau du comportement du guide dans l'onglet Simulation (vague 4, section 11.4 du plan) :
// agent Comportement du guide (événements au visiteur, retour, accompagnement, robot perdu).
// Squelette livré par l'intégrateur : simulation.js appelle monter(element, outils) et, en
// fermant l'onglet, fermer() de l'objet renvoyé. outils : {lieu, etage, plan, carte}. Les données en
// direct viennent de abonner() (direct.js) : champs guide et evenements de /ws/etat.

export function monter(element, outils) {   // eslint-disable-line no-unused-vars
  element.hidden = true;
  return { fermer: () => {} };
}
