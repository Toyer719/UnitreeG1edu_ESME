// Messages à l'utilisateur, en bas de l'écran : informations (qui disparaissent seules),
// avertissements et erreurs (qui restent jusqu'à ce qu'on les ferme).

import { ErreurApi } from './api.js';

function zone() {
  return document.getElementById('messages');
}

function element(balise, classe, texte) {
  const e = document.createElement(balise);
  if (classe) e.className = classe;
  if (texte !== undefined) e.textContent = texte;
  return e;
}

// genre : info, succes, avertissement ou erreur. details : liste de phrases. sortie : texte d'une commande.
export function afficherMessage(texte, genre, details, sortie) {
  genre = genre || 'info';
  const boite = element('div', 'message message-' + genre);
  boite.setAttribute('role', genre === 'erreur' ? 'alert' : 'status');
  const fermer = element('button', 'message-fermer', '×');
  fermer.title = 'Fermer ce message';
  fermer.addEventListener('click', () => boite.remove());
  boite.appendChild(fermer);
  boite.appendChild(element('p', 'message-texte', texte));
  if (details && details.length) {
    const liste = element('ul', 'message-details');
    details.forEach((d) => liste.appendChild(element('li', '', d)));
    boite.appendChild(liste);
  }
  if (sortie) {
    const plus = element('details', 'message-sortie');
    plus.appendChild(element('summary', '', 'Voir le message complet de la commande'));
    plus.appendChild(element('pre', '', sortie));
    boite.appendChild(plus);
  }
  zone().appendChild(boite);
  if (genre === 'info' || genre === 'succes') {
    setTimeout(() => boite.remove(), 6000);
  }
  return boite;
}

export function afficherErreur(e) {
  if (e instanceof ErreurApi) {
    return afficherMessage(e.message, 'erreur', e.erreurs, e.sortie);
  }
  console.error(e);
  return afficherMessage('Erreur inattendue dans la page : ' + (e && e.message ? e.message : e)
    + '. Rechargez la page (touche F5).', 'erreur');
}

// Rapport de vérification du lieu renvoyé après un enregistrement : {ok, erreurs, avertissements}
export function afficherRapport(rapport, reussite) {
  if (reussite) afficherMessage(reussite, 'succes');
  if (!rapport) return;
  if (rapport.erreurs && rapport.erreurs.length) {
    afficherMessage('Enregistré, mais le lieu a encore des problèmes à corriger avant de faire rouler le robot :',
      'avertissement', rapport.erreurs);
  }
}

export function viderMessages() {
  zone().innerHTML = '';
}
