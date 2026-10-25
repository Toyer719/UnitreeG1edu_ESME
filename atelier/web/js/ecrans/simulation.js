// Écran Simulation : lancer Gazebo et le guide sur le lieu, voir le robot et les piétons en
// direct (carte et 3D), envoyer le robot vers une salle (« Y aller »), l'arrêter (« Arrêt »).

import { api, urlLieu } from '../api.js';
import { contexte } from '../contexte.js';
import { abonner } from '../direct.js';
import * as F from '../formulaire.js';
import * as G from '../geometrie.js';
import { afficherErreur, afficherMessage } from '../messages.js';
import { creerPlan, iconeOrientee, ll, lls } from '../plan.js';
import { Vue3D } from '../vue3d.js';

const L = window.L;

const NOMS_PROCESSUS = {
  simulation: 'Simulation (Gazebo)',
  navigation: 'Navigation (guide)',
  faux_slam: 'Faux service du scan',
  scan: 'Scan',
};

const ETATS_GUIDE = {
  attente: 'En attente d\'une destination',
  en_route: 'En route',
  bloque: 'Bloqué : quelque chose gêne le passage',
  detour: 'Détour : le guide prend un autre chemin',
  arrive: 'Arrivé',
  echec: 'Échec : le guide n\'a pas pu y aller',
};

