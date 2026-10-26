// Pilotage (vague 4, section 11.5 du plan) : écran de l'agent Pilotage et danses.
// Squelette livré par l'intégrateur : ouvrir(racine) remplit l'écran et renvoie {modifie, fermer},
// comme les autres écrans (voir app.js). À remplacer par l'agent Pilotage et danses.

export function ouvrir(racine) {
  racine.innerHTML = '<div class="carte-section vide-grand"><h2>Pilotage</h2>'
    + '<p>En construction : postures, marche au joystick, gestes, voix, LED, danses du robot et chorégraphies, par le conteneur du Jetson.</p></div>';
  return { modifie: () => false, fermer: () => {} };
}
