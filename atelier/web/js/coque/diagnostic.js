// « Vérifier le robot » dans l'Atelier (vague 6, section 13.2 du plan) : module de l'agent Diagnostic.
//
// Contrat (les outils de la coque : {mode, repetition, lieu, etage, message(texte, genre, details),
// confirmer(texte, options) → promesse, ouvrirCommande(id), api}) :
//   monterDiagnosticAccueil(element, outils) → {rafraichir(), detruire()}
//       sous les vérifications de la carte « Robot réel » de l'accueil : le bouton « Vérifier le robot »
//       ([data-role=verifier-robot]) et le résumé du dernier diagnostic ([data-role=diagnostic-resume]) ;
//   monterDiagnosticBarre(element, outils) → {detruire()}
//       dans la barre d'outils, en Réel (et répétition) seulement : le bouton [data-role=verifier-robot], avec une
//       pastille de l'état du dernier diagnostic ;
//   ouvrirDiagnostic(outils, options) → promesse
//       la fenêtre du diagnostic dans la page ([data-role=diagnostic]), sous la barre d'outils (elle ne couvre
//       jamais l'ARRÊT) : chaque vérification en [data-verification=<id>][data-etat=ok|attention|probleme|inconnu],
//       ce qui a été vu, quoi faire et, s'il y en a une, le bouton de son action ([data-action=<id>]) qui demande
//       confirmation dans la page (outils.confirmer), puis POST /api/robot/diagnostic/<action> {confirme: true} ;
//       « Vérifier à nouveau » ([data-role=reverifier]) ; Échap et ✗ la ferment. options.relancer (vrai par
//       défaut) : refaire le diagnostic ; faux : montrer le dernier ;
//   executer(nom, valeur, outils)
//       la commande du ruban robot.verifier (nom « verifier ») : ouvre la fenêtre du diagnostic.
// Données : GET /api/robot/diagnostic?mode=reel|repetition (schéma diagnostic), GET …/dernier. Textes simples, sans
// jargon ROS (le détail technique est dans l'infobulle) ; aucune donnée insérée en HTML (textContent) ; jamais de
// fenêtre du navigateur (confirm, alert). Le diagnostic ne fait jamais bouger le robot ; une action ne part
// qu'après un clic et la confirmation.

import { fenetreOuverte } from './confirmation.js';
import { icone } from './icones.js';

export const ETATS_VERIFICATION = ['ok', 'attention', 'probleme', 'inconnu'];
export const LIBELLES_ETATS = { ok: 'OK', attention: 'Attention', probleme: 'Problème', inconnu: 'Inconnu' };
export const GROUPES_DIAGNOSTIC = [['reseau', 'Câble et réseau'], ['robot', 'Robot'], ['jetson', 'Jetson']];
// Copie des actions de atelier.lieu.diagnostic.ACTIONS_DIAGNOSTIC (libellé, phrase de confirmation : le test les
// compare), plus le bouton de la confirmation et le texte pendant l'action
export const ACTIONS_DIAGNOSTIC = {
  'demarrer-services': {
    libelle: 'Démarrer les services de cartographie',
    confirmation: 'Démarrer lidar_driver et unitree_slam sur le robot ? Ils servent au scan et au repérage. '
      + 'Le robot ne bouge pas.',
    ok: 'Démarrer', attente: 'Démarrage… (20 s au plus)',
  },
  'retablir-cable': {
    libelle: 'Rétablir la connexion du câble',
    confirmation: 'Rallumer la connexion « robot-g1 » du câble Ethernet ? Le Wi-Fi n\'est pas touché.',
    ok: 'Rétablir', attente: 'Connexion…',
  },
  'cable-automatique': {
    libelle: 'La rétablir seule à chaque branchement',
    confirmation: 'Rallumer seule la connexion « robot-g1 » à chaque branchement du câble ? Le PC garde Internet '
      + 'par le Wi-Fi. On peut revenir en arrière avec robot.sh.',
    ok: 'Oui, à chaque fois', attente: 'Réglage…',
  },
};
export const MODES_DIAGNOSTIC = { reel: 'Vrai robot', repetition: 'Répétition sans robot (faux G1)' };
const TEXTE_ATTENTE = 'Je regarde le câble, le réseau, les services, la batterie et le Jetson…';
const TEXTE_INVITATION = 'Un contrôle complet en quelques secondes : câble, réseau, services, mode, batterie et '
  + 'Jetson, avec un conseil pour chaque problème.';

