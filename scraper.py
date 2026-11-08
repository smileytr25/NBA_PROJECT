from bs4 import BeautifulSoup
from dotenv import load_dotenv
from io import StringIO
import json 
import numpy as np 
import os 
import pandas as pd 
from pathlib import Path
from rate_limiting import RateLimiter
import re 
import requests
import unicodedata

loaded = load_dotenv()

base_url = os.environ["BASE_URL"]
leagues_url = base_url + "/leagues/"

def remove_accents(text):
    nfd_form = unicodedata.normalize('NFD', text)
    return "".join(c for c in nfd_form if not unicodedata.combining(c))


def get_league_urls(limiter):
    limiter.add_request() 
    req = requests.get(leagues_url)

    soup = BeautifulSoup(req.content, "html.parser")
    table = soup.find("table", id="stats")

    league_urls = {} 
    for row in table.find_all("th", attrs={"data-stat": "season", "scope": "row"}):
        href = row.find("a")["href"]
        league, year = re.search(r"/leagues/(\w+)_(\d+).html", href).groups()
        season = f"{int(year) - 1}-{year}"

        league_urls[(league, season)] = base_url + href

    return league_urls 


def get_scrape_links(league_urls, limiter):
    scrape_links = {} 
    for (league, season), url in league_urls.items():
        print(f"Getting links for the {season} season of the {league}")
        scrape_links[(league, season, "league_home")] = url 

        limiter.add_request()
        req = requests.get(url)

        if req.status_code != 200:
            raise 

        soup = BeautifulSoup(req.content, "html.parser")
        bottom_nav = soup.find("div", id="bottom_nav_container")

        link_texts = [
            "Schedule and Results", "Per Game", "Totals", "Per 36 Minutes",
            "Per 100 Possessions", "Adjusted Shooting", "Advanced"
        ]

        for link_text in link_texts:
            element = bottom_nav.find("a", string=link_text)
            if element:
                link = element["href"]
                link = re.sub(r"/leagues/", "", link)
                scrape_links[(league, season, link_text.lower().replace(" ", "_"))] = leagues_url + link
    
    return scrape_links 


def get_scraper_metadata(limiter): 
    league_urls = get_league_urls(limiter)
    scrape_links = get_scrape_links(league_urls, limiter)

    data = [
        [league, season, page, url]
        for (league, season, page), url 
        in scrape_links.items() 
    ] 

    scrape_df = pd.DataFrame(data=data)
    return scrape_df 


def scrape_schedule_and_results(metadata, soup):

    def parse_game_duration(game_duration):
        try:
            hours, minutes = game_duration.split(":")
            hours, minutes = int(hours), int(minutes)
            return 60 * hours + minutes 
        except:
            return np.nan
        
    schedule_table = soup.find("table", id="schedule")

    columns = []
    for table_header in schedule_table.find_all("th", attrs={"scope": "col"}):
        colname = table_header["data-stat"] 
        columns.append(colname)

    data = []
    for row in schedule_table.find("tbody").select('tr:not(.sr_added_headers)'):
        row_data = [] 
        
        row_data.append(row.find("th", attrs={"data-stat": "date_game"}).find("a").text) # Extract game date
        
        for colval in row.find_all("td"):
            row_data.append(colval.text)
        
        data.append(row_data)
    
    schedule_results_df = pd.DataFrame(data=data, columns=columns)

    schedule_results_df["game_timestamp"] = schedule_results_df["date_game"] + " " + schedule_results_df["game_start_time"]
    
    schedule_results_df["game_timestamp"] = pd.to_datetime(
        schedule_results_df["game_timestamp"], 
        format="mixed",
        errors="coerce"
    )

    schedule_results_df["league"] = metadata.league
    schedule_results_df["season"] = metadata.season

    schedule_results_df["overtimes"] = schedule_results_df["overtimes"].replace("", "None")
    
    schedule_results_df["game_remarks"] = schedule_results_df["game_remarks"].replace("", "None")

    schedule_results_df["game_duration"] = schedule_results_df["game_duration"].apply(parse_game_duration)

    schedule_results_df["attendance"] = schedule_results_df["attendance"].str.replace(",", "").astype(int)
    
    col_order = [
        "league", "season", "game_timestamp", "visitor_team_name", "visitor_pts",
        "home_team_name", "home_pts", "overtimes", "attendance", "game_duration", 
        "arena_name", "game_remarks"
    ]

    return schedule_results_df[col_order]


