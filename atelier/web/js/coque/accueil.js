// Écran d'accueil (« Nouveau document » de SolidWorks) : deux grandes cartes Simulation et Robot réel,
// la liste des lieux, « Nouveau lieu », la case « Répétition sans robot (faux G1) » et les
// vérifications du mode Réel (GET /api/robot/liaison), puis « Ouvrir » (vague 5, section 12.2 du
// plan). Module de l'agent Coquille.
//
// afficherAccueil(racine, {surOuvrir({mode, repetition, lieu, etage, telecommande}), surPilotageSansLieu(),
//   mode, repetition, lieu, etage, surTheme()}) → {fermer()}
// Un clic choisit une carte, un double-clic ou Entrée ouvre. Repères : [data-role=accueil],
// [data-role=mode-simu], [data-role=mode-reel] (aria-pressed), [data-role=repetition] (case),
// [data-role=verifications] avec [data-verif=ros|cable|robot|telecommande] (data-etat=ok|non|inconnu),
// [data-role=liste-lieux] avec [data-lieu=<id>], [data-role=nouveau-lieu], [data-role=ouvrir],
// [data-role=pilotage-sans-lieu].

import { api } from '../api.js';
import { idDepuisNom, verifierId } from '../geometrie.js';
import { icone, ILLUSTRATIONS } from './icones.js';

const PERIODE_LIAISON_MS = 4000;
const TEXTES_MODES = {
  simu: { titre: 'Simulation', texte: 'Dessiner un lieu et essayer le guide sur l\'ordinateur, sans robot.' },
  reel: { titre: 'Robot réel', texte: 'Scanner le bâtiment, placer les salles et guider le vrai G1.' },
};
const VERIFICATIONS = {
  ros: { reel: 'Atelier lancé avec robot.sh', repetition: 'ROS 2 actif dans l\'Atelier' },
  cable: { reel: 'Câble du robot branché' },
  robot: { reel: 'PC1 et Jetson répondent' },
  telecommande: { reel: 'Télécommande en main' },
};

function el(balise, classe, texte) {
  const e = document.createElement(balise);
  if (classe) e.className = classe;
  if (texte !== undefined && texte !== null) e.textContent = texte;
  return e;
}

function lireMemoire(cle) {
  try {
    return localStorage.getItem(cle);
  } catch (e) {
    return null;
  }
}

function ms(v) {
  return v === null || v === undefined ? '?' : String(v < 10 ? Math.round(v * 10) / 10 : Math.round(v)).replace('.', ',');
}

// État d'une vérification d'après la réponse de GET /api/robot/liaison : [etat, détail]
export function etatVerification(nom, liaison, repetition) {
  if (!liaison) return ['inconnu', 'vérification en cours…'];
  if (nom === 'ros') {
    if (repetition) return liaison.ros.actif ? ['ok', 'ROS 2 répond'] : ['non', 'pont ROS 2 de l\'Atelier arrêté'];
    const bon = liaison.ros.domaine === '0' && (!liaison.ros.cyclonedds || liaison.ros.cyclonedds === liaison.interface);
    return bon ? ['ok', 'domaine 0' + (liaison.ros.cyclonedds ? ', ' + liaison.ros.cyclonedds : '')]
      : ['non', 'domaine ' + liaison.ros.domaine + ' : relancez avec « source ~/robot-g1/setup/robot.sh »'];
  }
  if (nom === 'cable') {
    return liaison.cable ? ['ok', liaison.interface + (liaison.adresse_pc ? ', ' + liaison.adresse_pc : '')]
      : ['non', 'rien sur ' + liaison.interface];
  }
  if (nom === 'robot') {
    if (!liaison.cable) return ['inconnu', 'branchez d\'abord le câble'];
    const pc1 = liaison.pc1.repond;
    const jetson = liaison.jetson.repond;
    if (pc1 && jetson) return ['ok', 'en ' + ms(liaison.pc1.ms) + ' et ' + ms(liaison.jetson.ms) + ' ms'];
    if (pc1) return ['non', 'PC1 répond, le Jetson pas encore'];
    return ['non', 'aucune réponse : le robot est-il allumé ?'];
  }
  return ['inconnu', ''];
}

