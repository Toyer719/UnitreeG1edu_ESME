// Écran Piloter (Réel › Piloter, vague 4 : section 11.5 du plan ; vague 5 : section 12.2), comme Unitree
// Explore : la vue du robot remplit la vue centrale (le G1 en 3D, la carte et la caméra de la tête en
// incrustation) avec deux joysticks posés dessus ; postures et gestes dans le ruban ; le panneau de droite
// montre l'état du robot, « Prendre la main », et la section de la commande choisie (postures, gestes,
// voix, lumière, danses, portique, volume). « Mes chorégraphies » : l'aperçu 3D et la ligne de temps dans
// la vue, le fichier, les réglages et l'élément choisi dans le panneau.
//
// Tout passe par le serveur de l'Atelier (/api/pilotage/*, /ws/pilotage), qui relaie vers le nœud
// pilotage (conteneur du Jetson, ou le PC en répétition). Les règles de sécurité sont dans le nœud ;
// l'écran les rend visibles : grisé sans la main, confirmations. L'ARRÊT est celui de la barre d'outils
// (et la touche Échap) : il arrête aussi le pilotage (POST /api/arret).

import { api } from '../api.js';
import { abonner } from '../direct.js';
import { preparerEcran, section } from '../coque/ecran.js';
import { ouvrirPanneau } from '../coque/panneau.js';
import * as F from '../formulaire.js';
import { afficherErreur } from '../messages.js';
import { Apercu3D } from '../pilotage/apercu3d.js';
import * as C from '../pilotage/choregraphie.js';
import { Joystick } from '../pilotage/joystick.js';
import { LigneTemps } from '../pilotage/ligne_temps.js';
import { Musique } from '../pilotage/musique.js';
import { VueRobot } from '../pilotage/vue_robot.js';

const PERIODE_ETAT_MS = 500;
const SECTIONS = ['commandes', 'postures', 'gestes', 'voix', 'led', 'portique', 'volume', 'danses', 'choregraphies'];
const ACTIVITES = {
  repos: 'au repos', marche: 'marche au joystick', posture: 'changement de posture', geste: 'geste',
  danse: 'danse du robot', choregraphie: 'chorégraphie', arret: 'ARRÊT',
};
// Noms des modes du robot (atelier.lieu.pilotage.NOMS_MODES, vague 5) : 501 et 801 = marche, 802 = course
export const MODES_FSM = {
  0: 'pas démarré', 1: 'amorti', 2: 'accroupi', 3: 'assis', 4: 'debout, verrouillé', 500: 'démarrage', 501: 'marche',
  702: 'se relève', 706: 'accroupi ↔ debout', 801: 'marche', 802: 'course',
};
const GESTES_PRINCIPAUX = [26, 25, 17, 20, 18, 19, 27];

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

function hexa(e) {
  const h = (v) => ('0' + Math.max(0, Math.min(255, v | 0)).toString(16)).slice(-2);
  return '#' + h(e.r) + h(e.g) + h(e.b);
}

function depuisHexa(texte) {
  const v = parseInt(String(texte).replace('#', ''), 16);
  return { r: (v >> 16) & 255, g: (v >> 8) & 255, b: v & 255 };
}

class EcranPilotage {
  constructor(racine, options) {
    const ecran = preparerEcran(racine, options);
    this.ecran = ecran;
    this.coque = ecran.coque;
    this.racine = ecran.vue;
    this.config = null;
    this.etat = null;
    this.joignable = null;
    this.ws = null;
    this.joystick = null;
    this.modifie = false;
    this.minuteurs = [];
    this.sectionCourante = null;
    this.musique = new Musique();
    this.d = null;                     // chorégraphie en cours d'édition
    this.idChoregraphie = null;
    this.protegee = false;
    this.lecture = null;               // aperçu en cours : {t0, origine}
    this.tApercu = 0;
    this.apercu = null;
    this.ligne = null;
    this.choix = null;
    this.pont = null;
    this.ferme = false;
    this.joysticksVisibles = this.coque.cases().joysticks !== false;
    this.racine.classList.add('chargement');
    this.construire();
    const demande = ecran.commande;
    const valeur = ecran.valeur;
    api.lire('/api/pilotage/config').then((c) => {
      if (this.ferme) return;
      this.config = c;
      this.vueRobot = new VueRobot(this.zoneVue, c, { disposition: 'centrale' });
      this.vueRobot.montrer(true);
      this.racine.classList.remove('chargement');
      this.monterJoysticks();
      this.ouvrirSection(SECTIONS.indexOf(demande) >= 0 ? demande : souvenirLocal('section', 'commandes'));
      if (demande && valeur !== undefined) this.commandeRuban(demande, valeur);
      else if (demande === 'main') this.basculerMain();
      this.majEntete();
    }).catch((e) => {
      this.racine.classList.remove('chargement');
      afficherErreur(e);
    });
    this.lireEtat();
    this.minuteurs.push(setInterval(() => this.lireEtat(), PERIODE_ETAT_MS));
    this.desabonner = abonner((d) => {
      this.pont = d && d.pont && !d.pont.perime ? d.pont : null;
    });
    // l'ARRÊT est celui de la coque (bouton ou Échap) : ici, on lâche seulement les manettes et l'aperçu. Un
    // pouce resté sur une manette ne relance rien : il faut la relâcher puis la reprendre.
    this._lacherTout = () => {
      if (this.joystick) this.joystick.toutLacher();
      this.arreterApercu();
      this.musique.arreter();
    };
    this._echap = (e) => {
      if (e.key === 'Escape') this._lacherTout();
    };
    document.addEventListener('keydown', this._echap);
    document.addEventListener('atelier-arret', this._lacherTout);
  }