def scrape_per_game(metadata, soup):
    regular_season_table = soup.find("table", id="per_game_stats")
    post_season_table = soup.find("table", id="per_game_stats_post")

    table_frames = []
    for table in [regular_season_table, post_season_table]:
        columns = [] 
        for table_header in table.find_all("th", attrs={"scope": "col"}):
            colname = table_header["data-stat"] 
            columns.append(colname)

        data = [] 
        for row in table.find("tbody").select("tr:not(.sr_added_headers)"):
            row_data = []
            row_data.append(row.find("th", attrs={"data-stat": "ranker"}).text)

            for colval in row.find_all("td"):
                row_data.append(colval.text)

            data.append(row_data)
        
        table_df = pd.DataFrame(data=data, columns=columns)

        table_df["name_display"] = table_df["name_display"].apply(remove_accents)
        
        for col in [
            "ranker", "age", "games", "games_started", "mp_per_g", "fg_per_g",
            "fga_per_g", "fg_pct", "fg3_per_g", "fg3a_per_g", "fg3_pct",
            "fg2_per_g", "fg2a_per_g", "fg2_pct", "efg_pct", "ft_per_g",
            "fta_per_g", "ft_pct", "orb_per_g", "drb_per_g", "trb_per_g",
            "ast_per_g", "stl_per_g", "blk_per_g", "tov_per_g", "pf_per_g",
            "pts_per_g"
        ]:
            table_df[col] = table_df[col].replace('', np.nan).astype(float)
        
        table_df["league"] = metadata.league 
        table_df["season"] = metadata.season 

        renaming = {
            "name_display": "player_name",
            "team_name_abbr": "team_abbreviation"
        }
        table_df = table_df.rename(columns=renaming)

        col_order = [
            "league", "season", "player_name", "team_abbreviation", "pos",
            "age", "games", "games_started", "mp_per_g", "pts_per_g", "ast_per_g", "trb_per_g",
            "drb_per_g", "orb_per_g", "stl_per_g", "blk_per_g", "tov_per_g", "pf_per_g",
            "fg_per_g", "fga_per_g", "fg_pct", "fg2_per_g", "fg2a_per_g", "fg2_pct", 
            "fg3_per_g", "fg3a_per_g", "fg3_pct", "ft_per_g", "fta_per_g", "ft_pct",
            "efg_pct", "awards" 
        ] 

        table_frames.append(table_df[col_order])

    return table_frames 


def scrape_totals(metadata, soup):
    regular_season_table = soup.find("table", id="totals_stats")
    post_season_table = soup.find("table", id="totals_stats_post")

    table_frames = []
    for table in [regular_season_table, post_season_table]:
        columns = [] 
        for table_header in table.find_all("th", attrs={"scope": "col"}):
            colname = table_header["data-stat"] 
            columns.append(colname)

        data = [] 
        for row in table.find("tbody").select("tr:not(.sr_added_headers)"):
            row_data = []
            row_data.append(row.find("th", attrs={"data-stat": "ranker"}).text)

            for colval in row.find_all("td"):
                row_data.append(colval.text)

            data.append(row_data)
        
        table_df = pd.DataFrame(data=data, columns=columns)

        table_df["name_display"] = table_df["name_display"].apply(remove_accents)
        
        for col in [
            "age", "games", "games_started", "mp", "fg",
            "fga", "fg_pct", "fg3", "fg3a", "fg3_pct",
            "fg2", "fg2a", "fg2_pct", "efg_pct", "ft",
            "fta", "ft_pct", "orb", "drb", "trb", "ast", "stl", 
            "blk", "tov", "pf", "pts", "tpl_dbl"
        ]:
            table_df[col] = table_df[col].replace('', np.nan).astype(float)

        table_df["league"] = metadata.league 
        table_df["season"] = metadata.season 

        renaming = {
            "name_display": "player_name",
            "team_name_abbr": "team_abbreviation"
        }
        table_df = table_df.rename(columns=renaming)
        
        col_order = [
            "league", "season", "player_name", "team_abbreviation", "pos",
            "age", "games", "games_started", "mp", "pts", "ast", "trb",
            "drb", "orb", "stl", "blk", "tov", "pf",
            "fg", "fga", "fg_pct", "fg2", "fg2a", "fg2_pct", 
            "fg3", "fg3a", "fg3_pct", "ft", "fta", "ft_pct",
            "efg_pct", "tpl_dbl", "awards" 
        ] 
        table_frames.append(table_df[col_order])

    return table_frames 


