// Réglages de la voix du robot (vague 6, section 13.6 du plan) : sortie, voix, volume, vitesse, « Essayer ».
//
// Composant écrit par l'agent Voix, mis en place par l'assemblage de la vague 6 (13.13) : l'écran Démo le monte dans
// Équipe › Démo › ⚙ Réglages de la démo (js/ecrans/demo.js), à la place des champs de la voix de demo.yaml :
//   const voix = monterReglagesVoix(zone, { lieu, valeurs: demo.voix, surChange: (v) => { demo.voix = v; } });
//   …   voix.fermer();            // à la fermeture de l'écran (arrête la relecture de l'état)
// Il ne se sert que des routes de la voix (13.8) : GET /api/voix/etat (relu chaque seconde),
// POST /api/voix/demarrer, /arreter, /essayer, /commande, et GET /api/voix/son/<id> (écouter sur ce PC).
// Repères des tests : [data-role=voix-reglages], [data-role=voix-etat] (data-etat : arrete, attente, parle,
// muet), [data-role=voix-demarrer], [data-role=voix-arreter], [data-role=voix-essai] (le texte),
// [data-role=voix-essayer], [data-role=voix-ecouter] (<audio>). Aucune donnée insérée en HTML (textContent).
import { api } from '../api.js';
import { bouton, champNombre, champTexte, el, listeDeroulante, paragraphe } from '../formulaire.js';

export const TEXTE_ESSAI = "Bonjour ! Je suis le robot d'accueil. Suivez-moi !";
export const PERIODE_ETAT_MS = 1000;
export const REGLAGES_DEFAUT = { sortie: 'robot', nom: 'fr_FR-siwis-medium', volume: 70, vitesse: 1.0 };
// Les sorties de la voix (corrections de la vague 6 : le panneau est étroit, « Haut-parleur du robot (voix du PC) » se
// lisait « Haut-parleur du ») : un nom court dans la liste, et une phrase sous la liste qui dit la différence
export const SORTIES_VOIX = [
  { id: 'robot', texte: 'Haut-parleur du robot', aide: 'La voix est fabriquée sur ce PC, puis jouée par le haut-parleur du robot.' },
  { id: 'borne', texte: 'Borne (tablette ou téléphone)', aide: 'Le son est joué par la tablette ou le téléphone de la borne.' },
  { id: 'robot_tts', texte: 'Synthèse du robot', aide: 'La voix intégrée du robot : son français est à vérifier avec le robot.' },
];

// La phrase d'aide d'une sortie (SORTIES_VOIX)
export function aideSortie(id) {
  const s = SORTIES_VOIX.find((x) => x.id === id);
  return s ? s.aide : '';
}

// Les réglages de la voix (champ voix de demo.yaml) complétés par les défauts, bornés comme le schéma demo.
export function reglagesVoix(voix) {
  const v = Object.assign({}, REGLAGES_DEFAUT, voix || {});
  const volume = Math.round(Number(v.volume));
  const vitesse = Number(v.vitesse);
  return {
    sortie: ['robot', 'borne', 'robot_tts'].indexOf(v.sortie) >= 0 ? v.sortie : REGLAGES_DEFAUT.sortie,
    nom: typeof v.nom === 'string' && v.nom ? v.nom : REGLAGES_DEFAUT.nom,
    volume: isFinite(volume) ? Math.min(100, Math.max(0, volume)) : REGLAGES_DEFAUT.volume,
    vitesse: isFinite(vitesse) ? Math.min(2, Math.max(0.5, vitesse)) : REGLAGES_DEFAUT.vitesse,
  };
}

// L'état de la voix en une phrase simple et un genre (arrete, attente, parle, muet), d'après GET /api/voix/etat.
export function resumeEtatVoix(reponse) {
  if (!reponse || !reponse.tourne || !reponse.etat) {
    return { genre: 'arrete', texte: 'La voix du robot ne tourne pas : cliquez sur « Démarrer la voix ».' };
  }
  const e = reponse.etat;
  const robot = e.robot || {};
  if ((e.sortie === 'robot' || e.sortie === 'robot_tts') && (!robot.abonne || robot.repond === false)) {
    return { genre: 'muet', texte: "Le haut-parleur du robot ne répond pas : le robot est-il relié et allumé ?" };
  }
  if (e.en_cours) {
    return { genre: 'parle', texte: 'Le robot dit : « ' + e.en_cours.texte + ' »' };
  }
  const dites = e.dites || 0;
  return { genre: 'attente', texte: 'La voix est prête (' + dites + (dites > 1 ? ' phrases dites).' : ' phrase dite).') };
}

