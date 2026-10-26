// Dialogues (vague 4, section 11.6 du plan) : écran de l'agent Équipe.
// Squelette livré par l'intégrateur : ouvrir(racine) remplit l'écran et renvoie {modifie, fermer},
// comme les autres écrans (voir app.js). À remplacer par l'agent Équipe.

export function ouvrir(racine) {
  racine.innerHTML = '<div class="carte-section vide-grand"><h2>Dialogues</h2>'
    + '<p>En construction : le chatbot à règles du lieu (dialogues.yaml).</p></div>';
  return { modifie: () => false, fermer: () => {} };
}
