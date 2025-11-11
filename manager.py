"""
Odds Ticker Plugin for LEDMatrix

Displays scrolling odds and betting lines for upcoming games across multiple sports leagues.
Shows point spreads, money lines, and over/under totals with team information.

This plugin perfectly mirrors the original odds_ticker_manager.py functionality
with all the fine-tuned drawing, layout, logic, filtering, data, fonts, colors, and logos.

Features:
- Multi-sport odds display (NFL, NBA, MLB, NCAA Football, NCAA Basketball, NHL, MiLB, NCAA Baseball, NCAA Basketball)
- Scrolling ticker format with exact original layout
- Favorite team prioritization
- Broadcast channel logos with exact mapping
- Configurable scroll speed and display duration
- Background data fetching
- Live game support with sport-specific formatting
- Dynamic duration calculation
- Team rankings for NCAA football
- Base indicators for baseball
- All original fonts, colors, and spacing

API Version: 1.0.0
"""

import time
import logging
import requests
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
import os
from PIL import Image, ImageDraw, ImageFont
import pytz
from pathlib import Path

# Import will be handled by the plugin system
try:
    from src.plugin_system.base_plugin import BasePlugin
except ImportError:
    # Fallback for when running outside of LEDMatrix
    class BasePlugin:
        def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
            self.plugin_id = plugin_id
            self.config = config
            self.display_manager = display_manager
            self.cache_manager = cache_manager
            self.plugin_manager = plugin_manager

# Import the API counter function from web interface
try:
    from web_interface_v2 import increment_api_counter
except ImportError:
    # Fallback if web interface is not available
    def increment_api_counter(kind: str, count: int = 1):
        pass

# Import BaseOddsManager from LEDMatrix core
try:
    from src.base_odds_manager import BaseOddsManager
except ImportError:
    # Fallback - create a minimal BaseOddsManager
    class BaseOddsManager:
        def __init__(self, cache_manager, plugin_manager):
            self.cache_manager = cache_manager
            self.plugin_manager = plugin_manager
            self.logger = logging.getLogger(__name__)
            self.base_url = "https://sports.core.api.espn.com/v2/sports"
            self.base_odds_config = {}
            self.update_interval = 3600
            self.request_timeout = 30
            self.cache_ttl = 1800
        
        def get_odds(self, sport, league, event_id, update_interval_seconds=None):
            return None

# Import background service and dynamic resolver
try:
    from src.background_data_service import get_background_service
    from src.dynamic_team_resolver import DynamicTeamResolver
    from src.logo_downloader import download_missing_logo
    from src.common.scroll_helper import ScrollHelper
except ImportError:
    # Fallback implementations
    def get_background_service(cache_manager, max_workers=1):
        return None
    
    class DynamicTeamResolver:
        def resolve_teams(self, teams, league):
            return teams
    
    def download_missing_logo(league, team_id, team_abbr, logo_path, logo_url):
        return False
    
    class ScrollHelper:
        pass  # Will be handled by proper import

# Get logger
logger = logging.getLogger(__name__)


