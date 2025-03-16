import time
import random
from typing import Dict, List, Set, Any, Optional, Tuple
from abc import ABC, abstractmethod
from enum import Enum


class GameMode(Enum):
    """Enum for different game modes."""
    REAL_TIME = "real_time"
    TURN_BASED = "turn_based"


class Player:
    """Represents a connected player in the game."""
    
    def __init__(self, player_id: str, connection_id: int, stream_id: int):
        self.id = player_id
        self.connection_id = connection_id
        self.stream_id = stream_id
        self.active_keys: Set[str] = set()  # Currently pressed keys
        self.username = f"Player-{player_id[:6]}"
        self.connected = True
        self.last_activity = time.time()
        self.ready = False  # Used for game start synchronization
    
    def update_keys(self, keys: List[str]):
        """Update the set of active keys for this player."""
        self.active_keys = set(keys)
        self.last_activity = time.time()
    
    def mark_active(self):
        """Mark the player as active (to prevent timeout)."""
        self.last_activity = time.time()


class GameState(ABC):
    """Abstract base class for game states."""
    
    def __init__(self, min_players: int = 1, max_players: int = 0, game_mode: GameMode = GameMode.REAL_TIME):
        """Initialize the game state.
        
        Args:
            min_players: Minimum number of players required to start the game
            max_players: Maximum number of players (0 for unlimited)
            game_mode: Whether the game is real-time or turn-based
        """
        self.min_players = min_players
        self.max_players = max_players
        self.game_mode = game_mode
        self.game_started = False
        self.game_over = False
        self.winner = None
        self.current_turn = None  # For turn-based games
        self.turn_order = []  # For turn-based games
        self.turn_timeout = 60  # Seconds before turn auto-advances
        self.last_turn_change = 0  # Timestamp of last turn change
    
    @abstractmethod
    def update(self, players: Dict[str, Player], delta_time: float) -> None:
        """Update the game state based on player inputs and time passed."""
        pass
    
    @abstractmethod
    def get_state_for_player(self, player_id: str) -> Dict[str, Any]:
        """Get the game state to send to a specific player."""
        pass
    
    @abstractmethod
    def add_player(self, player_id: str) -> None:
        """Add a new player to the game."""
        pass
    
    @abstractmethod
    def remove_player(self, player_id: str) -> None:
        """Remove a player from the game."""
        pass
    
    def can_start_game(self, player_count: int) -> bool:
        """Check if the game can start with the current number of players."""
        if self.game_started:
            return False
        
        if player_count < self.min_players:
            return False
        
        if self.max_players > 0 and player_count > self.max_players:
            return False
        
        return True
    
    def start_game(self, players: Dict[str, Player]) -> None:
        """Start the game with the given players."""
        self.game_started = True
        self.game_over = False
        self.winner = None
        
        # For turn-based games, initialize the turn order
        if self.game_mode == GameMode.TURN_BASED:
            self.turn_order = list(players.keys())
            random.shuffle(self.turn_order)
            self.current_turn = 0
            self.last_turn_change = time.time()
    
    def end_game(self, winner: Optional[str] = None) -> None:
        """End the game with an optional winner."""
        self.game_started = False
        self.game_over = True
        self.winner = winner
    
    def advance_turn(self) -> str:
        """Advance to the next player's turn and return the new current player ID."""
        if self.game_mode != GameMode.TURN_BASED or not self.turn_order:
            return None
        
        self.current_turn = (self.current_turn + 1) % len(self.turn_order)
        self.last_turn_change = time.time()
        return self.turn_order[self.current_turn]
    
    def get_current_player_id(self) -> Optional[str]:
        """Get the ID of the player whose turn it currently is."""
        if self.game_mode != GameMode.TURN_BASED or not self.turn_order:
            return None
        
        return self.turn_order[self.current_turn]
    
    def is_player_turn(self, player_id: str) -> bool:
        """Check if it's the specified player's turn."""
        if self.game_mode != GameMode.TURN_BASED:
            return True  # In real-time games, it's always everyone's "turn"
        
        return self.get_current_player_id() == player_id
    
    def handle_move(self, player_id: str, move_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process a move from a player in a turn-based game.
        
        Returns:
            A dictionary with at least a 'valid' key indicating if the move was valid,
            and optionally other information about the move.
        """
        # Default implementation just checks if it's the player's turn
        if not self.is_player_turn(player_id):
            return {"valid": False, "reason": "Not your turn"}
        
        return {"valid": True}
    
    def check_turn_timeout(self) -> bool:
        """Check if the current turn has timed out.
        
        Returns:
            True if the turn was advanced due to timeout, False otherwise.
        """
        if (self.game_mode != GameMode.TURN_BASED or 
            not self.game_started or 
            self.game_over or 
            not self.turn_order):
            return False
        
        current_time = time.time()
        if current_time - self.last_turn_change > self.turn_timeout:
            # Turn has timed out, advance to the next player
            self.advance_turn()
            return True
        
        return False