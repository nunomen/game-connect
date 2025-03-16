import time
import random
from typing import Dict, Any, List, Optional

from game_framework import GameState, GameMode, Player


class TicTacToeGame(GameState):
    """A simple Tic-Tac-Toe game implementation."""
    
    def __init__(self):
        super().__init__(min_players=2, max_players=2, game_mode=GameMode.TURN_BASED)
        self.board = [[None, None, None], [None, None, None], [None, None, None]]
        self.player_symbols = {}  # player_id -> 'X' or 'O'
        self.turn_timeout = 30  # 30 seconds per turn
    
    def add_player(self, player_id: str) -> None:
        """Add a new player to the game."""
        if player_id in self.player_symbols:
            return
        
        # Assign X to first player, O to second
        symbol = 'X' if len(self.player_symbols) == 0 else 'O'
        self.player_symbols[player_id] = symbol
    
    def remove_player(self, player_id: str) -> None:
        """Remove a player from the game."""
        if player_id in self.player_symbols:
            del self.player_symbols[player_id]
    
    def update(self, players: Dict[str, Player], delta_time: float) -> None:
        """Update game state - for turn-based games, this mostly checks for game end conditions."""
        # Check for a winner
        winner = self._check_winner()
        if winner:
            # Find player with this symbol
            for player_id, symbol in self.player_symbols.items():
                if symbol == winner:
                    self.end_game(player_id)
                    break
        
        # Check for a draw
        elif self._is_board_full():
            self.end_game()  # No winner means draw
    
    def _check_winner(self):
        """Check if there's a winner on the board."""
        # Check rows
        for row in self.board:
            if row[0] and row[0] == row[1] == row[2]:
                return row[0]
        
        # Check columns
        for col in range(3):
            if self.board[0][col] and self.board[0][col] == self.board[1][col] == self.board[2][col]:
                return self.board[0][col]
        
        # Check diagonals
        if self.board[0][0] and self.board[0][0] == self.board[1][1] == self.board[2][2]:
            return self.board[0][0]
        
        if self.board[0][2] and self.board[0][2] == self.board[1][1] == self.board[2][0]:
            return self.board[0][2]
        
        return None
    
    def _is_board_full(self):
        """Check if the board is full (draw)."""
        for row in self.board:
            if None in row:
                return False
        return True
    
    def handle_move(self, player_id: str, move_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process a move from a player."""
        # Validate that it's the player's turn
        if not self.is_player_turn(player_id):
            return {"valid": False, "reason": "Not your turn"}
        
        # Get move coordinates
        row = move_data.get("row")
        col = move_data.get("col")
        
        # Validate coordinates
        if row is None or col is None or not (0 <= row < 3 and 0 <= col < 3):
            return {"valid": False, "reason": "Invalid move coordinates"}
        
        # Check if the cell is empty
        if self.board[row][col] is not None:
            return {"valid": False, "reason": "Cell already occupied"}
        
        # Make the move
        symbol = self.player_symbols[player_id]
        self.board[row][col] = symbol
        
        return {
            "valid": True,
            "row": row,
            "col": col,
            "symbol": symbol
        }
    
    def get_state_for_player(self, player_id: str) -> Dict[str, Any]:
        """Get the game state to send to a specific player."""
        return {
            "board": self.board,
            "your_symbol": self.player_symbols.get(player_id),
            "player_symbols": self.player_symbols,
            "game_started": self.game_started,
            "game_over": self.game_over,
            "winner": self.winner
        }


class MultiplayerRaceGame(GameState):
    """A simple multiplayer racing game."""
    
    def __init__(self):
        super().__init__(min_players=1, max_players=8, game_mode=GameMode.REAL_TIME)
        self.track_length = 1000  # Units to finish line
        self.positions = {}  # player_id -> position
        self.velocities = {}  # player_id -> velocity
        self.boost_cooldowns = {}  # player_id -> cooldown time
        self.finished = {}  # player_id -> finish time
        self.race_start_time = 0
        self.race_countdown = 3  # Seconds before race starts
        self.countdown_started = False
        self.max_speed = 200
        self.acceleration = 100
        self.boost_multiplier = 2.0
        self.boost_duration = 1.0
        self.boost_cooldown = 5.0
    
    def add_player(self, player_id: str) -> None:
        """Add a new player to the race."""
        self.positions[player_id] = 0
        self.velocities[player_id] = 0
        self.boost_cooldowns[player_id] = 0
        self.finished[player_id] = None
    
    def remove_player(self, player_id: str) -> None:
        """Remove a player from the race."""
        if player_id in self.positions:
            del self.positions[player_id]
        if player_id in self.velocities:
            del self.velocities[player_id]
        if player_id in self.boost_cooldowns:
            del self.boost_cooldowns[player_id]
        if player_id in self.finished:
            del self.finished[player_id]
    
    def start_game(self, players: Dict[str, Player]) -> None:
        """Start the race with a countdown."""
        super().start_game(players)
        self.countdown_started = True
        self.race_start_time = time.time() + self.race_countdown
        
        # Reset all players to starting position
        for player_id in players:
            self.positions[player_id] = 0
            self.velocities[player_id] = 0
            self.boost_cooldowns[player_id] = 0
            self.finished[player_id] = None
    
    def update(self, players: Dict[str, Player], delta_time: float) -> None:
        """Update race progress based on player inputs."""
        current_time = time.time()
        
        # Check if countdown is still going
        if self.countdown_started and current_time < self.race_start_time:
            # Don't update race positions during countdown
            return
        elif self.countdown_started:
            # Countdown just finished
            self.countdown_started = False
        
        # Check if all players have finished
        active_players = [pid for pid, finish_time in self.finished.items() if finish_time is None]
        if not active_players and self.game_started and not self.game_over:
            # Race is finished, determine winner
            finished_players = [(pid, t) for pid, t in self.finished.items() if t is not None]
            if finished_players:
                # Winner is player with lowest finish time
                winner_id = min(finished_players, key=lambda x: x[1])[0]
                self.end_game(winner_id)
            else:
                # No one finished
                self.end_game()
            return
        
        # Update each player's position
        for player_id, player in players.items():
            if player_id not in self.positions or self.finished[player_id] is not None:
                continue
            
            # Get current position and velocity
            position = self.positions[player_id]
            velocity = self.velocities[player_id]
            
            # Apply acceleration based on input
            accel = 0
            if 'w' in player.active_keys or 'ArrowUp' in player.active_keys:
                accel += self.acceleration
            if 's' in player.active_keys or 'ArrowDown' in player.active_keys:
                accel -= self.acceleration * 0.5  # Braking is half as effective
            
            # Apply boost if requested and available
            boost_active = False
            if ' ' in player.active_keys and self.boost_cooldowns[player_id] <= 0:
                boost_active = True
                self.boost_cooldowns[player_id] = self.boost_cooldown
            
            # Apply boost multiplier
            if boost_active:
                accel *= self.boost_multiplier
            
            # Update boost cooldown
            self.boost_cooldowns[player_id] = max(0, self.boost_cooldowns[player_id] - delta_time)
            
            # Apply acceleration and limit speed
            velocity += accel * delta_time
            velocity = max(0, min(self.max_speed, velocity))  # Clamp between 0 and max_speed
            
            # Apply velocity to position
            position += velocity * delta_time
            
            # Check if player has finished
            if position >= self.track_length and self.finished[player_id] is None:
                self.finished[player_id] = current_time - self.race_start_time
                print(f"Player {player_id} finished in {self.finished[player_id]:.2f} seconds")
            
            # Update state
            self.positions[player_id] = position
            self.velocities[player_id] = velocity
    
    def get_state_for_player(self, player_id: str) -> Dict[str, Any]:
        """Get the race state to send to a specific player."""
        current_time = time.time()
        countdown = max(0, self.race_start_time - current_time) if self.countdown_started else 0
        
        return {
            "positions": self.positions,
            "velocities": self.velocities,
            "boost_cooldowns": self.boost_cooldowns,
            "finished": self.finished,
            "track_length": self.track_length,
            "your_position": self.positions.get(player_id),
            "your_velocity": self.velocities.get(player_id),
            "your_boost_cooldown": self.boost_cooldowns.get(player_id),
            "your_finished": self.finished.get(player_id),
            "countdown": countdown,
            "race_time": current_time - self.race_start_time if self.game_started and not self.countdown_started else 0,
            "game_started": self.game_started,
            "game_over": self.game_over,
            "winner": self.winner
        }