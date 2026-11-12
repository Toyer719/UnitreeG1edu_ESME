// Textes de la borne visiteur (vague 6, section 13.5 du plan) : les mots des boutons et des fenêtres, en
// français et en anglais (demo.yaml : borne.langue). Les phrases des écrans viennent du serveur (texte, detail).
// Module de l'agent Borne et orchestrateur ; aucune donnée insérée en HTML (textContent seulement).

export const LANGUES = ['fr', 'en'];

// Typographie française : une espace insécable avant ? ! : ; et à l'intérieur des guillemets (« … »), et un
// trait d'union insécable dans les mots composés (« Suivez-moi ») : une ponctuation ou une moitié de mot ne se
// retrouve jamais seule en début de ligne (aussi pour l'écran Démo de l'Atelier : corrections de la vague 6)
export function insecables(t) {
  return String(t === undefined || t === null ? '' : t)
    .replace(/ ([?!:;»])/g, '\u00a0$1').replace(/« /g, '«\u00a0')
    .replace(/([A-Za-zÀ-ÿ])-([A-Za-zÀ-ÿ])/g, '$1\u2011$2');
}

export const TEXTES = {
  fr: {
    question: 'Je vous accompagne à',
    salleQuestion: '« {nom} » ?',
    oui: 'Oui, allons-y !',
    non: 'Non, merci',
    patience: 'Un instant…',
    daccord: 'D\'accord',
    autreEtage: '« {nom} » est à un autre étage : demandez à l\'accueil.',
    pasDeSalle: 'Aucune salle n\'est proposée pour le moment.',
    robotMuet: 'Le robot ne répond pas. Réessayez dans un instant.',
    connexion: 'Connexion au robot perdue… nouvel essai.',
    etage: 'Étage',
    operateur: 'Espace opérateur',
    code: 'Code opérateur',
    codeAide: 'Tapez le code donné par l\'équipe.',
    valider: 'Valider',
    effacer: 'Effacer',
    fermer: 'Fermer',
    codeFaux: 'Code faux.',
    pause: 'Mettre en pause',
    reprendre: 'Reprendre',
    ramener: 'Ramener à l\'accueil',
    fait: 'C\'est fait.',
    progression: 'Progression du trajet',
    salles: 'Les salles',
  },
  en: {
    question: 'Shall I take you to',
    salleQuestion: '“{nom}”?',
    oui: 'Yes, let\'s go!',
    non: 'No, thanks',
    patience: 'Just a moment…',
    daccord: 'OK',
    autreEtage: '“{nom}” is on another floor: please ask at the reception.',
    pasDeSalle: 'No room is offered at the moment.',
    robotMuet: 'The robot does not answer. Please try again in a moment.',
    connexion: 'Connection to the robot lost… trying again.',
    etage: 'Floor',
    operateur: 'Staff area',
    code: 'Staff code',
    codeAide: 'Type the code given by the team.',
    valider: 'OK',
    effacer: 'Erase',
    fermer: 'Close',
    codeFaux: 'Wrong code.',
    pause: 'Pause',
    reprendre: 'Resume',
    ramener: 'Back to the reception',
    fait: 'Done.',
    progression: 'Trip progress',
    salles: 'Rooms',
  },
};

// Le texte d'une clé dans la langue (le français si la langue ou la clé manquent) ; {nom} remplacé.
export function texte(langue, cle, valeurs) {
  const table = TEXTES[langue] || TEXTES.fr;
  let t = table[cle];
  if (t === undefined) t = TEXTES.fr[cle];
  if (t === undefined) t = cle;
  Object.keys(valeurs || {}).forEach((k) => {
    t = t.split('{' + k + '}').join(String(valeurs[k]));
  });
  return t;
}

// La salle de la question de la confirmation : « Salle B204 » ? en français (espaces insécables), “Salle B204”? en
// anglais (corrections de la vague 6 : un visiteur anglophone lisait « Shall I take you to « CDI » ? »)
export function questionSalle(langue, nom) {
  const q = texte(langue, 'salleQuestion', { nom: nom });
  return langue === 'en' ? q : insecables(q);
}

// Petits dessins des salles : l'étiquette de salles.yaml (pictogramme du serveur) ; à défaut, un mot du nom
const MOTS_PICTOGRAMMES = [
  ['toilettes', ['toilette', 'wc', 'sanitaire']], ['sortie', ['sortie', 'exit']],
  ['cafeteria', ['cafét', 'cafet', 'cantine', 'self', 'restaur']], ['cdi', ['cdi', 'biblioth', 'médiath', 'mediath']],
  ['infirmerie', ['infirm', 'santé']], ['secretariat', ['secrét', 'secret', 'administr', 'bureau']],
  ['ascenseur', ['ascenseur']], ['labo', ['labo', 'physique', 'chimie', 'science']],
  ['gymnase', ['gymnase', 'gym', 'sport']], ['amphi', ['amphi', 'conférence', 'conference', 'auditorium']],
];

function sansAccent(t) {
  return String(t || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
}

export function pictogrammeDe(salle) {
  if (salle && salle.pictogramme) return salle.pictogramme;
  const nom = sansAccent(salle && salle.nom);
  for (let i = 0; i < MOTS_PICTOGRAMMES.length; i++) {
    const mots = MOTS_PICTOGRAMMES[i][1];
    for (let j = 0; j < mots.length; j++) {
      if (nom.indexOf(sansAccent(mots[j])) >= 0) return MOTS_PICTOGRAMMES[i][0];
    }
  }
  return 'porte';
}
