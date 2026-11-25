# 🎮 Mönninghausen Games

Eine Plattform für Spiele und Turniere unserer Runde – **ein Konto für alles**. Nach dem Öffnen
landet man auf einer Startseite und wählt den Bereich:

| Bereich | Adresse | Stand |
|---|---|---|
| 🏆 **Fantasy Darts** – Team zur PDC-WM zusammenstellen, Ranking | `/fantasy` | fertig |
| 🎯 **Darts** – 501 gegeneinander spielen, am Handy zählen, Stats | `/darts` | fertig |
| 🍺 **Beer Pong** – Becher live zählen, Turniere mit Teams | `/beerpong` | fertig |

Konten, Login, Profilbilder, Profilseiten, Einladungen und die Mitgliederverwaltung gehören zum
gemeinsamen Kern und gelten in jedem Bereich. Welche Bereiche es gibt (Name, Icon, Tabs, Admin-Seite),
steht zentral in `app/platform.py` – Startseite, Navigation und Admin übernehmen das automatisch.

**Farben:** Markenfarbe ist Blau – zentral als `--pico-primary` oben in `app/static/app.css` (dazu das
Dunkelblau der Kopfzeile). Das App-Icon erzeugt `python scripts/make_icons.py`.

Die App ist eine **mobile Web-App (PWA)**: im Handy-Browser öffnen → „Zum Startbildschirm
hinzufügen“ → läuft wie eine App, ohne App Store.

## Fantasy Darts

Jede:r stellt ein Team aus Spielern zusammen (Budget, Playmaker, Underdog, Weltmeister-Tipp),
der Admin trägt die Ergebnisse im Turnierbaum ein, und das Ranking aktualisiert sich automatisch.
Fantasy Darts lag früher direkt unter `/` – alte Links (z. B. `/my`, `/bracket`) werden automatisch
auf `/fantasy/...` umgeleitet.

## Darts

Unter *Darts → New game* Startwert (301/501/701), „First to X Legs“ und 1–4 Spieler wählen
(1 Spieler = Training). Spieler sind Mitglieder **oder Gäste ohne Konto** – ein Admin kann einen Gast
später einem Konto zuordnen (*Stats → Spieler → Link guest to an account*), die Stats wandern mit.

- **Doppel (2 gegen 2):** unter *New game* „Doubles 2 v 2“ wählen und 4 Spieler in Wurfreihenfolge eintragen
  (Team 1 · Spieler 1, Team 2 · Spieler 1, Team 1 · Spieler 2, Team 2 · Spieler 2). Der Rest zählt pro Team,
  der Anwurf wandert jedes Leg eine Position weiter. Average, 180er usw. zählen pro Spieler, ein Sieg für beide.
- **Partyspiele** (unter *New game* bei „Game“ wählbar), Eingabe Dart für Dart (Single/Double/Triple +
  Zahl, 25, Bull, Miss):
  - **Cricket** (2–4): 15–20 und Bull mit je 3 Treffern schließen, Extra-Treffer punkten, solange ein
    Gegner offen hat. Alles zu und mindestens so viele Punkte wie jeder Gegner → Sieg.
  - **Around the Clock** (1–4): 1 → 20 → Bull der Reihe nach.
  - **Shanghai** (1–4): Runde n zählt nur die n (7/10/20 Runden); Single + Double + Triple in einer
    Aufnahme = Shanghai, sofort gewonnen. Bei Gleichstand wird weitergespielt.
  - **Killer** (2–4): zufällige Zahlen, 1–5 Leben. Eigenes Doppel → Killer; danach kostet jedes Doppel eines
    Gegners ihn ein Leben (das eigene kostet einen selbst eins). Wer übrig bleibt, gewinnt.
  Average, Checkout & Co. zählen nur X01; die Partyspiele haben eigene Bilanzen auf der Spielerseite.
