"""
Game Filter for Odds Ticker Plugin

Handles filtering and sorting of games based on configuration.
Manages favorite teams, league preferences, and display options.

Features:
- Favorite team filtering
- League-based filtering
- Game sorting and prioritization
- Time-based filtering
- Performance optimization
"""

import logging
from typing import Dict, Any, List
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


class GameFilter:
    """Handles filtering and sorting of games for the odds ticker."""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize the game filter."""
        self.config = config
        
        # Filter settings
        self.show_favorite_teams_only = config.get('show_favorite_teams_only', False)
        self.games_per_favorite_team = config.get('games_per_favorite_team', 1)
        self.max_games_per_league = config.get('max_games_per_league', 5)
        self.sort_order = config.get('sort_order', 'soonest')
        self.enabled_leagues = config.get('enabled_leagues', ['nfl', 'nba', 'mlb'])
        self.future_fetch_days = config.get('future_fetch_days', 7)
        
        # League configurations
        self.league_configs = self._setup_league_configs()
        
        logger.info("GameFilter initialized")
    
    def _setup_league_configs(self) -> Dict[str, Dict]:
        """Setup league configurations for filtering."""
        return {
            'nfl': {
                'favorite_teams': self.config.get('nfl', {}).get('favorite_teams', []),
                'enabled': self.config.get('nfl', {}).get('enabled', False)
            },
            'nba': {
                'favorite_teams': self.config.get('nba', {}).get('favorite_teams', []),
                'enabled': self.config.get('nba', {}).get('enabled', False)
            },
            'mlb': {
                'favorite_teams': self.config.get('mlb', {}).get('favorite_teams', []),
                'enabled': self.config.get('mlb', {}).get('enabled', False)
            },
            'ncaa_fb': {
                'favorite_teams': self.config.get('ncaa_fb', {}).get('favorite_teams', []),
                'enabled': self.config.get('ncaa_fb', {}).get('enabled', False)
            },
            'ncaam_basketball': {
                'favorite_teams': self.config.get('ncaam_basketball', {}).get('favorite_teams', []),
                'enabled': self.config.get('ncaam_basketball', {}).get('enabled', False)
            }
        }
    
    def filter_games(self, games: List[Dict]) -> List[Dict]:
        """Filter games based on configuration."""
        if not games:
            return []
        
        try:
            # Apply league filtering
            filtered_games = self._filter_by_league(games)
            
            # Apply favorite teams filtering
            if self.show_favorite_teams_only:
                filtered_games = self._filter_by_favorite_teams(filtered_games)
            
            # Apply time-based filtering
            filtered_games = self._filter_by_time(filtered_games)
            
            # Sort games
            filtered_games = self._sort_games(filtered_games)
            
            # Limit games per league
            filtered_games = self._limit_games_per_league(filtered_games)
            
            logger.debug(f"Filtered {len(games)} games down to {len(filtered_games)}")
            return filtered_games
            
        except Exception as e:
            logger.error(f"Error filtering games: {e}")
            return games[:self.max_games_per_league]  # Return first N games as fallback
    
    def _filter_by_league(self, games: List[Dict]) -> List[Dict]:
        """Filter games by enabled leagues."""
        filtered = []
        
        for game in games:
            league = game.get('league', '')
            if league in self.enabled_leagues:
                league_config = self.league_configs.get(league, {})
                if league_config.get('enabled', False):
                    filtered.append(game)
        
        return filtered
    
    def _filter_by_favorite_teams(self, games: List[Dict]) -> List[Dict]:
        """Filter games to only include favorite teams."""
        if not self.show_favorite_teams_only:
            return games
        
        filtered = []
        
        for game in games:
            league = game.get('league', '')
            league_config = self.league_configs.get(league, {})
            favorite_teams = league_config.get('favorite_teams', [])
            
            if not favorite_teams:
                # If no favorite teams for this league, include all games
                filtered.append(game)
                continue
            
            home_abbr = game.get('home_abbr', '')
            away_abbr = game.get('away_abbr', '')
            
            if home_abbr in favorite_teams or away_abbr in favorite_teams:
                filtered.append(game)
        
        return filtered
    
    def _filter_by_time(self, games: List[Dict]) -> List[Dict]:
        """Filter games by time (upcoming games only)."""
        try:
            current_time = datetime.now(timezone.utc)
            future_cutoff = current_time + timedelta(days=self.future_fetch_days)
            
            filtered = []
            
            for game in games:
                start_time_str = game.get('start_time', '')
                if not start_time_str:
                    continue
                
                try:
                    # Parse start time (assuming ISO format)
                    start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                    
                    # Only include games in the future within our fetch window
                    if current_time <= start_time <= future_cutoff:
                        filtered.append(game)
                        
                except ValueError as e:
                    logger.debug(f"Error parsing start time '{start_time_str}': {e}")
                    continue
            
            return filtered
            
        except Exception as e:
            logger.error(f"Error filtering games by time: {e}")
            return games
    
    def _sort_games(self, games: List[Dict]) -> List[Dict]:
        """Sort games based on configuration."""
        try:
            if self.sort_order == 'soonest':
                return self._sort_by_time(games)
            elif self.sort_order == 'league':
                return self._sort_by_league(games)
            elif self.sort_order == 'team':
                return self._sort_by_team(games)
            else:
                return games
                
        except Exception as e:
            logger.error(f"Error sorting games: {e}")
            return games
    
    def _sort_by_time(self, games: List[Dict]) -> List[Dict]:
        """Sort games by start time (soonest first)."""
        def sort_key(game):
            start_time_str = game.get('start_time', '')
            try:
                if start_time_str:
                    return datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                else:
                    return datetime.max
            except ValueError:
                return datetime.max
        
        return sorted(games, key=sort_key)
    
    def _sort_by_league(self, games: List[Dict]) -> List[Dict]:
        """Sort games by league priority."""
        league_priority = {league: i for i, league in enumerate(self.enabled_leagues)}
        
        def sort_key(game):
            league = game.get('league', '')
            return league_priority.get(league, 999)
        
        return sorted(games, key=sort_key)
    
    def _sort_by_team(self, games: List[Dict]) -> List[Dict]:
        """Sort games by team name."""
        def sort_key(game):
            home_team = game.get('home_team', {}).get('name', '')
            away_team = game.get('away_team', {}).get('name', '')
            return f"{away_team} @ {home_team}"
        
        return sorted(games, key=sort_key)
    
    def _limit_games_per_league(self, games: List[Dict]) -> List[Dict]:
        """Limit number of games per league."""
        if self.max_games_per_league <= 0:
            return games
        
        league_counts = {}
        limited_games = []
        
        for game in games:
            league = game.get('league', '')
            current_count = league_counts.get(league, 0)
            
            if current_count < self.max_games_per_league:
                limited_games.append(game)
                league_counts[league] = current_count + 1
        
        return limited_games
    
    def should_show_game(self, game: Dict) -> bool:
        """Check if a game should be shown based on current filters."""
        try:
            # Check league
            league = game.get('league', '')
            if league not in self.enabled_leagues:
                return False
            
            league_config = self.league_configs.get(league, {})
            if not league_config.get('enabled', False):
                return False
            
            # Check favorite teams if enabled
            if self.show_favorite_teams_only:
                favorite_teams = league_config.get('favorite_teams', [])
                if favorite_teams:
                    home_abbr = game.get('home_abbr', '')
                    away_abbr = game.get('away_abbr', '')
                    
                    if home_abbr not in favorite_teams and away_abbr not in favorite_teams:
                        return False
            
            # Check time
            start_time_str = game.get('start_time', '')
            if start_time_str:
                try:
                    start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                    current_time = datetime.now(timezone.utc)
                    future_cutoff = current_time + timedelta(days=self.future_fetch_days)
                    
                    if not (current_time <= start_time <= future_cutoff):
                        return False
                        
                except ValueError:
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking if game should be shown: {e}")
            return False
    
    def get_filter_stats(self) -> Dict[str, Any]:
        """Get statistics about current filtering configuration."""
        return {
            'show_favorite_teams_only': self.show_favorite_teams_only,
            'games_per_favorite_team': self.games_per_favorite_team,
            'max_games_per_league': self.max_games_per_league,
            'sort_order': self.sort_order,
            'enabled_leagues': self.enabled_leagues,
            'future_fetch_days': self.future_fetch_days,
            'league_configs': {
                league: {
                    'enabled': config.get('enabled', False),
                    'favorite_teams_count': len(config.get('favorite_teams', []))
                }
                for league, config in self.league_configs.items()
            }
        }
