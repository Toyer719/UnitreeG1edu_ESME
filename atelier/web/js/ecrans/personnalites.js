// Personnalités (vague 4, section 11.6 du plan) : écran de l'agent Équipe.
// Squelette livré par l'intégrateur : ouvrir(racine) remplit l'écran et renvoie {modifie, fermer},
// comme les autres écrans (voir app.js). À remplacer par l'agent Équipe.

export function ouvrir(racine) {
  racine.innerHTML = '<div class="carte-section vide-grand"><h2>Personnalités</h2>'
    + '<p>En construction : les modes de personnalité du robot dans ce lieu (personnalites.yaml).</p></div>';
  return { modifie: () => false, fermer: () => {} };
}