  // ---------------------------------------------------------------- squelette de l'écran

  construire() {
    const r = this.racine;
    r.textContent = '';
    const p = F.el('div', 'pilotage pilotage-centrale');
    // vue du robot (G1 en 3D, carte, caméra), ou aperçu des chorégraphies
    this.zoneVue = F.el('div', 'zone-vue-robot');
    p.appendChild(this.zoneVue);
    this.zoneChoregraphie = F.el('div', 'zone-choregraphie');
    this.zoneChoregraphie.hidden = true;
    p.appendChild(this.zoneChoregraphie);
    // en surimpression : l'état en pilule, et les deux joysticks
    this.pilule = F.el('div', 'pilule-etat');
    this.pilule.setAttribute('data-role', 'pilule-etat');
    p.appendChild(this.pilule);
    this.zoneJoysticks = F.el('div', 'joysticks-vue');
    this.zoneJoysticks.setAttribute('data-role', 'joysticks');
    p.appendChild(this.zoneJoysticks);
    r.appendChild(p);
    // panneau : l'état du robot, puis la section choisie
    const pan = ouvrirPanneau(this.ecran.panneau, { titre: 'Piloter' });
    const z = pan.corps;
    z.classList.add('panneau-pilotage');
    const barre = F.el('div', 'pilotage-barre');
    barre.setAttribute('data-role', 'etat-robot');
    const ligne = F.el('div', 'pilotage-ligne');
    this.pastille = F.el('span', 'pastille-pilotage', 'Nœud pilotage : …');
    this.etatBatterie = F.el('span', 'etat-batterie', '');
    ligne.appendChild(this.pastille);
    ligne.appendChild(this.etatBatterie);
    barre.appendChild(ligne);
    this.etatMaitre = F.el('div', 'etat-maitre', '');
    barre.appendChild(this.etatMaitre);
    this.etatRobot = F.el('div', 'etat-robot', '');
    barre.appendChild(this.etatRobot);
    const actions = F.el('div', 'pilotage-actions');
    this.boutonDemarrer = F.bouton(actions, 'Démarrer le pilotage', () => this.demarrerNoeud(), 'bouton bouton-principal');
    this.boutonDemarrer.title = 'Lance le nœud pilotage sur ce PC (répétition sans robot)';
    this.boutonMain = F.bouton(actions, 'Prendre la main', () => this.basculerMain(), 'bouton bouton-principal');
    barre.appendChild(actions);
    this.message = F.el('p', 'pilotage-message', '');
    barre.appendChild(this.message);
    this.alerteMode = F.el('p', 'panneau-alerte alerte-mode', '');
    this.alerteMode.hidden = true;
    barre.appendChild(this.alerteMode);
    z.appendChild(barre);
    this.contenu = F.el('div', 'pilotage-contenu');
    z.appendChild(this.contenu);
  }

  monterJoysticks() {
    if (this.joystick || !this.config) return;
    this.joystick = new Joystick(this.zoneJoysticks, this.config.limites_marche, (m) => this.envoyerJoystick(m),
      { disposition: 'double' });
    this.zoneJoysticks.hidden = !this.joysticksVisibles;
    this.ouvrirWs();                 // la liaison est prête quand le doigt touche le manche
  }

  // ---------------------------------------------------------------- sections du panneau

