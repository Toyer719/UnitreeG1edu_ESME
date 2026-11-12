// Annuler et refaire : on garde des copies de l'état avant chaque modification.

export class Historique {
  constructor(limite) {
    this.limite = limite || 200;
    this.passe = [];
    this.futur = [];
  }

  // À appeler juste AVANT une modification, avec l'état actuel
  noter(etat) {
    this.passe.push(JSON.stringify(etat));
    if (this.passe.length > this.limite) this.passe.shift();
    this.futur = [];
  }

  // Renvoie l'état précédent (ou null), en gardant l'état actuel pour « refaire »
  annuler(actuel) {
    if (!this.passe.length) return null;
    this.futur.push(JSON.stringify(actuel));
    return JSON.parse(this.passe.pop());
  }

  refaire(actuel) {
    if (!this.futur.length) return null;
    this.passe.push(JSON.stringify(actuel));
    return JSON.parse(this.futur.pop());
  }

  get peutAnnuler() {
    return this.passe.length > 0;
  }

  get peutRefaire() {
    return this.futur.length > 0;
  }

  vider() {
    this.passe = [];
    this.futur = [];
  }
}