// État du module : derniers résultats (par mode), diagnostics en cours, abonnés, fenêtre ouverte
const memoire = { derniers: { reel: null, repetition: null }, enCours: {}, abonnes: [], fenetre: null };

function el(balise, classe, texte) {
  const e = document.createElement(balise);
  if (classe) e.className = classe;
  if (texte !== undefined && texte !== null) e.textContent = texte;
  return e;
}

// ---------------------------------------------------------------- fonctions pures (testées)

// Le mode du diagnostic d'après les outils de la coque : 'reel', 'repetition', ou null en simulation
export function modeDiagnostic(outils) {
  const o = outils || {};
  if (o.mode === 'repetition') return 'repetition';
  if (o.mode === 'reel') return o.repetition ? 'repetition' : 'reel';
  return null;
}

export function urlDiagnostic(mode, rapide) {
  return '/api/robot/diagnostic?mode=' + encodeURIComponent(mode) + (rapide ? '&rapide=1' : '');
}

// « 1 point à régler », « 3 points à régler »… d'après le résumé
export function nombreARegler(d) {
  const r = (d && d.resume) || {};
  return (r.attention || 0) + (r.probleme || 0);
}

// Le titre du bandeau : « Tout est prêt ! », « 2 points à régler »…
export function titreBandeau(d) {
  if (!d) return 'Vérification…';
  const n = nombreARegler(d);
  if (n) return n + (n > 1 ? ' points à régler' : ' point à régler');
  if (d.etat === 'inconnu') return 'Rien à régler pour le moment';
  return 'Tout est prêt !';
}

// Les compteurs affichés : [[etat, texte]] pour les états présents (« 12 OK », « 1 problème »…)
export function compteurs(d) {
  const r = (d && d.resume) || {};
  const noms = { ok: ['OK', 'OK'], attention: ['attention', 'attentions'], probleme: ['problème', 'problèmes'],
    inconnu: ['inconnu', 'inconnus'] };
  return ETATS_VERIFICATION.filter((e) => r[e]).map((e) => [e, r[e] + ' ' + noms[e][r[e] > 1 ? 1 : 0]]);
}

// Les vérifications rangées par groupe, dans l'ordre du serveur : [[groupe, titre, [v…]]]
export function parGroupe(verifications) {
  return GROUPES_DIAGNOSTIC.map((g) => [g[0], g[1], (verifications || []).filter((v) => v.groupe === g[0])])
    .filter((g) => g[2].length);
}

// Heure locale « 14:03 » d'une date ISO du serveur (sans dépendre du fuseau du navigateur)
export function heureDe(dateIso) {
  const m = /T(\d\d):(\d\d)/.exec(String(dateIso || ''));
  return m ? m[1] + ':' + m[2] : '';
}

// Nombre à la française : 1,8
export function nombreFr(x, chiffres) {
  const n = Number(x);
  if (!isFinite(n)) return '?';
  const p = Math.pow(10, chiffres === undefined ? 1 : chiffres);
  return String(Math.round(n * p) / p).replace('.', ',');
}

// « il y a 2 min » depuis un instant (millisecondes), pour le résumé de l'accueil
export function depuis(instantMs, maintenantMs) {
  const s = Math.max(0, Math.round(((maintenantMs === undefined ? Date.now() : maintenantMs) - instantMs) / 1000));
  if (s < 45) return 'à l\'instant';
  const min = Math.round(s / 60);
  if (min < 60) return 'il y a ' + min + ' min';
  const h = Math.floor(min / 60);
  return 'il y a ' + h + ' h' + (min % 60 ? ' ' + String(min % 60).padStart(2, '0') : '');
}