  async ouvrirSection(id) {
    if (!this.config) return;
    if (SECTIONS.indexOf(id) < 0) id = 'commandes';
    if (this.modifie && this.sectionCourante === 'choregraphies' && id !== 'choregraphies') {
      const ok = await this.coque.confirmer('La chorégraphie a des modifications non enregistrées. Les abandonner ?',
        { titre: 'Modifications non enregistrées', ok: 'Abandonner', annuler: 'Rester', danger: true });
      if (!ok) return;
    }
    this.fermerChoregraphie();
    this.sectionCourante = id;
    memoriserLocal('section', id);
    this.contenu.textContent = '';
    this.contenu.dataset.section = id;
    this.majSection = null;
    const choregraphie = id === 'choregraphies';
    this.zoneVue.hidden = choregraphie;
    this.zoneChoregraphie.hidden = !choregraphie;
    this.zoneJoysticks.hidden = choregraphie || !this.joysticksVisibles;
    if (this.vueRobot) this.vueRobot.montrer(!choregraphie);
    if (id === 'danses') this.sectionDanses();
    else if (choregraphie) this.sectionChoregraphies();
    else if (id === 'voix') this.sectionVoix();
    else if (id === 'led') this.sectionLed();
    else if (id === 'volume') this.sectionVolume();
    else if (id === 'portique') this.sectionPortique();
    else if (id === 'gestes') this.sectionGestes(true);
    else if (id === 'postures') this.sectionPostures(true);
    else {
      this.sectionPostures(false);
      this.sectionGestes(false);
    }
    const nom = { commandes: null, postures: null, gestes: null }[id] === undefined ? id : null;
    this.coque.activer(nom);
    this.majEntete();
  }

  // Une commande du ruban : (nom, valeur) ; voir COMMANDES de js/coque/ruban.js
  commandeRuban(nom, valeur) {
    if (!this.config) return;
    if (nom === 'main') this.basculerMain();
    else if (nom === 'postures' && valeur !== undefined) this.commande('/api/pilotage/posture', { fsm: Number(valeur) });
    else if (nom === 'gestes' && valeur !== undefined) this.geste('bras', Number(valeur));
    else if (nom === 'joysticks') {
      this.joysticksVisibles = valeur !== false;
      this.zoneJoysticks.hidden = !this.joysticksVisibles || this.sectionCourante === 'choregraphies';
      if (!this.joysticksVisibles && this.joystick) this.joystick.toutLacher();
    } else if (SECTIONS.indexOf(nom) >= 0) this.ouvrirSection(nom);
  }

  fermerChoregraphie() {
    this.arreterApercu();
    if (this.apercu) {
      this.apercu.fermer();
      this.apercu = null;
    }
    if (this.ligne) {
      this.ligne.fermer();
      this.ligne = null;
    }
    this.zoneChoregraphie.textContent = '';
    this.modifie = false;
  }

  // ---------------------------------------------------------------- état du nœud

  lireEtat() {
    if (this.enLecture || this.ferme) return;
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
      if (!this.ferme) this.majEntete();
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
    const main = this.aLaMain();
    this.etatMaitre.textContent = e ? (main ? 'Vous avez la main' : 'Le guide a la main') : '';
    this.etatMaitre.className = 'etat-maitre ' + (main ? 'maitre-pilotage' : 'maitre-guide');
    const nomMode = e && e.fsm !== null && e.fsm !== undefined ? (MODES_FSM[e.fsm] || 'mode ' + e.fsm) : '?';
    this.etatRobot.textContent = e ? ('Mode ' + (e.fsm === null ? '?' : e.fsm) + ' (' + nomMode + ') · '
      + (ACTIVITES[e.activite] || e.activite)) : '';
    this.etatBatterie.textContent = e && e.batterie ? 'Batterie ' + e.batterie.pourcent + ' %' : '';
    this.etatBatterie.classList.toggle('batterie-faible', !!(e && e.batterie && e.batterie.pourcent < 20));
    const local = this.config && this.config.local;
    this.boutonDemarrer.hidden = !local || this.joignable === true;
    this.boutonMain.disabled = !e;
    this.boutonMain.textContent = main ? 'Rendre la main' : 'Prendre la main';
    this.boutonMain.className = 'bouton ' + (main ? '' : 'bouton-principal');
    this.coque.libelle('main', main ? 'Rendre la main' : 'Prendre la main');
    this.coque.coche('main', main);
    if (this.joignable === false) {
      this.message.textContent = this.detailInjoignable || '';
    } else if (e) {
      this.message.textContent = e.message + (e.dernier_refus && e.dernier_refus.message && e.dernier_refus.message !== e.message
        ? ' (Dernier refus du robot : ' + e.dernier_refus.message + ')' : '');
    }
    // vague 5 (section 12.6) : le pont dit quand le robot n'est pas en mode marche, et quoi faire
    const p = this.pont;
    this.alerteMode.hidden = !(p && p.etat === 'pas_en_marche');
    if (p && p.etat === 'pas_en_marche') this.alerteMode.textContent = p.message || 'Le robot n\'est pas en mode marche.';
    // pilule sur la vue : mode, activité, main
    this.pilule.textContent = e ? (nomMode + ' · ' + (main ? 'vous pilotez' : 'le guide a la main'))
      : (this.joignable === false ? 'Nœud pilotage injoignable' : '…');
    this.pilule.classList.toggle('pilule-main', main);
    this.contenu.classList.toggle('sans-main', !main);
    const raison = !e ? 'Le nœud pilotage ne répond pas' : (!main ? 'Prenez d\'abord la main' : null);
    this.coque.griser('postures', raison);
    this.coque.griser('gestes', raison);
    this.coque.griser('main', e ? null : 'Le nœud pilotage ne répond pas');
    if (this.joystick) this.joystick.activer(main && !(e && e.danse));
    if (this.vueRobot) this.vueRobot.majEtat(this.etat, this.joignable);
    if (this.majSection) this.majSection();
  }