export function ouvrir(racine) {
  const lieu = contexte.lieu;
  const etage = contexte.etage;
  const etat = { salles: [], noeuds: {}, monde: null, dernierItineraire: '', enCours: false };

  racine.innerHTML = `
    <div class="barre">
      <div class="barre-gauche">
        <button type="button" class="bouton bouton-principal bouton-grand" data-role="lancer">Lancer la simulation</button>
        <button type="button" class="bouton bouton-grand" data-role="arreter">Arrêter la simulation</button>
        <span class="etat-action" data-role="etat-simu">Simulation arrêtée</span>
      </div>
    </div>
    <div class="espace-trois">
      <div class="plan" data-role="plan"></div>
      <div class="cote">
        <div class="vue3d" data-role="vue3d"></div>
        <div class="panneau panneau-guide">
          <button type="button" class="bouton-arret" data-role="arret" title="Arrête le robot tout de suite">ARRÊT</button>
          <div class="guide-etat" data-role="guide">Guide non lancé</div>
          <div class="guide-detail" data-role="guide-detail"></div>
          <h3 class="panneau-titre">Envoyer le robot</h3>
          <ul class="liste-salles" data-role="salles"></ul>
          <details class="processus">
            <summary>Ce qui tourne (messages des commandes)</summary>
            <div data-role="processus"></div>
          </details>
        </div>
      </div>
    </div>`;
  const $ = (r) => racine.querySelector('[data-role="' + r + '"]');
  const plan = creerPlan($('plan'));
  const carte = plan.carte;
  const vue = new Vue3D($('vue3d'));
  const calqueSalles = L.layerGroup().addTo(carte);
  const calqueItineraire = L.layerGroup().addTo(carte);
  const calqueDirect = L.layerGroup().addTo(carte);
  let marqueurRobot = null;
  const marqueursPietons = new Map();

  function nomDe(id) {
    const s = etat.salles.find((x) => x.id === id);
    return s ? s.nom : id;
  }

  function listeSalles() {
    const ul = $('salles');
    ul.innerHTML = '';
    const salles = etat.salles.filter((s) => s.etage === etage);
    if (!salles.length) ul.appendChild(F.el('li', 'vide', 'Aucune salle : placez-en dans l\'onglet Salles.'));
    salles.forEach((s) => {
      const li = F.el('li');
      li.appendChild(F.el('span', 'nom-salle', s.nom));
      F.bouton(li, 'Y aller', () => allerVers(s.id), 'bouton bouton-principal');
      ul.appendChild(li);
    });
  }

  function dessinerSalles() {
    calqueSalles.clearLayers();
    etat.salles.filter((s) => s.etage === etage).forEach((s) => {
      L.marker(ll(s.pose.x, s.pose.y), { icon: iconeOrientee('salle' + (s.id === 'accueil' ? ' accueil' : ''), s.pose.theta), keyboard: false })
        .bindTooltip(s.nom, { permanent: true, direction: 'right', offset: [12, 0], className: 'etiquette' })
        .on('click', () => allerVers(s.id))
        .addTo(calqueSalles);
    });
  }

  async function allerVers(id) {
    try {
      const r = await api.envoyer('/api/guide/aller', { cible: id });
      afficherMessage('Destination envoyée : ' + nomDe(id) + '.', 'info');
      if (r.avertissement) afficherMessage(r.avertissement, 'avertissement');
    } catch (e) {
      afficherErreur(e);
    }
  }

  $('arret').addEventListener('click', async () => {
    try {
      await api.envoyer('/api/guide/stop');
      afficherMessage('Arrêt envoyé au robot.', 'info');
    } catch (e) {
      afficherErreur(e);
    }
  });

  $('lancer').addEventListener('click', async () => {
    const b = $('lancer');
    b.disabled = true;
    $('etat-simu').textContent = 'Lancement…';
    try {
      const r = await api.envoyer('/api/simulation/demarrer', { lieu: lieu, etage: etage });
      const av = (r.simulation && r.simulation.avertissements) || [];
      afficherMessage('Simulation lancée. Gazebo démarre (sans fenêtre) : le robot apparaît dans quelques secondes.', 'succes');
      av.forEach((m) => afficherMessage(m, 'avertissement'));
    } catch (e) {
      afficherErreur(e);
      b.disabled = false;
    }
  });

  $('arreter').addEventListener('click', async () => {
    const b = $('arreter');
    b.disabled = true;
    $('etat-simu').textContent = 'Arrêt en cours… (quelques secondes)';
    try {
      await api.envoyer('/api/simulation/arreter');
      afficherMessage('Simulation arrêtée.', 'info');
    } catch (e) {
      afficherErreur(e);
    } finally {
      b.disabled = false;
    }
  });

  function texteGuide(g) {
    if (!g) return { titre: 'Guide non lancé', detail: 'Lancez la simulation : le guide démarre avec elle.' };
    let titre = ETATS_GUIDE[g.etat] || ('État : ' + g.etat);
    if ((g.etat === 'en_route' || g.etat === 'arrive' || g.etat === 'echec' || g.etat === 'detour' || g.etat === 'bloque') && g.cible) {
      titre += (g.etat === 'arrive' ? ' à « ' : ' — vers « ') + nomDe(g.cible) + ' »';
    }
    let detail = '';
    if (g.reste_m !== null && g.reste_m !== undefined && g.etat !== 'arrive') detail = 'Encore ' + G.nb(g.reste_m, 1) + ' m.';
    if (g.itineraire && g.itineraire.length) detail += ' Chemin : ' + g.itineraire.join(' → ');
    return { titre: titre, detail: detail };
  }

  function dessinerItineraire(g) {
    const cle = g && g.itineraire ? g.itineraire.join(',') + g.etat : '';
    if (cle === etat.dernierItineraire) return;
    etat.dernierItineraire = cle;
    calqueItineraire.clearLayers();
    if (!g || !g.itineraire || g.etat === 'arrive' || g.etat === 'attente') return;
    const pts = g.itineraire.map((id) => etat.noeuds[id]).filter((n) => n && n.etage === etage).map((n) => [n.x, n.y]);
    if (pts.length > 1) L.polyline(lls(pts), { className: 'itineraire-direct', interactive: false }).addTo(calqueItineraire);
  }

  function majProcessus(processus) {
    const z = $('processus');
    z.innerHTML = '';
    const roles = Object.keys(processus || {});
    if (!roles.length) {
      z.appendChild(F.el('p', 'panneau-note', 'Rien ne tourne.'));
      return;
    }
    roles.forEach((role) => {
      const p = processus[role];
      const bloc = F.el('div', 'processus-bloc');
      const etatTexte = p.en_cours ? 'en cours' : (p.arret_demande ? 'arrêté' : 'terminé (code ' + p.code + ')');
      bloc.appendChild(F.el('div', 'processus-titre' + (!p.en_cours && !p.arret_demande && p.code ? ' processus-erreur' : ''),
        (NOMS_PROCESSUS[role] || role) + ' : ' + etatTexte));
      bloc.appendChild(F.el('div', 'code', p.commande));
      if (p.dernieres_lignes && p.dernieres_lignes.length) bloc.appendChild(F.el('pre', 'processus-sortie', p.dernieres_lignes.join('\n')));
      if (p.journal) bloc.appendChild(F.el('div', 'panneau-note', 'Journal complet : ' + p.journal));
      z.appendChild(bloc);
    });
  }

  function recevoir(d) {
    const sim = d.simulation;
    const procs = d.processus || {};
    const enCours = !!(sim && sim.en_cours);
    etat.enCours = enCours;
    let texte = 'Simulation arrêtée';
    if (enCours) {
      texte = 'Simulation en cours : lieu « ' + sim.lieu + ' », étage « ' + sim.etage + ' »';
      if (procs.navigation) texte += procs.navigation.en_cours ? ', guide lancé' : ', guide arrêté';
      if (sim.lieu !== lieu || sim.etage !== etage) texte += ' (ce n\'est pas le lieu affiché)';
    } else if (procs.simulation && !procs.simulation.en_cours && !procs.simulation.arret_demande) {
      texte = 'La simulation s\'est arrêtée seule (code ' + procs.simulation.code + ') : ouvrez « Ce qui tourne » pour voir pourquoi.';
    }
    $('etat-simu').textContent = texte;
    $('lancer').disabled = enCours;
    $('arreter').disabled = !enCours && !(procs.navigation && procs.navigation.en_cours);
    if (!d.ros || !d.ros.actif) $('etat-simu').textContent += ' — pas de liaison ROS 2' + (d.ros && d.ros.erreur ? ' (' + d.ros.erreur + ')' : '');

    const memeLieu = sim && sim.lieu === lieu && sim.etage === etage;
    // robot
    const r = d.robot;
    if (r && memeLieu) {
      const icone = iconeOrientee('robot-direct' + (r.perimee ? ' perimee' : ''), r.theta);
      if (!marqueurRobot) marqueurRobot = L.marker(ll(r.x, r.y), { icon: icone, interactive: false, zIndexOffset: 1000 }).addTo(calqueDirect);
      else {
        marqueurRobot.setLatLng(ll(r.x, r.y));
        marqueurRobot.setIcon(icone);
      }
      vue.robotEnDirect = true;
      vue.placerRobot(r.x, r.y, r.theta);
    } else if (marqueurRobot) {
      calqueDirect.removeLayer(marqueurRobot);
      marqueurRobot = null;
    }
    // piétons
    const vus = new Set();
    (memeLieu ? d.pietons || [] : []).forEach((p) => {
      vus.add(p.id);
      let m = marqueursPietons.get(p.id);
      if (!m) {
        m = L.circle(ll(p.x, p.y), { radius: 0.25, className: 'pieton-direct', interactive: false }).addTo(calqueDirect);
        marqueursPietons.set(p.id, m);
      } else m.setLatLng(ll(p.x, p.y));
    });
    marqueursPietons.forEach((m, id) => {
      if (!vus.has(id)) {
        calqueDirect.removeLayer(m);
        marqueursPietons.delete(id);
      }
    });
    vue.placerPietons(memeLieu ? d.pietons : []);
    // guide. Juste après le lancement, Nav2 se prépare (20 à 30 s) et refuserait un but : on attend
    // tant qu'il est vu inactif, ou 60 s au plus s'il n'est pas encore visible (le moteur unitree
    // n'a pas de Nav2 : au-delà, on laisse faire).
    const g = enCours || d.guide ? d.guide : null;
    const t = texteGuide(g);
    const nav = procs.navigation;
    const nav2 = d.ros ? d.ros.nav2 : null;
    const attendreNav2 = !!(nav && nav.en_cours && d.ros && d.ros.actif)
      && (nav2 === false || (nav2 === null && nav.duree_s < 60));
    if (attendreNav2) {
      t.titre = 'Le guide démarre…';
      t.detail = 'Nav2 se prépare (20 à 30 secondes après le lancement). « Y aller » sera possible ensuite.';
    }
    racine.querySelectorAll('.liste-salles button').forEach((b) => { b.disabled = attendreNav2; });
    $('guide').textContent = t.titre;
    $('guide').className = 'guide-etat' + (g ? ' guide-' + g.etat : '');
    $('guide-detail').textContent = t.detail;
    dessinerItineraire(g);
    majProcessus(procs);
  }

  let desabonner = null;
  async function charger() {
    try {
      const fond = await plan.afficherFond(lieu, etage);
      etat.monde = fond.monde;
      etat.salles = await api.lire(urlLieu(lieu) + '/salles');
      etat.noeuds = (await api.lire(urlLieu(lieu) + '/itineraires')).noeuds;
    } catch (e) {
      afficherErreur(e);
    }
    if (etat.monde) {
      vue.afficherMonde(etat.monde, null, false);
      vue.cadrer(etat.monde.emprise);
    }
    dessinerSalles();
    listeSalles();
    desabonner = abonner(recevoir);
  }
  racine.classList.add('chargement');     // rien n'est modifiable avant la fin du chargement
  charger().finally(() => racine.classList.remove('chargement'));

  return {
    modifie: () => false,
    fermer: () => {
      if (desabonner) desabonner();
      vue.detruire();
      plan.detruire();
    },
  };
}