def scrape_per_36_minutes(metadata, soup):
    regular_season_table = soup.find("table", id="per_minute_stats")
    post_season_table = soup.find("table", id="per_minute_stats_post")

    table_frames = []
    for table in [regular_season_table, post_season_table]:
        columns = [] 
        for table_header in table.find_all("th", attrs={"scope": "col"}):
            colname = table_header["data-stat"] 
            columns.append(colname)

        data = [] 
        for row in table.find("tbody").select("tr:not(.sr_added_headers)"):
            row_data = []
            row_data.append(row.find("th", attrs={"data-stat": "ranker"}).text)

            for colval in row.find_all("td"):
                row_data.append(colval.text)

            data.append(row_data)
        
        table_df = pd.DataFrame(data=data, columns=columns)

        table_df["name_display"] = table_df["name_display"].apply(remove_accents)
        
        for col in [
            "age", "games", "games_started", "mp", "fg_per_minute_36",
            "fga_per_minute_36", "fg_pct", "fg3_per_minute_36", "fg3a_per_minute_36", 
            "fg3_pct", "fg2_per_minute_36", "fg2a_per_minute_36", "fg2_pct", 
            "efg_pct", "ft_per_minute_36", "fta_per_minute_36", "ft_pct", 
            "orb_per_minute_36", "drb_per_minute_36", "trb_per_minute_36",
            "ast_per_minute_36", "stl_per_minute_36", "blk_per_minute_36", 
            "tov_per_minute_36", "pf_per_minute_36", "pts_per_minute_36"
        ]:
            table_df[col] = table_df[col].replace('', np.nan).astype(float)

        table_df["league"] = metadata.league 
        table_df["season"] = metadata.season 

        renaming = {
            "name_display": "player_name",
            "team_name_abbr": "team_abbreviation"
        }
        table_df = table_df.rename(columns=renaming)

        col_order = [
            "league", "season", "player_name", "team_abbreviation", "pos",
            "age", "games", "games_started", "mp", "pts_per_minute_36", "ast_per_minute_36", 
            "trb_per_minute_36", "drb_per_minute_36", "orb_per_minute_36", "stl_per_minute_36", 
            "blk_per_minute_36", "tov_per_minute_36", "pf_per_minute_36", "fg_per_minute_36", 
            "fga_per_minute_36", "fg_pct", "fg2_per_minute_36", "fg2a_per_minute_36", "fg2_pct", 
            "fg3_per_minute_36", "fg3a_per_minute_36", "fg3_pct", "ft_per_minute_36", 
            "fta_per_minute_36", "ft_pct", "efg_pct", "awards" 
        ] 
        table_frames.append(table_df[col_order])

    return table_frames 


def scrape_per_100_possessions(metadata, soup):
    regular_season_table = soup.find("table", id="per_poss")
    post_season_table = soup.find("table", id="per_poss_post")

    table_frames = []
    for table in [regular_season_table, post_season_table]:
        columns = [] 
        for table_header in table.find_all("th", attrs={"scope": "col"}):
            colname = table_header["data-stat"] 
            columns.append(colname)

        data = [] 
        for row in table.find("tbody").select("tr:not(.sr_added_headers)"):
            row_data = []
            row_data.append(row.find("th", attrs={"data-stat": "ranker"}).text)

            for colval in row.find_all("td"):
                row_data.append(colval.text)

            data.append(row_data)
        
        table_df = pd.DataFrame(data=data, columns=columns)

        table_df["name_display"] = table_df["name_display"].apply(remove_accents)

        for col in [
            "age", "games", "games_started", "mp", "fg_per_poss",
            "fga_per_poss", "fg_pct", "fg3_per_poss", "fg3a_per_poss", "fg3_pct",
            "fg2_per_poss", "fg2a_per_poss", "fg2_pct", "efg_pct", "ft_per_poss",
            "fta_per_poss", "ft_pct", "orb_per_poss", "drb_per_poss", "trb_per_poss",
            "ast_per_poss", "stl_per_poss", "blk_per_poss", "tov_per_poss", "pf_per_poss",
            "pts_per_poss", "off_rtg", "def_rtg"
        ]:
            table_df[col] = table_df[col].replace('', np.nan).astype(float)

        table_df["league"] = metadata.league 
        table_df["season"] = metadata.season 

        table_df["net_rtg"] = table_df["off_rtg"] - table_df["def_rtg"] 
        
        renaming = {
            "name_display": "player_name",
            "team_name_abbr": "team_abbreviation"
        }
        table_df = table_df.rename(columns=renaming)


        col_order = [
            "league", "season", "player_name", "team_abbreviation", "pos",
            "age", "games", "games_started", "mp", "pts_per_poss", "ast_per_poss", "trb_per_poss",
            "drb_per_poss", "orb_per_poss", "stl_per_poss", "blk_per_poss", "tov_per_poss", "pf_per_poss",
            "fg_per_poss", "fga_per_poss", "fg_pct", "fg2_per_poss", "fg2a_per_poss", "fg2_pct", 
            "fg3_per_poss", "fg3a_per_poss", "fg3_pct", "ft_per_poss", "fta_per_poss", "ft_pct",
            "efg_pct", "off_rtg", "def_rtg", "net_rtg", "awards" 
        ] 
        table_frames.append(table_df[col_order])

    return table_frames 