  // ---------------------------------------------------------------- actions générales

  async demarrerNoeud() {
    this.boutonDemarrer.disabled = true;
    try {
      const r = await api.envoyer('/api/pilotage/demarrer', {});
      this.coque.message(r.detail, 'succes');
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
        this.coque.message(r.detail, 'succes');
      } else {
        try {
          const r = await api.envoyer('/api/pilotage/maitre', { maitre: 'pilotage' });
          this.coque.message(r.detail, 'succes');
        } catch (e) {
          if (e.statut === 409 && /mission/.test(e.message) && await this.coque.confirmer(e.message
            + '\n\nArrêter le guide et prendre la main ?', { titre: 'Le guide est en route', ok: 'Prendre la main',
            annuler: 'Laisser le guide', danger: true })) {
            const r = await api.envoyer('/api/pilotage/maitre', { maitre: 'pilotage', forcer: true });
            this.coque.message(r.detail, 'avertissement');
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
      const ok = await this.coque.confirmer(r.corps.detail + '\n\nLe robot est-il bien tenu au portique ?',
        { titre: 'Robot au portique ?', ok: 'Oui, il est tenu', annuler: 'Non', danger: true });
      if (ok) {
        r = await this.poster(chemin, Object.assign({}, corps, { jeton: r.corps.jeton }));
      } else {
        this.lireEtat();
        return null;
      }
    }
    this.lireEtat();
    if (r.statut >= 200 && r.statut < 300) {
      if (!options.silence) this.coque.message(r.corps.detail || 'Fait.', 'succes');
      return r.corps;
    }
    this.coque.message(r.corps.detail || ('Erreur ' + r.statut), r.statut === 428 ? 'avertissement' : 'erreur', r.corps.erreurs);
    return null;
  }

  // ---------------------------------------------------------------- postures, gestes, voix, lumière

  sectionPostures(seule) {
    const c = this.config;
    const s = section(this.contenu, 'Postures', 'postures');
    s.classList.add('pilotage-postures');
    const normales = F.el('div', 'boutons-postures');
    c.postures.filter((p) => !p.confirmation).forEach((p) => {
      const b = F.bouton(normales, p.nom.replace(/ \(.*\)$/, ''), () => this.commande('/api/pilotage/posture', { fsm: p.fsm }),
        'bouton bouton-grand mouvement');
      b.dataset.fsm = String(p.fsm);
      b.title = p.nom;
    });
    s.appendChild(normales);
    if (seule) this.sectionPortique(s);
    this.majSection = () => this.majMouvements();
    this.majMouvements();
  }

  sectionPortique(dans) {
    const c = this.config;
    const s = dans || section(this.contenu, 'Au portique', 'portique');
    const portique = F.el('div', 'zone-portique');
    portique.appendChild(F.el('p', 'panneau-alerte', 'Au portique seulement : le robot s\'affaisse s\'il n\'est pas tenu.'));
    this.casePortique = F.caseACocher(portique, 'Le robot est tenu au portique', false, () => {});
    const boutonsPortique = F.el('div', 'boutons-postures');
    c.postures.filter((p) => p.confirmation === 'portique').forEach((p) => {
      const b = F.bouton(boutonsPortique, p.nom.replace(/ \(.*\)$/, ''), () => this.commande('/api/pilotage/posture',
        { fsm: p.fsm, portique: this.casePortique.checked }), 'bouton bouton-danger mouvement');
      b.dataset.fsm = String(p.fsm);
      b.title = p.nom;
    });
    portique.appendChild(boutonsPortique);
    s.appendChild(portique);
    if (!dans) {
      this.majSection = () => this.majMouvements();
      this.majMouvements();
    }
  }

  sectionGestes(tous) {
    const c = this.config;
    const s = section(this.contenu, 'Gestes', 'gestes');
    s.classList.add('pilotage-gestes');
    const boutonsGestes = F.el('div', 'boutons-gestes');
    const liste = tous ? c.gestes.filter((g) => g.id !== 99)
      : GESTES_PRINCIPAUX.map((id) => c.gestes.find((g) => g.id === id)).filter((g) => g);
    liste.forEach((g) => {
      const b = F.bouton(boutonsGestes, g.nom, () => this.geste('bras', g.id), 'bouton mouvement');
      b.dataset.geste = String(g.id);
    });
    s.appendChild(boutonsGestes);
    const relacher = F.bouton(s, 'Relâcher les bras', () => this.geste('bras', 99), 'bouton');
    relacher.dataset.geste = '99';
    if (tous) {
      const taches = F.el('div', 'boutons-gestes');
      taches.appendChild(F.el('span', 'champ-libelle', 'En marchant :'));
      c.taches.filter((t) => t.id === 0 || t.id === 2).forEach((t) => {
        F.bouton(taches, t.nom, () => this.geste('tache', t.id), 'bouton mouvement');
      });
      s.appendChild(taches);
    } else {
      F.bouton(s, 'Tous les gestes', () => this.ouvrirSection('gestes'), 'bouton-lien');
    }
    this.majSection = () => this.majMouvements();
    this.majMouvements();
  }

  majMouvements() {
    const sans = !this.aLaMain();
    this.contenu.querySelectorAll('.mouvement').forEach((b) => { b.disabled = sans; });
  }

  sectionVoix() {
    const s = section(this.contenu, 'Voix', 'voix');
    s.classList.add('pilotage-voix');
    let texte = 'Bonjour, je suis le robot d\'accueil.';
    const champ = F.champTexte(s, 'Phrase', texte, (v) => { texte = v; }, { lignes: 2 });
    champ.addEventListener('input', () => { texte = champ.value; });
    F.bouton(s, 'Dire', () => this.commande('/api/pilotage/voix', { texte }), 'bouton bouton-principal');
    F.paragraphe(s, 'La voix de l\'équipe (personnalités) parle par un autre chemin.', 'panneau-note');
  }

  sectionVolume() {
    const s = section(this.contenu, 'Volume', 'volume');
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
    s.appendChild(ligneVolume);
    F.bouton(s, 'Appliquer le volume', () => this.commande('/api/pilotage/volume', { volume }), 'bouton bouton-principal');
  }

  sectionLed() {
    const s = section(this.contenu, 'Lumière', 'led');
    const ligneLed = F.el('div', 'champ');
    ligneLed.appendChild(F.el('span', 'champ-libelle', 'Couleur'));
    const couleur = F.el('input');
    couleur.type = 'color';
    couleur.value = '#ff0080';
    ligneLed.appendChild(couleur);
    s.appendChild(ligneLed);
    const boutonsLed = F.el('div', 'formulaire-ligne');
    F.bouton(boutonsLed, 'Allumer', () => this.commande('/api/pilotage/led', depuisHexa(couleur.value)), 'bouton bouton-principal');
    F.bouton(boutonsLed, 'Éteindre', () => this.commande('/api/pilotage/led', { r: 0, g: 0, b: 0 }), 'bouton');
    s.appendChild(boutonsLed);
  }

  // Geste (arm 7106) ou tâche (sport 7106) ; la Vue du robot en montre un aperçu approché
  async geste(genre, id) {
    const r = genre === 'tache' ? await this.commande('/api/pilotage/tache', { tache: id })
      : await this.commande('/api/pilotage/geste', { action: id });
    if (r && this.vueRobot) this.vueRobot.gesteDemande(genre, id);
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
        if (this.joystick) this.joystick.lecture.textContent = m.detail;
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
    const s = section(this.contenu, 'Danses du robot', 'danses');
    s.classList.add('pilotage-danses');
    s.appendChild(F.el('p', 'panneau-alerte', 'Les danses font bouger les pieds : dégagez 2 à 3 m autour du robot, '
      + 'télécommande en main (rien d\'autre n\'arrête une danse).'));
    const ligne = F.el('div', 'formulaire-ligne');
    F.bouton(ligne, 'Lire la liste du robot', () => this.lireDanses(true), 'bouton bouton-principal');
    s.appendChild(ligne);
    this.caseZone = F.caseACocher(s, 'Zone libre de 2 à 3 m, télécommande en main', false, () => this.majSection());
    this.progresDanse = F.el('div', 'progres-danse');
    this.progresDanse.hidden = true;
    s.appendChild(this.progresDanse);
    this.tableDanses = F.el('table', 'tableau tableau-danses');
    s.appendChild(this.tableDanses);
    F.paragraphe(s, '401, 402 et 403 sont interdites (le robot peut se coucher par terre). Une danse jamais essayée : '
      + 'au portique d\'abord.', 'panneau-note');
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
      if (robot) this.coque.message(r.detail, 'succes');
    } catch (e) {
      if (robot) afficherErreur(e);
      else this.remplirDanses();
    }
  }

  remplirDanses() {
    const t = this.tableDanses;
    if (!t) return;
    t.textContent = '';
    if (!this.danses) {
      const l = t.insertRow();
      l.insertCell().textContent = 'Liste pas encore lue : « Lire la liste du robot ».';
      return;
    }
    const entete = t.createTHead().insertRow();
    ['N°', 'Nom', 'Durée', ''].forEach((x) => {
      const c = document.createElement('th');
      c.textContent = x;
      entete.appendChild(c);
    });
    const corps = t.createTBody();
    this.danses.forEach((d) => {
      const l = corps.insertRow();
      l.className = d.interdite ? 'danse-interdite' : (d.essayee ? 'danse-essayee' : 'danse-inconnue');
      l.dataset.danse = String(d.id);
      l.title = d.remarque || '';
      l.insertCell().textContent = String(d.id);
      l.insertCell().textContent = d.nom || '—';
      l.insertCell().textContent = d.duree_s ? d.duree_s.toFixed(0) + ' s' : '?';
      const c = l.insertCell();
      if (d.interdite) {
        c.appendChild(F.el('span', 'etiquette-interdite', 'Interdite'));
      } else {
        const b = F.bouton(c, 'Jouer', () => this.jouerDanse(d), 'bouton bouton-petit jouer-danse');
        b.dataset.interdite = '0';
      }
    });
    if (this.majSection) this.majSection();
  }

  async jouerDanse(d) {
    if (!this.caseZone.checked) return;
    const ok = await this.coque.confirmer('Danse ' + d.id + ' (' + (d.nom || 'sans nom') + ', ' + (d.duree_s || '?') + ' s).\n\n'
      + this.config.confirmations.zone_libre, { titre: 'Jouer une danse', ok: 'Jouer', annuler: 'Annuler', danger: true });
    if (!ok) return;
    await this.commande('/api/pilotage/danse', { id: d.id, zone_libre: true });
  }

  // ---------------------------------------------------------------- Mes chorégraphies

  sectionChoregraphies() {
    // la vue : aperçu 3D, lecture et ligne de temps
    const vue = this.zoneChoregraphie;
    vue.textContent = '';
    const cadre = F.el('div', 'pilotage-choregraphies');
    const centre = F.el('div', 'choregraphie-apercu');
    this.vue = F.el('div', 'apercu-3d');
    centre.appendChild(this.vue);
    const transport = F.el('div', 'transport');
    this.boutonApercu = F.bouton(transport, '▶ Aperçu', () => this.basculerApercu(), 'bouton bouton-principal');
    this.boutonApercu.dataset.role = 'apercu';
    F.bouton(transport, '⏮', () => { this.arreterApercu(); this.placer(0); }, 'bouton').title = 'Revenir au début';
    this.affichageTemps = F.el('span', 'temps-apercu', '0,0 s');
    transport.appendChild(this.affichageTemps);
    this.caseSon = F.caseACocher(transport, 'Son', souvenirLocal('son', '1') === '1', (v) => memoriserLocal('son', v ? '1' : '0'));
    centre.appendChild(transport);
    cadre.appendChild(centre);
    const bas = F.el('div', 'choregraphie-ligne');
    const ajouts = F.el('div', 'formulaire-ligne');
    ajouts.appendChild(F.el('span', 'champ-libelle', 'Ajouter ici :'));
    F.bouton(ajouts, 'Pose des bras', () => this.ajouter('bras'), 'bouton bouton-petit');
    F.bouton(ajouts, 'Pas', () => this.ajouter('pas'), 'bouton bouton-petit');
    F.bouton(ajouts, 'LED', () => this.ajouter('led'), 'bouton bouton-petit');
    F.bouton(ajouts, 'Parole', () => this.ajouter('paroles'), 'bouton bouton-petit');
    F.caseACocher(ajouts, 'Aimant au battement', true, (v) => { if (this.ligne) this.ligne.aimant = v; });
    bas.appendChild(ajouts);
    const zoneLigne = F.el('div', 'zone-ligne-temps');
    bas.appendChild(zoneLigne);
    cadre.appendChild(bas);
    vue.appendChild(cadre);
    // le panneau : fichier, réglages, élément choisi, jouer sur le robot
    const s = section(this.contenu, 'Mes chorégraphies', 'choregraphies');
    s.classList.add('choregraphie-fichier');
    this.listeChoregraphies = F.el('select', 'liste-choregraphies');
    this.listeChoregraphies.setAttribute('aria-label', 'Chorégraphie');
    this.listeChoregraphies.addEventListener('change', () => this.chargerChoregraphie(this.listeChoregraphies.value));
    s.appendChild(this.listeChoregraphies);
    const boutons = F.el('div', 'formulaire-ligne');
    F.bouton(boutons, 'Nouvelle', () => this.nouvelleChoregraphie(), 'bouton bouton-petit');
    this.boutonEnregistrer = F.bouton(boutons, 'Enregistrer', () => this.enregistrer(false), 'bouton bouton-petit bouton-principal');
    F.bouton(boutons, 'Enregistrer sous', () => this.enregistrer(true), 'bouton bouton-petit');
    this.boutonSupprimer = F.bouton(boutons, 'Supprimer', () => this.supprimer(), 'bouton bouton-petit bouton-danger');
    s.appendChild(boutons);
    this.resume = F.el('div', 'choregraphie-resume');
    s.appendChild(this.resume);
    this.erreurs = F.el('ul', 'choregraphie-erreurs');
    s.appendChild(this.erreurs);
    const jouer = section(this.contenu, 'Jouer sur le robot', 'jouer');
    jouer.classList.add('jouer-robot');
    this.caseZoneChoregraphie = F.caseACocher(jouer, 'Zone libre autour du robot, télécommande en main', false, () => this.majSection());
    this.vitesseLecture = parseFloat(souvenirLocal('vitesse', '1')) || 1;
    F.listeDeroulante(jouer, 'Vitesse', String(this.vitesseLecture),
      [{ id: '1', texte: 'normale' }, { id: '0.75', texte: '3/4' }, { id: '0.5', texte: '1/2 (premiers essais)' }, { id: '0.25', texte: '1/4' }],
      (v) => { this.vitesseLecture = parseFloat(v); memoriserLocal('vitesse', v); });
    this.boutonJouer = F.bouton(jouer, 'Jouer sur le robot', () => this.jouerSurLeRobot(), 'bouton bouton-principal mouvement');
    this.progresChoregraphie = F.el('p', 'panneau-note progres-choregraphie', '');
    jouer.appendChild(this.progresChoregraphie);
    this.panneauChoix = section(this.contenu, null, 'element');
    this.panneauChoix.classList.add('choregraphie-element');
    const reglages = F.el('details', 'bloc-avance choregraphie-reglages-bloc');
    reglages.appendChild(F.el('summary', '', 'Réglages de la chorégraphie'));
    this.reglages = F.el('div', 'formulaire choregraphie-reglages');
    reglages.appendChild(this.reglages);
    this.contenu.appendChild(reglages);
    F.paragraphe(this.contenu, 'Importer les bras d\'une vidéo de danse : g1-pilotage importer-video DANSE.mp4 --id ma_danse, '
      + 'puis rouvrez cette section.', 'panneau-note');
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
      if (!this.listeChoregraphies) return;
      this.listeChoregraphies.textContent = '';
      r.choregraphies.forEach((c) => {
        const o = F.el('option', '', c.nom + (c.erreurs && c.erreurs.length ? ' (à corriger)' : '') + (c.protegee ? ' — exemple' : ''));
        o.value = c.id;
        this.listeChoregraphies.appendChild(o);
      });
      const ids = r.choregraphies.map((c) => c.id);
      const id = ids.indexOf(choisir) >= 0 ? choisir : (ids[0] || null);
      if (id) {
        this.listeChoregraphies.value = id;
        await this.chargerChoregraphie(id, true);
      } else {
        this.nouvelleChoregraphie();
      }
    } catch (e) {
      afficherErreur(e);
    }
  }

