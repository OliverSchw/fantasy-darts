import streamlit as st
import requests
import pandas as pd
import math
import re
import time

import os

# Wenn auf Streamlit Cloud: nimm BASE_URL aus den Secrets
# Wenn lokal: fallback auf localhost
BASE_URL = os.getenv(
    "BASE_URL", "https://fantasy-darts-1.onrender.com"
)  #  #"http://127.0.0.1:8000"

COUNTRY_CODE_MAP = {
    "England": "gb-eng",
    "Netherlands": "nl",
    "Scotland": "gb-sct",
    "Wales": "gb-wls",
    "Germany": "de",
    "Belgium": "be",
    "Australia": "au",
    "Northern Ireland": "gb-nir",
    "Poland": "pl",
    "Ireland": "ie",
    "Latvia": "lv",
    "Austria": "at",
    "France": "fr",
    "Czech Republic": "cz",
    "Canada": "ca",
    "Lithuania": "lt",
    # new
    "Sweden": "se",
    "Switzerland": "ch",
    "Japan": "jp",
    "China": "cn",
    "India": "in",
    "Hong Kong": "hk",
    "Philippines": "ph",
    "Singapore": "sg",
    "Spain": "es",
    "Croatia": "hr",
    "Hungary": "hu",
    "USA": "us",
    "Argentina": "ar",
    "Finland": "fi",
    "Norway": "no",
    "New Zealand": "nz",
    "Kenya": "ke",
    "Portugal": "pt",
}

BASE_FLAG_URL = "https://cdnjs.cloudflare.com/ajax/libs/flag-icons/7.5.0/flags/4x3/"


def get_flag_url(nation):
    code = COUNTRY_CODE_MAP.get(nation.strip())
    if code:
        # Beispiel: https://cdnjs.cloudflare.com/ajax/libs/flag-icons/7.5.0/flags/4x3/gb-eng.svg
        # Wir verwenden SVG, da es gut skaliert
        return f"{BASE_FLAG_URL}{code}.svg"
    return ""  # Leerer String, falls kein Code gefunden wurde


st.set_page_config(page_title="Fantasy Darts WM", layout="wide")

# -----------------------------------
# 🔹 Seitenmenü
# -----------------------------------
st.sidebar.title("🎯 Fantasy Darts World Championship")


if "user_id" not in st.session_state:
    st.sidebar.subheader("🔐 Login")
    username = st.sidebar.text_input("Username")
    password = st.sidebar.text_input("Password", type="password")
    if st.sidebar.button("Login"):
        try:
            response = requests.post(
                f"{BASE_URL}/auth/login",
                json={"username": username, "password": password},
            )
            if response.status_code == 200:
                data = response.json()
                st.session_state.user_id = data["user_id"]
                st.session_state.username = data["username"]
                st.success(f"Welcome {data['username']}!")
                st.rerun()  # sofort neu rendern
            else:
                st.error("Invalid username or password")
        except Exception as e:
            st.error(f"Login failed: {e}")

else:
    st.sidebar.write(f"Logged in as {st.session_state.username}")
    if st.sidebar.button("Logout"):
        del st.session_state.user_id
        del st.session_state.username
        st.success("Logged out successfully!")
        st.rerun()  # sofort neu rendern

# Seiten-Navigation
page = st.sidebar.radio(
    "Navigation",
    [
        "🏠 Overview",
        "🎯 Players",
        "🧩 Teams",
        # "⚔️ Tournament Bracket"
        "📅 Tournament Schedule",
    ],
)

# -----------------------------------
# 🔹 Overview (Dashboard)
# -----------------------------------
if page == "🏠 Overview":

    # --- Initial page state ---
    if "current_page" not in st.session_state:
        st.session_state.current_page = "overview"

    # --- Callback-Funktionen ---
    def go_to_team(team_id, team_name):
        st.session_state.selected_team_id = team_id
        st.session_state.selected_team_name = team_name
        st.session_state.current_page = "team_detail"

    def back_to_overview():
        st.session_state.current_page = "overview"
        requests.put(f"{BASE_URL}/players/points/recompute")

    # --- Team Detail Seite ---
    if st.session_state.current_page == "team_detail":
        team_id = st.session_state.selected_team_id
        team_name = st.session_state.selected_team_name

        st.title(f"🎯 Team: {team_name}")
        st.subheader("👥 Your Players")

        # Spieler laden (enthält jetzt is_captain/is_underdog)
        try:
            players = requests.get(f"{BASE_URL}/teams/{team_id}/players").json()

        except Exception as e:
            st.error(f"Fehler beim Laden der Teamspieler: {e}")
            st.stop()

        if players and isinstance(players, list):
            df_players = pd.DataFrame(players)
            # ... (Logik zur Erstellung von Role, format_points, Display_Points, Calculated_Total_Points)

            # Ich übernehme hier die funktionale Struktur aus deiner letzten Eingabe:

            # --- Rollen-Berechnung ---
            def get_player_role(row):
                role = ""
                is_captain = row.get("is_captain")
                is_underdog = row.get("is_underdog")
                if is_captain in (True, 1):
                    role += "👑 CAPTAIN (x2)"
                if is_underdog in (True, 1):
                    if role:
                        role += " / 🐕 UNDERDOG (x2)"
                    else:
                        role += "🐕 UNDERDOG (x2)"
                return role

            df_players["Role"] = df_players.apply(get_player_role, axis=1)

            # --- Punkte-Formatierung ---
            def format_points(row):
                base_points = row["points"]
                multiplier = 1
                if row.get("is_captain") in (True, 1):
                    multiplier += 1
                if row.get("is_underdog") in (True, 1):
                    multiplier += 1
                weighted_points = base_points * multiplier
                if multiplier > 1:
                    return f"{base_points:,.0f} ({weighted_points:,.0f})"
                else:
                    return f"{base_points:,.0f}"

            df_players["Display_Points"] = df_players.apply(format_points, axis=1)

            # --- Berechnung der Total Points (für Sortierung und Summe) ---
            def calculate_weighted_points_value(row):
                base_points = row["points"]
                multiplier = 1
                if row.get("is_captain") in (True, 1):
                    multiplier += 1
                if row.get("is_underdog") in (True, 1):
                    multiplier += 1
                return base_points * multiplier

            df_players["Calculated_Total_Points"] = df_players.apply(
                calculate_weighted_points_value, axis=1
            )

            df_players["flag_url"] = df_players["nation"].apply(get_flag_url)

            # Sortierung
            df_players = df_players.sort_values(
                by="Calculated_Total_Points", ascending=False
            ).reset_index(drop=True)

            # --- Highlight Row Funktion (Unverändert, aber funktioniert, da 'points' jetzt in der Liste unten ist) ---
            def highlight_row(row):
                # 'points' ist hier jetzt verfügbar, da es in die Liste der zu stylenden Spalten aufgenommen wird
                if row["points"] > 0:
                    color = "red" if row["eliminated"] else "green"
                else:
                    color = "red" if row["eliminated"] else ""

                if row.get("is_captain") in (True, 1):
                    return [
                        f"color: black; font-weight: bold; background-color: #d1e7f7"
                    ] * len(row)

                return [f"color: {color}"] * len(row)

            # --- ANPASSUNG HIER: 'points' in die Spaltenliste aufnehmen ---
            st.dataframe(
                df_players[
                    [
                        "seed",
                        "name",
                        "price",
                        "flag_url",
                        "points",  # WICHTIG: Füge 'points' hinzu, damit highlight_row es findet
                        "Display_Points",
                        "Role",
                        "eliminated",
                    ]
                ].style.apply(highlight_row, axis=1),
                column_config={
                    "seed": st.column_config.Column("Seed", width="tiny"),
                    "name": st.column_config.Column("Player Name"),
                    "price": st.column_config.NumberColumn("Price", format="compact"),
                    "flag_url": st.column_config.ImageColumn("Nation", width="tiny"),
                    "points": None,  # WICHTIG: Blende die redundante 'points' Spalte aus
                    "Display_Points": st.column_config.Column("Points"),
                    "Role": st.column_config.Column("Role", width="medium"),
                    "eliminated": None,
                },
                width="stretch",
                # Passe die Spaltenreihenfolge an, indem du 'points' durch 'Display_Points' ersetzt
                column_order=[
                    "seed",
                    "flag_url",
                    "name",
                    "price",
                    "Display_Points",
                    "Role",
                ],
                hide_index=True,
            )

            # Anzeige der Gesamtpunkte
            total_points = df_players["Calculated_Total_Points"].sum()
            st.markdown(f"### 📊 Total Team Points: **{total_points:,.0f}**")

        else:
            st.info("No players found for this team.")

        # Zurück-Button
        st.markdown("---")
        st.button("⬅️ Back to Leaderboard", on_click=back_to_overview)

    # --- Leaderboard Seite ---
    # elif st.session_state.current_page == "overview":
    else:
        st.title("🏠 Overview & Leaderboard")

        # Load leaderboard
        requests.put(f"{BASE_URL}/players/points/recompute")
        leaderboard = requests.get(f"{BASE_URL}/leaderboard/").json()
        df_lb = pd.DataFrame(leaderboard)
        if not df_lb.empty:
            df_lb = df_lb.sort_values(by="total_points", ascending=False).reset_index(
                drop=True
            )
            df_lb.insert(0, "Rank", df_lb.index + 1)

            st.subheader("🏆 Current Teams & Rankings")
            for i, row in df_lb.iterrows():
                cols = st.columns([1, 4, 2, 1])
                cols[0].write(row["Rank"])
                cols[1].write(row["team_name"])
                cols[2].write(row["total_points"])
                # View-Button mit Callback
                cols[3].button(
                    "View",
                    key=f"team_{row['team_id']}",
                    on_click=go_to_team,
                    args=(row["team_id"], row["team_name"]),
                )


# # -----------------------------------
# elif page == "⚔️ Tournament Bracket":

#     st.title("⚔️ Tournament Bracket")
#     players = requests.get(f"{BASE_URL}/players/").json()
#     df_players = pd.DataFrame(players)
#     df_players = df_players.sort_values("seed").head(64).reset_index(drop=True)

