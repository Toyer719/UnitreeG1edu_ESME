// La borne visiteur (vague 6, section 13.5 du plan) : page /borne, pour une tablette ou un téléphone du même
// réseau. Module de l'agent Borne et orchestrateur.
//
// demarrerBorne(racine) lit l'état (WebSocket /ws/borne, sinon GET /api/borne/etat toutes les 0,5 s ; schéma
// etat_borne) et montre l'écran demandé (data-ecran sur [data-role=borne] : hors_service, salles, suivez_moi,
// arrivee, retour, occupe, pause). Une salle touchée ([data-salle=<id>]) demande confirmation dans la page
// (« Je vous accompagne à … ? », [data-role=confirmer-salle] : Oui), puis POST /api/borne/choisir ; anti-rebond de
// 0,6 s ; le premier appui sur l'écran envoie POST /api/borne/appui (le robot salue) et débloque le son ; le son
// de la sortie borne (champ son) est joué une fois par <audio data-role=borne-son> ; le mode opérateur
// ([data-role=borne-operateur] : code, puis pause, reprendre, ramener ; rien d'autre). Ce module ne charge que des
// fichiers de js/borne/ (les seuls permis depuis la tablette). Aucune donnée insérée en HTML (textContent).

import { fleche, HUMEURS, mascotte, pictogramme, svg } from './dessins.js';
import { ANTI_REBOND_MS, creerAntiRebond, creerLiaison } from './liaison.js';
import { creerSon } from './son.js';
import { pictogrammeDe, texte } from './textes.js';

export const ECRANS_BORNE = ['hors_service', 'salles', 'suivez_moi', 'arrivee', 'retour', 'occupe', 'pause'];
export const ECRANS_AVEC_SALLES = ['salles', 'occupe', 'pause'];
export const ACTIONS_OPERATEUR = ['pause', 'reprendre', 'ramener'];
const DUREE_BULLE_MS = 4500;
const APPUI_VIVANT_MS = 5000;        // pendant le choix : un appui au plus toutes les 5 s garde la visite
const CONFIRMATION_MAX_MS = 25000;   // une confirmation oubliée se referme seule
const LONGUEUR_CODE_MAX = 8;

function el(balise, classe, contenu) {
  const e = document.createElement(balise);
  if (classe) e.className = classe;
  if (contenu !== undefined && contenu !== null) e.textContent = contenu;
  return e;
}

function bouton(classe, contenu, role) {
  const b = el('button', classe, contenu);
  b.type = 'button';
  if (role) b.setAttribute('data-role', role);
  return b;
}

// Typographie française : une espace insécable avant ? ! : ; et à l'intérieur des guillemets (« … »), et un
// trait d'union insécable dans les mots composés (« Suivez-moi ») : une ponctuation ou une moitié de mot ne se
// retrouve jamais seule en début de ligne
export function insecables(t) {
  return String(t === undefined || t === null ? '' : t)
    .replace(/ ([?!:;»])/g, '\u00a0$1').replace(/« /g, '«\u00a0')
    .replace(/([A-Za-zÀ-ÿ])-([A-Za-zÀ-ÿ])/g, '$1\u2011$2');
}

// L'écran à montrer pour un état reçu (inconnu ou absent : hors_service)
export function ecranAffiche(etat) {
  return etat && ECRANS_BORNE.indexOf(etat.ecran) >= 0 ? etat.ecran : 'hors_service';
}

// Part du trajet faite (0 à 1), d'après la distance restante et celle du début de la visite
export function progression(reste, initial) {
  if (typeof reste !== 'number' || typeof initial !== 'number' || !(initial > 0)) return null;
  return Math.max(0, Math.min(1, 1 - reste / initial));
}

// Ce qui change le dessin des cartes : ids, noms, étages, accès, pictogrammes, cartes actives ou non
export function signatureSalles(salles, actives, langue) {
  return JSON.stringify([actives, langue, (salles || []).map((s) => [s.id, s.nom, s.nom_etage || s.etage,
    s.accessible, pictogrammeDe(s)])]);
}

