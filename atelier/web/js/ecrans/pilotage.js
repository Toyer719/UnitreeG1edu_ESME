// Onglet Pilotage (vague 4, section 11.5 du plan), comme l'appli Unitree Explore : état et batterie,
// postures (avec leurs confirmations), joystick tactile, gestes, voix, volume et LED, danses du robot
// et « Mes chorégraphies » (éditeur à ligne de temps, aperçu 3D du G1, lecture sur le robot).
//
// Tout passe par le serveur de l'Atelier (/api/pilotage/*, /ws/pilotage), qui relaie vers le nœud
// pilotage (conteneur du Jetson, ou le PC en répétition). Les règles de sécurité sont dans le nœud ;
// l'onglet les rend visibles : grisé sans la main, confirmations, gros bouton ARRÊT toujours actif
// (touche Échap aussi).

import { api } from '../api.js';
import * as F from '../formulaire.js';
import { afficherErreur, afficherMessage } from '../messages.js';
import { Apercu3D } from '../pilotage/apercu3d.js';
import * as C from '../pilotage/choregraphie.js';
import { Joystick } from '../pilotage/joystick.js';
import { LigneTemps } from '../pilotage/ligne_temps.js';
import { Musique } from '../pilotage/musique.js';

const PERIODE_ETAT_MS = 500;
const SOUS_ONGLETS = [
  { id: 'commandes', texte: 'Commandes', titre: 'Postures, joystick, gestes, voix et LED' },
  { id: 'danses', texte: 'Danses du robot', titre: 'Les danses déjà dans le robot' },
  { id: 'choregraphies', texte: 'Mes chorégraphies', titre: 'Éditeur, aperçu 3D et lecture' },
];
const ACTIVITES = {
  repos: 'au repos', marche: 'marche au joystick', posture: 'changement de posture', geste: 'geste',
  danse: 'danse du robot', choregraphie: 'chorégraphie', arret: 'ARRÊT',
};
const MODES_FSM = {
  0: 'couple nul', 1: 'amorti', 3: 'assis', 500: 'démarrage', 501: 'démarrage', 702: 'se relève',
  706: 'accroupi', 801: 'debout, prêt à marcher',
};

function souvenirLocal(cle, defaut) {
  try {
    const v = localStorage.getItem('atelier.pilotage.' + cle);
    return v === null ? defaut : v;
  } catch (e) {
    return defaut;
  }
}

function memoriserLocal(cle, valeur) {
  try {
    localStorage.setItem('atelier.pilotage.' + cle, valeur);
  } catch (e) {
    // stockage indisponible : rien de grave
  }
}

function copie(d) {
  return JSON.parse(JSON.stringify(d));
}

function hexa(e) {
  const h = (v) => ('0' + Math.max(0, Math.min(255, v | 0)).toString(16)).slice(-2);
  return '#' + h(e.r) + h(e.g) + h(e.b);
}

function depuisHexa(texte) {
  const v = parseInt(String(texte).replace('#', ''), 16);
  return { r: (v >> 16) & 255, g: (v >> 8) & 255, b: v & 255 };
}

