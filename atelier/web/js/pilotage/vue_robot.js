// Vue du robot de l'onglet Pilotage (section 11.13 du plan), sous « Commandes » et « Danses du
// robot » : ce que fait le robot, sans rien commander (la vue n'envoie aucun ordre ; ARRÊT et la
// touche Échap restent ceux de l'onglet).
//   - Carte : le lieu de la simulation, de la répétition ou du robot, la position et le cap du
//     robot et les passants, en direct (WebSocket /ws/etat, comme l'onglet Simulation).
//   - Le G1 en 3D (apercu3d.js, maillages de l'URDF) : posture d'après le mode FSM, marche qui suit
//     la consigne du joystick, gestes et danse du robot en APERÇU APPROCHÉ (poses_vue.js : le vrai
//     geste est dans le robot), chorégraphie en cours avec ses vraies poses (choregraphie.js).
//   - Caméra de la tête (GET /api/pilotage/camera : JPEG du service videohub, relayé par le nœud et
//     l'Atelier) ; une image toutes les 0,35 s au plus, seulement quand la vue est visible et la
//     caméra allumée. En répétition, une image de remplacement ; « Voir » montre l'image de test du
//     faux G1.

import { api } from '../api.js';
import { contexte, memoriser, souvenir } from '../contexte.js';
import { abonner } from '../direct.js';
import * as F from '../formulaire.js';
import { nb } from '../geometrie.js';
import { creerPlan, iconeOrientee, ll } from '../plan.js';
import { Apercu3D } from './apercu3d.js';
import * as C from './choregraphie.js';
import * as P from './poses_vue.js';

const L = window.L;
const IMAGE_MIN_MS = 33;                // animation : 30 images par seconde au plus
const ZOOM_SUIVI = 4.6;                 // 2^4,6 ≈ 24 pixels par mètre
const PERIODE_CAMERA_MS = 350;          // contrat : CAMERA_PERIODE_PAGE_S
const IMAGE_FIGEE_S = 2.0;
const TAU_S = 0.12;                     // lissage des poses affichées
const TAU_POSTURE_S = 0.5;              // ... pendant un changement de posture (3 s)
const NOTES = {
  posture: 'Aperçu approché de la posture.',
  marche: 'Aperçu approché de la marche ; la carte montre où va le robot.',
  geste: 'Aperçu approché : le vrai geste est dans le robot.',
  danse: 'Aperçu approché : la vraie danse est dans le robot.',
  choregraphie: 'Poses exactes de la chorégraphie (bras et pas).',
};
const TEXTES_CAMERA = {
  robot: 'Caméra coupée. « Voir » l\'allume (quelques images par seconde, par le Wi-Fi).',
  repetition: 'Pas de caméra en répétition : le faux G1 n\'en a pas. « Voir » montre son image de test '
    + '(la chaîne de la vidéo est essayée de bout en bout).',
  simu: 'Pas de caméra en simulation.',
  aucun: 'Ni robot ni répétition en cours : pas de caméra.',
};

