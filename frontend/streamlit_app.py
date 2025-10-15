import streamlit as st
import requests
import pandas as pd
import math
import re

import os

# Wenn auf Streamlit Cloud: nimm BASE_URL aus den Secrets
# Wenn lokal: fallback auf localhost
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")

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
        "⚔️ Tournament Bracket",
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

    # --- Team Detail Seite ---
    if st.session_state.current_page == "team_detail":
        team_id = st.session_state.selected_team_id
        team_name = st.session_state.selected_team_name

        st.title(f"🎯 Team: {team_name}")

        # Spieler laden
        players = requests.get(f"{BASE_URL}/teams/{team_id}/players").json()

        if players:
            df_players = pd.DataFrame(players)
            df_players["flag_url"] = df_players["nation"].apply(get_flag_url)

            # --- Nach Punkten absteigend sortieren ---
            df_players = df_players.sort_values(
                by="points", ascending=False
            ).reset_index(drop=True)

            # --- Punkte hervorheben: grün, wenn > 0 ---
            # def highlight_points(val):
            #     color = "green" if val > 0 else "black"
            #     return f"color: {color}"

            # st.dataframe(
            #     df_players[
            #         ["seed", "name", "price", "flag_url", "points"]
            #     ].style.applymap(highlight_points, subset=["points"]),
            #     column_config={
            #         "seed": st.column_config.Column("Seed"),
            #         "name": st.column_config.Column("Player Name"),
            #         "price": st.column_config.NumberColumn("Price", format="compact"),
            #         "flag_url": st.column_config.ImageColumn("Nation"),
            #         "points": st.column_config.NumberColumn("Points", format="compact"),
            #     },
            #     width="stretch",
            #     hide_index=True,
            # )
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
        else:
            st.info("No players found for this team.")

        # Zurück-Button
        st.button("⬅️ Back to Leaderboard", on_click=back_to_overview)

    # --- Leaderboard Seite ---
    # elif st.session_state.current_page == "overview":
    else:
        st.title("🏠 Overview & Leaderboard")

        # Load leaderboard
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

        # # Display upcoming matches
        # st.subheader("📅 Tournament Bracket")
        # # try:

        # players = requests.get(f"{BASE_URL}/players/").json()
        # df_players = pd.DataFrame(players)
        # df_players = df_players.sort_values("seed").head(64).reset_index(drop=True)

        # num_players = 64
        # num_rounds = int(math.log2(num_players))
        # rows = num_players * 2 - 1

        # # --- Seed-Reihenfolge generieren ---
        # def generate_bracket(n):
        #     if n == 1:
        #         return [1]
        #     prev = generate_bracket(n // 2)
        #     result = []
        #     for p in prev:
        #         result.append(p)
        #         result.append(n + 1 - p)
        #     return result

        # bracket = generate_bracket(num_players)

        # # --- Session-State initialisieren ---

        # if "winners" not in st.session_state:
        #     st.session_state["winners"] = {}

        # results = requests.get(f"{BASE_URL}/matches/results/").json()
        # for match in results:
        #     match_id = match["match_id"]
        #     winner_id = match["winner_id"]
        #     winner = f"{df_players.loc[df_players['id'] == winner_id, 'name'].values[0]} ({df_players.loc[df_players['id'] == winner_id, 'seed'].values[0]})"
        #     st.session_state["winners"][match_id] = winner

        # if "match_data" not in st.session_state:
        #     st.session_state["match_data"] = {}
        # if "current_match" not in st.session_state:
        #     st.session_state["current_match"] = None

        # # --- Tabelle aufbauen ---
        # table = pd.DataFrame(
        #     "",
        #     index=range(rows),
        #     columns=[f"Round {i+1}" for i in range(num_rounds)],
        # )

        # # Runde 1
        # for i, seed in enumerate(bracket):
        #     row = i * 2
        #     player = f"{df_players.loc[seed-1, 'name']} ({seed})"
        #     table.iloc[row, 0] = player

        # # Weitere Runden: Platzhalter setzen
        # for r in range(1, num_rounds):
        #     step = 2**r
        #     for i in range(0, rows, step * 2):
        #         row_winner = i + step - 1
        #         match_id = f"match_{row_winner}_{r}"
        #         table.iloc[row_winner, r] = st.session_state["winners"].get(
        #             match_id, "?"
        #         )

        # # --- Dynamische Breite ---
        # max_name_len = max(len(str(name)) for name in df_players["name"])
        # button_width = int(max_name_len * 8.5 + 60)

        # # st.write("## 🗓 Match Schedule")

        # # --- CSS ---
        # st.markdown(
        #     f"""
        # <style>
        # .bracket-box {{
        #     border: 2px solid black;
        #     border-radius: 6px;
        #     padding: 6px;
        #     text-align: center;
        #     background-color: #FFFFFF;
        #     width: {button_width}px;
        #     min-height: 30px;
        #     display: flex;
        #     align-items: center;
        #     justify-content: center;
        # }}
        # .empty-cell {{
        #     min-width: {button_width}px;
        #     min-height: 30px;
        # }}
        # .bracket-btn > button {{
        #     min-width: {button_width}px !important;
        #     min-height: 30px !important;
        # }}
        # </style>
        # """,
        #     unsafe_allow_html=True,
        # )

        # # st.write("## 🏆 Tournament Bracket")

        # # # --- Anzeige der Tabelle ---
        # # for row_idx, row in enumerate(table.itertuples(index=False)):
        # #     cols = st.columns(len(table.columns) * 2 - 1)
        # #     for col_idx, val in enumerate(row):
        # #         col = cols[col_idx * 2]
        # #         if val != "":
        # #             if val == "?":
        # #                 prev_col = col_idx - 1
        # #                 step = 2**col_idx
        # #                 top_row = max(row_idx - step // 2, 0)
        # #                 bottom_row = min(row_idx + step // 2, rows - 1)
        # #                 top_player = table.iloc[top_row, prev_col]
        # #                 bottom_player = table.iloc[bottom_row, prev_col]

        # #                 match_id = f"match_{row_idx}_{col_idx}"

        # #                 with col:
        # #                     if st.button("?", key=match_id):
        # #                         st.session_state.current_match = match_id
        # #                         st.session_state.current_page = "match_detail"
        # #                         st.session_state.match_data[match_id] = {
        # #                             "p1_name": top_player,
        # #                             "p2_name": bottom_player,
        # #                             "legs": None,
        # #                             "180s": None,
        # #                             "sets": None,
        # #                             "high_checkout": None,
        # #                             "average": None,
        # #                             "checkout_pct": None,
        # #                         }
        # #                         st.rerun()
        # #             else:
        # #                 col.markdown(
        # #                     f"<div class='bracket-box'>{val}</div>",
        # #                     unsafe_allow_html=True,
        # #                 )
        # #         else:
        # #             col.markdown(
        # #                 f"<div class='empty-cell'></div>", unsafe_allow_html=True
        # #             )
        # for row_idx, row in enumerate(table.itertuples(index=False)):
        #     cols = st.columns(len(table.columns) * 2)
        #     for col_idx, val in enumerate(row):
        #         box_col = cols[col_idx * 2]  # Spalte für Box
        #         between_col = cols[col_idx * 2 + 1]  # Zwischen-Spalte

        #         if val != "":
        #             match_id = f"match_{row_idx}_{col_idx}"

        #             # Box anzeigen
        #             box_col.markdown(
        #                 f"<div class='bracket-box'>{val}</div>", unsafe_allow_html=True
        #             )

        #             # Ab Runde 2 den Edit-Button in der freien Spalte zwischen den Runden
        #             if col_idx > 0:
        #                 prev_col = col_idx - 1
        #                 step = 2**col_idx
        #                 top_row = max(row_idx - step // 2, 0)
        #                 bottom_row = min(row_idx + step // 2, rows - 1)
        #                 top_player = table.iloc[top_row, prev_col]
        #                 bottom_player = table.iloc[bottom_row, prev_col]

        #                 with between_col:
        #                     # between_col.markdown("<div style='visibility: hidden; height: 30px;'>_</div>", unsafe_allow_html=True)

        #                     # Button oben drüber
        #                     # st.markdown(
        #                     #     "<div style='text-align: right; margin-top: -30px;'>",
        #                     #     unsafe_allow_html=True,
        #                     # )
        #                     if st.button("Edit", key=match_id):
        #                         st.session_state.current_match = match_id
        #                         st.session_state.current_page = "match_detail"
        #                         st.session_state.match_data[match_id] = {
        #                             "p1_name": top_player,
        #                             "p2_name": bottom_player,
        #                             "legs": None,
        #                             "180s": None,
        #                             "sets": None,
        #                             "high_checkout": None,
        #                             "average": None,
        #                             "checkout_pct": None,
        #                         }
        #                         st.rerun()

        #         else:
        #             # leere Zelle
        #             box_col.markdown(
        #                 f"<div class='empty-cell'></div>", unsafe_allow_html=True
        #             )

        # --- Match-Fenster ---
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
# 🔹 Spielerübersicht
# -----------------------------------
elif page == "⚔️ Tournament Bracket":

    st.title("⚔️ Tournament Bracket")
    players = requests.get(f"{BASE_URL}/players/").json()
    df_players = pd.DataFrame(players)
    df_players = df_players.sort_values("seed").head(64).reset_index(drop=True)

    num_players = 64
    num_rounds = int(math.log2(num_players))
    rows = num_players * 2 - 1

    # --- Seed-Reihenfolge generieren ---
    def generate_bracket(n):
        if n == 1:
            return [1]
        prev = generate_bracket(n // 2)
        result = []
        for p in prev:
            result.append(p)
            result.append(n + 1 - p)
        return result

    bracket = generate_bracket(num_players)

    # --- Session-State initialisieren ---

    if "winners" not in st.session_state:
        st.session_state["winners"] = {}

    results = requests.get(f"{BASE_URL}/matches/results/").json()
    for match in results:
        match_id = match["match_id"]
        winner_id = match["winner_id"]
        winner = f"{df_players.loc[df_players['id'] == winner_id, 'name'].values[0]} ({df_players.loc[df_players['id'] == winner_id, 'seed'].values[0]})"
        st.session_state["winners"][match_id] = winner

    if "match_data" not in st.session_state:
        st.session_state["match_data"] = {}
    if "current_match" not in st.session_state:
        st.session_state["current_match"] = None

    # --- Tabelle aufbauen ---
    table = pd.DataFrame(
        "",
        index=range(rows),
        columns=[f"Round {i+1}" for i in range(num_rounds + 1)],
    )

    # Runde 1
    for i, seed in enumerate(bracket):
        row = i * 2
        player = f"{df_players.loc[seed-1, 'name']} ({seed})"
        table.iloc[row, 0] = player

    # Weitere Runden: Platzhalter setzen
    for r in range(1, num_rounds + 1):
        step = 2**r
        for i in range(0, rows, step * 2):
            row_winner = i + step - 1
            match_id = f"match_{row_winner}_{r}"
            table.iloc[row_winner, r] = st.session_state["winners"].get(match_id, "?")

    # --- Dynamische Breite ---
    max_name_len = max(len(str(name)) for name in df_players["name"])
    button_width = int(max_name_len * 8.5 + 25)

    # st.write("## 🗓 Match Schedule")

    # --- CSS ---
    st.markdown(
        f"""
    <style>
    .bracket-box {{
        border: 2px solid black;
        border-radius: 6px;
        padding: 6px;
        text-align: center;
        background-color: #FFFFFF;
        width: {button_width}px;
        min-height: 30px;
        display: flex;
        align-items: center;
        justify-content: center;
    }}
    .empty-cell {{
        min-width: {button_width}px;
        min-height: 30px;
    }}
    .bracket-btn > button {{
        min-width: {button_width}px !important;
        min-height: 30px !important;
    }}
    </style>
    """,
        unsafe_allow_html=True,
    )

    # st.write("## 🏆 Tournament Bracket")

    # --- Anzeige der Tabelle ---
    for row_idx, row in enumerate(table.itertuples(index=False)):
        cols = st.columns(len(table.columns) * 2 + 1)
        for col_idx, val in enumerate(row):
            col = cols[col_idx * 2]
            if val != "":
                # if val == "?":
                #     prev_col = col_idx - 1
                #     step = 2**col_idx
                #     top_row = max(row_idx - step // 2, 0)
                #     bottom_row = min(row_idx + step // 2, rows - 1)
                #     top_player = table.iloc[top_row, prev_col]
                #     bottom_player = table.iloc[bottom_row, prev_col]

                #     match_id = f"match_{row_idx}_{col_idx}"

                #     with col:
                #         if st.button("?", key=match_id):
                #             st.session_state.current_match = match_id
                #             st.session_state.current_page = "match_detail"
                #             st.session_state.match_data[match_id] = {
                #                 "p1_name": top_player,
                #                 "p2_name": bottom_player,
                #                 "legs": None,
                #                 "180s": None,
                #                 "sets": None,
                #                 "high_checkout": None,
                #                 "average": None,
                #                 "checkout_pct": None,
                #             }
                #             st.rerun()
                # else:
                col.markdown(
                    f"<div class='bracket-box'>{val}</div>",
                    unsafe_allow_html=True,
                )
            else:
                col.markdown(f"<div class='empty-cell'></div>", unsafe_allow_html=True)
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
    selected_nation = st.selectbox("🌍 Nation filtern", ["All"] + nations)
    if selected_nation != "All":
        df_players = df_players[df_players["nation"] == selected_nation]

    # st.dataframe(
    #     df_players[["seed", "name", "flag_url", "price"]],
    #     column_config={
    #         "seed": st.column_config.Column("Seed", width="small"),
    #         "name": st.column_config.Column("Name"),
    #         "price": st.column_config.Column("Price"),
    #         # "nation": st.column_config.Column("Nation"),
    #         "flag_url": st.column_config.ImageColumn("Nation", width="small"),
    #     },
    #     column_order=["seed","flag_url",  "name", "price",],
    #     width="stretch",
    #     hide_index=True,
    # )
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
    if st.session_state.current_page != "match_detail":
        st.write("## 🗓 Match Schedule")
        players = requests.get(f"{BASE_URL}/players/").json()
        df_players = pd.DataFrame(players)
        df_players = df_players.sort_values("seed").head(64).reset_index(drop=True)

        num_players = 64
        num_rounds = int(math.log2(num_players))
        rows = num_players * 2 - 1

        # --- Seed-Reihenfolge generieren ---
        def generate_bracket(n):
            if n == 1:
                return [1]
            prev = generate_bracket(n // 2)
            result = []
            for p in prev:
                result.append(p)
                result.append(n + 1 - p)
            return result

        bracket = generate_bracket(num_players)

        # --- Session-State initialisieren ---

        if "winners" not in st.session_state:
            st.session_state["winners"] = {}

        results = requests.get(f"{BASE_URL}/matches/results/").json()
        for match in results:
            match_id = match["match_id"]
            winner_id = match["winner_id"]
            winner = f"{df_players.loc[df_players['id'] == winner_id, 'name'].values[0]} ({df_players.loc[df_players['id'] == winner_id, 'seed'].values[0]})"
            st.session_state["winners"][match_id] = winner

        if "match_data" not in st.session_state:
            st.session_state["match_data"] = {}
        if "current_match" not in st.session_state:
            st.session_state["current_match"] = None

        # --- Tabelle aufbauen ---
        table = pd.DataFrame(
            "",
            index=range(rows),
            columns=[f"Round {i+1}" for i in range(num_rounds)],
        )

        # Runde 1
        for i, seed in enumerate(bracket):
            row = i * 2
            player = f"{df_players.loc[seed-1, 'name']} ({seed})"
            table.iloc[row, 0] = player

        # Weitere Runden: Platzhalter setzen
        for r in range(1, num_rounds):
            step = 2**r
            for i in range(0, rows, step * 2):
                row_winner = i + step - 1
                match_id = f"match_{row_winner}_{r}"
                table.iloc[row_winner, r] = st.session_state["winners"].get(
                    match_id, "?"
                )

        # --- Dynamische Breite ---
        max_name_len = max(len(str(name)) for name in df_players["name"])
        button_width = int(max_name_len * 8.5 + 60)

        for r in range(1, num_rounds):
            step = 2**r
            for i in range(0, rows, step * 2):
                row_winner = i + step - 1
                match_id = f"match_{row_winner}_{r}"
                p1_row = i
                p2_row = i + step
                p1_name = table.iloc[p1_row, r - 1]
                p2_name = table.iloc[p2_row, r - 1]

                # Nur echte Spieler anzeigen (nicht leere Zellen)
                if p1_name != "" and p2_name != "":
                    cols = st.columns([2, 2, 1])
                    cols[0].markdown(f"**{p1_name}**")
                    cols[1].markdown(f"**{p2_name}**")
                    if cols[2].button("Edit", key=match_id):
                        st.session_state.current_match = match_id
                        st.session_state.current_page = "match_detail"
                        st.session_state.match_data[match_id] = {
                            "p1_name": p1_name,
                            "p2_name": p2_name,
                            "legs": None,
                            "180s": None,
                            "sets": None,
                            "high_checkout": None,
                            "average": None,
                            "checkout_pct": None,
                        }
                        st.rerun()

    elif st.session_state.current_page == "match_detail":
        match_id = st.session_state.current_match
        match_info = st.session_state.match_data[match_id]
        players = requests.get(f"{BASE_URL}/players/").json()
        df_players = pd.DataFrame(players)
        player_base_name1 = re.match(r"^(.*?) \(\d+\)$", match_info["p1_name"])
        if player_base_name1:
            player_base_name1 = player_base_name1.group(1)
        else:
            player_base_name1 = match_info["p1_name"]

        player_base_name2 = re.match(r"^(.*?) \(\d+\)$", match_info["p2_name"])
        if player_base_name2:
            player_base_name2 = player_base_name2.group(1)
        else:
            player_base_name2 = match_info["p2_name"]

        p1_id = df_players.loc[df_players["name"] == player_base_name1, "id"].values[0]
        p2_id = df_players.loc[df_players["name"] == player_base_name2, "id"].values[0]
        st.write(f"### 🏹 Match Details – {match_id}")
        st.write(f"**Player 1:** {match_info["p1_name"]}")
        st.write(f"**Player 2:** {match_info["p2_name"]}")

        # Stats-Eingabe
        match_info["sets"] = st.number_input(
            f"Sets {match_info["p1_name"]}",
            min_value=0,
            max_value=50,
            key=f"{match_id}_sets_p1",
        )
        match_info["legs"] = st.number_input(
            f"Legs {match_info["p1_name"]}",
            min_value=0,
            max_value=50,
            key=f"{match_id}_legs_p1",
        )
        match_info["180s"] = st.number_input(
            f"180s {match_info["p1_name"]}",
            min_value=0,
            max_value=50,
            key=f"{match_id}_180s_p1",
        )
        match_info["high_checkout"] = st.number_input(
            f"High Checkout {match_info["p1_name"]}",
            min_value=0,
            max_value=180,
            key=f"{match_id}_high_p1",
        )
        match_info["average"] = st.number_input(
            f"Average {match_info["p1_name"]}",
            min_value=0.0,
            max_value=200.0,
            key=f"{match_id}_avg_p1",
        )
        match_info["checkout_pct"] = st.number_input(
            f"Checkout % {match_info["p1_name"]}",
            min_value=0.0,
            max_value=100.0,
            key=f"{match_id}_co_p1",
        )

        match_info["sets_p2"] = st.number_input(
            f"Sets {match_info["p2_name"]}",
            min_value=0,
            max_value=50,
            key=f"{match_id}_sets_p2",
        )
        match_info["legs_p2"] = st.number_input(
            f"Legs {match_info["p2_name"]}",
            min_value=0,
            max_value=50,
            key=f"{match_id}_legs_p2",
        )
        match_info["180s_p2"] = st.number_input(
            f"180s {match_info["p2_name"]}",
            min_value=0,
            max_value=50,
            key=f"{match_id}_180s_p2",
        )
        match_info["high_checkout_p2"] = st.number_input(
            f"High Checkout {match_info["p2_name"]}",
            min_value=0,
            max_value=180,
            key=f"{match_id}_high_p2",
        )
        match_info["average_p2"] = st.number_input(
            f"Average {match_info["p2_name"]}",
            min_value=0.0,
            max_value=200.0,
            key=f"{match_id}_avg_p2",
        )
        match_info["checkout_pct_p2"] = st.number_input(
            f"Checkout % {match_info["p2_name"]}",
            min_value=0.0,
            max_value=100.0,
            key=f"{match_id}_co_p2",
        )
        if st.button("Back"):
            st.session_state.current_page = "overview"
            st.rerun()
        if st.button("Save Match"):
            players = requests.get(f"{BASE_URL}/players/").json()
            df_players = pd.DataFrame(players)
            df_players = df_players.sort_values("seed").head(64).reset_index(drop=True)
            # Gewinner bestimmen
            winner_id = p1_id if match_info["sets"] > match_info["sets_p2"] else p2_id
            winner_name = (
                match_info["p2_name"]
                if match_info["sets"] > match_info["sets_p2"]
                else match_info["p2_name"]
            )
            payload = {
                "match_id": match_id,
                "p1_id": int(p1_id),
                "p2_id": int(p2_id),
                "winner_id": int(winner_id),
                "sets_p1": match_info["sets"],
                "sets_p2": match_info["sets_p2"],
                "legs_p1": match_info["legs"],
                "legs_p2": match_info["legs_p2"],
                # optional weitere stats
                "average_p1": match_info["average"],
                "average_p2": match_info["average_p2"],
                "checkout_pct_p1": match_info["checkout_pct"],
                "checkout_pct_p2": match_info["checkout_pct_p2"],
                "high_checkout_p1": match_info["high_checkout"],
                "high_checkout_p2": match_info["high_checkout_p2"],
                "180s_p1": match_info["180s"],
                "180s_p2": match_info["180s_p2"],
            }

            resp = requests.put(f"{BASE_URL}/matches/save_match/", json=payload)
            try:
                msg = resp.json().get("msg", "No message returned")
            except ValueError:
                # Kein JSON erhalten
                msg = f"Error: server returned status {resp.status_code}, body: {resp.text}"
            requests.put(f"{BASE_URL}/players/points/recompute", json=payload)
            st.session_state.current_match = None
            st.session_state.current_page = "overview"
            st.rerun()
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

        # --- Lade Team-Spieler ---
        try:
            team_players = requests.get(f"{BASE_URL}/teams/{team_id}/players").json()
        except Exception as e:
            st.error(f"Fehler beim Laden der Teamspieler: {e}")
            st.stop()

        # IDs der aktuellen Teamspieler
        current_player_ids = (
            [p["id"] for p in team_players] if isinstance(team_players, list) else []
        )

        # --- Lade alle Spieler ---
        try:
            players = requests.get(f"{BASE_URL}/players/").json()
        except Exception as e:
            st.error(f"Fehler beim Laden der Spielerliste: {e}")
            players = []

        if not isinstance(players, list) or len(players) == 0:
            st.error("❌ Keine Spieler gefunden!")
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
            disabled=["seed", "name", "price", "nation", "id"],
            key="edit_team_editor",
        )

        # --- Auswahl aktualisieren ---
        selected_df = edited_df[edited_df["selected"]]
        selected_ids = selected_df["id"].tolist()
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

        # --- Aktuelles Team anzeigen ---
        if not selected_df.empty:
            st.subheader("✅ Your Current Team")
            st.dataframe(
                selected_df[["seed", "name", "price", "flag_url"]],
                column_config={
                    "seed": st.column_config.Column("Seed", width="tiny"),
                    "name": st.column_config.Column("Player Name"),
                    "price": st.column_config.Column("Price"),
                    "flag_url": st.column_config.ImageColumn("Flag", width="tiny"),
                },
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("No players selected yet.")

        # --- Update / Save Button ---
        can_save = (selected_count == 15) and (remaining_budget >= 0)
        if can_save:
            if st.button("💾 Save Team Changes"):
                payload = {"player_ids": selected_ids}
                response = requests.put(f"{BASE_URL}/teams/{team_id}", json=payload)
                if response.status_code == 200:
                    st.success("Team updated successfully!")
                    # st.session_state.current_page = "teams_overview"
                    st.session_state.current_page = "overview"
                    st.rerun()
                else:
                    st.error(f"Error updating team: {response.text}")
        else:
            st.warning("Team not valid (check player count or budget).")

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
            st.error(f"Fehler beim Laden der Spieler: {e}")
            st.stop()

        if not isinstance(players, list) or len(players) == 0:
            st.error("❌ Keine Spieler gefunden!")
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
            disabled=["seed", "name", "price", "nation", "id"],
            key="create_team_editor",
        )

        # --- Auswahl & Budget ---
        selected_df = edited_df[edited_df["selected"]]
        selected_ids = selected_df["id"].tolist()
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

        # --- Teamübersicht ---
        if not selected_df.empty:
            st.subheader("✅ Your Current Team")
            st.dataframe(
                selected_df[["seed", "name", "price", "flag_url"]],
                column_config={
                    "seed": st.column_config.Column("Seed", width="tiny"),
                    "name": st.column_config.Column("Player Name"),
                    "price": st.column_config.Column("Price"),
                    "flag_url": st.column_config.ImageColumn("Flag", width="tiny"),
                },
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("No players selected yet.")

        # --- Team speichern ---
        can_create = (selected_count == 15) and (remaining_budget >= 0)
        team_name = st.text_input("Team name", "My Dream Team")

        if can_create:
            if st.button("✅ Create Team"):
                payload = {
                    "user_id": st.session_state.user_id,
                    "team_name": team_name,
                    "player_ids": selected_ids,
                }
                response = requests.post(f"{BASE_URL}/teams/", json=payload)
                if response.status_code == 200:
                    st.success("✅ Team successfully created!")
                    # Zurück zur Übersicht
                    # st.session_state.current_page = "teams_overview"
                    st.session_state.current_page = "overview"
                    st.rerun()
                else:
                    st.error(f"Error creating team: {response.text}")
        else:
            st.warning("⚠️ Select exactly 15 players and stay within budget.")