class OddsTickerPlugin(BasePlugin, BaseOddsManager):
    """Manager for displaying scrolling odds ticker for multiple sports leagues."""
    
    BROADCAST_LOGO_MAP = {
        "ACC Network": "accn",
        "ACCN": "accn",
        "ABC": "abc",
        "BTN": "btn",
        "CBS": "cbs",
        "CBSSN": "cbssn",
        "CBS Sports Network": "cbssn",
        "ESPN": "espn",
        "ESPN2": "espn2",
        "ESPN3": "espn3",
        "ESPNU": "espnu",
        "ESPNEWS": "espn",
        "ESPN+": "espn",
        "ESPN Plus": "espn",
        "FOX": "fox",
        "FS1": "fs1",
        "FS2": "fs2",
        "MLBN": "mlbn",
        "MLB Network": "mlbn",
        "MLB.TV": "mlbn",
        "NBC": "nbc",
        "NFLN": "nfln",
        "NFL Network": "nfln",
        "PAC12": "pac12n",
        "Pac-12 Network": "pac12n",
        "SECN": "espn-sec-us",
        "TBS": "tbs",
        "TNT": "tnt",
        "truTV": "tru",
        "Peacock": "nbc",
        "Paramount+": "cbs",
        "Hulu": "espn",
        "Disney+": "espn",
        "Apple TV+": "nbc",
        # Regional sports networks
        "MASN": "cbs",
        "MASN2": "cbs",
        "MAS+": "cbs",
        "SportsNet": "nbc",
        "FanDuel SN": "fox",
        "FanDuel SN DET": "fox",
        "FanDuel SN FL": "fox",
        "SportsNet PIT": "nbc",
        "Padres.TV": "espn",
        "CLEGuardians.TV": "espn"
    }
    
    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the odds ticker plugin with exact original functionality."""
        # Initialize BasePlugin first
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        
        # Initialize BaseOddsManager with cache_manager and config_manager
        BaseOddsManager.__init__(self, cache_manager, plugin_manager)
        
        # Check required dependencies
        if get_background_service is None or DynamicTeamResolver is None:
            self.logger.error("Failed to import required services. Plugin will not function.")
            self.initialized = False
            return

        # Configuration - exactly like original
        # The config parameter already contains the odds-ticker configuration directly
        self.odds_ticker_config = config
        self.is_enabled = self.odds_ticker_config.get('enabled', False)
        
        # Debug logging
        self.logger.info(f"Full config received: {config}")
        self.logger.info(f"Odds ticker configuration: {self.odds_ticker_config}")
        self.logger.info(f"Odds ticker enabled: {self.is_enabled}")
        self.show_favorite_teams_only = self.odds_ticker_config.get('show_favorite_teams_only', False)
        self.games_per_favorite_team = self.odds_ticker_config.get('games_per_favorite_team', 1)
        self.max_games_per_league = self.odds_ticker_config.get('max_games_per_league', 5)
        self.show_odds_only = self.odds_ticker_config.get('show_odds_only', False)
        self.fetch_odds = self.odds_ticker_config.get('fetch_odds', True)
        self.sort_order = self.odds_ticker_config.get('sort_order', 'soonest')
        self.enabled_leagues = self.odds_ticker_config.get('enabled_leagues', ['nfl', 'nba', 'mlb'])
        self.update_interval = self.odds_ticker_config.get('update_interval', 3600)
        self.scroll_speed = self.odds_ticker_config.get('scroll_speed', 2)
        self.scroll_delay = self.odds_ticker_config.get('scroll_delay', 0.05)
        self.display_duration = self.odds_ticker_config.get('display_duration', 30)
        # Get target FPS from config (support both target_fps and scroll_target_fps for compatibility)
        self.target_fps = self.odds_ticker_config.get('target_fps') or self.odds_ticker_config.get('scroll_target_fps', 120)
        self.future_fetch_days = self.odds_ticker_config.get('future_fetch_days', 7)
        self.loop = self.odds_ticker_config.get('loop', True)
        self.show_channel_logos = self.odds_ticker_config.get('show_channel_logos', True)
        self.broadcast_logo_height_ratio = self.odds_ticker_config.get('broadcast_logo_height_ratio', 0.8)
        self.broadcast_logo_max_width_ratio = self.odds_ticker_config.get('broadcast_logo_max_width_ratio', 0.8)
        self.request_timeout = self.odds_ticker_config.get('request_timeout', 30)
        
        # Dynamic duration settings
        self.dynamic_duration_enabled = self.odds_ticker_config.get('dynamic_duration', True)
        self.min_duration = self.odds_ticker_config.get('min_duration', 30)
        self.max_duration = self.odds_ticker_config.get('max_duration', 300)
        self.duration_buffer = self.odds_ticker_config.get('duration_buffer', 0.1)
        self.dynamic_duration = 60  # Default duration in seconds
        self.total_scroll_width = 0  # Track total width for dynamic duration calculation
        
        # Initialize managers
        # BaseOddsManager is now inherited, no need for separate instance
        
        # Initialize background data service with optimized settings
        # Hardcoded for memory optimization: 1 worker, 30s timeout, 3 retries
        self.background_service = get_background_service(self.cache_manager, max_workers=1)
        self.background_fetch_requests = {}  # Track background fetch requests
        self.background_enabled = True
        logger.info("[Odds Ticker] Background service enabled with 1 worker (memory optimized)")
        
        # State variables
        self.last_update = 0
        self.games_data = []
        self.current_game_index = 0
        self.ticker_image = None # This will hold the single, wide image
        self.last_display_time = 0
        self._end_reached_logged = False  # Track if we've already logged reaching the end
        self._insufficient_time_warning_logged = False  # Track if we've already logged insufficient time warning
        self._team_rankings_cache = {}
        self._rankings_cache_timestamp = 0
        self._bases_data = None
        self._display_start_time = None
        
        # Font setup
        self.fonts = self._load_fonts()
        
        # Initialize dynamic team resolver
        self.dynamic_resolver = DynamicTeamResolver()
        
        # Initialize ScrollHelper for scrolling functionality
        display_width = self.display_manager.matrix.width if hasattr(self.display_manager, 'matrix') else 128
        display_height = self.display_manager.matrix.height if hasattr(self.display_manager, 'matrix') else 32
        self.scroll_helper = ScrollHelper(display_width, display_height, logger=self.logger)
        
        # Configure ScrollHelper with plugin settings
        # Convert scroll_speed from pixels per frame to pixels per second
        # scroll_speed is pixels per frame, scroll_delay is seconds per frame
        # So pixels per second = scroll_speed / scroll_delay
        pixels_per_second = self.scroll_speed / self.scroll_delay if self.scroll_delay > 0 else self.scroll_speed * 20
        self.scroll_helper.set_scroll_speed(pixels_per_second)
        self.scroll_helper.set_scroll_delay(self.scroll_delay)
        # Set target FPS for high-performance scrolling (backward compatible)
        if hasattr(self.scroll_helper, 'set_target_fps'):
            self.scroll_helper.set_target_fps(self.target_fps)
        else:
            # Fallback for older ScrollHelper versions - set target_fps directly
            self.scroll_helper.target_fps = max(30.0, min(200.0, self.target_fps))
            self.scroll_helper.frame_time_target = 1.0 / self.scroll_helper.target_fps
            self.logger.debug(f"Target FPS set to: {self.scroll_helper.target_fps} FPS (using fallback method)")
        self.scroll_helper.set_dynamic_duration_settings(
            enabled=self.dynamic_duration_enabled,
            min_duration=self.min_duration,
            max_duration=self.max_duration,
            buffer=self.duration_buffer
        )
        
        # League configurations - exactly like original
        self.league_configs = {
            'nfl': {
                'sport': 'football',
                'league': 'nfl',
                'logo_league': 'nfl',  # ESPN API league identifier for logo downloading
                'logo_dir': 'assets/sports/nfl_logos',
                'favorite_teams': config.get('nfl_scoreboard', {}).get('favorite_teams', []),
                'enabled': config.get('nfl_scoreboard', {}).get('enabled', False)
            },
            'nba': {
                'sport': 'basketball',
                'league': 'nba',
                'logo_league': 'nba',  # ESPN API league identifier for logo downloading
                'logo_dir': 'assets/sports/nba_logos',
                'favorite_teams': config.get('nba_scoreboard', {}).get('favorite_teams', []),
                'enabled': config.get('nba_scoreboard', {}).get('enabled', False)
            },
            'mlb': {
                'sport': 'baseball',
                'league': 'mlb',
                'logo_league': 'mlb',  # ESPN API league identifier for logo downloading
                'logo_dir': 'assets/sports/mlb_logos',
                'favorite_teams': config.get('mlb_scoreboard', {}).get('favorite_teams', []),
                'enabled': config.get('mlb_scoreboard', {}).get('enabled', False)
            },
            'ncaa_fb': {
                'sport': 'football',
                'league': 'college-football',
                'logo_league': 'ncaa_fb',  # ESPN API league identifier for logo downloading
                'logo_dir': 'assets/sports/ncaa_logos',
                'favorite_teams': config.get('ncaa_fb_scoreboard', {}).get('favorite_teams', []),
                'enabled': config.get('ncaa_fb_scoreboard', {}).get('enabled', False)
            },
            'milb': {
                'sport': 'baseball',
                'league': 'milb',
                'logo_league': 'milb',  # ESPN API league identifier for logo downloading (if supported)
                'logo_dir': 'assets/sports/milb_logos',
                'favorite_teams': config.get('milb_scoreboard', {}).get('favorite_teams', []),
                'enabled': config.get('milb_scoreboard', {}).get('enabled', False)
            },
            'nhl': {
                'sport': 'hockey',
                'league': 'nhl',
                'logo_league': 'nhl',  # ESPN API league identifier for logo downloading
                'logo_dir': 'assets/sports/nhl_logos',
                'favorite_teams': config.get('nhl_scoreboard', {}).get('favorite_teams', []),
                'enabled': config.get('nhl_scoreboard', {}).get('enabled', False)
            },
            'ncaam_basketball': {
                'sport': 'basketball',
                'league': 'mens-college-basketball',
                'logo_league': 'ncaam_basketball',  # ESPN API league identifier for logo downloading
                'logo_dir': 'assets/sports/ncaa_logos',
                'favorite_teams': config.get('ncaam_basketball_scoreboard', {}).get('favorite_teams', []),
                'enabled': config.get('ncaam_basketball_scoreboard', {}).get('enabled', False)
            },
            'ncaa_baseball': {
                'sport': 'baseball',
                'league': 'college-baseball',
                'logo_league': 'ncaa_baseball',  # ESPN API league identifier for logo downloading
                'logo_dir': 'assets/sports/ncaa_logos',
                'favorite_teams': config.get('ncaa_baseball_scoreboard', {}).get('favorite_teams', []),
                'enabled': config.get('ncaa_baseball_scoreboard', {}).get('enabled', False)
            },
            'soccer': {
                'sport': 'soccer',
                'leagues': config.get('soccer_scoreboard', {}).get('leagues', []),
                'logo_league': None,  # Soccer logos not supported by ESPN API
                'logo_dir': 'assets/sports/soccer_logos',
                'favorite_teams': config.get('soccer_scoreboard', {}).get('favorite_teams', []),
                'enabled': config.get('soccer_scoreboard', {}).get('enabled', False)
            }
        }
        
        # Resolve dynamic teams for each league
        for league_key, league_config in self.league_configs.items():
            if league_config.get('enabled', False):
                raw_favorite_teams = league_config.get('favorite_teams', [])
                if raw_favorite_teams:
                    # Resolve dynamic teams for this league
                    resolved_teams = self.dynamic_resolver.resolve_teams(raw_favorite_teams, league_key)
                    league_config['favorite_teams'] = resolved_teams
                    
                    # Log dynamic team resolution
                    if raw_favorite_teams != resolved_teams:
                        logger.info(f"Resolved dynamic teams for {league_key}: {raw_favorite_teams} -> {resolved_teams}")
                    else:
                        logger.info(f"Favorite teams for {league_key}: {resolved_teams}")
        
        logger.info(f"OddsTickerManager initialized with enabled leagues: {self.enabled_leagues}")
        logger.info(f"Show favorite teams only: {self.show_favorite_teams_only}")
        self.initialized = True

    def _load_fonts(self) -> Dict[str, ImageFont.FreeTypeFont]:
        """Load fonts for the ticker display."""
        try:
            return {
                'small': ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 6),
                'medium': ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8),
                'large': ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 10)
            }
        except Exception as e:
            logger.error(f"Error loading fonts: {e}")
            return {
                'small': ImageFont.load_default(),
                'medium': ImageFont.load_default(),
                'large': ImageFont.load_default()
            }

    def _fetch_team_record(self, team_abbr: str, league: str) -> str:
        """Fetch team record from ESPN API."""
        # This is a simplified implementation; a more robust solution would cache team data
        try:
            sport = 'baseball' if league == 'mlb' else 'football' if league in ['nfl', 'college-football'] else 'basketball'
            
            # Use a more specific endpoint for college sports
            if league == 'college-football':
                url = f"https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/{team_abbr}"
            else:
                url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{team_abbr}"

            response = requests.get(url, timeout=self.request_timeout)
            response.raise_for_status()
            data = response.json()
            
            # Increment API counter for sports data
            increment_api_counter('sports', 1)
            
            # Different path for college sports records
            if league == 'college-football':
                record_items = data.get('team', {}).get('record', {}).get('items', [])
                if record_items:
                    return record_items[0].get('summary', 'N/A')
                else:
                    return 'N/A'
            else:
                record = data.get('team', {}).get('record', {}).get('summary', 'N/A')
                return record

        except Exception as e:
            logger.error(f"Error fetching record for {team_abbr} in league {league}: {e}")
            return "N/A"

    def _fetch_team_rankings(self) -> Dict[str, int]:
        """Fetch current team rankings from ESPN API for NCAA football."""
        current_time = time.time()
        
        # Check if we have cached rankings that are still valid
        if (hasattr(self, '_team_rankings_cache') and 
            hasattr(self, '_rankings_cache_timestamp') and
            self._team_rankings_cache and 
            current_time - self._rankings_cache_timestamp < 3600):  # Cache for 1 hour
            return self._team_rankings_cache
        
        try:
            rankings_url = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/rankings"
            response = requests.get(rankings_url, timeout=self.request_timeout)
            response.raise_for_status()
            data = response.json()
            
            # Increment API counter for sports data
            increment_api_counter('sports', 1)
            
            rankings = {}
            rankings_data = data.get('rankings', [])
            
            if rankings_data:
                # Use the first ranking (usually AP Top 25)
                first_ranking = rankings_data[0]
                teams = first_ranking.get('ranks', [])
                
                for team_data in teams:
                    team_info = team_data.get('team', {})
                    team_abbr = team_info.get('abbreviation', '')
                    current_rank = team_data.get('current', 0)
                    
                    if team_abbr and current_rank > 0:
                        rankings[team_abbr] = current_rank
            
            # Cache the results
            self._team_rankings_cache = rankings
            self._rankings_cache_timestamp = current_time
            
            logger.debug(f"Fetched rankings for {len(rankings)} teams")
            return rankings
            
        except Exception as e:
            logger.error(f"Error fetching team rankings: {e}")
            return {}

    def convert_image(self, logo_path: Path) -> Optional[Image.Image]:
        if logo_path.exists():
            logo = Image.open(logo_path)
            # Convert palette images with transparency to RGBA to avoid PIL warnings
            if logo.mode == 'P' and 'transparency' in logo.info:
                logo = logo.convert('RGBA')
            logger.debug(f"Successfully loaded logo {logo_path}")
            return logo
        return None

    def _get_team_logo(self, league: str, team_id: str, team_abbr: str, logo_dir: str) -> Optional[Image.Image]:
        """Get team logo from the configured directory, downloading if missing."""
        if not team_abbr or not logo_dir:
            logger.debug("Cannot get team logo with missing team_abbr or logo_dir")
            return None
        try:
            logo_path = Path(logo_dir, f"{team_abbr}.png")
            logger.debug(f"Attempting to load logo from path: {logo_path}")
            if (image := self.convert_image(logo_path)):
                return image
            else:
                logger.warning(f"Logo not found at path: {logo_path}")
                
                # Try to download the missing logo if we have league information
                if league and download_missing_logo:
                    logger.info(f"Attempting to download missing logo for {team_abbr} in league {league}")
                    success = download_missing_logo(league, team_id, team_abbr, logo_path, None)
                    if success:
                        # Try to load the downloaded logo
                        if os.path.exists(logo_path):
                            logo = Image.open(logo_path)
                            # Convert palette images with transparency to RGBA to avoid PIL warnings
                            if logo.mode == 'P' and 'transparency' in logo.info:
                                logo = logo.convert('RGBA')
                            logger.info(f"Successfully downloaded and loaded logo for {team_abbr}")
                            return logo
                
                return None
        except Exception as e:
            logger.error(f"Error loading logo for {team_abbr} from {logo_dir}: {e}")
            return None

    def _fetch_upcoming_games(self) -> List[Dict[str, Any]]:
        """Fetch upcoming games with odds for all enabled leagues with user-defined granularity."""
        games_data = []
        now = datetime.now(timezone.utc)
        
        logger.debug(f"Fetching upcoming games for {len(self.enabled_leagues)} enabled leagues")
        logger.debug(f"Enabled leagues: {self.enabled_leagues}")
        logger.debug(f"Show favorite teams only: {self.show_favorite_teams_only}")
        logger.debug(f"Show odds only: {self.show_odds_only}")
        
        for league_key in self.enabled_leagues:
            if league_key not in self.league_configs:
                logger.warning(f"Unknown league: {league_key}")
                continue
                
            league_config = self.league_configs[league_key]
            logger.debug(f"Processing league {league_key}: enabled={league_config['enabled']}")
            
            try:
                # Fetch all upcoming games for this league
                all_games = self._fetch_league_games(league_config, now)
                logger.debug(f"Found {len(all_games)} games for {league_key}")
                league_games = []
                
                if self.show_favorite_teams_only:
                    # For each favorite team, find their next N games
                    favorite_teams = league_config.get('favorite_teams', [])
                    logger.debug(f"Favorite teams for {league_key}: {favorite_teams}")
                    seen_game_ids = set()
                    for team in favorite_teams:
                        # Find games where this team is home or away
                        team_games = [g for g in all_games if (g['home_team'] == team or g['away_team'] == team)]
                        logger.debug(f"Found {len(team_games)} games for team {team}")
                        # Sort by start_time
                        team_games.sort(key=lambda x: x.get('start_time', datetime.max))
                        # Only keep games with odds if show_odds_only is set
                        if self.show_odds_only:
                            team_games = [g for g in team_games if g.get('odds')]
                            logger.debug(f"After odds filter: {len(team_games)} games for team {team}")
                        # Take the next N games for this team
                        for g in team_games[:self.games_per_favorite_team]:
                            if g['id'] not in seen_game_ids:
                                league_games.append(g)
                                seen_game_ids.add(g['id'])
                    # Cap at max_games_per_league
                    league_games = league_games[:self.max_games_per_league]
                else:
                    # Show all games, optionally only those with odds
                    league_games = all_games
                    if self.show_odds_only:
                        league_games = [g for g in league_games if g.get('odds')]
                    # Sort by start_time
                    league_games.sort(key=lambda x: x.get('start_time', datetime.max))
                    league_games = league_games[:self.max_games_per_league]
                
                # Sorting (default is soonest)
                if self.sort_order == 'soonest':
                    league_games.sort(key=lambda x: x.get('start_time', datetime.max))
                # (Other sort options can be added here)
                
                games_data.extend(league_games)
                logger.debug(f"Added {len(league_games)} games from {league_key}")
                
            except Exception as e:
                logger.error(f"Error fetching games for {league_key}: {e}")
        
        logger.debug(f"Total games found: {len(games_data)}")
        if games_data:
            logger.debug(f"Sample game data keys: {list(games_data[0].keys())}")
        return games_data

    def _fetch_league_games(self, league_config: Dict[str, Any], now: datetime) -> List[Dict[str, Any]]:
        """Fetch upcoming games for a specific league using day-by-day approach."""
        games = []
        yesterday = now - timedelta(days=1)
        future_window = now + timedelta(days=self.future_fetch_days)
        num_days = (future_window - yesterday).days + 1
        dates = [(yesterday + timedelta(days=i)).strftime("%Y%m%d") for i in range(num_days)]

        # Optimization: If showing favorite teams only, track games found per team
        favorite_teams = league_config.get('favorite_teams', []) if self.show_favorite_teams_only else []
        team_games_found = {team: 0 for team in favorite_teams}
        max_games = self.games_per_favorite_team if self.show_favorite_teams_only else None
        all_games = []
        
        # Optimization: Track total games found when not showing favorite teams only
        games_found = 0
        max_games_per_league = self.max_games_per_league if not self.show_favorite_teams_only else None

        sport = league_config['sport']
        leagues_to_fetch = []
        if sport == 'soccer':
            leagues_to_fetch.extend(league_config.get('leagues', []))
        else:
            if league_config.get('league'):
                leagues_to_fetch.append(league_config.get('league'))

        for league in leagues_to_fetch:
            # As requested, do not even attempt to make API calls for MiLB.
            if league == 'milb':
                logger.warning("Skipping all MiLB game requests as the API endpoint is not supported.")
                continue
                
            for date in dates:
                # Stop if we have enough games for favorite teams
                if self.show_favorite_teams_only and favorite_teams and all(team_games_found.get(t, 0) >= max_games for t in favorite_teams):
                    break  # All favorite teams have enough games, stop searching
                # Stop if we have enough games for the league (when not showing favorite teams only)
                if not self.show_favorite_teams_only and max_games_per_league and games_found >= max_games_per_league:
                    break  # We have enough games for this league, stop searching
                try:
                    cache_key = f"scoreboard_data_{sport}_{league}_{date}"

                    # Dynamically set TTL for scoreboard data
                    current_date_obj = now.date()
                    request_date_obj = datetime.strptime(date, "%Y%m%d").date()

                    if request_date_obj < current_date_obj:
                        ttl = 86400 * 30  # 30 days for past dates
                    elif request_date_obj == current_date_obj:
                        ttl = 300  # 5 minutes for today (shorter to catch live games)
                    else:
                        ttl = 43200  # 12 hours for future dates
                    
                    data = self.cache_manager.get(cache_key, max_age=ttl)

                    if data is None:
                        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard?dates={date}"
                        logger.debug(f"Fetching {league} games from ESPN API for date: {date}")
                        response = requests.get(url, timeout=self.request_timeout)
                        response.raise_for_status()
                        data = response.json()
                        
                        # Increment API counter for sports data
                        increment_api_counter('sports', 1)
                        
                        self.cache_manager.set(cache_key, data)
                        logger.debug(f"Cached scoreboard for {league} on {date} with a TTL of {ttl} seconds.")
                    else:
                        logger.debug(f"Using cached scoreboard data for {league} on {date}.")

                    for event in data.get('events', []):
                        # Stop if we have enough games for the league (when not showing favorite teams only)
                        if not self.show_favorite_teams_only and max_games_per_league and games_found >= max_games_per_league:
                            break
                        game_id = event['id']
                        status = event['status']['type']['name'].lower()
                        status_state = event['status']['type']['state'].lower()
                        
                        # Include both scheduled and live games
                        if status in ['scheduled', 'pre-game', 'status_scheduled'] or status_state == 'in':
                            game_time = datetime.fromisoformat(event['date'].replace('Z', '+00:00'))
                            
                            # For live games, include them regardless of time window
                            # For scheduled games, check if they're within the future window
                            if status_state == 'in' or (now <= game_time <= future_window):
                                competitors = event['competitions'][0]['competitors']
                                home_team = next(c for c in competitors if c['homeAway'] == 'home')
                                away_team = next(c for c in competitors if c['homeAway'] == 'away')
                                home_id = home_team['team']['id']
                                away_id = away_team['team']['id']
                                home_abbr = home_team['team']['abbreviation']
                                away_abbr = away_team['team']['abbreviation']
                                home_name = home_team['team'].get('name', home_abbr)
                                away_name = away_team['team'].get('name', away_abbr)

                                broadcast_info = []
                                broadcasts = event.get('competitions', [{}])[0].get('broadcasts', [])
                                if broadcasts:
                                    # Handle new ESPN API format where broadcast names are in 'names' array
                                    for broadcast in broadcasts:
                                        if 'names' in broadcast:
                                            # New format: broadcast names are in 'names' array
                                            broadcast_names = broadcast.get('names', [])
                                            broadcast_info.extend(broadcast_names)
                                        elif 'media' in broadcast and 'shortName' in broadcast['media']:
                                            # Old format: broadcast name is in media.shortName
                                            short_name = broadcast['media']['shortName']
                                            if short_name:
                                                broadcast_info.append(short_name)
                                    
                                    # Remove duplicates and filter out empty strings
                                    broadcast_info = list(set([name for name in broadcast_info if name]))
                                    
                                    logger.info(f"Found broadcast channels for game {game_id}: {broadcast_info}")
                                    logger.debug(f"Raw broadcasts data for game {game_id}: {broadcasts}")
                                    # Log the first broadcast structure for debugging
                                    if broadcasts:
                                        logger.debug(f"First broadcast structure: {broadcasts[0]}")
                                        if 'media' in broadcasts[0]:
                                            logger.debug(f"Media structure: {broadcasts[0]['media']}")
                                else:
                                    logger.debug(f"No broadcasts data found for game {game_id}")
                                    # Log the competitions structure to see what's available
                                    competitions = event.get('competitions', [])
                                    if competitions:
                                        logger.debug(f"Competitions structure for game {game_id}: {competitions[0].keys()}")

                                # Only process favorite teams if enabled
                                if self.show_favorite_teams_only:
                                    if not favorite_teams:
                                        continue
                                    if home_abbr not in favorite_teams and away_abbr not in favorite_teams:
                                        continue
                                # Build game dict (existing logic)
                                home_record = home_team.get('records', [{}])[0].get('summary', '') if home_team.get('records') else ''
                                away_record = away_team.get('records', [{}])[0].get('summary', '') if away_team.get('records') else ''
                                
                                # Dynamically set update interval based on game start time
                                time_until_game = game_time - now
                                if status_state == 'in':
                                    # Live games need more frequent updates
                                    update_interval_seconds = 300  # 5 minutes for live games
                                elif time_until_game > timedelta(hours=48):
                                    update_interval_seconds = 86400  # 24 hours
                                else:
                                    update_interval_seconds = 3600   # 1 hour
                                
                                logger.debug(f"Game {game_id} starts in {time_until_game}. Setting odds update interval to {update_interval_seconds}s.")
                                
                                # Fetch odds with timeout protection to prevent freezing (if enabled)
                                if self.fetch_odds:
                                    try:
                                        import threading
                                        import queue
                                        
                                        result_queue = queue.Queue()
                                        
                                        def fetch_odds():
                                            try:
                                                odds_result = self.get_odds(
                                                    sport=sport,
                                                    league=league,
                                                    event_id=game_id,
                                                    update_interval_seconds=update_interval_seconds
                                                )
                                                result_queue.put(('success', odds_result))
                                            except Exception as e:
                                                result_queue.put(('error', e))
                                        
                                        # Start odds fetch in a separate thread
                                        odds_thread = threading.Thread(target=fetch_odds)
                                        odds_thread.daemon = True
                                        odds_thread.start()
                                        
                                        # Wait for result with 3-second timeout
                                        try:
                                            result_type, result_data = result_queue.get(timeout=3)
                                            if result_type == 'success':
                                                odds_data = result_data
                                            else:
                                                logger.warning(f"Odds fetch failed for game {game_id}: {result_data}")
                                                odds_data = None
                                        except queue.Empty:
                                            logger.warning(f"Odds fetch timed out for game {game_id}")
                                            odds_data = None
                                        
                                    except Exception as e:
                                        logger.warning(f"Odds fetch failed for game {game_id}: {e}")
                                        odds_data = None
                                else:
                                    # Odds fetching is disabled
                                    odds_data = None
                                
                                has_odds = False
                                if odds_data and not odds_data.get('no_odds'):
                                    if odds_data.get('spread') is not None:
                                        has_odds = True
                                    if odds_data.get('home_team_odds', {}).get('spread_odds') is not None:
                                        has_odds = True
                                    if odds_data.get('away_team_odds', {}).get('spread_odds') is not None:
                                        has_odds = True
                                    if odds_data.get('over_under') is not None:
                                        has_odds = True
                                
                                # Extract live game information if the game is in progress
                                live_info = None
                                if status_state == 'in':
                                    live_info = self._extract_live_game_info(event, sport)
                                
                                game = {
                                    'id': game_id,
                                    'home_id': home_id,
                                    'away_id': away_id,
                                    'home_team': home_abbr,
                                    'away_team': away_abbr,
                                    'home_team_name': home_name,
                                    'away_team_name': away_name,
                                    'start_time': game_time,
                                    'home_record': home_record,
                                    'away_record': away_record,
                                    'odds': odds_data if has_odds else None,
                                    'broadcast_info': broadcast_info,
                                    'logo_dir': league_config.get('logo_dir', f'assets/sports/{league.lower()}_logos'),
                                    'league': league_config.get('logo_league', league),  # Use logo_league for downloading
                                    'status': status,
                                    'status_state': status_state,
                                    'live_info': live_info
                                }
                                all_games.append(game)
                                games_found += 1
                                # If favorite teams only, increment counters
                                if self.show_favorite_teams_only:
                                    for team in [home_abbr, away_abbr]:
                                        if team in team_games_found and team_games_found[team] < max_games:
                                            team_games_found[team] += 1
                    # Stop if we have enough games for the league (when not showing favorite teams only)
                    if not self.show_favorite_teams_only and max_games_per_league and games_found >= max_games_per_league:
                        break
                except requests.exceptions.HTTPError as http_err:
                    logger.error(f"HTTP error occurred while fetching games for {league} on {date}: {http_err}")
                except Exception as e:
                    logger.error(f"Error fetching games for {league_config.get('league', 'unknown')} on {date}: {e}", exc_info=True)
            if not self.show_favorite_teams_only and max_games_per_league and games_found >= max_games_per_league:
                break
        return all_games

    def _extract_live_game_info(self, event: Dict[str, Any], sport: str) -> Dict[str, Any]:
        """Extract live game information from ESPN API event data."""
        try:
            status = event['status']
            competitions = event['competitions'][0]
            competitors = competitions['competitors']
            
            # Get scores
            home_score = next(c['score'] for c in competitors if c['homeAway'] == 'home')
            away_score = next(c['score'] for c in competitors if c['homeAway'] == 'away')
            
            live_info = {
                'home_score': home_score,
                'away_score': away_score,
                'period': status.get('period', 1),
                'clock': status.get('displayClock', ''),
                'detail': status['type'].get('detail', ''),
                'short_detail': status['type'].get('shortDetail', '')
            }
            
            # Sport-specific information
            if sport == 'baseball':
                # Extract inning information
                situation = competitions.get('situation', {})
                count = situation.get('count', {})
                
                live_info.update({
                    'inning': status.get('period', 1),
                    'inning_half': 'top',  # Default
                    'balls': count.get('balls', 0),
                    'strikes': count.get('strikes', 0),
                    'outs': situation.get('outs', 0),
                    'bases_occupied': [
                        situation.get('onFirst', False),
                        situation.get('onSecond', False),
                        situation.get('onThird', False)
                    ]
                })
                
                # Determine inning half from status detail
                status_detail = status['type'].get('detail', '').lower()
                status_short = status['type'].get('shortDetail', '').lower()
                
                if 'bottom' in status_detail or 'bot' in status_detail or 'bottom' in status_short or 'bot' in status_short:
                    live_info['inning_half'] = 'bottom'
                elif 'top' in status_detail or 'mid' in status_detail or 'top' in status_short or 'mid' in status_short:
                    live_info['inning_half'] = 'top'
                    
            elif sport == 'football':
                # Extract football-specific information
                situation = competitions.get('situation', {})
                
                live_info.update({
                    'quarter': status.get('period', 1),
                    'down': situation.get('down', 0),
                    'distance': situation.get('distance', 0),
                    'yard_line': situation.get('yardLine', 0),
                    'possession': situation.get('possession', '')
                })
                
            elif sport == 'basketball':
                # Extract basketball-specific information
                situation = competitions.get('situation', {})
                
                live_info.update({
                    'quarter': status.get('period', 1),
                    'time_remaining': status.get('displayClock', ''),
                    'possession': situation.get('possession', '')
                })
                
            elif sport == 'hockey':
                # Extract hockey-specific information
                situation = competitions.get('situation', {})
                
                live_info.update({
                    'period': status.get('period', 1),
                    'time_remaining': status.get('displayClock', ''),
                    'power_play': situation.get('powerPlay', False)
                })
                
            elif sport == 'soccer':
                # Extract soccer-specific information
                live_info.update({
                    'period': status.get('period', 1),
                    'time_remaining': status.get('displayClock', ''),
                    'extra_time': status.get('displayClock', '').endswith('+')
                })
            
            return live_info
            
        except Exception as e:
            logger.error(f"Error extracting live game info: {e}")
            return None

    def _format_odds_text(self, game: Dict[str, Any]) -> str:
        """Format the odds text for display."""
        # Check if this is a live game
        is_live = game.get('status_state') == 'in'
        live_info = game.get('live_info')
        
        if is_live and live_info:
            # Format live game information
            home_score = live_info.get('home_score', 0)
            away_score = live_info.get('away_score', 0)
            
            # Determine sport for sport-specific formatting
            sport = None
            for league_key, config in self.league_configs.items():
                if config.get('logo_dir') == game.get('logo_dir'):
                    sport = config.get('sport')
                    break
            
            # Get team names with rankings for NCAA football
            away_team_name = game.get('away_team_name', game['away_team'])
            home_team_name = game.get('home_team_name', game['home_team'])
            away_team_abbr = game.get('away_team', '')
            home_team_abbr = game.get('home_team', '')
            
            # Check if this is NCAA football and add rankings
            league_key = None
            for key, config in self.league_configs.items():
                if config.get('logo_dir') == game.get('logo_dir'):
                    league_key = key
                    break
            
            if league_key == 'ncaa_fb':
                rankings = self._fetch_team_rankings()
                
                # Add ranking to away team name if ranked
                if away_team_abbr in rankings and rankings[away_team_abbr] > 0:
                    away_team_name = f"{rankings[away_team_abbr]}. {away_team_name}"
                
                # Add ranking to home team name if ranked
                if home_team_abbr in rankings and rankings[home_team_abbr] > 0:
                    home_team_name = f"{rankings[home_team_abbr]}. {home_team_name}"
            
            if sport == 'baseball':
                inning_half_indicator = "▲" if live_info.get('inning_half') == 'top' else "▼"
                inning_text = f"{inning_half_indicator}{live_info.get('inning', 1)}"
                count_text = f"{live_info.get('balls', 0)}-{live_info.get('strikes', 0)}"
                outs_count = live_info.get('outs', 0)
                outs_text = f"{outs_count} out" if outs_count == 1 else f"{outs_count} outs"
                return f"[LIVE] {away_team_name} {away_score} vs {home_team_name} {home_score} - {inning_text} {count_text} {outs_text}"
                
            elif sport == 'football':
                quarter_text = f"Q{live_info.get('quarter', 1)}"
                # Validate down and distance for odds ticker display
                down = live_info.get('down')
                distance = live_info.get('distance')
                if (down is not None and isinstance(down, int) and 1 <= down <= 4 and 
                    distance is not None and isinstance(distance, int) and distance >= 0):
                    down_text = f"{down}&{distance}"
                else:
                    down_text = ""  # Don't show invalid down/distance
                clock_text = live_info.get('clock', '')
                return f"[LIVE] {away_team_name} {away_score} vs {home_team_name} {home_score} - {quarter_text} {down_text} {clock_text}".strip()
                
            elif sport == 'basketball':
                quarter_text = f"Q{live_info.get('quarter', 1)}"
                clock_text = live_info.get('time_remaining', '')
                return f"[LIVE] {away_team_name} {away_score} vs {home_team_name} {home_score} - {quarter_text} {clock_text}"
                
            elif sport == 'hockey':
                period_text = f"P{live_info.get('period', 1)}"
                clock_text = live_info.get('time_remaining', '')
                return f"[LIVE] {away_team_name} {away_score} vs {home_team_name} {home_score} - {period_text} {clock_text}"
                
            else:
                return f"[LIVE] {away_team_name} {away_score} vs {home_team_name} {home_score}"
        
        # Original odds formatting for non-live games
        odds = game.get('odds', {})
        if not odds:
            # Show just the game info without odds
            game_time = game['start_time']
            timezone_str = self.config.get('timezone', 'UTC')
            try:
                tz = pytz.timezone(timezone_str)
            except pytz.exceptions.UnknownTimeZoneError:
                tz = pytz.UTC
            
            if game_time.tzinfo is None:
                game_time = game_time.replace(tzinfo=pytz.UTC)
            local_time = game_time.astimezone(tz)
            time_str = local_time.strftime("%I:%M%p").lstrip('0')
            
            # Get team names with rankings for NCAA football
            away_team_name = game.get('away_team_name', game['away_team'])
            home_team_name = game.get('home_team_name', game['home_team'])
            away_team_abbr = game.get('away_team', '')
            home_team_abbr = game.get('home_team', '')
            
            # Check if this is NCAA football and add rankings
            league_key = None
            for key, config in self.league_configs.items():
                if config.get('logo_dir') == game.get('logo_dir'):
                    league_key = key
                    break
            
            if league_key == 'ncaa_fb':
                rankings = self._fetch_team_rankings()
                
                # Add ranking to away team name if ranked
                if away_team_abbr in rankings and rankings[away_team_abbr] > 0:
                    away_team_name = f"{rankings[away_team_abbr]}. {away_team_name}"
                
                # Add ranking to home team name if ranked
                if home_team_abbr in rankings and rankings[home_team_abbr] > 0:
                    home_team_name = f"{rankings[home_team_abbr]}. {home_team_name}"
            
            return f"[{time_str}] {away_team_name} vs {home_team_name} (No odds)"
        
        # Extract odds data
        home_team_odds = odds.get('home_team_odds', {})
        away_team_odds = odds.get('away_team_odds', {})
        
        home_spread = home_team_odds.get('spread_odds')
        away_spread = away_team_odds.get('spread_odds')
        home_ml = home_team_odds.get('money_line')
        away_ml = away_team_odds.get('money_line')
        over_under = odds.get('over_under')
        
        # Format time
        game_time = game['start_time']
        timezone_str = self.config.get('timezone', 'UTC')
        try:
            tz = pytz.timezone(timezone_str)
        except pytz.exceptions.UnknownTimeZoneError:
            tz = pytz.UTC
        
        if game_time.tzinfo is None:
            game_time = game_time.replace(tzinfo=pytz.UTC)
        local_time = game_time.astimezone(tz)
        time_str = local_time.strftime("%I:%M %p").lstrip('0')
        
        # Build odds string
        odds_parts = [f"[{time_str}]"]
        
        # Get team names with rankings for NCAA football
        away_team_name = game.get('away_team_name', game['away_team'])
        home_team_name = game.get('home_team_name', game['home_team'])
        away_team_abbr = game.get('away_team', '')
        home_team_abbr = game.get('home_team', '')
        
        # Check if this is NCAA football and add rankings
        league_key = None
        for key, config in self.league_configs.items():
            if config.get('logo_dir') == game.get('logo_dir'):
                league_key = key
                break
        
        if league_key == 'ncaa_fb':
            rankings = self._fetch_team_rankings()
            
            # Add ranking to away team name if ranked
            if away_team_abbr in rankings and rankings[away_team_abbr] > 0:
                away_team_name = f"{rankings[away_team_abbr]}. {away_team_name}"
            
            # Add ranking to home team name if ranked
            if home_team_abbr in rankings and rankings[home_team_abbr] > 0:
                home_team_name = f"{rankings[home_team_abbr]}. {home_team_name}"
        
        # Add away team and odds
        odds_parts.append(away_team_name)
        if away_spread is not None:
            spread_str = f"{away_spread:+.1f}" if away_spread > 0 else f"{away_spread:.1f}"
            odds_parts.append(spread_str)
        if away_ml is not None:
            ml_str = f"ML {away_ml:+d}" if away_ml > 0 else f"ML {away_ml}"
            odds_parts.append(ml_str)
        
        odds_parts.append("vs")
        
        # Add home team and odds
        odds_parts.append(home_team_name)
        if home_spread is not None:
            spread_str = f"{home_spread:+.1f}" if home_spread > 0 else f"{home_spread:.1f}"
            odds_parts.append(spread_str)
        if home_ml is not None:
            ml_str = f"ML {home_ml:+d}" if home_ml > 0 else f"ML {home_ml}"
            odds_parts.append(ml_str)
        
        # Add over/under
        if over_under is not None:
            odds_parts.append(f"O/U {over_under}")
        
        return " ".join(odds_parts)

    def _draw_base_indicators(self, draw: ImageDraw.Draw, bases_occupied: List[bool], center_x: int, y: int) -> None:
        """Draw base indicators on the display similar to MLB manager."""
        base_diamond_size = 8  # Match MLB manager size
        base_horiz_spacing = 8  # Reduced from 10 to 8 for tighter spacing
        base_vert_spacing = 6  # Reduced from 8 to 6 for tighter vertical spacing
        base_cluster_width = base_diamond_size + base_horiz_spacing + base_diamond_size
        base_cluster_height = base_diamond_size + base_vert_spacing + base_diamond_size
        
        # Calculate cluster dimensions and positioning
        bases_origin_x = center_x - (base_cluster_width // 2)
        overall_start_y = y - (base_cluster_height // 2)
        
        # Draw diamond-shaped bases like MLB manager
        base_color_occupied = (255, 255, 255)
        base_color_empty = (255, 255, 255)  # Outline color
        h_d = base_diamond_size // 2
        
        # 2nd Base (Top center)
        c2x = bases_origin_x + base_cluster_width // 2
        c2y = overall_start_y + h_d
        poly2 = [(c2x, overall_start_y), (c2x + h_d, c2y), (c2x, c2y + h_d), (c2x - h_d, c2y)]
        if bases_occupied[1]:
            draw.polygon(poly2, fill=base_color_occupied)
        else:
            draw.polygon(poly2, outline=base_color_empty)
        
        base_bottom_y = c2y + h_d  # Bottom Y of 2nd base diamond
        
        # 3rd Base (Bottom left)
        c3x = bases_origin_x + h_d
        c3y = base_bottom_y + base_vert_spacing + h_d
        poly3 = [(c3x, base_bottom_y + base_vert_spacing), (c3x + h_d, c3y), (c3x, c3y + h_d), (c3x - h_d, c3y)]
        if bases_occupied[2]:
            draw.polygon(poly3, fill=base_color_occupied)
        else:
            draw.polygon(poly3, outline=base_color_empty)

        # 1st Base (Bottom right)
        c1x = bases_origin_x + base_cluster_width - h_d
        c1y = base_bottom_y + base_vert_spacing + h_d
        poly1 = [(c1x, base_bottom_y + base_vert_spacing), (c1x + h_d, c1y), (c1x, c1y + h_d), (c1x - h_d, c1y)]
        if bases_occupied[0]:
            draw.polygon(poly1, fill=base_color_occupied)
        else:
            draw.polygon(poly1, outline=base_color_empty)

    def _create_game_display(self, game: Dict[str, Any]) -> Image.Image:
        """Create a display image for a game in the new format."""
        width = self.display_manager.matrix.width
        height = self.display_manager.matrix.height
        
        # Make logos use most of the display height, with a small margin
        logo_size = int(height * 1.2)
        h_padding = 4 # Use a consistent horizontal padding

        # Fonts
        team_font = self.fonts['medium']
        odds_font = self.fonts['medium']
        vs_font = self.fonts['medium']
        datetime_font = self.fonts['medium'] # Use large font for date/time

        # Get team logos (with automatic download if missing)
        home_logo = self._get_team_logo(game["league"], game['home_id'], game['home_team'], game['logo_dir'])
        away_logo = self._get_team_logo(game["league"], game['away_id'], game['away_team'], game['logo_dir'])
        broadcast_logo = None
        
        # Enhanced broadcast logo debugging
        if self.show_channel_logos:
            broadcast_names = game.get('broadcast_info', [])  # This is now a list
            logger.info(f"Game {game.get('id')}: Raw broadcast info from API: {broadcast_names}")
            logger.info(f"Game {game.get('id')}: show_channel_logos setting: {self.show_channel_logos}")
            
            if broadcast_names:
                logo_name = None
                # Sort keys by length, descending, to match more specific names first (e.g., "ESPNEWS" before "ESPN")
                sorted_keys = sorted(self.BROADCAST_LOGO_MAP.keys(), key=len, reverse=True)
                logger.debug(f"Game {game.get('id')}: Available broadcast logo keys: {sorted_keys}")

                for b_name in broadcast_names:
                    logger.debug(f"Game {game.get('id')}: Checking broadcast name: '{b_name}'")
                    for key in sorted_keys:
                        if key in b_name:
                            logo_name = self.BROADCAST_LOGO_MAP[key]
                            logger.info(f"Game {game.get('id')}: Matched '{key}' to logo '{logo_name}' for broadcast '{b_name}'")
                            break  # Found the best match for this b_name
                    if logo_name:
                        break  # Found a logo, stop searching through broadcast list

                logger.info(f"Game {game.get('id')}: Final mapped logo name: '{logo_name}' from broadcast names: {broadcast_names}")
                if logo_name:
                    broadcast_logo = self.convert_image(Path("assets/broadcast_logos",f"{logo_name}.png"))
                    if broadcast_logo:
                        logger.info(f"Game {game.get('id')}: Successfully loaded broadcast logo for '{logo_name}' - Size: {broadcast_logo.size}")
                    else:
                        logger.warning(f"Game {game.get('id')}: Failed to load broadcast logo for '{logo_name}'")
                        # Check if the file exists
                        logo_path = os.path.join('assets', 'broadcast_logos', f"{logo_name}.png")
                        logger.warning(f"Game {game.get('id')}: Logo file exists: {os.path.exists(logo_path)}")
                else:
                    logger.warning(f"Game {game.get('id')}: No mapping found for broadcast names {broadcast_names} in BROADCAST_LOGO_MAP")
            else:
                logger.info(f"Game {game.get('id')}: No broadcast info available.")

        if home_logo:
            home_logo = home_logo.resize((logo_size, logo_size), Image.Resampling.LANCZOS)
        if away_logo:
            away_logo = away_logo.resize((logo_size, logo_size), Image.Resampling.LANCZOS)
        
        broadcast_logo_col_width = 0
        if broadcast_logo:
            # Standardize broadcast logo size to be smaller and more consistent
            # Use configurable height ratio that's smaller than the display height
            b_logo_h = int(height * self.broadcast_logo_height_ratio)
            # Maintain aspect ratio while fitting within the height constraint
            ratio = b_logo_h / broadcast_logo.height
            b_logo_w = int(broadcast_logo.width * ratio)
            
            # Ensure the width doesn't get too wide - cap it at configurable max width ratio
            max_width = int(width * self.broadcast_logo_max_width_ratio)
            if b_logo_w > max_width:
                ratio = max_width / broadcast_logo.width
                b_logo_w = max_width
                b_logo_h = int(broadcast_logo.height * ratio)
            
            broadcast_logo = broadcast_logo.resize((b_logo_w, b_logo_h), Image.Resampling.LANCZOS)
            broadcast_logo_col_width = b_logo_w
            logger.info(f"Game {game.get('id')}: Resized broadcast logo to {broadcast_logo.size}, column width: {broadcast_logo_col_width}")

        # Format date and time into 3 parts
        game_time = game['start_time']
        timezone_str = self.config.get('timezone', 'UTC')
        try:
            tz = pytz.timezone(timezone_str)
        except pytz.exceptions.UnknownTimeZoneError:
            tz = pytz.UTC
        
        if game_time.tzinfo is None:
            game_time = game_time.replace(tzinfo=pytz.UTC)
        local_time = game_time.astimezone(tz)
        
        # Check if this is a live game
        is_live = game.get('status_state') == 'in'
        live_info = game.get('live_info')
        
        if is_live and live_info:
            # Show live game information instead of date/time
            sport = None
            for league_key, config in self.league_configs.items():
                if config.get('logo_dir') == game.get('logo_dir'):
                    sport = config.get('sport')
                    break
            
            if sport == 'baseball':
                # For baseball, we'll use graphical base indicators instead of text
                # Don't show any text for bases - the graphical display will replace this section
                away_odds_text = ""
                home_odds_text = ""
                
                # Store bases data for later drawing
                self._bases_data = live_info.get('bases_occupied', [False, False, False])
                
                # Set datetime text for baseball live games
                inning_half_indicator = "▲" if live_info.get('inning_half') == 'top' else "▼"
                inning_text = f"{inning_half_indicator}{live_info.get('inning', 1)}"
                count_text = f"{live_info.get('balls', 0)}-{live_info.get('strikes', 0)}"
                outs_count = live_info.get('outs', 0)
                outs_text = f"{outs_count} out" if outs_count == 1 else f"{outs_count} outs"
                
                day_text = inning_text
                date_text = count_text
                time_text = outs_text
            elif sport == 'football':
                # Football: Show quarter and down/distance
                quarter_text = f"Q{live_info.get('quarter', 1)}"
                # Validate down and distance for odds ticker display
                down = live_info.get('down')
                distance = live_info.get('distance')
                if (down is not None and isinstance(down, int) and 1 <= down <= 4 and 
                    distance is not None and isinstance(distance, int) and distance >= 0):
                    down_text = f"{down}&{distance}"
                else:
                    down_text = ""  # Don't show invalid down/distance
                clock_text = live_info.get('clock', '')
                
                day_text = quarter_text
                date_text = down_text
                time_text = clock_text
                
            elif sport == 'basketball':
                # Basketball: Show quarter and time remaining
                quarter_text = f"Q{live_info.get('quarter', 1)}"
                clock_text = live_info.get('time_remaining', '')
                possession_text = live_info.get('possession', '')
                
                day_text = quarter_text
                date_text = clock_text
                time_text = possession_text
                
            elif sport == 'hockey':
                # Hockey: Show period and time remaining
                period_text = f"P{live_info.get('period', 1)}"
                clock_text = live_info.get('time_remaining', '')
                power_play_text = "PP" if live_info.get('power_play') else ""
                
                day_text = period_text
                date_text = clock_text
                time_text = power_play_text
                
            elif sport == 'soccer':
                # Soccer: Show period and time remaining
                period_text = f"P{live_info.get('period', 1)}"
                clock_text = live_info.get('time_remaining', '')
                extra_time_text = "+" if live_info.get('extra_time') else ""
                
                day_text = period_text
                date_text = clock_text
                time_text = extra_time_text
                
            else:
                # Fallback: Show generic live info
                day_text = "LIVE"
                date_text = f"{live_info.get('home_score', 0)}-{live_info.get('away_score', 0)}"
                time_text = live_info.get('clock', '')
        else:
            # Show regular date/time for non-live games
            # Capitalize full day name, e.g., 'Tuesday'
            day_text = local_time.strftime("%A")
            date_text = local_time.strftime("%-m/%d")
            time_text = local_time.strftime("%I:%M%p").lstrip('0')
        
        # Datetime column width
        temp_draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
        day_width = int(temp_draw.textlength(day_text, font=datetime_font))
        date_width = int(temp_draw.textlength(date_text, font=datetime_font))
        time_width = int(temp_draw.textlength(time_text, font=datetime_font))
        datetime_col_width = max(day_width, date_width, time_width)

        # "vs." text
        vs_text = "vs."
        vs_width = int(temp_draw.textlength(vs_text, font=vs_font))

        # Team and record text with rankings
        away_team_name = game.get('away_team_name', game.get('away_team', 'N/A'))
        home_team_name = game.get('home_team_name', game.get('home_team', 'N/A'))
        away_team_abbr = game.get('away_team', '')
        home_team_abbr = game.get('home_team', '')
        
        # Check if this is NCAA football and fetch rankings
        league_key = None
        for key, config in self.league_configs.items():
            if config.get('logo_dir') == game.get('logo_dir'):
                league_key = key
                break
        
        # Add ranking prefix for NCAA football teams
        if league_key == 'ncaa_fb':
            rankings = self._fetch_team_rankings()
            
            # Add ranking to away team name if ranked
            if away_team_abbr in rankings and rankings[away_team_abbr] > 0:
                away_team_name = f"{rankings[away_team_abbr]}. {away_team_name}"
            
            # Add ranking to home team name if ranked
            if home_team_abbr in rankings and rankings[home_team_abbr] > 0:
                home_team_name = f"{rankings[home_team_abbr]}. {home_team_name}"
        
        away_team_text = f"{away_team_name} ({game.get('away_record', '') or 'N/A'})"
        home_team_text = f"{home_team_name} ({game.get('home_record', '') or 'N/A'})"
        
        # For live games, show scores instead of records
        if is_live and live_info:
            away_score = live_info.get('away_score', 0)
            home_score = live_info.get('home_score', 0)
            away_team_text = f"{away_team_name}:{away_score} "
            home_team_text = f"{home_team_name}:{home_score} "
        
        away_team_width = int(temp_draw.textlength(away_team_text, font=team_font))
        home_team_width = int(temp_draw.textlength(home_team_text, font=team_font))
        team_info_width = max(away_team_width, home_team_width)
        
        # Odds text
        odds = game.get('odds') or {}
        home_team_odds = odds.get('home_team_odds', {})
        away_team_odds = odds.get('away_team_odds', {})
        
        # Determine the favorite and get the spread
        home_spread = home_team_odds.get('spread_odds')
        away_spread = away_team_odds.get('spread_odds')
        
        # Fallback to top-level spread from odds_manager
        top_level_spread = odds.get('spread')
        if top_level_spread is not None:
            if home_spread is None or home_spread == 0.0:
                home_spread = top_level_spread
            if away_spread is None:
                away_spread = -top_level_spread

        # Check for valid spread values before comparing
        home_favored = isinstance(home_spread, (int, float)) and home_spread < 0
        away_favored = isinstance(away_spread, (int, float)) and away_spread < 0

        over_under = odds.get('over_under')
        
        away_odds_text = ""
        home_odds_text = ""
        
        # For live games, show live status instead of odds
        if is_live and live_info:
            sport = None
            for league_key, config in self.league_configs.items():
                if config.get('logo_dir') == game.get('logo_dir'):
                    sport = config.get('sport')
                    break
            
            if sport == 'baseball':
                # Show bases occupied for baseball
                bases = live_info.get('bases_occupied', [False, False, False])
                bases_text = ""
                if bases[0]: bases_text += "1B"
                if bases[1]: bases_text += "2B"
                if bases[2]: bases_text += "3B"
                if not bases_text: bases_text = "Empty"
                
                away_odds_text = f"Bases: {bases_text}"
                home_odds_text = f"Count: {live_info.get('balls', 0)}-{live_info.get('strikes', 0)}"
                
            elif sport == 'football':
                # Show possession and yard line for football
                possession = live_info.get('possession', '')
                yard_line = live_info.get('yard_line', 0)
                
                away_odds_text = f"Ball: {possession}"
                home_odds_text = f"Yard: {yard_line}"
                
            elif sport == 'basketball':
                # Show possession for basketball
                possession = live_info.get('possession', '')
                
                away_odds_text = f"Ball: {possession}"
                home_odds_text = f"Time: {live_info.get('time_remaining', '')}"
                
            elif sport == 'hockey':
                # Show power play status for hockey
                power_play = live_info.get('power_play', False)
                
                away_odds_text = "Power Play" if power_play else "Even"
                home_odds_text = f"Time: {live_info.get('time_remaining', '')}"
                
            else:
                # Generic live status
                away_odds_text = "LIVE"
                home_odds_text = live_info.get('clock', '')
        else:
            # Show odds for non-live games
            # Simplified odds placement logic
            if home_favored:
                home_odds_text = f"{home_spread}"
                if over_under:
                    away_odds_text = f"O/U {over_under}"
            elif away_favored:
                away_odds_text = f"{away_spread}"
                if over_under:
                    home_odds_text = f"O/U {over_under}"
            elif over_under:
                home_odds_text = f"O/U {over_under}"
        
        away_odds_width = int(temp_draw.textlength(away_odds_text, font=odds_font))
        home_odds_width = int(temp_draw.textlength(home_odds_text, font=odds_font))
        odds_width = max(away_odds_width, home_odds_width)
        
        # For baseball live games, optimize width for graphical bases
        is_baseball_live = False
        if is_live and live_info and hasattr(self, '_bases_data'):
            sport = None
            for league_key, config in self.league_configs.items():
                if config.get('logo_dir') == game.get('logo_dir'):
                    sport = config.get('sport')
                    break
            
            if sport == 'baseball':
                is_baseball_live = True
                # Use a more compact width for baseball games to minimize dead space
                # The bases graphic only needs about 24px width, so we can be more efficient
                min_bases_width = 24  # Reduced from 30 to minimize dead space
                odds_width = max(odds_width, min_bases_width)

        # --- Calculate total width ---
        # Start with the sum of all visible components and consistent padding
        total_width = (logo_size + h_padding + 
                       vs_width + h_padding + 
                       logo_size + h_padding +
                       team_info_width + h_padding + 
                       odds_width + h_padding + 
                       datetime_col_width + h_padding) # Always add padding at the end
        
        # Add width for the broadcast logo if it exists
        if broadcast_logo:
            total_width += broadcast_logo_col_width + h_padding  # Add padding after broadcast logo
        
        logger.info(f"Game {game.get('id')}: Total width calculation - logo_size: {logo_size}, vs_width: {vs_width}, team_info_width: {team_info_width}, odds_width: {odds_width}, datetime_col_width: {datetime_col_width}, broadcast_logo_col_width: {broadcast_logo_col_width}, total_width: {total_width}")

        # --- Create final image ---
        image = Image.new('RGB', (int(total_width), height), color=(0, 0, 0))
        draw = ImageDraw.Draw(image)

        # --- Draw elements ---
        current_x = 0

        # Away Logo
        if away_logo:
            y_pos = (height - logo_size) // 2  # Center the logo vertically
            image.paste(away_logo, (current_x, y_pos), away_logo if away_logo.mode == 'RGBA' else None)
        current_x += logo_size + h_padding

        # "vs."
        y_pos = (height - vs_font.size) // 2 if hasattr(vs_font, 'size') else (height - 8) // 2 # Added fallback for default font
        
        # Use red color for live game "vs." text to make it stand out
        vs_color = (255, 255, 255)  # White for regular games
        if is_live and live_info:
            vs_color = (255, 0, 0)  # Red for live games
        
        draw.text((current_x, y_pos), vs_text, font=vs_font, fill=vs_color)
        current_x += vs_width + h_padding

        # Home Logo
        if home_logo:
            y_pos = (height - logo_size) // 2  # Center the logo vertically
            image.paste(home_logo, (current_x, y_pos), home_logo if home_logo.mode == 'RGBA' else None)
        current_x += logo_size + h_padding

        # Team Info (stacked)
        team_font_height = team_font.size if hasattr(team_font, 'size') else 8
        away_y = 2
        home_y = height - team_font_height - 2
        
        # Use red color for live game scores to make them stand out
        team_color = (255, 255, 255)  # White for regular team info
        if is_live and live_info:
            team_color = (255, 0, 0)  # Red for live games
        
        draw.text((current_x, away_y), away_team_text, font=team_font, fill=team_color)
        draw.text((current_x, home_y), home_team_text, font=team_font, fill=team_color)
        current_x += team_info_width + h_padding

        # Odds (stacked) - Skip text for baseball live games, draw bases instead
        odds_font_height = odds_font.size if hasattr(odds_font, 'size') else 8
        odds_y_away = 2
        odds_y_home = height - odds_font_height - 2
        
        # Use a consistent color for all odds text
        odds_color = (0, 255, 0) # Green
        
        # Use red color for live game information to make it stand out
        if is_live and live_info:
            odds_color = (255, 0, 0)  # Red for live games

        # Draw odds content based on game type
        if is_baseball_live:
            # Draw graphical bases instead of text
            # Position bases closer to team names (left side of odds column) for better spacing
            bases_x = current_x + 12  # Position at left side, offset by half cluster width (24/2 = 12)
            # Shift bases down a bit more for better positioning
            bases_y = (height // 2) + 2  # Move down 2 pixels from center
            
            # Ensure the bases don't go off the edge of the image
            base_diamond_size = 8  # Total size of the diamond
            base_cluster_width = 24  # Width of the base cluster (8 + 8 + 8) with tighter spacing
            if bases_x - (base_cluster_width // 2) >= 0 and bases_x + (base_cluster_width // 2) <= image.width:
                # Draw the base indicators
                self._draw_base_indicators(draw, self._bases_data, bases_x, bases_y)
            
            # Clear the bases data after drawing
            delattr(self, '_bases_data')
        else:
            # Draw regular odds text for non-baseball games
            draw.text((current_x, odds_y_away), away_odds_text, font=odds_font, fill=odds_color)
            draw.text((current_x, odds_y_home), home_odds_text, font=odds_font, fill=odds_color)
        
        # Dynamic spacing: Use reduced padding for baseball games to minimize dead space
        if is_baseball_live:
            # Use minimal padding since bases are positioned at left of column
            current_x += odds_width + (h_padding // 3)  # Use 1/3 padding for baseball games
        else:
            current_x += odds_width + h_padding
        
        # Datetime (stacked, 3 rows) - Center justified
        datetime_font_height = datetime_font.size if hasattr(datetime_font, 'size') else 6
        
        # Calculate available height for the three text lines
        total_text_height = (3 * datetime_font_height) + 4 # 2px padding between lines
        
        # Center the block of text vertically
        dt_start_y = (height - total_text_height) // 2

        day_y = dt_start_y
        date_y = day_y + datetime_font_height + 2
        time_y = date_y + datetime_font_height + 2

        # Center justify each line of text within the datetime column
        day_text_width = int(temp_draw.textlength(day_text, font=datetime_font))
        date_text_width = int(temp_draw.textlength(date_text, font=datetime_font))
        time_text_width = int(temp_draw.textlength(time_text, font=datetime_font))

        day_x = current_x + (datetime_col_width - day_text_width) // 2
        date_x = current_x + (datetime_col_width - date_text_width) // 2
        time_x = current_x + (datetime_col_width - time_text_width) // 2

        # Use red color for live game information to make it stand out
        datetime_color = (255, 255, 255)  # White for regular date/time
        if is_live and live_info:
            datetime_color = (255, 0, 0)  # Red for live games

        draw.text((day_x, day_y), day_text, font=datetime_font, fill=datetime_color)
        draw.text((date_x, date_y), date_text, font=datetime_font, fill=datetime_color)
        draw.text((time_x, time_y), time_text, font=datetime_font, fill=datetime_color)
        current_x += datetime_col_width + h_padding # Add padding after datetime

        if broadcast_logo:
            # Position the broadcast logo in its own column
            logo_y = (height - broadcast_logo.height) // 2
            logger.info(f"Game {game.get('id')}: Pasting broadcast logo at ({int(current_x)}, {logo_y})")
            logger.info(f"Game {game.get('id')}: Broadcast logo size: {broadcast_logo.size}, image total width: {image.width}")
            image.paste(broadcast_logo, (int(current_x), logo_y), broadcast_logo if broadcast_logo.mode == 'RGBA' else None)
            logger.info(f"Game {game.get('id')}: Successfully pasted broadcast logo")
        else:
            logger.info(f"Game {game.get('id')}: No broadcast logo to paste")

        return image

    def _create_ticker_image(self):
        """Create a single wide image containing all game tickers using ScrollHelper."""
        logger.debug("Entering _create_ticker_image method")
        logger.debug(f"Number of games in games_data: {len(self.games_data) if self.games_data else 0}")
        
        if not self.games_data:
            logger.warning("No games data available, cannot create ticker image.")
            self.ticker_image = None
            self.scroll_helper.clear_cache()
            return

        logger.debug(f"Creating ticker image for {len(self.games_data)} games.")
        game_images = [self._create_game_display(game) for game in self.games_data]
        logger.debug(f"Created {len(game_images)} game images")
        
        if not game_images:
            logger.warning("Failed to create any game images.")
            self.ticker_image = None
            self.scroll_helper.clear_cache()
            return

        gap_width = 24  # Gap between games
        height = self.display_manager.matrix.height
        
        # Use ScrollHelper to create the scrolling image
        # ScrollHelper automatically adds display_width padding at the start
        self.ticker_image = self.scroll_helper.create_scrolling_image(
            content_items=game_images,
            item_gap=gap_width,
            element_gap=0  # No gap within items
        )
        
        # Add white vertical bars between games for visual separation
        # ScrollHelper places items with gaps, so we need to find where to add bars
        display_width = self.display_manager.matrix.width
        current_x = display_width  # Start after initial padding
        
        for idx, img in enumerate(game_images):
            current_x += img.width
            # Add white bar in the middle of the gap (except after last game)
            if idx < len(game_images) - 1:
                bar_x = current_x + gap_width // 2
                # Use ImageDraw for more efficient drawing
                draw = ImageDraw.Draw(self.ticker_image)
                draw.line([(bar_x, 0), (bar_x, height - 1)], fill=(255, 255, 255), width=1)
            current_x += gap_width
        
        # Store reference for compatibility
        self.total_scroll_width = self.scroll_helper.total_scroll_width
        
        # Get dynamic duration from ScrollHelper
        self.dynamic_duration = self.scroll_helper.get_dynamic_duration()
        
        logger.debug(f"Odds ticker image creation:")
        logger.debug(f"  Display width: {display_width}px")
        logger.debug(f"  Content width: {self.total_scroll_width}px")
        logger.debug(f"  Total image width: {self.ticker_image.width}px")
        logger.debug(f"  Number of games: {len(game_images)}")
        logger.debug(f"  Gap width: {gap_width}px")
        logger.debug(f"  Dynamic duration: {self.dynamic_duration}s")

    def _draw_text_with_outline(self, draw: ImageDraw.Draw, text: str, position: tuple, font: ImageFont.FreeTypeFont, 
                               fill: tuple = (255, 255, 255), outline_color: tuple = (0, 0, 0)) -> None:
        """Draw text with a black outline for better readability."""
        x, y = position
        # Draw outline
        for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
            draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
        # Draw main text
        draw.text((x, y), text, font=font, fill=fill)

    # Dynamic duration calculation is now handled by ScrollHelper

    def get_dynamic_duration(self) -> int:
        """Get the calculated dynamic duration for display"""
        # If we don't have a valid dynamic duration yet (total_scroll_width is 0),
        # try to update the data first
        if self.total_scroll_width == 0 and self.is_enabled:
            logger.debug("get_dynamic_duration called but total_scroll_width is 0, attempting update...")
            try:
                # Force an update to get the data and calculate proper duration
                # Bypass the update interval check for duration calculation
                self.games_data = self._fetch_upcoming_games()
                self.scroll_helper.reset_scroll()
                self.current_game_index = 0
                self._create_ticker_image() # Create the composite image
                logger.debug(f"Force update completed, total_scroll_width: {self.total_scroll_width}px")
            except Exception as e:
                logger.error(f"Error updating odds ticker for dynamic duration: {e}")
        
        logger.debug(f"get_dynamic_duration called, returning: {self.dynamic_duration}s")
        return self.dynamic_duration

    def update(self):
        """Update odds ticker data."""
        logger.debug("Entering update method")
        if not self.is_enabled:
            logger.debug("Odds ticker is disabled, skipping update")
            return
            
        # Check if we're currently scrolling and defer the update if so
        if hasattr(self.display_manager, 'is_currently_scrolling') and self.display_manager.is_currently_scrolling():
            logger.debug("Odds ticker is currently scrolling, deferring update")
            if hasattr(self.display_manager, 'defer_update'):
                self.display_manager.defer_update(self._perform_update, priority=1)
            return
            
        self._perform_update()

    def _perform_update(self):
        """Internal method to perform the actual update."""
        current_time = time.time()
        if current_time - self.last_update < self.update_interval:
            logger.debug(f"Odds ticker update interval not reached. Next update in {self.update_interval - (current_time - self.last_update)} seconds")
            return
        
        try:
            logger.debug("Updating odds ticker data")
            logger.debug(f"Enabled leagues: {self.enabled_leagues}")
            logger.debug(f"Show favorite teams only: {self.show_favorite_teams_only}")
            
            self.games_data = self._fetch_upcoming_games()
            self.last_update = current_time
            self.scroll_helper.reset_scroll()
            self.current_game_index = 0
            # Reset logging flags when updating data
            self._end_reached_logged = False
            self._insufficient_time_warning_logged = False
            self._create_ticker_image() # Create the composite image
            
            if self.games_data:
                logger.info(f"Updated odds ticker with {len(self.games_data)} games")
                for i, game in enumerate(self.games_data[:3]):  # Log first 3 games
                    logger.info(f"Game {i+1}: {game['away_team']} @ {game['home_team']} - {game['start_time']}")
            else:
                logger.warning("No games found for odds ticker")
                
        except Exception as e:
            logger.error(f"Error updating odds ticker: {e}", exc_info=True)

    def display(self, display_mode: str = None, force_clear: bool = False):
        """Display the odds ticker."""
        logger.debug("Entering display method")
        logger.debug(f"Odds ticker enabled: {self.is_enabled}")
        logger.debug(f"Current scroll position: {self.scroll_helper.scroll_position}")
        logger.debug(f"Ticker image width: {self.ticker_image.width if self.ticker_image else 'None'}")
        logger.debug(f"Dynamic duration: {self.dynamic_duration}s")
        
        if not self.is_enabled:
            logger.debug("Odds ticker is disabled, exiting display method.")
            return
        
        # Reset display start time when force_clear is True or when starting fresh
        if force_clear or self._display_start_time is None:
            self._display_start_time = time.time()
            logger.debug(f"Reset/initialized display start time: {self._display_start_time}")
            # Also reset scroll position for clean start
            self.scroll_helper.reset_scroll()
            # Reset the end reached logging flag
            self._end_reached_logged = False
            # Reset the insufficient time warning logging flag
            self._insufficient_time_warning_logged = False
        else:
            # Check if the display start time is too old (more than 2x the dynamic duration)
            current_time = time.time()
            elapsed_time = current_time - self._display_start_time
            if elapsed_time > (self.dynamic_duration * 2):
                logger.debug(f"Display start time is too old ({elapsed_time:.1f}s), resetting")
                self._display_start_time = current_time
                self.scroll_helper.reset_scroll()
                # Reset the end reached logging flag
                self._end_reached_logged = False
                # Reset the insufficient time warning logging flag
                self._insufficient_time_warning_logged = False
        
        logger.debug(f"Number of games in data at start of display method: {len(self.games_data)}")
        if not self.games_data:
            logger.warning("Odds ticker has no games data. Attempting to update...")
            try:
                import threading
                import queue
                
                update_queue = queue.Queue()
                
                def perform_update():
                    try:
                        self.update()
                        update_queue.put(('success', None))
                    except Exception as e:
                        update_queue.put(('error', e))
                
                # Start update in a separate thread with 10-second timeout
                update_thread = threading.Thread(target=perform_update)
                update_thread.daemon = True
                update_thread.start()
                
                try:
                    result_type, result_data = update_queue.get(timeout=10)
                    if result_type == 'error':
                        logger.error(f"Update failed: {result_data}")
                except queue.Empty:
                    logger.warning("Update timed out after 10 seconds, using fallback")
                
            except Exception as e:
                logger.error(f"Error during update: {e}")
            
            if not self.games_data:
                logger.warning("Still no games data after update. Displaying fallback message.")
                self._display_fallback_message()
                return
        
        if self.ticker_image is None:
            logger.warning("Ticker image is not available. Attempting to create it.")
            try:
                import threading
                import queue
                
                image_queue = queue.Queue()
                
                def create_image():
                    try:
                        self._create_ticker_image()
                        image_queue.put(('success', None))
                    except Exception as e:
                        image_queue.put(('error', e))
                
                # Start image creation in a separate thread with 5-second timeout
                image_thread = threading.Thread(target=create_image)
                image_thread.daemon = True
                image_thread.start()
                
                try:
                    result_type, result_data = image_queue.get(timeout=5)
                    if result_type == 'error':
                        logger.error(f"Image creation failed: {result_data}")
                except queue.Empty:
                    logger.warning("Image creation timed out after 5 seconds")
                
            except Exception as e:
                logger.error(f"Error during image creation: {e}")
            
            if self.ticker_image is None:
                logger.error("Failed to create ticker image.")
                self._display_fallback_message()
                return

        try:
            # Use ScrollHelper for scrolling functionality
            # For non-looping mode, only update scroll if not complete
            if self.loop or not self.scroll_helper.is_scroll_complete():
                # Update scroll position (handles time-based scrolling automatically)
                self.scroll_helper.update_scroll_position()
            else:
                # Non-looping and scroll complete - stop scrolling
                if not self._end_reached_logged:
                    logger.info("Odds ticker reached end - scroll complete")
                    self._end_reached_logged = True
                # Signal that scrolling has stopped
                if hasattr(self.display_manager, 'set_scrolling_state'):
                    self.display_manager.set_scrolling_state(False)
            
            # Get the visible portion of the scrolling image
            visible_image = self.scroll_helper.get_visible_portion()
            
            if visible_image is None:
                logger.warning("ScrollHelper returned None for visible portion, using fallback")
                self._display_fallback_message()
                return
            
            # Signal scrolling state
            if hasattr(self.display_manager, 'set_scrolling_state'):
                if self.loop or not self.scroll_helper.is_scroll_complete():
                    self.display_manager.set_scrolling_state(True)
                else:
                    self.display_manager.set_scrolling_state(False)
            
            # Update dynamic duration from ScrollHelper
            self.dynamic_duration = self.scroll_helper.get_dynamic_duration()
            
            # Display the visible portion (use paste like leaderboard for better performance)
            if visible_image:
                self.display_manager.image.paste(visible_image, (0, 0))
                self.display_manager.update_display()
            
            # Log frame rate for performance monitoring (like leaderboard does)
            self.scroll_helper.log_frame_rate()
            
        except Exception as e:
            logger.error(f"Error displaying odds ticker: {e}", exc_info=True)
            self._display_fallback_message()

    def _display_fallback_message(self):
        """Display a fallback message when no games data is available."""
        try:
            width = self.display_manager.matrix.width
            height = self.display_manager.matrix.height
            
            logger.info(f"Displaying fallback message on {width}x{height} display")
            
            # Create a simple fallback image with a brighter background
            image = Image.new('RGB', (width, height), color=(50, 50, 50))  # Dark gray instead of black
            draw = ImageDraw.Draw(image)
            
            # Draw a simple message with larger font
            message = "No odds data"
            font = self.fonts['large']  # Use large font for better visibility
            text_width = draw.textlength(message, font=font)
            text_x = (width - text_width) // 2
            text_y = (height - font.size) // 2
            
            logger.info(f"Drawing fallback message: '{message}' at position ({text_x}, {text_y})")
            
            # Draw with bright white text and black outline
            self._draw_text_with_outline(draw, message, (text_x, text_y), font, fill=(255, 255, 255), outline_color=(0, 0, 0))
            
            # Display the fallback image
            self.display_manager.image = image
            self.display_manager.draw = ImageDraw.Draw(self.display_manager.image)
            self.display_manager.update_display()
            
            logger.info("Fallback message display completed")
            
        except Exception as e:
            logger.error(f"Error displaying fallback message: {e}", exc_info=True)

    def get_display_duration(self) -> float:
        """Get display duration from config."""
        return self.get_dynamic_duration()

    def get_info(self) -> Dict[str, Any]:
        """Return plugin info for web UI."""
        info = {
            'total_games': len(self.games_data),
            'enabled_leagues': self.enabled_leagues,
            'last_update': self.last_update,
            'display_duration': self.get_display_duration(),
            'scroll_speed': self.scroll_speed,
            'show_favorite_teams_only': self.show_favorite_teams_only,
            'max_games_per_league': self.max_games_per_league,
            'dynamic_duration': self.dynamic_duration,
            'total_scroll_width': self.total_scroll_width,
            'scroll_position': self.scroll_helper.scroll_position,
            'ticker_image_width': self.ticker_image.width if self.ticker_image else 0
        }
        return info

    def cleanup(self) -> None:
        """Cleanup resources."""
        self.games_data = []
        self.ticker_image = None
        self.scroll_helper.clear_cache()
        self._end_reached_logged = False
        self._insufficient_time_warning_logged = False
        logger.info("Odds ticker plugin cleaned up")