function attendre(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function souvenirVue(cle, defaut) {
  const v = souvenir('pilotage.vue.' + cle);
  return v === null ? defaut : v;
}

export class VueRobot {
  // element : le conteneur ; config : GET /api/pilotage/config (noms des gestes, limites de marche) ;
  // options : {disposition: 'centrale'} (vague 5 : la vue centrale de Piloter, le G1 en grand, la carte et
  // la caméra en incrustation), sinon les trois panneaux côte à côte d'avant
  constructor(element, config, options) {
    this.element = element;
    this.config = config || {};
    this.centrale = !!(options && options.disposition === 'centrale');
    this.visible = false;
    this.ferme = false;
    this.replie = souvenirVue('repliee', '0') === '1';
    this.etat = null;
    this.joignable = null;
    this.recu = 0;
    this.direct = null;
    this.qAffiche = P.poseDeRepos();
    this.limites = {};
    this.posture = 'debout';
    this.tPosture = -1e9;
    this.geste = null;             // {source, genre, id, nom, t0, depart, numero}
    this.danse = null;
    this.chor = null;
    this.choregraphies = {};       // id → contenu (pour les vraies poses)
    this.phase = 0;
    this.suivre = true;
    this.cameraActive = false;
    this.jetonCamera = 0;
    this.urlImage = null;
    this.modeVu = undefined;
    this.numeroVu = null;
    this.textes = {};
    this.construire();
    this.desabonner = abonner((d) => this.recevoirDirect(d));
    this.apercu.charger().then(() => {
      this.limites = P.limitesDuModele(this.apercu.modele);
      this.pret = true;
    }).catch(() => {
      this.pret = true;
    });
    this.tPrecedent = performance.now();
    const boucle = (t) => {
      if (this.ferme) return;
      if (this.visible && !document.hidden && t - this.tPrecedent >= IMAGE_MIN_MS) this.animer(t);
      requestAnimationFrame(boucle);
    };
    requestAnimationFrame(boucle);
    window.vueRobot = this;
  }

  // ---------------------------------------------------------------- page

  construire() {
    if (this.centrale) {
      this.construireCentrale();
      return;
    }
    const s = F.el('section', 'carte-section vue-robot');
    const entete = F.el('div', 'vue-robot-entete');
    entete.appendChild(F.el('h3', 'panneau-titre', 'Vue du robot'));
    entete.appendChild(F.el('span', 'vue-robot-aide', 'Elle montre le robot et ne commande rien.'));
    this.boutonReplier = F.bouton(entete, '', () => this.replier(!this.replie), 'bouton vue-robot-replier');
    s.appendChild(entete);
    this.corps = F.el('div', 'vue-robot-corps');
    // carte
    const carte = F.el('div', 'vue-robot-panneau vue-robot-carte');
    const titreCarte = F.el('div', 'vue-robot-titre');
    titreCarte.appendChild(F.el('strong', '', 'Carte'));
    this.etatCarte = F.el('span', 'vue-robot-etat', '');
    titreCarte.appendChild(this.etatCarte);
    carte.appendChild(titreCarte);
    this.zonePlan = F.el('div', 'vue-robot-plan');
    carte.appendChild(this.zonePlan);
    this.boutonSuivre = F.bouton(carte, 'Suivre le robot', () => this.suivreRobot(), 'bouton vue-robot-suivre');
    this.boutonSuivre.hidden = true;
    this.corps.appendChild(carte);
    // 3D
    const trois = F.el('div', 'vue-robot-panneau vue-robot-3d');
    const titre3d = F.el('div', 'vue-robot-titre');
    titre3d.appendChild(F.el('strong', '', 'Le robot en 3D'));
    trois.appendChild(titre3d);
    this.zone3d = F.el('div', 'vue-robot-apercu');
    trois.appendChild(this.zone3d);
    const legende = F.el('div', 'vue-robot-legende');
    this.lignePosture = F.el('div', 'vue-robot-posture', '');
    this.ligneActivite = F.el('div', 'vue-robot-activite', '');
    this.progres = F.el('div', 'vue-robot-progres');
    this.progres.hidden = true;
    this.ligneNote = F.el('div', 'vue-robot-approche', '');
    [this.lignePosture, this.ligneActivite, this.progres, this.ligneNote].forEach((e) => legende.appendChild(e));
    trois.appendChild(legende);
    this.corps.appendChild(trois);
    // caméra
    const camera = F.el('div', 'vue-robot-panneau vue-robot-camera');
    const titreCamera = F.el('div', 'vue-robot-titre');
    titreCamera.appendChild(F.el('strong', '', 'Caméra de la tête'));
    this.boutonCamera = F.bouton(titreCamera, 'Voir', () => this.basculerCamera(), 'bouton vue-robot-voir');
    camera.appendChild(titreCamera);
    const cadre = F.el('div', 'vue-robot-image');
    this.image = F.el('img');
    this.image.alt = 'Image de la caméra de la tête du robot';
    this.image.hidden = true;
    this.remplacement = F.el('p', 'vue-robot-remplacement', '');
    cadre.appendChild(this.image);
    cadre.appendChild(this.remplacement);
    camera.appendChild(cadre);
    this.etatCamera = F.el('div', 'vue-robot-etat-camera', '');
    camera.appendChild(this.etatCamera);
    this.corps.appendChild(camera);
    s.appendChild(this.corps);
    this.element.appendChild(s);
    this.section = s;
    this.plan = creerPlan(this.zonePlan);
    this.calque = L.layerGroup().addTo(this.plan.carte);
    this.marqueurRobot = null;
    this.pietons = new Map();
    this.plan.carte.on('dragstart', () => {
      this.suivre = false;
      this.boutonSuivre.hidden = false;
    });
    this.apercu = new Apercu3D(this.zone3d, { nomGlobal: 'vueRobot3d', camera: [2.0, 1.1, 1.25], cible: [0, 0, 0.7] });
    this.majRepli();
  }

  // Vague 5 : le G1 en grand dans la vue centrale, la carte en haut à gauche, la caméra en haut à droite
  construireCentrale() {
    this.replie = false;
    const s = F.el('div', 'vue-robot vue-robot-centrale');
    const trois = F.el('div', 'vue-robot-panneau vue-robot-3d');
    this.zone3d = F.el('div', 'vue-robot-apercu');
    trois.appendChild(this.zone3d);
    const legende = F.el('div', 'vue-robot-legende');
    this.lignePosture = F.el('div', 'vue-robot-posture', '');
    this.ligneActivite = F.el('div', 'vue-robot-activite', '');
    this.progres = F.el('div', 'vue-robot-progres');
    this.progres.hidden = true;
    this.ligneNote = F.el('div', 'vue-robot-approche', '');
    [this.lignePosture, this.ligneActivite, this.progres, this.ligneNote].forEach((e) => legende.appendChild(e));
    trois.appendChild(legende);
    s.appendChild(trois);
    // carte, en incrustation
    const carte = F.el('div', 'vue-robot-panneau vue-robot-carte vue-robot-incrustation');
    const titreCarte = F.el('div', 'vue-robot-titre');
    titreCarte.appendChild(F.el('strong', '', 'Carte'));
    this.etatCarte = F.el('span', 'vue-robot-etat', '');
    titreCarte.appendChild(this.etatCarte);
    carte.appendChild(titreCarte);
    this.zonePlan = F.el('div', 'vue-robot-plan');
    carte.appendChild(this.zonePlan);
    this.boutonSuivre = F.bouton(carte, 'Suivre', () => this.suivreRobot(), 'bouton bouton-petit vue-robot-suivre');
    this.boutonSuivre.hidden = true;
    s.appendChild(carte);
    // caméra de la tête, en incrustation
    const camera = F.el('div', 'vue-robot-panneau vue-robot-camera vue-robot-incrustation');
    const titreCamera = F.el('div', 'vue-robot-titre');
    titreCamera.appendChild(F.el('strong', '', 'Caméra de la tête'));
    this.boutonCamera = F.bouton(titreCamera, 'Voir', () => this.basculerCamera(), 'bouton bouton-petit vue-robot-voir');
    camera.appendChild(titreCamera);
    const cadre = F.el('div', 'vue-robot-image');
    this.image = F.el('img');
    this.image.alt = 'Image de la caméra de la tête du robot';
    this.image.hidden = true;
    this.remplacement = F.el('p', 'vue-robot-remplacement', '');
    cadre.appendChild(this.image);
    cadre.appendChild(this.remplacement);
    camera.appendChild(cadre);
    this.etatCamera = F.el('div', 'vue-robot-etat-camera', '');
    camera.appendChild(this.etatCamera);
    s.appendChild(camera);
    this.corps = s;
    this.section = s;
    this.boutonReplier = F.el('button');      // pas de repli dans la vue centrale
    this.element.appendChild(s);
    this.plan = creerPlan(this.zonePlan);
    this.calque = L.layerGroup().addTo(this.plan.carte);
    this.marqueurRobot = null;
    this.pietons = new Map();
    this.plan.carte.on('dragstart', () => {
      this.suivre = false;
      this.boutonSuivre.hidden = false;
    });
    this.apercu = new Apercu3D(this.zone3d, { nomGlobal: 'vueRobot3d', camera: [2.4, 1.3, 1.35], cible: [0, 0, 0.75] });
  }

  montrer(oui) {
    this.element.hidden = !oui;
    this.visible = !!oui && !this.replie;
    if (this.visible) {
      this.plan.carte.invalidateSize();
      this.apercu.redimensionner();
      this.majCamera();
    }
  }

  replier(oui) {
    this.replie = oui;
    memoriser('pilotage.vue.repliee', oui ? '1' : '0');
    this.majRepli();
    this.montrer(!this.element.hidden);
  }

  majRepli() {
    if (this.centrale) return;
    this.corps.hidden = this.replie;
    this.boutonReplier.textContent = this.replie ? 'Montrer la vue' : 'Masquer la vue';
    this.section.classList.toggle('repliee', this.replie);
  }

  fermer() {
    this.ferme = true;
    this.jetonCamera += 1;
    if (this.desabonner) this.desabonner();
    this.apercu.fermer();
    this.plan.detruire();
    if (this.urlImage) URL.revokeObjectURL(this.urlImage);
    if (window.vueRobot === this) window.vueRobot = null;
  }

  // ---------------------------------------------------------------- carte (WebSocket /ws/etat)

  lieuSuivi(d) {
    const sim = d && d.simulation;
    if (sim && sim.en_cours) return { lieu: sim.lieu, etage: sim.etage, enCours: true };
    return { lieu: contexte.lieu, etage: contexte.etage, enCours: false };
  }

  async chargerFond(lieu, etage) {
    this.fond = lieu + '/' + etage;
    this.plan.cadre_initial = false;
    if (!lieu || !etage) return;
    try {
      await this.plan.afficherFond(lieu, etage);
      if (this.suivre && this.marqueurRobot) {     // le fond cadre tout l'étage : on revient au robot
        this.plan.carte.setView(this.marqueurRobot.getLatLng(), ZOOM_SUIVI, { animate: false });
      }
    } catch (e) {
      this.etatCarte.textContent = ' — ' + e.message;
    }
  }

  recevoirDirect(d) {
    this.direct = d;
    if ((d.mode || null) !== this.modeVu) {
      this.modeVu = d.mode || null;
      this.majCamera();
    }
    const suivi = this.lieuSuivi(d);
    if (suivi.lieu + '/' + suivi.etage !== this.fond) this.chargerFond(suivi.lieu, suivi.etage);
    const r = suivi.enCours ? d.robot : null;
    let texte;
    if (!suivi.lieu) texte = ' — aucun lieu choisi';
    else if (!suivi.enCours) texte = ' — « ' + suivi.lieu + ' » : rien ne tourne';
    else if (!r) {
      texte = ' — « ' + suivi.lieu + ' » : robot pas encore repéré'
        + (d.mode === 'simu' ? '' : ' (Naviguer › Repérer)');
    } else texte = ' — « ' + suivi.lieu + ' », ' + suivi.etage + (r.perimee ? ' : position ancienne' : '');
    this.etatCarte.textContent = texte;
    if (r) {
      const icone = iconeOrientee('robot-direct' + (r.perimee ? ' perimee' : ''), r.theta);
      const p = ll(r.x, r.y);
      if (!this.marqueurRobot) {
        this.marqueurRobot = L.marker(p, { icon: icone, interactive: false, zIndexOffset: 1000 }).addTo(this.calque);
        if (this.suivre) this.plan.carte.setView(p, ZOOM_SUIVI, { animate: false });
      } else {
        this.marqueurRobot.setLatLng(p);
        this.marqueurRobot.setIcon(icone);
      }
      if (this.suivre && this.visible && !this.plan.carte.getBounds().pad(-0.2).contains(p)) {
        this.plan.carte.panTo(p, { animate: false });
      }
    } else if (this.marqueurRobot) {
      this.calque.removeLayer(this.marqueurRobot);
      this.marqueurRobot = null;
    }
    const vus = new Set();
    (suivi.enCours ? d.pietons || [] : []).forEach((pi) => {
      vus.add(pi.id);
      const m = this.pietons.get(pi.id);
      if (m) m.setLatLng(ll(pi.x, pi.y));
      else {
        this.pietons.set(pi.id, L.circle(ll(pi.x, pi.y), { radius: 0.25, className: 'pieton-direct', interactive: false })
          .addTo(this.calque));
      }
    });
    this.pietons.forEach((m, id) => {
      if (!vus.has(id)) {
        this.calque.removeLayer(m);
        this.pietons.delete(id);
      }
    });
  }

  suivreRobot() {
    this.suivre = true;
    this.boutonSuivre.hidden = true;
    if (this.marqueurRobot) this.plan.carte.setView(this.marqueurRobot.getLatLng(), Math.max(this.plan.carte.getZoom(), ZOOM_SUIVI), { animate: false });
  }

  // ---------------------------------------------------------------- état du pilotage

  // Appelé par l'onglet à chaque état lu (GET /api/pilotage/etat, 2 fois par seconde)
  majEtat(etat, joignable) {
    const now = performance.now();
    this.joignable = joignable;
    this.etat = etat;
    this.recu = now;
    if (!etat) return;
    const posture = P.postureDuMode(etat.fsm);
    if (posture !== this.postureLue) {
      if (this.postureLue !== undefined) this.tPosture = now;
      this.postureLue = posture;
    }
    // geste : celui du nœud (champ « geste »), sinon celui que la page a demandé (gesteDemande)
    if ('geste' in etat) {
      const g = etat.geste;
      if (g && g.numero !== this.numeroVu) {
        this.numeroVu = g.numero;
        this.commencerGeste('noeud', g.genre, g.id, g.nom, now - 1000 * g.ecoule_s, g.numero);
      } else if (!g && this.geste && this.geste.source === 'noeud' && !(this.geste.fini && this.geste.tenu)) {
        this.geste = null;                 // refusé par le robot, ou ARRÊT
      }
    }
    this.danse = etat.danse ? { id: etat.danse.id, nom: etat.danse.nom, duree_s: etat.danse.duree_s,
      t0: now - 1000 * (etat.danse.ecoule_s || 0) } : null;
    const c = etat.choregraphie;
    if (c) {
      this.chor = Object.assign({}, c, { recu: now });
      if (c.id && this.choregraphies[c.id] === undefined) this.chargerChoregraphie(c.id);
    } else {
      this.chor = null;
    }
  }

  // Geste demandé par un bouton de l'onglet (nœud sans le champ « geste » : avant la vue du robot)
  gesteDemande(genre, id) {
    if (this.etat && 'geste' in this.etat) return;
    const liste = genre === 'tache' ? this.config.taches : this.config.gestes;
    const g = (liste || []).find((x) => x.id === id);
    this.commencerGeste('page', genre, id, g ? g.nom : String(id), performance.now(), null);
  }

  commencerGeste(source, genre, id, nom, t0, numero) {
    if (genre === 'bras' && id === 99 && !this.geste) return;
    this.geste = { source, genre, id, nom, t0, numero, depart: Object.assign({}, this.qAffiche), fini: false };
  }

  async chargerChoregraphie(id) {
    this.choregraphies[id] = null;
    try {
      const r = await api.lire('/api/pilotage/choregraphies/' + encodeURIComponent(id));
      this.choregraphies[id] = r.choregraphie || null;
    } catch (e) {
      this.choregraphies[id] = null;     // introuvable sur ce PC : posture seulement
    }
  }

  // ---------------------------------------------------------------- animation

  animer(now) {
    const dt = Math.min(0.1, (now - this.tPrecedent) / 1000);
    this.tPrecedent = now;
    if (!this.pret) return;
    const e = this.etat;
    const nomPosture = (e && P.postureDuMode(e.fsm)) || 'debout';
    const qPosture = P.POSTURES[nomPosture].q;
    let cible = qPosture;
    let base = { x: 0, y: 0, cap: 0 };
    let led = null;
    let exacte = false;
    let activite = 'Au repos';
    let note = e && P.postureDuMode(e.fsm) && nomPosture !== 'debout' ? NOTES.posture : '';
    let part = null;
    const marche = !!(e && e.activite === 'marche' && e.consigne
      && (Math.abs(e.consigne.vx) + Math.abs(e.consigne.vy) + Math.abs(e.consigne.wz) > 0.01));
    const d = this.chor && this.chor.id ? this.choregraphies[this.chor.id] : null;
    if (this.danse) {
      const t = (now - this.danse.t0) / 1000;
      cible = P.poseDanse(t);
      activite = 'Danse ' + this.danse.id + (this.danse.nom ? ' « ' + this.danse.nom + ' »' : '') + ' : '
        + nb(t, 0) + ' s sur ' + (this.danse.duree_s ? nb(this.danse.duree_s, 0) + ' s' : '?');
      part = this.danse.duree_s ? Math.min(1, t / this.danse.duree_s) : null;
      note = NOTES.danse;
    } else if (this.chor && d && typeof this.chor.t === 'number') {
      const t = Math.min(d.duree_s, this.chor.t + ((now - this.chor.recu) / 1000) * (this.chor.vitesse || 1));
      const a = C.anglesVus(d, t);
      cible = Object.assign({}, qPosture, a.q);
      base = C.positionBase(d, t);
      led = C.couleurLed(d, t);
      exacte = true;
      this.tChor = t;
      activite = 'Chorégraphie « ' + (d.nom || d.id) + ' » : ' + nb(t, 1) + ' s sur ' + nb(d.duree_s, 1) + ' s';
      part = Math.min(1, t / d.duree_s);
      note = NOTES.choregraphie;
      this.dernierChor = a.q;
    } else if (this.chor) {
      // fin d'une chorégraphie (ARRÊT) : le poids des bras redescend ; ou chorégraphie inconnue ici
      const poids = typeof this.chor.poids_bras === 'number' ? this.chor.poids_bras : 0;
      cible = this.dernierChor ? P.melanger(qPosture, this.dernierChor, poids) : qPosture;
      activite = 'Chorégraphie « ' + (this.chor.nom || this.chor.id) + ' »' + (this.chor.arret ? ' : arrêt, bras relâchés' : '');
      note = d === undefined || d === null ? 'Chorégraphie absente de ce PC : posture seulement.' : '';
    } else if (this.geste) {
      const g = this.geste;
      const r = P.poseGeste(g.genre, g.id, (now - g.t0) / 1000, g.depart, qPosture);
      if (!r || (r.fini && !r.tenu)) {
        this.geste = null;
      } else {
        g.fini = r.fini;
        g.tenu = r.tenu;
        cible = r.q;
        activite = (g.genre === 'tache' ? 'Tâche : ' : 'Geste : ') + g.nom + (r.fini ? ' (tenu)' : '');
        note = NOTES.geste;
      }
    }
    if (marche && !this.danse && !exacte) {
      const m = P.poseMarche(cible, e.consigne, this.phase, this.config.limites_marche);
      this.phase = (this.phase + 2 * Math.PI * P.FREQUENCE_PAS_HZ * dt) % (2 * Math.PI);
      cible = this.geste ? Object.assign({}, cible, jambes(m)) : m;
      activite = (this.geste ? activite + ' · ' : '') + texteMarche(e.consigne);
      if (!this.geste) note = NOTES.marche;
    }
    const enTransition = now - this.tPosture < 3000;
    const k = exacte ? 1 : 1 - Math.exp(-dt / (enTransition ? TAU_POSTURE_S : TAU_S));
    this.qAffiche = P.melanger(this.qAffiche, cible, k);
    // on ne redessine que ce qui a bougé (robot immobile : aucune image)
    const q = P.borner(this.qAffiche, this.limites);
    const signature = JSON.stringify([base, led]);
    const bouge = !this.qPose || signature !== this.signaturePose
      || Object.keys(q).some((n) => Math.abs(q[n] - (this.qPose[n] === undefined ? 1e9 : this.qPose[n])) > 2e-4);
    if (bouge) {
      this.apercu.poser(q, base, led, { sol: true });
      this.qPose = q;
      this.signaturePose = signature;
    }
    // légende
    let posture = P.POSTURES[nomPosture].texte;
    if (!e) posture = this.joignable === false ? 'Nœud pilotage injoignable : la vue est figée' : 'État du robot inconnu';
    else if (P.postureDuMode(e.fsm) === null) posture = 'Mode du robot inconnu (' + (e.fsm === null ? '?' : e.fsm) + ')';
    else posture += ' · mode ' + e.fsm;
    this.ecrire('posture', this.lignePosture, posture);
    this.ecrire('activite', this.ligneActivite, activite);
    this.ecrire('note', this.ligneNote, note);
    this.progres.hidden = part === null;
    if (part !== null) this.progres.style.setProperty('--part', String(part));
    this.section.classList.toggle('vue-sans-etat', !e);
  }

  ecrire(cle, element, texte) {
    if (this.textes[cle] === texte) return;
    this.textes[cle] = texte;
    element.textContent = texte;
  }

  // ---------------------------------------------------------------- caméra de la tête

  modeCamera() {
    const m = this.direct && this.direct.mode;
    return m === 'robot' || m === 'repetition' || m === 'simu' ? m : 'aucun';
  }

  majCamera() {
    const mode = this.modeCamera();
    const voulu = souvenirVue('camera.' + mode, mode === 'robot' ? '1' : '0') === '1' && mode !== 'aucun';
    this.cameraActive = voulu;
    this.boutonCamera.textContent = voulu ? 'Couper' : 'Voir';
    this.boutonCamera.disabled = mode === 'aucun';
    if (!voulu) {
      this.jetonCamera += 1;
      this.image.hidden = true;
      this.remplacement.hidden = false;
      this.remplacement.textContent = TEXTES_CAMERA[mode];
      this.etatCamera.textContent = '';
      return;
    }
    if (this.visible) this.boucleCamera();
  }

  basculerCamera() {
    const mode = this.modeCamera();
    memoriser('pilotage.vue.camera.' + mode, this.cameraActive ? '0' : '1');
    this.majCamera();
  }

  async boucleCamera() {
    this.jetonCamera += 1;
    const jeton = this.jetonCamera;
    if (this.image.hidden) {
      this.remplacement.hidden = false;
      this.remplacement.textContent = 'Image de la caméra demandée…';
    }
    while (jeton === this.jetonCamera && this.cameraActive && this.visible && !this.ferme) {
      if (document.hidden) {
        await attendre(500);
        continue;
      }
      const debut = performance.now();
      let pause = PERIODE_CAMERA_MS;
      try {
        const r = await fetch('/api/pilotage/camera', { cache: 'no-store' });
        const genre = r.headers.get('content-type') || '';
        if (jeton !== this.jetonCamera) return;
        if (r.ok && genre.indexOf('image/') === 0) {
          const url = URL.createObjectURL(await r.blob());
          if (jeton !== this.jetonCamera) {
            URL.revokeObjectURL(url);
            return;
          }
          this.image.src = url;
          if (this.urlImage) URL.revokeObjectURL(this.urlImage);
          this.urlImage = url;
          this.image.hidden = false;
          this.remplacement.hidden = true;
          const age = parseFloat(r.headers.get('x-image-age-s') || '0');
          this.images = (this.images || 0) + 1;
          this.etatCamera.textContent = (age > IMAGE_FIGEE_S ? 'Image figée : la dernière date de ' + nb(age, 0) + ' s'
            : 'En direct') + (this.modeCamera() === 'robot' ? '' : ' · image de test du faux G1');
          this.etatCamera.classList.toggle('camera-figee', age > IMAGE_FIGEE_S);
        } else {
          let detail = 'La caméra ne répond pas (' + r.status + ').';
          try {
            detail = (await r.json()).detail || detail;
          } catch (err) {
            // réponse sans JSON : le message par défaut suffit
          }
          this.sansImage(detail);
          pause = 2000;
        }
      } catch (err) {
        this.sansImage('Le serveur de l\'Atelier ne répond pas.');
        pause = 2000;
      }
      await attendre(Math.max(0, pause - (performance.now() - debut)));
    }
  }

  sansImage(detail) {
    this.image.hidden = true;
    this.remplacement.hidden = false;
    const mode = this.modeCamera();
    this.remplacement.textContent = (mode === 'robot' ? '' : TEXTES_CAMERA[mode] + ' ') + detail;
    this.etatCamera.textContent = '';
  }
}

function jambes(q) {
  const r = {};
  Object.keys(q).forEach((n) => {
    if (/hip|knee|ankle/.test(n)) r[n] = q[n];
  });
  return r;
}

function texteMarche(c) {
  const parties = [];
  if (Math.abs(c.vx) > 0.01) parties.push((c.vx > 0 ? 'avance à ' : 'recule à ') + nb(Math.abs(c.vx), 2) + ' m/s');
  if (Math.abs(c.vy) > 0.01) parties.push('pas de côté vers la ' + (c.vy > 0 ? 'gauche' : 'droite') + ' à ' + nb(Math.abs(c.vy), 2) + ' m/s');
  if (Math.abs(c.wz) > 0.01) parties.push('tourne à ' + (c.wz > 0 ? 'gauche' : 'droite') + ' à ' + nb(Math.abs(c.wz), 2) + ' rad/s');
  return 'Marche : ' + (parties.join(', ') || 'sur place');
}
