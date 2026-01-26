"""
Data Fetcher for Odds Ticker Plugin

Handles fetching odds data from various sports APIs and managing
background data fetching for the odds ticker display.

Features:
- Multi-sport odds fetching (NFL, NBA, MLB, NCAA Football, NCAA Basketball)
- Background data service integration
- Caching and error handling
- Team record and ranking fetching
- Dynamic team resolution
"""

import time
import logging
import requests
from typing import Dict, Any, List, Optional

# Import the API counter function from web interface
try:
    from web_interface_v2 import increment_api_counter
except ImportError:
    # Fallback if web interface is not available
    def increment_api_counter(kind: str, count: int = 1):
        pass

logger = logging.getLogger(__name__)


class OddsDataFetcher:
    """Handles fetching odds data for the odds ticker plugin."""
    
    def __init__(self, cache_manager, odds_manager, background_service, 
                 dynamic_resolver, config: Dict[str, Any]):
        """Initialize the data fetcher."""
        self.cache_manager = cache_manager
        self.odds_manager = odds_manager
        self.background_service = background_service
        self.dynamic_resolver = dynamic_resolver
        self.config = config
        
        # Configuration
        self.request_timeout = config.get('request_timeout', 30)
        self.future_fetch_days = config.get('future_fetch_days', 7)
        self.show_favorite_teams_only = config.get('show_favorite_teams_only', False)
        self.games_per_favorite_team = config.get('games_per_favorite_team', 1)
        self.max_games_per_league = config.get('max_games_per_league', 5)
        self.fetch_odds = config.get('fetch_odds', True)
        self.enabled_leagues = config.get('enabled_leagues', ['nfl', 'nba', 'mlb'])
        
        # League configurations
        self.league_configs = self._setup_league_configs()
        
        # Background fetch tracking
        self.background_fetch_requests = {}
        self.background_enabled = True
        
        # Initialize cache attributes
        self._team_rankings_cache = {}
        self._rankings_cache_timestamp = 0
        
        logger.info("OddsDataFetcher initialized")
    
    def _setup_league_configs(self) -> Dict[str, Dict]:
        """Setup league configurations with dynamic team resolution."""
        league_configs = {
            'nfl': {
                'sport': 'football',
                'league': 'nfl',
                'logo_league': 'nfl',
                'logo_dir': 'assets/sports/nfl_logos',
                'favorite_teams': self.config.get('nfl', {}).get('favorite_teams', []),
                'enabled': self.config.get('nfl', {}).get('enabled', False)
            },
            'nba': {
                'sport': 'basketball',
                'league': 'nba',
                'logo_league': 'nba',
                'logo_dir': 'assets/sports/nba_logos',
                'favorite_teams': self.config.get('nba', {}).get('favorite_teams', []),
                'enabled': self.config.get('nba', {}).get('enabled', False)
            },
            'mlb': {
                'sport': 'baseball',
                'league': 'mlb',
                'logo_league': 'mlb',
                'logo_dir': 'assets/sports/mlb_logos',
                'favorite_teams': self.config.get('mlb', {}).get('favorite_teams', []),
                'enabled': self.config.get('mlb', {}).get('enabled', False)
            },
            'ncaa_fb': {
                'sport': 'football',
                'league': 'college-football',
                'logo_league': 'ncaa_fb',
                'logo_dir': 'assets/sports/ncaa_logos',
                'favorite_teams': self.config.get('ncaa_fb', {}).get('favorite_teams', []),
                'enabled': self.config.get('ncaa_fb', {}).get('enabled', False)
            },
            'ncaam_basketball': {
                'sport': 'basketball',
                'league': 'mens-college-basketball',
                'logo_league': 'ncaam_basketball',
                'logo_dir': 'assets/sports/ncaa_logos',
                'favorite_teams': self.config.get('ncaam_basketball', {}).get('favorite_teams', []),
                'enabled': self.config.get('ncaam_basketball', {}).get('enabled', False)
            }
        }
        
        # Resolve dynamic teams for each league
        for league_key, league_config in league_configs.items():
            if league_config.get('enabled', False):
                raw_favorite_teams = league_config.get('favorite_teams', [])
                if raw_favorite_teams:
                    resolved_teams = self.dynamic_resolver.resolve_teams(raw_favorite_teams, league_key)
                    league_config['favorite_teams'] = resolved_teams
                    
                    if raw_favorite_teams != resolved_teams:
                        logger.info(f"Resolved dynamic teams for {league_key}: {raw_favorite_teams} -> {resolved_teams}")
                    else:
                        logger.info(f"Favorite teams for {league_key}: {resolved_teams}")
        
        return league_configs
    
    def fetch_upcoming_games(self) -> List[Dict]:
        """Fetch upcoming games for all enabled leagues."""
        all_games = []
        
        for league_key in self.enabled_leagues:
            if league_key in self.league_configs:
                league_config = self.league_configs[league_key]
                if league_config.get('enabled', False):
                    games = self._fetch_league_games(league_key, league_config)
                    all_games.extend(games)
        
        # Sort games by start time
        all_games.sort(key=lambda x: x.get('start_time', ''))
        
        logger.info(f"Fetched {len(all_games)} upcoming games")
        return all_games
    
    def _fetch_league_games(self, league_key: str, league_config: Dict) -> List[Dict]:
        """Fetch games for a specific league."""
        try:
            logger.debug("Fetching games for %s", league_key)
            
            sport = league_config.get('sport')
            league = league_config.get('league')
            
            if not sport or not league:
                logger.warning("Missing sport or league for %s", league_key)
                return []
            
            # Fetch upcoming games from ESPN API
            url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"
            
            response = requests.get(url, timeout=self.request_timeout)
            response.raise_for_status()
            data = response.json()
            
            # Increment API counter
            if hasattr(self, 'increment_api_counter'):
                self.increment_api_counter('sports', 1)
            
            games = []
            events = data.get('events', [])
            
            for event in events:
                try:
                    competition = event.get('competitions', [{}])[0]
                    competitors = competition.get('competitors', [])
                    
                    # Get home and away team data (ESPN API structure)
                    home_competitor = competitors[0] if len(competitors) > 0 else {}
                    away_competitor = competitors[1] if len(competitors) > 1 else {}
                    
                    home_team_data = home_competitor.get('team', {})
                    away_team_data = away_competitor.get('team', {})
                    
                    # Extract broadcast info
                    broadcasts = competition.get('broadcasts', [])
                    broadcast_info = []
                    if broadcasts:
                        for broadcast in broadcasts:
                            names = broadcast.get('names', [])
                            if names:
                                broadcast_info.extend(names)
                    
                    game_data = {
                        'id': event.get('id'),
                        'home_id': home_team_data.get('id'),
                        'away_id': away_team_data.get('id'),
                        'home_team': home_team_data.get('abbreviation', 'HOME'),
                        'away_team': away_team_data.get('abbreviation', 'AWAY'),
                        'home_team_name': home_team_data.get('displayName', home_team_data.get('abbreviation', 'HOME')),
                        'away_team_name': away_team_data.get('displayName', away_team_data.get('abbreviation', 'AWAY')),
                        'start_time': event.get('date'),
                        'home_record': home_competitor.get('records', [{}])[0].get('summary', 'N/A') if home_competitor.get('records') else 'N/A',
                        'away_record': away_competitor.get('records', [{}])[0].get('summary', 'N/A') if away_competitor.get('records') else 'N/A',
                        'odds': None,  # Will be fetched separately
                        'broadcast_info': broadcast_info,
                        'logo_dir': league_config.get('logo_dir', f'assets/sports/{league.lower()}_logos'),
                        'league': league_config.get('logo_league', league),
                        'sport': sport
                    }
                    games.append(game_data)
                except Exception as e:
                    logger.debug("Error parsing game data: %s", e)
                    continue
            
            logger.debug("Fetched %s games for %s", len(games), league_key)
            return games
            
        except Exception as e:
            logger.error("Error fetching games for %s: %s", league_key, e)
            return []
    
    def fetch_team_record(self, team_abbr: str, league: str) -> str:
        """Fetch team record from ESPN API."""
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
    
    def fetch_team_rankings(self) -> Dict[str, int]:
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
            polls = data.get('polls', [])
            
            # Look for AP Poll (usually first poll)
            for poll in polls:
                if poll.get('name') == 'AP Top 25':
                    for rank, team in enumerate(poll.get('ranks', []), 1):
                        team_abbr = team.get('team', {}).get('abbreviation', '')
                        if team_abbr:
                            rankings[team_abbr] = rank
                    break
            
            # Cache the rankings
            self._team_rankings_cache = rankings
            self._rankings_cache_timestamp = current_time
            
            logger.info(f"Fetched {len(rankings)} team rankings")
            return rankings
            
        except Exception as e:
            logger.error(f"Error fetching team rankings: {e}")
            return {}
    
    def fetch_game_odds(self, game: Dict, league_key: str) -> Optional[Dict]:
        """Fetch odds for a specific game."""
        if not self.fetch_odds:
            return None

        try:
            league_config = self.league_configs.get(league_key, {})
            sport = league_config.get('sport', '')
            league = league_config.get('league', '')
            event_id = game.get('id', '')

            if not sport or not league or not event_id:
                return None

            # Check if game is live for cache strategy (2 min vs 30 min cache)
            is_live = game.get('status_state') == 'in' or game.get('is_live', False)
            odds_data = self.odds_manager.get_odds(sport, league, event_id, is_live=is_live)
            return odds_data
            
        except Exception as e:
            logger.error(f"Error fetching odds for game {game.get('id', 'N/A')}: {e}")
            return None
    
    def should_show_game(self, game: Dict, league_key: str) -> bool:
        """Determine if a game should be shown based on configuration."""
        if not self.show_favorite_teams_only:
            return True
        
        league_config = self.league_configs.get(league_key, {})
        favorite_teams = league_config.get('favorite_teams', [])
        
        if not favorite_teams:
            return True
        
        home_abbr = game.get('home_abbr', '')
        away_abbr = game.get('away_abbr', '')
        
        return home_abbr in favorite_teams or away_abbr in favorite_teams
    
    def get_background_service_status(self) -> Dict[str, Any]:
        """Get status of background data service."""
        return {
            'enabled': self.background_enabled,
            'active_requests': len(self.background_fetch_requests),
            'requests': list(self.background_fetch_requests.keys())
        }
