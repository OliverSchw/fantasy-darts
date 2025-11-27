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
)  # "http://127.0.0.1:8000"  #

CHAMPION_POINTS = 1000

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
                st.session_state.is_admin = data.get("is_admin", False)
                st.session_state.access_token = data.get("access_token")
                st.success(f"Welcome {data['username']}!")
                st.rerun()
            else:
                st.error("Invalid username or password")
        except Exception as e:
            st.error(f"Login failed: {e}")

else:
    st.sidebar.write(f"Logged in as {st.session_state.username}")
    if st.sidebar.button("Logout"):
        del st.session_state.user_id
        del st.session_state.username
        # NEU: Token beim Logout ebenfalls entfernen
        if "is_admin" in st.session_state:
            del st.session_state.is_admin
        if "access_token" in st.session_state:
            del st.session_state.access_token
        # Ende NEU
        st.success("Logged out successfully!")
        st.rerun()  # sofort neu rendern
# Seiten-Navigation

if "current_sub_state" not in st.session_state:
    st.session_state.current_sub_state = "overview"


def reset_sub_state():
    # Setzt den gewünschten Session State auf den gewünschten Standardwert
    st.session_state.current_sub_state = "overview"


page = st.sidebar.radio(
    "Navigation",
    [
        "🏠 Overview",
        "🎯 Players",
        "🧩 Teams",
        # "⚔️ Tournament Bracket"
        "📅 Tournament Schedule",
        "📝 Manage Accounts",
    ],
    on_change=reset_sub_state,
)


def get_auth_headers():
    """Creates the Authorization header with the JWT for protected requests."""
    token = st.session_state.get("access_token")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def fetch_users():
    """Retrieves the list of all users from the FastAPI backend (Admin-protected)."""
    try:
        response = requests.get(f"{BASE_URL}/auth/users", headers=get_auth_headers())

        if response.status_code == 200:
            return response.json()
        elif response.status_code == 403:
            st.error("Access denied. Invalid token or you are not an admin.")
        else:
            st.error(f"Error loading users: Status Code {response.status_code}")
        return []
    except Exception as e:
        st.error(f"Connection error: {e}")
        return []


def update_user_admin_status(user_id, new_status):
    """Updates a user's admin status (Admin-protected)."""
    try:
        response = requests.put(
            f"{BASE_URL}/auth/users/{user_id}",
            json={"is_admin": new_status},
            headers=get_auth_headers(),
        )
        if response.status_code == 200:
            st.success(
                f"Admin status for User ID {user_id} successfully changed to {new_status}."
            )
            st.rerun()
        else:
            st.error(
                f"Error updating admin status: Status Code {response.status_code} - {response.text}"
            )
    except Exception as e:
        st.error(f"Connection error during update: {e}")


