# QUIC Game Server Framework

A general-purpose game server framework that supports both turn-based and real-time multiplayer games. Uses the QUIC protocol for fast, secure, and reliable networking.

## Features

- Supports any number of players (1-N)
- Handles both turn-based and real-time games
- Built on QUIC for low-latency networking
- Lobby system with matchmaking
- Chat functionality
- Client-server architecture to prevent cheating

## Requirements

- Python 3.7+
- aioquic
- pygame
- SSL certificate (self-generated for testing)

## Installation

```bash
pip install aioquic pygame
```

## File Structure

- `game_framework.py` - Core framework classes
- `game_examples.py` - Example game implementations
- `game_server.py` - Server implementation
- `game_client.py` - Client implementation 

## Running the Server

1. Choose which game type to run:

```python
# In game_server.py
# Choose which game to run
game_class = TicTacToeGame  # Turn-based for 2 players
# OR
game_class = MultiplayerRaceGame  # Real-time for 1-8 players
```

2. Run the server:

```bash
python game_server.py
```

## Running the Client

```bash
python game_client.py
```

## Creating Your Own Games

To create your own game, extend the `GameState` abstract class:

```python
from game_framework import GameState, GameMode

class MyGame(GameState):
    def __init__(self):
        super().__init__(
            min_players=2,  # Minimum players required
            max_players=4,  # Maximum players allowed (0 for unlimited)
            game_mode=GameMode.TURN_BASED  # Or GameMode.REAL_TIME
        )
        # Initialize game state
        
    def add_player(self, player_id):
        # Add a player to the game
        pass
        
    def remove_player(self, player_id):
        # Remove a player from the game
        pass
        
    def update(self, players, delta_time):
        # Update game state based on player inputs
        pass
        
    def get_state_for_player(self, player_id):
        # Return relevant game state for a specific player
        pass
        
    # For turn-based games, you may want to override:
    def handle_move(self, player_id, move_data):
        # Process a player's move
        return {"valid": True}  # Or {"valid": False, "reason": "..."}
```

## Example Games

### Tic-Tac-Toe (Turn-Based)

A simple 3x3 grid game for 2 players. Players take turns placing X or O on the board.

### Multiplayer Race (Real-Time)

A racing game for 1-8 players. Use W/Up to accelerate, S/Down to brake, and Space to boost.

## Architecture

- Server maintains authoritative game state
- Clients send input to server
- Server processes input and updates game state
- Server sends updated state to clients
- Clients render the game state

## License

MIT