const GRAVITE = { ok: 0, inconnu: 1, attention: 2, probleme: 3 };

// Les vérifications à régler, la plus grave d'abord (à gravité égale : dans l'ordre du diagnostic)
export function aRegler(d) {
  const liste = ((d && d.verifications) || []).filter((v) => v.etat === 'probleme' || v.etat === 'attention');
  return liste.map((v, i) => [v, i]).sort((a, b) => (GRAVITE[b[0].etat] - GRAVITE[a[0].etat]) || (a[1] - b[1]))
    .map((x) => x[0]);
}

// La phrase du bandeau, sous son titre : quoi faire d'abord (sans répéter « 2 points à régler »)
export function phraseBandeau(d) {
  if (!d) return TEXTE_ATTENTE;
  const liste = aRegler(d);
  if (liste.length) return 'D\'abord : ' + liste[0].titre + '. ' + (liste[0].conseil || '');
  if (d.etat === 'inconnu') return d.message || '';
  return 'Tout ce qui a été vérifié répond comme il faut.';
}

// Le résumé d'une ligne de l'accueil : « 2 points à régler : Services de cartographie, Batterie. »
export function phraseResume(d) {
  if (!d) return TEXTE_INVITATION;
  const liste = aRegler(d);
  if (liste.length) {
    const titres = liste.slice(0, 2).map((v) => v.titre).join(', ');
    const reste = liste.length > 2 ? ' et ' + (liste.length - 2) + (liste.length > 3 ? ' autres' : ' autre') : '';
    return titreBandeau(d) + ' : ' + titres + reste + '.';
  }
  const inconnus = ((d.resume || {}).inconnu) || 0;
  if (inconnus) return 'Rien à régler ; ' + inconnus + (inconnus > 1 ? ' points n\'ont' : ' point n\'a')
    + ' pas pu être vérifié' + (inconnus > 1 ? 's' : '') + '.';
  return 'Tout est prêt : le robot répond comme il faut.';
}

// ---------------------------------------------------------------- données

function notifier() {
  memoire.abonnes.slice().forEach((f) => {
    try {
      f();
    } catch (e) {
      console.error(e);
    }
  });
}

function abonner(f) {
  memoire.abonnes.push(f);
  return () => {
    const i = memoire.abonnes.indexOf(f);
    if (i >= 0) memoire.abonnes.splice(i, 1);
  };
}

function retenir(d) {
  if (!d || !d.mode) return;
  // l'heure du diagnostic (date du serveur, sur ce PC), sinon l'heure de réception
  const quand = Date.parse(d.date);
  memoire.derniers[d.mode] = { resultat: d, recu: isFinite(quand) ? quand : Date.now() };
  notifier();
}

// Le diagnostic du mode : celui qui tourne déjà, sinon un nouveau (GET /api/robot/diagnostic)
export function lancerDiagnostic(outils, mode, rapide) {
  const cle = mode + (rapide ? '-rapide' : '');
  if (memoire.enCours[cle]) return memoire.enCours[cle];
  const promesse = outils.api.lire(urlDiagnostic(mode, rapide)).then((d) => {
    retenir(d);
    return d;
  });
  memoire.enCours[cle] = promesse;
  notifier();
  const fin = () => {
    delete memoire.enCours[cle];
    notifier();
  };
  promesse.then(fin, fin);
  return promesse;
}

function enCours(mode) {
  return !!(memoire.enCours[mode] || memoire.enCours[mode + '-rapide']);
}

// Le dernier diagnostic du mode connu du serveur (GET …/dernier), sans en refaire un
function chargerDernier(outils, mode) {
  if (!outils || !outils.api || !mode) return Promise.resolve(null);
  return outils.api.lire('/api/robot/diagnostic/dernier?mode=' + encodeURIComponent(mode)).then((d) => {
    if (d && d.mode === mode && !memoire.derniers[mode]) retenir(d);
    return d;
  }, () => null);
}