def create_new_user(username, password, is_admin):
    """Creates a new user via the FastAPI backend endpoint."""
    try:
        # Sends the Admin token, as only Admins should be able to set is_admin=True
        response = requests.post(
            f"{BASE_URL}/auth/register",  # Prerequisite: This endpoint must exist
            json={"username": username, "password": password, "is_admin": is_admin},
            headers=get_auth_headers(),
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as err:
        try:
            error_msg = err.response.json().get("detail", str(err))
        except:
            error_msg = str(err)
        raise Exception(f"User creation failed: {error_msg}") from err
    except Exception as e:
        raise Exception(f"Connection error during creation: {e}")


def delete_user_by_id(user_id):
    """Sendet die DELETE-Anfrage an den FastAPI-Endpunkt."""
    try:
        response = requests.delete(
            f"{BASE_URL}/auth/users/{user_id}", headers=get_auth_headers()
        )
        if response.status_code == 204:
            st.success(f"User ID {user_id} successfully deleted.")
            st.rerun()
        elif response.status_code == 403:
            st.error("Operation not allowed: You cannot delete your own account.")
        else:
            st.error(
                f"Error deleting user: Status Code {response.status_code} - {response.text}"
            )
    except Exception as e:
        st.error(f"Connection error during deletion: {e}")


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
        st.subheader("👥 Players")

        # Spieler laden (enthält jetzt is_captain/is_underdog)
        try:
            players = requests.get(f"{BASE_URL}/teams/{team_id}/players").json()
            champion_details = requests.get(
                f"{BASE_URL}/teams/{team_id}/champion_tip"
            ).json()

        except Exception as e:
            st.error(
                f"❌ Failed to load team data from the server. Please check the connection or API endpoint. Error details: {e}"
            )
            st.stop()

        if players and isinstance(players, list):
            df_players = pd.DataFrame(players)

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
                    "name": st.column_config.Column("Player Name", width="medium"),
                    "price": st.column_config.NumberColumn(
                        "Price", format="compact", width="small"
                    ),
                    "flag_url": st.column_config.ImageColumn("Nation", width=50),
                    "points": None,  # WICHTIG: Blende die redundante 'points' Spalte aus
                    "Display_Points": st.column_config.Column("Points", width="tiny"),
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

            st.markdown("---")
            st.subheader("🏆 Champion Pick")

            champion_name_raw = "N/A"
            champion_points = 0

            def highlight_champion_row(row):
                # Prüfe, ob eliminated True ist
                if row.get("eliminated") is True:
                    color = "red"
                    # Optional: Hintergrundfarbe für ausgeschieden
                    return [f"color: {color}; background-color: #ffe6e6"] * len(row)
                # Prüfe, ob is_champion True ist (d.h. gewonnen)
                elif row.get("is_champion") is True:
                    color = "green"
                    # Optional: Hintergrundfarbe für gewonnen
                    return [
                        f"color: {color}; font-weight: bold; background-color: #e6ffe6"
                    ] * len(row)
                else:
                    # Standardfarbe für aktiv/pending
                    return ["color: black"] * len(row)

            if champion_details:
                # Erstellen Sie eine Liste, die nur das Champion-Detail-Objekt enthält
                is_champion_status = champion_details.get("is_champion")
                eliminated = champion_details.get("eliminated")
                champion_flag_url = get_flag_url(champion_details.get("nation", ""))
                if is_champion_status:
                    champion_points = CHAMPION_POINTS
                champion_data_list = [
                    {
                        "seed": champion_details.get("seed"),
                        "name": champion_details.get("name"),
                        "price": champion_details.get("price"),
                        "nation": champion_details.get("nation"),
                        "flag_url": champion_flag_url,  # Verwendet die bereits generierte URL
                        "points": champion_details.get("points", 0),  # Base Points
                        "Display_Points": champion_points,
                        "Role": "🏆 CHAMPION PICK",
                        "eliminated": eliminated,
                        "is_champion": is_champion_status,  # Hinzufügen für die Highlight-Funktion
                    }
                ]

                df_champion = pd.DataFrame(champion_data_list)

                st.dataframe(
                    df_champion[
                        [
                            "seed",
                            "name",
                            "price",
                            "flag_url",
                            "points",
                            "Display_Points",
                            "Role",
                            "eliminated",
                            "is_champion",
                        ]
                    ].style.apply(highlight_champion_row, axis=1),
                    column_config={
                        "seed": st.column_config.Column("Seed", width="tiny"),
                        "name": st.column_config.Column("Player Name", width="medium"),
                        "price": st.column_config.NumberColumn(
                            "Price", format="compact", width="small"
                        ),
                        "flag_url": st.column_config.ImageColumn("Nation", width=50),
                        "points": None,  # Ausblenden
                        "is_champion": None,  # Ausblenden
                        "eliminated": None,  # Ausblenden
                        "Display_Points": st.column_config.Column(
                            "Champion Bonus Points", width="tiny"
                        ),
                        "Role": st.column_config.Column("Role", width="medium"),
                    },
                    width="stretch",
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
            else:
                st.info("No Champion Pick found for this team.")

            st.markdown("---")
            total_points = df_players["Calculated_Total_Points"].sum() + champion_points
            st.markdown(f"### 📊 Total Team Points: **{total_points:,.0f}**")

            # Zurück-Button
            st.markdown("---")
            st.button("⬅️ Back to Leaderboard", on_click=back_to_overview)

    # --- Leaderboard Seite ---
    # elif st.session_state.current_page == "overview":
    else:
        # st.title("🏠 Overview & Leaderboard")

        # Load leaderboard
        # requests.put(f"{BASE_URL}/players/points/recompute")
        # leaderboard = requests.get(f"{BASE_URL}/leaderboard/").json()
        # df_lb = pd.DataFrame(leaderboard)
        # if not df_lb.empty:
        #     df_lb = df_lb.sort_values(by="total_points", ascending=False).reset_index(
        #         drop=True
        #     )
        #     df_lb.insert(0, "Rank", df_lb.index + 1)

        #     st.subheader("🏆 Current Teams & Rankings")
        #     for i, row in df_lb.iterrows():
        #         cols = st.columns([1, 4, 2, 1])
        #         cols[0].write(row["Rank"])
        #         cols[1].write(row["team_name"])
        #         cols[2].write(row["total_points"])
        #         # View-Button mit Callback
        #         cols[3].button(
        #             "View",
        #             key=f"team_{row['team_id']}",
        #             on_click=go_to_team,
        #             args=(row["team_id"], row["team_name"]),
        #         )
        st.title("🏠 Overview & Leaderboard")

        team_selection = None

        requests.put(f"{BASE_URL}/players/points/recompute")
        leaderboard = requests.get(f"{BASE_URL}/leaderboard/").json()
        df_lb = pd.DataFrame(leaderboard)

        if not df_lb.empty:
            df_lb = df_lb.sort_values(by="total_points", ascending=False).reset_index(
                drop=True
            )
            df_lb.insert(0, "Rank", df_lb.index + 1)

            st.subheader("🏆 Current Teams & Rankings")

            # DataFrame für die Anzeige vorbereiten
            df_display = df_lb[["Rank", "team_name", "total_points"]]
            df_display.columns = ["Rank", "Name", "Total Points"]

            # 1. Responsive Tabelle anzeigen
            st.dataframe(
                df_display,
                width="stretch",
                hide_index=True,
            )

            st.markdown("---")

            # --- View Button Funktionalität ---

            # 2. Dropdown zum Auswählen eines Teams (basierend auf dem Namen)
            team_selection = st.selectbox(
                "Select a Team to view the details:",
                options=df_lb["team_name"],
                index=0,  # Startet beim Rang 1 Team
                key="leaderboard_team_select",
            )

        if team_selection:
            if st.button(f"Show team details 🔍"):

                # Finde die ID des ausgewählten Teams im Original-DataFrame
                selected_row = df_lb[df_lb["team_name"] == team_selection].iloc[0]
                team_id = selected_row["team_id"]

                # Rufe die Callback-Funktion auf, die zur Team-Detailseite wechselt
                # HINWEIS: go_to_team muss in Ihrem Skript definiert sein.
                go_to_team(team_id, team_selection)
                st.rerun()

        else:
            st.info("No teams found yet.")

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
            "seed": st.column_config.Column("Seed", width="tiny"),
            "name": st.column_config.Column("Player Name", width="medium"),
            "price": st.column_config.NumberColumn(
                "Price", format="compact", width="small"
            ),
            "flag_url": st.column_config.ImageColumn("Nation", width=50),
            "points": st.column_config.NumberColumn(
                "Points", format="compact", width="small"
            ),
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

    NUM_ROUNDS = 7  # Gesamtzahl der Runden (für Match-IDs und Logik)
    NUM_ROUNDS_T1 = 5  # Runden für Tabelle 1 (R1 bis R5)
    NUM_ROUNDS_T2 = NUM_ROUNDS - NUM_ROUNDS_T1  # Runden für Tabelle 2 (R6 und R7)
    NUM_MATCHES_ROUND_1 = 64
    ROWS = NUM_MATCHES_ROUND_1 * 2
    ROWS_T2 = 7  # Genug Platz, u

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
                    st.session_state["results_map"] = {
                        match["match_id"]: match for match in results
                    }
                    break
                except Exception as e:
                    if attempt < 2:
                        time.sleep(2**attempt)
                    else:
                        st.error(f"Error loading match results after 3 attempts: {e}")
                        raise e
            # Verarbeite die geladenen Ergebnisse (Füllt den 'winners' State)
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

        # Temporäre Match-Daten, um alle möglichen Matches zu speichern (R1 bis R7)
        all_possible_match_data = {}

        # --- Tabelle 1 aufbauen (Runden 1 bis 5) ---
        column_names_t1 = [f"Round {i+1}" for i in range(NUM_ROUNDS_T1 - 1)] + [
            "Quarter-Finals"
        ]
        table_1 = pd.DataFrame(
            "",
            index=range(ROWS),
            columns=column_names_t1,
        )

        # --- RUNDE 1: Spieler setzen und IDs speichern ---
        for i in range(NUM_MATCHES_ROUND_1):
            # ... (Logik zum Bestimmen von p1_display, p2_display, p1_id, p2_id) ...
            # (Dieser Abschnitt aus Ihrem Original-Code bleibt fast unverändert)

            # Annahme: Der Teil zur Bestimmung der Player-Infos ist hier vorhanden

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

            p1_display = (
                f"{p1_name} ({p1_seed})" if p1_seed and p1_seed <= 32 else p1_name
            )
            p2_display = (
                f"{p2_name} ({p2_seed})" if p2_seed and p2_seed <= 32 else p2_name
            )

            row_p1 = i * 2
            row_p2 = i * 2 + 1

            match_id_r1 = f"match_{row_p1}_{1}"

            # 1. Speichere Basis-Match-Daten in der zentralen Map
            current_match_data_r1 = {
                "p1_id": p1_id,
                "p2_id": p2_id,
                "p1_name_display": p1_display,
                "p2_name_display": p2_display,
            }
            all_possible_match_data[match_id_r1] = current_match_data_r1

            # 2. Fülle die Tabelle 1
            winner_display = st.session_state["winners"].get(match_id_r1)

            if winner_display:
                if winner_display == p1_display:
                    table_1.iloc[row_p1, 0] = p1_display
                    table_1.iloc[row_p2, 0] = f"~{p2_display}~"
                elif winner_display == p2_display:
                    table_1.iloc[row_p1, 0] = f"~{p1_display}~"
                    table_1.iloc[row_p2, 0] = p2_display
                else:
                    table_1.iloc[row_p1, 0] = winner_display
                    table_1.iloc[row_p2, 0] = f"~{p2_display}~"  # Annahme
            else:
                # Match ist offen, zeige beide Namen unverändert
                table_1.iloc[row_p1, 0] = p1_display
                table_1.iloc[row_p2, 0] = p2_display

                # --- FIX: Übernehme alte, ungespeicherte Stats, falls vorhanden ---
                if match_id_r1 in old_match_data:
                    st.session_state.match_data[match_id_r1] = {
                        **current_match_data_r1,
                        **old_match_data[match_id_r1],
                    }
                else:
                    st.session_state.match_data[match_id_r1] = current_match_data_r1

        # --- Weitere Runden: Gewinner weiterleiten oder Platzhalter setzen (Tabelle 1) ---
        for r in range(1, NUM_ROUNDS_T1):  # Läuft von r=1 (R2) bis r=4 (R5)
            step = 2**r
            step_prev = 2 ** (r - 1)

            for i in range(0, ROWS, step * 2):
                match_id = f"match_{i}_{r + 1}"

                match_id_p1_predecessor = f"match_{i}_{r}"
                match_id_p2_predecessor = f"match_{i + step}_{r}"

                row_p1_current = i + step_prev - 1
                row_p2_current = i + step + step_prev - 1

                p1_winner_name = st.session_state["winners"].get(
                    match_id_p1_predecessor
                )
                p2_winner_name = st.session_state["winners"].get(
                    match_id_p2_predecessor
                )

                p1_id_r = None
                p2_id_r = None

                # --- Spieler 1 bestimmen ---
                if p1_winner_name:
                    table_1.iloc[row_p1_current, r] = p1_winner_name
                    p1_base_name = extract_base_name(p1_winner_name)
                    try:
                        p1_id_r = df_players_all.loc[p1_base_name, "id"]
                    except KeyError:
                        pass
                else:
                    table_1.iloc[row_p1_current, r] = "TBD"

                # --- Spieler 2 bestimmen ---
                if p2_winner_name:
                    table_1.iloc[row_p2_current, r] = p2_winner_name
                    p2_base_name = extract_base_name(p2_winner_name)
                    try:
                        p2_id_r = df_players_all.loc[p2_base_name, "id"]
                    except KeyError:
                        pass
                else:
                    table_1.iloc[row_p2_current, r] = "TBD"

                display_p1 = table_1.iloc[row_p1_current, r]
                display_p2 = table_1.iloc[row_p2_current, r]

                # Wir müssen sicherstellen, dass wir keine ~TBD~ übergeben, also nur den reinen Namen
                if display_p1.startswith("~"):
                    display_p1 = extract_base_name(display_p1)
                if display_p2.startswith("~"):
                    display_p2 = extract_base_name(display_p2)

                current_match_data = {
                    "p1_id": p1_id_r,
                    "p2_id": p2_id_r,
                    "p1_name_display": display_p1,
                    "p2_name_display": display_p2,
                }

                # NEU: Das Match IMMER zur Liste der möglichen Matches hinzufügen (unbedingt)
                all_possible_match_data[match_id] = current_match_data

                # *************************************************************************
                # AB HIER STARTET DIE LOGIK FÜR SPIELBEREITE UND ABGESCHLOSSENE MATCHES
                # *************************************************************************

                # 2. Prüfen, ob das Match spielbereit ist (beide Spieler + IDs bekannt)
                if (
                    p1_winner_name
                    and p2_winner_name
                    and p1_id_r is not None
                    and p2_id_r is not None
                ):

                    winner_display = st.session_state["winners"].get(match_id)

                    if winner_display:
                        # MATCH ABGESCHLOSSEN (visuelle Darstellung in table_1)
                        if winner_display == p1_winner_name:
                            table_1.iloc[row_p1_current, r] = p1_winner_name
                            table_1.iloc[row_p2_current, r] = f"~{p2_winner_name}~"
                        elif winner_display == p2_winner_name:
                            table_1.iloc[row_p1_current, r] = f"~{p1_winner_name}~"
                            table_1.iloc[row_p2_current, r] = p2_winner_name
                        # ... (Restliche Logik für Abgeschlossene Matches, z.B. Linien zeichnen)

                    else:
                        # MATCH SPIELBEREIT (noch kein Gewinner): Zu st.session_state.match_data hinzufügen
                        if match_id in old_match_data:
                            st.session_state.match_data[match_id] = {
                                **current_match_data,
                                **old_match_data[match_id],
                            }
                        else:
                            st.session_state.match_data[match_id] = current_match_data

        # --- Visuelle Darstellung der Tabelle 1 (Runden 1-5) ---
        st.write("### 🟨 Round 1 to 5 ")
        st.dataframe(
            table_1,
            hide_index=True,
            width="stretch",
        )

        st.markdown("---")
        column_names_t2 = [
            f"Semi-Finals",
            f"Final",
            "🏆 Champion",
        ]
        table_2 = pd.DataFrame(
            "",
            index=range(ROWS_T2),
            columns=column_names_t2,
        )

        for r in range(NUM_ROUNDS_T2):  # r läuft von 0 (R6) bis 1 (R7)
            r_abs = r + NUM_ROUNDS_T1  # r_abs läuft von 6 bis 7

            step = 2**r_abs
            num_matches_in_round = NUM_MATCHES_ROUND_1 // step

            if r == 0:
                index_step = 4
            elif r == 1:
                index_step = 0

            for i in range(num_matches_in_round):
                start_row_r1 = i * step * 2
                match_id = f"match_{start_row_r1}_{r_abs + 1}"

                match_id_p1_predecessor = f"match_{start_row_r1}_{r_abs}"
                match_id_p2_predecessor = f"match_{start_row_r1 + step}_{r_abs}"

                p1_winner_name = st.session_state["winners"].get(
                    match_id_p1_predecessor
                )
                p2_winner_name = st.session_state["winners"].get(
                    match_id_p2_predecessor
                )

                p1_id_r = None
                p2_id_r = None

                # --- Bestimmung der Zeilen-Indizes in table_2 ---
                if r == 0:  # Runde 6 (nutzt den index_step)
                    row_p1_current_t2 = i * index_step
                    row_p2_current_t2 = row_p1_current_t2 + 2
                elif r == 1:  # Runde 7 (Finale, zentral in der Mitte)
                    row_p1_current_t2 = 1  # Zeile 5
                    row_p2_current_t2 = 5  # Zeile 6

                if p1_winner_name:
                    table_2.iloc[row_p1_current_t2, r] = p1_winner_name
                    p1_base_name = extract_base_name(p1_winner_name)
                    try:
                        p1_id_r = df_players_all.loc[p1_base_name, "id"]
                    except KeyError:
                        pass
                else:
                    table_2.iloc[row_p1_current_t2, r] = "TBD"

                # --- Spieler 2 bestimmen ---
                if p2_winner_name:
                    table_2.iloc[row_p2_current_t2, r] = p2_winner_name
                    p2_base_name = extract_base_name(p2_winner_name)
                    try:
                        p2_id_r = df_players_all.loc[p2_base_name, "id"]
                    except KeyError:
                        pass
                else:
                    table_2.iloc[row_p2_current_t2, r] = "TBD"

                display_p1 = p1_winner_name if p1_winner_name else "TBD"
                display_p2 = p2_winner_name if p2_winner_name else "TBD"

                current_match_data = {
                    "p1_id": p1_id_r,
                    "p2_id": p2_id_r,
                    "p1_name_display": display_p1,  # Wichtig: Setzt "TBD" wenn nötig
                    "p2_name_display": display_p2,
                }

                # NEU: Das Match IMMER zur Liste der möglichen Matches hinzufügen
                # Dadurch werden auch TBD vs. TBD Matches angezeigt.
                all_possible_match_data[match_id] = current_match_data
                if (
                    p1_winner_name
                    and p2_winner_name
                    and p1_id_r is not None
                    and p2_id_r is not None
                ):

                    winner_display = st.session_state["winners"].get(match_id)

                    if winner_display:
                        # MATCH ABGESCHLOSSEN: Ergebnisse in table_2 anzeigen (durchgestrichen)
                        if winner_display == p1_winner_name:
                            table_2.iloc[row_p1_current_t2, r] = p1_winner_name
                            table_2.iloc[row_p2_current_t2, r] = f"~{p2_winner_name}~"
                        elif winner_display == p2_winner_name:
                            table_2.iloc[row_p1_current_t2, r] = f"~{p1_winner_name}~"
                            table_2.iloc[row_p2_current_t2, r] = p2_winner_name

                        if r_abs == NUM_ROUNDS:
                            middle_row = 3
                            table_2.iloc[middle_row, 2] = winner_display

                    else:
                        # MATCH SPIELBEREIT (noch kein Gewinner): Zu st.session_state.match_data hinzufügen
                        if match_id in old_match_data:
                            st.session_state.match_data[match_id] = {
                                **current_match_data,
                                **old_match_data[match_id],
                            }
                        else:
                            st.session_state.match_data[match_id] = current_match_data

        final_match_id = f"match_{0}_{NUM_ROUNDS}"
        if final_match_id not in st.session_state["winners"]:
            table_2.iloc[3, 2] = "TBD"
        else:
            champion_display = st.session_state["winners"][final_match_id]
            table_2.iloc[3, 2] = champion_display

        st.session_state["all_possible_match_data"] = all_possible_match_data

        st.write("### 🏆 Semi-Finals and Final")
        st.dataframe(
            table_2,
            hide_index=True,
            width="stretch",
        )

        st.markdown("---")

        def sort_key(item):
            match_id = item[0]
            try:
                parts = match_id.split("_")
                round_num = int(parts[-1])
                start_row = int(parts[-2])
                return round_num, start_row
            except:
                return 999, 0

        all_matches_by_round = {}

        # Iteriere über alle möglichen Match-Daten (Runde 1 bis 7)
        for match_id, match_data in all_possible_match_data.items():
            try:
                round_num = get_round_num(match_id)
            except:
                # Matches, die nicht unseren ID-Format entsprechen (sollte nicht passieren)
                round_num = "?"

            if round_num not in all_matches_by_round:
                all_matches_by_round[round_num] = []

            all_matches_by_round[round_num].append((match_id, match_data))

        # Die Rundennummern sortieren, um sie in der richtigen Reihenfolge anzuzeigen (1, 2, 3...)
        sorted_round_nums = sorted(
            [r for r in all_matches_by_round.keys() if isinstance(r, int)]
        )

        st.write("### 📜 **Tournament Matches (Round 1 to Final)**")

        for round_num in sorted_round_nums:

            # --- Rundenüberschrift erstellen ---
            if round_num == 7:
                round_title = "Final"
            elif round_num == 6:
                round_title = "Semi-Finals"
            elif round_num == 5:
                round_title = "Quarter-Finals"
            else:
                round_title = f"Round {round_num}"

            # --- Expander-Logik ---

            # Das Finale (Runde 7) soll standardmäßig offen sein
            if round_num == 7:
                title_text = f"🏅 **{round_title}**"
                # Kein Expander hier
                display_container = st.expander(title_text, expanded=False)
            else:
                # Alle anderen Runden kommen in einen Expander
                if round_num == 6:
                    title_text = f"🏅 {round_title} ({len(all_matches_by_round[round_num])} Matches)"
                else:
                    title_text = f"🟨 {round_title} ({len(all_matches_by_round[round_num])} Matches)"
                is_expanded = False

                display_container = st.expander(title_text, expanded=is_expanded)

            # Die Matches innerhalb der Runde sortieren (nach Start-Zeile)
            current_round_matches = sorted(
                all_matches_by_round[round_num], key=sort_key
            )

            # Wir verwenden den Container/Expander, um den Match-Code einzuschließen
            with display_container:

                # Jedes Match in dieser Runde anzeigen
                for match_id, match_data in current_round_matches:
                    p1_display = match_data.get("p1_name_display", "TBD")
                    p2_display = match_data.get("p2_name_display", "TBD")

                    # Prüfen, ob das Match bereits gespielt wurde
                    winner_text = st.session_state["winners"].get(match_id)

                    # Prüfen, ob das Match spielbereit ist (Offenes Match im State)
                    is_open_match = match_id in st.session_state.match_data

                    # Die Spalten-Anordnung muss INNERHALB des expanders/containers sein
                    col1, col2 = st.columns([0.7, 0.3])

                    # --- Match-Status bestimmen und anzeigen ---
                    if winner_text:
                        # FALL 1: MATCH ABGESCHLOSSEN
                        scores = st.session_state["results_map"].get(match_id, {})
                        score_string = ""
                        if scores:
                            score_p1 = scores.get("sets_p1", "?")
                            score_p2 = scores.get("sets_p2", "?")
                            score_string = f" ({score_p1}:{score_p2})"

                        if winner_text == p1_display:
                            display_string = (
                                f"**{p1_display}** {score_string} ~~{p2_display}~~"
                            )
                        else:  # winner_text == p2_display:
                            display_string = (
                                f"~~{p1_display}~~ {score_string} **{p2_display}**"
                            )

                        col1.markdown(
                            f"✅ {display_string}",
                            unsafe_allow_html=True,
                        )
                        col2_status, col2_button = col2.columns(
                            [0.4, 0.6]
                        )  # Neue Spaltenstruktur in col2

                        col2_status.success("Completed")  # Grüner Badge

                        if col2_button.button(
                            "Result 🔍", key=f"edit_score_{match_id}"
                        ):
                            # Hier ändern wir den Seiten-Status, um zur Detailseite zu springen
                            st.session_state.current_match = match_id
                            st.session_state.current_page = "match_detail"
                            st.rerun()

                    elif is_open_match:
                        # FALL 2: MATCH SPIELBEREIT (Spieler stehen fest)
                        col1.markdown(f"🎯 **{p1_display}** vs. **{p2_display}**")

                        # Button, um zur Detailseite zu wechseln
                        if col2.button(
                            "Capture Result 📝", key=f"enter_score_{match_id}"
                        ):
                            st.session_state.current_match = match_id
                            st.session_state.current_page = "match_detail"
                            st.rerun()

                    else:
                        # FALL 3: MATCH NOCH NICHT SPIELBEREIT (TBD)
                        if p1_display == "TBD" and p2_display == "TBD":
                            col1.markdown(f"⏳ **TBD** vs. **TBD**")
                        else:
                            col1.markdown(f"⏳ **{p1_display}** vs. **{p2_display}**")

                        col2.info("Waiting for Predecessor")  # Blauer Badge

                    # Trennlinie nach jedem Match
                    st.markdown("---")

    elif st.session_state.current_page == "match_detail":
        is_admin = st.session_state.get("is_admin", False)
        match_id = st.session_state.current_match
        all_possible_match_data_s = st.session_state.get("all_possible_match_data", {})

        if match_id in st.session_state.match_data:
            match_info = st.session_state.match_data[match_id]

        # Prüfe zweitens, ob es ein abgeschlossenes Match zur Bearbeitung ist
        elif match_id in st.session_state.get("results_map", {}):

            base_data = all_possible_match_data_s.get(match_id, {})

            match_info = {
                **base_data,
                **st.session_state["results_map"][match_id],
            }
            st.session_state.match_data[match_id] = base_data

        else:
            st.error(
                f"Error: Match ID {match_id} not found in open or completed matches."
            )
            st.session_state.current_page = "overview"
            st.rerun()

        p1_id = match_info.get("p1_id", -1)
        p2_id = match_info.get("p2_id", -1)
        p1_name_display = match_info.get("p1_name_display", "N/A")
        p2_name_display = match_info.get("p2_name_display", "N/A")

        try:
            round_num = int(match_id.split("_")[-1])
            sets_to_win = {1: 3, 2: 3, 3: 4, 4: 4, 5: 5, 6: 6, 7: 7}.get(round_num, 7)
        except:
            sets_to_win = 5
            round_num = "?"

        st.write(f"### 🏹 Match Details – Round {round_num}")
        st.markdown(f"**{p1_name_display}** vs. **{p2_name_display}**")
        st.markdown(
            f"Best-of {sets_to_win*2+1} Sets. Needed to win: {sets_to_win} Sets."
        )
        st.markdown("---")

        col1, col2 = st.columns(2)

        # Definition der eindeutigen Keys
        KEY_SETS_P1 = f"sets_p1_{match_id}"
        KEY_LEGS_P1 = f"legs_p1_{match_id}"
        KEY_180S_P1 = f"d180s_p1_{match_id}"
        KEY_HIGH_CHECKOUT_P1 = f"high_checkout_p1_{match_id}"
        KEY_AVERAGE_P1 = f"average_p1_{match_id}"
        KEY_CHECKOUT_PCT_P1 = f"checkout_pct_p1_{match_id}"

        KEY_SETS_P2 = f"sets_p2_{match_id}"
        KEY_LEGS_P2 = f"legs_p2_{match_id}"
        KEY_180S_P2 = f"d180s_p2_{match_id}"
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
            max_value=sets_to_win,
            step=1,
            value=get_initial_value("sets_p1", 0),
        )
        col1.number_input(
            "Legs won",
            key=KEY_LEGS_P1,  # NEU: Eindeutiger Key
            min_value=0,
            step=1,
            value=get_initial_value("legs_p1", 0),
        )
        col1.number_input(
            "180s",
            key=KEY_180S_P1,  # NEU: Eindeutiger Key
            min_value=0,
            step=1,
            value=get_initial_value("d180s_p1", 0),
        )
        col1.number_input(
            "Highest Checkout",
            key=KEY_HIGH_CHECKOUT_P1,  # NEU: Eindeutiger Key
            min_value=0,
            max_value=170,
            step=1,
            value=get_initial_value("high_checkout_p1", 0),
        )
        col1.number_input(
            "Average",
            key=KEY_AVERAGE_P1,  # NEU: Eindeutiger Key
            min_value=0.0,
            step=0.01,
            format="%.2f",
            value=get_initial_value("average_p1", 0.0),
        )
        col1.number_input(
            "Checkout %",
            key=KEY_CHECKOUT_PCT_P1,  # NEU: Eindeutiger Key
            min_value=0.0,
            max_value=100.0,
            step=0.01,
            format="%.2f",
            value=get_initial_value("checkout_pct_p1", 0.0),
        )

        # Input-Felder für Spieler 2
        col2.subheader(f"{p2_name_display}")

        p2_sets = col2.number_input(
            "Sets won",
            key=KEY_SETS_P2,  # NEU: Eindeutiger Key
            min_value=0,
            max_value=sets_to_win,
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
            value=get_initial_value("d180s_p2", 0),
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
        st.session_state["results_map"][match_id] = {
            "sets_p1": st.session_state[KEY_SETS_P1],
            "legs_p1": st.session_state[KEY_LEGS_P1],
            "d180s_p1": st.session_state[KEY_180S_P1],
            "high_checkout_p1": st.session_state[KEY_HIGH_CHECKOUT_P1],
            "average_p1": st.session_state[KEY_AVERAGE_P1],
            "checkout_pct_p1": st.session_state[KEY_CHECKOUT_PCT_P1],
            "sets_p2": st.session_state[KEY_SETS_P2],
            "legs_p2": st.session_state[KEY_LEGS_P2],
            "d180s_p2": st.session_state[KEY_180S_P2],
            "high_checkout_p2": st.session_state[KEY_HIGH_CHECKOUT_P2],
            "average_p2": st.session_state[KEY_AVERAGE_P2],
            "checkout_pct_p2": st.session_state[KEY_CHECKOUT_PCT_P2],
        }

        # --- DIESE ZEILE AM ENDE DES BLOCKS IST WICHTIG FÜR DIE KORREKTE BEENDIGUNG ---
        # NEU: Entferne das Match aus match_data, wenn es abgeschlossen wird/wurde
        if match_id in st.session_state.match_data:
            del st.session_state.match_data[match_id]

        # NEU: Verwende die Werte direkt aus dem Session State, die durch number_input gesetzt wurden
        p1_sets_final = st.session_state[KEY_SETS_P1]
        p2_sets_final = st.session_state[KEY_SETS_P2]

        st.markdown("---")
        col_buttons = st.columns(3)

        if col_buttons[0].button("Back to Overview"):
            st.session_state["confirm_delete"] = False
            st.session_state["current_match"] = None
            st.session_state.current_page = "overview"
            st.rerun()

        if col_buttons[1].button(
            "Delete Match", type="secondary", disabled=not is_admin
        ):

            # 🎯 BESTÄTIGUNG ERFORDERLICH
            if (
                st.session_state.get("confirm_delete", False)
                and st.session_state.current_match == match_id
            ):

                try:
                    # IMPORTANT: Send the Admin Token!
                    resp = requests.delete(
                        f"{BASE_URL}/matches/{match_id}", headers=get_auth_headers()
                    )

                    # NEW: Differentiated Error Handling before raise_for_status()
                    if resp.status_code == 403:
                        # 403 Forbidden (Not an Admin or invalid token)
                        error_detail = resp.json().get("detail", "Access Denied.")
                        st.error(
                            f"❌ **Deletion Error (403):** {error_detail} Ensure you are logged in as an Admin."
                        )
                        # Reset confirmation flag and stop execution
                        st.session_state["confirm_delete"] = False
                        st.stop()

                    if resp.status_code == 404:
                        # 404 Not Found (Match no longer exists in the backend)
                        error_detail = resp.json().get("detail", "Match not found.")
                        st.warning(
                            f"⚠️ **Deletion Error (404):** {error_detail} The match may have already been deleted."
                        )

                        # Treat a 404 as a successful removal from the frontend state
                        # as the desired outcome (match gone) is achieved.
                        # Remove the match from the frontend Session State
                        if match_id in st.session_state.match_data:
                            del st.session_state.match_data[match_id]
                        if match_id in st.session_state.get("results_map", {}):
                            del st.session_state["results_map"][match_id]
                        if match_id in st.session_state.get("winners", {}):
                            del st.session_state["winners"][match_id]

                        st.session_state.current_page = "overview"
                        st.session_state["confirm_delete"] = False
                        st.rerun()

                    # If status code is 204 (Success) or an unexpected error occurs, proceed to check status.
                    resp.raise_for_status()

                    # --- Success Case (Status 204) ---
                    # Remove the match from the frontend Session State (rest of success logic)
                    if match_id in st.session_state.match_data:
                        del st.session_state.match_data[match_id]
                    if match_id in st.session_state.get("results_map", {}):
                        del st.session_state["results_map"][match_id]
                    if match_id in st.session_state.get("winners", {}):
                        del st.session_state["winners"][match_id]

                    st.success(
                        f"Match {match_id} successfully deleted and data cleared."
                    )

                    # Recompute points (if not handled by backend on delete)
                    requests.put(
                        f"{BASE_URL}/players/points/recompute",
                        headers=get_auth_headers(),
                    )

                    # Return to overview and Rerun
                    st.session_state.current_page = "overview"
                    st.session_state["confirm_delete"] = False
                    st.rerun()

                except requests.exceptions.RequestException as e:
                    # Catch general connection or unexpected errors (5xx)
                    st.error(
                        f"🌐 **Connection Error:** Could not reach the server or unexpected error occurred: {e}"
                    )
                    st.session_state["confirm_delete"] = (
                        False  # Reset confirmation flag
                    )
                    # Note: Rerunning is unnecessary here as we want the error to persist until the user interacts again.

            else:
                # Logic to display the confirmation warning remains the same
                st.session_state["confirm_delete"] = True
                st.session_state["current_match"] = match_id
                st.warning(
                    f"⚠️ **CONFIRM DELETION:** Press the 'Delete Match' button again to permanently delete Match {match_id} from the database."
                )
                st.stop()

        # Überprüfe die Siegesbedingung
        is_p1_winner = p1_sets_final >= sets_to_win and p1_sets_final > p2_sets_final
        is_p2_winner = p2_sets_final >= sets_to_win and p2_sets_final > p1_sets_final
        is_valid_match = is_p1_winner or is_p2_winner

        if not is_valid_match and (p1_sets_final > 0 or p2_sets_final > 0):
            st.warning(
                f"The match is not yet completed. One player requires {sets_to_win} sets to win."
            )

        if col_buttons[2].button(
            "Save and Conclude Match",
            disabled=not is_valid_match
            or not is_admin,  # <-- Hinzugefügter Admin-Check
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
                "d180s_p1": st.session_state[KEY_180S_P1],
                "d180s_p2": st.session_state[KEY_180S_P2],
            }

            # --- Speichere Daten im Backend (Mocked) ---
            try:
                for attempt in range(3):
                    try:
                        # WICHTIG: Sendet den Token im Header mit!
                        resp = requests.put(
                            f"{BASE_URL}/matches/save_match/",
                            json=payload,
                            headers=get_auth_headers(),
                        )
                        requests.put(
                            f"{BASE_URL}/players/points/recompute",
                            json=payload,
                            headers=get_auth_headers(),  # Falls recompute auch geschützt ist
                        )
                        resp.raise_for_status()
                        break
                    except requests.exceptions.RequestException as e:
                        # ... (Rest der Wiederholungslogik) ...
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
                st.session_state["confirm_delete"] = False
                st.session_state["current_match"] = None
                st.session_state.current_page = "overview"
                st.rerun()

            except requests.exceptions.RequestException as e:
                error_message = f"Error saving the match in the backend: {e}"
                if "resp" in locals():
                    error_message += f"\nResponse: {resp.text}"
                st.error(error_message)

# -----------------------------------
# 🔹 Team erstellen
# -----------------------------------
elif page == "🧩 Teams":
    if "user_id" not in st.session_state:
        st.warning("⚠️ Please log in to create a team!")
        st.stop()

    if st.session_state.get("current_page", "") not in ["edit_team", "create_new_team"]:
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
                            response = requests.delete(
                                f"{BASE_URL}/teams/{row['team_id']}"
                            )
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

        if st.button("➕ Create New Team"):
            # Bereite Session State für Team Creation vor
            st.session_state.selected_ids = []
            st.session_state.current_page = "create_new_team"
            st.rerun()

    # --- 3. Edit Team oder Create New Team Seiten ---
    if "current_page" in st.session_state:

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

            # --- Lade Team-Spieler & Champion-Tipp ---
            try:
                # 1. Hauptspieler laden (liefert Liste mit is_captain/is_underdog)
                team_players = requests.get(
                    f"{BASE_URL}/teams/{team_id}/players"
                ).json()

                # 2. Champion-Tipp laden (liefert Player-Objekt oder None/leeres Dict bei 200 OK)
                champion_response = requests.get(
                    f"{BASE_URL}/teams/{team_id}/champion_tip"
                )
                champion_response.raise_for_status()
                current_champion = champion_response.json()

            except requests.exceptions.HTTPError as http_err:
                st.error(f"HTTP error occurred while loading data: {http_err}")
                st.stop()
            except Exception as e:
                st.error(f"Error loading team data: {e}")
                st.stop()

            # IDs der aktuellen Teamspieler & Rollen finden
            if isinstance(team_players, list):
                current_player_ids = [p["id"] for p in team_players]
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

            # current_champion vorbereiten
            if current_champion is None:
                current_champion = {}

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
                    "seed": st.column_config.NumberColumn("Seed", width="tiny"),
                    "name": st.column_config.Column("Name", width="medium"),
                    "price": st.column_config.NumberColumn(
                        "Price", format="compact", width="small"
                    ),
                    "flag_url": st.column_config.ImageColumn("Nation", width=50),
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
                ],
                key="edit_team_editor",
            )

            # --- Auswahl & Budget ---
            selected_df = edited_df[edited_df["selected"]].copy()
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

            # --- Rollen & Champion Tipp Initialisierung ---
            captain_id = None
            underdog_id = None
            champion_id = None
            captain_ok = False
            underdog_ok = False
            can_select_champion = False

            if not selected_df.empty:
                st.subheader("✅ Your Current Team")

                # Rollen-Markierung in der Tabelle (basierend auf den NEU GEWÄHLTEN IDs)
                selected_df["Role"] = ""
                # Verwende die IDs aus den selectboxen, wenn diese gültig sind
                if captain_id in selected_ids and captain_ok:
                    selected_df.loc[selected_df["id"] == captain_id, "Role"] = (
                        "CAPTAIN 👑 (x2)"
                    )
                if underdog_id in selected_ids and underdog_ok:
                    role_text = "UNDERDOG 🐕 (x2)"
                    if selected_df.loc[selected_df["id"] == underdog_id, "Role"].iloc[
                        0
                    ]:
                        role_text = (
                            " / " + role_text
                        )  # Füge Schrägstrich hinzu, wenn Captain auch Underdog ist

                    selected_df.loc[
                        selected_df["id"] == underdog_id, "Role"
                    ] += role_text

                st.dataframe(
                    selected_df[["seed", "name", "price", "flag_url", "Role"]],
                    column_config={
                        "seed": st.column_config.Column("Seed", width="tiny"),
                        "name": st.column_config.Column("Player Name", width="medium"),
                        "price": st.column_config.NumberColumn(
                            "Price", format="compact", width="small"
                        ),
                        "flag_url": st.column_config.ImageColumn("Flag", width=50),
                        "Role": st.column_config.Column("Role", width="medium"),
                    },
                    hide_index=True,
                    width="stretch",
                )
            else:
                st.info("No players selected yet.")

            if selected_count == 15 and remaining_budget >= 0:
                st.markdown("---")
                st.subheader("⭐ Select Captain & Underdog")

                # 1. Captain-Auswahl
                max_price = selected_df["price"].max()
                eligible_captains = selected_df[selected_df["price"] < max_price]
                captain_options = eligible_captains.set_index("id")["name"].to_dict()

                default_captain_name = (
                    current_captain["name"]
                    if current_captain
                    and current_captain.get("name") in captain_options.values()
                    else None
                )

                if captain_options:
                    default_captain_index = (
                        list(captain_options.values()).index(default_captain_name)
                        if default_captain_name in captain_options.values()
                        else 0
                    )

                    captain_name = st.selectbox(
                        "Select your **Team Captain** (x2 Points, must not be the most expensive player):",
                        options=captain_options.values(),
                        index=default_captain_index,
                        key="edit_captain_select",
                    )
                    captain_id = int(
                        eligible_captains[eligible_captains["name"] == captain_name][
                            "id"
                        ].iloc[0]
                    )
                    captain_ok = True  # Captain erfolgreich gewählt
                else:
                    st.error(
                        "❌ No eligible Captain player found! (Must not be the most expensive player in your squad)."
                    )
                    captain_ok = False

                # 2. Underdog-Auswahl
                underdog_candidates = selected_df[selected_df["price"] < 800]
                underdog_options = underdog_candidates.set_index("id")["name"].to_dict()
                default_underdog_name = (
                    current_underdog["name"]
                    if current_underdog
                    and current_underdog.get("name") in underdog_options.values()
                    else None
                )

                if underdog_options:
                    default_underdog_index = (
                        list(underdog_options.values()).index(default_underdog_name)
                        if default_underdog_name in underdog_options.values()
                        else 0
                    )

                    underdog_name = st.selectbox(
                        "Select your **Underdog** (x2 Points, Price < 800.0):",
                        options=underdog_options.values(),
                        index=default_underdog_index,
                        key="edit_underdog_select",
                    )
                    underdog_id = int(
                        underdog_candidates[
                            underdog_candidates["name"] == underdog_name
                        ]["id"].iloc[0]
                    )
                    underdog_ok = True
                else:
                    st.error(
                        "❌ No eligible Underdog player (Price < 800.0) selected in your team!"
                    )
                    underdog_ok = False

                # Rollen sind nur wählbar, wenn Captain UND Underdog erfolgreich waren
                can_select_roles = captain_ok and underdog_ok

                st.markdown("---")
                st.subheader("🏆 Champion Pick")

                all_player_options = df.set_index("id")["name"].to_dict()
                select_champion_label = "--- Select Champion ---"

                # Standardwert für den Champion-Tipp laden
                default_champion_name = (
                    current_champion.get("name")
                    if current_champion and current_champion.get("name")
                    else select_champion_label  # Wenn kein Champion gesetzt, wähle den Platzhalter
                )

                champion_options_list = [select_champion_label] + list(
                    all_player_options.values()
                )

                default_champion_index = (
                    champion_options_list.index(default_champion_name)
                    if default_champion_name in champion_options_list
                    else 0
                )

                champion_name = st.selectbox(
                    "Select your **Champion Pick** (Bonus Points if they win the tournament):",
                    options=champion_options_list,
                    index=default_champion_index,
                    key="edit_champion_select",
                )

                # Finde die ID des ausgewählten Spielers
                if champion_name != select_champion_label:
                    champion_id_list = df[df["name"] == champion_name]["id"].tolist()
                    if champion_id_list:
                        champion_id = int(champion_id_list[0])
                        can_select_champion = True
                    else:
                        can_select_champion = False
                else:
                    st.warning("⚠️ Please pick a Champion.")
                    can_select_champion = False

                st.markdown("---")

            else:
                can_select_roles = False
                can_select_champion = False

            can_save = (
                (selected_count == 15)
                and (remaining_budget >= 0)
                and can_select_roles  # Prüft Captain & Underdog
                and can_select_champion  # Prüft Champion
            )

            if can_save:
                if st.button("💾 Save Team Changes"):
                    payload = {
                        "player_ids": selected_ids,
                        "captain_id": captain_id,
                        "underdog_id": underdog_id,
                        "champion_id": champion_id,
                    }

                    response = requests.put(f"{BASE_URL}/teams/{team_id}", json=payload)
                    if response.status_code == 200:
                        st.success("Team updated successfully!")
                        st.session_state.current_page = "overview"
                        st.rerun()
                    else:
                        st.error(f"Error updating team: {response.text}")
            else:
                st.warning(
                    "⚠️ Select exactly 15 players, stay within budget, and choose Captain, Underdog, and Champion."
                )

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
                    "seed": st.column_config.Column("Seed", width="tiny"),
                    "name": st.column_config.Column("Name"),
                    "price": st.column_config.Column("Price"),
                    "flag_url": st.column_config.ImageColumn("Nation", width=50),
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
            champion_id = None
            can_select_roles = False
            can_select_champion = False

            # --- Teamübersicht ---
            if not selected_df.empty:
                st.subheader("✅ Your Current Team")

                # Code zur Kennzeichnung:
                selected_df["Role"] = ""
                if captain_id in selected_ids:
                    selected_df.loc[selected_df["id"] == captain_id, "Role"] = (
                        "CAPTAIN 👑 (x2)"
                    )
                if underdog_id in selected_ids:
                    selected_df.loc[selected_df["id"] == underdog_id, "Role"] += (
                        " / UNDERDOG 🐕 (x2)"
                        if selected_df.loc[
                            selected_df["id"] == underdog_id, "Role"
                        ].iloc[0]
                        else "UNDERDOG 🐕 (x2)"
                    )

                st.dataframe(
                    selected_df[["seed", "name", "price", "flag_url", "Role"]],
                    column_config={
                        "seed": st.column_config.Column("Seed", width="tiny"),
                        "name": st.column_config.Column("Player Name", width="medium"),
                        "price": st.column_config.NumberColumn(
                            "Price", format="compact", width="small"
                        ),
                        "flag_url": st.column_config.ImageColumn("Nation", width=50),
                        "Role": st.column_config.Column("Role", width="medium"),
                    },
                    hide_index=True,
                    width="stretch",
                )
            else:
                st.info("No players selected yet.")
                # 3. Champion Auswahl

            if selected_count == 15 and remaining_budget >= 0:

                st.markdown("---")
                st.subheader("⭐ Select Captain & Underdog")

                # 1. Captain Auswahl
                max_price = selected_df["price"].max()
                eligible_captains = selected_df[selected_df["price"] < max_price]
                captain_options = eligible_captains.set_index("id")["name"].to_dict()

                if captain_options:
                    captain_name = st.selectbox(
                        "Select your **Team Captain** (x2 Points, must not be the most expensive player):",
                        options=captain_options.values(),
                        key="create_captain_select",
                    )
                    captain_id = int(
                        eligible_captains[eligible_captains["name"] == captain_name][
                            "id"
                        ].iloc[0]
                    )
                    captain_ok = True
                else:
                    st.error("❌ No eligible Captain player found!")
                    captain_ok = False

                # 2. Underdog Auswahl
                underdog_candidates = selected_df[selected_df["price"] < 800]
                underdog_options = underdog_candidates.set_index("id")["name"].to_dict()

                if underdog_options:
                    underdog_name = st.selectbox(
                        "Select your **Underdog** (x2 Points, Price < 800.0):",
                        options=underdog_options.values(),
                        key="create_underdog_select",
                    )
                    underdog_id = int(
                        underdog_candidates[
                            underdog_candidates["name"] == underdog_name
                        ]["id"].iloc[0]
                    )
                    underdog_ok = True
                else:
                    st.error(
                        "❌ No eligible Underdog player (Price < 800.0) selected in your team!"
                    )
                    underdog_ok = False

                can_select_roles = captain_ok and underdog_ok

                st.markdown("---")
                st.subheader("🏆 Champion Pick")

                champion_options_names = df.set_index("id")["name"].to_dict()

                champion_name = st.selectbox(
                    "Select your **Champion Pick** (Bonus Points if they win the tournament):",
                    options=["--- Select Champion ---"]
                    + list(champion_options_names.values()),
                    key="create_champion_select",
                )

                # Finde die ID des ausgewählten Spielers
                if champion_name != "--- Select Champion ---" and champion_name:
                    champion_id_list = df[df["name"] == champion_name]["id"].tolist()
                    if champion_id_list:
                        champion_id = int(champion_id_list[0])
                        can_select_champion = True
                    else:
                        can_select_champion = False  # Sollte nicht passieren
                else:
                    st.warning("⚠️ Please pick a Champion.")
                    can_select_champion = False

            else:
                can_select_roles = False
                can_select_champion = False

            # --- Team speichern ---

            can_create = (
                (selected_count == 15)
                and (remaining_budget >= 0)
                and can_select_roles
                and can_select_champion
            )
            team_name = st.text_input("Team name", "My Dream Team")

            if can_create:
                if st.button("✅ Create Team"):

                    # --- NEU: PRÜFUNG DES TEAMNAMEN ---
                    # 1. API-Aufruf zur Überprüfung des Teamnamens
                    try:
                        # ANNAHME: Der Backend-Service bietet einen GET-Endpunkt zur Prüfung der Verfügbarkeit
                        check_response = requests.post(
                            f"{BASE_URL}/teams/check_name",
                            json={"team_name": team_name},  # Senden im Body
                        )
                    except requests.exceptions.RequestException as e:
                        st.error(f"❌ Connection error during name check: {e}")
                        st.stop()

                    # 2. Prüfen der Verfügbarkeit
                    if (
                        check_response.status_code == 409
                    ):  # 409 Conflict oder ein ähnlicher Code für "bereits existiert"
                        st.error(
                            f"⚠️ The team name **'{team_name}'** is already taken. Please choose a different name."
                        )
                        # st.stop() ist hier nicht nötig, da wir den Erstellungsprozess nur überspringen

                    elif check_response.status_code != 200:
                        st.error(
                            f"❌ An error occurred during team name availability check. Status: {check_response.status_code}"
                        )

                    else:
                        # Statuscode ist 200: Name ist verfügbar, Team erstellen

                        payload = {
                            "user_id": int(st.session_state.user_id),
                            "team_name": team_name,
                            "player_ids": selected_ids,
                            "captain_id": captain_id,
                            "underdog_id": underdog_id,
                            "champion_id": champion_id,
                        }

                        response = requests.post(f"{BASE_URL}/teams/", json=payload)

                        if response.status_code == 200:
                            st.success("✅ Team successfully created!")
                            st.session_state.current_page = "overview"
                            st.rerun()
                        else:
                            # Zeigt die Fehlermeldung vom Backend an
                            st.error(f"Error creating team: {response.text}")

            else:
                st.warning(
                    "⚠️ Select exactly 15 players, stay within budget, and choose Captain, Underdog, and Champion."
                )