export function afficherAccueil(racine, options) {
  options = options || {};
  let mode = options.mode === 'reel' ? 'reel' : (options.mode === 'simu' ? 'simu'
    : (lireMemoire('atelier.mode') === 'reel' ? 'reel' : 'simu'));
  let repetition = options.repetition !== undefined ? !!options.repetition : lireMemoire('atelier.repetition') === '1';
  let lieux = [];
  let lieuChoisi = options.lieu || lireMemoire('atelier.lieu');
  let etageChoisi = options.etage || lireMemoire('atelier.etage');
  let liaison = null;
  let lieuxCharges = false;
  let telecommande = false;
  let minuterie = null;
  let ferme = false;

  racine.textContent = '';
  const page = el('div', 'accueil');
  page.setAttribute('data-role', 'accueil');
  // en-tête
  const entete = el('header', 'accueil-entete');
  const marque = el('div', 'marque');
  marque.appendChild(icone('robot', 22));
  marque.appendChild(el('span', '', 'Atelier G1'));
  entete.appendChild(marque);
  entete.appendChild(el('span', 'espace-flexible'));
  const etatServeur = el('span', 'accueil-serveur', 'Serveur…');
  etatServeur.setAttribute('data-role', 'etat-serveur');
  entete.appendChild(etatServeur);
  const boutonTheme = el('button', 'bouton-icone');
  boutonTheme.type = 'button';
  boutonTheme.setAttribute('data-role', 'theme');
  boutonTheme.title = 'Thème clair ou sombre';
  boutonTheme.appendChild(icone('theme', 20));
  boutonTheme.addEventListener('click', () => { if (options.surTheme) options.surTheme(); });
  entete.appendChild(boutonTheme);
  page.appendChild(entete);

  const corps = el('main', 'accueil-corps');
  corps.appendChild(el('h1', 'accueil-titre', 'Avec quoi travaillez-vous aujourd\'hui ?'));
  // les deux cartes
  const modes = el('div', 'accueil-modes');
  modes.setAttribute('role', 'radiogroup');
  modes.setAttribute('aria-label', 'Mode de travail');
  const cartes = {};
  ['simu', 'reel'].forEach((m) => {
    const b = el('button', 'carte-mode carte-mode-' + m);
    b.type = 'button';
    b.setAttribute('data-role', 'mode-' + m);
    b.setAttribute('role', 'radio');
    const image = el('span', 'carte-mode-image');
    image.innerHTML = ILLUSTRATIONS[m];          // gabarit fixe (aucune donnée des fichiers)
    b.appendChild(image);
    const textes = el('span', 'carte-mode-textes');
    textes.appendChild(el('span', 'carte-mode-titre', TEXTES_MODES[m].titre));
    textes.appendChild(el('span', 'carte-mode-texte', TEXTES_MODES[m].texte));
    b.appendChild(textes);
    b.appendChild(el('span', 'carte-mode-coche', '✓'));
    b.addEventListener('click', () => choisirMode(m));
    b.addEventListener('dblclick', () => {
      choisirMode(m);
      ouvrir();
    });
    cartes[m] = b;
    modes.appendChild(b);
  });
  corps.appendChild(modes);

  const bas = el('div', 'accueil-bas');
  // lieux
  const blocLieux = el('section', 'accueil-lieux');
  const titreLieux = el('div', 'accueil-section-titre');
  titreLieux.appendChild(el('h2', '', 'Lieu'));
  const boutonNouveau = el('button', 'bouton bouton-discret');
  boutonNouveau.type = 'button';
  boutonNouveau.setAttribute('data-role', 'nouveau-lieu');
  boutonNouveau.appendChild(icone('plus', 18));
  boutonNouveau.appendChild(el('span', '', 'Nouveau lieu'));
  titreLieux.appendChild(boutonNouveau);
  blocLieux.appendChild(titreLieux);
  const liste = el('div', 'liste-lieux');
  liste.setAttribute('data-role', 'liste-lieux');
  liste.setAttribute('role', 'listbox');
  liste.setAttribute('aria-label', 'Lieux');
  liste.appendChild(el('p', 'panneau-note', 'Chargement…'));
  blocLieux.appendChild(liste);
  // nouveau lieu
  const formulaire = el('form', 'nouveau-lieu');
  formulaire.setAttribute('data-role', 'formulaire-lieu');
  formulaire.hidden = true;
  const ligneNom = el('label', 'champ champ-empile');
  ligneNom.appendChild(el('span', 'champ-libelle', 'Nom du nouveau lieu'));
  const champNom = el('input');
  champNom.type = 'text';
  champNom.placeholder = 'ex. Lycée Victor Hugo';
  champNom.setAttribute('data-role', 'nom-lieu');
  ligneNom.appendChild(champNom);
  formulaire.appendChild(ligneNom);
  const tailles = el('div', 'nouveau-lieu-taille');
  tailles.setAttribute('data-role', 'taille-lieu');
  const champLargeur = el('input');
  champLargeur.type = 'number';
  champLargeur.min = '3';
  champLargeur.step = '1';
  champLargeur.value = '20';
  champLargeur.setAttribute('aria-label', 'Largeur en mètres');
  const champProfondeur = el('input');
  champProfondeur.type = 'number';
  champProfondeur.min = '3';
  champProfondeur.step = '1';
  champProfondeur.value = '15';
  champProfondeur.setAttribute('aria-label', 'Profondeur en mètres');
  tailles.appendChild(el('span', 'champ-libelle', 'Monde de'));
  tailles.appendChild(champLargeur);
  tailles.appendChild(el('span', '', '×'));
  tailles.appendChild(champProfondeur);
  tailles.appendChild(el('span', 'champ-unite', 'm'));
  formulaire.appendChild(tailles);
  const lignesBoutons = el('div', 'formulaire-ligne');
  const creer = el('button', 'bouton bouton-principal', 'Créer');
  creer.type = 'submit';
  creer.setAttribute('data-role', 'creer-lieu');
  const renoncer = el('button', 'bouton', 'Annuler');
  renoncer.type = 'button';
  lignesBoutons.appendChild(creer);
  lignesBoutons.appendChild(renoncer);
  formulaire.appendChild(lignesBoutons);
  blocLieux.appendChild(formulaire);
  bas.appendChild(blocLieux);

  // options du mode
  const blocMode = el('section', 'accueil-options');
  blocMode.setAttribute('data-role', 'options-mode');
  bas.appendChild(blocMode);
  corps.appendChild(bas);

  // actions
  const actions = el('div', 'accueil-actions');
  const sansLieu = el('button', 'bouton-lien', 'Piloter le robot sans lieu');
  sansLieu.type = 'button';
  sansLieu.setAttribute('data-role', 'pilotage-sans-lieu');
  sansLieu.title = 'Postures, gestes et joysticks, sans carte (au portique par exemple)';
  sansLieu.addEventListener('click', () => { if (options.surPilotageSansLieu) options.surPilotageSansLieu(); });
  actions.appendChild(sansLieu);
  const message = el('p', 'accueil-message');
  message.setAttribute('data-role', 'accueil-message');
  message.setAttribute('aria-live', 'polite');
  actions.appendChild(message);
  const boutonOuvrir = el('button', 'bouton-go');
  boutonOuvrir.type = 'button';
  boutonOuvrir.setAttribute('data-role', 'ouvrir');
  boutonOuvrir.appendChild(el('span', '', 'Ouvrir'));
  boutonOuvrir.appendChild(icone('chevron', 22));
  boutonOuvrir.addEventListener('click', () => ouvrir());
  actions.appendChild(boutonOuvrir);
  corps.appendChild(actions);
  page.appendChild(corps);
  racine.appendChild(page);

  // ---------------------------------------------------------------- mode et vérifications

  function choisirMode(m) {
    mode = m;
    ['simu', 'reel'].forEach((k) => {
      cartes[k].setAttribute('aria-pressed', k === m ? 'true' : 'false');
      cartes[k].setAttribute('aria-checked', k === m ? 'true' : 'false');
      cartes[k].classList.toggle('choisie', k === m);
    });
    page.setAttribute('data-mode', m);
    tailles.hidden = m !== 'simu';
    dessinerOptions();
    suivreLiaison();
    majOuvrir();
  }

  function dessinerOptions() {
    blocMode.textContent = '';
    if (mode === 'simu') {
      const titre = el('div', 'accueil-section-titre');
      titre.appendChild(el('h2', '', 'En simulation'));
      blocMode.appendChild(titre);
      const ul = el('ul', 'accueil-astuces');
      ['Dessinez les murs et les meubles, la carte se fait seule.', 'Placez l\'accueil et les salles.',
        'Lancez la simulation, puis « Y aller » : le robot y va.'].forEach((t, i) => {
        const li = el('li');
        li.appendChild(el('span', 'accueil-astuce-numero', String(i + 1)));
        li.appendChild(el('span', '', t));
        ul.appendChild(li);
      });
      blocMode.appendChild(ul);
      return;
    }
    const titre = el('div', 'accueil-section-titre');
    titre.appendChild(el('h2', '', 'Avant de commencer'));
    const reverifier = el('button', 'bouton-icone petit');
    reverifier.type = 'button';
    reverifier.title = 'Vérifier à nouveau';
    reverifier.setAttribute('data-role', 'reverifier');
    reverifier.appendChild(icone('refaire', 18));
    reverifier.addEventListener('click', () => lireLiaison());
    titre.appendChild(reverifier);
    blocMode.appendChild(titre);
    const caseRepetition = el('label', 'case-repetition');
    const c = el('input');
    c.type = 'checkbox';
    c.checked = repetition;
    c.setAttribute('data-role', 'repetition');
    c.addEventListener('change', () => {
      repetition = c.checked;
      dessinerOptions();
      majOuvrir();
    });
    caseRepetition.appendChild(c);
    const textes = el('span', 'case-repetition-textes');
    textes.appendChild(el('strong', '', 'Répétition sans robot (faux G1)'));
    textes.appendChild(el('span', '', 'La chaîne du vrai robot, avec un faux G1 dans Gazebo.'));
    caseRepetition.appendChild(textes);
    blocMode.appendChild(caseRepetition);
    const ul = el('ul', 'verifications');
    ul.setAttribute('data-role', 'verifications');
    Object.keys(VERIFICATIONS).forEach((nom) => {
      const libelle = VERIFICATIONS[nom][repetition ? 'repetition' : 'reel'];
      if (!libelle) return;
      const li = el('li', 'verification');
      li.setAttribute('data-verif', nom);
      const pastille = el('span', 'verification-pastille');
      pastille.setAttribute('aria-hidden', 'true');
      li.appendChild(pastille);
      if (nom === 'telecommande') {
        const l = el('label', 'verification-case');
        const t = el('input');
        t.type = 'checkbox';
        t.checked = telecommande;
        t.addEventListener('change', () => {
          telecommande = t.checked;
          majVerifications();
        });
        l.appendChild(t);
        l.appendChild(el('span', 'verification-libelle', libelle));
        li.appendChild(l);
        li.appendChild(el('span', 'verification-detail', 'elle reste l\'arrêt d\'urgence'));
      } else {
        li.appendChild(el('span', 'verification-libelle', libelle));
        li.appendChild(el('span', 'verification-detail', ''));
      }
      ul.appendChild(li);
    });
    blocMode.appendChild(ul);
    const note = el('p', 'verification-message panneau-note');
    note.setAttribute('data-role', 'message-liaison');
    blocMode.appendChild(note);
    majVerifications();
  }

  function majVerifications() {
    blocMode.querySelectorAll('[data-verif]').forEach((li) => {
      const nom = li.getAttribute('data-verif');
      let etat;
      let detail;
      if (nom === 'telecommande') {
        etat = telecommande ? 'ok' : 'non';
        detail = 'elle reste l\'arrêt d\'urgence';
      } else {
        const r = etatVerification(nom, liaison, repetition);
        etat = r[0];
        detail = r[1];
      }
      li.setAttribute('data-etat', etat);
      li.querySelector('.verification-detail').textContent = detail;
    });
    const note = blocMode.querySelector('[data-role=message-liaison]');
    if (note) {
      note.textContent = repetition ? 'Rien n\'est envoyé au robot : tout tourne sur ce PC.'
        : (liaison ? liaison.message : 'Vérification de la liaison avec le robot…');
    }
  }

  async function lireLiaison() {
    try {
      liaison = await api.lire('/api/robot/liaison');
    } catch (e) {
      liaison = null;
      const note = blocMode.querySelector('[data-role=message-liaison]');
      if (note) note.textContent = e.message;
    }
    if (!ferme) majVerifications();
  }

  function suivreLiaison() {
    if (minuterie) clearInterval(minuterie);
    minuterie = null;
    if (mode !== 'reel') return;
    lireLiaison();
    minuterie = setInterval(() => { if (!document.hidden) lireLiaison(); }, PERIODE_LIAISON_MS);
  }

  // ---------------------------------------------------------------- lieux

  function dessinerLieux() {
    liste.textContent = '';
    if (!lieux.length) {
      liste.appendChild(el('p', 'panneau-note', 'Aucun lieu pour l\'instant : créez-en un avec « Nouveau lieu ».'));
      return;
    }
    lieux.forEach((l) => {
      const b = el('button', 'ligne-lieu');
      b.type = 'button';
      b.setAttribute('role', 'option');
      b.setAttribute('data-lieu', l.id);
      const choisi = l.id === lieuChoisi;
      b.setAttribute('aria-selected', choisi ? 'true' : 'false');
      b.appendChild(icone('lieu', 20));
      const textes = el('span', 'ligne-lieu-textes');
      textes.appendChild(el('span', 'ligne-lieu-nom', l.nom));
      const etages = l.erreur ? 'fichier invalide' : l.etages.map((e) => e.nom).join(', ');
      textes.appendChild(el('span', 'ligne-lieu-detail', l.id + (etages ? ' · ' + etages : '')));
      b.appendChild(textes);
      const scan = l.etages.some((e) => e.source_carte === 'scan');
      if (scan) b.appendChild(el('span', 'puce puce-scan', 'scanné'));
      b.addEventListener('click', () => choisirLieu(l.id));
      b.addEventListener('dblclick', () => {
        choisirLieu(l.id);
        ouvrir();
      });
      liste.appendChild(b);
      if (choisi && l.etages.length > 1) {
        const etages2 = el('div', 'ligne-lieu-etages');
        l.etages.forEach((e) => {
          const p = el('button', 'puce puce-etage' + (e.id === etageChoisi ? ' choisie' : ''), e.nom);
          p.type = 'button';
          p.setAttribute('data-etage', e.id);
          p.addEventListener('click', () => {
            etageChoisi = e.id;
            dessinerLieux();
          });
          etages2.appendChild(p);
        });
        liste.appendChild(etages2);
      }
    });
    const choisi = liste.querySelector('[aria-selected=true]');
    if (choisi) choisi.scrollIntoView({ block: 'nearest' });
  }

  function choisirLieu(id) {
    lieuChoisi = id;
    const l = lieux.find((x) => x.id === id);
    if (l && !l.etages.some((e) => e.id === etageChoisi)) etageChoisi = l.etages.length ? l.etages[0].id : null;
    dessinerLieux();
    majOuvrir();
  }

  async function chargerLieux() {
    try {
      lieux = await api.lire('/api/lieux');
    } catch (e) {
      lieux = [];
      liste.textContent = '';
      liste.appendChild(el('p', 'panneau-alerte', e.message));
      majOuvrir();
      return;
    }
    if (ferme) return;
    lieuxCharges = true;
    if (!lieux.some((l) => l.id === lieuChoisi)) lieuChoisi = lieux.length ? lieux[0].id : null;
    choisirLieu(lieuChoisi);
  }

  boutonNouveau.addEventListener('click', () => {
    formulaire.hidden = !formulaire.hidden;
    if (!formulaire.hidden) champNom.focus();
  });
  renoncer.addEventListener('click', () => { formulaire.hidden = true; });
  formulaire.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const nom = champNom.value.trim();
    if (!nom) {
      dire('Donnez un nom au nouveau lieu.', 'erreur');
      champNom.focus();
      return;
    }
    const id = idDepuisNom(nom);
    const refus = verifierId(id, lieux.map((l) => l.id), 'un lieu');
    if (refus) {
      dire(refus, 'erreur');
      return;
    }
    creer.disabled = true;
    try {
      const corpsDemande = { id: id, nom: nom };
      if (mode === 'simu') {
        corpsDemande.largeur = Math.max(3, parseFloat(champLargeur.value) || 20);
        corpsDemande.profondeur = Math.max(3, parseFloat(champProfondeur.value) || 15);
      }
      await api.envoyer('/api/lieux', corpsDemande);
      formulaire.hidden = true;
      champNom.value = '';
      lieuChoisi = id;
      etageChoisi = null;
      await chargerLieux();
      dire('Lieu « ' + nom + ' » créé : « Ouvrir » pour y travailler.', 'succes');
    } catch (e) {
      dire(e.message, 'erreur');
    } finally {
      creer.disabled = false;
    }
  });

  // ---------------------------------------------------------------- ouvrir

  function dire(texte, genre) {
    message.textContent = texte || '';
    message.setAttribute('data-genre', genre || 'info');
  }

  function majOuvrir() {
    boutonOuvrir.disabled = !lieuChoisi;
    boutonOuvrir.title = lieuChoisi ? 'Ouvrir le lieu (touche Entrée)' : 'Choisissez un lieu ou créez-en un';
    if (lieuxCharges && !lieux.length) dire('Créez d\'abord un lieu avec « Nouveau lieu ».', 'info');
  }

  function ouvrir() {
    if (!lieuChoisi) {
      dire('Choisissez un lieu, ou créez-en un.', 'erreur');
      return;
    }
    if (options.surOuvrir) {
      options.surOuvrir({ mode: mode, repetition: mode === 'reel' && repetition, lieu: lieuChoisi,
        etage: etageChoisi, telecommande: telecommande });
    }
  }

  function clavier(ev) {
    const cible = ev.target;
    if (cible && (cible.tagName === 'INPUT' || cible.tagName === 'TEXTAREA' || cible.tagName === 'SELECT')) return;
    if (ev.key === 'Enter' && !(cible && cible.tagName === 'BUTTON' && cible !== boutonOuvrir)) {
      ev.preventDefault();
      ouvrir();
    } else if (ev.key === 'ArrowLeft' || ev.key === 'ArrowRight') {
      if (cible && cible.closest && cible.closest('.liste-lieux')) return;
      choisirMode(ev.key === 'ArrowLeft' ? 'simu' : 'reel');
      cartes[mode].focus();
    }
  }
  document.addEventListener('keydown', clavier);

  api.lire('/api/etat').then((e) => {
    etatServeur.textContent = e.ros && e.ros.actif ? 'Serveur prêt · ROS 2' : 'Serveur prêt · sans ROS 2';
    etatServeur.setAttribute('data-genre', e.ros && e.ros.actif ? 'ok' : 'partiel');
  }).catch(() => {
    etatServeur.textContent = 'Serveur injoignable';
    etatServeur.setAttribute('data-genre', 'ko');
  });
  choisirMode(mode);
  chargerLieux();

  return {
    fermer: () => {
      ferme = true;
      if (minuterie) clearInterval(minuterie);
      document.removeEventListener('keydown', clavier);
      racine.textContent = '';
    },
  };
}
