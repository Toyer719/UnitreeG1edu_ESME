// La carte 3D en direct (vague 5, section 12.3 du plan) : le robot et les piétons de /ws/etat (direct.js),
// environ 10 fois par seconde. En répétition et avec le vrai robot, la pose du robot est celle du repérage
// (champ robot de /ws/etat, avec perimee : le robot est alors estompé).

import { abonner } from '../direct.js';

// Applique un message de /ws/etat à la carte : robot ({x, y, theta, perimee?} ou null) et piétons
// ([{id, x, y, theta?}]). options : {robot (vrai), pietons (vrai)}.
export function appliquerEtat(carte, etat, options) {
  const o = Object.assign({ robot: true, pietons: true }, options || {});
  if (!etat) return;
  if (o.robot) carte.afficherRobot(etat.robot && typeof etat.robot === 'object' ? etat.robot : null);
  if (o.pietons) carte.afficherPietons(Array.isArray(etat.pietons) ? etat.pietons : []);
}

// S'abonne à /ws/etat pour la carte ; renvoie la fonction qui arrête
export function suivreEnDirect(carte, options) {
  return abonner((etat) => appliquerEtat(carte, etat, options));
}
