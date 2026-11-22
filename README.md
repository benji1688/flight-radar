# ✈️ Flight Radar

Veille automatique des prix de vols, 100 % gratuite, pilotée depuis Telegram.

- **Sur l'iPhone** : tu crées et gères tes alertes en écrivant au bot, et tu reçois les notifs.
- **Sur GitHub** : toutes les heures, le moteur cherche les prix (Aviasales pour balayer large, Google Flights pour confirmer), dans plusieurs pays de vente, et apprend lesquels battent la France.
- **Sur Cloudflare** : un petit relais gratuit répond tout de suite au bot et garde tes alertes et l'historique des prix.

## Installation (une seule fois, environ 15 minutes)

> Sur iPhone, certaines pages GitHub et Cloudflare s'affichent mieux en version ordinateur : dans Safari, touche **aA** puis **Demander le site pour ordinateur**.

### 1. Récupérer les clés

| Clé | Où la trouver |
|---|---|
| **Token Telegram** | Dans Telegram, écris à **@BotFather**, tape `/newbot`, choisis un nom puis un identifiant finissant par `bot`. Il te renvoie le token (`123456:ABC…`). |
| **Token Travelpayouts** | Crée un compte sur travelpayouts.com, rejoins le programme **Aviasales**, puis copie ton token dans la rubrique API de ton espace (emplacement exact à vérifier, il peut changer). |
| **Token Cloudflare** | Sur dash.cloudflare.com : icône de profil → **My Profile** → **API Tokens** → **Create Token** → modèle **Edit Cloudflare Workers** → **Use template** → choisis ton compte → **Continue to summary** → **Create Token**. |
| **Account ID Cloudflare** | C'est la suite de 32 caractères dans l'adresse du tableau de bord : `dash.cloudflare.com/`**`ce-code-là`**`/…` |
| **API_KEY** | Un mot de passe que tu inventes (au moins 20 caractères, lettres et chiffres). Il protège la liaison entre GitHub et le relais. L'app **Mots de passe** de l'iPhone peut en générer un. |

### 2. Les coller dans GitHub

Dans le dépôt : **Settings** → **Secrets and variables** → **Actions** → **New repository secret**, une fois par clé, avec exactement ces noms :

| Nom du secret | Valeur |
|---|---|
| `TELEGRAM_BOT_TOKEN` | token Telegram |
| `TRAVELPAYOUTS_TOKEN` | token Travelpayouts |
| `CLOUDFLARE_API_TOKEN` | token Cloudflare |
| `CLOUDFLARE_ACCOUNT_ID` | Account ID Cloudflare |
| `API_KEY` | ton mot de passe inventé |

Les secrets sont chiffrés : personne ne peut les relire, même toi (tu peux seulement les remplacer).

### 3. Mettre le bot en ligne

Onglet **Actions** → **Déployer le bot** → **Run workflow**. Au bout de 2 minutes environ, une coche verte apparaît.

Si ça échoue en parlant de *workers.dev subdomain* : ouvre une fois **Workers & Pages** dans le tableau de bord Cloudflare, choisis un sous-domaine, puis relance.

### 4. Prendre possession du bot

Dans Telegram, ouvre ton bot et écris **`/start`**. Le premier compte qui lui écrit en devient le propriétaire : les autres sont ignorés.

### 5. Créer ta première alerte et tester

```
/alerte de lyon vers BCN,LIS weekends mars,avril max 80
```

Pour ne pas attendre le passage automatique : **Actions** → **Chercher les prix** → **Run workflow**.

## Utilisation

Tape `/aide` dans le bot pour le mode d'emploi complet.

| Commande | Effet |
|---|---|
| `/alerte de LYS,GVA vers BCN du 01/03 au 31/03 nuits 2-4 max 80` | dates précises, plusieurs départs et destinations |
| `/alerte de lyon vers partout weekends mars max 60` | les week-ends les moins chers, toutes destinations |
| `/alerte de LYS vers OPO en mai aller-simple depart 6-12 direct prio` | aller simple, créneau de départ, sans escale, vérifié à chaque passage |
| `/liste`, `/voir a1` | alertes, meilleur prix, top 5, historique |
| `/pause a1`, `/reprise a1` | arrêter / relancer les recherches |
| `/notif a1 off`, `/notif a1 on` | couper / remettre les notifs (le suivi continue) |
| `/prio a1`, `/suppr a1` | vérification à chaque passage, suppression |
| `/pays` | pays de vente qui battent le plus souvent la France |
| `/reglages frais 2 gain 15 baisse 5 silence 23-7 pays 3` | frais de change de ta carte, gain minimum pour proposer un autre pays, baisse qui déclenche une nouvelle notif, heures de notifs silencieuses, nombre de pays testés |
| `/statut` | dernier passage du moteur, erreurs éventuelles |