export function demarrerBorne(racine, options) {
  options = options || {};
  const permis = creerAntiRebond(ANTI_REBOND_MS);
  let dernier = null;
  let langue = 'fr';
  let ecran = null;
  let humeur = null;
  let signature = null;
  let premierEtat = true;
  let dernierAppui = 0;
  let debutVisite = { salle: null, reste: null };
  let salleChoisie = null;
  let envoiEnCours = false;
  let jeton = null;
  let finJeton = 0;
  let code = '';
  const minuteries = {};

  function attendre(nom, ms, f) {
    if (minuteries[nom]) clearTimeout(minuteries[nom]);
    minuteries[nom] = setTimeout(() => {
      minuteries[nom] = null;
      f();
    }, ms);
  }

  racine.textContent = '';
  racine.setAttribute('data-ecran', 'hors_service');

  // en-tête : la mascotte, la phrase principale de l'écran et son détail
  const entete = el('header', 'borne-entete');
  const cadreMascotte = el('div', 'borne-mascotte');
  const textes = el('div', 'borne-textes');
  const titre = el('h1', 'borne-titre');
  titre.setAttribute('data-role', 'borne-titre');
  titre.setAttribute('aria-live', 'polite');
  const detail = el('p', 'borne-detail');
  detail.setAttribute('data-role', 'borne-detail');
  textes.appendChild(titre);
  textes.appendChild(detail);
  entete.appendChild(cadreMascotte);
  entete.appendChild(textes);

  // centre : les cartes des salles (la seule partie qui défile), ou le suivi de la visite
  const centre = el('section', 'borne-centre');
  const liste = el('div', 'borne-salles');
  liste.setAttribute('data-role', 'borne-salles');
  const vide = el('p', 'borne-vide');
  vide.hidden = true;
  const visite = el('div', 'borne-visite');
  visite.setAttribute('data-role', 'borne-visite');
  const barre = el('div', 'borne-barre');
  barre.setAttribute('role', 'progressbar');
  barre.setAttribute('aria-valuemin', '0');
  barre.setAttribute('aria-valuemax', '100');
  const plein = el('div', 'borne-barre-plein');
  barre.appendChild(plein);
  const destination = el('div', 'borne-destination');
  destination.setAttribute('data-role', 'borne-destination');
  const iconeDestination = el('span', 'borne-carte-icone borne-destination-icone');
  const nomDestination = el('span', 'borne-destination-nom');
  destination.appendChild(iconeDestination);
  destination.appendChild(nomDestination);
  visite.appendChild(destination);
  visite.appendChild(fleche());
  visite.appendChild(barre);
  centre.appendChild(liste);
  centre.appendChild(vide);
  centre.appendChild(visite);

  // pied : le lieu, la liaison, le bouton discret de l'opérateur
  const pied = el('footer', 'borne-pied');
  const nomLieu = el('span', 'borne-lieu');
  const etatLiaison = el('span', 'borne-liaison');
  etatLiaison.setAttribute('data-role', 'borne-liaison');
  etatLiaison.hidden = true;
  const boutonOperateur = bouton('borne-operateur', null, 'borne-operateur');
  boutonOperateur.appendChild(svg('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true' }, [
    svg('circle', { cx: 5, cy: 12, r: 2 }), svg('circle', { cx: 12, cy: 12, r: 2 }), svg('circle', { cx: 19, cy: 12, r: 2 })]));
  boutonOperateur.hidden = true;
  pied.appendChild(nomLieu);
  pied.appendChild(etatLiaison);
  pied.appendChild(boutonOperateur);

  // la bulle des messages courts, et le son
  const bulle = el('div', 'borne-bulle');
  bulle.setAttribute('data-role', 'borne-bulle');
  bulle.setAttribute('role', 'status');
  bulle.hidden = true;
  const audio = el('audio', 'borne-son');
  audio.setAttribute('data-role', 'borne-son');
  audio.preload = 'auto';
  const son = creerSon(audio);

  // la confirmation du choix
  const voileConfirmation = el('div', 'borne-voile');
  voileConfirmation.setAttribute('data-role', 'confirmation-borne');
  voileConfirmation.hidden = true;
  const dialogue = el('div', 'borne-dialogue');
  dialogue.setAttribute('role', 'dialog');
  dialogue.setAttribute('aria-modal', 'true');
  const mascotteDialogue = el('div', 'borne-dialogue-mascotte');
  mascotteDialogue.appendChild(mascotte('content'));
  const question = el('p', 'borne-question');
  const nomSalle = el('p', 'borne-question-salle');
  nomSalle.setAttribute('data-role', 'salle-confirmee');
  const messageDialogue = el('p', 'borne-dialogue-message');
  messageDialogue.hidden = true;
  const boutons = el('div', 'borne-boutons');
  const oui = bouton('borne-bouton borne-bouton-oui', '', 'confirmer-salle');
  const non = bouton('borne-bouton borne-bouton-non', '', 'renoncer-salle');
  boutons.appendChild(non);
  boutons.appendChild(oui);
  [mascotteDialogue, question, nomSalle, messageDialogue, boutons].forEach((x) => dialogue.appendChild(x));
  voileConfirmation.appendChild(dialogue);

  // le mode opérateur : le code, puis les seules actions permises
  const voileCode = el('div', 'borne-voile borne-voile-operateur');
  voileCode.setAttribute('data-role', 'operateur-code');
  voileCode.hidden = true;
  const dialogueCode = el('div', 'borne-dialogue borne-dialogue-code');
  const titreCode = el('h2', 'borne-dialogue-titre');
  const aideCode = el('p', 'borne-dialogue-aide');
  const points = el('div', 'borne-code-points');
  points.setAttribute('data-role', 'code-points');
  const messageCode = el('p', 'borne-dialogue-message');
  messageCode.setAttribute('data-role', 'code-message');
  messageCode.hidden = true;
  const clavier = el('div', 'borne-clavier');
  ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'effacer', '0', 'valider'].forEach((touche) => {
    const b = bouton('borne-touche' + (touche.length > 1 ? ' borne-touche-' + touche : ''), touche.length > 1 ? '' : touche);
    b.setAttribute('data-touche', touche);
    b.addEventListener('click', () => toucheCode(touche));
    clavier.appendChild(b);
  });
  const fermerCode = bouton('borne-bouton borne-bouton-non', '', 'fermer-code');
  [titreCode, aideCode, points, messageCode, clavier, fermerCode].forEach((x) => dialogueCode.appendChild(x));
  voileCode.appendChild(dialogueCode);

  const voileActions = el('div', 'borne-voile borne-voile-operateur');
  voileActions.setAttribute('data-role', 'operateur-actions');
  voileActions.hidden = true;
  const dialogueActions = el('div', 'borne-dialogue');
  const titreActions = el('h2', 'borne-dialogue-titre');
  const messageActions = el('p', 'borne-dialogue-aide');
  messageActions.setAttribute('data-role', 'operateur-message');
  const boutonsActions = el('div', 'borne-boutons borne-boutons-colonne');
  const actions = {};
  ACTIONS_OPERATEUR.forEach((a) => {
    const b = bouton('borne-bouton', '');
    b.setAttribute('data-action', a);
    b.addEventListener('click', () => agir(a));
    actions[a] = b;
    boutonsActions.appendChild(b);
  });
  const fermerActions = bouton('borne-bouton borne-bouton-non', '', 'fermer-operateur');
  [titreActions, messageActions, boutonsActions, fermerActions].forEach((x) => dialogueActions.appendChild(x));
  voileActions.appendChild(dialogueActions);

  [entete, centre, pied, bulle, voileConfirmation, voileCode, voileActions, audio].forEach((x) => racine.appendChild(x));

  // ------------------------------------------------------------ textes fixes, selon la langue

  function textesFixes() {
    question.textContent = texte(langue, 'question');
    if (!envoiEnCours) {
      oui.textContent = texte(langue, 'oui');
      non.textContent = texte(langue, 'non');
    }
    vide.textContent = texte(langue, 'pasDeSalle');
    titreCode.textContent = texte(langue, 'code');
    aideCode.textContent = texte(langue, 'codeAide');
    fermerCode.textContent = texte(langue, 'fermer');
    clavier.querySelector('[data-touche=effacer]').textContent = '⌫';
    clavier.querySelector('[data-touche=effacer]').setAttribute('aria-label', texte(langue, 'effacer'));
    clavier.querySelector('[data-touche=valider]').textContent = texte(langue, 'valider');
    titreActions.textContent = texte(langue, 'operateur');
    ACTIONS_OPERATEUR.forEach((a) => { actions[a].textContent = texte(langue, a); });
    fermerActions.textContent = texte(langue, 'fermer');
    boutonOperateur.setAttribute('aria-label', texte(langue, 'operateur'));
    boutonOperateur.title = texte(langue, 'operateur');
    liste.setAttribute('aria-label', texte(langue, 'salles'));
    barre.setAttribute('aria-label', texte(langue, 'progression'));
  }

  function montrerBulle(message) {
    bulle.textContent = message;
    bulle.hidden = false;
    attendre('bulle', DUREE_BULLE_MS, () => { bulle.hidden = true; });
  }

  // ------------------------------------------------------------ les cartes des salles

  function dessinerSalles(salles, actives) {
    liste.textContent = '';
    // l'étage n'est écrit que si le lieu en a plusieurs (sinon, il est le même partout)
    const etages = new Set(salles.map((s) => s.etage));
    salles.forEach((s) => {
      const b = bouton('borne-carte' + (s.accessible ? '' : ' borne-carte-ailleurs'));
      b.setAttribute('data-salle', s.id);
      b.disabled = !actives;
      const icone = el('span', 'borne-carte-icone');
      icone.appendChild(pictogramme(pictogrammeDe(s)));
      const mots = el('span', 'borne-carte-textes');
      mots.appendChild(el('span', 'borne-carte-nom', s.nom));
      if (etages.size > 1 || !s.accessible) mots.appendChild(el('span', 'borne-carte-etage', s.nom_etage || s.etage || ''));
      const chevron = el('span', 'borne-carte-chevron', '›');
      chevron.setAttribute('aria-hidden', 'true');
      b.appendChild(icone);
      b.appendChild(mots);
      b.appendChild(chevron);
      b.addEventListener('click', () => toucherSalle(s));
      liste.appendChild(b);
    });
  }

  function toucherSalle(s) {
    if (ecran !== 'salles' || !permis('salle')) return;
    if (!s.accessible) {
      montrerBulle(texte(langue, 'autreEtage', { nom: s.nom }));
      return;
    }
    salleChoisie = s;
    nomSalle.textContent = insecables('« ' + s.nom + ' » ?');
    messageDialogue.hidden = true;
    oui.hidden = false;
    oui.disabled = false;
    non.disabled = false;
    textesFixes();
    voileConfirmation.hidden = false;
    oui.focus();
    attendre('confirmation', CONFIRMATION_MAX_MS, fermerConfirmation);
  }

  function fermerConfirmation() {
    voileConfirmation.hidden = true;
    salleChoisie = null;
    envoiEnCours = false;
    if (minuteries.confirmation) clearTimeout(minuteries.confirmation);
  }

  async function confirmer() {
    if (!salleChoisie || envoiEnCours || !permis('oui')) return;
    envoiEnCours = true;
    oui.disabled = true;
    non.disabled = true;
    messageDialogue.textContent = texte(langue, 'patience');
    messageDialogue.hidden = false;
    const r = await liaison.envoyer('/api/borne/choisir', { salle: salleChoisie.id });
    envoiEnCours = false;
    if (r.statut === 200 && r.donnees && r.donnees.accepte) {
      fermerConfirmation();
      return;
    }
    messageDialogue.textContent = insecables((r.donnees && r.donnees.detail) || texte(langue, 'robotMuet'));
    oui.hidden = true;
    non.disabled = false;
    non.textContent = texte(langue, 'daccord');
    attendre('confirmation', DUREE_BULLE_MS + 1500, fermerConfirmation);
  }

  oui.addEventListener('click', confirmer);
  non.addEventListener('click', () => {
    if (permis('non')) fermerConfirmation();
  });

  // ------------------------------------------------------------ le premier appui : le robot salue

  function appuiVisiteur(e) {
    son.debloquer();
    if (e && e.target && e.target.closest && e.target.closest('.borne-voile-operateur, .borne-operateur')) return;
    const demo = dernier && dernier.demo;
    if (!demo || ecran !== 'salles') return;
    const t = Date.now();
    if (demo.etat === 'attente') {
      if (!permis('appui')) return;
    } else if (demo.etat === 'choix' || demo.etat === 'salutation') {
      if (t - dernierAppui < APPUI_VIVANT_MS) return;
    } else {
      return;
    }
    dernierAppui = t;
    liaison.envoyer('/api/borne/appui', {});
  }
  racine.addEventListener('pointerdown', appuiVisiteur, true);

  // ------------------------------------------------------------ le mode opérateur

  function jetonValable() {
    return jeton && Date.now() < finJeton;
  }

  function dessinerCode() {
    points.textContent = '';
    for (let i = 0; i < Math.max(4, code.length); i++) points.appendChild(el('span', i < code.length ? 'plein' : ''));
  }

  function ouvrirOperateur() {
    if (!permis('operateur')) return;
    if (jetonValable()) {
      voileActions.hidden = false;
      majActions();
      return;
    }
    code = '';
    dessinerCode();
    messageCode.hidden = true;
    textesFixes();
    voileCode.hidden = false;
  }

  async function toucheCode(touche) {
    if (touche === 'effacer') {
      code = code.slice(0, -1);
    } else if (touche === 'valider') {
      if (!code || !permis('valider')) return;
      const r = await liaison.envoyer('/api/borne/operateur', { code: code });
      code = '';
      dessinerCode();
      if (r.statut === 200 && r.donnees && r.donnees.jeton) {
        jeton = r.donnees.jeton;
        finJeton = Date.now() + (r.donnees.expire_s || 300) * 1000;
        liaison.changerJeton(jeton);
        attendre('jeton', finJeton - Date.now(), oublierJeton);
        voileCode.hidden = true;
        voileActions.hidden = false;
        majActions();
        return;
      }
      messageCode.textContent = r.statut === 403 ? texte(langue, 'codeFaux')
        : ((r.donnees && r.donnees.detail) || texte(langue, 'robotMuet'));
      messageCode.hidden = false;
      return;
    } else if (code.length < LONGUEUR_CODE_MAX) {
      code += touche;
    }
    messageCode.hidden = true;
    dessinerCode();
  }

  function oublierJeton() {
    jeton = null;
    finJeton = 0;
    liaison.changerJeton(null);
    voileActions.hidden = true;
  }

  function majActions() {
    const mode = dernier && dernier.mode_operateur;
    messageActions.textContent = (mode && mode.message) || '';
    ACTIONS_OPERATEUR.forEach((a) => {
      // sans l'état du mode opérateur (jeton pas encore vu par le serveur) : rien n'est possible
      actions[a].disabled = !(mode && Array.isArray(mode.actions) && mode.actions.indexOf(a) >= 0);
    });
  }

  async function agir(action) {
    if (!jetonValable() || !permis('action-' + action)) return;
    const r = await liaison.envoyer('/api/borne/operateur/' + action, {});
    if (r.statut === 401) oublierJeton();
    montrerBulle(r.statut === 200 ? ((r.donnees && r.donnees.texte) || texte(langue, 'fait'))
      : ((r.donnees && r.donnees.detail) || texte(langue, 'robotMuet')));
  }

  boutonOperateur.addEventListener('click', ouvrirOperateur);
  fermerCode.addEventListener('click', () => { voileCode.hidden = true; });
  fermerActions.addEventListener('click', () => { voileActions.hidden = true; });

  // ------------------------------------------------------------ l'état reçu

  function rendre(etat) {
    dernier = etat;
    const nouvelleLangue = etat.langue === 'en' ? 'en' : 'fr';
    const changeLangue = nouvelleLangue !== langue || premierEtat;
    langue = nouvelleLangue;
    if (changeLangue) {
      document.documentElement.lang = langue;
      textesFixes();
    }
    const e = ecranAffiche(etat);
    if (e !== ecran) {
      ecran = e;
      racine.setAttribute('data-ecran', e);
      if (e !== 'salles') fermerConfirmation();
    }
    titre.textContent = insecables(etat.texte);
    detail.textContent = insecables(etat.detail);
    detail.hidden = !etat.detail;
    const h = HUMEURS[e] || 'accueil';
    if (h !== humeur) {
      humeur = h;
      cadreMascotte.textContent = '';
      cadreMascotte.appendChild(mascotte(h));
    }
    nomLieu.textContent = etat.lieu && etat.lieu.nom ? etat.lieu.nom : '';
    const salles = Array.isArray(etat.salles) ? etat.salles : [];
    const actives = e === 'salles';
    const sig = signatureSalles(salles, actives, langue);
    if (sig !== signature) {
      signature = sig;
      dessinerSalles(salles, actives);
    }
    vide.hidden = !(ECRANS_AVEC_SALLES.indexOf(e) >= 0 && !salles.length);
    // la visite : la barre de progression du trajet
    const v = etat.visite;
    if (v && v.salle) {
      if (debutVisite.salle !== v.salle || (typeof v.reste_m === 'number' && debutVisite.reste === null)) {
        debutVisite = { salle: v.salle, reste: typeof v.reste_m === 'number' ? v.reste_m : null };
        const s = salles.find((x) => x.id === v.salle) || { id: v.salle, nom: v.nom };
        iconeDestination.textContent = '';
        iconeDestination.appendChild(pictogramme(pictogrammeDe(s)));
        nomDestination.textContent = v.nom || v.salle;
      }
      const p = e === 'arrivee' ? 1 : progression(v.reste_m, debutVisite.reste);
      plein.style.width = p === null ? '0%' : Math.round(p * 100) + '%';
      barre.setAttribute('aria-valuenow', p === null ? '0' : String(Math.round(p * 100)));
      barre.hidden = p === null;
    } else {
      debutVisite = { salle: null, reste: null };
      barre.hidden = true;
    }
    destination.hidden = !(v && v.salle) || e === 'retour';
    // le son de la sortie borne : chaque phrase une seule fois (pas celle d'avant l'ouverture de la page)
    if (etat.son && etat.son.id) {
      if (premierEtat) son.ignorer(etat.son.id);
      else son.jouer(etat.son);
    }
    cadreMascotte.classList.toggle('parle', son.parle());
    premierEtat = false;
    // le mode opérateur
    boutonOperateur.hidden = !(etat.operateur && etat.operateur.possible);
    if (!voileActions.hidden) majActions();
    if (jeton && !jetonValable()) oublierJeton();
  }

  const liaison = (options.liaison || creerLiaison)({
    surEtat: rendre,
    surConnexion: (ok) => {
      etatLiaison.textContent = ok ? '' : texte(langue, 'connexion');
      etatLiaison.hidden = ok;
      racine.setAttribute('data-connexion', ok ? 'ok' : 'perdue');
    },
  });
  audio.addEventListener('playing', () => cadreMascotte.classList.add('parle'));
  audio.addEventListener('ended', () => cadreMascotte.classList.remove('parle'));
  textesFixes();
  rendre({ ecran: 'hors_service', texte: texte('fr', 'patience'), salles: [], operateur: { possible: false } });
  premierEtat = true;

  return {
    arreter: () => {
      liaison.arreter();
      Object.keys(minuteries).forEach((k) => { if (minuteries[k]) clearTimeout(minuteries[k]); });
    },
    etat: () => dernier,
    rendre: rendre,
  };
}

const racine = document.getElementById('borne');
if (racine) window.borne = demarrerBorne(racine);