#     num_players = 64
#     num_rounds = int(math.log2(num_players))
#     rows = num_players * 2 - 1

#     # --- Seed-Reihenfolge generieren ---
#     def generate_bracket(n):
#         if n == 1:
#             return [1]
#         prev = generate_bracket(n // 2)
#         result = []
#         for p in prev:
#             result.append(p)
#             result.append(n + 1 - p)
#         return result

#     bracket = generate_bracket(num_players)

#     # --- Session-State initialisieren ---

#     if "winners" not in st.session_state:
#         st.session_state["winners"] = {}

#     results = requests.get(f"{BASE_URL}/matches/results/").json()
#     for match in results:
#         match_id = match["match_id"]
#         winner_id = match["winner_id"]
#         winner = f"{df_players.loc[df_players['id'] == winner_id, 'name'].values[0]} ({df_players.loc[df_players['id'] == winner_id, 'seed'].values[0]})"
#         st.session_state["winners"][match_id] = winner

#     if "match_data" not in st.session_state:
#         st.session_state["match_data"] = {}
#     if "current_match" not in st.session_state:
#         st.session_state["current_match"] = None

#     # --- Tabelle aufbauen ---
#     table = pd.DataFrame(
#         "",
#         index=range(rows),
#         columns=[f"Round {i+1}" for i in range(num_rounds + 1)],
#     )

#     # Runde 1
#     for i, seed in enumerate(bracket):
#         row = i * 2
#         player = f"{df_players.loc[seed-1, 'name']} ({seed})"
#         table.iloc[row, 0] = player

#     # Weitere Runden: Platzhalter setzen
#     for r in range(1, num_rounds + 1):
#         step = 2**r
#         for i in range(0, rows, step * 2):
#             row_winner = i + step - 1
#             match_id = f"match_{row_winner}_{r}"
#             table.iloc[row_winner, r] = st.session_state["winners"].get(match_id, "?")

#     # --- Dynamische Breite ---
#     max_name_len = max(len(str(name)) for name in df_players["name"])
#     button_width = int(max_name_len * 8.5 + 25)

#     # st.write("## 🗓 Match Schedule")

#     # --- CSS ---
#     st.markdown(
#         f"""
#     <style>
#     .bracket-box {{
#         border: 2px solid black;
#         border-radius: 6px;
#         padding: 6px;
#         text-align: center;
#         background-color: #FFFFFF;
#         width: {button_width}px;
#         min-height: 30px;
#         display: flex;
#         align-items: center;
#         justify-content: center;
#     }}
#     .empty-cell {{
#         min-width: {button_width}px;
#         min-height: 30px;
#     }}
#     .bracket-btn > button {{
#         min-width: {button_width}px !important;
#         min-height: 30px !important;
#     }}
#     </style>
#     """,
#         unsafe_allow_html=True,
#     )

#     # st.write("## 🏆 Tournament Bracket")

#     # --- Anzeige der Tabelle ---
#     for row_idx, row in enumerate(table.itertuples(index=False)):
#         cols = st.columns(len(table.columns) * 2 + 1)
#         for col_idx, val in enumerate(row):
#             col = cols[col_idx * 2]
#             if val != "":
#                 col.markdown(
#                     f"<div class='bracket-box'>{val}</div>",
#                     unsafe_allow_html=True,
#                 )
#             else:
#                 col.markdown(f"<div class='empty-cell'></div>", unsafe_allow_html=True)
elif page == "🎯 Players":
    st.title("🎯 All Players")

    players = requests.get(f"{BASE_URL}/players/").json()
    df_players = pd.DataFrame(players)

    def get_flag_url(nation):
        code = COUNTRY_CODE_MAP.get(nation.strip())
        if code:
            # Beispiel: https://cdnjs.cloudflare.com/ajax/libs/flag-icons/7.5.0/flags/4x3/gb-eng.svg
            # Wir verwenden SVG, da es gut skaliert
            return f"{BASE_FLAG_URL}{code}.svg"
        return ""  # Leerer String, falls kein Code gefunden wurde

    df_players["flag_url"] = df_players["nation"].apply(get_flag_url)

    if df_players.empty:
        st.error("No Players found.")
        st.stop()

    # Filteroptionen
    nations = sorted(df_players["nation"].dropna().unique())
    selected_nation = st.selectbox("🌍 Filter nation", ["All"] + nations)
    if selected_nation != "All":
        df_players = df_players[df_players["nation"] == selected_nation]

    def highlight_row(row):
        if row["points"] > 0:
            if row["eliminated"]:
                return ["color: red"] * len(row)  # alle Spalten rot
            else:
                return ["color: green"] * len(row)  # alle Spalten grün
        else:
            if row["eliminated"]:
                return ["color: red"] * len(row)
            else:
                return [""] * len(row)  # keine Farbe

    st.dataframe(
        df_players[
            ["seed", "name", "price", "flag_url", "points", "eliminated"]
        ].style.apply(highlight_row, axis=1),
        column_config={
            "seed": st.column_config.Column("Seed"),
            "name": st.column_config.Column("Player Name"),
            "price": st.column_config.NumberColumn("Price", format="compact"),
            "flag_url": st.column_config.ImageColumn("Nation"),
            "points": st.column_config.NumberColumn("Points", format="compact"),
            "eliminated": None,
        },
        width="stretch",
        column_order=["seed", "flag_url", "name", "price", "points"],
        hide_index=True,
    )
