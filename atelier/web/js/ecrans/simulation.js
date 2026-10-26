// Écran Simulation : lancer Gazebo et le guide sur le lieu, voir le robot et les piétons en
// direct (carte et 3D), envoyer le robot vers une salle (« Y aller »), l'arrêter (« Arrêt »).
//
// Trois modes (section 10.8 du plan) : « Simulation » (Gazebo seul), « Répétition sans robot »
// (Gazebo avec le faux G1 : la vraie chaîne du robot, repérage et pont compris) et « Robot »
// (la navigation dans le conteneur du Jetson). En répétition et avec le robot, le panneau
// « Repérage » rappelle de poser le robot sur le point principal du lieu (vague 4, section 11.2 :
// l'étoile sur la carte, tourné dans le sens de sa flèche), puis « Repérer le robot », qui part
// de cette pose ; sans point principal sur l'étage, c'est la marque au sol (croix) de la vague 3.
// « Y aller » reste grisé tant que le robot n'est pas repéré ou que Nav2 n'est pas prêt.

import { api, urlLieu } from '../api.js';
import { contexte, memoriser, souvenir } from '../contexte.js';
import { abonner } from '../direct.js';
import * as F from '../formulaire.js';
import * as G from '../geometrie.js';
import { afficherErreur, afficherMessage } from '../messages.js';
import { creerPlan, iconeOrientee, ll, lls, suivrePointeur } from '../plan.js';
import { Vue3D } from '../vue3d.js';
import { etiquetteSalle, iconePrincipal, sallePrincipale } from './salles.js';
// Vague 4 (section 11 du plan) : panneaux des agents Comportement du guide et Passants
import * as panneauGuide from '../panneaux/guide.js';
import * as panneauPassants from '../panneaux/passants.js';

const L = window.L;

const NOMS_PROCESSUS = {
  simulation: 'Simulation (Gazebo)',
  navigation: 'Navigation (guide)',
  faux_slam: 'Faux service de cartographie (slam_operate)',
  scan: 'Scan',
};

const MODES = [
  { id: 'simu', texte: 'Simulation', lancer: 'Lancer la simulation', arreter: 'Arrêter la simulation',
    aide: 'Le robot simulé de Gazebo, piloté directement par la navigation.' },
  { id: 'repetition', texte: 'Répétition sans robot', lancer: 'Lancer la répétition', arreter: 'Arrêter la répétition',
    aide: 'Comme avec le vrai robot (repérage, pont vers la marche), mais avec un faux G1 dans Gazebo.' },
  { id: 'robot', texte: 'Robot', lancer: 'Lancer sur le robot', arreter: 'Arrêter la navigation du robot',
    aide: 'La navigation tourne dans le conteneur du Jetson et commande le vrai G1.' },
];

const CONFIRMATION_ROBOT = 'Navigation sur le vrai robot :\n'
  + '- câble Ethernet branché entre le PC et le robot ;\n'
  + '- Atelier lancé après « source ~/robot-g1/setup/robot.sh » ;\n'
  + '- télécommande en main : elle reste l\'arrêt d\'urgence ;\n'
  + '- robot debout, en mode marche, avec quelqu\'un à côté.\n\nLancer la navigation sur le robot ?';

const ETATS_REPERAGE = {
  non_repere: 'Non repéré',
  en_cours: 'Repérage en cours…',
  repere: 'Repéré',
  perdu: 'Repérage perdu',
  echec: 'Échec du repérage',
};

const ETATS_PONT = {
  demarrage: 'démarrage', attente_reperage: 'attend le repérage', pret: 'prêt', en_mouvement: 'en marche',
  arret: 'arrêt demandé', arret_verrouille: 'bloqué', robot_muet: 'le robot ne répond pas', refus: 'refus du robot',
};