// ---------------------------------------------------------------- la fenêtre

function pastille(etat) {
  const p = el('span', 'diagnostic-pastille');
  p.setAttribute('data-etat', etat);
  p.setAttribute('aria-hidden', 'true');
  return p;
}

function ligneVerification(v, f) {
  const li = el('li', 'diagnostic-ligne');
  li.setAttribute('data-verification', v.id);
  li.setAttribute('data-etat', v.etat);
  if (v.technique) li.title = v.technique;
  li.appendChild(pastille(v.etat));
  const textes = el('div', 'diagnostic-textes');
  const haut = el('div', 'diagnostic-ligne-haut');
  haut.appendChild(el('span', 'diagnostic-titre', v.titre));
  const etiquette = el('span', 'diagnostic-etiquette', LIBELLES_ETATS[v.etat] || v.etat);
  etiquette.setAttribute('data-etat', v.etat);
  haut.appendChild(etiquette);
  textes.appendChild(haut);
  textes.appendChild(el('p', 'diagnostic-detail', v.detail));
  if (v.etat !== 'ok' && v.conseil) {
    const conseil = el('p', 'diagnostic-conseil');
    conseil.appendChild(icone('chevron', 14));
    conseil.appendChild(el('span', '', v.conseil));
    textes.appendChild(conseil);
  }
  if (v.action && ACTIONS_DIAGNOSTIC[v.action]) {
    const a = ACTIONS_DIAGNOSTIC[v.action];
    const b = el('button', 'bouton bouton-principal diagnostic-action');
    b.type = 'button';
    b.setAttribute('data-action', v.action);
    b.appendChild(icone(v.action === 'demarrer-services' ? 'lancer' : 'cable', 16));
    b.appendChild(el('span', '', a.libelle));
    b.title = 'Demande une confirmation avant de faire quoi que ce soit.';
    b.addEventListener('click', () => f.action(v.action, b));
    textes.appendChild(b);
  }
  li.appendChild(textes);
  return li;
}

function dessinerResultat(f, d) {
  const corps = f.corps;
  const defilement = corps.scrollTop;          // redessinée (action, nouveau diagnostic) : la liste ne saute pas
  corps.textContent = '';
  f.racine.setAttribute('data-etat', d ? d.etat : 'attente');
  f.racine.setAttribute('data-mode', f.mode);
  f.bandeau.setAttribute('data-etat', d ? d.etat : 'attente');
  f.bandeau.querySelector('.diagnostic-pastille').setAttribute('data-etat', d ? d.etat : 'attente');
  f.titreBandeau.textContent = titreBandeau(d);
  f.messageBandeau.textContent = phraseBandeau(d);
  f.compteurs.textContent = '';
  compteurs(d).forEach((c) => {
    const x = el('span', 'diagnostic-compteur', c[1]);
    x.setAttribute('data-etat', c[0]);
    f.compteurs.appendChild(x);
  });
  if (!d) return;
  parGroupe(d.verifications).forEach((g) => {
    const section = el('section', 'diagnostic-groupe');
    section.setAttribute('data-groupe', g[0]);
    section.appendChild(el('h3', 'diagnostic-groupe-titre', g[1]));
    const ul = el('ul', 'diagnostic-liste');
    g[2].forEach((v) => ul.appendChild(ligneVerification(v, f)));
    section.appendChild(ul);
    corps.appendChild(section);
  });
  const ignorees = d.ignorees || [];
  if (ignorees.length) {
    const details = el('details', 'diagnostic-ignorees');
    details.setAttribute('data-role', 'diagnostic-ignorees');
    details.appendChild(el('summary', '', 'Pas vérifiés ici (' + ignorees.length + ')'));
    const ul = el('ul', 'diagnostic-ignorees-liste');
    const titres = {};
    (d.verifications || []).forEach((v) => { titres[v.id] = v.titre; });
    ignorees.forEach((x) => {
      const li = el('li');
      li.setAttribute('data-verification', x.id);
      li.appendChild(el('span', 'diagnostic-ignoree-titre', TITRES_IGNOREES[x.id] || titres[x.id] || x.id));
      li.appendChild(el('span', 'diagnostic-ignoree-raison', x.raison));
      ul.appendChild(li);
    });
    details.appendChild(ul);
    corps.appendChild(details);
  }
  f.duree.textContent = 'Vérifié à ' + heureDe(d.date) + ' en ' + nombreFr(d.duree_s) + ' s'
    + (d.faux ? ' · vérifications système simulées' : '');
  corps.scrollTop = defilement;
}

