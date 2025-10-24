"""
Odds Ticker Plugin for LEDMatrix

Displays scrolling odds and betting lines for upcoming games across multiple sports leagues.
Shows point spreads, money lines, and over/under totals with team information.

Features:
- Multi-sport odds display (NFL, NBA, MLB, NCAA Football, NCAA Basketball)
- Scrolling ticker format
- Favorite team prioritization
- Broadcast channel logos
- Configurable scroll speed and display duration
- Background data fetching

API Version: 1.0.0
"""

import logging
import time
from typing import Dict, Any

from src.plugin_system.base_plugin import BasePlugin

# Import odds manager for data access
try:
    from src.old_managers.odds_manager import OddsManager
except ImportError:
    OddsManager = None

# Import background service and dynamic resolver
try:
    from src.background_data_service import get_background_service
    from src.dynamic_team_resolver import DynamicTeamResolver
except ImportError:
    get_background_service = None
    DynamicTeamResolver = None

# Import our modular components
import sys
import os

# Add the plugin directory to Python path for imports
plugin_dir = os.path.dirname(os.path.abspath(__file__))
if plugin_dir not in sys.path:
    sys.path.insert(0, plugin_dir)

from data_fetcher import OddsDataFetcher
from odds_renderer import OddsRenderer
from game_filter import GameFilter

logger = logging.getLogger(__name__)