const ETATS_GUIDE = {
  attente: 'En attente d\'une destination',
  en_route: 'En route',
  bloque: 'Bloqué : quelque chose gêne le passage',
  detour: 'Détour : le guide prend un autre chemin',
  arrive: 'Arrivé',
  echec: 'Échec : le guide n\'a pas pu y aller',
  // vague 4 (section 11.4)
  retour: 'Retour au point principal',
  attente_passage: 'Attend qu\'un passant libère le passage',
  attente_visiteur: 'Attend le visiteur',
  perdu: 'Perdu : le robot ne sait plus où il est',
};

export function ouvrir(racine) {
  const lieu = contexte.lieu;
  const etage = contexte.etage;
  const memoire = souvenir('mode-simulation');
  const etat = {
    salles: [], noeuds: {}, monde: null, dernierItineraire: '', enCours: false,
    mode: MODES.some((m) => m.id === memoire) ? memoire : 'simu',   // mode choisi
    modeActif: null,        // mode de ce qui tourne (null : rien)
    marque: null,           // pose où poser le robot {x, y, theta}, repère map : le point principal, sinon la marque au sol
    principal: null,        // point principal de l'étage {salle, nom, etage, x, y, theta}, ou null
    repere: false,
    reperageEnCours: false,
    placement: null,        // « pas sur le point principal » : {x, y, theta} pendant le geste
    choixPosition: false,
  };

  racine.innerHTML = `
    <div class="barre">
      <div class="barre-gauche">
        <div class="groupe-outils modes-simulation" data-role="modes" role="radiogroup" aria-label="Mode"></div>
        <button type="button" class="bouton bouton-principal bouton-grand" data-role="lancer">Lancer la simulation</button>
        <button type="button" class="bouton bouton-grand" data-role="arreter">Arrêter la simulation</button>
        <span class="etat-action" data-role="etat-simu">Simulation arrêtée</span>
      </div>
    </div>
    <p class="aide" data-role="aide-mode"></p>
    <div class="espace-trois">
      <div class="plan" data-role="plan"></div>
      <div class="cote">
        <div class="vue3d" data-role="vue3d"></div>
        <div class="panneau panneau-reperage" data-role="reperage" hidden>
          <h3 class="panneau-titre">Repérage</h3>
          <p class="panneau-texte" data-role="consigne-reperage">Posez le robot sur le point principal (étoile sur la carte), tourné dans le sens de la flèche.</p>
          <button type="button" class="bouton bouton-principal bouton-grand bouton-reperer" data-role="reperer">Repérer le robot</button>
          <button type="button" class="bouton-lien" data-role="pas-sur-marque">Le robot n'est pas sur le point principal</button>
          <p class="panneau-note" data-role="aide-position" hidden>Cliquez sur la carte là où se trouve le robot, puis glissez vers l'avant du robot. Le repérage part quand vous lâchez.</p>
          <div class="etat-reperage" data-role="etat-reperage">Non repéré</div>
          <div class="panneau-note" data-role="message-reperage"></div>
          <div class="pastille-pont" data-role="pont">Pont vers la marche : —</div>
          <div class="boutons-verrou">
            <button type="button" class="bouton bouton-danger" data-role="bloquer">Bloquer le robot</button>
            <button type="button" class="bouton" data-role="debloquer">Débloquer</button>
          </div>
        </div>
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
        <div class="panneau panneau-comportement" data-role="panneau-comportement"></div>
        <div class="panneau panneau-passants" data-role="panneau-passants"></div>
      </div>
    </div>`;
  const $ = (r) => racine.querySelector('[data-role="' + r + '"]');
  const plan = creerPlan($('plan'));
  const carte = plan.carte;
  const vue = new Vue3D($('vue3d'));
  const outilsPanneaux = { lieu: lieu, etage: etage, plan: plan, carte: carte };
  const panneaux = [panneauGuide.monter($('panneau-comportement'), outilsPanneaux),
    panneauPassants.monter($('panneau-passants'), outilsPanneaux)];
  const calqueSalles = L.layerGroup().addTo(carte);
  const calqueMarque = L.layerGroup().addTo(carte);
  const calqueItineraire = L.layerGroup().addTo(carte);
  const calqueDirect = L.layerGroup().addTo(carte);
  let marqueurRobot = null;
  let marqueurPlacement = null;
  const marqueursPietons = new Map();

  // ---------------------------------------------------------------- mode, point principal et marque au sol

  const boutonsModes = MODES.map((m) => {
    const b = F.el('button', 'outil', m.texte);
    b.type = 'button';
    b.dataset.mode = m.id;
    b.title = m.aide;
    b.setAttribute('role', 'radio');
    b.addEventListener('click', () => choisirMode(m.id));
    $('modes').appendChild(b);
    return b;
  });

  function defMode(id) {
    return MODES.find((m) => m.id === id) || MODES[0];
  }

  function avecReperage() {
    return (etat.modeActif || etat.mode) !== 'simu';
  }

  function choisirMode(id) {
    if (etat.modeActif) return;          // on ne change pas de mode pendant que ça tourne
    etat.mode = id;
    memoriser('mode-simulation', id);
    majMode();
  }

  function majMode() {
    const actuel = etat.modeActif || etat.mode;
    const d = defMode(actuel);
    boutonsModes.forEach((b) => {
      const choisi = b.dataset.mode === actuel;
      b.classList.toggle('actif', choisi);
      b.setAttribute('aria-checked', choisi ? 'true' : 'false');
      b.disabled = !!etat.modeActif && !choisi;
    });
    $('lancer').textContent = d.lancer;
    $('arreter').textContent = d.arreter;
    $('aide-mode').textContent = d.aide;
    $('reperage').hidden = !avecReperage();
    if (!avecReperage() && etat.choixPosition) choisirPosition(false);
    dessinerMarque();
  }

  // Textes du panneau Repérage : le point principal (vague 4), ou la marque au sol sans lui
  function textesPose() {
    const p = etat.principal;
    if (p) {
      return {
        consigne: 'Posez le robot sur le point principal « ' + p.nom + ' » (étoile sur la carte), tourné dans le sens de la flèche.',
        lien: 'Le robot n\'est pas sur le point principal',
        annuler: 'Annuler : le robot est sur le point principal',
        court: 'sur le point principal « ' + p.nom + ' »',
      };
    }
    return {
      consigne: 'Posez le robot sur la marque au sol (croix sur la carte), tourné dans le sens de la flèche.',
      lien: 'Le robot n\'est pas sur la marque',
      annuler: 'Annuler : le robot est sur la marque',
      court: 'sur la marque au sol',
    };
  }

  function majTextesPose() {
    const t = textesPose();
    $('consigne-reperage').textContent = t.consigne;
    $('pas-sur-marque').textContent = etat.choixPosition ? t.annuler : t.lien;
  }

  async function chargerMarque() {
    try {
      const r = await api.lire('/api/robot/etat?lieu=' + encodeURIComponent(lieu) + '&etage=' + encodeURIComponent(etage));
      if (!r.mode || (r.lieu === lieu && r.etage === etage)) {
        etat.marque = r.marque;
        etat.principal = r.principal || null;
      }
    } catch (e) {
      etat.marque = null;          // pas grave : la marque n'est qu'une aide
      etat.principal = null;
    }
    majTextesPose();
    dessinerMarque();
  }

  function dessinerMarque() {
    calqueMarque.clearLayers();
    if (!etat.marque || !avecReperage()) return;
    const m = etat.marque;
    if (etat.principal) {
      // le point principal est déjà dessiné (étoile et flèche, calque des salles) : on l'entoure
      L.circle(ll(m.x, m.y), { radius: 0.6, className: 'marque-principal', interactive: false })
        .bindTooltip('Point principal « ' + etat.principal.nom + ' » : posez le robot ici, tourné dans le sens de la flèche',
          { direction: 'top', className: 'etiquette' })
        .addTo(calqueMarque);
      return;
    }
    const deg = -m.theta * 180 / Math.PI;
    L.marker(ll(m.x, m.y), {
      icon: L.divIcon({ className: 'marque-sol', iconSize: [34, 34], iconAnchor: [17, 17],
        html: '<div class="marque-sol-croix" style="transform: rotate(' + deg + 'deg)"><span></span></div>' }),
      interactive: false, keyboard: false,
    }).bindTooltip('Marque au sol : posez le robot ici', { direction: 'top', offset: [0, -14], className: 'etiquette' })
      .addTo(calqueMarque);
  }

  // ---------------------------------------------------------------- repérage

  async function reperer(pose) {
    if (etat.reperageEnCours) return;
    etat.reperageEnCours = true;
    const b = $('reperer');
    b.disabled = true;
    b.textContent = 'Repérage…';
    const corps = { lieu: lieu, etage: etage };
    if (pose) {
      corps.x = G.arrondir(pose.x, 3);
      corps.y = G.arrondir(pose.y, 3);
      corps.cap = G.arrondir(pose.theta, 4);
    }
    try {
      const r = await api.envoyer('/api/robot/reperer', corps);
      afficherMessage(r.message || 'Robot repéré.', 'succes');
    } catch (e) {
      afficherErreur(e);
    } finally {
      etat.reperageEnCours = false;
      b.textContent = 'Repérer le robot';
      b.disabled = false;
    }
  }

  $('reperer').addEventListener('click', () => reperer(null));

  function choisirPosition(oui) {
    etat.choixPosition = oui;
    $('aide-position').hidden = !oui;
    majTextesPose();
    plan.cadre.classList.toggle('dessin', oui);
  }

  $('pas-sur-marque').addEventListener('click', () => choisirPosition(!etat.choixPosition));

  function dessinerPlacement() {
    const t = etat.placement;
    if (!t) {
      if (marqueurPlacement) calqueDirect.removeLayer(marqueurPlacement);
      marqueurPlacement = null;
      return;
    }
    const icone = iconeOrientee('robot-direct trace', t.theta);
    if (!marqueurPlacement) marqueurPlacement = L.marker(ll(t.x, t.y), { icon: icone, interactive: false, zIndexOffset: 900 }).addTo(calqueDirect);
    else {
      marqueurPlacement.setLatLng(ll(t.x, t.y));
      marqueurPlacement.setIcon(icone);
    }
  }

  const arreterPointeur = suivrePointeur(plan, {
    debut: (p) => {
      if (!etat.choixPosition) return false;
      etat.placement = { x: p[0], y: p[1], theta: etat.marque ? etat.marque.theta : 0 };
      dessinerPlacement();
      return true;
    },
    deplacer: (p) => {
      const t = etat.placement;
      if (!t) return;
      if (G.distance([t.x, t.y], p) > 0.2) t.theta = G.accrocherAngle(Math.atan2(p[1] - t.y, p[0] - t.x), 5);
      dessinerPlacement();
    },
    fin: () => {
      const t = etat.placement;
      choisirPosition(false);
      if (t) {
        reperer(t).finally(() => {
          etat.placement = null;
          dessinerPlacement();
        });
      }
    },
    annuler: () => {
      etat.placement = null;
      dessinerPlacement();
    },
  });

  async function verrouiller(verrou) {
    try {
      const r = await api.envoyer('/api/robot/arret', { verrou: verrou });
      afficherMessage(verrou ? 'Robot bloqué : il reste immobile jusqu\'à « Débloquer ».'
        : 'Robot débloqué : il repartira à la prochaine consigne.', verrou ? 'avertissement' : 'info');
      if (r.avertissement) afficherMessage(r.avertissement, 'avertissement');
    } catch (e) {
      afficherErreur(e);
    }
  }

  $('bloquer').addEventListener('click', () => verrouiller(true));
  $('debloquer').addEventListener('click', () => verrouiller(false));

  function majReperage(d) {
    const r = d.reperage;
    const avecRobot = !!etat.modeActif && etat.modeActif !== 'simu';
    let titre = 'Non repéré';
    let classe = 'reperage-non_repere';
    let message = 'Lancez la répétition ou le robot, puis posez le robot ' + textesPose().court + '.';
    etat.repere = false;
    if (avecRobot) {
      if (!r || r.perime) {
        titre = 'Relais de position…';
        message = 'Le relais de position démarre : « Repérer le robot » sera possible dans quelques secondes.';
      } else {
        titre = ETATS_REPERAGE[r.etat] || r.etat;
        classe = 'reperage-' + r.etat;
        message = r.message || '';
        etat.repere = !!r.repere;
        if (r.repere) {
          const morceaux = [];
          if (r.precision_m !== null && r.precision_m !== undefined) morceaux.push('précision ' + Math.max(1, Math.round(r.precision_m * 100)) + ' cm');
          if (r.age_s !== null && r.age_s !== undefined) morceaux.push('il y a ' + G.nb(r.age_s, 1) + ' s');
          if (morceaux.length) titre += ' (' + morceaux.join(', ') + ')';
        }
      }
    }
    $('etat-reperage').textContent = titre;
    $('etat-reperage').className = 'etat-reperage ' + classe;
    $('message-reperage').textContent = message;
    const ros = !!(d.ros && d.ros.actif);
    $('reperer').disabled = !(avecRobot && ros) || etat.reperageEnCours;
    $('pas-sur-marque').disabled = !(avecRobot && ros);
    $('bloquer').disabled = !ros;
    $('debloquer').disabled = !ros;
    const p = d.pont;
    const z = $('pont');
    if (!p || p.perime) {
      z.textContent = 'Pont vers la marche : ' + (avecRobot ? 'pas encore de nouvelles' : '—');
      z.className = 'pastille-pont';
    } else {
      z.textContent = 'Pont vers la marche : ' + (ETATS_PONT[p.etat] || p.etat) + (p.message ? ' — ' + p.message : '');
      const ok = p.etat === 'pret' || p.etat === 'en_mouvement';
      const ko = p.etat === 'robot_muet' || p.etat === 'refus' || p.etat === 'arret_verrouille';
      z.className = 'pastille-pont ' + (ok ? 'pont-ok' : (ko ? 'pont-ko' : 'pont-attente'));
    }
  }

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
    const p = sallePrincipale(etat.salles);
    etat.salles.filter((s) => s.etage === etage).forEach((s) => {
      const icone = s === p ? iconePrincipal(s.pose.theta) : iconeOrientee('salle', s.pose.theta);
      L.marker(ll(s.pose.x, s.pose.y), { icon: icone, keyboard: false, zIndexOffset: s === p ? 500 : 0 })
        .bindTooltip(etiquetteSalle(s.nom, s === p), { permanent: true, direction: 'right', offset: [14, 0], className: 'etiquette' })
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
    const mode = etat.mode;
    if (mode === 'robot' && !window.confirm(CONFIRMATION_ROBOT)) return;
    b.disabled = true;
    $('etat-simu').textContent = 'Lancement…';
    try {
      const corps = { lieu: lieu, etage: etage };
      if (mode !== 'simu') corps.mode = mode;
      const r = await api.envoyer('/api/simulation/demarrer', corps);
      const av = (r.simulation && r.simulation.avertissements) || [];
      if (mode === 'simu') afficherMessage('Simulation lancée. Gazebo démarre (sans fenêtre) : le robot apparaît dans quelques secondes.', 'succes');
      else if (mode === 'repetition') afficherMessage('Répétition lancée : Gazebo et le faux G1 démarrent. Quand le relais de position est prêt, cliquez sur « Repérer le robot ».', 'succes');
      else afficherMessage('Navigation lancée sur le robot. Posez-le ' + textesPose().court + ', tourné dans le sens de la flèche, puis cliquez sur « Repérer le robot ».', 'succes');
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
      afficherMessage(etat.modeActif === 'robot' ? 'Navigation du robot arrêtée.' : 'Simulation arrêtée.', 'info');
    } catch (e) {
      afficherErreur(e);
    } finally {
      b.disabled = false;
    }
  });

  function texteGuide(g) {
    if (!g) return { titre: 'Guide non lancé', detail: 'Lancez la simulation : le guide démarre avec elle.' };
    let titre = ETATS_GUIDE[g.etat] || ('État : ' + g.etat);
    if (['en_route', 'arrive', 'echec', 'detour', 'bloque', 'retour', 'attente_passage', 'attente_visiteur', 'perdu'].includes(g.etat) && g.cible) {
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
    const robot = d.mode === 'robot';
    const enCours = !!(sim && sim.en_cours) || robot;
    etat.enCours = enCours;
    if ((d.mode || null) !== etat.modeActif) {
      etat.modeActif = d.mode || null;
      majMode();
    }
    let texte = 'Simulation arrêtée';
    if (robot) {
      texte = 'Robot : navigation en cours sur le lieu « ' + sim.lieu + ' », étage « ' + sim.etage + ' »';
    } else if (enCours) {
      texte = (d.mode === 'repetition' ? 'Répétition en cours' : 'Simulation en cours') + ' : lieu « ' + sim.lieu + ' », étage « ' + sim.etage + ' »';
      if (procs.navigation) texte += procs.navigation.en_cours ? ', guide lancé' : ', guide arrêté';
    } else if (procs.simulation && !procs.simulation.en_cours && !procs.simulation.arret_demande) {
      texte = 'La simulation s\'est arrêtée seule (code ' + procs.simulation.code + ') : ouvrez « Ce qui tourne » pour voir pourquoi.';
    }
    if (enCours && sim && (sim.lieu !== lieu || sim.etage !== etage)) texte += ' (ce n\'est pas le lieu affiché)';
    $('etat-simu').textContent = texte;
    $('lancer').disabled = enCours;
    $('arreter').disabled = !enCours && !(procs.navigation && procs.navigation.en_cours);
    majReperage(d);
    if (!d.ros || !d.ros.actif) $('etat-simu').textContent += ' — pas de liaison ROS 2' + (d.ros && d.ros.erreur ? ' (' + d.ros.erreur + ')' : '');

    const memeLieu = !!sim && sim.lieu === lieu && sim.etage === etage;
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
    const navEnCours = robot || !!(nav && nav.en_cours);
    const attendreNav2 = navEnCours && !!(d.ros && d.ros.actif)
      && (nav2 === false || (nav2 === null && (robot || nav.duree_s < 60)));
    // répétition et robot : il faut d'abord repérer le robot (la carte globale de Nav2 attend sa position)
    const attendreReperage = navEnCours && avecReperage() && !etat.repere;
    if (attendreReperage) {
      t.titre = 'Le guide attend le repérage du robot';
      t.detail = 'Posez le robot ' + textesPose().court + ', tourné dans le sens de la flèche, puis cliquez sur « Repérer le robot ».';
    } else if (attendreNav2) {
      t.titre = 'Le guide démarre…';
      t.detail = 'Nav2 se prépare (20 à 30 secondes après le lancement). « Y aller » sera possible ensuite.';
    }
    if (g && g.message && !attendreReperage) t.detail = g.message + (t.detail ? ' ' + t.detail : '');
    racine.querySelectorAll('.liste-salles button').forEach((b) => { b.disabled = attendreNav2 || attendreReperage; });
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
    majMode();
    chargerMarque();
    desabonner = abonner(recevoir);
  }
  racine.classList.add('chargement');     // rien n'est modifiable avant la fin du chargement
  charger().finally(() => racine.classList.remove('chargement'));

  return {
    modifie: () => false,
    fermer: () => {
      if (desabonner) desabonner();
      panneaux.forEach((p) => p.fermer());
      arreterPointeur();
      vue.detruire();
      plan.detruire();
    },
  };
}