  async chargerChoregraphie(id, sansDemander) {
    if (this.modifie && !sansDemander) {
      const ok = await this.coque.confirmer('La chorégraphie a des modifications non enregistrées. Les abandonner ?',
        { titre: 'Modifications non enregistrées', ok: 'Abandonner', annuler: 'Rester', danger: true });
      if (!ok) {
        this.listeChoregraphies.value = this.idChoregraphie || '';
        return;
      }
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

  async nouvelleChoregraphie() {
    const id = await this.coque.saisir('Nom de la nouvelle chorégraphie (lettres minuscules sans accent, chiffres, _ ou -) :',
      { titre: 'Nouvelle chorégraphie', valeur: 'ma_choregraphie', ok: 'Créer' });
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
      id = await this.coque.saisir('Enregistrer sous le nom :', { titre: 'Enregistrer sous', valeur: this.protegee ? id + '_copie' : id,
        ok: 'Enregistrer' });
      if (!id) return;
    }
    try {
      const r = await api.ecrire('/api/pilotage/choregraphies/' + encodeURIComponent(id), { choregraphie: Object.assign({}, this.d, { id }) });
      this.d = r.choregraphie;
      this.idChoregraphie = id;
      this.protegee = false;
      this.modifie = false;
      this.coque.message('Chorégraphie « ' + id + ' » enregistrée.', 'succes');
      await this.listerChoregraphies(id);
    } catch (e) {
      afficherErreur(e);
    }
  }

  async supprimer() {
    if (!this.idChoregraphie || this.protegee) return;
    const ok = await this.coque.confirmer('Supprimer la chorégraphie « ' + this.idChoregraphie + ' » ?',
      { titre: 'Supprimer', ok: 'Supprimer', annuler: 'Garder', danger: true });
    if (!ok) return;
    let r;
    try {
      r = await fetch('/api/pilotage/choregraphies/' + encodeURIComponent(this.idChoregraphie), { method: 'DELETE' });
    } catch (e) {
      this.coque.message('Le serveur de l\'Atelier ne répond pas.', 'erreur');
      return;
    }
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      this.coque.message(d.detail || ('Erreur ' + r.status), 'erreur');
      return;
    }
    this.modifie = false;
    this.coque.message('Chorégraphie supprimée.', 'succes');
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
    if (!this.erreurs) return;
    this.erreursActuelles = erreurs || [];
    this.erreurs.textContent = '';
    if (this.erreursActuelles.length) {
      this.erreurs.appendChild(F.el('li', 'rapport-titre-erreur', 'À corriger avant de jouer :'));
      this.erreursActuelles.forEach((m) => this.erreurs.appendChild(F.el('li', '', m)));
    } else {
      this.erreurs.appendChild(F.el('li', 'rapport-ok', 'Chorégraphie sûre : dans les limites des bras et des pas.'));
    }
    this.resume.textContent = '';
    if (this.d) {
      const r = resume || {};
      const v = r.vitesse_bras_max === null || r.vitesse_bras_max === undefined ? C.vitesseMax(this.d) : r.vitesse_bras_max;
      const dep = r.deplacement_m === null || r.deplacement_m === undefined ? C.deplacement(this.d).distance : r.deplacement_m;
      F.valeur(this.resume, 'Durée', this.d.duree_s + ' s');
      F.valeur(this.resume, 'Bras', 'au plus ' + v.toFixed(2) + ' rad/s (limite ' + this.config.vitesse_bras_max + ')');
      F.valeur(this.resume, 'Déplacement', 'au plus ' + dep.toFixed(2) + ' m (limite ' + this.config.deplacement_max_m + ' m)');
    }
    if (this.majSection) this.majSection();
  }