class OddsTickerPlugin(BasePlugin):
    """
    Odds ticker plugin for displaying betting odds across multiple sports.

    Supports NFL, NBA, MLB, NCAA Football, and NCAA Basketball with configurable
    display options and scrolling ticker format.

    Configuration options:
        leagues: Enable/disable specific sports for odds
        display_options: Scroll speed, duration, favorite teams only
        background_service: Data fetching configuration
    """

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the odds ticker plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        # Check required dependencies
        if OddsManager is None:
            self.logger.error("Failed to import OddsManager. Plugin will not function.")
            self.initialized = False
            return

        if get_background_service is None or DynamicTeamResolver is None:
            self.logger.error("Failed to import required services. Plugin will not function.")
            self.initialized = False
            return

        # Configuration
        self.global_config = config
        self.display_duration = config.get('display_duration', 30)
        self.update_interval = config.get('update_interval', 3600)

        # Initialize managers
        self.odds_manager = OddsManager(self.cache_manager, None)
        self.dynamic_resolver = DynamicTeamResolver()
        
        # Initialize background service with optimized settings
        self.background_service = get_background_service(self.cache_manager, max_workers=1)
        
        # Initialize modular components
        self.data_fetcher = OddsDataFetcher(
            self.cache_manager, 
            self.odds_manager, 
            self.background_service,
            self.dynamic_resolver,
            config
        )
        
        self.game_filter = GameFilter(config)
        
        self.odds_renderer = OddsRenderer(self.display_manager, config)

        # State
        self.current_games = []
        self.last_update = 0
        self.initialized = True

        # Register fonts
        self._register_fonts()

        # Log enabled leagues and their settings
        enabled_leagues = config.get('enabled_leagues', [])
        self.logger.info("Odds ticker plugin initialized")
        self.logger.info(f"Enabled leagues: {enabled_leagues}")

    def _register_fonts(self):
        """Register fonts with the font manager."""
        try:
            if not hasattr(self.plugin_manager, 'font_manager'):
                return

            font_manager = self.plugin_manager.font_manager

            # Team name font
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.team_name",
                family="press_start",
                size_px=10,
                color=(255, 255, 255)
            )

            # Odds font
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.odds",
                family="press_start",
                size_px=10,
                color=(255, 200, 0)
            )

            # Info font (time, channel)
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.info",
                family="four_by_six",
                size_px=6,
                color=(200, 200, 200)
            )

            self.logger.info("Odds ticker fonts registered")
        except Exception as e:
            self.logger.warning(f"Error registering fonts: {e}")

    def update(self) -> None:
        """Update odds data for all enabled leagues."""
        if not self.initialized:
            return

        current_time = time.time()
        if current_time - self.last_update < self.update_interval:
            self.logger.debug(f"Odds ticker update interval not reached. Next update in {self.update_interval - (current_time - self.last_update)} seconds")
            return

        try:
            self.logger.debug("Updating odds ticker data")
            
            # Fetch upcoming games using data fetcher
            all_games = self.data_fetcher.fetch_upcoming_games()
            
            # Filter games using game filter
            filtered_games = self.game_filter.filter_games(all_games)
            
            # Fetch odds for each game
            for game in filtered_games:
                league = game.get('league', '')
                odds_data = self.data_fetcher.fetch_game_odds(game, league)
                if odds_data:
                    game['odds'] = odds_data
            
            self.current_games = filtered_games
            self.last_update = current_time
            
            # Create ticker image
            self.odds_renderer.create_ticker_image(self.current_games)
            
            if self.current_games:
                self.logger.info(f"Updated odds ticker with {len(self.current_games)} games")
                for i, game in enumerate(self.current_games[:3]):  # Log first 3 games
                    home_team = game.get('home_team', 'HOME')
                    away_team = game.get('away_team', 'AWAY')
                    start_time = game.get('start_time', '')
                    self.logger.info(f"Game {i+1}: {away_team} @ {home_team} - {start_time}")
            else:
                self.logger.warning("No games found for odds ticker")

        except Exception as e:
            self.logger.error(f"Error updating odds ticker: {e}", exc_info=True)

    def display(self, display_mode: str = None, force_clear: bool = False) -> None:
        """
        Display scrolling odds ticker with full original functionality.

        Args:
            display_mode: Should be 'odds_ticker'
            force_clear: If True, clear display before rendering
        """
        if not self.initialized:
            self._display_error("Odds ticker plugin not initialized")
            return

        # Start display session with proper timing
        self.odds_renderer.start_display_session(force_clear)
        
        self.logger.debug("Entering display method")
        self.logger.debug(f"Odds ticker enabled: {self.enabled}")
        self.logger.debug(f"Current scroll position: {self.odds_renderer.scroll_position}")
        self.logger.debug(f"Ticker image width: {self.odds_renderer.ticker_image.width if self.odds_renderer.ticker_image else 'None'}")
        self.logger.debug(f"Dynamic duration: {self.odds_renderer.dynamic_duration}s")
        
        if not self.enabled:
            self.logger.debug("Odds ticker is disabled, exiting display method.")
            return
        
        self.logger.debug(f"Number of games in data at start of display method: {len(self.current_games)}")
        if not self.current_games:
            self.logger.warning("Odds ticker has no games data. Attempting to update...")
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
                        self.logger.error(f"Update failed: {result_data}")
                except queue.Empty:
                    self.logger.warning("Update timed out after 10 seconds, using fallback")
                
            except Exception as e:
                self.logger.error(f"Error during update: {e}")
            
            if not self.current_games:
                self.logger.warning("Still no games data after update. Displaying fallback message.")
                self.odds_renderer._display_fallback_message()
                return
        
        if self.odds_renderer.ticker_image is None:
            self.logger.warning("Ticker image is not available. Attempting to create it.")
            try:
                # Create the ticker image directly (no threading needed for this)
                ticker_img = self.odds_renderer.create_ticker_image(self.current_games)
                if ticker_img is None:
                    self.logger.error("Failed to create ticker image.")
                    self.odds_renderer._display_fallback_message()
                    return
                
            except Exception as e:
                self.logger.error(f"Error during image creation: {e}")
                self.odds_renderer._display_fallback_message()
                return

        # Display scrolling ticker using enhanced renderer
        success = self.odds_renderer.render_scrolling_ticker(self.odds_renderer.ticker_image)
        
        if not success and not self.odds_renderer.loop:
            # End of ticker reached
            self.logger.debug("Ticker display completed")

    def _display_no_odds(self):
        """Display message when no odds are available."""
        img = self.odds_renderer._create_no_data_image()
        self.display_manager.image = img.copy()
        self.display_manager.update_display()

    def _display_error(self, message: str):
        """Display error message."""
        img = self.odds_renderer._create_error_image(message)
        self.display_manager.image = img.copy()
        self.display_manager.update_display()

    def get_display_duration(self) -> float:
        """Get display duration from config."""
        return self.odds_renderer.get_display_duration()

    def get_info(self) -> Dict[str, Any]:
        """Return plugin info for web UI."""
        info = super().get_info()

        # Get filter stats
        filter_stats = self.game_filter.get_filter_stats()
        
        # Get background service status
        background_status = self.data_fetcher.get_background_service_status()

        info.update({
            'total_games': len(self.current_games),
            'enabled_leagues': self.config.get('enabled_leagues', []),
            'last_update': self.last_update,
            'display_duration': self.get_display_duration(),
            'scroll_speed': self.config.get('scroll_speed', 2),
            'show_favorite_teams_only': self.config.get('show_favorite_teams_only', False),
            'max_games_per_league': self.config.get('max_games_per_league', 5),
            'filter_stats': filter_stats,
            'background_service': background_status,
            'global_config': self.global_config
        })
        return info

    def cleanup(self) -> None:
        """Cleanup resources."""
        self.current_games = []
        self.odds_renderer.reset_scroll()
        self.logger.info("Odds ticker plugin cleaned up")