- **Zählen am Handy:** Punkte der Aufnahme eintippen oder Schnelltaste (26, 41, 45, 60, 81, 85, 100, 140, 180).
  Bust wird automatisch erkannt, beim Checkout fragt die App nach der Anzahl Darts, darüber steht
  ein Checkout-Vorschlag (z. B. 121 → T20 · T15 · D8). *Undo* nimmt die letzte Aufnahme zurück.
- **Zählen dürfen:** wer das Spiel angelegt hat, mitspielende Mitglieder und Admins. Alle anderen sehen
  das Spiel live – die Seite aktualisiert sich nach jeder Aufnahme automatisch (alle 3 Sekunden geprüft).
- **Stats** (immer aus den gespeicherten Aufnahmen berechnet): 3-Dart-Average, First-9-Average,
  Siege, Legs, 180er, 140+, 100+, höchstes Finish, bestes Leg, Checkout-Quote (Checkouts geteilt durch
  Aufnahmen, die auf einem ausmachbaren Rest begonnen haben). Abgebrochene Spiele zählen nicht.
- Spiellogik in `app/darts/` (engine, checkouts, stats, service) – reine Funktionen mit eigenen Tests.

**Elo, Formkurve, Erfolge:** Jeder startet mit 1000 Elo. Nach jedem beendeten Spiel (X01 und Partyspiele)
gewinnt der Sieger Punkte vom Verlierer, gegen Stärkere mehr als gegen Schwächere (K = 32, bei mehreren
Gegnern aufgeteilt, im Doppel zählt der Schnitt des Teams). Unter 5 Spielen gilt die Wertung als vorläufig.
Auf der Spielerseite: Elo und Platz, **Formkurve** (Average der letzten 30 X01-Spiele, ● gewonnen /
○ verloren), Elo-Verlauf und 16 **Erfolge** (180, Ton-up finish, Big Fish 170, Bull-Finish, Short leg,
Sixty/Eighty club, Party animal, Champion …) mit Datum. Alles wird wie die Stats aus den Spielen
berechnet (`app/darts/rating.py`, `app/darts/achievements.py`).

**📰 Neuigkeiten** (Startseite und Darts): Turniersieger, Ergebnisse mit Elo-Änderung, 180er, Finishes
ab 100 und neue Erfolge der letzten 30 Tage (`app/feed.py`).

**Turniere** (*Darts → Tournaments*): Name, Startwert, „First to X Legs“ (fürs Finale extra einstellbar),
Mitglieder antippen und Gäste eintippen, optional zufällig losen. Es entsteht ein K.-o.-Baum mit
üblicher Setzliste (1 gegen den Letzten …); bei ungerader Teilnehmerzahl bekommen die Topgesetzten
ein Freilos. Match antippen → *Play this match* startet ein normales Darts-Spiel; ist es entschieden,
rückt der Sieger automatisch weiter. Ohne Handy gespielt? Der Organisator (wer das Turnier angelegt hat,
oder ein Admin) trägt das Ergebnis direkt ein. Ergebnisse lassen sich ändern, solange das Folgematch
noch keins hat. Die Turnier-Logik (`app/tournaments.py`) ist für alle Sportarten gleich.

**Format „Groups + KO“** (bei Darts und Beer Pong): Anzahl Gruppen und wie viele pro Gruppe weiterkommen
wählen. Die Einträge werden nach Setzliste in Schlangenlinie verteilt (A B C C B A …), in jeder Gruppe
spielt jeder gegen jeden. Tabelle: Siege → Differenz (Legs/Becher) → erzielte Legs/Becher → direkter
Vergleich. Sind alle Gruppenspiele gespielt, entsteht der K.-o.-Baum automatisch – bei zwei Qualifikanten
pro Gruppe über Kreuz (A1–B2, B1–A2), sonst nach Bilanz gesetzt. Danach sind Gruppenergebnisse gesperrt;
der Organisator kann den K.-o. zurücksetzen, solange dort noch nichts gespielt ist.