elif page == "📅 Tournament Schedule":
    FIRST_ROUND_PAIRS = [
        "Luke Littler",
        "Darius Labanauskas",
        "Mario Vandenbogaerde",
        "David Davies",
        "Joe Cullen",
        "Bradley Brooks",
        "Mensur Suljovic",
        "David Cameron",
        "Damon Heta",
        "Steve Lennon",
        "Raymond van Barneveld",
        "Stefan Bellmont",
        "Rob Cross",
        "Cor Dekker",
        "Ian White",
        "Mervyn King",
        "Chris Dobey",
        "Xiaochen Zong",
        "Andrew Gilding",
        "Cam Crabtree",
        "Luke Woodhouse",
        "Boris Krcmar",
        "Martin Lukeman",
        "Max Hopp",
        "Gerwyn Price",
        "Adam Gawlas",
        "Lukas Wenig",
        "Wesley Plaisier",
        "Ryan Joyce",
        "Owen Bates",
        "Krzysztof Ratajski",
        "Alexis Toylo",
        "Stephen Bunting",
        "Sebastian Bialecki",
        "Richard Veenstra",
        "Nitin Kumar",
        "Dirk van Duijvenbode",
        "Andy Baetens",
        "James Hurrell",
        "Stowe Buntz",
        "Martin Schindler",
        "Stephen Burton",
        "Keane Barry",
        "Tim Pusey",
        "Ryan Searle",
        "Chris Landman",
        "Brendan Dolan",
        "Tavis Dudeney",
        "Jonny Clayton",
        "Adam Lipscombe",
        "Dom Taylor",
        "Oskar Lukasiak",
        "Michael Smith",
        "Lisa Ashton",
        "Niels Zonneveld",
        "Haupai Puha",
        "Ross Smith",
        "Andreas Harrysson",
        "Thibault Tricole",
        "Motomu Sakai",
        "Dave Chisnall",
        "Fallon Sherrock",
        "Ricardo Pietreczko",
        "José de Sousa",
        "Luke Humphries",
        "Ted Evetts",
        "Jeffrey de Graaf",
        "Paul Lim",
        "Wessel Nijman",
        "Karel Sedlacek",
        "Gabriel Clemens",
        "Alex Spellman",
        "Nathan Aspinall",
        "Lourence Ilagan",
        "Mickey Mansell",
        "Leonard Gates",
        "Mike De Decker",
        "David Munyua",
        "Kevin Doets",
        "Matthew Dennant",
        "James Wade",
        "Ryusei Azemoto",
        "Ricky Evans",
        "Man Lok Leung",
        "Cameron Menzies",
        "Charlie Manby",
        "Matt Campbell",
        "Adam Sevada",
        "Gian van Veen",
        "Cristo Reyes",
        "Alan Soutar",
        "Teemu Harju",
        "Dimitri Van den Bergh",
        "Darren Beveridge",
        "Madars Razma",
        "Jamai van den Herik",
        "Michael van Gerwen",
        "Mitsuhiko Tatsunami",
        "William O'Connor",
        "Krzysztof Kciuk",
        "Peter Wright",
        "Noa van Leuven",
        "Kim Huybrechts",
        "Arno Merk",
        "Gary Anderson",
        "Adam Hunt",
        "Connor Scutt",
        "Simon Whitlock",
        "Jermaine Wattimena",
        "Dominik Grüllich",
        "Scott Williams",
        "Paolo Nebrida",
        "Danny Noppert",
        "Jurjen van der Velde",
        "Nick Kenny",
        "Justin Hood",
        "Ritchie Edhouse",
        "Jonny Tata",
        "Ryan Meikle",
        "Jesus Salate",
        "Josh Rock",
        "Gemma Hayter",
        "Niko Springer",
        "Joe Comito",
        "Daryl Gurney",
        "Beau Greaves",
        "Callan Rydz",
        "Patrik Kovacs",
    ]

    NUM_ROUNDS = 6
    NUM_MATCHES_ROUND_1 = 64
    ROWS = NUM_MATCHES_ROUND_1 * 2

    # --- INITIALISIERUNG DES SESSION STATE ---
    if "current_page" not in st.session_state:
        st.session_state.current_page = "overview"
    if "winners" not in st.session_state:
        st.session_state["winners"] = {}
    if "match_data" not in st.session_state:
        st.session_state["match_data"] = {}
    if "current_match" not in st.session_state:
        st.session_state["current_match"] = None

    # --- HILFSFUNKTIONEN ---
    def extract_base_name(full_name_display):
        """Extrahiert den Spielernamen ohne (Seed) oder (ID)."""
        # Entfernt Seed/ID in Klammern am Ende des Strings
        match = re.match(r"^(.*?) \(\d+|\?\)$", full_name_display)
        return match.group(1).strip() if match else full_name_display

    def get_round_num(match_id):
        """Extrahiert die Runden-Nummer aus der Match-ID (z.B. match_0_1 -> 1)."""
        try:
            parts = match_id.split("_")
            return int(parts[-1])
        except:
            return 999

    # Helferfunktion, um alle Spielerdaten zu laden
    @st.cache_data
    def load_all_players():
        """Lädt alle Spielerdaten vom Backend und erstellt einen Index nach Name.
        Fügt Dummy-Daten für eine lauffähige Version hinzu."""

        player_list = []

        # Füge die Spieler aus der FIRST_ROUND_PAIRS Liste hinzu
        for i, name in enumerate(FIRST_ROUND_PAIRS):
            # Bestimme den Seed nur für die ersten 32 Spieler
            seed = (i // 2) + 1 if i < 64 and i % 2 == 0 else None

            # Erstelle eine ID, die für das Backend benötigt wird
            player_id = i + 1

            # Simuliere, dass nur die Top-Spieler Seeds haben
            player_list.append(
                {
                    "id": player_id,
                    "name": name,
                    "seed": seed if seed and seed <= 32 else None,
                }
            )

        try:
            # Versuche, echte Daten vom Backend zu laden
            response = requests.get(f"{BASE_URL}/players/")
            response.raise_for_status()
            players = response.json()
            df = pd.DataFrame(players)
        except (requests.exceptions.RequestException, KeyError) as e:
            # Bei Fehler oder fehlendem Backend: Verwende die Dummy-Daten
            st.warning(
                f"Konnte keine echten Spielerdaten laden (Fehler: {e}). Verwende Platzhalterdaten."
            )
            df = pd.DataFrame(player_list)

        # Erstellt ein DataFrame, das nach 'name' indiziert ist, für schnelles Nachschlagen
        df_indexed_by_name = df.set_index("name")
        return df_indexed_by_name

    # --- HAUPTTEIL DER ANWENDUNG ---
    if st.session_state.current_page == "overview":
        st.write("## 🏆 Darts World Championship Match-Overview")

        df_players_all = load_all_players()

        if df_players_all.empty:
            st.info(
                "Cannot load player data. Please ensure that the backend is reachable at {} and provides player data.".format(
                    BASE_URL
                )
            )
            st.stop()

        # Initialisiere den Gewinner-State
        if "winners" not in st.session_state:
            st.session_state["winners"] = {}

        # --- FIX: Speichere den aktuellen Match-State, bevor die Struktur neu aufgebaut wird ---
        # Dies ist notwendig, um ungespeicherte Stats zu behalten
        old_match_data = st.session_state.match_data.copy()
        st.session_state.match_data = {}

        # Lade existierende Ergebnisse und fülle den winners State (simuliert)
        try:
            results = []
            # Implementiere Exponential Backoff für den Request
            for attempt in range(3):
                try:
                    results_resp = requests.get(f"{BASE_URL}/matches/results/")
                    results_resp.raise_for_status()
                    results = results_resp.json()
                    break
                except Exception as e:
                    if attempt < 2:
                        time.sleep(2**attempt)
                    else:
                        st.error(f"Error loading match results after 3 attempts: {e}")
                        raise e

            # Verarbeite die geladenen Ergebnisse
            for match in results:
                match_id = match["match_id"]
                winner_id = match["winner_id"]

                try:
                    # Suche in der Spalte 'id' im DataFrame
                    winner_info = df_players_all[df_players_all["id"] == winner_id]
                    if winner_info.empty:
                        winner_display = f"Winner (ID: {winner_id} not found)"
                    else:
                        winner_info = winner_info.iloc[0]
                        winner_name = winner_info.name
                        winner_seed = winner_info["seed"]
                        if winner_seed <= 32 and winner_seed > 0:
                            winner_display = f"{winner_name} ({winner_seed})"
                        else:
                            winner_display = f"{winner_name}"
                except Exception:
                    winner_display = f"Winner (ID: {winner_id} not found)"

                st.session_state["winners"][match_id] = winner_display
        except Exception as e:
            st.error(
                f"Critical error in API communication/data processing: {e}. Show empty overview."
            )
            st.session_state["winners"] = {}

        # --- Tabelle aufbauen (für die visuelle Bracket-Darstellung) ---
        column_names = [f"Round {i+1}" for i in range(NUM_ROUNDS)]
        table = pd.DataFrame(
            "",
            index=range(ROWS),
            columns=column_names,
        )

        # Temporäre Match-Daten, um alle möglichen Matches zu speichern
        all_possible_match_data = {}

        # --- RUNDE 1: Spieler setzen und IDs speichern ---
        for i in range(NUM_MATCHES_ROUND_1):
            p1_name = FIRST_ROUND_PAIRS[i * 2]
            p2_name = FIRST_ROUND_PAIRS[i * 2 + 1]

            try:
                p1_info = df_players_all.loc[p1_name]
                p2_info = df_players_all.loc[p2_name]
            except KeyError as e:
                st.error(f"Player '{e.args[0]}' not found in the database.")
                continue

            p1_seed = p1_info.get("seed")
            p2_seed = p2_info.get("seed")
            p1_id = p1_info.get("id")
            p2_id = p2_info.get("id")

            if p1_seed <= 32 and p1_seed > 0:
                p1_display = f"{p1_name} ({p1_seed})"
            else:
                p1_display = f"{p1_name}"
            if p2_seed <= 32 and p2_seed > 0:
                p2_display = f"{p2_name} ({p2_seed})"
            else:
                p2_display = f"{p2_name}"

            row_p1 = i * 2
            row_p2 = i * 2 + 1

            match_id_r1 = f"match_{row_p1}_{1}"

            # 1. Speichere Basis-Match-Daten
            current_match_data_r1 = {
                "p1_id": p1_id,
                "p2_id": p2_id,
                "p1_name_display": p1_display,
                "p2_name_display": p2_display,
            }
            all_possible_match_data[match_id_r1] = current_match_data_r1

            # 2. Fülle die Tabelle
            winner_display = st.session_state["winners"].get(match_id_r1)

            if winner_display:
                if winner_display == p1_display:
                    table.iloc[row_p1, 0] = p1_display
                    table.iloc[row_p2, 0] = f"~{p2_display}~"
                elif winner_display == p2_display:
                    table.iloc[row_p1, 0] = f"~{p1_display}~"
                    table.iloc[row_p2, 0] = p2_display
                else:
                    table.iloc[row_p1, 0] = winner_display
                    table.iloc[row_p2, 0] = f"~{p2_display}~"
            else:
                # Match ist offen, zeige beide Namen unverändert
                table.iloc[row_p1, 0] = p1_display
                table.iloc[row_p2, 0] = p2_display

                # --- FIX: Übernehme alte, ungespeicherte Stats, falls vorhanden ---
                if match_id_r1 in old_match_data:
                    # Kopiere die alten, ungespeicherten Stats in den neuen State
                    st.session_state.match_data[match_id_r1] = {
                        **current_match_data_r1,
                        **old_match_data[match_id_r1],
                    }
                else:
                    # Füge das Match neu zu den offenen Matches hinzu (nur Basisdaten)
                    st.session_state.match_data[match_id_r1] = current_match_data_r1

        # --- Weitere Runden: Gewinner weiterleiten oder Platzhalter setzen ---
        for r in range(1, NUM_ROUNDS):
            step = 2**r
            step_prev = 2 ** (r - 1)

            for i in range(0, ROWS, step * 2):
                match_id = f"match_{i}_{r + 1}"

                match_id_p1_predecessor = f"match_{i}_{r}"
                match_id_p2_predecessor = f"match_{i + step}_{r}"

                p1_predecessor_won = (
                    match_id_p1_predecessor in st.session_state["winners"]
                )
                p2_predecessor_won = (
                    match_id_p2_predecessor in st.session_state["winners"]
                )

                row_p1_current = i + step_prev - 1
                row_p2_current = i + step + step_prev - 1

                if p1_predecessor_won and p2_predecessor_won:

                    p1_full_name = st.session_state["winners"][match_id_p1_predecessor]
                    p2_full_name = st.session_state["winners"][match_id_p2_predecessor]

                    p1_base_name = extract_base_name(p1_full_name)
                    p2_base_name = extract_base_name(p2_full_name)

                    try:
                        p1_id_r = df_players_all.loc[p1_base_name, "id"]
                        p2_id_r = df_players_all.loc[p2_base_name, "id"]
                    except KeyError:
                        table.iloc[row_p1_current, r] = "ID-Error!"
                        table.iloc[row_p2_current, r] = "ID-Error!"
                        continue

                    # Basis-Match-Daten für die aktuelle Runde
                    current_match_data = {
                        "p1_id": p1_id_r,
                        "p2_id": p2_id_r,
                        "p1_name_display": p1_full_name,
                        "p2_name_display": p2_full_name,
                    }
                    all_possible_match_data[match_id] = current_match_data

                    winner_display = st.session_state["winners"].get(match_id)

                    if winner_display:
                        # Match ist abgeschlossen
                        if winner_display == p1_full_name:
                            table.iloc[row_p1_current, r] = p1_full_name
                            table.iloc[row_p2_current, r] = f"~{p2_full_name}~"
                        elif winner_display == p2_full_name:
                            table.iloc[row_p1_current, r] = f"~{p1_full_name}~"
                            table.iloc[row_p2_current, r] = p2_full_name
                        else:
                            table.iloc[row_p1_current, r] = winner_display
                            table.iloc[row_p2_current, r] = f"~{p2_full_name}~"

                    else:
                        # Match ist offen und spielbereit
                        table.iloc[row_p1_current, r] = p1_full_name
                        table.iloc[row_p2_current, r] = p2_full_name

                        # --- FIX: Übernehme alte, ungespeicherte Stats, falls vorhanden ---
                        if match_id in old_match_data:
                            # Merge Basisdaten mit alten, ungespeicherten Stats
                            st.session_state.match_data[match_id] = {
                                **current_match_data,
                                **old_match_data[match_id],
                            }
                        else:
                            st.session_state.match_data[match_id] = current_match_data

                else:
                    # Setze die Platzhalter, da die Vormatches noch nicht entschieden sind
                    table.iloc[row_p1_current, r] = "TBD"
                    table.iloc[row_p2_current, r] = "TBD"

        # --- Visuelle Darstellung der Tabelle (Bracket) ---
        st.dataframe(
            table,
            hide_index=True,
            use_container_width=True,
        )

        # --- NEUE KORRIGIERTE AUSGABE: LISTE DER MATCHES ---
        st.markdown("---")

        # 1. Sammle alle offenen Matches (nur jene, die in st.session_state.match_data sind)
        all_open_matches = [
            (match_id, data)
            for match_id, data in st.session_state.match_data.items()
            if match_id not in st.session_state["winners"]
        ]

        # 2. Finde die niedrigste Runden-Nummer mit offenen Matches
        min_open_round = min(
            [get_round_num(match_id) for match_id, _ in all_open_matches],
            default=NUM_ROUNDS + 1,
        )

        # 3. Filtere die Liste, um NUR Matches dieser niedrigsten offenen Runde anzuzeigen
        open_matches = [
            (match_id, data)
            for match_id, data in all_open_matches
            if get_round_num(match_id) == min_open_round
        ]

        # ABGESCHLOSSENE MATCHES:
        closed_matches = [
            (match_id, data)
            for match_id, data in all_possible_match_data.items()
            if match_id in st.session_state["winners"]
        ]

        # --- Helferfunktion zur Sortierung ---
        def sort_key(item):
            match_id = item[0]
            try:
                parts = match_id.split("_")
                round_num = int(parts[-1])
                start_row = int(parts[-2])
                return round_num, start_row
            except:
                return 999, 0

        open_matches.sort(key=sort_key)
        closed_matches.sort(key=sort_key)

        # --- 2. Anzeige der offenen Matches ---
        st.write("### 🎯 Open Matches (Round {})".format(min_open_round))
        if not open_matches:
            st.info(
                "No open matches available. The tournament might be concluded or you must enter preliminary round results."
            )
        else:
            for match_id, match_data in open_matches:
                p1_display = match_data["p1_name_display"]
                p2_display = match_data["p2_name_display"]

                try:
                    round_num = get_round_num(match_id)
                except:
                    round_num = "?"

                col1, col2 = st.columns([0.7, 0.3])

                col1.markdown(
                    f"**Round {round_num}:** **{p1_display}** vs. **{p2_display}**"
                )

                # Button, um zur Detailseite zu wechseln
                if col2.button("Capture Result 📝", key=f"enter_score_{match_id}"):
                    st.session_state.current_match = match_id
                    st.session_state.current_page = "match_detail"
                    st.rerun()

                st.markdown("---")

        # --- 3. Anzeige der abgeschlossenen Matches ---
        st.write("### ✅ Completed Matches")
        if not closed_matches:
            st.info("No results have been recorded yet.")
        else:
            for match_id, match_data in closed_matches:
                p1_display = match_data["p1_name_display"]
                p2_display = match_data["p2_name_display"]
                winner_text = st.session_state["winners"].get(match_id)

                try:
                    round_num = get_round_num(match_id)
                except:
                    round_num = "?"

                col1, col2 = st.columns([0.2, 0.8])

                col1.markdown(f"Round {round_num}:")

                p1_base = extract_base_name(p1_display)
                p2_base = extract_base_name(p2_display)
                winner_base = extract_base_name(winner_text)

                if winner_text == p1_display:
                    display_string = f"**{p1_base}** defeats ~~{p2_base}~~"
                elif winner_text == p2_display:
                    display_string = f"**{p2_base}** defeats ~~{p1_base}~~"
                else:
                    display_string = (
                        f"{p1_base} vs. {p2_base}. Winner: **{winner_base}**"
                    )

                col2.markdown(display_string, unsafe_allow_html=True)
                st.markdown("---")

    # --- MATCH DETAIL SEITE (Jetzt mit eindeutigen Keys und korrekter Speicherung) ---
    elif st.session_state.current_page == "match_detail":
        match_id = st.session_state.current_match

        # NEU: Daten werden direkt aus der Session geholt.
        # Wenn die Seite lädt, werden die Keys im Session State mit Werten gefüllt,
        # die aus match_data als 'value' in number_input übergeben werden.
        match_info = st.session_state.match_data.get(match_id, {})

        p1_id = match_info.get("p1_id", -1)
        p2_id = match_info.get("p2_id", -1)
        p1_name_display = match_info.get("p1_name_display", "N/A")
        p2_name_display = match_info.get("p2_name_display", "N/A")

        try:
            round_num = int(match_id.split("_")[-1])
            max_sets = {1: 5, 2: 5, 3: 7, 4: 7, 5: 9, 6: 11}.get(round_num, 7)
        except:
            max_sets = 7
            round_num = "?"

        sets_to_win = (max_sets // 2) + 1

        st.write(f"### 🏹 Match Details – Round {round_num}")
        st.markdown(
            f"**{p1_name_display}** (ID: {p1_id}) vs. **{p2_name_display}** (ID: {p2_id})"
        )
        st.markdown(f"Best-of {max_sets} Sets. Needed to win: {sets_to_win} Sets.")
        st.markdown("---")

        col1, col2 = st.columns(2)

        # Definition der eindeutigen Keys
        KEY_SETS_P1 = f"sets_{match_id}"
        KEY_LEGS_P1 = f"legs_{match_id}"
        KEY_180S_P1 = f"180s_{match_id}"
        KEY_HIGH_CHECKOUT_P1 = f"high_checkout_{match_id}"
        KEY_AVERAGE_P1 = f"average_{match_id}"
        KEY_CHECKOUT_PCT_P1 = f"checkout_pct_{match_id}"

        KEY_SETS_P2 = f"sets_p2_{match_id}"
        KEY_LEGS_P2 = f"legs_p2_{match_id}"
        KEY_180S_P2 = f"180s_p2_{match_id}"
        KEY_HIGH_CHECKOUT_P2 = f"high_checkout_p2_{match_id}"
        KEY_AVERAGE_P2 = f"average_p2_{match_id}"
        KEY_CHECKOUT_PCT_P2 = f"checkout_pct_p2_{match_id}"

        # Hilfsfunktion, um den Wert aus match_info oder 0/0.0 zu holen
        def get_initial_value(key_base, default_value):
            # Die Match-Info enthält die Keys ohne match_id Suffix
            return match_info.get(key_base, default_value)

        # Input-Felder für Spieler 1
        col1.subheader(f"{p1_name_display}")

        p1_sets = col1.number_input(
            "Sets won",
            key=KEY_SETS_P1,  # NEU: Eindeutiger Key
            min_value=0,
            max_value=max_sets,
            step=1,
            value=get_initial_value("sets", 0),
        )
        col1.number_input(
            "Legs won",
            key=KEY_LEGS_P1,  # NEU: Eindeutiger Key
            min_value=0,
            step=1,
            value=get_initial_value("legs", 0),
        )
        col1.number_input(
            "180s",
            key=KEY_180S_P1,  # NEU: Eindeutiger Key
            min_value=0,
            step=1,
            value=get_initial_value("180s", 0),
        )
        col1.number_input(
            "Highest Checkout",
            key=KEY_HIGH_CHECKOUT_P1,  # NEU: Eindeutiger Key
            min_value=0,
            max_value=170,
            step=1,
            value=get_initial_value("high_checkout", 0),
        )
        col1.number_input(
            "Average",
            key=KEY_AVERAGE_P1,  # NEU: Eindeutiger Key
            min_value=0.0,
            step=0.01,
            format="%.2f",
            value=get_initial_value("average", 0.0),
        )
        col1.number_input(
            "Checkout %",
            key=KEY_CHECKOUT_PCT_P1,  # NEU: Eindeutiger Key
            min_value=0.0,
            max_value=100.0,
            step=0.01,
            format="%.2f",
            value=get_initial_value("checkout_pct", 0.0),
        )

        # Input-Felder für Spieler 2
        col2.subheader(f"{p2_name_display}")

        p2_sets = col2.number_input(
            "Sets won",
            key=KEY_SETS_P2,  # NEU: Eindeutiger Key
            min_value=0,
            max_value=max_sets,
            step=1,
            value=get_initial_value("sets_p2", 0),
        )
        col2.number_input(
            "Legs won",
            key=KEY_LEGS_P2,  # NEU: Eindeutiger Key
            min_value=0,
            step=1,
            value=get_initial_value("legs_p2", 0),
        )
        col2.number_input(
            "180s",
            key=KEY_180S_P2,  # NEU: Eindeutiger Key
            min_value=0,
            step=1,
            value=get_initial_value("180s_p2", 0),
        )
        col2.number_input(
            "Highest Checkout",
            key=KEY_HIGH_CHECKOUT_P2,  # NEU: Eindeutiger Key
            min_value=0,
            max_value=170,
            step=1,
            value=get_initial_value("high_checkout_p2", 0),
        )
        col2.number_input(
            "Average",
            key=KEY_AVERAGE_P2,  # NEU: Eindeutiger Key
            min_value=0.0,
            step=0.01,
            format="%.2f",
            value=get_initial_value("average_p2", 0.0),
        )
        col2.number_input(
            "Checkout %",
            key=KEY_CHECKOUT_PCT_P2,  # NEU: Eindeutiger Key
            min_value=0.0,
            max_value=100.0,
            step=0.01,
            format="%.2f",
            value=get_initial_value("checkout_pct_p2", 0.0),
        )

        # --- Aktualisiere Session State (Dies muss manuell erfolgen, da number_input
        # --- die Werte unter den eindeutigen Keys speichert, aber match_data die Basisdaten braucht) ---
        st.session_state.match_data[match_id]["sets"] = st.session_state[KEY_SETS_P1]
        st.session_state.match_data[match_id]["legs"] = st.session_state[KEY_LEGS_P1]
        st.session_state.match_data[match_id]["180s"] = st.session_state[KEY_180S_P1]
        st.session_state.match_data[match_id]["high_checkout"] = st.session_state[
            KEY_HIGH_CHECKOUT_P1
        ]
        st.session_state.match_data[match_id]["average"] = st.session_state[
            KEY_AVERAGE_P1
        ]
        st.session_state.match_data[match_id]["checkout_pct"] = st.session_state[
            KEY_CHECKOUT_PCT_P1
        ]

        st.session_state.match_data[match_id]["sets_p2"] = st.session_state[KEY_SETS_P2]
        st.session_state.match_data[match_id]["legs_p2"] = st.session_state[KEY_LEGS_P2]
        st.session_state.match_data[match_id]["180s_p2"] = st.session_state[KEY_180S_P2]
        st.session_state.match_data[match_id]["high_checkout_p2"] = st.session_state[
            KEY_HIGH_CHECKOUT_P2
        ]
        st.session_state.match_data[match_id]["average_p2"] = st.session_state[
            KEY_AVERAGE_P2
        ]
        st.session_state.match_data[match_id]["checkout_pct_p2"] = st.session_state[
            KEY_CHECKOUT_PCT_P2
        ]

        # NEU: Verwende die Werte direkt aus dem Session State, die durch number_input gesetzt wurden
        p1_sets_final = st.session_state[KEY_SETS_P1]
        p2_sets_final = st.session_state[KEY_SETS_P2]

        st.markdown("---")
        col_buttons = st.columns(2)

        if col_buttons[0].button("Back to Overview"):
            st.session_state.current_page = "overview"
            st.rerun()

        # Überprüfe die Siegesbedingung
        is_p1_winner = p1_sets_final >= sets_to_win and p1_sets_final > p2_sets_final
        is_p2_winner = p2_sets_final >= sets_to_win and p2_sets_final > p1_sets_final
        is_valid_match = is_p1_winner or is_p2_winner

        if not is_valid_match and (p1_sets_final > 0 or p2_sets_final > 0):
            st.warning(
                f"The match is not yet completed. {sets_to_win} sets required to win."
            )

        if col_buttons[1].button(
            "Save and Conclude Match",
            disabled=not is_valid_match,
            type="primary",
        ):

            # Gewinnerbestimmung
            if is_p1_winner:
                winner_id = p1_id
                winner_display = p1_name_display
            elif is_p2_winner:
                winner_id = p2_id
                winner_display = p2_name_display
            else:
                st.error("Internal Error: Invalid result before saving.")
                st.stop()

            # Payload wird aus den Werten des Session State erstellt, die durch die number_inputs gesetzt wurden
            payload = {
                "match_id": match_id,
                "p1_id": int(p1_id),
                "p2_id": int(p2_id),
                "winner_id": int(winner_id),
                "sets_p1": st.session_state[KEY_SETS_P1],
                "sets_p2": st.session_state[KEY_SETS_P2],
                "legs_p1": st.session_state[KEY_LEGS_P1],
                "legs_p2": st.session_state[KEY_LEGS_P2],
                "average_p1": st.session_state[KEY_AVERAGE_P1],
                "average_p2": st.session_state[KEY_AVERAGE_P2],
                "checkout_pct_p1": st.session_state[KEY_CHECKOUT_PCT_P1],
                "checkout_pct_p2": st.session_state[KEY_CHECKOUT_PCT_P2],
                "high_checkout_p1": st.session_state[KEY_HIGH_CHECKOUT_P1],
                "high_checkout_p2": st.session_state[KEY_HIGH_CHECKOUT_P2],
                "180s_p1": st.session_state[KEY_180S_P1],
                "180s_p2": st.session_state[KEY_180S_P2],
            }

            # --- Speichere Daten im Backend (Mocked) ---
            try:
                for attempt in range(3):
                    try:
                        resp = requests.put(
                            f"{BASE_URL}/matches/save_match/", json=payload
                        )
                        requests.put(
                            f"{BASE_URL}/players/points/recompute", json=payload
                        )
                        resp.raise_for_status()
                        break
                    except requests.exceptions.RequestException as e:
                        if attempt < 2:
                            st.warning(
                                f"Attempt {attempt+1}: Error saving the match: {e}. Trying again..."
                            )
                            time.sleep(2**attempt)
                        else:
                            raise e

                # Aktualisiere den Gewinner-Status und kehre zur Übersicht zurück
                st.session_state["winners"][match_id] = winner_display

                # NEU: Entferne das Match aus match_data, da es nun abgeschlossen ist
                if match_id in st.session_state.match_data:
                    del st.session_state.match_data[match_id]

                st.success(
                    f"Result for {p1_name_display} vs. {p2_name_display} successfully saved! Winner: {winner_display}"
                )
                st.session_state.current_page = "overview"
                st.rerun()

            except requests.exceptions.RequestException as e:
                error_message = f"Error saving the match in the backend: {e}"
                if "resp" in locals():
                    error_message += f"\nResponse: {resp.text}"
                st.error(error_message)
    # if st.session_state.current_page != "match_detail":
    #     st.write("## 🗓 Match Schedule")
    #     players = requests.get(f"{BASE_URL}/players/").json()
    #     df_players = pd.DataFrame(players)
    #     df_players = df_players.sort_values("seed").head(64).reset_index(drop=True)

    #     num_players = 64
    #     num_rounds = int(math.log2(num_players))
    #     rows = num_players * 2 - 1

    #     # --- Seed-Reihenfolge generieren ---
    #     def generate_bracket(n):
    #         if n == 1:
    #             return [1]
    #         prev = generate_bracket(n // 2)
    #         result = []
    #         for p in prev:
    #             result.append(p)
    #             result.append(n + 1 - p)
    #         return result

    #     bracket = generate_bracket(num_players)

    #     # --- Session-State initialisieren ---

    #     if "winners" not in st.session_state:
    #         st.session_state["winners"] = {}

    #     results = requests.get(f"{BASE_URL}/matches/results/").json()
    #     for match in results:
    #         match_id = match["match_id"]
    #         winner_id = match["winner_id"]
    #         winner = f"{df_players.loc[df_players['id'] == winner_id, 'name'].values[0]} ({df_players.loc[df_players['id'] == winner_id, 'seed'].values[0]})"
    #         st.session_state["winners"][match_id] = winner

    #     if "match_data" not in st.session_state:
    #         st.session_state["match_data"] = {}
    #     if "current_match" not in st.session_state:
    #         st.session_state["current_match"] = None

    #     # --- Tabelle aufbauen ---
    #     table = pd.DataFrame(
    #         "",
    #         index=range(rows),
    #         columns=[f"Round {i+1}" for i in range(num_rounds)],
    #     )

    #     # Runde 1
    #     for i, seed in enumerate(bracket):
    #         row = i * 2
    #         player = f"{df_players.loc[seed-1, 'name']} ({seed})"
    #         table.iloc[row, 0] = player

    #     # Weitere Runden: Platzhalter setzen
    #     for r in range(1, num_rounds):
    #         step = 2**r
    #         for i in range(0, rows, step * 2):
    #             row_winner = i + step - 1
    #             match_id = f"match_{row_winner}_{r}"
    #             table.iloc[row_winner, r] = st.session_state["winners"].get(
    #                 match_id, "?"
    #             )

    #     # --- Dynamische Breite ---
    #     max_name_len = max(len(str(name)) for name in df_players["name"])
    #     button_width = int(max_name_len * 8.5 + 60)

    #     for r in range(1, num_rounds):
    #         step = 2**r
    #         for i in range(0, rows, step * 2):
    #             row_winner = i + step - 1
    #             match_id = f"match_{row_winner}_{r}"
    #             p1_row = i
    #             p2_row = i + step
    #             p1_name = table.iloc[p1_row, r - 1]
    #             p2_name = table.iloc[p2_row, r - 1]

    #             # Nur echte Spieler anzeigen (nicht leere Zellen)
    #             if p1_name != "" and p2_name != "":
    #                 cols = st.columns([2, 2, 1])
    #                 cols[0].markdown(f"**{p1_name}**")
    #                 cols[1].markdown(f"**{p2_name}**")
    #                 if cols[2].button("Edit", key=match_id):
    #                     st.session_state.current_match = match_id
    #                     st.session_state.current_page = "match_detail"
    #                     st.session_state.match_data[match_id] = {
    #                         "p1_name": p1_name,
    #                         "p2_name": p2_name,
    #                         "legs": None,
    #                         "180s": None,
    #                         "sets": None,
    #                         "high_checkout": None,
    #                         "average": None,
    #                         "checkout_pct": None,
    #                     }
    #                     st.rerun()

    # elif st.session_state.current_page == "match_detail":
    #     match_id = st.session_state.current_match
    #     match_info = st.session_state.match_data[match_id]
    #     players = requests.get(f"{BASE_URL}/players/").json()
    #     df_players = pd.DataFrame(players)
    #     player_base_name1 = re.match(r"^(.*?) \(\d+\)$", match_info["p1_name"])
    #     if player_base_name1:
    #         player_base_name1 = player_base_name1.group(1)
    #     else:
    #         player_base_name1 = match_info["p1_name"]

    #     player_base_name2 = re.match(r"^(.*?) \(\d+\)$", match_info["p2_name"])
    #     if player_base_name2:
    #         player_base_name2 = player_base_name2.group(1)
    #     else:
    #         player_base_name2 = match_info["p2_name"]

    #     p1_id = df_players.loc[df_players["name"] == player_base_name1, "id"].values[0]
    #     p2_id = df_players.loc[df_players["name"] == player_base_name2, "id"].values[0]
    #     st.write(f"### 🏹 Match Details – {match_id}")
    #     st.write(f"**Player 1:** {match_info["p1_name"]}")
    #     st.write(f"**Player 2:** {match_info["p2_name"]}")

    #     # Stats-Eingabe
    #     match_info["sets"] = st.number_input(
    #         f"Sets {match_info["p1_name"]}",
    #         min_value=0,
    #         max_value=50,
    #         key=f"{match_id}_sets_p1",
    #     )
    #     match_info["legs"] = st.number_input(
    #         f"Legs {match_info["p1_name"]}",
    #         min_value=0,
    #         max_value=50,
    #         key=f"{match_id}_legs_p1",
    #     )
    #     match_info["180s"] = st.number_input(
    #         f"180s {match_info["p1_name"]}",
    #         min_value=0,
    #         max_value=50,
    #         key=f"{match_id}_180s_p1",
    #     )
    #     match_info["high_checkout"] = st.number_input(
    #         f"High Checkout {match_info["p1_name"]}",
    #         min_value=0,
    #         max_value=180,
    #         key=f"{match_id}_high_p1",
    #     )
    #     match_info["average"] = st.number_input(
    #         f"Average {match_info["p1_name"]}",
    #         min_value=0.0,
    #         max_value=200.0,
    #         key=f"{match_id}_avg_p1",
    #     )
    #     match_info["checkout_pct"] = st.number_input(
    #         f"Checkout % {match_info["p1_name"]}",
    #         min_value=0.0,
    #         max_value=100.0,
    #         key=f"{match_id}_co_p1",
    #     )

    #     match_info["sets_p2"] = st.number_input(
    #         f"Sets {match_info["p2_name"]}",
    #         min_value=0,
    #         max_value=50,
    #         key=f"{match_id}_sets_p2",
    #     )
    #     match_info["legs_p2"] = st.number_input(
    #         f"Legs {match_info["p2_name"]}",
    #         min_value=0,
    #         max_value=50,
    #         key=f"{match_id}_legs_p2",
    #     )
    #     match_info["180s_p2"] = st.number_input(
    #         f"180s {match_info["p2_name"]}",
    #         min_value=0,
    #         max_value=50,
    #         key=f"{match_id}_180s_p2",
    #     )
    #     match_info["high_checkout_p2"] = st.number_input(
    #         f"High Checkout {match_info["p2_name"]}",
    #         min_value=0,
    #         max_value=180,
    #         key=f"{match_id}_high_p2",
    #     )
    #     match_info["average_p2"] = st.number_input(
    #         f"Average {match_info["p2_name"]}",
    #         min_value=0.0,
    #         max_value=200.0,
    #         key=f"{match_id}_avg_p2",
    #     )
    #     match_info["checkout_pct_p2"] = st.number_input(
    #         f"Checkout % {match_info["p2_name"]}",
    #         min_value=0.0,
    #         max_value=100.0,
    #         key=f"{match_id}_co_p2",
    #     )
    #     if st.button("Back"):
    #         st.session_state.current_page = "overview"
    #         st.rerun()
    #     if st.button("Save Match"):
    #         players = requests.get(f"{BASE_URL}/players/").json()
    #         df_players = pd.DataFrame(players)
    #         df_players = df_players.sort_values("seed").head(64).reset_index(drop=True)
    #         # Gewinner bestimmen
    #         winner_id = p1_id if match_info["sets"] > match_info["sets_p2"] else p2_id
    #         winner_name = (
    #             match_info["p2_name"]
    #             if match_info["sets"] > match_info["sets_p2"]
    #             else match_info["p2_name"]
    #         )
    #         payload = {
    #             "match_id": match_id,
    #             "p1_id": int(p1_id),
    #             "p2_id": int(p2_id),
    #             "winner_id": int(winner_id),
    #             "sets_p1": match_info["sets"],
    #             "sets_p2": match_info["sets_p2"],
    #             "legs_p1": match_info["legs"],
    #             "legs_p2": match_info["legs_p2"],
    #             # optional weitere stats
    #             "average_p1": match_info["average"],
    #             "average_p2": match_info["average_p2"],
    #             "checkout_pct_p1": match_info["checkout_pct"],
    #             "checkout_pct_p2": match_info["checkout_pct_p2"],
    #             "high_checkout_p1": match_info["high_checkout"],
    #             "high_checkout_p2": match_info["high_checkout_p2"],
    #             "180s_p1": match_info["180s"],
    #             "180s_p2": match_info["180s_p2"],
    #         }

    #         resp = requests.put(f"{BASE_URL}/matches/save_match/", json=payload)
    #         try:
    #             msg = resp.json().get("msg", "No message returned")
    #         except ValueError:
    #             # Kein JSON erhalten
    #             msg = f"Error: server returned status {resp.status_code}, body: {resp.text}"
    #         requests.put(f"{BASE_URL}/players/points/recompute", json=payload)
    #         st.session_state.current_match = None
    #         st.session_state.current_page = "overview"
    #         st.rerun()
# -----------------------------------
# 🔹 Team erstellen
# -----------------------------------
elif page == "🧩 Teams":
    if "user_id" not in st.session_state:
        st.warning("⚠️ Please log in to create a team!")
        st.stop()

    st.title("🧩 Your Teams")

    # --- 1. Load user's teams ---
    try:
        user_teams = requests.get(
            f"{BASE_URL}/teams/user/{st.session_state.user_id}"
        ).json()
        df_teams = pd.DataFrame(user_teams)
        if not df_teams.empty:
            st.subheader("📝 Your Existing Teams")
            df_teams = df_teams.sort_values(
                by="total_points", ascending=False
            ).reset_index(drop=True)
            df_teams.insert(0, "Rank", df_teams.index + 1)

            for i, row in df_teams.iterrows():
                cols = st.columns([1, 4, 2, 2, 2])
                cols[0].write(row["Rank"])
                cols[1].write(row["team_name"])
                cols[2].write(row["total_points"])
                if cols[3].button("✏️ Edit", key=f"edit_{row['team_id']}"):
                    # Speichere Team für Edit
                    st.session_state.edit_team_id = row["team_id"]
                    st.session_state.edit_team_name = row["team_name"]
                    st.session_state.current_page = "edit_team"
                    st.rerun()

                if cols[4].button("🗑 Delete", key=f"delete_{row['team_id']}"):
                    try:
                        response = requests.delete(f"{BASE_URL}/teams/{row['team_id']}")
                        if response.status_code == 200:
                            st.success(
                                f"Team '{row['team_name']}' deleted successfully!"
                            )
                            st.session_state.current_page = "overview"
                            st.rerun()  # Seite neu laden, damit gelöschtes Team verschwindet
                        else:
                            st.error(f"Error deleting team: {response.text}")
                    except Exception as e:
                        st.error(f"Error deleting team: {e}")
        else:
            st.info("You have not created any teams yet.")
    except Exception as e:
        st.warning(f"Could not load your teams: {e}")

    st.markdown("---")

    if st.session_state.get("current_page", "") not in ["edit_team", "create_new_team"]:
        if st.button("➕ Create New Team"):
            # Bereite Session State für Team Creation vor
            st.session_state.selected_ids = []
            st.session_state.current_page = "create_new_team"
            st.rerun()


# --- 3. Edit Team oder Create New Team Seiten ---
if "current_page" in st.session_state:

    # 🟦 --- EDIT EXISTING TEAM ---
    if st.session_state.current_page == "edit_team":
        if st.button("⬅️ Back to Teams"):
            st.session_state.current_page = (
                "overview"  # oder "teams_overview" je nach deinem Setup
            )
            st.rerun()
        team_id = st.session_state.edit_team_id
        team_name = st.session_state.edit_team_name
        st.title(f"✏️ Edit Team: {team_name}")

        TOTAL_BUDGET = 20000

        # --- Lade Team-Spieler (mit Rollen) ---
        # Annahme: Der Endpoint /teams/{team_id}/players gibt jetzt auch is_captain/is_underdog zurück
        try:
            team_players = requests.get(f"{BASE_URL}/teams/{team_id}/players").json()
        except Exception as e:
            st.error(f"Error loading team players: {e}")
            st.stop()

        # IDs der aktuellen Teamspieler & Rollen finden
        if isinstance(team_players, list):
            current_player_ids = [p["id"] for p in team_players]

            # NEU: Aktuelle Rollen bestimmen
            current_captain = next(
                (p for p in team_players if p.get("is_captain")), None
            )
            current_underdog = next(
                (p for p in team_players if p.get("is_underdog")), None
            )
        else:
            current_player_ids = []
            current_captain = None
            current_underdog = None

        # --- Lade alle Spieler ---
        try:
            players = requests.get(f"{BASE_URL}/players/").json()
        except Exception as e:
            st.error(f"Error loading the player list: {e}")
            players = []

        if not isinstance(players, list) or len(players) == 0:
            st.error("❌ No players found!")
            st.stop()

        # --- DataFrame vorbereiten ---
        df = pd.DataFrame(players)
        df["selected"] = df["id"].isin(current_player_ids)

        def get_flag_url(nation):
            code = COUNTRY_CODE_MAP.get(nation.strip())
            return f"{BASE_FLAG_URL}{code}.svg" if code else ""

        df["flag_url"] = df["nation"].apply(get_flag_url)

        # --- Tabelle anzeigen ---
        edited_df = st.data_editor(
            df,
            column_config={
                "seed": st.column_config.Column("Seed", width="small"),
                "name": st.column_config.Column("Name"),
                "price": st.column_config.Column("Price"),
                "flag_url": st.column_config.ImageColumn("Nation", width="small"),
                "selected": st.column_config.CheckboxColumn("Select"),
            },
            column_order=["seed", "name", "price", "flag_url", "selected"],
            hide_index=True,
            width="stretch",
            disabled=[
                "seed",
                "name",
                "price",
                "nation",
                "id",
                "points",
                "eliminated",
            ],  # id, points, eliminated hinzugefügt
            key="edit_team_editor",
        )

        # --- Auswahl aktualisieren ---
        # selected_df = edited_df[edited_df["selected"]]
        selected_df = edited_df[edited_df["selected"]].copy()
        # selected_ids = selected_df["id"].tolist()
        selected_ids = selected_df["id"].apply(int).tolist()
        total_spent = selected_df["price"].sum()
        remaining_budget = TOTAL_BUDGET - total_spent
        selected_count = len(selected_ids)

        # --- Budgetanzeige ---
        st.markdown(
            f"""
            ### 💰 Budget
            - **Total:** {TOTAL_BUDGET:,.2f}  
            - **Used:** {total_spent:,.2f}  
            - **Remaining:** <span style="color:{'red' if remaining_budget < 0 else 'green'}">{remaining_budget:,.2f}</span>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(f"### 🧍 Selected Players: {selected_count} / 15")

        # --- Captain und Underdog Auswahl (NEU) ---
        captain_id = None
        underdog_id = None
        can_select_roles = False

        if selected_count == 15 and remaining_budget >= 0:
            st.markdown("---")
            st.subheader("⭐ Select Captain & Underdog")

            player_options = selected_df.set_index("id")["name"].to_dict()
            default_captain_name = current_captain["name"] if current_captain else None

            # 1. Captain-Auswahl
            captain_name = st.selectbox(
                "Select your **Team Captain** (x2 Points):",
                options=player_options.values(),
                index=(
                    list(player_options.values()).index(default_captain_name)
                    if default_captain_name in player_options.values()
                    else 0
                ),
                key="edit_captain_select",
            )
            # captain_id = selected_df[selected_df["name"] == captain_name]["id"].iloc[0]
            captain_id = int(
                selected_df[selected_df["name"] == captain_name]["id"].iloc[0]
            )
            # 2. Underdog-Auswahl
            underdog_candidates = selected_df[selected_df["price"] < 800]
            underdog_options = underdog_candidates.set_index("id")["name"].to_dict()
            default_underdog_name = (
                current_underdog["name"] if current_underdog else None
            )

            if underdog_options:
                default_underdog_index = (
                    list(underdog_options.values()).index(default_underdog_name)
                    if default_underdog_name in underdog_options.values()
                    else 0
                )

                underdog_name = st.selectbox(
                    "Select your **Underdog** (Price < 800.0):",
                    options=underdog_options.values(),
                    index=default_underdog_index,
                    key="edit_underdog_select",
                )
                # underdog_id = underdog_candidates[
                #     underdog_candidates["name"] == underdog_name
                # ]["id"].iloc[0]
                underdog_id = int(
                    underdog_candidates[underdog_candidates["name"] == underdog_name][
                        "id"
                    ].iloc[0]
                )
                can_select_roles = True
            else:
                st.error(
                    "❌ No eligible Underdog player (Price < 800.0) selected in your team!"
                )
                can_select_roles = False

        # --- Aktuelles Team anzeigen ---
        if not selected_df.empty:
            st.subheader("✅ Your Current Team")
            # Füge hier die Kennzeichnung des Captains/Underdogs hinzu (optional)

            # Code zur Kennzeichnung:
            selected_df["Role"] = ""
            if captain_id in selected_ids:
                selected_df.loc[selected_df["id"] == captain_id, "Role"] = "CAPTAIN 👑"
            if underdog_id in selected_ids:
                selected_df.loc[selected_df["id"] == underdog_id, "Role"] += (
                    " / UNDERDOG 🐕 (x2)"
                    if selected_df.loc[selected_df["id"] == underdog_id, "Role"].iloc[0]
                    else "UNDERDOG 🐕 (x2)"
                )

            st.dataframe(
                selected_df[["seed", "name", "price", "flag_url", "Role"]],
                column_config={
                    "seed": st.column_config.Column("Seed", width="tiny"),
                    "name": st.column_config.Column("Player Name"),
                    "price": st.column_config.Column("Price"),
                    "flag_url": st.column_config.ImageColumn("Flag", width="tiny"),
                    "Role": st.column_config.Column("Role", width="medium"),
                },
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("No players selected yet.")

        # --- Update / Save Button ---
        can_save = (
            (selected_count == 15) and (remaining_budget >= 0) and can_select_roles
        )
        if can_save:
            if st.button("💾 Save Team Changes"):
                # NEU: captain_id und underdog_id zum Payload hinzufügen
                payload = {
                    "player_ids": selected_ids,
                    "captain_id": captain_id,
                    "underdog_id": underdog_id,
                }

                response = requests.put(f"{BASE_URL}/teams/{team_id}", json=payload)
                if response.status_code == 200:
                    st.success("Team updated successfully!")
                    st.session_state.current_page = "overview"
                    st.rerun()
                else:
                    st.error(f"Error updating team: {response.text}")
        else:
            st.warning("Team not valid (check 15 players, budget, and selected roles).")

    # 🟩 --- CREATE NEW TEAM ---
    elif st.session_state.current_page == "create_new_team":
        if st.button("⬅️ Back to Teams"):
            st.session_state.current_page = (
                "overview"  # oder "teams_overview" je nach deinem Setup
            )
            st.rerun()
        st.title("🎯 Fantasy Darts – Create Your Team")
        TOTAL_BUDGET = 20000

        # --- Lade Spieler ---
        try:
            players = requests.get(f"{BASE_URL}/players/").json()
        except Exception as e:
            st.error(f"Error loading players: {e}")
            st.stop()

        if not isinstance(players, list) or len(players) == 0:
            st.error("❌ No players found!")
            st.stop()

        df = pd.DataFrame(players)
        df["selected"] = False

        def get_flag_url(nation):
            code = COUNTRY_CODE_MAP.get(nation.strip())
            return f"{BASE_FLAG_URL}{code}.svg" if code else ""

        df["flag_url"] = df["nation"].apply(get_flag_url)

        # --- Tabelle ---
        edited_df = st.data_editor(
            df,
            column_config={
                "seed": st.column_config.Column("Seed", width="small"),
                "name": st.column_config.Column("Name"),
                "price": st.column_config.Column("Price"),
                "flag_url": st.column_config.ImageColumn("Nation", width="small"),
                "selected": st.column_config.CheckboxColumn("Select"),
            },
            column_order=["seed", "name", "price", "flag_url", "selected"],
            hide_index=True,
            width="stretch",
            disabled=[
                "seed",
                "name",
                "price",
                "nation",
                "id",
                "points",
                "eliminated",
            ],  # id, points, eliminated hinzugefügt
            key="create_team_editor",
        )

        # --- Auswahl & Budget ---
        # selected_df = edited_df[edited_df["selected"]]
        selected_df = edited_df[edited_df["selected"]].copy()
        # selected_ids = selected_df["id"].tolist()
        selected_ids = selected_df["id"].apply(int).tolist()
        total_spent = selected_df["price"].sum()
        remaining_budget = TOTAL_BUDGET - total_spent
        selected_count = len(selected_ids)

        # --- Budgetanzeige ---
        st.markdown(
            f"""
            ### 💰 Budget
            - **Total:** {TOTAL_BUDGET:,.2f}  
            - **Used:** {total_spent:,.2f}  
            - **Remaining:** <span style="color:{'red' if remaining_budget < 0 else 'green'}">{remaining_budget:,.2f}</span>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(f"### 🧍 Selected Players: {selected_count} / 15")

        # --- Captain und Underdog Auswahl (NEU) ---
        captain_id = None
        underdog_id = None
        can_select_roles = False

        if selected_count == 15 and remaining_budget >= 0:
            st.markdown("---")
            st.subheader("⭐ Select Captain & Underdog")

            player_options = selected_df.set_index("id")["name"].to_dict()

            # 1. Captain-Auswahl
            captain_name = st.selectbox(
                "Select your **Team Captain** (x2 Points):",
                options=player_options.values(),
                key="create_captain_select",
            )
            # captain_id = selected_df[selected_df["name"] == captain_name]["id"].iloc[0]
            captain_id = int(
                selected_df[selected_df["name"] == captain_name]["id"].iloc[0]
            )
            # 2. Underdog-Auswahl
            underdog_candidates = selected_df[selected_df["price"] < 800]
            underdog_options = underdog_candidates.set_index("id")["name"].to_dict()

            if underdog_options:
                underdog_name = st.selectbox(
                    "Select your **Underdog** (Price < 800.0):",
                    options=underdog_options.values(),
                    key="create_underdog_select",
                )
                # underdog_id = underdog_candidates[
                #     underdog_candidates["name"] == underdog_name
                # ]["id"].iloc[0]
                underdog_id = int(
                    underdog_candidates[underdog_candidates["name"] == underdog_name][
                        "id"
                    ].iloc[0]
                )
                can_select_roles = True
            else:
                st.error(
                    "❌ No eligible Underdog player (Price < 800.0) selected in your team!"
                )
                can_select_roles = False

        # --- Teamübersicht ---
        if not selected_df.empty:
            st.subheader("✅ Your Current Team")

            # Code zur Kennzeichnung:
            selected_df["Role"] = ""
            if captain_id in selected_ids:
                selected_df.loc[selected_df["id"] == captain_id, "Role"] = "CAPTAIN 👑"
            if underdog_id in selected_ids:
                selected_df.loc[selected_df["id"] == underdog_id, "Role"] += (
                    " / UNDERDOG 🐕 (x2)"
                    if selected_df.loc[selected_df["id"] == underdog_id, "Role"].iloc[0]
                    else "UNDERDOG 🐕 (x2)"
                )

            st.dataframe(
                selected_df[["seed", "name", "price", "flag_url", "Role"]],
                column_config={
                    "seed": st.column_config.Column("Seed", width="tiny"),
                    "name": st.column_config.Column("Player Name"),
                    "price": st.column_config.Column("Price"),
                    "flag_url": st.column_config.ImageColumn("Flag", width="tiny"),
                    "Role": st.column_config.Column("Role", width="medium"),
                },
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("No players selected yet.")

        # --- Team speichern ---
        can_create = (
            (selected_count == 15) and (remaining_budget >= 0) and can_select_roles
        )
        team_name = st.text_input("Team name", "My Dream Team")

        if can_create:
            if st.button("✅ Create Team"):
                payload = {
                    "user_id": int(st.session_state.user_id),
                    "team_name": team_name,
                    "player_ids": selected_ids,
                    "captain_id": captain_id,
                    "underdog_id": underdog_id,
                }

                response = requests.post(f"{BASE_URL}/teams/", json=payload)
                if response.status_code == 200:
                    st.success("✅ Team successfully created!")
                    st.session_state.current_page = "overview"
                    st.rerun()
                else:
                    st.error(f"Error creating team: {response.text}")
        else:
            st.warning(
                "⚠️ Select exactly 15 players, stay within budget, and choose both roles."
            )


# elif page == "🧩 Teams":
#     if "user_id" not in st.session_state:
#         st.warning("⚠️ Please log in to create a team!")
#         st.stop()

#     st.title("🧩 Your Teams")

#     # --- 1. Load user's teams ---
#     try:
#         user_teams = requests.get(
#             f"{BASE_URL}/teams/user/{st.session_state.user_id}"
#         ).json()
#         df_teams = pd.DataFrame(user_teams)
#         if not df_teams.empty:
#             st.subheader("📝 Your Existing Teams")
#             df_teams = df_teams.sort_values(
#                 by="total_points", ascending=False
#             ).reset_index(drop=True)
#             df_teams.insert(0, "Rank", df_teams.index + 1)

#             for i, row in df_teams.iterrows():
#                 cols = st.columns([1, 4, 2, 2, 2])
#                 cols[0].write(row["Rank"])
#                 cols[1].write(row["team_name"])
#                 cols[2].write(row["total_points"])
#                 if cols[3].button("✏️ Edit", key=f"edit_{row['team_id']}"):
#                     # Speichere Team für Edit
#                     st.session_state.edit_team_id = row["team_id"]
#                     st.session_state.edit_team_name = row["team_name"]
#                     st.session_state.current_page = "edit_team"
#                     st.rerun()

#                 if cols[4].button("🗑 Delete", key=f"delete_{row['team_id']}"):
#                     try:
#                         response = requests.delete(f"{BASE_URL}/teams/{row['team_id']}")
#                         if response.status_code == 200:
#                             st.success(
#                                 f"Team '{row['team_name']}' deleted successfully!"
#                             )
#                             st.session_state.current_page = "overview"
#                             st.rerun()  # Seite neu laden, damit gelöschtes Team verschwindet
#                         else:
#                             st.error(f"Error deleting team: {response.text}")
#                     except Exception as e:
#                         st.error(f"Error deleting team: {e}")
#         else:
#             st.info("You have not created any teams yet.")
#     except Exception as e:
#         st.warning(f"Could not load your teams: {e}")

#     st.markdown("---")

#     if st.session_state.get("current_page", "") not in ["edit_team", "create_new_team"]:
#         if st.button("➕ Create New Team"):
#             # Bereite Session State für Team Creation vor
#             st.session_state.selected_ids = []
#             st.session_state.current_page = "create_new_team"
#             st.rerun()


# # --- 3. Edit Team oder Create New Team Seiten ---
# if "current_page" in st.session_state:

#     # 🟦 --- EDIT EXISTING TEAM ---
#     if st.session_state.current_page == "edit_team":
#         if st.button("⬅️ Back to Teams"):
#             st.session_state.current_page = (
#                 "overview"  # oder "teams_overview" je nach deinem Setup
#             )
#             st.rerun()
#         team_id = st.session_state.edit_team_id
#         team_name = st.session_state.edit_team_name
#         st.title(f"✏️ Edit Team: {team_name}")

#         TOTAL_BUDGET = 20000

#         # --- Lade Team-Spieler ---
#         try:
#             team_players = requests.get(f"{BASE_URL}/teams/{team_id}/players").json()
#         except Exception as e:
#             st.error(f"Fehler beim Laden der Teamspieler: {e}")
#             st.stop()

#         # IDs der aktuellen Teamspieler
#         current_player_ids = (
#             [p["id"] for p in team_players] if isinstance(team_players, list) else []
#         )

#         # --- Lade alle Spieler ---
#         try:
#             players = requests.get(f"{BASE_URL}/players/").json()
#         except Exception as e:
#             st.error(f"Fehler beim Laden der Spielerliste: {e}")
#             players = []

#         if not isinstance(players, list) or len(players) == 0:
#             st.error("❌ Keine Spieler gefunden!")
#             st.stop()

#         # --- DataFrame vorbereiten ---
#         df = pd.DataFrame(players)
#         df["selected"] = df["id"].isin(current_player_ids)

#         def get_flag_url(nation):
#             code = COUNTRY_CODE_MAP.get(nation.strip())
#             return f"{BASE_FLAG_URL}{code}.svg" if code else ""

#         df["flag_url"] = df["nation"].apply(get_flag_url)

#         # --- Tabelle anzeigen ---
#         edited_df = st.data_editor(
#             df,
#             column_config={
#                 "seed": st.column_config.Column("Seed", width="small"),
#                 "name": st.column_config.Column("Name"),
#                 "price": st.column_config.Column("Price"),
#                 "flag_url": st.column_config.ImageColumn("Nation", width="small"),
#                 "selected": st.column_config.CheckboxColumn("Select"),
#             },
#             column_order=["seed", "name", "price", "flag_url", "selected"],
#             hide_index=True,
#             width="stretch",
#             disabled=["seed", "name", "price", "nation", "id"],
#             key="edit_team_editor",
#         )

#         # --- Auswahl aktualisieren ---
#         selected_df = edited_df[edited_df["selected"]]
#         selected_ids = selected_df["id"].tolist()
#         total_spent = selected_df["price"].sum()
#         remaining_budget = TOTAL_BUDGET - total_spent
#         selected_count = len(selected_ids)

#         # --- Budgetanzeige ---
#         st.markdown(
#             f"""
#             ### 💰 Budget
#             - **Total:** {TOTAL_BUDGET:,.2f}
#             - **Used:** {total_spent:,.2f}
#             - **Remaining:** <span style="color:{'red' if remaining_budget < 0 else 'green'}">{remaining_budget:,.2f}</span>
#             """,
#             unsafe_allow_html=True,
#         )
#         st.markdown(f"### 🧍 Selected Players: {selected_count} / 15")

#         # --- Aktuelles Team anzeigen ---
#         if not selected_df.empty:
#             st.subheader("✅ Your Current Team")
#             st.dataframe(
#                 selected_df[["seed", "name", "price", "flag_url"]],
#                 column_config={
#                     "seed": st.column_config.Column("Seed", width="tiny"),
#                     "name": st.column_config.Column("Player Name"),
#                     "price": st.column_config.Column("Price"),
#                     "flag_url": st.column_config.ImageColumn("Flag", width="tiny"),
#                 },
#                 hide_index=True,
#                 width="stretch",
#             )
#         else:
#             st.info("No players selected yet.")

#         # --- Update / Save Button ---
#         can_save = (selected_count == 15) and (remaining_budget >= 0)
#         if can_save:
#             if st.button("💾 Save Team Changes"):
#                 payload = {"player_ids": selected_ids}
#                 response = requests.put(f"{BASE_URL}/teams/{team_id}", json=payload)
#                 if response.status_code == 200:
#                     st.success("Team updated successfully!")
#                     # st.session_state.current_page = "teams_overview"
#                     st.session_state.current_page = "overview"
#                     st.rerun()
#                 else:
#                     st.error(f"Error updating team: {response.text}")
#         else:
#             st.warning("Team not valid (check player count or budget).")

#     # 🟩 --- CREATE NEW TEAM ---
#     elif st.session_state.current_page == "create_new_team":
#         if st.button("⬅️ Back to Teams"):
#             st.session_state.current_page = (
#                 "overview"  # oder "teams_overview" je nach deinem Setup
#             )
#             st.rerun()
#         st.title("🎯 Fantasy Darts – Create Your Team")
#         TOTAL_BUDGET = 20000

#         # --- Lade Spieler ---
#         try:
#             players = requests.get(f"{BASE_URL}/players/").json()
#         except Exception as e:
#             st.error(f"Fehler beim Laden der Spieler: {e}")
#             st.stop()

#         if not isinstance(players, list) or len(players) == 0:
#             st.error("❌ Keine Spieler gefunden!")
#             st.stop()

#         df = pd.DataFrame(players)
#         df["selected"] = False

#         def get_flag_url(nation):
#             code = COUNTRY_CODE_MAP.get(nation.strip())
#             return f"{BASE_FLAG_URL}{code}.svg" if code else ""

#         df["flag_url"] = df["nation"].apply(get_flag_url)

#         # --- Tabelle ---
#         edited_df = st.data_editor(
#             df,
#             column_config={
#                 "seed": st.column_config.Column("Seed", width="small"),
#                 "name": st.column_config.Column("Name"),
#                 "price": st.column_config.Column("Price"),
#                 "flag_url": st.column_config.ImageColumn("Nation", width="small"),
#                 "selected": st.column_config.CheckboxColumn("Select"),
#             },
#             column_order=["seed", "name", "price", "flag_url", "selected"],
#             hide_index=True,
#             width="stretch",
#             disabled=["seed", "name", "price", "nation", "id"],
#             key="create_team_editor",
#         )

#         # --- Auswahl & Budget ---
#         selected_df = edited_df[edited_df["selected"]]
#         selected_ids = selected_df["id"].tolist()
#         total_spent = selected_df["price"].sum()
#         remaining_budget = TOTAL_BUDGET - total_spent
#         selected_count = len(selected_ids)

#         # --- Budgetanzeige ---
#         st.markdown(
#             f"""
#             ### 💰 Budget
#             - **Total:** {TOTAL_BUDGET:,.2f}
#             - **Used:** {total_spent:,.2f}
#             - **Remaining:** <span style="color:{'red' if remaining_budget < 0 else 'green'}">{remaining_budget:,.2f}</span>
#             """,
#             unsafe_allow_html=True,
#         )
#         st.markdown(f"### 🧍 Selected Players: {selected_count} / 15")

#         # --- Teamübersicht ---
#         if not selected_df.empty:
#             st.subheader("✅ Your Current Team")
#             st.dataframe(
#                 selected_df[["seed", "name", "price", "flag_url"]],
#                 column_config={
#                     "seed": st.column_config.Column("Seed", width="tiny"),
#                     "name": st.column_config.Column("Player Name"),
#                     "price": st.column_config.Column("Price"),
#                     "flag_url": st.column_config.ImageColumn("Flag", width="tiny"),
#                 },
#                 hide_index=True,
#                 width="stretch",
#             )
#         else:
#             st.info("No players selected yet.")

#         # --- Team speichern ---
#         can_create = (selected_count == 15) and (remaining_budget >= 0)
#         team_name = st.text_input("Team name", "My Dream Team")

#         if can_create:
#             if st.button("✅ Create Team"):
#                 payload = {
#                     "user_id": st.session_state.user_id,
#                     "team_name": team_name,
#                     "player_ids": selected_ids,
#                 }
#                 response = requests.post(f"{BASE_URL}/teams/", json=payload)
#                 if response.status_code == 200:
#                     st.success("✅ Team successfully created!")
#                     # Zurück zur Übersicht
#                     # st.session_state.current_page = "teams_overview"
#                     st.session_state.current_page = "overview"
#                     st.rerun()
#                 else:
#                     st.error(f"Error creating team: {response.text}")
#         else:
#             st.warning("⚠️ Select exactly 15 players and stay within budget.")