def scrape_adjusted_shooting(metadata, soup):
    regular_season_table = soup.find("table", id="adj_shooting")
    post_season_table = soup.find("table", id="adj_shooting_post")

    table_frames = []
    for table in [regular_season_table, post_season_table]:
        columns = [] 
        for table_header in table.find_all("th", attrs={"scope": "col"}):
            colname = table_header["data-stat"] 
            columns.append(colname)

        data = [] 
        for row in table.find("tbody").select("tr:not(.sr_added_headers)"):
            row_data = []
            row_data.append(row.find("th", attrs={"data-stat": "ranker"}).text)

            for colval in row.find_all("td"):
                row_data.append(colval.text)

            data.append(row_data)
        
        table_df = pd.DataFrame(data=data, columns=columns)

        table_df["name_display"] = table_df["name_display"].apply(remove_accents)
    
        for col in [
            "age", "games", "games_started", "mp", "fg_pct",
            "fg2_pct", "fg3_pct", "efg_pct", "ft_pct", "ts_pct",
            "fta_per_fga_pct", "fg3a_per_fga_pct", "adj_fg_pct", "adj_fg2_pct", 
            "adj_fg3_pct", "adj_ft_pct", "adj_ts_pct", "adj_fta_per_fga_pct", 
            "adj_fg3a_per_fga_pct", "fg_pts_added", "ts_pts_added"
        ]:
            try:
                table_df[col] = table_df[col].replace('', np.nan).astype(float)
            except:
                continue 

        table_df["league"] = metadata.league 
        table_df["season"] = metadata.season 

        renaming = {
            "name_display": "player_name",
            "team_name_abbr": "team_abbreviation"
        }
        table_df = table_df.rename(columns=renaming)
        
        col_order = [
            "league", "season", "player_name", "team_abbreviation", "pos",
            "age", "games", "games_started", "mp", "fg_pct", "fg2_pct", "fg3_pct",
            "efg_pct", "ft_pct", "ts_pct", "fta_per_fga_pct", "fg3a_per_fga_pct",
            "adj_fg_pct", "adj_fg2_pct", "adj_fg3_pct", "adj_efg_pct", "adj_ft_pct",
            "adj_ts_pct", "adj_fta_per_fga_pct", "adj_fg3a_per_fga_pct"
        ] 

        if table == regular_season_table:
            col_order += ["fg_pts_added", "ts_pts_added", "awards"]
        else:
            col_order += ["awards"]
        
        table_frames.append(table_df[col_order])

    return table_frames 