**Format „League“** (Liga, bei Darts und Beer Pong): jeder gegen jeden, wahlweise nur Hinrunde oder
Hin- und Rückrunde (*Home & away*, in der Rückrunde mit getauschten Seiten), aufgeteilt in **Spieltage**
(niemand spielt zweimal am selben Spieltag, wer zuerst wirft, wechselt). Tabelle: 2 Punkte pro Sieg, dann
Differenz, erzielte Legs/Becher, direkter Vergleich. Sind alle Spiele gespielt, ist der Tabellenerste Meister.
Eine spätere Ergebnisänderung bestimmt den Meister neu. Die Spiele können über Tage oder Wochen verteilt
gespielt werden; der aktuelle Spieltag ist markiert, Scheiben/Push/TV-Ansicht funktionieren wie im Turnier.

**Scheiben / Tische:** Beim Anlegen festlegen, wie viele Scheiben (Darts) bzw. Tische (Beer Pong) es gibt.
Sie werden durchnummeriert, und die App setzt automatisch das nächste spielbare Match auf jede freie
Scheibe – niemand muss auf zwei Scheiben gleichzeitig spielen. Reihenfolge: Gruppenspiele nach Spieltag
(Gruppen abwechselnd), dann K.-o. Runde für Runde. Oben im Turnier steht, was auf welcher Scheibe läuft und
was als Nächstes kommt; im Spiel steht die Scheibe oben. Der Organisator kann die Anzahl jederzeit ändern
(*Organizer options*), z. B. wenn eine Scheibe dazukommt. 0 = keine Zuordnung.

**Turnier-Spielarten:** Statt X01 auch Cricket, Around the Clock, Shanghai (7/10/20 Runden) oder Killer
(1–9 Leben) – ein Spiel entscheidet das Match. X01-Turniere gehen auch als **Doppel**: Paare zufällig
auslosen (*🎲 Doubles*) oder feste Teams eintippen (*✍️ Teams*, eine Zeile pro Team: „Chris & Dana“).

**📺 TV-Ansicht** (Link oben im Turnier): Vollbild für Fernseher/Beamer mit allen Scheiben und Live-Ständen,
Warteschlange, letzten Ergebnissen und Gruppen/Baum. Aktualisiert sich alle 5 Sekunden selbst.

