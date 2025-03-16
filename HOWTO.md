# How to Use the QUIC Game Framework

This guide explains how to use the framework to create and run multiplayer games.

## Getting Started

### Prerequisites

1. Install required packages:
   ```bash
   pip install aioquic pygame
   ```

2. SSL Certificate:
   - The framework includes a function to generate self-signed certificates for testing
   - For production, you'll want proper certificates

### Running the Example Games

1. Start the server:
   ```bash
   python game_server.py
   ```

2. Start one or more clients:
   ```bash
   python game_client.py
   ```

3. In the lobby, press "Ready" when you want to start the game

## Creating Your Own Game

### 1. Define Your Game State

Create a new Python file (e.g., `my_game.py`) and define your game:

```python
from game_framework import GameState, GameMode, Player

class MyCustomGame(GameState):
    def __init__(self):
        # For a 2-4 player turn-based game:
        super().__init__(
            min_players=2,
            max_players=4,
            game_mode=GameMode.TURN_BASED
        )
        
        # Initialize your game state
        self.my_game_data = {}
        
    def add_player(self, player_id):
        # Initialize player state
        self.my_game_data[player_id] = {
            "score": 0,
            "position": (0, 0)
        }
    
    def remove_player(self, player_id):
        # Clean up player data
        if player_id in self.my_game_data:
            del self.my_game_data[player_id]
    
    def update(self, players, delta_time):
        # For turn-based games, this might just check win conditions
        # For real-time games, update positions, physics, etc.
        
        for player_id, player in players.items():
            # Handle player input
            if 'w' in player.active_keys:
                # Move player up
                pass
    
    def get_state_for_player(self, player_id):
        # Return game state relevant to this player
        return {
            "your_data": self.my_game_data.get(player_id),
            "other_players": {
                pid: data for pid, data in self.my_game_data.items()
                if pid != player_id
            }
        }
    
    # For turn-based games only:
    def handle_move(self, player_id, move_data):
        # Validate and process a player's move
        if not self.is_player_turn(player_id):
            return {"valid": False, "reason": "Not your turn"}
            
        # Process the move...
        
        return {"valid": True, "result": "move_result"}
```

### 2. Update Server to Use Your Game

In `game_server.py`, import your game and use it:

```python
from my_game import MyCustomGame

# ...

if __name__ == "__main__":
    # Generate SSL certificate for QUIC
    cert_path, key_path = generate_ssl_cert()
    
    # Use your custom game
    game_class = MyCustomGame
    
    # Create and run server
    server = GameServer("127.0.0.1", 8888, game_class, cert_path, key_path)
    
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        print("Server shutting down...")
```

### 3. Customize the Client Rendering

Modify the `render_game` method in `game_client.py` to handle your game:

```python
def render_game(self):
    """Render the game state."""
    if self.is_turn_based:
        self.render_turn_based_game()
    else:
        self.render_real_time_game()
    
    # Add custom rendering for your specific game
    if "your_data" in self.game_state:
        # Render player-specific data
        your_data = self.game_state["your_data"]
        score = your_data.get("score", 0)
        
        text = self.font_medium.render(f"Score: {score}", True, self.colors["white"])
        self.screen.blit(text, (50, 50))
        
        # Render other players
        other_players = self.game_state.get("other_players", {})
        for player_id, data in other_players.items():
            # Render other players
            position = data.get("position", (0, 0))
            pygame.draw.circle(self.screen, self.colors["blue"], position, 10)
    
    # Render chat messages
    self.render_chat_messages()
```

## Advanced Features

### Custom Move Processing

For turn-based games, you can process complex moves:

```python
def handle_move(self, player_id, move_data):
    # Get the action type
    action = move_data.get("action")
    
    if action == "place_piece":
        # Place a piece on the board
        x = move_data.get("x")
        y = move_data.get("y")
        
        # Validate coordinates
        if not (0 <= x < board_width and 0 <= y < board_height):
            return {"valid": False, "reason": "Invalid coordinates"}
            
        # Check if space is empty
        if self.board[y][x] is not None:
            return {"valid": False, "reason": "Space already occupied"}
            
        # Place the piece
        self.board[y][x] = player_id
        
        return {"valid": True, "x": x, "y": y}
        
    elif action == "move_piece":
        # Move a piece
        # ...
    
    else:
        return {"valid": False, "reason": "Unknown action"}
```

### Game Flow Control

You can override these methods to customize game flow:

```python
def start_game(self, players):
    """Start the game with the given players."""
    super().start_game(players)
    
    # Deal cards, setup the board, etc.
    self._deal_initial_cards()
    
def end_game(self, winner=None):
    """End the game with an optional winner."""
    super().end_game(winner)
    
    # Calculate final scores, save statistics, etc.
    self._calculate_final_scores()
```

### Custom Turn Management

For turn-based games with special turn rules:

```python
def advance_turn(self):
    """Advance to the next player's turn."""
    # Skip players who are out of the game
    while True:
        self.current_turn = (self.current_turn + 1) % len(self.turn_order)
        player_id = self.turn_order[self.current_turn]
        
        if not self.players_eliminated.get(player_id, False):
            break
    
    self.last_turn_change = time.time()
    
    # Give the player a card at the start of their turn
    player_id = self.turn_order[self.current_turn]
    self._give_card_to_player(player_id)
    
    return player_id
```

## Performance Tips

1. **Optimize State Updates**: Only send necessary data to clients
2. **Delta Compression**: Send only changes to game state
3. **Update Frequency**: Adjust server tick rate based on game needs
4. **Player Zones**: Only send data about nearby players/objects

## Troubleshooting

- **Connection Issues**: Ensure certificates are properly generated
- **Game State Sync Problems**: Add logging to track state changes
- **Client Rendering Issues**: Use debug displays for game state