// Liaison de la borne avec l'Atelier (vague 6, section 13.5 du plan) : l'état par le WebSocket /ws/borne
// (4 fois par seconde), et, quand il est coupé, GET /api/borne/etat toutes les 0,5 s ; les demandes (appui,
// choix, code opérateur) par POST, avec l'en-tête X-Jeton-Borne en mode opérateur. Anti-rebond des appuis :
// deux appuis à moins de 0,6 s comptent pour un (ANTI_REBOND_MS, comme le serveur). Agent Borne et orchestrateur.

export const ANTI_REBOND_MS = 600;
export const PERIODE_SECOURS_MS = 500;
export const ENTETE_JETON = 'X-Jeton-Borne';
const RECONNEXION_MS = 1500;
const ECHECS_AVANT_PERTE = 4;

// permis(cle) : vrai au premier appui, faux pour un autre appui de même clé moins de delaiMs après
// (une clé vide : tous les appuis comptent ensemble). horloge : millisecondes (Date.now par défaut).
export function creerAntiRebond(delaiMs, horloge) {
  const maintenant = horloge || (() => Date.now());
  const derniers = {};
  return function permis(cle) {
    const k = cle || '';
    const t = maintenant();
    if (derniers[k] !== undefined && t - derniers[k] < delaiMs) return false;
    derniers[k] = t;
    return true;
  };
}

// Adresse du WebSocket de la borne, sur la même machine que la page
export function adresseWs(loc, jeton) {
  const base = (loc.protocol === 'https:' ? 'wss://' : 'ws://') + loc.host + '/ws/borne';
  return jeton ? base + '?jeton=' + encodeURIComponent(jeton) : base;
}

// options : {surEtat(etat), surConnexion(vrai|faux)} → {envoyer(chemin, corps), changerJeton(j), arreter()}
export function creerLiaison(options) {
  let ws = null;
  let jeton = null;
  let fini = false;
  let echecs = 0;
  let connecte = null;
  let attenteReconnexion = null;

  function signaler(ok) {
    if (ok) echecs = 0;
    else echecs += 1;
    const etat = ok || echecs < ECHECS_AVANT_PERTE;
    if (etat !== connecte) {
      connecte = etat;
      if (options.surConnexion) options.surConnexion(etat);
    }
  }

  function recevoir(texte) {
    let etat = null;
    try {
      etat = JSON.parse(texte);
    } catch (e) {
      return;
    }
    if (etat && etat.ecran) {
      signaler(true);
      options.surEtat(etat);
    }
  }

  function ouvrir() {
    if (fini || ws) return;
    try {
      ws = new WebSocket(adresseWs(window.location, jeton));
    } catch (e) {
      ws = null;
      prevoir();
      return;
    }
    ws.onmessage = (e) => recevoir(e.data);
    ws.onclose = () => {
      ws = null;
      prevoir();
    };
    ws.onerror = () => {
      if (ws) ws.close();
    };
  }

  function prevoir() {
    if (fini || attenteReconnexion) return;
    attenteReconnexion = setTimeout(() => {
      attenteReconnexion = null;
      ouvrir();
    }, RECONNEXION_MS);
  }

  // Secours : GET /api/borne/etat quand le WebSocket n'est pas ouvert
  const secours = setInterval(() => {
    if (fini || (ws && ws.readyState === 1)) return;
    const entetes = jeton ? { [ENTETE_JETON]: jeton } : {};
    fetch('/api/borne/etat', { headers: entetes, cache: 'no-store' })
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
      .then(recevoir)
      .catch(() => signaler(false));
  }, PERIODE_SECOURS_MS);

  async function envoyer(chemin, corps) {
    const entetes = { 'Content-Type': 'application/json' };
    if (jeton) entetes[ENTETE_JETON] = jeton;
    let reponse;
    try {
      reponse = await fetch(chemin, { method: 'POST', headers: entetes, body: JSON.stringify(corps || {}) });
    } catch (e) {
      return { statut: 0, donnees: null };
    }
    let donnees = null;
    try {
      donnees = await reponse.json();
    } catch (e) {
      donnees = null;
    }
    return { statut: reponse.status, donnees: donnees };
  }

  ouvrir();
  return {
    envoyer: envoyer,
    changerJeton: (j) => {
      jeton = j || null;
      if (ws) ws.close();     // rouvert avec le jeton (mode opérateur dans l'état)
    },
    arreter: () => {
      fini = true;
      clearInterval(secours);
      if (attenteReconnexion) clearTimeout(attenteReconnexion);
      if (ws) ws.close();
    },
  };
}