  rafraichir() {
    if (!this.boutonSupprimer) return;
    this.boutonSupprimer.disabled = this.protegee;
    this.boutonEnregistrer.title = this.protegee ? 'L\'exemple est en lecture seule : il sera enregistré sous un autre nom' : '';
    this.remplirReglages();
    if (this.ligne) this.ligne.definir(this.d);
    this.panneauElement();
  }

  remplirReglages() {
    const r = this.reglages;
    r.textContent = '';
    if (!this.d) return;
    const d = this.d;
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
      if (piste === 'pas') e = { t, vx: 0, vy: 0.2, wz: 0, duree_s: 1.0 };
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
    p.textContent = '';
    const d = this.d;
    const choix = this.choix;
    if (!d || !choix || choix.index === null || choix.index === undefined) {
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
      F.listeDeroulante(p, 'Voix', e.voix || 'equipe', [{ id: 'equipe', texte: 'la voix de l\'équipe' }, { id: 'unitree', texte: 'la synthèse du robot' }],
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
      this.coque.message('Enregistrez d\'abord la chorégraphie : le robot joue le fichier enregistré.', 'avertissement');
      return;
    }
    const vitesse = this.vitesseLecture || 1;
    const ok = await this.coque.confirmer('Jouer « ' + this.d.nom + ' » sur le robot (' + (this.d.duree_s / vitesse).toFixed(0) + ' s'
      + (vitesse < 1 ? ', vitesse ' + vitesse : '') + ', zone libre de ' + this.d.zone_libre_m + ' m).\n\n'
      + this.config.confirmations.zone_libre, { titre: 'Jouer sur le robot', ok: 'Jouer', annuler: 'Annuler', danger: true });
    if (!ok) return;
    const r = await this.commande('/api/pilotage/choregraphies/' + encodeURIComponent(this.idChoregraphie) + '/jouer',
      { zone_libre: true, vitesse });
    if (r && r.debut_mur) {
      // aperçu et musique calés sur le départ annoncé par le nœud
      this.demarrerApercu(0, Math.max(0, r.debut_mur - Date.now() / 1000), vitesse);
      (r.avertissements || []).forEach((a) => this.coque.message(a, 'avertissement'));
    }
  }

  fermer() {
    this.ferme = true;
    this.minuteurs.forEach((m) => clearInterval(m));
    clearTimeout(this.minuteurVerif);
    document.removeEventListener('keydown', this._echap);
    document.removeEventListener('atelier-arret', this._lacherTout);
    if (this.desabonner) this.desabonner();
    this.fermerChoregraphie();
    if (this.joystick) {
      this.joystick.fermer();
      this.joystick = null;
    }
    this.fermerWs();
    this.musique.arreter();
    if (this.vueRobot) this.vueRobot.fermer();
  }
}

export function ouvrir(racine, options) {
  const ecran = new EcranPilotage(racine, options);
  window.ecranPilotage = ecran;
  return {
    modifie: () => ecran.modifie,
    commande: (nom, valeur) => ecran.commandeRuban(nom, valeur),
    fermer: () => {
      ecran.fermer();
      if (window.ecranPilotage === ecran) window.ecranPilotage = null;
    },
  };
}