// Titres des vérifications (pour celles qui ne sont pas faites ici : la liste du contrat, VERIFICATIONS)
export const TITRES_IGNOREES = {
  cable: 'Câble du robot', adresse: 'Adresse du PC sur le câble', profil: 'Connexion « robot-g1 »',
  ros: 'Réglages ROS de l\'Atelier', pc1: 'Ordinateur de marche (PC1)', jetson: 'Jetson', lidar: 'LiDAR',
  sujets: 'Le robot parle au PC', services: 'Services de cartographie', mode: 'Mode du robot', batterie: 'Batterie',
  jetson_ssh: 'Clé SSH du Jetson', jetson_docker: 'Docker sur le Jetson', jetson_image: 'Image du conteneur',
  jetson_place: 'Place libre sur le Jetson', jetson_horloge: 'Heure du Jetson', camera: 'Caméra de poitrine',
};

function dessinerAttente(f) {
  f.racine.setAttribute('data-occupe', enCours(f.mode) ? 'oui' : 'non');
  f.reverifier.disabled = enCours(f.mode);
  const attente = f.racine.querySelector('.diagnostic-attente');
  if (enCours(f.mode)) {
    if (!attente) {
      const a = el('div', 'diagnostic-attente');
      a.setAttribute('data-role', 'diagnostic-attente');
      a.appendChild(el('span', 'diagnostic-roue'));
      a.appendChild(el('span', '', TEXTE_ATTENTE));
      f.corps.parentNode.insertBefore(a, f.corps);
    }
  } else if (attente) {
    attente.remove();
  }
}

function dessinerRetour(f, texte, genre) {
  f.retour.hidden = !texte;
  f.retour.textContent = texte || '';
  f.retour.setAttribute('data-genre', genre || 'info');
}

function fermerFenetre() {
  const f = memoire.fenetre;
  if (!f) return;
  memoire.fenetre = null;
  f.desabonner();
  document.removeEventListener('keydown', f.clavier, true);
  f.racine.remove();
  if (f.avant && f.avant.focus && document.contains(f.avant)) {
    try {
      f.avant.focus();
    } catch (e) {
      // l'élément n'accepte plus le focus : rien de grave
    }
  }
}