**🔔 Push-Benachrichtigung „Du bist dran“:** Unter *Account → Notifications* (oder über den Hinweis im
Turnier, wenn man mitspielt) einschalten. Sobald ein eigenes Match eine Scheibe/einen Tisch bekommt, kommt
eine Nachricht aufs Handy („🎯 You're up – Board 2“); antippen öffnet das Match. Klappt auf Android/Desktop
im Browser, auf dem iPhone ab iOS 16.4, wenn die App zum Home-Bildschirm hinzugefügt ist. Technik: Web Push
mit VAPID, selbst umgesetzt in `app/push.py` (nur `cryptography`). Die Schlüssel erzeugt die App beim ersten
Gebrauch selbst und speichert sie in der Datenbank, es muss nichts eingerichtet werden. Abgelaufene Geräte
werden automatisch entfernt.

**🔊 Ansager** (Knopf im Darts-Spiel): sagt jede Aufnahme an („One hundred and eighty!“, „Game shot!“) –
über die Sprachausgabe des Handys, an/aus wird pro Gerät gemerkt.

**Turnier-Historie & Stats:** Die Turnierliste zeigt alle (auch beendeten) Turniere mit Champion und oben
eine **Hall of Fame** (Turniersiege pro Spieler). Auf jeder Turnierseite steht unten **„Standings & stats“**:
Platzierung (Champion, Runner-up, Halbfinale …, in der Gruppe ausgeschieden), Siege–Niederlagen, Differenz,
bei Darts zusätzlich Average, 180er, höchstes Finish und Checkout-Quote aus den Turnierspielen, bei Beer Pong
Becher pro Spiel.

**Wer darf Ergebnisse eingeben?** (Darts und Beer Pong gleich): wer das Spiel angelegt hat, alle Mitspieler
mit Konto (auf ihrem eigenen Handy eingeloggt), Admins und bei Turnierspielen der Organisator des Turniers.
Alle anderen sehen das Spiel live, können aber nichts eintragen. Für Gäste ohne Konto zählt, wer das Spiel
angelegt hat.

## Beer Pong

*Beer Pong → New game*: 6 oder 10 Becher, zwei Teams mit je 1–4 Spielern (Mitglieder oder Gäste),
optional Teamnamen. Im Spiel hat jedes Team einen großen **„Hit!“**-Knopf und **„−1“** zum Korrigieren;
wer zuerst alle Becher trifft, gewinnt. Zuschauer sehen den Stand live.

**Turniere** (*Beer Pong → Tournaments*), gleicher K.-o.-Baum wie bei Darts. Teams entweder
- **zufällig**: Spieler antippen / Gäste eintippen, die App lost Zweierteams (gerade Anzahl nötig), oder
- **fest**: eine Zeile pro Team, z. B. `Cup Kings: Olli, Kevin` (Name optional). Mitglieder und Gäste
  werden am Namen erkannt, neue Namen werden Gäste.

*Play this match* startet das Spiel, der Sieger rückt automatisch weiter; der Organisator kann
Ergebnisse auch direkt eintragen (Becher pro Team, der Sieger trifft alle). **Stats** pro Spieler:
Spiele, Siege, Siegquote, getroffene Becher pro Spiel, Becher-Differenz (zählt für jedes Teammitglied).

Alle Stats (Darts und Beer Pong) stehen auch auf der Profilseite jedes Mitglieds.

**Vergleichen (⚖️ Compare)**: unter *Stats* oder über „Compare with me“ auf einer Spieler- bzw. Profilseite.
Zwei Spieler nebeneinander, bei jedem Wert ist der bessere grün markiert („Categories won“). Darts zeigt
dazu den **direkten Vergleich** (Siege, Legs und Stats nur aus den gemeinsamen Spielen, letzte Duelle),
Beer Pong die Bilanz **gegeneinander** und **zusammen im Team**.

## Aufbau

```
app/
  main.py        FastAPI-App (Einstiegspunkt, auch für Vercel), Weiterleitung alter Adressen
  platform.py    Welche Bereiche es gibt (Startseite, Navigation, Admin)
  settings.py    Konfiguration über Umgebungsvariablen / .env
  avatars.py     Profilbilder verkleinern & speichern
  tournaments.py K.-o.-Turniere (Setzliste, Freilose, Weiterrücken) für alle Sportarten
  competitors.py Teilnehmer (Mitglieder & Gäste) für Darts und Beer Pong
  beerpong.py    Beer Pong: Spiele, Teams, Stats, Turnier-Anbindung
  darts/         Darts: Spiellogik, Checkout-Wege, Stats, Datenbank-Operationen
  rules.py       Fantasy: lädt seasons/<saison>/rules.toml
  scoring.py     Fantasy: Punkteberechnung (reine Funktionen)
  teams.py       Fantasy: Team-Validierung & Speichern
  bracket.py     Fantasy: Ergebnisse eintragen, Sieger weiterreichen
  season.py      Fantasy: Saison-Import aus CSV, Lock-Status
  cli.py         Kommandozeile (Import, User anlegen, ...)
  web/
    hub.py       Kern: Startseite, Admin-Übersicht
    darts.py     Darts-Seiten (Spiele, Zählen, Stats, Turniere)
    beerpong.py  Beer-Pong-Seiten
    account.py   Kern: Login, Registrierung, Account, Profilbild
    members.py   Kern: Mitglieder, Einladungslinks, Einladungscode
    pages.py, my_teams.py, admin*.py   Fantasy-Seiten
  templates/     HTML (Jinja2) – Pico CSS + Alpine.js, kein Build-Schritt
  static/        CSS, JS, Icons, Flaggen, Service Worker
seasons/
  wm2026/
    rules.toml   ⚙️ ALLE Regeln & Punkte
    players.csv  name,price,nation,seed
    draw.csv     Paarungen der 1. Runde (player1,player2) in Turnierbaum-Reihenfolge
tests/
```

**Admin-Bereich:** *Admin* (im Menü oben rechts oder auf der Account-Seite) zeigt eine Übersicht
über alle Bereiche. **Members** (Einladen, Mitglieder verwalten) gilt für die ganze Plattform,
jeder Bereich hat zusätzlich seinen eigenen Admin – bei Fantasy Darts mit den Tabs **Overview**
(Zahlen, To-do-Liste, Team-Sperre, Export), **Schedule**, **Players** und **Rules**.

**Regeln & Punkte** kann der Admin unter *Admin → Fantasy Darts → Rules* direkt in der App ändern
(solange die Teams nicht gesperrt sind). `rules.toml` ist nur die Vorlage für eine neue Saison.
Spieler (Name, Nation, Preis, Seed) bearbeitet der Admin unter *Admin → Fantasy Darts → Players*, inklusive
Nachrücker in der Auslosung. Mitspieler melden sich per persönlichem Einmal-Link oder gemeinsamem Einladungscode selbst an (*Admin → Members*).

**Profilbilder** lädt jede:r unter *Account* selbst hoch. Der Browser schneidet das Bild quadratisch zu,
der Server verkleinert es auf 512×512 px (WebP, entfernt Metadaten wie GPS) und speichert es in der
Datenbank – auf Vercel gibt es kein dauerhaftes Dateisystem. Fotos sehen nur eingeloggte Mitspieler,
Gäste sehen einen Kreis mit dem Anfangsbuchstaben. Admins können Bilder unter *Admin → Members* entfernen.

**Punkte werden nie gespeichert**, sondern bei jedem Aufruf aus den Matches + `rules.toml`
berechnet. Regeln ändern → Punkte stimmen sofort, auch rückwirkend.

## Lokal starten

```bash
python -m venv .venv
.venv\Scripts\activate          # Linux/Mac: source .venv/bin/activate
pip install -r requirements-dev.txt

python -m app.cli import-season wm2026
python -m app.cli create-user olli --admin
uvicorn app.main:app --reload
```

→ http://127.0.0.1:8000 . Ohne `.env` wird lokal die SQLite-Datei `fantasy.db` benutzt.

Tests: `pytest` (SQLite). Gegen eine echte, **leere** Postgres-Test-Datenbank:
`TEST_DATABASE_URL=postgresql://user:pass@localhost/fd_test pytest` – die Tests löschen und erzeugen dort alle Tabellen.

## Neue Saison (z. B. WM 2027)

1. Ordner kopieren: `seasons/wm2026` → `seasons/wm2027`
2. `players.csv` mit neuen Spielern/Preisen füllen, `draw.csv` mit der Auslosung
   (64 Zeilen, Reihenfolge wie im Turnierbaum von oben nach unten)
3. `rules.toml` anpassen (Name, Budget, Punkte, `lock_at` = Turnierstart)
4. `python -m app.cli import-season wm2027` (gegen die Produktions-DB: vorher `DATABASE_URL` setzen)
5. Umgebungsvariable `SEASON=wm2027` setzen und neu deployen

User bleiben über Saisons hinweg erhalten.

## Hosting (kostenlos): Vercel + Neon

**Datenbank – Neon** (kostenloses Postgres, läuft nicht ab):
1. Auf neon.tech ein Projekt anlegen (Region Frankfurt)
2. Den Connection-String kopieren (`postgresql://...?sslmode=require`)
3. Lokal einmalig die Daten anlegen:
   ```bash
   set DATABASE_URL=postgresql://...      # PowerShell: $env:DATABASE_URL="postgresql://..."
   python -m app.cli import-season wm2026
   python -m app.cli create-user olli --admin
   # optional: alte User übernehmen
   python -m app.cli import-legacy-users sqlite:///fantasy_alt.db
   ```

**App – Vercel**:
1. Repo auf vercel.com importieren (wird automatisch als FastAPI erkannt, `app/main.py`)
2. Unter *Settings → Environment Variables* setzen:
   - `DATABASE_URL` = Neon-Connection-String
   - `SECRET_KEY` = langer Zufallswert (`python -c "import secrets; print(secrets.token_urlsafe(32))"`)
   - `SECURE_COOKIES` = `true`
   - `SEASON` = `wm2026`
   - optional `INVITE_CODE` = Code, mit dem sich Mitspieler unter `/register` selbst anmelden
3. Deploy. Jeder `git push` auf `main` deployt automatisch neu.

*Alternative:* Läuft genauso auf Render/Railway/Fly mit dem Startbefehl
`uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Dann aber auch dort die DB bei Neon lassen,
weil die kostenlose Render-Postgres nach 30 Tagen gelöscht wird.

## Admin-Ablauf während des Turniers

- **Vor dem Start – Mitspieler einladen**, drei Wege:
  - **Persönliche Einladungslinks** (empfohlen): *Admin → Members* → Notiz eintragen
    (z. B. den Namen, nur für dich sichtbar) → *Create link* → Link kopieren und an genau diese Person
    schicken. Jeder Link funktioniert für **genau eine** Registrierung, ein Code ist nicht nötig. Danach
    steht er unter *Used* mit dem gewählten Usernamen und Datum. Benutzte oder gelöschte Links zeigen
    „already used“. Offene Links lassen sich jederzeit löschen.
  - **Gemeinsamer Einladungscode:** `INVITE_CODE` setzen oder unter *Admin → Members → Shared invite code* einen Code
    festlegen und den Link teilen. Damit können sich beliebig viele selbst anmelden, solange der Code aktiv ist.
  - **Manuell:** unter *Admin → Members → Add member manually* anlegen und das Startpasswort weitergeben (jede:r kann es
    unter *Account* ändern).
- **Teams sperren:** Teams werden zum `lock_at`-Zeitpunkt automatisch gesperrt, oder
  manuell über den Schalter unter *Admin → Fantasy Darts → Overview*. Die To-do-Liste dort zeigt, wer noch
  kein Team hat.
- **Ergebnisse:** *Bracket* → Runde wählen → Match antippen → Sätze + Stats eintragen.
  Der Sieger rückt automatisch in die nächste Runde. Korrigieren geht jederzeit. Den Sieger
  ändern kann man nur, solange das Folgematch noch kein Ergebnis hat.
  Hast du unter *Schedule* Anstoßzeiten eingetragen, zeigt die To-do-Liste auf *Admin → Fantasy Darts → Overview*, welche
  Matches schon gespielt sein müssten und noch kein Ergebnis haben.

## Sicherheit

- Passwörter werden mit bcrypt gespeichert, der Login ist ein signiertes Cookie (`SECRET_KEY`).
- **Schutz gegen Passwort-Raten:** nach 10 falschen Passwörtern für einen Namen innerhalb von 15 Minuten
  ist dieser Name 15 Minuten gesperrt (gezählt in der Datenbank, wirkt also auch auf Vercel). Setzt ein
  Admin das Passwort zurück, ist die Sperre sofort weg.

## Backup & Export

- **Wo liegen die Daten?** In Produktion in der Postgres-DB (Neon), unabhängig von der App –
  Abstürze oder Redeploys löschen nichts. Jede Aktion wird sofort gespeichert. Auf Vercel
  verweigert die App den Start ohne `DATABASE_URL`, damit nie versehentlich SQLite auf einem
  flüchtigen Dateisystem benutzt wird.
- **CSV-Export** (öffnet sich direkt in Excel): *Admin → Fantasy Darts → Overview → Export & backup* – Teams, Ergebnisse, Spieler.
- **Komplett-Backup** (JSON, inkl. User mit Passwort-Hashes, Profilbildern, Einladungslinks sowie allen
  Darts-, Beer-Pong- und Turnierdaten – vertraulich behandeln):
  ```bash
  python -m app.cli backup                        # oder auf der Admin-Seite herunterladen
  python -m app.cli restore-backup <datei>.json   # in eine DB ohne diese Saison einspielen
  ```
  Tipp: Während des Turniers ab und zu ein Backup ziehen, z. B. nach jedem Spieltag.
