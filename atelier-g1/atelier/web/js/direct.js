// Liaison en direct avec le serveur : WebSocket /ws/etat, environ 10 messages par seconde
// {robot, guide, pietons, processus, simulation, ros}. Reconnexion automatique.

let ws = null;
let dernier = null;
let connecte = false;
const abonnes = new Set();
const surConnexion = new Set();

function adresse() {
  return (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws/etat';
}

function changerConnexion(etat) {
  if (etat === connecte) return;
  connecte = etat;
  surConnexion.forEach((f) => f(connecte));
}

export function connecter() {
  if (ws) return;
  try {
    ws = new WebSocket(adresse());
  } catch (e) {
    ws = null;
    setTimeout(connecter, 2000);
    return;
  }
  ws.onopen = () => changerConnexion(true);
  ws.onmessage = (e) => {
    try {
      dernier = JSON.parse(e.data);
    } catch (err) {
      return;
    }
    abonnes.forEach((f) => f(dernier));
  };
  ws.onclose = () => {
    ws = null;
    changerConnexion(false);
    setTimeout(connecter, 2000);
  };
  ws.onerror = () => {
    if (ws) ws.close();
  };
}

// f(etat) à chaque message ; renvoie la fonction qui désabonne
export function abonner(f) {
  abonnes.add(f);
  if (dernier) f(dernier);
  connecter();
  return () => abonnes.delete(f);
}

export function suivreConnexion(f) {
  surConnexion.add(f);
  f(connecte);
}

export function dernierEtat() {
  return dernier;
}