elif page == "📝 Manage Accounts":

    st.title("🛡️ Admin User Management")

    # 1. Admin Check
    if st.session_state.get("is_admin") != True:
        st.warning("🚫 Admin privileges required to access user management!")
        st.stop()

    st.markdown("---")

    # 2. Add New User Section
    st.header("➕ Create New User")
    with st.form("create_new_user_form"):
        new_username = st.text_input("Username")
        new_password = st.text_input("Password", type="password")
        is_new_admin = st.checkbox("Create as Admin?", value=False)

        submitted = st.form_submit_button("Create User")

        if submitted and new_username and new_password:
            try:
                create_new_user(new_username, new_password, is_new_admin)
                st.success(f"User **'{new_username}'** created successfully.")
                st.rerun()
            except Exception as e:
                st.error(f"Error creating user: {e}")
        elif submitted:
            st.error("Please enter both username and password.")

    st.markdown("---")

    # 3. Display User List and Change Admin Status
    st.header("👥 All Registered Users")

    users = fetch_users()

    if users:
        for user in users:
            col1, col2, col3, col4 = st.columns([1, 2, 2, 1])

            col1.write(f"**ID:** {user['id']}")
            col2.write(f"**Username:** {user['username']}")

            is_current_user = user.get("id") == st.session_state.get("user_id")

            # Checkbox for Admin Status
            new_status = col3.checkbox(
                f"Admin Status",
                value=user.get("is_admin", False),
                key=f"admin_check_{user['id']}",
                disabled=is_current_user,
            )

            if new_status != user.get("is_admin", False) and not is_current_user:
                if col3.button("Save Status", key=f"save_btn_{user['id']}"):
                    update_user_admin_status(user["id"], new_status)
            elif is_current_user and new_status != user.get("is_admin", False):
                col3.warning("Cannot change your own admin status.")

            if not is_current_user:
                # 1. DELETE BUTTON
                delete_button_pressed = col4.button(
                    "🗑️ Delete", key=f"delete_btn_{user['id']}"
                )

                # 2. ÜBERPRÜFUNG DER BESTÄTIGUNG

                # Zustand prüfen: Ist die Bestätigung für diesen spezifischen Benutzer aktiv?
                if (
                    delete_button_pressed
                    and st.session_state.get("confirm_delete_user_id") == user["id"]
                ):

                    try:
                        delete_user_by_id(user["id"])

                        st.session_state["confirm_delete_user_id"] = None
                        st.success(f"User '{user['username']}' successfully deleted.")
                        st.rerun()

                    except Exception as e:
                        st.error(f"Error deleting user: {e}")
                        st.session_state["confirm_delete_user_id"] = None

                elif delete_button_pressed:

                    st.session_state["confirm_delete_user_id"] = user["id"]
                    st.warning(
                        f"⚠️ **CONFIRM DELETION:** Press the '🗑️ Delete' button again to permanently delete user '{user['username']}'."
                    )
                    st.stop()

            else:
                col4.write("🚫 Self-Delete")

    else:
        st.info("No users found or error loading data.")
