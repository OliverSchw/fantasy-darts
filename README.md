# 🎯 Fantasy Darts

Fantasy-Spiel zur PDC Darts-WM für eine private Runde. Jede:r stellt ein Team aus Spielern
zusammen (Budget, Playmaker, Underdog, Weltmeister-Tipp), der Admin trägt die Ergebnisse
im Turnierbaum ein, und das Ranking aktualisiert sich automatisch.

Die App ist eine **mobile Web-App (PWA)**: im Handy-Browser öffnen → „Zum Startbildschirm
hinzufügen“ → läuft wie eine App, ohne App Store.

## Aufbau

```
app/
  main.py        FastAPI-App (Einstiegspunkt, auch für Vercel)
  settings.py    Konfiguration über Umgebungsvariablen / .env
  rules.py       lädt seasons/<saison>/rules.toml
  scoring.py     Punkteberechnung (reine Funktionen)
  teams.py       Team-Validierung & Speichern
  bracket.py     Ergebnisse eintragen, Sieger weiterreichen
  season.py      Saison-Import aus CSV, Lock-Status
  cli.py         Kommandozeile (Import, User anlegen, ...)
  web/           Seiten (Routen)
  templates/     HTML (Jinja2) – Pico CSS + Alpine.js, kein Build-Schritt
  static/        CSS, JS, Icons, Flaggen, Service Worker
seasons/
  wm2026/
    rules.toml   ⚙️ ALLE Regeln & Punkte
    players.csv  name,price,nation,seed
    draw.csv     Paarungen der 1. Runde (player1,player2) in Turnierbaum-Reihenfolge
tests/
```

**Regeln & Punkte** kann der Admin unter *Admin → Rules & points* direkt in der App ändern
(solange die Teams nicht gesperrt sind). `rules.toml` ist nur die Vorlage für eine neue Saison.
Spieler (Name, Nation, Preis, Seed) bearbeitet der Admin unter *Admin → Players*, inklusive
Nachrücker in der Auslosung. Mitspieler melden sich per persönlichem Einmal-Link oder gemeinsamem Einladungscode selbst an (*Admin → Overview*).

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

Tests: `pytest`

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
  - **Persönliche Einladungslinks** (empfohlen): *Admin → Personal invite links* → Notiz eintragen
    (z. B. den Namen, nur für dich sichtbar) → *Create link* → Link kopieren und an genau diese Person
    schicken. Jeder Link funktioniert für **genau eine** Registrierung, ein Code ist nicht nötig. Danach
    steht er unter *Used* mit dem gewählten Usernamen und Datum. Benutzte oder gelöschte Links zeigen
    „already used“. Offene Links lassen sich jederzeit löschen.
  - **Gemeinsamer Einladungscode:** `INVITE_CODE` setzen oder auf der *Admin*-Seite einen Code
    festlegen und den Link teilen. Damit können sich beliebig viele selbst anmelden, solange der Code aktiv ist.
  - **Manuell:** User unter *Admin → Users* anlegen und das Startpasswort weitergeben (jede:r kann es
    unter *Account* ändern).
- **Teams sperren:** Teams werden zum `lock_at`-Zeitpunkt automatisch gesperrt, oder
  manuell über den Schalter unter *Admin*.
- **Ergebnisse:** *Bracket* → Runde wählen → Match antippen → Sätze + Stats eintragen.
  Der Sieger rückt automatisch in die nächste Runde. Korrigieren geht jederzeit. Den Sieger
  ändern kann man nur, solange das Folgematch noch kein Ergebnis hat.

## Backup & Export

- **Wo liegen die Daten?** In Produktion in der Postgres-DB (Neon), unabhängig von der App –
  Abstürze oder Redeploys löschen nichts. Jede Aktion wird sofort gespeichert. Auf Vercel
  verweigert die App den Start ohne `DATABASE_URL`, damit nie versehentlich SQLite auf einem
  flüchtigen Dateisystem benutzt wird.
- **CSV-Export** (öffnet sich direkt in Excel): *Admin → Export & backup* – Teams, Ergebnisse, Spieler.
- **Komplett-Backup** (JSON, inkl. User mit Passwort-Hashes – vertraulich behandeln):
  ```bash
  python -m app.cli backup                        # oder auf der Admin-Seite herunterladen
  python -m app.cli restore-backup <datei>.json   # in eine DB ohne diese Saison einspielen
  ```
  Tipp: Während des Turniers ab und zu ein Backup ziehen, z. B. nach jedem Spieltag.
