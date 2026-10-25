// Écran Scan : scanner un étage avec le LiDAR, puis en tirer la carte 2D et le monde.
//   1. le mode : Robot (le vrai G1 et sa cartographie Unitree ; « Répétition sans robot » rejoue
//      tout avec le robot simulé) ou Simulation (le robot proxy de Gazebo scanne le monde dessiné) ;
//   2. « Scan » : la cartographie démarre ; aperçu en direct (vue de dessus et nuage 3D) ;
//   3. « Fin » : carte 3D, carte 2D, puis reconnaissance des murs, passages et objets (progression) ;
//   4. la revue : éléments à garder ou non, puis adoption par l'étage (la carte, ou la carte et le monde).
// API : section 9.7 du plan (/api/scan/...). Pilotage du robot simulé : teleop.js.

import { api, urlEtage } from '../api.js';
import { choisirEtage, contexte, emettre, etageCourant, memoriser, rechargerLieu, souvenir } from '../contexte.js';
import * as F from '../formulaire.js';
import { coinsMur, empreinteObjet, nb } from '../geometrie.js';
import { afficherErreur, afficherMessage, afficherRapport } from '../messages.js';
import { Nuage3D } from '../nuage3d.js';
import { creerPlan, iconeOrientee, ll, lls } from '../plan.js';
import { Teleop } from '../teleop.js';
import { Vue3D } from '../vue3d.js';

const L = window.L;
const PERIODE_ETAT = 1000;          // ms : GET /api/scan/etat
const PERIODE_APERCU = 2000;        // ms : apercu.png et apercu.json (réécrits toutes les 2 s au plus)
const DELAI_CHOIX = 400;            // ms : les cases cochées à la suite partent ensemble
export const CONFIANCE_DOUTEUSE = 0.5;

// Une couleur par catégorie : sur le plan, dans la liste et dans la légende
export const CATEGORIES = {
  mur: { texte: 'Mur', couleur: '#e5484d' },
  passage: { texte: 'Passage (porte)', couleur: '#22a559' },
  table: { texte: 'Table', couleur: '#f59e0b' },
  chaise: { texte: 'Chaise', couleur: '#3b82f6' },
  banc: { texte: 'Banc', couleur: '#8b5cf6' },
  poteau: { texte: 'Poteau', couleur: '#0891b2' },
  meuble: { texte: 'Meuble', couleur: '#a16207' },
  poubelle: { texte: 'Poubelle', couleur: '#65a30d' },
  personne: { texte: 'Personne', couleur: '#db2777' },
  inconnu: { texte: 'Inconnu', couleur: '#6b7280' },
};
const ORDRE_OBJETS = ['table', 'chaise', 'banc', 'poteau', 'meuble', 'poubelle', 'personne', 'inconnu'];

const ETAPES = [
  { id: 'arret', texte: 'Arrêt du scan et fermeture de l\'enregistrement' },
  { id: 'carte_3d', texte: 'Carte 3D : le nuage de points assemblé' },
  { id: 'carte_2d', texte: 'Carte 2D : la carte de navigation' },
  { id: 'reconnaissance', texte: 'Reconnaissance des murs, des passages et des objets' },
  { id: 'monde', texte: 'Monde : vérification et rapport' },
];
const NOMS_ETAPES = {
  preparation: 'Préparation', enregistrement: 'Enregistrement', arret: 'Arrêt', carte_3d: 'Carte 3D',
  carte_2d: 'Carte 2D', reconnaissance: 'Reconnaissance', monde: 'Monde', fini: 'Fini',
};
const NOMS_ETATS = {
  en_cours: 'Scan en cours', arret_en_cours: 'Arrêt en cours', traitement: 'Traitement', termine: 'Terminé', echec: 'Échec',
};

function categorie(c) {
  return CATEGORIES[c] || CATEGORIES.inconnu;
}

function enc(v) {
  return encodeURIComponent(v);
}

function urlSession(lieu, session, quoi) {
  return '/api/scan/sessions/' + enc(session) + '/' + quoi + '?lieu=' + enc(lieu);
}

function urlScan(quoi, lieu, session) {
  return '/api/scan/' + quoi + '?lieu=' + enc(lieu) + (session ? '&session=' + enc(session) : '');
}

// GET qui rend null au lieu d'une erreur 404 (fichier pas encore écrit)
async function lireOuNull(url) {
  try {
    return await api.lire(url);
  } catch (e) {
    if (e.statut === 404) return null;
    throw e;
  }
}

export function texteDuree(secondes) {
  if (secondes === null || secondes === undefined || isNaN(secondes)) return '—';
  const s = Math.max(0, Math.floor(secondes));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  const deux = (x) => (x < 10 ? '0' : '') + x;
  return h ? h + ' h ' + deux(m) + ' min' : m + ':' + deux(r);
}

function entier(n) {
  return n === null || n === undefined ? '—' : Math.round(n).toLocaleString('fr-FR');
}