function construireFenetre(outils, mode) {
  const racine = el('section', 'diagnostic-fenetre');
  racine.setAttribute('data-role', 'diagnostic');
  // Échap la ferme : la coque ne l'envoie pas comme un ARRÊT tant que le robot ne bouge pas (assemblage, vague 6)
  racine.setAttribute('data-ferme-echap', '');
  racine.setAttribute('role', 'dialog');
  racine.setAttribute('aria-modal', 'false');
  racine.setAttribute('aria-labelledby', 'diagnostic-titre');
  racine.tabIndex = -1;
  const entete = el('header', 'diagnostic-entete');
  const pictogramme = el('span', 'diagnostic-icone');
  pictogramme.appendChild(icone('diagnostic', 22));
  entete.appendChild(pictogramme);
  const titres = el('div', 'diagnostic-titres');
  const h2 = el('h2', 'diagnostic-titre-fenetre', 'Vérifier le robot');
  h2.id = 'diagnostic-titre';
  titres.appendChild(h2);
  const sousTitre = el('span', 'diagnostic-sous-titre', MODES_DIAGNOSTIC[mode]);
  sousTitre.setAttribute('data-role', 'diagnostic-mode');
  titres.appendChild(sousTitre);
  entete.appendChild(titres);
  const fermer = el('button', 'bouton-icone petit diagnostic-fermer');
  fermer.type = 'button';
  fermer.setAttribute('data-role', 'fermer-diagnostic');
  fermer.setAttribute('aria-label', 'Fermer');
  fermer.title = 'Fermer (Échap)';
  fermer.appendChild(icone('croix', 18));
  entete.appendChild(fermer);
  racine.appendChild(entete);

  const bandeau = el('div', 'diagnostic-bandeau');
  bandeau.setAttribute('data-role', 'diagnostic-bandeau');
  bandeau.setAttribute('aria-live', 'polite');
  bandeau.appendChild(pastille('attente'));
  const textesBandeau = el('div', 'diagnostic-bandeau-textes');
  const titreB = el('strong', 'diagnostic-bandeau-titre');
  const messageB = el('p', 'diagnostic-bandeau-message');
  textesBandeau.appendChild(titreB);
  textesBandeau.appendChild(messageB);
  const lesCompteurs = el('div', 'diagnostic-compteurs');
  lesCompteurs.setAttribute('data-role', 'diagnostic-compteurs');
  textesBandeau.appendChild(lesCompteurs);
  bandeau.appendChild(textesBandeau);
  racine.appendChild(bandeau);

  const retour = el('p', 'diagnostic-retour');
  retour.setAttribute('data-role', 'diagnostic-retour');
  retour.setAttribute('aria-live', 'polite');
  retour.hidden = true;
  racine.appendChild(retour);

  const corps = el('div', 'diagnostic-corps');
  corps.setAttribute('data-role', 'diagnostic-corps');
  racine.appendChild(corps);

  const pied = el('footer', 'diagnostic-pied');
  const duree = el('span', 'diagnostic-duree');
  pied.appendChild(duree);
  const reverifier = el('button', 'bouton diagnostic-reverifier');
  reverifier.type = 'button';
  reverifier.setAttribute('data-role', 'reverifier');
  reverifier.appendChild(icone('refaire', 16));
  reverifier.appendChild(el('span', '', 'Vérifier à nouveau'));
  pied.appendChild(reverifier);
  racine.appendChild(pied);

  const f = { racine: racine, corps: corps, bandeau: bandeau, titreBandeau: titreB, messageBandeau: messageB,
    compteurs: lesCompteurs, retour: retour, duree: duree, reverifier: reverifier, outils: outils, mode: mode,
    avant: document.activeElement, desabonner: () => {}, clavier: null, action: null };
  f.clavier = (ev) => {
    // la fenêtre de confirmation ouverte au-dessus se ferme d'abord (elle écoute Échap elle-même) ; la coque
    // reçoit aussi Échap (l'ARRÊT si le robot bouge : la sécurité d'abord)
    if (ev.key === 'Escape' && !fenetreOuverte()) fermerFenetre();
  };
  f.action = (id, bouton) => faireAction(f, id, bouton);
  fermer.addEventListener('click', fermerFenetre);
  reverifier.addEventListener('click', () => verifier(f));
  return f;
}

function rafraichirFenetre(f) {
  const dernier = memoire.derniers[f.mode];
  dessinerResultat(f, dernier ? dernier.resultat : null);
  dessinerAttente(f);
}

function verifier(f) {
  dessinerRetour(f, '', 'info');
  return lancerDiagnostic(f.outils, f.mode, false).then((d) => d, (e) => {
    if (memoire.fenetre === f) dessinerRetour(f, (e && e.message) || 'Le diagnostic n\'a pas pu se faire.', 'erreur');
    return null;
  });
}