def scrape_advanced(metadata, soup):
    regular_season_table = soup.find("table", id="advanced")
    post_season_table = soup.find("table", id="advanced_post")

    table_frames = []
    for table in [regular_season_table, post_season_table]:
        columns = [] 
        for table_header in table.find_all("th", attrs={"scope": "col"}):
            colname = table_header["data-stat"] 
            columns.append(colname)

        data = [] 
        for row in table.find("tbody").select("tr:not(.sr_added_headers)"):
            row_data = []
            row_data.append(row.find("th", attrs={"data-stat": "ranker"}).text)

            for colval in row.find_all("td"):
                row_data.append(colval.text)

            data.append(row_data)
        
        table_df = pd.DataFrame(data=data, columns=columns)

        table_df["name_display"] = table_df["name_display"].apply(remove_accents)
        
        for col in [
            "age", "games", "games_started", "mp", "per",
            "ts_pct", "fg3a_per_fga_pct", "fta_per_fga_pct",
            "orb_pct", "drb_pct", "trb_pct", "ast_pct", "stl_pct",
            "blk_pct", "tov_pct", "usg_pct", "ows", "dws", "ws", 
            "ws_per_48", "obpm", "dbpm", "bpm", "vorp"
        ]:
            table_df[col] = table_df[col].replace('', np.nan).astype(float)
        
        table_df["league"] = metadata.league 
        table_df["season"] = metadata.season 

        renaming = {
            "name_display": "player_name",
            "team_name_abbr": "team_abbreviation"
        }
        table_df = table_df.rename(columns=renaming)
        
        col_order = [
            "league", "season", "player_name", "team_abbreviation", "pos",
            "age", "games", "games_started", "mp", "per", "ts_pct", "fg3a_per_fga_pct",
            "fta_per_fga_pct", "orb_pct", "drb_pct", "trb_pct", "ast_pct", "stl_pct",
            "blk_pct", "tov_pct", "usg_pct", "ows", "dws", "ws", "ws_per_48", "obpm",
            "dbpm", "bpm", "vorp", "awards"
        ] 
        
        table_frames.append(table_df)

    return table_frames 


def save_scraping_results(scraping_results, output_path="scraping_results.json"):
    output = [] 

    for (league, season, page), dataframe in scraping_results.items():
        dataframe_json = json.loads(
            dataframe.to_json(
                orient="table",
                date_format="iso"
            )
        )

        output.append({
            "league": league,
            "season": season,
            "page": page,
            "data": dataframe_json
        })
    
    Path(output_path).write_text(
        json.dumps(output, indent=2),
        encoding="utf-8"
    )

def run_scraper():
    limiter = RateLimiter(
        limit=15,
        shelf_life=60,
        persist=True,
        persistence_dir="./rate_limiter_cache",
        persistence_file="state.json"
    )

    scraper_metadata = get_scraper_metadata(limiter)

    scraping_results = {} 
    for row in scraper_metadata.itertuples():
        if row.page == "league_home" or row.season == "2026-2027":
            continue 

        print(f"Scraping {row.season} of the {row.league}, page: {row.page}")

        limiter.add_request()
        req = requests.get(row.url) 
        soup = BeautifulSoup(req.content, "html.parser")

        match row.page:
            case "schedule_and_results":
                schedule_results_df = scrape_schedule_and_results(row, soup)
                scraping_results[(row.league, row.season, row.page)] = schedule_results_df
            
            case "per_game":
                regular_season_df, post_season_df = scrape_per_game(row, soup)
                scraping_results[(row.league, row.season, "regular_season_per_game")] = regular_season_df
                scraping_results[(row.league, row.season, "post_season_per_game")] = post_season_df
            
            case "totals": 
                regular_season_df, post_season_df = scrape_totals(row, soup)
                scraping_results[(row.league, row.season, "regular_season_totals")] = regular_season_df
                scraping_results[(row.league, row.season, "post_season_totals")] = post_season_df
    
            case "per_36_minutes":
                regular_season_df, post_season_df = scrape_per_36_minutes(row, soup)
                scraping_results[(row.league, row.season, "regular_season_per_36_minutes")] = regular_season_df
                scraping_results[(row.league, row.season, "post_season_per_36_minutes")] = post_season_df
    
            case "per_100_possessions":
                regular_season_df, post_season_df = scrape_per_100_possessions(row, soup)
                scraping_results[(row.league, row.season, "regular_season_per_100_possessions")] = regular_season_df
                scraping_results[(row.league, row.season, "post_season_per_100_possessions")] = post_season_df
    
            case "adjusted_shooting":
                regular_season_df, post_season_df = scrape_adjusted_shooting(row, soup) 
                scraping_results[(row.league, row.season, "regular_season_adjusted_shooting")] = regular_season_df
                scraping_results[(row.league, row.season, "post_season_adjusted_shooting")] = post_season_df
            
            case "advanced":
                regular_season_df, post_season_df = scrape_advanced(row, soup) 
                scraping_results[(row.league, row.season, "regular_season_advanced")] = regular_season_df
                scraping_results[(row.league, row.season, "post_season_advanced")] = post_season_df
    
    return scraping_results


if __name__ == "__main__":
    results = run_scraper()
    save_scraping_results(results)