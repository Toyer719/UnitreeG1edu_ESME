// Appels à l'API du serveur de l'Atelier (JSON). Les erreurs deviennent des ErreurApi,
// avec la phrase du serveur (detail), la liste des points à corriger (erreurs) et,
// pour une commande qui a échoué, sa sortie.

export class ErreurApi extends Error {
  constructor(message, erreurs, sortie, statut) {
    super(message);
    this.erreurs = erreurs || [];
    this.sortie = sortie || null;
    this.statut = statut || 0;
  }
}

async function requete(methode, url, corps) {
  const options = { method: methode, headers: {} };
  if (corps !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(corps);
  }
  let reponse;
  try {
    reponse = await fetch(url, options);
  } catch (e) {
    throw new ErreurApi("Le serveur de l'Atelier ne répond pas. Est-il lancé ? Dans un terminal : g1-atelier", [], null, 0);
  }
  const texte = await reponse.text();
  let donnees = null;
  try {
    donnees = texte ? JSON.parse(texte) : null;
  } catch (e) {
    donnees = { detail: texte };
  }
  if (!reponse.ok) {
    const detail = (donnees && donnees.detail) || ('Erreur ' + reponse.status + ' du serveur');
    throw new ErreurApi(typeof detail === 'string' ? detail : JSON.stringify(detail),
      (donnees && donnees.erreurs) || [], donnees && donnees.sortie, reponse.status);
  }
  return donnees;
}

export const api = {
  lire: (url) => requete('GET', url),
  ecrire: (url, donnees) => requete('PUT', url, donnees),
  envoyer: (url, donnees) => requete('POST', url, donnees === undefined ? {} : donnees),
};

// Adresses de l'API pour un lieu et un étage
export function urlLieu(lieu) {
  return '/api/lieux/' + encodeURIComponent(lieu);
}

export function urlEtage(lieu, etage) {
  return urlLieu(lieu) + '/etages/' + encodeURIComponent(etage);
}