function dateCourte(iso) {
  const t = Date.parse(iso);
  if (isNaN(t)) return iso || '—';
  return new Date(t).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function texteMode(s) {
  if (s.mode === 'simu') return 'Simulation';
  return s.repetition ? 'Robot (répétition sans robot)' : 'Robot';
}

function simule(s) {
  return s.mode === 'simu' || !!s.repetition;
}

function dureeSession(s) {
  const debut = Date.parse(s.debut);
  if (isNaN(debut)) return s.statistiques ? s.statistiques.duree_s : null;
  const fin = s.fin ? Date.parse(s.fin) : Date.now();
  return (fin - debut) / 1000;
}

// apercu.png : l'inconnu (gris) devient transparent, les obstacles bleu foncé ; les couleurs
// éventuelles (trajectoire dessinée par g1-scan) sont gardées. Renvoie une adresse data:.
function rendreTransparent(image) {
  const c = document.createElement('canvas');
  c.width = image.naturalWidth;
  c.height = image.naturalHeight;
  const g = c.getContext('2d');
  g.drawImage(image, 0, 0);
  const d = g.getImageData(0, 0, c.width, c.height);
  const p = d.data;
  for (let i = 0; i < p.length; i += 4) {
    const gris = Math.abs(p[i] - p[i + 1]) < 12 && Math.abs(p[i + 1] - p[i + 2]) < 12;
    if (!gris) continue;
    if (p[i] > 150) {
      p[i + 3] = 0;
    } else {
      p[i] = 23;
      p[i + 1] = 63;
      p[i + 2] = 145;
      p[i + 3] = 255;
    }
  }
  g.putImageData(d, 0, 0);
  return c.toDataURL('image/png');
}

function compteur(parent, libelle, role) {
  const b = F.el('div', 'compteur');
  b.appendChild(F.el('span', 'compteur-libelle', libelle));
  const v = F.el('span', 'compteur-valeur', '—');
  v.dataset.role = role;
  b.appendChild(v);
  parent.appendChild(b);
  return v;
}

function liste(parent, classe, lignes) {
  const ul = F.el(classe === 'ol' ? 'ol' : 'ul', 'scan-liste');
  lignes.forEach((l) => {
    const li = F.el('li');
    (Array.isArray(l) ? l : [l]).forEach((morceau) => {
      if (morceau && morceau.code) li.appendChild(F.el('code', 'code', morceau.code));
      else li.appendChild(document.createTextNode(morceau));
    });
    ul.appendChild(li);
  });
  parent.appendChild(ul);
  return ul;
}

export function ouvrir(racine) {
  const lieu = contexte.lieu;
  const etage = contexte.etage;
  const infoEtage = etageCourant();
  const reglages = {
    mode: souvenir('scan.mode') === 'robot' ? 'robot' : 'simu',
    repetition: souvenir('scan.repetition') === '1',
    explorer: souvenir('scan.explorer') === '1',
    nom: '',
  };
  const etat = { suivie: null, ferme: false, minuteur: null, cleHistorique: null, erreurEtat: null };
  let vue = null;      // écran affiché : {id, session, maj(s), fermer(), modifie()}

  racine.innerHTML = `
    <div class="barre">
      <div class="barre-gauche">
        <h2 class="scan-titre" data-role="titre"></h2>
        <span class="etat-action" data-role="statut"></span>
      </div>
    </div>
    <div class="scan-contenu" data-role="contenu"></div>
    <section class="carte-section scan-historique">
      <h2>Scans précédents</h2>
      <div data-role="historique"></div>
    </section>`;
  const $ = (r) => racine.querySelector('[data-role="' + r + '"]');
  $('titre').textContent = 'Scanner l\'étage « ' + (infoEtage ? infoEtage.nom : etage) + ' »';

  // ------------------------------------------------------------ suivi de l'état (chaque seconde)

  function vueDe(s) {
    if (!s) return 'choix';
    if (s.interrompue) return 'interrompu';
    if (s.etat === 'en_cours') return 'direct';
    if (s.etat === 'arret_en_cours' || s.etat === 'traitement') return 'traitement';
    if (s.etat === 'termine') return 'resultat';
    return 'echec';
  }

  function afficherVue(id, s) {
    if (vue) {
      try {
        vue.fermer();
      } catch (e) {
        console.error(e);
      }
    }
    const z = $('contenu');
    z.innerHTML = '';
    z.className = 'scan-contenu scan-vue-' + id;
    vue = VUES[id](z, s);
    vue.id = id;
    vue.session = s ? s.id : null;
  }

  function statut(s) {
    let t = 'Aucun scan en cours.';
    if (s) {
      t = (NOMS_ETATS[s.etat] || s.etat) + ' · ' + s.nom + ' · ' + texteMode(s);
      if (s.interrompue) t = 'Scan interrompu · ' + s.nom;
      if (s.etat === 'traitement') t += ' · ' + s.progression + ' %';
    }
    $('statut').textContent = t;
  }

  function recevoir(e) {
    etat.erreurEtat = null;
    let s = e.session;
    if (!etat.suivie && e.actif && s) etat.suivie = s.id;     // scan lancé ailleurs, ou avant de recharger la page
    if (!etat.suivie || !s || s.id !== etat.suivie) s = null;
    const id = vueDe(s);
    if (!vue || vue.id !== id || vue.session !== (s ? s.id : null)) afficherVue(id, s);
    else vue.maj(s);
    statut(s);
    const cle = s ? s.id + s.etat + (s.adoption ? 'a' : '') : '';
    if (cle !== etat.cleHistorique) {
      etat.cleHistorique = cle;
      majHistorique();
    }
  }

  async function interroger() {
    if (etat.ferme) return;
    try {
      const e = await api.lire(urlScan('etat', lieu, etat.suivie));
      if (!etat.ferme) recevoir(e);
    } catch (err) {
      if (err.statut === 404 && etat.suivie) {
        etat.suivie = null;          // la session a disparu (dossier supprimé)
      } else if (etat.erreurEtat !== err.message) {
        etat.erreurEtat = err.message;
        $('statut').textContent = err.message;
      }
    }
    if (!etat.ferme) etat.minuteur = setTimeout(interroger, PERIODE_ETAT);
  }

  function suivre(session) {
    etat.suivie = session;
    clearTimeout(etat.minuteur);
    interroger();
  }

  // ------------------------------------------------------------ 1. choix du mode, bouton « Scan »

  function vueChoix(z) {
    z.innerHTML = `
      <div class="colonnes scan-choix">
        <section class="carte-section">
          <h2>1. Choisissez le mode</h2>
          <div class="scan-modes" role="radiogroup" aria-label="Mode du scan">
            <button type="button" class="scan-mode" data-mode="simu" role="radio">
              <span class="scan-mode-titre">Simulation</span>
              <span class="scan-mode-texte">Le robot simulé de Gazebo scanne le monde dessiné de l'étage.</span>
            </button>
            <button type="button" class="scan-mode" data-mode="robot" role="radio">
              <span class="scan-mode-titre">Robot</span>
              <span class="scan-mode-texte">Le vrai G1 scanne le bâtiment avec son LiDAR et sa cartographie.</span>
            </button>
          </div>
          <div class="scan-consignes" data-role="consignes"></div>
          <div class="formulaire" data-role="options"></div>
        </section>
        <section class="carte-section scan-lancer">
          <h2>2. Lancez le scan</h2>
          <button type="button" class="bouton-scan" data-role="scan">Scan</button>
          <p class="aide-section">La carte se construit en direct pendant le scan. « Fin » l'arrête : la carte 2D est
            alors fabriquée, et les murs, les passages et les objets sont reconnus.</p>
          <div data-role="prerequis"></div>
        </section>
      </div>`;
    const $v = (r) => z.querySelector('[data-role="' + r + '"]');
    const modes = z.querySelectorAll('.scan-mode');

    function majChoix() {
      const robot = reglages.mode === 'robot';
      const avecSimulation = !robot || reglages.repetition;
      modes.forEach((b) => {
        const choisi = b.dataset.mode === reglages.mode;
        b.classList.toggle('actif', choisi);
        b.setAttribute('aria-checked', choisi ? 'true' : 'false');
      });
      const c = $v('consignes');
      c.innerHTML = '';
      if (robot && !reglages.repetition) {
        F.paragraphe(c, 'Avec le vrai robot :');
        liste(c, 'ol', [
          'Branchez le câble Ethernet entre le PC et le robot (les données du scan ne passent pas par le Wi-Fi).',
          ['Dans un terminal, tapez ', { code: 'source ~/robot-g1/setup/robot.sh' }, ' : il vérifie que le robot répond.'],
          'Posez le robot à son point de départ (l\'accueil), puis cliquez sur « Scan ».',
          'Pilotez le robot à la télécommande, lentement, dans tous les couloirs, en marchant derrière lui avec le PC : le câble doit suivre.',
          'Revenez au point de départ, puis cliquez sur « Fin ».',
        ]);
      } else if (robot) {
        F.paragraphe(c, 'Répétition sans robot : tout se passe comme avec le vrai robot (mêmes commandes de la '
          + 'cartographie, mêmes données enregistrées), mais avec un faux service de cartographie et le robot simulé '
          + 'de Gazebo. Aucun câble n\'est nécessaire.');
      } else {
        F.paragraphe(c, 'Le robot simulé part de son point de départ (onglet Monde) et voit le monde avec son LiDAR, '
          + 'à 1,245 m de haut. Deux façons de le conduire :');
      }
      if (avecSimulation) {
        liste(c, 'ul', [
          'avec les flèches à l\'écran ou au clavier : ↑ ↓ avancer et reculer, ← → tourner, Q et D pas de côté ;',
          'ou cochez « Exploration automatique » : il fait seul le tour des couloirs de l\'onglet Itinéraires, puis le scan se termine tout seul.',
        ]);
      }
      const o = $v('options');
      o.innerHTML = '';
      if (robot) {
        F.caseACocher(o, 'Répétition sans robot (essai complet sur cet ordinateur)', reglages.repetition, (v) => {
          reglages.repetition = v;
          memoriser('scan.repetition', v ? '1' : '0');
          majChoix();
        });
      }
      if (avecSimulation) {
        F.caseACocher(o, 'Exploration automatique (le robot simulé suit seul les couloirs)', reglages.explorer, (v) => {
          reglages.explorer = v;
          memoriser('scan.explorer', v ? '1' : '0');
        });
      }
      F.champTexte(o, 'Nom du scan', reglages.nom, (v) => { reglages.nom = v.trim(); },
        { indice: 'facultatif, ex. Rez-de-chaussée, aile nord' });
      const p = $v('prerequis');
      p.innerHTML = '';
      if (avecSimulation && infoEtage && !infoEtage.a_sdf) {
        const n = F.el('div', 'panneau-alerte', 'Cet étage n\'a pas encore de monde Gazebo : le robot simulé n\'aurait rien à scanner. ');
        p.appendChild(n);
        F.bouton(p, 'Aller à l\'onglet Carte (« Fabriquer la carte »)', () => emettre('aller-ecran', 'carte'));
      }
    }

    modes.forEach((b) => b.addEventListener('click', () => {
      reglages.mode = b.dataset.mode;
      memoriser('scan.mode', reglages.mode);
      majChoix();
    }));
    majChoix();

    const bouton = $v('scan');
    bouton.addEventListener('click', async () => {
      const robotReel = reglages.mode === 'robot' && !reglages.repetition;
      if (robotReel && !window.confirm('Scan avec le vrai robot.\n\n'
        + '• Le câble Ethernet relie-t-il bien le PC au robot ?\n'
        + '• Avez-vous tapé « source ~/robot-g1/setup/robot.sh » dans un terminal ?\n\n'
        + 'Pendant le scan, pilotez le robot à la télécommande en marchant derrière lui avec le PC. Commencer ?')) return;
      const avecSimulation = reglages.mode === 'simu' || reglages.repetition;
      const corps = { lieu: lieu, etage: etage, mode: reglages.mode,
        repetition: reglages.mode === 'robot' && reglages.repetition, explorer: avecSimulation && reglages.explorer };
      if (reglages.nom) corps.nom = reglages.nom;
      bouton.disabled = true;
      bouton.textContent = 'Démarrage…';
      try {
        const e = await api.envoyer('/api/scan/demarrer', corps);
        afficherMessage('Scan démarré : ' + e.session.nom + '.', 'succes');
        etat.suivie = e.session.id;
        recevoir(e);
      } catch (err) {
        afficherErreur(err);
        bouton.disabled = false;
        bouton.textContent = 'Scan';
      }
    });
    return { maj: () => {}, fermer: () => {}, modifie: () => false };
  }

  // ------------------------------------------------------------ 2. pendant le scan : aperçu en direct

  function vueDirect(z, s0) {
    let s = s0;
    z.innerHTML = `
      <div class="scan-direct">
        <div class="scan-compteurs" data-role="compteurs">
          <button type="button" class="bouton-fin" data-role="fin" title="Arrête le scan, puis fabrique la carte">Fin</button>
        </div>
        <p class="scan-message" data-role="message"></p>
        <div class="espace-deux">
          <div class="plan" data-role="plan"></div>
          <div class="cote">
            <div class="vue3d nuage3d" data-role="nuage"></div>
            <div class="panneau" data-role="pilotage"></div>
          </div>
        </div>
      </div>`;
    const $v = (r) => z.querySelector('[data-role="' + r + '"]');
    const zc = $v('compteurs');
    const fin = $v('fin');
    const chrono = compteur(zc, 'Durée', 'chrono');
    const points = compteur(zc, 'Points', 'points');
    const distance = compteur(zc, 'Distance', 'distance');
    const mode = compteur(zc, 'Mode', 'mode');
    zc.appendChild(fin);
    mode.textContent = texteMode(s) + (s.explorer ? ' · exploration' : '');

    const plan = creerPlan($v('plan'));
    // l'aperçu au-dessus du dessin du monde, la trajectoire au-dessus de l'aperçu, le robot tout en haut
    plan.carte.createPane('scanApercu').style.zIndex = 450;
    plan.carte.createPane('scanTrajet').style.zIndex = 460;
    const calqueApercu = L.layerGroup().addTo(plan.carte);
    const calqueDirect = L.layerGroup().addTo(plan.carte);
    let image = null;
    let trajet = null;
    let marqueur = null;
    const nuage = new Nuage3D($v('nuage'));
    let teleop = null;
    let stats = s.statistiques;
    let dernierApercu = null;
    let minuteurApercu = null;
    let cadre = false;
    let ferme = false;

    // pilotage
    const zp = $v('pilotage');
    if (simule(s) && !s.explorer) {
      F.titre(zp, 'Piloter le robot simulé');
      teleop = new Teleop(zp);
      teleop.activer();
      F.paragraphe(zp, 'Au clavier : ↑ ↓ avancer et reculer, ← → tourner, Q et D pas de côté. Le robot s\'arrête dès '
        + 'que vous lâchez.', 'panneau-note');
    } else if (simule(s)) {
      F.titre(zp, 'Exploration automatique');
      F.paragraphe(zp, 'Le robot simulé fait seul le tour des couloirs de l\'onglet Itinéraires. Le scan se termine '
        + 'tout seul à la fin du tour ; « Fin » l\'arrête plus tôt.');
    } else {
      F.titre(zp, 'Piloter le vrai robot');
      F.paragraphe(zp, 'Pilotez le robot à la télécommande, lentement, dans tous les couloirs, en marchant derrière '
        + 'lui avec le PC (le câble Ethernet doit suivre). Revenez au point de départ, puis « Fin ».');
    }

    // fond : en simulation, le monde dessiné de l'étage, dans le même repère que le scan
    if (simule(s)) {
      lireOuNull(urlEtage(lieu, s.etage) + '/monde').then((monde) => {
        if (ferme || !monde) return;
        plan.afficherMondeFond(monde);
        if (!cadre) {
          plan.cadrer(monde.emprise.min[0], monde.emprise.min[1], monde.emprise.max[0], monde.emprise.max[1]);
          cadre = true;
        }
      }).catch(() => {});
    }

    function majCompteurs() {
      chrono.textContent = texteDuree(dureeSession(s));
      points.textContent = entier(stats ? stats.points : null);
      distance.textContent = stats ? nb(stats.distance_m, 1) + ' m' : '—';
    }

    function poserImage(a) {
      const b = a.bornes;
      const limites = [[b.ymin, b.xmin], [b.ymax, b.xmax]];
      const img = new Image();
      img.onload = () => {
        if (ferme) return;
        let url = img.src;
        try {
          url = rendreTransparent(img);
        } catch (e) {
          // canvas indisponible : l'image telle quelle
        }
        if (!image) {
          image = L.imageOverlay(url, limites, { className: 'apercu-image', interactive: false, pane: 'scanApercu' })
            .addTo(calqueApercu);
        }
        else {
          image.setUrl(url);
          image.setBounds(L.latLngBounds(limites));
        }
      };
      img.src = urlScan('apercu.png', lieu, s.id) + '&v=' + enc(a.maj || Date.now());
    }

    async function majApercu() {
      if (ferme) return;
      try {
        const a = await lireOuNull(urlScan('apercu.json', lieu, s.id));
        if (ferme) return;
        if (!a) {
          $v('message').textContent = 'L\'aperçu arrive dans quelques secondes…';
        } else if (a.maj !== dernierApercu) {
          dernierApercu = a.maj;
          if (a.statistiques && (!stats || a.statistiques.duree_s >= stats.duree_s)) stats = a.statistiques;
          majCompteurs();
          if (!cadre && a.bornes) {
            plan.cadrer(a.bornes.xmin, a.bornes.ymin, a.bornes.xmax, a.bornes.ymax);
            cadre = true;
          }
          poserImage(a);
          const pts = (a.trajectoire || []).map((q) => [q[0], q[1]]);
          if (!trajet) {
            trajet = L.polyline(lls(pts), { className: 'trajectoire-scan', interactive: false, pane: 'scanTrajet' })
              .addTo(calqueDirect);
          }
          else trajet.setLatLngs(lls(pts));
          const r = a.robot;
          if (r) {
            const icone = iconeOrientee('robot-direct', r.theta);
            if (!marqueur) marqueur = L.marker(ll(r.x, r.y), { icon: icone, interactive: false, zIndexOffset: 1000 }).addTo(calqueDirect);
            else {
              marqueur.setLatLng(ll(r.x, r.y));
              marqueur.setIcon(icone);
            }
          }
          nuage.afficher(a);
          z.dataset.apercu = a.maj || '';
        }
      } catch (err) {
        $v('message').textContent = 'Aperçu indisponible : ' + err.message;
      }
      if (!ferme) minuteurApercu = setTimeout(majApercu, PERIODE_APERCU);
    }

    fin.addEventListener('click', async () => {
      fin.disabled = true;
      fin.textContent = 'Arrêt…';
      if (teleop) teleop.desactiver();
      $v('message').textContent = 'Arrêt du scan : fermeture de l\'enregistrement (jusqu\'à 30 s)…';
      try {
        const e = await api.envoyer('/api/scan/arreter', { lieu: lieu, session: s.id });
        if (!etat.ferme) recevoir(e);
      } catch (err) {
        afficherErreur(err);
        if (!ferme) {
          fin.disabled = false;
          fin.textContent = 'Fin';
          if (teleop) teleop.activer();
        }
      }
    });

    const minuteurChrono = setInterval(majCompteurs, 1000);
    majCompteurs();
    $v('message').textContent = s.message;
    majApercu();
    return {
      maj: (n) => {
        s = n;
        if (n.statistiques && (!stats || n.statistiques.duree_s > stats.duree_s)) stats = n.statistiques;
        if (!fin.disabled) $v('message').textContent = n.message;
        majCompteurs();
      },
      fermer: () => {
        ferme = true;
        clearInterval(minuteurChrono);
        clearTimeout(minuteurApercu);
        if (teleop) teleop.detruire();
        nuage.detruire();
        plan.detruire();
      },
      modifie: () => false,
    };
  }

  // ------------------------------------------------------------ 3. après « Fin » : le traitement

  function vueTraitement(z, s) {
    z.innerHTML = `
      <section class="carte-section scan-traitement">
        <h2>Fabrication de la carte</h2>
        <div class="progression" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-label="Avancement du traitement">
          <div class="progression-barre" data-role="barre"></div>
        </div>
        <p class="progression-texte"><strong data-role="pourcent"></strong> · <span data-role="etape"></span></p>
        <p class="scan-message" data-role="message"></p>
        <ol class="etapes-scan" data-role="etapes"></ol>
        <p class="panneau-note" data-role="resume"></p>
      </section>`;
    const $v = (r) => z.querySelector('[data-role="' + r + '"]');
    const lignes = ETAPES.map((e) => {
      const li = F.el('li', 'etape-scan', e.texte);
      $v('etapes').appendChild(li);
      return li;
    });

    function maj(n) {
      const p = Math.max(0, Math.min(100, n.progression || 0));
      $v('barre').style.width = p + '%';
      z.querySelector('.progression').setAttribute('aria-valuenow', String(p));
      $v('pourcent').textContent = p + ' %';
      $v('etape').textContent = n.etat === 'arret_en_cours' ? 'Arrêt du scan' : (NOMS_ETAPES[n.etape] || n.etape);
      $v('message').textContent = n.message;
      const rang = ETAPES.findIndex((e) => e.id === n.etape);
      lignes.forEach((li, i) => {
        li.classList.toggle('fait', i < rang);
        li.classList.toggle('en-cours', i === rang);
      });
      const st = n.statistiques || {};
      $v('resume').textContent = 'Enregistrement : ' + texteDuree(st.duree_s) + ', ' + nb(st.distance_m, 1)
        + ' m parcourus, ' + entier(st.points) + ' points (' + texteMode(n) + ').';
    }
    maj(s);
    return { maj: maj, fermer: () => {}, modifie: () => false };
  }

  // ------------------------------------------------------------ 4. le résultat : revue et adoption

  function vueResultat(z, s0) {
    let s = s0;
    z.innerHTML = `
      <div class="scan-resultat">
        <div class="barre">
          <div class="barre-gauche">
            <button type="button" class="bouton bouton-principal" data-role="adopter-carte">Utiliser cette carte pour l'étage</button>
            <button type="button" class="bouton bouton-principal" data-role="adopter-monde">Ouvrir dans l'éditeur du monde</button>
            <button type="button" class="bouton" data-role="nouveau">Nouveau scan</button>
          </div>
          <span class="etat-action" data-role="etat-choix"></span>
        </div>
        <p class="scan-message" data-role="message"></p>
        <div class="espace-deux">
          <div class="plan" data-role="plan"></div>
          <div class="cote">
            <div class="vue3d" data-role="vue3d"></div>
            <div class="panneau" data-role="elements"></div>
          </div>
        </div>
      </div>`;
    const $v = (r) => z.querySelector('[data-role="' + r + '"]');
    const plan = creerPlan($v('plan'));
    const calqueReco = L.layerGroup().addTo(plan.carte);
    const vue3d = new Vue3D($v('vue3d'));
    const couches = {};        // id → couche Leaflet
    const lignes = {};         // id → ligne de la liste
    const elements = {};       // id → élément de la reconnaissance
    const enAttente = {};      // choix pas encore envoyés
    let reco = null;
    let monde = null;
    let choisi = null;
    let minuteurChoix = null;
    let envoi = null;
    let ferme = false;

    function majEntete() {
      let t = s.message;
      if (s.adoption) {
        t += ' Adopté le ' + dateCourte(s.adoption.quand) + (s.adoption.monde ? ' (carte et monde).' : ' (carte seule).');
      }
      $v('message').textContent = t;
    }

    function style(e) {
      const c = categorie(e.categorie).couleur;
      const garde = e.a_garder;
      const base = { color: c, fillColor: c, opacity: garde ? 0.95 : 0.55, fillOpacity: garde ? 0.45 : 0.08,
        dashArray: garde ? null : '5 5', weight: e.categorie === 'passage' ? 6 : 2 };
      if (e.id === choisi) {
        base.weight += 3;
        base.opacity = 1;
      }
      return base;
    }

    function texteElement(e) {
      return categorie(e.categorie).texte + ' · ' + e.id + ' · confiance ' + Math.round(e.confiance * 100) + ' %'
        + (e.a_garder ? '' : ' · retiré');
    }

    function dessiner(e) {
      let c;
      if (e.categorie === 'mur') {
        c = L.polygon(lls(coinsMur(e)), style(e));
      } else if (e.categorie === 'passage') {
        c = L.polyline(lls([e.de, e.a]), style(e));
      } else {
        const f = empreinteObjet({ type: e.forme, centre: e.centre, taille: e.taille, cap: e.cap, rayon: e.rayon });
        c = f.genre === 'cercle' ? L.circle(ll(f.centre[0], f.centre[1]), Object.assign({ radius: f.rayon }, style(e)))
          : L.polygon(lls(f.points), style(e));
      }
      c.options.className = 'reco reco-' + (CATEGORIES[e.categorie] ? e.categorie : 'inconnu');
      c.bindTooltip(F.el('span', '', texteElement(e)), { sticky: true });
      c.on('click', () => choisir(e.id, true));
      c.addTo(calqueReco);
      couches[e.id] = c;
    }

    function restyler(id) {
      const e = elements[id];
      const c = couches[id];
      if (!e || !c) return;
      c.setStyle(style(e));
      c.setTooltipContent(F.el('span', '', texteElement(e)));
      const l = lignes[id];
      if (l) {
        l.classList.toggle('retire', !e.a_garder);
        l.classList.toggle('choisi', id === choisi);
        l.querySelector('input').checked = e.a_garder;
      }
    }

    function choisir(id, depuisPlan) {
      const avant = choisi;
      choisi = choisi === id ? null : id;
      if (avant) restyler(avant);
      if (choisi) restyler(choisi);
      if (monde) vue3d.afficherMonde(monde, choisi, false);
      if (choisi && depuisPlan && lignes[choisi]) {
        const details = lignes[choisi].closest('details');
        if (details) details.open = true;
        lignes[choisi].scrollIntoView({ block: 'nearest' });
      }
    }

    function resume() {
      if (!reco) return 'Pas de reconnaissance pour ce scan : sa carte 2D peut quand même servir.';
      const objets = reco.objets.length;
      const gardes = reco.objets.filter((o) => o.a_garder).length;
      const murs = reco.murs.filter((m) => m.a_garder).length;
      const passages = reco.passages.filter((p) => p.a_garder).length;
      return reco.murs.length + ' murs (' + murs + ' gardés), ' + reco.passages.length + ' passages (' + passages
        + ' gardés), ' + objets + ' objets (' + gardes + ' gardés).';
    }

    function ligneElement(parent, e) {
      const l = F.el('label', 'reco-ligne');
      const c = F.el('input');
      c.type = 'checkbox';
      c.checked = e.a_garder;
      c.title = 'Garder cet élément dans le monde tiré du scan';
      c.dataset.id = e.id;
      c.addEventListener('change', () => changer(e.id, c.checked));
      l.appendChild(c);
      const pastille = F.el('span', 'pastille-categorie');
      pastille.style.background = categorie(e.categorie).couleur;
      l.appendChild(pastille);
      const nom = F.el('span', 'reco-nom', categorie(e.categorie).texte + ' ');
      nom.appendChild(F.el('span', 'reco-id', e.id));
      l.appendChild(nom);
      l.appendChild(F.el('span', 'reco-confiance', Math.round(e.confiance * 100) + ' %'));
      if (e.confiance < CONFIANCE_DOUTEUSE) {
        const b = F.el('span', 'badge badge-douteux', 'douteux');
        b.title = 'Confiance sous 50 % : vérifiez sur le plan avant de le garder';
        l.appendChild(b);
      }
      if (e.categorie === 'personne') {
        const b = F.el('span', 'badge badge-personne', 'jamais sur la carte');
        b.title = 'Une personne n\'est jamais dessinée sur la carte 2D. Gardée, elle est dans le monde 3D.';
        l.appendChild(b);
      }
      l.addEventListener('click', (ev) => {
        if (ev.target !== c) {
          ev.preventDefault();          // un clic sur le nom choisit l'élément sans changer la case
          choisir(e.id, false);
        }
      });
      l.classList.toggle('retire', !e.a_garder);
      parent.appendChild(l);
      lignes[e.id] = l;
    }

    function remplirListe(rapport) {
      const z2 = $v('elements');
      z2.innerHTML = '';
      F.titre(z2, 'Ce qui a été reconnu');
      F.paragraphe(z2, resume()).dataset.role = 'resume';
      if (rapport && rapport.comparaison) {
        F.paragraphe(z2, 'Recouvrement avec la carte actuelle de l\'étage : '
          + nb(rapport.comparaison.recouvrement * 100, 1) + ' %.', 'panneau-note');
      }
      ((rapport && rapport.avertissements) || []).forEach((a) => F.paragraphe(z2, a, 'panneau-alerte'));
      if (!reco) return;
      F.paragraphe(z2, 'Décochez ce qui ne doit pas aller dans le monde. Les personnes sont décochées d\'office ; '
        + 'les éléments douteux (confiance sous 50 %) sont signalés. Cliquez sur un nom pour le voir sur le plan.',
      'panneau-note');
      const legende = F.el('div', 'legende-scan');
      Object.keys(CATEGORIES).forEach((k) => {
        const morceau = F.el('span', 'legende-element');
        const p = F.el('span', 'pastille-categorie');
        p.style.background = CATEGORIES[k].couleur;
        morceau.appendChild(p);
        morceau.appendChild(document.createTextNode(CATEGORIES[k].texte));
        legende.appendChild(morceau);
      });
      z2.appendChild(legende);
      const objets = reco.objets.slice().sort((a, b) => {
        const ia = ORDRE_OBJETS.indexOf(a.categorie);
        const ib = ORDRE_OBJETS.indexOf(b.categorie);
        return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || (a.id < b.id ? -1 : 1);
      });
      const groupe = (titre, liste2, replie) => {
        const d = F.el('details', 'groupe-reco');
        d.open = !replie;
        d.appendChild(F.el('summary', '', titre + ' (' + liste2.length + ')'));
        liste2.forEach((e) => ligneElement(d, e));
        z2.appendChild(d);
        return d;
      };
      groupe('Objets', objets, false).dataset.groupe = 'objets';
      groupe('Passages', reco.passages, false).dataset.groupe = 'passages';
      groupe('Murs', reco.murs, true).dataset.groupe = 'murs';
    }

    function changer(id, garder) {
      elements[id].a_garder = garder;
      enAttente[id] = garder;
      restyler(id);
      const r = $v('elements').querySelector('[data-role=resume]');
      if (r) r.textContent = resume();
      $v('etat-choix').textContent = 'Choix pas encore enregistrés…';
      clearTimeout(minuteurChoix);
      minuteurChoix = setTimeout(envoyerChoix, DELAI_CHOIX);
    }

    function envoyerChoix() {
      minuteurChoix = null;
      const choix = Object.assign({}, enAttente);
      Object.keys(choix).forEach((k) => delete enAttente[k]);
      if (!Object.keys(choix).length) return Promise.resolve();
      $v('etat-choix').textContent = 'Enregistrement des choix…';
      envoi = api.ecrire(urlSession(lieu, s.id, 'reconnaissance'), { a_garder: choix }).then((r) => {
        if (ferme) return;
        monde = r.monde;
        vue3d.afficherMonde(monde, choisi, false);
        $v('etat-choix').textContent = 'Choix enregistrés : le monde du scan est à jour.';
      }).catch((err) => {
        afficherErreur(err);
        // retour à ce que le serveur a gardé
        Object.keys(choix).forEach((k) => {
          elements[k].a_garder = !choix[k];
          restyler(k);
        });
        if (!ferme) $v('etat-choix').textContent = 'Les derniers choix n\'ont pas été enregistrés.';
      }).then(() => {
        envoi = null;
      });
      return envoi;
    }

    async function finirChoix() {
      if (minuteurChoix) {
        clearTimeout(minuteurChoix);
        await envoyerChoix();
      } else if (envoi) {
        await envoi;
      }
    }

    async function adopter(avecMonde) {
      await finirChoix();
      const nomEtage = '« ' + s.etage + ' »';
      let question = avecMonde
        ? 'La carte ET le monde de l\'étage ' + nomEtage + ' vont être remplacés par ceux du scan. L\'ancien monde est '
          + 'gardé dans le dossier du scan. Le monde du scan s\'ouvrira ensuite dans l\'onglet Monde. Continuer ?'
        : 'La carte 2D de l\'étage ' + nomEtage + ' va être remplacée par celle du scan (les objets décochés et les '
          + 'personnes en sont effacés). Le monde dessiné ne change pas. Continuer ?';
      if (s.mode === 'robot') {
        question += '\n\nCe scan vient du vrai robot : son repère n\'est pas celui du monde dessiné. Il faudra replacer '
          + 'les salles, les itinéraires et les zones.';
      }
      if (s.adoption) question = 'Ce scan a déjà été adopté une fois.\n\n' + question;
      if (!window.confirm(question)) return;
      const boutons = [$v('adopter-carte'), $v('adopter-monde')];
      boutons.forEach((b) => { b.disabled = true; });
      $v('etat-choix').textContent = 'Adoption en cours…';
      try {
        const r = await api.envoyer(urlSession(lieu, s.id, 'adopter'), { monde: avecMonde });
        afficherMessage(avecMonde ? 'Carte et monde du scan adoptés pour l\'étage ' + nomEtage + '.'
          : 'Carte du scan adoptée pour l\'étage ' + nomEtage + ' : voyez-la dans l\'onglet Carte.', 'succes', [], r.sortie);
        (r.avertissements || []).forEach((a) => afficherMessage(a, 'avertissement'));
        afficherRapport(r.rapport);
        await rechargerLieu();
        if (avecMonde) {
          if (contexte.etage !== s.etage) choisirEtage(s.etage);
          emettre('aller-ecran', 'monde');
          return;
        }
        $v('etat-choix').textContent = 'Carte adoptée.';
      } catch (err) {
        afficherErreur(err);
        if (!ferme) $v('etat-choix').textContent = 'L\'adoption a échoué : voyez le message.';
      } finally {
        if (!ferme) {
          boutons[0].disabled = false;
          boutons[1].disabled = !monde;
        }
      }
    }

    $v('adopter-carte').addEventListener('click', () => adopter(false));
    $v('adopter-monde').addEventListener('click', () => adopter(true));
    $v('nouveau').addEventListener('click', () => {
      etat.suivie = null;
      afficherVue('choix', null);
      statut(null);
    });

    async function charger() {
      z.classList.add('chargement');
      try {
        const reponses = await Promise.all([
          api.lire(urlSession(lieu, s.id, 'carte.yaml')),
          lireOuNull(urlSession(lieu, s.id, 'reconnaissance')),
          lireOuNull(urlSession(lieu, s.id, 'monde')),
          lireOuNull(urlSession(lieu, s.id, 'rapport')),
        ]);
        if (ferme) return;
        const info = reponses[0];
        reco = reponses[1] ? reponses[1].reconnaissance : null;
        monde = reponses[2];
        const b = info.bornes;
        L.imageOverlay(urlSession(lieu, s.id, 'carte.png') + '&v=' + Date.now(), [[b.ymin, b.xmin], [b.ymax, b.xmax]],
          { className: 'plan-image-carte', interactive: false }).addTo(plan.calques.fond);
        plan.cadrer(b.xmin, b.ymin, b.xmax, b.ymax);
        if (reco) {
          ['murs', 'passages', 'objets'].forEach((cle) => reco[cle].forEach((e) => {
            elements[e.id] = e;
            dessiner(e);
          }));
        }
        remplirListe(reponses[3]);
        if (monde) {
          vue3d.afficherMonde(monde, null, false);
          vue3d.cadrer(monde.emprise);
        }
        $v('adopter-monde').disabled = !monde;
        if (!monde) $v('adopter-monde').title = 'Ce scan n\'a pas de monde (la reconnaissance a échoué) : seule sa carte peut servir.';
      } catch (err) {
        afficherErreur(err);
      } finally {
        z.classList.remove('chargement');
      }
    }

    majEntete();
    charger();
    return {
      maj: (n) => {
        s = n;
        majEntete();
      },
      fermer: () => {
        if (minuteurChoix) {
          clearTimeout(minuteurChoix);
          envoyerChoix();          // les derniers choix partent quand même
        }
        ferme = true;
        vue3d.detruire();
        plan.detruire();
      },
      modifie: () => Object.keys(enAttente).length > 0,
    };
  }

  // ------------------------------------------------------------ échec, scan interrompu

  function boutonNouveau(parent) {
    F.bouton(parent, 'Nouveau scan', () => {
      etat.suivie = null;
      afficherVue('choix', null);
      statut(null);
    }, 'bouton bouton-principal');
  }

  function vueEchec(z, s) {
    const sec = F.el('section', 'carte-section scan-echec');
    sec.appendChild(F.el('h2', '', 'Le scan a échoué'));
    const m = F.paragraphe(sec, s.message, 'panneau-alerte');
    F.paragraphe(sec, 'Étape : ' + (NOMS_ETAPES[s.etape] || s.etape) + '. ' + texteMode(s) + ', commencé le '
      + dateCourte(s.debut) + '.', 'panneau-note');
    if (s.journal) F.paragraphe(sec, 'Journal du scan : ' + s.journal, 'panneau-note code');
    boutonNouveau(sec);
    z.appendChild(sec);
    return { maj: (n) => { m.textContent = n.message; }, fermer: () => {}, modifie: () => false };
  }

  function vueInterrompu(z, s) {
    const sec = F.el('section', 'carte-section scan-echec');
    sec.appendChild(F.el('h2', '', 'Le scan s\'est arrêté sans prévenir'));
    F.paragraphe(sec, 'Le programme du scan « ' + s.nom + ' » ne tourne plus (ordinateur redémarré, commande '
      + 'arrêtée…). « Terminer ce scan » le clôt : s\'il a été enregistré, la carte est fabriquée ; sinon il passe '
      + 'en échec, et il faut recommencer.');
    if (s.journal) F.paragraphe(sec, 'Journal du scan : ' + s.journal, 'panneau-note code');
    const b = F.bouton(sec, 'Terminer ce scan', async () => {
      b.disabled = true;
      try {
        recevoir(await api.envoyer('/api/scan/arreter', { lieu: lieu, session: s.id }));
      } catch (err) {
        afficherErreur(err);
        b.disabled = false;
      }
    }, 'bouton bouton-principal');
    boutonNouveau(sec);
    z.appendChild(sec);
    return { maj: () => {}, fermer: () => {}, modifie: () => false };
  }

  const VUES = { choix: vueChoix, direct: vueDirect, traitement: vueTraitement, resultat: vueResultat,
    echec: vueEchec, interrompu: vueInterrompu };

  // ------------------------------------------------------------ scans précédents

  async function majHistorique() {
    let sessions;
    try {
      sessions = await api.lire('/api/scan/sessions?lieu=' + enc(lieu));
    } catch (e) {
      return;
    }
    if (etat.ferme) return;
    const z = $('historique');
    z.innerHTML = '';
    if (!sessions.length) {
      z.appendChild(F.el('p', 'vide', 'Aucun scan pour ce lieu pour l\'instant.'));
      return;
    }
    const table = F.el('table', 'tableau scan-sessions');
    const tete = F.el('tr');
    ['Scan', 'Étage', 'Mode', 'État', 'Durée', 'Distance', ''].forEach((t) => tete.appendChild(F.el('th', '', t)));
    table.appendChild(tete);
    sessions.forEach((s) => {
      const tr = F.el('tr', s.id === etat.suivie ? 'session-suivie' : '');
      tr.dataset.session = s.id;
      if (s.illisible) {
        tr.appendChild(F.el('td', '', s.id));
        const td = F.el('td', 'non', 'Fichier session.json illisible : ce scan ne peut plus servir.');
        td.colSpan = 6;
        tr.appendChild(td);
        table.appendChild(tr);
        return;
      }
      const nom = F.el('td');
      nom.appendChild(F.el('div', '', s.nom));
      nom.appendChild(F.el('div', 'lieu-id', dateCourte(s.debut)));
      tr.appendChild(nom);
      tr.appendChild(F.el('td', '', s.etage));
      tr.appendChild(F.el('td', '', texteMode(s) + (s.explorer ? ', exploration' : '')));
      let texte = s.interrompue ? 'Interrompu' : (NOMS_ETATS[s.etat] || s.etat);
      if (s.etat === 'traitement') texte += ' (' + s.progression + ' %)';
      if (s.adoption) texte += s.adoption.monde ? ' · adopté avec le monde' : ' · carte adoptée';
      tr.appendChild(F.el('td', 'etat-session etat-' + s.etat + (s.interrompue ? ' etat-interrompu' : ''), texte));
      const actif = s.etat === 'en_cours' && !s.interrompue;      // chiffres en direct : dans l'aperçu
      tr.appendChild(F.el('td', '', actif ? '…' : texteDuree(s.statistiques.duree_s)));
      tr.appendChild(F.el('td', '', actif ? '…' : nb(s.statistiques.distance_m, 1) + ' m'));
      const action = F.el('td');
      if (s.id !== etat.suivie) F.bouton(action, 'Voir', () => suivre(s.id), 'bouton-lien');
      else action.appendChild(F.el('span', 'lieu-id', 'affiché'));
      tr.appendChild(action);
      table.appendChild(tr);
    });
    z.appendChild(table);
  }

  interroger();
  return {
    modifie: () => !!(vue && vue.modifie()),
    fermer: () => {
      etat.ferme = true;
      clearTimeout(etat.minuteur);
      if (vue) vue.fermer();
    },
  };
}
