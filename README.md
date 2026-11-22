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

**Mots compris dans `/alerte`** : `de`, `vers` (ou `partout`), `du … au …`, `en mars`, `weekends mars,avril`, `nuits 2-4`, `max 80`, `direct`, `aller-simple`, `depart 6-12`, `retour 17-23`, `prio`. Villes connues : lyon, geneve, paris, londres, milan… sinon le code aéroport à 3 lettres.

**Week-end** = départ jeudi, vendredi ou samedi et retour samedi, dimanche ou lundi (1 à 3 nuits par défaut, modifiable avec `nuits`).

## Comment ça marche

1. **Aviasales** (cache gratuit, prix vus par les utilisateurs ces 2 à 7 derniers jours) balaye toutes les combinaisons : plusieurs départs, destinations ou « partout », mois entiers.
2. **Google Flights** confirme les meilleures pistes avec le prix réel du moment, en France puis dans les pays de vente les mieux classés (devise locale convertie en euros au taux BCE du jour, frais de change de ta carte inclus).
3. Pour les alertes à destination précise, le moteur fait aussi tourner les dates à chaque passage, pour couvrir ce que le cache Aviasales ne connaît pas.
4. **Classement des pays** : au départ, ordre par défaut (pays de la destination, puis Pologne, Hongrie, Turquie, Inde, Brésil, Mexique…). Ensuite, le moteur retient quels pays ont battu la France sur chaque route et les teste en priorité. Une fois par semaine et par alerte, il refait un tour complet de tous les pays.
5. **Notifs** : à la première fois sous ton prix max, puis à chaque nouvelle baisse d'au moins 5 % (réglable). Une offre dans un autre pays n'est proposée que si elle fait gagner au moins 15 € (réglable). « 🔥 Prix anormalement bas » quand le prix passe 20 % sous la médiane des 30 derniers jours.

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