async function faireAction(f, id, bouton) {
  const a = ACTIONS_DIAGNOSTIC[id];
  if (!a || !f.outils.confirmer) return null;
  const oui = await f.outils.confirmer(a.confirmation, { titre: a.libelle, ok: a.ok, annuler: 'Annuler' });
  if (!oui || memoire.fenetre !== f) return null;
  bouton.disabled = true;
  const texte = bouton.querySelector('span');
  if (texte) texte.textContent = a.attente;
  dessinerRetour(f, a.attente, 'info');
  let r = null;
  try {
    r = await f.outils.api.envoyer('/api/robot/diagnostic/' + encodeURIComponent(id), { confirme: true, mode: f.mode });
  } catch (e) {
    if (memoire.fenetre === f) {
      dessinerRetour(f, (e && e.message) || 'L\'action n\'a pas pu se faire.', 'erreur');
      bouton.disabled = false;
      if (texte) texte.textContent = a.libelle;
    }
    if (f.outils.message) f.outils.message((e && e.message) || a.libelle + ' : échec', 'erreur');
    return null;
  }
  if (r && r.diagnostic) retenir(r.diagnostic);
  if (memoire.fenetre === f) {
    rafraichirFenetre(f);
    dessinerRetour(f, r.message, r.ok ? 'succes' : 'erreur');
  }
  if (f.outils.message) f.outils.message(r.message, r.ok ? 'succes' : 'erreur');
  return r;
}

export function ouvrirDiagnostic(outils, options) {
  const o = options || {};
  const mode = modeDiagnostic(outils);
  if (!mode) {
    if (outils && outils.message) outils.message('En simulation, il n\'y a pas de robot à vérifier.', 'info');
    return Promise.resolve(null);
  }
  let f = memoire.fenetre;
  if (f && f.mode !== mode) {
    fermerFenetre();
    f = null;
  }
  if (!f) {
    f = construireFenetre(outils, mode);
    memoire.fenetre = f;
    f.desabonner = abonner(() => {
      if (memoire.fenetre === f) rafraichirFenetre(f);
    });
    document.addEventListener('keydown', f.clavier, true);
    document.body.appendChild(f.racine);
  } else {
    f.outils = outils;
  }
  f.proprietaire = o.proprietaire || null;
  rafraichirFenetre(f);
  try {
    f.racine.focus({ preventScroll: true });
  } catch (e) {
    f.racine.focus();
  }
  if (o.relancer === false && memoire.derniers[mode]) return Promise.resolve(memoire.derniers[mode].resultat);
  return verifier(f);
}

// La fenêtre est-elle ouverte ? (tests, et la coque si elle veut le savoir)
export function fenetreDiagnosticOuverte() {
  return !!memoire.fenetre;
}

export function fermerDiagnostic() {
  fermerFenetre();
}

// ---------------------------------------------------------------- l'accueil