**Mots compris dans `/alerte`** : `de`, `vers` (ou `partout`), `du … au …`, `en mars`, `weekends mars,avril`, `nuits 2-4`, `max 80`, `direct`, `aller-simple`, `prio`. Villes connues : lyon, geneve, paris, londres, milan… sinon le code aéroport à 3 lettres.

**Horaires et jours** :
- même créneau tous les jours : `depart 6-12`, `retour 17-23` ;
- créneau par jour : `depart jeu apres 18, ven apres 12` · `retour sam, dim, lun avant 6` (`apres 18` = 18 h-minuit, `avant 6` = minuit-6 h, ou `18-23`) ;
- dates précises : `aller 30/12 ou 31/12 retour 02/01 ou 03/01`.

Exemples :
```
/alerte de lyon vers partout en decembre,janvier depart jeu apres 18, ven apres 12 retour sam, dim, lun avant 6 max 100
/alerte de lyon vers partout aller 30/12 ou 31/12 retour 02/01 ou 03/01
```

**Week-end** = départ jeudi, vendredi ou samedi et retour samedi, dimanche ou lundi (1 à 3 nuits par défaut, modifiable avec `nuits`).

## Comment ça marche

1. **Aller et retour sont cherchés séparément** (deux allers simples) : c'est ce qui permet un créneau différent selon le jour, l'heure exacte du retour, et de combiner deux compagnies. Les prix affichés sont donc ceux de deux billets séparés, souvent la formule la moins chère en low-cost (une compagnie classique peut être moins chère en aller-retour sur un seul billet).
2. **Aviasales** (cache gratuit, prix vus ces 2 à 7 derniers jours) repère les destinations et dates prometteuses, toutes les 6 h. Pour « partout », le moteur y ajoute une liste de grands aéroports européens et méditerranéens (`checker/destinations.py`).
3. **Google Flights** vérifie trajet par trajet le prix réel du moment. Chaque prix est mémorisé : à chaque passage, le moteur complète les trajets manquants (destinations repérées d'abord), rafraîchit ceux des meilleures combinaisons et abandonne les destinations dont l'aller dépasse déjà ton prix max. Une alerte « partout » sur deux mois se remplit donc en quelques passages : `/voir` indique combien de trajets ont déjà été vérifiés.
4. **Classement des pays** : au départ, ordre par défaut (pays de la destination, puis Pologne, Hongrie, Turquie, Inde, Brésil, Mexique…). Ensuite, le moteur retient quels pays ont battu la France sur chaque route et les teste en priorité. Une fois par semaine et par alerte, il refait un tour complet de tous les pays.
5. **Notifs** : un message regroupe les bons plans, une ligne par destination : la première fois qu'elle passe sous ton prix max, puis à chaque nouvelle baisse d'au moins 5 % (réglable). Seuls les prix vérifiés sur Google sont annoncés (les estimations Aviasales restent visibles dans `/voir`). Un autre pays de vente n'est retenu pour un trajet que s'il fait gagner au moins la moitié du « gain minimum » (15 € par défaut, réglable).

Alertes normales : vérifiées toutes les 3 h. Alertes `prio` : à chaque passage (toutes les heures).

## Limites à connaître

- **Google Flights n'a pas d'API officielle.** Le moteur utilise la bibliothèque open source `faster-flights`, prévue pour un usage perso. Si Google change son site, il faudra mettre à jour la version dans `checker/requirements.txt` (le bot te prévient). Le moteur se limite à 80 requêtes Google par passage pour éviter les blocages (variable `GOOGLE_MAX_REQUESTS` dans Settings → Variables).
- **Les serveurs GitHub sont aux États-Unis.** La simulation de pays passe par les paramètres de Google (pays et devise). À vérifier sur quelques trajets que les écarts sont bien réels avant de réserver.
- **Réserver depuis un autre pays** peut demander un VPN, une adresse de facturation locale, et coûte des frais de change selon ta carte.
- **Prix Aviasales** : ce sont des prix en cache, signalés comme tels dans la notif, à confirmer sur le site.
- **Bagages** : le prix affiché est celui de Google ou d'Aviasales, généralement sans bagage en soute.

## Structure

```
checker/        moteur Python (GitHub Actions)
  main.py       orchestration d'un passage
  planner.py    dates, week-ends, filtres
  markets.py    pays de vente et classement appris
  fx.py         taux de change
  notify.py     décision de notif et messages
  sources/      Aviasales (Travelpayouts) et Google Flights
worker/         relais Cloudflare (bot Telegram + stockage)
.github/workflows/
  check.yml     passage toutes les heures
  deploy.yml    mise en ligne du relais
tests/          tests du moteur (python -m unittest discover -s tests -t .)
```