// Monte les réglages dans zone. options : {lieu, valeurs, surChange(valeurs), message(texte, genre)}.
// Rend {valeurs(), rafraichir(), fermer()}.
export function monterReglagesVoix(zone, options) {
  options = options || {};
  let valeurs = reglagesVoix(options.valeurs);
  let dernier = null;
  let minuterie = null;
  const message = options.message || (() => {});
  const racine = el('div', 'voix-reglages');
  racine.setAttribute('data-role', 'voix-reglages');
  zone.appendChild(racine);

  const ligneEtat = paragraphe(racine, 'La voix du robot : lecture de son état…');
  ligneEtat.setAttribute('data-role', 'voix-etat');
  ligneEtat.setAttribute('data-etat', 'arrete');

  function changer(champ, v) {
    valeurs = reglagesVoix(Object.assign({}, valeurs, { [champ]: v }));
    if (options.surChange) options.surChange(Object.assign({}, valeurs));
    if (dernier && dernier.tourne) {
      const commandes = { sortie: { action: 'sortie', sortie: valeurs.sortie }, nom: { action: 'voix', voix: valeurs.nom },
        volume: { action: 'volume', volume: valeurs.volume } };
      if (commandes[champ]) {
        api.envoyer('/api/voix/commande', commandes[champ]).catch((e) => message(e.message, 'erreur'));
      }
    }
  }

  const choixSorties = SORTIES_VOIX.map((x) => ({ id: x.id, texte: x.texte }));
  const choixVoix = [{ id: 'fr_FR-siwis-medium', texte: 'Siwis (voix de femme)' }, { id: 'fr_FR-tom-medium', texte: "Tom (voix d'homme)" }];
  const sortie = listeDeroulante(racine, 'Le robot parle par', valeurs.sortie, choixSorties, (v) => {
    changer('sortie', v);
    aide.textContent = aideSortie(valeurs.sortie);
  });
  const aide = paragraphe(racine, aideSortie(valeurs.sortie), 'panneau-note voix-sortie-aide');
  aide.setAttribute('data-role', 'voix-sortie-aide');
  const voix = listeDeroulante(racine, 'Voix', valeurs.nom, choixVoix, (v) => changer('nom', v));
  champNombre(racine, 'Volume', valeurs.volume, { pas: 5, min: 0, max: 100, unite: '%', decimales: 0 },
    (v) => changer('volume', v));
  champNombre(racine, 'Vitesse', valeurs.vitesse, { pas: 0.05, min: 0.5, max: 2, decimales: 2 }, (v) => changer('vitesse', v));

  const boutons = el('div', 'voix-boutons');
  racine.appendChild(boutons);
  const demarrer = bouton(boutons, 'Démarrer la voix', async () => {
    try {
      const r = await api.envoyer('/api/voix/demarrer', { lieu: options.lieu, sortie: valeurs.sortie, volume: valeurs.volume,
        voix: valeurs.nom, vitesse: valeurs.vitesse });
      message(r.avertissement || r.detail, r.avertissement ? 'avertissement' : 'succes');
    } catch (e) {
      message(e.message, 'erreur');
    }
    rafraichir();
  });
  demarrer.setAttribute('data-role', 'voix-demarrer');
  const arreter = bouton(boutons, 'Arrêter la voix', async () => {
    try {
      message((await api.envoyer('/api/voix/arreter')).detail, 'info');
    } catch (e) {
      message(e.message, 'erreur');
    }
    rafraichir();
  });
  arreter.setAttribute('data-role', 'voix-arreter');

  const essai = champTexte(racine, 'Phrase à essayer', TEXTE_ESSAI, () => {}, { lignes: 2 });
  essai.setAttribute('data-role', 'voix-essai');
  const ecouter = el('audio');
  ecouter.setAttribute('data-role', 'voix-ecouter');
  ecouter.preload = 'none';
  const essayer = bouton(racine, 'Essayer', async () => {
    try {
      const r = await api.envoyer('/api/voix/essayer', { texte: essai.value || TEXTE_ESSAI,
        voix: { nom: valeurs.nom, vitesse: valeurs.vitesse } });
      message(r.detail, 'succes');
      // la même phrase, écoutée sur ce PC quand son WAV est prêt (sorties robot et borne)
      if (valeurs.sortie !== 'robot_tts') {
        setTimeout(() => {
          ecouter.src = r.url;
          ecouter.play().catch(() => {});
        }, 800);
      }
    } catch (e) {
      message(e.message, 'erreur');
    }
  });
  essayer.setAttribute('data-role', 'voix-essayer');
  racine.appendChild(ecouter);

  async function rafraichir() {
    try {
      dernier = await api.lire('/api/voix/etat');
    } catch (e) {
      dernier = null;
    }
    const resume = resumeEtatVoix(dernier);
    ligneEtat.textContent = resume.texte;
    ligneEtat.setAttribute('data-etat', resume.genre);
    demarrer.disabled = !options.lieu;
    arreter.disabled = !(dernier && dernier.lancee);
    essayer.disabled = !(dernier && dernier.tourne);
    if (dernier && Array.isArray(dernier.voix)) {
      Array.from(voix.options).forEach((o) => {
        const v = dernier.voix.find((x) => x.id === o.value);
        o.disabled = !!(v && !v.presente);
      });
    }
    sortie.title = valeurs.sortie === 'robot_tts' ? 'Le français de la synthèse du robot est à vérifier avec le robot.' : '';
  }

  rafraichir();
  minuterie = setInterval(rafraichir, PERIODE_ETAT_MS);
  return {
    valeurs: () => Object.assign({}, valeurs),
    rafraichir: rafraichir,
    fermer: () => {
      if (minuterie) clearInterval(minuterie);
      minuterie = null;
      ecouter.pause();
      racine.remove();
    },
  };
}