export function monterDiagnosticAccueil(element, outils) {
  const mode = modeDiagnostic(outils) || 'reel';
  const outilsMode = Object.assign({}, outils, { mode: mode });
  const jeton = {};
  element.textContent = '';
  const boite = el('div', 'diagnostic-accueil');
  const bouton = el('button', 'bouton bouton-principal diagnostic-verifier');
  bouton.type = 'button';
  bouton.setAttribute('data-role', 'verifier-robot');
  bouton.title = 'Vérifie le câble, le réseau, les services, le mode, la batterie et le Jetson, et dit quoi faire.';
  bouton.appendChild(icone('diagnostic', 18));
  bouton.appendChild(el('span', '', 'Vérifier le robot'));
  boite.appendChild(bouton);
  const resume = el('button', 'diagnostic-resume');
  resume.type = 'button';
  resume.setAttribute('data-role', 'diagnostic-resume');
  resume.appendChild(pastille('aucun'));
  const textes = el('span', 'diagnostic-resume-textes');
  const phrase = el('span', 'diagnostic-resume-phrase');
  const quand = el('span', 'diagnostic-resume-quand');
  textes.appendChild(phrase);
  textes.appendChild(quand);
  resume.appendChild(textes);
  boite.appendChild(resume);
  element.appendChild(boite);

  function dessiner() {
    const dernier = memoire.derniers[mode];
    const d = dernier ? dernier.resultat : null;
    const etat = enCours(mode) ? 'en-cours' : (d ? d.etat : 'aucun');
    resume.setAttribute('data-etat', etat);
    resume.querySelector('.diagnostic-pastille').setAttribute('data-etat', etat);
    resume.disabled = !d;
    resume.title = d ? 'Voir le détail du dernier diagnostic' : '';
    bouton.disabled = enCours(mode);
    if (enCours(mode)) {
      phrase.textContent = TEXTE_ATTENTE;
      quand.textContent = '';
    } else {
      phrase.textContent = phraseResume(d);
      quand.textContent = d ? depuis(dernier.recu) + ' · voir le détail' : '';
    }
  }

  bouton.addEventListener('click', () => {
    ouvrirDiagnostic(outilsMode, { proprietaire: jeton });
  });
  resume.addEventListener('click', () => {
    if (memoire.derniers[mode]) ouvrirDiagnostic(outilsMode, { relancer: false, proprietaire: jeton });
  });
  const desabonner = abonner(dessiner);
  const minuterie = setInterval(dessiner, 30000);       // « il y a … min » reste juste
  dessiner();
  chargerDernier(outilsMode, mode);
  return {
    rafraichir: () => {
      chargerDernier(outilsMode, mode).then(dessiner);
    },
    detruire: () => {
      desabonner();
      clearInterval(minuterie);
      if (memoire.fenetre && memoire.fenetre.proprietaire === jeton) fermerFenetre();
      element.textContent = '';
    },
  };
}

// ---------------------------------------------------------------- la barre d'outils

export function monterDiagnosticBarre(element, outils) {
  const mode = modeDiagnostic(outils);
  element.textContent = '';
  if (!mode) {
    element.hidden = true;            // en simulation : rien (pas de robot à vérifier)
    return { detruire: () => { element.hidden = false; } };
  }
  element.hidden = false;
  const bouton = el('button', 'bouton-barre diagnostic-barre');
  bouton.type = 'button';
  bouton.setAttribute('data-role', 'verifier-robot');
  bouton.appendChild(icone('diagnostic', 18));
  bouton.appendChild(el('span', 'bouton-barre-texte', 'Vérifier'));
  const point = el('span', 'diagnostic-point');
  point.setAttribute('aria-hidden', 'true');
  bouton.appendChild(point);
  element.appendChild(bouton);

  function dessiner() {
    const dernier = memoire.derniers[mode];
    const d = dernier ? dernier.resultat : null;
    const etat = enCours(mode) ? 'en-cours' : (d ? d.etat : 'aucun');
    bouton.setAttribute('data-etat', etat);
    let titre = 'Vérifier le robot : câble, réseau, services, mode, batterie et Jetson';
    if (enCours(mode)) titre = 'Vérification du robot en cours…';
    else if (d) titre += ' (dernier : ' + titreBandeau(d).toLowerCase().replace('!', '').trim() + ')';
    bouton.title = titre;
    bouton.setAttribute('aria-label', titre);
  }

  bouton.addEventListener('click', () => {
    ouvrirDiagnostic(outils);
  });
  const desabonner = abonner(dessiner);
  dessiner();
  chargerDernier(outils, mode);
  return {
    detruire: () => {
      // l'espace de travail se ferme : la fenêtre ouverte par la barre ou par le ruban se ferme avec lui
      desabonner();
      fermerFenetre();
      element.textContent = '';
    },
  };
}

// ---------------------------------------------------------------- le ruban

export function executer(nom, valeur, outils) {
  if (nom === 'verifier') return ouvrirDiagnostic(outils);
  return null;
}