class EcranPilotage {
  constructor(racine) {
    this.racine = racine;
    this.config = null;
    this.etat = null;
    this.joignable = null;
    this.ws = null;
    this.joystick = null;
    this.modifie = false;
    this.minuteurs = [];
    this.sousOnglet = souvenirLocal('onglet', 'commandes');
    this.musique = new Musique();
    this.d = null;                     // chorégraphie en cours d'édition
    this.idChoregraphie = null;
    this.protegee = false;
    this.lecture = null;               // aperçu en cours : {t0, origine}
    this.tApercu = 0;
    this.apercu = null;
    this.ligne = null;
    this.choix = null;
    racine.classList.add('chargement');
    this.construire();
    api.lire('/api/pilotage/config').then((c) => {
      this.config = c;
      racine.classList.remove('chargement');
      this.ouvrirSousOnglet(this.sousOnglet);
      this.majEntete();
    }).catch((e) => {
      racine.classList.remove('chargement');
      afficherErreur(e);
    });
    this.lireEtat();
    this.minuteurs.push(setInterval(() => this.lireEtat(), PERIODE_ETAT_MS));
    this._echap = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        this.arret();
      }
    };
    document.addEventListener('keydown', this._echap);
  }

  // ---------------------------------------------------------------- squelette de l'écran

  construire() {
    const r = this.racine;
    r.innerHTML = '';
    const p = F.el('div', 'pilotage');
    const barre = F.el('div', 'pilotage-barre');
    this.pastille = F.el('span', 'pastille-pilotage', 'Nœud pilotage : …');
    this.etatMaitre = F.el('span', 'etat-maitre', '');
    this.etatRobot = F.el('span', 'etat-robot', '');
    this.etatBatterie = F.el('span', 'etat-batterie', '');
    const actions = F.el('div', 'pilotage-actions');
    this.boutonDemarrer = F.bouton(actions, 'Démarrer le pilotage', () => this.demarrerNoeud(), 'bouton');
    this.boutonDemarrer.title = 'Lance le nœud pilotage sur ce PC (simulation ou répétition)';
    this.boutonMain = F.bouton(actions, 'Prendre la main', () => this.basculerMain(), 'bouton bouton-principal');
    this.boutonArret = F.el('button', 'bouton-arret bouton-arret-pilotage', 'ARRÊT');
    this.boutonArret.type = 'button';
    this.boutonArret.title = 'Arrête tout : marche, chorégraphie (bras relâchés en 1 s), geste, guide. Touche Échap.';
    this.boutonArret.addEventListener('click', () => this.arret());
    [this.pastille, this.etatMaitre, this.etatRobot, this.etatBatterie, actions].forEach((e) => barre.appendChild(e));
    barre.appendChild(this.boutonArret);
    p.appendChild(barre);
    this.message = F.el('p', 'pilotage-message', '');
    p.appendChild(this.message);
    const onglets = F.el('div', 'pilotage-sous-onglets');
    this.barreOnglets = F.barreOutils(onglets, SOUS_ONGLETS, this.sousOnglet, (id) => this.ouvrirSousOnglet(id));
    p.appendChild(onglets);
    this.contenu = F.el('div', 'pilotage-contenu');
    p.appendChild(this.contenu);
    r.appendChild(p);
  }

  ouvrirSousOnglet(id) {
    if (!this.config) return;
    if (this.modifie && this.sousOnglet === 'choregraphies' && id !== 'choregraphies'
      && !window.confirm('La chorégraphie a des modifications non enregistrées. Les abandonner ?')) return;
    this.fermerSection();
    this.sousOnglet = id;
    memoriserLocal('onglet', id);
    this.barreOnglets.choisir(id);
    this.contenu.innerHTML = '';
    this.contenu.dataset.section = id;
    if (id === 'danses') this.sectionDanses();
    else if (id === 'choregraphies') this.sectionChoregraphies();
    else this.sectionCommandes();
    this.majEntete();
  }

  fermerSection() {
    if (this.joystick) {
      this.joystick.fermer();
      this.joystick = null;
    }
    this.fermerWs();
    this.arreterApercu();
    if (this.apercu) {
      this.apercu.fermer();
      this.apercu = null;
    }
    if (this.ligne) {
      this.ligne.fermer();
      this.ligne = null;
    }
    this.modifie = false;
  }

  // ---------------------------------------------------------------- état du nœud

  lireEtat() {
    if (this.enLecture) return;
    this.enLecture = true;
    api.lire('/api/pilotage/etat').then((e) => {
      this.etat = e;
      this.joignable = true;
      this.detailInjoignable = null;
    }).catch((e) => {
      this.joignable = false;
      this.detailInjoignable = e.message;
      this.etat = null;
    }).then(() => {
      this.enLecture = false;
      this.majEntete();
    });
  }

  aLaMain() {
    return !!(this.etat && this.etat.maitre === 'pilotage');
  }

  majEntete() {
    const e = this.etat;
    if (this.joignable === false) {
      this.pastille.textContent = 'Nœud pilotage injoignable';
      this.pastille.className = 'pastille-pilotage pastille-ko';
      this.pastille.title = this.detailInjoignable || '';
    } else if (e) {
      this.pastille.textContent = e.robot_repond ? 'Robot relié' : 'Le robot ne répond pas';
      this.pastille.className = 'pastille-pilotage ' + (e.robot_repond ? 'pastille-ok' : 'pastille-partielle');
      this.pastille.title = (this.config ? this.config.url : '') + (e.age_reponse_s !== null ? ' · réponse il y a ' + e.age_reponse_s + ' s' : '');
    }
    this.etatMaitre.textContent = e ? (e.maitre === 'pilotage' ? 'Vous avez la main' : 'Le guide a la main') : '';
    this.etatMaitre.className = 'etat-maitre ' + (e && e.maitre === 'pilotage' ? 'maitre-pilotage' : 'maitre-guide');
    this.etatRobot.textContent = e ? ('Mode ' + (e.fsm === null ? '?' : e.fsm) + (MODES_FSM[e.fsm] ? ' (' + MODES_FSM[e.fsm] + ')' : '')
      + ' · ' + (ACTIVITES[e.activite] || e.activite)) : '';
    this.etatBatterie.textContent = e && e.batterie ? 'Batterie ' + e.batterie.pourcent + ' %' : '';
    this.etatBatterie.classList.toggle('batterie-faible', !!(e && e.batterie && e.batterie.pourcent < 20));
    const local = this.config && this.config.local;
    this.boutonDemarrer.hidden = !local || this.joignable === true;
    this.boutonMain.disabled = !e;
    this.boutonMain.textContent = this.aLaMain() ? 'Rendre la main' : 'Prendre la main';
    this.boutonMain.className = 'bouton ' + (this.aLaMain() ? '' : 'bouton-principal');
    if (this.joignable === false) {
      this.message.textContent = this.detailInjoignable || '';
    } else if (e) {
      this.message.textContent = e.message + (e.dernier_refus && e.dernier_refus.message && e.dernier_refus.message !== e.message
        ? ' (Dernier refus du robot : ' + e.dernier_refus.message + ')' : '');
    }
    this.contenu.classList.toggle('sans-main', !this.aLaMain());
    if (this.majSection) this.majSection();
  }

  // ---------------------------------------------------------------- actions générales

  async arret() {
    this.arreterApercu();
    this.musique.arreter();
    if (this.joystick) this.joystick.toutLacher();
    try {
      const r = await api.envoyer('/api/pilotage/arret', {});
      afficherMessage(r.detail || 'ARRÊT envoyé.', r.danse ? 'avertissement' : 'succes');
    } catch (e) {
      afficherErreur(e);
    }
    this.lireEtat();
  }

  async demarrerNoeud() {
    this.boutonDemarrer.disabled = true;
    try {
      const r = await api.envoyer('/api/pilotage/demarrer', {});
      afficherMessage(r.detail, 'succes');
    } catch (e) {
      afficherErreur(e);
    }
    this.boutonDemarrer.disabled = false;
    this.lireEtat();
  }

  async basculerMain() {
    try {
      if (this.aLaMain()) {
        const r = await api.envoyer('/api/pilotage/maitre', { maitre: 'guide' });
        afficherMessage(r.detail, 'succes');
      } else {
        try {
          const r = await api.envoyer('/api/pilotage/maitre', { maitre: 'pilotage' });
          afficherMessage(r.detail, 'succes');
        } catch (e) {
          if (e.statut === 409 && /mission/.test(e.message)
            && window.confirm(e.message + '\n\nArrêter le guide et prendre la main ?')) {
            const r = await api.envoyer('/api/pilotage/maitre', { maitre: 'pilotage', forcer: true });
            afficherMessage(r.detail, 'avertissement');
          } else {
            throw e;
          }
        }
      }
    } catch (e) {
      afficherErreur(e);
    }
    this.lireEtat();
  }

  // POST en JSON ; renvoie {statut, corps} sans lever d'erreur pour un refus (403, 409, 428…)
  async poster(chemin, corps) {
    let r;
    try {
      r = await fetch(chemin, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corps || {}) });
    } catch (e) {
      return { statut: 0, corps: { detail: 'Le serveur de l\'Atelier ne répond pas. Est-il lancé ? Dans un terminal : g1-atelier' } };
    }
    let d;
    try {
      d = await r.json();
    } catch (e) {
      d = { detail: 'Réponse illisible du serveur (' + r.status + ').' };
    }
    return { statut: r.status, corps: d || {} };
  }

  // Envoie une commande ; gère la confirmation double « portique » (428 avec un jeton)
  async commande(chemin, corps, options) {
    options = options || {};
    let r = await this.poster(chemin, corps);
    if (r.statut === 428 && r.corps.confirmation === 'portique' && corps.portique && r.corps.jeton) {
      if (window.confirm(r.corps.detail + '\n\nLe robot est-il bien tenu au portique ?')) {
        r = await this.poster(chemin, Object.assign({}, corps, { jeton: r.corps.jeton }));
      } else {
        this.lireEtat();
        return null;
      }
    }
    this.lireEtat();
    if (r.statut >= 200 && r.statut < 300) {
      if (!options.silence) afficherMessage(r.corps.detail || 'Fait.', 'succes');
      return r.corps;
    }
    afficherMessage(r.corps.detail || ('Erreur ' + r.statut), r.statut === 428 ? 'avertissement' : 'erreur', r.corps.erreurs);
    return null;
  }

  // ---------------------------------------------------------------- Commandes

  sectionCommandes() {
    const c = this.config;
    const grille = F.el('div', 'pilotage-grille');
    this.contenu.appendChild(grille);
    // postures
    const postures = F.el('section', 'carte-section pilotage-postures');
    F.titre(postures, 'Postures');
    const normales = F.el('div', 'boutons-postures');
    c.postures.filter((p) => !p.confirmation).forEach((p) => {
      const b = F.bouton(normales, p.nom, () => this.commande('/api/pilotage/posture', { fsm: p.fsm }), 'bouton bouton-grand mouvement');
      b.dataset.fsm = String(p.fsm);
    });
    postures.appendChild(normales);
    const portique = F.el('div', 'zone-portique');
    portique.appendChild(F.el('p', 'panneau-alerte', 'Au portique seulement : le robot s\'affaisse s\'il n\'est pas tenu.'));
    this.casePortique = F.caseACocher(portique, 'Le robot est tenu au portique', false, () => {});
    const boutonsPortique = F.el('div', 'boutons-postures');
    c.postures.filter((p) => p.confirmation === 'portique').forEach((p) => {
      const b = F.bouton(boutonsPortique, p.nom, () => this.commande('/api/pilotage/posture',
        { fsm: p.fsm, portique: this.casePortique.checked }), 'bouton bouton-danger mouvement');
      b.dataset.fsm = String(p.fsm);
    });
    portique.appendChild(boutonsPortique);
    postures.appendChild(portique);
    grille.appendChild(postures);
    // joystick
    const marche = F.el('section', 'carte-section pilotage-joystick');
    F.titre(marche, 'Marche');
    F.paragraphe(marche, 'Tenez le manche pour marcher, lâchez pour arrêter (le robot s\'arrête seul 0,5 s après le dernier ordre).', 'panneau-note');
    this.joystick = new Joystick(marche, c.limites_marche, (m) => this.envoyerJoystick(m));
    this.noteJoystick = F.el('p', 'panneau-alerte note-joystick', '');
    marche.appendChild(this.noteJoystick);
    grille.appendChild(marche);
    // gestes
    const gestes = F.el('section', 'carte-section pilotage-gestes');
    F.titre(gestes, 'Gestes des bras');
    const boutonsGestes = F.el('div', 'boutons-gestes');
    c.gestes.filter((g) => g.id !== 99).forEach((g) => {
      const b = F.bouton(boutonsGestes, g.nom, () => this.commande('/api/pilotage/geste', { action: g.id }), 'bouton mouvement');
      b.dataset.geste = String(g.id);
    });
    gestes.appendChild(boutonsGestes);
    const relacher = F.bouton(gestes, 'Relâcher les bras (99)', () => this.commande('/api/pilotage/geste', { action: 99 }), 'bouton');
    relacher.dataset.geste = '99';
    const taches = F.el('div', 'boutons-gestes');
    taches.appendChild(F.el('span', 'champ-libelle', 'En marchant :'));
    c.taches.filter((t) => t.id === 0 || t.id === 2).forEach((t) => {
      F.bouton(taches, t.nom, () => this.commande('/api/pilotage/tache', { tache: t.id }), 'bouton mouvement');
    });
    gestes.appendChild(taches);
    grille.appendChild(gestes);
    // voix, volume, LED
    const voix = F.el('section', 'carte-section pilotage-voix');
    F.titre(voix, 'Voix et LED');
    let texte = 'Bonjour, je suis le robot d\'accueil.';
    const champ = F.champTexte(voix, 'Phrase', texte, (v) => { texte = v; }, { lignes: 2 });
    champ.addEventListener('input', () => { texte = champ.value; });
    F.bouton(voix, 'Dire (voix du robot)', () => this.commande('/api/pilotage/voix', { texte }), 'bouton');
    F.paragraphe(voix, 'La synthèse du robot (1001) ne parle peut-être pas français (à vérifier) : la voix de l\'équipe passe par /robot/dire.', 'panneau-note');
    let volume = 70;
    const ligneVolume = F.el('div', 'champ');
    ligneVolume.appendChild(F.el('span', 'champ-libelle', 'Volume'));
    const curseur = F.el('input');
    curseur.type = 'range';
    curseur.min = '0';
    curseur.max = '100';
    curseur.value = String(volume);
    const affiche = F.el('span', 'champ-valeur', volume + ' %');
    curseur.addEventListener('input', () => { volume = parseInt(curseur.value, 10); affiche.textContent = volume + ' %'; });
    ligneVolume.appendChild(curseur);
    ligneVolume.appendChild(affiche);
    voix.appendChild(ligneVolume);
    F.bouton(voix, 'Appliquer le volume', () => this.commande('/api/pilotage/volume', { volume }), 'bouton');
    const ligneLed = F.el('div', 'champ');
    ligneLed.appendChild(F.el('span', 'champ-libelle', 'Couleur'));
    const couleur = F.el('input');
    couleur.type = 'color';
    couleur.value = '#ff0080';
    ligneLed.appendChild(couleur);
    voix.appendChild(ligneLed);
    const boutonsLed = F.el('div', 'formulaire-ligne');
    F.bouton(boutonsLed, 'Allumer la LED', () => this.commande('/api/pilotage/led', depuisHexa(couleur.value)), 'bouton');
    F.bouton(boutonsLed, 'Éteindre', () => this.commande('/api/pilotage/led', { r: 0, g: 0, b: 0 }), 'bouton');
    voix.appendChild(boutonsLed);
    grille.appendChild(voix);
    this.ouvrirWs();                 // la liaison est prête quand le doigt touche le manche
    this.majSection = () => {
      const sans = !this.aLaMain();
      this.contenu.querySelectorAll('.mouvement').forEach((b) => { b.disabled = sans; });
      if (this.joystick) this.joystick.activer(!sans && !(this.etat && this.etat.danse));
      if (this.noteJoystick) {
        this.noteJoystick.textContent = sans ? 'Prenez la main pour marcher et faire des gestes.'
          : (this.etat && this.etat.danse ? 'Pendant une danse, le joystick est refusé.' : (this.refusJoystick || ''));
      }
    };
    this.majSection();
  }

  ouvrirWs() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return;
    const url = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws/pilotage';
    const ws = new WebSocket(url);
    this.ws = ws;
    ws.onmessage = (ev) => {
      let m = null;
      try {
        m = JSON.parse(ev.data);
      } catch (e) {
        return;
      }
      if (m.type === 'refus') {
        this.refusJoystick = m.detail;
        if (this.noteJoystick) this.noteJoystick.textContent = m.detail;
      } else if (m.type === 'etat' && m.etat) {
        this.etat = m.etat;
      }
    };
    ws.onclose = () => {
      if (this.ws === ws) this.ws = null;
    };
  }

  fermerWs() {
    if (this.ws) {
      try {
        this.ws.close();
      } catch (e) {
        // déjà fermé
      }
      this.ws = null;
    }
  }

  envoyerJoystick(message) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.ouvrirWs();                  // l'ordre est perdu : le suivant partira (0,1 s plus tard)
      return;
    }
    this.refusJoystick = '';
    this.ws.send(JSON.stringify(message));
  }

  // ---------------------------------------------------------------- Danses du robot

  sectionDanses() {
    const s = F.el('section', 'carte-section pilotage-danses');
    F.titre(s, 'Danses du robot');
    s.appendChild(F.el('p', 'panneau-alerte', 'Les danses font bouger les pieds : dégagez 2 à 3 m autour du robot. '
      + 'Aucune commande connue n\'interrompt une danse : gardez la télécommande en main, c\'est l\'arrêt d\'urgence.'));
    F.paragraphe(s, 'Source communautaire non officielle (micrologiciel 1.5.6) : la liste est lue dans le robot. '
      + 'Les danses 401, 402 et 403 sont interdites (le robot peut se coucher par terre). Au portique d\'abord pour une danse jamais essayée.', 'panneau-note');
    const ligne = F.el('div', 'formulaire-ligne');
    F.bouton(ligne, 'Lire la liste du robot', () => this.lireDanses(true), 'bouton bouton-principal');
    this.caseZone = F.caseACocher(ligne, 'Zone libre de 2 à 3 m, télécommande en main', false, () => this.majSection());
    s.appendChild(ligne);
    this.progresDanse = F.el('div', 'progres-danse');
    this.progresDanse.hidden = true;
    s.appendChild(this.progresDanse);
    this.tableDanses = F.el('table', 'tableau tableau-danses');
    s.appendChild(this.tableDanses);
    this.contenu.appendChild(s);
    this.danses = null;
    this.lireDanses(false);
    this.majSection = () => {
      const e = this.etat;
      this.contenu.querySelectorAll('.jouer-danse').forEach((b) => {
        b.disabled = !this.aLaMain() || b.dataset.interdite === '1' || !!(e && e.danse) || !this.caseZone.checked;
      });
      if (e && e.danse) {
        this.progresDanse.hidden = false;
        const duree = e.danse.duree_s || 60;
        const part = Math.min(1, e.danse.ecoule_s / duree);
        this.progresDanse.textContent = 'Danse ' + e.danse.id + ' (' + (e.danse.nom || 'sans nom') + ') : '
          + e.danse.ecoule_s.toFixed(0) + ' s sur ' + (e.danse.duree_s ? e.danse.duree_s.toFixed(0) : '?') + ' s';
        this.progresDanse.style.setProperty('--part', String(part));
      } else {
        this.progresDanse.hidden = true;
      }
    };
    this.majSection();
  }

  async lireDanses(robot) {
    try {
      const r = await api.lire('/api/pilotage/danses' + (robot ? '?lire=1' : ''));
      this.danses = r.danses;
      this.remplirDanses();
      if (robot) afficherMessage(r.detail, 'succes');
    } catch (e) {
      if (robot) afficherErreur(e);
      else this.remplirDanses();
    }
  }

  remplirDanses() {
    const t = this.tableDanses;
    t.innerHTML = '';
    if (!this.danses) {
      const l = t.insertRow();
      l.insertCell().textContent = 'Liste pas encore lue : « Lire la liste du robot ».';
      return;
    }
    const entete = t.createTHead().insertRow();
    ['N°', 'Nom', 'Durée', 'Remarque', ''].forEach((x) => {
      const c = document.createElement('th');
      c.textContent = x;
      entete.appendChild(c);
    });
    const corps = t.createTBody();
    this.danses.forEach((d) => {
      const l = corps.insertRow();
      l.className = d.interdite ? 'danse-interdite' : (d.essayee ? 'danse-essayee' : 'danse-inconnue');
      l.dataset.danse = String(d.id);
      l.insertCell().textContent = String(d.id);
      l.insertCell().textContent = d.nom || '—';
      l.insertCell().textContent = d.duree_s ? d.duree_s.toFixed(1) + ' s' : '?';
      l.insertCell().textContent = d.remarque;
      const c = l.insertCell();
      if (d.interdite) {
        c.appendChild(F.el('span', 'etiquette-interdite', 'Interdite'));
      } else {
        const b = F.bouton(c, 'Jouer', () => this.jouerDanse(d), 'bouton jouer-danse');
        b.dataset.interdite = '0';
      }
    });
    if (this.majSection) this.majSection();
  }

  async jouerDanse(d) {
    if (!this.caseZone.checked) return;
    if (!window.confirm('Danse ' + d.id + ' (' + (d.nom || 'sans nom') + ', ' + (d.duree_s || '?') + ' s).\n\n'
      + this.config.confirmations.zone_libre)) return;
    await this.commande('/api/pilotage/danse', { id: d.id, zone_libre: true });
  }

  // ---------------------------------------------------------------- Mes chorégraphies

  sectionChoregraphies() {
    const cadre = F.el('div', 'pilotage-choregraphies');
    // colonne de gauche : liste et fichier
    const gauche = F.el('section', 'carte-section choregraphie-fichier');
    F.titre(gauche, 'Mes chorégraphies');
    this.listeChoregraphies = F.el('select', 'liste-choregraphies');
    this.listeChoregraphies.setAttribute('aria-label', 'Chorégraphie');
    this.listeChoregraphies.addEventListener('change', () => this.chargerChoregraphie(this.listeChoregraphies.value));
    gauche.appendChild(this.listeChoregraphies);
    const boutons = F.el('div', 'formulaire-ligne');
    F.bouton(boutons, 'Nouvelle', () => this.nouvelleChoregraphie(), 'bouton');
    this.boutonEnregistrer = F.bouton(boutons, 'Enregistrer', () => this.enregistrer(false), 'bouton bouton-principal');
    F.bouton(boutons, 'Enregistrer sous', () => this.enregistrer(true), 'bouton');
    this.boutonSupprimer = F.bouton(boutons, 'Supprimer', () => this.supprimer(), 'bouton bouton-danger');
    gauche.appendChild(boutons);
    this.resume = F.el('div', 'choregraphie-resume');
    gauche.appendChild(this.resume);
    this.erreurs = F.el('ul', 'choregraphie-erreurs');
    gauche.appendChild(this.erreurs);
    this.reglages = F.el('div', 'formulaire choregraphie-reglages');
    gauche.appendChild(this.reglages);
    F.paragraphe(gauche, 'Importer les bras d\'une vidéo de danse (pose humaine, hors ligne) : '
      + 'g1-pilotage importer-video DANSE.mp4 --id ma_danse, puis rechargez cette liste.', 'panneau-note');
    cadre.appendChild(gauche);
    // centre : aperçu 3D et lecture
    const centre = F.el('section', 'carte-section choregraphie-apercu');
    this.vue = F.el('div', 'apercu-3d');
    centre.appendChild(this.vue);
    const transport = F.el('div', 'formulaire-ligne transport');
    this.boutonApercu = F.bouton(transport, '▶ Aperçu', () => this.basculerApercu(), 'bouton');
    this.boutonApercu.dataset.role = 'apercu';
    F.bouton(transport, '⏮', () => { this.arreterApercu(); this.placer(0); }, 'bouton').title = 'Revenir au début';
    this.affichageTemps = F.el('span', 'temps-apercu', '0,0 s');
    transport.appendChild(this.affichageTemps);
    this.caseSon = F.caseACocher(transport, 'Son', souvenirLocal('son', '1') === '1', (v) => memoriserLocal('son', v ? '1' : '0'));
    centre.appendChild(transport);
    const jouer = F.el('div', 'formulaire-ligne jouer-robot');
    this.caseZoneChoregraphie = F.caseACocher(jouer, 'Zone libre autour du robot, télécommande en main', false, () => this.majSection());
    this.vitesseLecture = parseFloat(souvenirLocal('vitesse', '1')) || 1;
    F.listeDeroulante(jouer, 'Vitesse', String(this.vitesseLecture),
      [{ id: '1', texte: 'normale' }, { id: '0.75', texte: '3/4' }, { id: '0.5', texte: '1/2 (premiers essais)' }, { id: '0.25', texte: '1/4' }],
      (v) => { this.vitesseLecture = parseFloat(v); memoriserLocal('vitesse', v); });
    this.boutonJouer = F.bouton(jouer, 'Jouer sur le robot', () => this.jouerSurLeRobot(), 'bouton bouton-principal mouvement');
    centre.appendChild(jouer);
    this.progresChoregraphie = F.el('p', 'panneau-note progres-choregraphie', '');
    centre.appendChild(this.progresChoregraphie);
    cadre.appendChild(centre);
    // droite : l'élément choisi
    this.panneauChoix = F.el('section', 'carte-section choregraphie-element');
    cadre.appendChild(this.panneauChoix);
    // bas : ligne de temps
    const bas = F.el('section', 'carte-section choregraphie-ligne');
    const ajouts = F.el('div', 'formulaire-ligne');
    ajouts.appendChild(F.el('span', 'champ-libelle', 'Ajouter ici :'));
    F.bouton(ajouts, 'Pose des bras', () => this.ajouter('bras'), 'bouton');
    F.bouton(ajouts, 'Pas', () => this.ajouter('pas'), 'bouton');
    F.bouton(ajouts, 'LED', () => this.ajouter('led'), 'bouton');
    F.bouton(ajouts, 'Parole', () => this.ajouter('paroles'), 'bouton');
    F.caseACocher(ajouts, 'Aimant au battement', true, (v) => { if (this.ligne) this.ligne.aimant = v; });
    bas.appendChild(ajouts);
    const zoneLigne = F.el('div', 'zone-ligne-temps');
    bas.appendChild(zoneLigne);
    cadre.appendChild(bas);
    this.contenu.appendChild(cadre);
    this.apercu = new Apercu3D(this.vue);
    this.apercu.charger().then(() => this.placer(this.tApercu)).catch((e) => afficherErreur(e));
    this.ligne = new LigneTemps(zoneLigne, {
      choisir: (choix) => { this.choix = choix; this.panneauElement(); },
      temps: (t) => { this.arreterApercu(); this.placer(t); },
      modifie: () => this.change(),
    });
    this.majSection = () => {
      const e = this.etat;
      this.boutonJouer.disabled = !this.aLaMain() || !this.d || !this.caseZoneChoregraphie.checked
        || !!(e && (e.danse || e.choregraphie)) || (this.erreursActuelles && this.erreursActuelles.length > 0);
      if (e && e.choregraphie && e.choregraphie.t !== null && e.choregraphie.t !== undefined) {
        this.progresChoregraphie.textContent = 'Sur le robot : « ' + (e.choregraphie.nom || e.choregraphie.id) + ' » à '
          + Math.max(0, e.choregraphie.t).toFixed(1) + ' s sur ' + e.choregraphie.duree_s + ' s, bras pondérés à '
          + Math.round(100 * e.choregraphie.poids_bras) + ' %';
      } else if (e && e.choregraphie) {
        this.progresChoregraphie.textContent = 'Arrêt : les bras sont rendus au contrôleur d\'Unitree (poids '
          + Math.round(100 * e.choregraphie.poids_bras) + ' %).';
      } else {
        this.progresChoregraphie.textContent = '';
      }
    };
    this.listerChoregraphies(souvenirLocal('choregraphie', this.config.exemple));
  }

  async listerChoregraphies(choisir) {
    try {
      const r = await api.lire('/api/pilotage/choregraphies');
      this.listeChoregraphies.innerHTML = '';
      r.choregraphies.forEach((c) => {
        const o = F.el('option', '', c.nom + (c.erreurs && c.erreurs.length ? ' (à corriger)' : '') + (c.protegee ? ' — exemple' : ''));
        o.value = c.id;
        this.listeChoregraphies.appendChild(o);
      });
      const ids = r.choregraphies.map((c) => c.id);
      const id = ids.indexOf(choisir) >= 0 ? choisir : (ids[0] || null);
      if (id) {
        this.listeChoregraphies.value = id;
        await this.chargerChoregraphie(id);
      } else {
        this.nouvelleChoregraphie();
      }
    } catch (e) {
      afficherErreur(e);
    }
  }

  async chargerChoregraphie(id) {
    if (this.modifie && !window.confirm('La chorégraphie a des modifications non enregistrées. Les abandonner ?')) {
      this.listeChoregraphies.value = this.idChoregraphie || '';
      return;
    }
    try {
      const r = await api.lire('/api/pilotage/choregraphies/' + encodeURIComponent(id));
      this.arreterApercu();
      this.d = r.choregraphie;
      this.idChoregraphie = id;
      this.protegee = !!r.protegee;
      this.modifie = false;
      memoriserLocal('choregraphie', id);
      this.choix = null;
      this.montrerErreurs(r.erreurs, r.resume);
      this.rafraichir();
      this.placer(0);
    } catch (e) {
      afficherErreur(e);
    }
  }

  nouvelleChoregraphie() {
    const id = window.prompt('Nom de la nouvelle chorégraphie (lettres minuscules sans accent, chiffres, _ ou -) :', 'ma_choregraphie');
    if (!id) return;
    this.arreterApercu();
    this.d = C.nouvelle(id, id);
    this.idChoregraphie = id;
    this.protegee = false;
    this.change();
    this.rafraichir();
    this.placer(0);
  }

  async enregistrer(sous) {
    if (!this.d) return;
    let id = this.idChoregraphie;
    if (sous || this.protegee) {
      id = window.prompt('Enregistrer sous le nom :', this.protegee ? id + '_copie' : id);
      if (!id) return;
    }
    try {
      const r = await api.ecrire('/api/pilotage/choregraphies/' + encodeURIComponent(id), { choregraphie: Object.assign({}, this.d, { id }) });
      this.d = r.choregraphie;
      this.idChoregraphie = id;
      this.protegee = false;
      this.modifie = false;
      afficherMessage('Chorégraphie « ' + id + ' » enregistrée.', 'succes');
      await this.listerChoregraphies(id);
    } catch (e) {
      afficherErreur(e);
    }
  }

  async supprimer() {
    if (!this.idChoregraphie || this.protegee) return;
    if (!window.confirm('Supprimer la chorégraphie « ' + this.idChoregraphie + ' » ?')) return;
    let r;
    try {
      r = await fetch('/api/pilotage/choregraphies/' + encodeURIComponent(this.idChoregraphie), { method: 'DELETE' });
    } catch (e) {
      afficherMessage('Le serveur de l\'Atelier ne répond pas.', 'erreur');
      return;
    }
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      afficherMessage(d.detail || ('Erreur ' + r.status), 'erreur');
      return;
    }
    this.modifie = false;
    afficherMessage('Chorégraphie supprimée.', 'succes');
    await this.listerChoregraphies(this.config.exemple);
  }

  change() {
    this.modifie = true;
    if (this.ligne) this.ligne.definir(this.d);
    this.placer(this.tApercu);
    clearTimeout(this.minuteurVerif);
    this.minuteurVerif = setTimeout(() => this.verifier(), 400);
  }

  async verifier() {
    if (!this.d) return;
    try {
      const r = await api.envoyer('/api/pilotage/choregraphies/verifier', { choregraphie: this.d });
      this.montrerErreurs(r.erreurs, r.resume);
    } catch (e) {
      afficherErreur(e);
    }
  }

  montrerErreurs(erreurs, resume) {
    this.erreursActuelles = erreurs || [];
    this.erreurs.innerHTML = '';
    if (this.erreursActuelles.length) {
      this.erreurs.appendChild(F.el('li', 'rapport-titre-erreur', 'À corriger avant de jouer :'));
      this.erreursActuelles.forEach((m) => this.erreurs.appendChild(F.el('li', '', m)));
    } else {
      this.erreurs.appendChild(F.el('li', 'rapport-ok', 'Chorégraphie sûre : dans les limites des bras et des pas.'));
    }
    this.resume.innerHTML = '';
    if (this.d) {
      const r = resume || {};
      const v = r.vitesse_bras_max === null || r.vitesse_bras_max === undefined ? C.vitesseMax(this.d) : r.vitesse_bras_max;
      const dep = r.deplacement_m === null || r.deplacement_m === undefined ? C.deplacement(this.d).distance : r.deplacement_m;
      F.valeur(this.resume, 'Durée', this.d.duree_s + ' s');
      F.valeur(this.resume, 'Bras', 'au plus ' + v.toFixed(2) + ' rad/s (limite ' + this.config.vitesse_bras_max + ')');
      F.valeur(this.resume, 'Déplacement', 'au plus ' + dep.toFixed(2) + ' m du départ (limite ' + this.config.deplacement_max_m + ' m)');
    }
    if (this.majSection) this.majSection();
  }

  rafraichir() {
    this.boutonSupprimer.disabled = this.protegee;
    this.boutonEnregistrer.title = this.protegee ? 'L\'exemple est en lecture seule : il sera enregistré sous un autre nom' : '';
    this.remplirReglages();
    if (this.ligne) this.ligne.definir(this.d);
    this.panneauElement();
  }

  remplirReglages() {
    const r = this.reglages;
    r.innerHTML = '';
    if (!this.d) return;
    const d = this.d;
    F.titre(r, 'Réglages');
    F.champTexte(r, 'Nom', d.nom, (v) => { d.nom = v; this.change(); });
    F.champNombre(r, 'Durée', d.duree_s, { pas: 0.5, min: 1, max: 600, unite: 's', decimales: 2 }, (v) => { d.duree_s = v; this.change(); });
    F.champNombre(r, 'Zone libre', d.zone_libre_m, { pas: 0.5, min: 2, max: 10, unite: 'm', decimales: 1 }, (v) => { d.zone_libre_m = v; this.change(); });
    if (!d.musique) d.musique = { fichier: null, battement: { bpm: 120, accent: 4 }, decalage_s: 0, sortie: 'navigateur' };
    const m = d.musique;
    if (!m.battement) m.battement = { bpm: 120, accent: 4 };
    F.champNombre(r, 'Battement', m.battement.bpm, { pas: 1, min: 40, max: 220, unite: 'temps/min', decimales: 0 }, (v) => { m.battement.bpm = v; this.change(); });
    F.champTexte(r, 'Musique', m.fichier || '', (v) => { m.fichier = v.trim() || null; this.change(); },
      { indice: 'fichier de choregraphies/musique/ (vide : battement)' });
    F.champNombre(r, 'Décalage', m.decalage_s || 0, { pas: 0.05, min: -60, max: 60, unite: 's', decimales: 2 }, (v) => { m.decalage_s = v; this.change(); });
    if (d.bras) {
      F.champNombre(r, 'Rampe des bras', d.bras.rampe_s === undefined ? 1 : d.bras.rampe_s, { pas: 0.5, min: 1, max: 10, unite: 's', decimales: 2 },
        (v) => { d.bras.rampe_s = v; this.change(); });
      F.listeDeroulante(r, 'Mouvement', d.bras.interpolation || 'douce', [{ id: 'douce', texte: 'doux (sans à-coup)' }, { id: 'lineaire', texte: 'linéaire' }],
        (v) => { d.bras.interpolation = v; this.change(); });
    }
  }

  ajouter(piste) {
    if (!this.d) return;
    const t = Math.round(this.tApercu * 100) / 100;
    let index = 0;
    if (piste === 'bras') {
      index = C.ajouterPose(this.d, Math.min(Math.max(t, (this.d.bras && this.d.bras.rampe_s) || 1.5), this.d.duree_s - 1.5));
    } else {
      if (!this.d[piste]) this.d[piste] = [];
      let e;
      if (piste === 'pas') e = { t, vx: 0, vy: 0.1, wz: 0, duree_s: 1.0 };
      else if (piste === 'led') e = { t, r: 255, g: 0, b: 128 };
      else e = { t, texte: 'Bonjour !' };
      this.d[piste].push(e);
      this.d[piste].sort((a, b) => a.t - b.t);
      index = this.d[piste].indexOf(e);
    }
    this.choix = { piste, index };
    if (this.ligne) this.ligne.choisir(this.choix);
    this.change();
    this.panneauElement();
  }

  panneauElement() {
    const p = this.panneauChoix;
    if (!p) return;
    p.innerHTML = '';
    const d = this.d;
    const choix = this.choix;
    if (!d || !choix || choix.index === null || choix.index === undefined) {
      F.titre(p, 'Élément choisi');
      F.paragraphe(p, 'Cliquez un élément de la ligne de temps pour le modifier, ou ajoutez-en un à la tête de lecture.', 'panneau-note');
      return;
    }
    const liste = choix.piste === 'bras' ? d.bras.poses : d[choix.piste];
    const e = liste && liste[choix.index];
    if (!e) return;
    const supprimer = () => {
      liste.splice(choix.index, 1);
      this.choix = null;
      if (this.ligne) this.ligne.choisir(null);
      this.change();
      this.panneauElement();
    };
    const temps = (v) => { e.t = v; liste.sort((a, b) => a.t - b.t); choix.index = liste.indexOf(e); this.change(); };
    if (choix.piste === 'bras') {
      F.titre(p, 'Pose des bras');
      F.champTexte(p, 'Nom', e.nom || '', (v) => { e.nom = v; this.change(); });
      F.champNombre(p, 'Temps', e.t, { pas: 0.05, min: 0, unite: 's', decimales: 2 }, temps);
      const angles = C.anglesDeLaPose(d, choix.index);
      this.config.articulations.forEach((a) => {
        const ligne = F.el('div', 'champ champ-angle');
        ligne.appendChild(F.el('span', 'champ-libelle', C.libelleArticulation(a.nom)));
        const curseur = F.el('input');
        curseur.type = 'range';
        curseur.min = String(a.bas);
        curseur.max = String(a.haut);
        curseur.step = '0.01';
        curseur.value = String(angles[a.nom]);
        curseur.dataset.articulation = a.nom;
        const valeur = F.el('span', 'champ-valeur', angles[a.nom].toFixed(2));
        curseur.addEventListener('input', () => {
          e.q[a.nom] = Math.round(parseFloat(curseur.value) * 1000) / 1000;
          valeur.textContent = e.q[a.nom].toFixed(2);
          this.tApercu = e.t;
          this.change();
        });
        ligne.appendChild(curseur);
        ligne.appendChild(valeur);
        p.appendChild(ligne);
      });
      F.paragraphe(p, 'Les angles sont bornés aux limites du robot (URDF moins 0,05 rad) ; la vitesse est vérifiée entre deux poses.', 'panneau-note');
    } else if (choix.piste === 'pas') {
      F.titre(p, 'Pas de marche');
      F.champNombre(p, 'Temps', e.t, { pas: 0.05, min: 0, unite: 's', decimales: 2 }, temps);
      const l = this.config.limites_pas;
      F.champNombre(p, 'Avant', e.vx, { pas: 0.05, min: -l.vx, max: l.vx, unite: 'm/s', decimales: 2 }, (v) => { e.vx = v; this.change(); });
      F.champNombre(p, 'Côté', e.vy, { pas: 0.05, min: -l.vy, max: l.vy, unite: 'm/s', decimales: 2 }, (v) => { e.vy = v; this.change(); });
      F.champNombre(p, 'Rotation', e.wz, { pas: 0.05, min: -l.wz, max: l.wz, unite: 'rad/s', decimales: 2 }, (v) => { e.wz = v; this.change(); });
      F.champNombre(p, 'Durée', e.duree_s, { pas: 0.1, min: 0.2, max: 2, unite: 's', decimales: 2 }, (v) => { e.duree_s = v; this.change(); });
    } else if (choix.piste === 'led') {
      F.titre(p, 'Couleur de la LED');
      F.champNombre(p, 'Temps', e.t, { pas: 0.05, min: 0, unite: 's', decimales: 2 }, temps);
      const ligne = F.el('div', 'champ');
      ligne.appendChild(F.el('span', 'champ-libelle', 'Couleur'));
      const c = F.el('input');
      c.type = 'color';
      c.value = hexa(e);
      c.addEventListener('input', () => { Object.assign(e, depuisHexa(c.value)); this.change(); });
      ligne.appendChild(c);
      p.appendChild(ligne);
    } else if (choix.piste === 'paroles') {
      F.titre(p, 'Parole');
      F.champNombre(p, 'Temps', e.t, { pas: 0.05, min: 0, unite: 's', decimales: 2 }, temps);
      F.champTexte(p, 'Texte', e.texte, (v) => { e.texte = v; this.change(); }, { lignes: 2 });
      F.listeDeroulante(p, 'Voix', e.voix || 'equipe', [{ id: 'equipe', texte: 'voix de l\'équipe (/robot/dire)' }, { id: 'unitree', texte: 'synthèse du robot (1001)' }],
        (v) => { if (v === 'equipe') delete e.voix; else e.voix = v; this.change(); });
    } else if (choix.piste === 'gestes') {
      F.titre(p, 'Geste d\'Unitree');
      F.champNombre(p, 'Temps', e.t, { pas: 0.05, min: 0, unite: 's', decimales: 2 }, temps);
      F.listeDeroulante(p, 'Geste', String(e.action), this.config.gestes.map((g) => ({ id: String(g.id), texte: g.nom })),
        (v) => { e.action = parseInt(v, 10); this.change(); });
    }
    F.bouton(p, 'Supprimer cet élément', supprimer, 'bouton bouton-danger');
  }

  // ---------------------------------------------------------------- aperçu

  placer(t) {
    if (!this.d) return;
    t = Math.max(0, Math.min(this.d.duree_s, t));
    this.tApercu = t;
    if (this.apercu && this.apercu.pret) {
      this.apercu.poser(C.anglesVus(this.d, t).q, C.positionBase(this.d, t), C.couleurLed(this.d, t));
    }
    if (this.ligne) this.ligne.temps(t);
    if (this.affichageTemps) this.affichageTemps.textContent = t.toFixed(1).replace('.', ',') + ' s / ' + this.d.duree_s + ' s';
    window.apercuPilotage = this.apercu;
    if (this.apercu) this.apercu.tChoregraphie = t;
  }

  basculerApercu() {
    if (this.lecture) this.arreterApercu();
    else this.demarrerApercu(this.tApercu >= this.d.duree_s - 0.05 ? 0 : this.tApercu, 0, this.vitesseLecture);
  }

  // Aperçu à partir de l'instant t de la chorégraphie, dans « dans » secondes, à la vitesse de lecture
  demarrerApercu(t, dans, vitesse) {
    if (!this.d) return;
    this.arreterApercu();
    vitesse = vitesse || 1;
    const origine = performance.now() + (dans || 0) * 1000;
    this.lecture = { origine, t, vitesse };
    if (this.boutonApercu) this.boutonApercu.textContent = '⏸ Pause';
    if (this.caseSon && this.caseSon.checked) this.musique.jouer(this.d, t, dans || 0, vitesse);
    const pas = () => {
      if (!this.lecture) return;
      const tc = this.lecture.t + ((performance.now() - this.lecture.origine) / 1000) * this.lecture.vitesse;
      if (performance.now() >= this.lecture.origine) this.placer(tc);
      if (tc >= this.d.duree_s) {
        this.arreterApercu();
        return;
      }
      requestAnimationFrame(pas);
    };
    requestAnimationFrame(pas);
  }

  arreterApercu() {
    this.lecture = null;
    this.musique.arreter();
    if (this.boutonApercu) this.boutonApercu.textContent = '▶ Aperçu';
  }

  async jouerSurLeRobot() {
    if (!this.d || !this.caseZoneChoregraphie.checked) return;
    if (this.modifie) {
      afficherMessage('Enregistrez d\'abord la chorégraphie : le robot joue le fichier enregistré.', 'avertissement');
      return;
    }
    const vitesse = this.vitesseLecture || 1;
    if (!window.confirm('Jouer « ' + this.d.nom + ' » sur le robot (' + (this.d.duree_s / vitesse).toFixed(0) + ' s'
      + (vitesse < 1 ? ', vitesse ' + vitesse : '') + ', zone libre de ' + this.d.zone_libre_m + ' m).\n\n'
      + this.config.confirmations.zone_libre)) return;
    const r = await this.commande('/api/pilotage/choregraphies/' + encodeURIComponent(this.idChoregraphie) + '/jouer',
      { zone_libre: true, vitesse });
    if (r && r.debut_mur) {
      // aperçu et musique calés sur le départ annoncé par le nœud
      this.demarrerApercu(0, Math.max(0, r.debut_mur - Date.now() / 1000), vitesse);
      (r.avertissements || []).forEach((a) => afficherMessage(a, 'avertissement'));
    }
  }

  fermer() {
    this.minuteurs.forEach((m) => clearInterval(m));
    clearTimeout(this.minuteurVerif);
    document.removeEventListener('keydown', this._echap);
    this.fermerSection();
    this.musique.arreter();
  }
}

export function ouvrir(racine) {
  const ecran = new EcranPilotage(racine);
  window.ecranPilotage = ecran;
  return {
    modifie: () => ecran.modifie,
    fermer: () => {
      ecran.fermer();
      if (window.ecranPilotage === ecran) window.ecranPilotage = null;
    },
  };
}
