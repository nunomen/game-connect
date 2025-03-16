import asyncio
import json
import pygame
import sys
import ssl
import time
import random
from typing import Dict, Any, Set, Optional, List, Tuple

from aioquic.asyncio.client import connect
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import QuicEvent, StreamDataReceived
from aioquic.h3.connection import H3_ALPN


class ClientProtocol:
    """QUIC protocol handler for the game client."""
    
    def __init__(self, client):
        self.client = client
        self.stream_id = None
    
    def quic_event_received(self, event: QuicEvent, connection):
        """Handle QUIC events."""
        if isinstance(event, StreamDataReceived):
            # Process received data
            data = event.data
            if data:
                try:
                    message = json.loads(data.decode())
                    asyncio.create_task(self.client.handle_message(message))
                except json.JSONDecodeError:
                    print("Received invalid JSON from server")


class GameClient:
    """A client for connecting to the QUIC game server."""
    
    def __init__(self, host: str, port: int, verify_ssl: bool = False):
        self.host = host
        self.port = port
        self.verify_ssl = verify_ssl
        self.connection = None
        self.connected = False
        self.player_id = None
        self.username = "Player"
        self.game_state = {}
        self.active_keys: Set[str] = set()
        self.protocol = ClientProtocol(self)
        self.stream_id = None
        
        # Game-specific state
        self.game_mode = None
        self.is_turn_based = False
        self.is_my_turn = False
        self.current_player = None
        self.min_players = 1
        self.max_players = 0
        self.game_in_progress = False
        self.waiting_for_players = False
        self.ready = False
        self.lobby_players = []
        
        # Chat messages
        self.chat_messages = []
        self.max_chat_messages = 10
        
        # UI state
        self.ui_state = "connecting"  # connecting, lobby, game, game_over
        self.show_chat = False
        self.chat_input = ""
        self.chat_active = False
        
        # Initialize pygame
        pygame.init()
        self.screen_size = (800, 600)
        self.screen = pygame.display.set_mode(self.screen_size)
        pygame.display.set_caption("Game Client")
        self.clock = pygame.time.Clock()
        
        # Fonts
        self.font_small = pygame.font.SysFont(None, 24)
        self.font_medium = pygame.font.SysFont(None, 32)
        self.font_large = pygame.font.SysFont(None, 48)
        
        # Colors
        self.colors = {
            "black": (0, 0, 0),
            "white": (255, 255, 255),
            "gray": (128, 128, 128),
            "light_gray": (200, 200, 200),
            "dark_gray": (50, 50, 50),
            "red": (255, 0, 0),
            "green": (0, 255, 0),
            "blue": (0, 0, 255),
            "yellow": (255, 255, 0),
            "cyan": (0, 255, 255),
            "magenta": (255, 0, 255),
            "orange": (255, 165, 0),
            "purple": (128, 0, 128),
            "brown": (165, 42, 42),
            "pink": (255, 192, 203),
        }
        
        # Input handling for turn-based games
        self.selected_cell = None  # For games like Tic-Tac-Toe
        
        # Button definitions for UI
        self.buttons = []
    
    async def connect(self):
        """Connect to the game server using QUIC."""
        # Update UI state
        self.ui_state = "connecting"
        
        # Configure QUIC
        configuration = QuicConfiguration(
            alpn_protocols=H3_ALPN,
            is_client=True,
            verify_mode=ssl.CERT_NONE if not self.verify_ssl else ssl.CERT_REQUIRED,
        )
        
        try:
            # Connect to server
            self.connection, _ = await connect(
                self.host,
                self.port,
                configuration=configuration,
                create_protocol=lambda: self.protocol,
            )
            
            # Create a bidirectional stream
            self.stream_id = self.connection.get_next_available_stream_id()
            print(f"Connected to server, using stream ID: {self.stream_id}")
            
            # Send join message
            await self.send_message({
                "type": "join"
            })
            
            self.connected = True
            return True
            
        except Exception as e:
            print(f"Connection failed: {e}")
            self.ui_state = "connection_failed"
            return False
    
    async def send_message(self, message: Dict[str, Any]):
        """Send a message to the server."""
        if not self.connected or not self.connection:
            return
        
        try:
            # Add player_id to message if we have one
            if self.player_id and "player_id" not in message:
                message["player_id"] = self.player_id
            
            # Encode and send the message
            data = json.dumps(message).encode()
            self.connection.send_stream_data(self.stream_id, data)
        except Exception as e:
            print(f"Failed to send message: {e}")
            self.connected = False
    
    async def send_input(self):
        """Send the current active keys to the server."""
        # Don't send inputs if we're not in a game
        if self.ui_state != "game":
            return
        
        await self.send_message({
            "type": "input",
            "keys": list(self.active_keys)
        })
    
    async def set_username(self, username: str):
        """Set the player's username."""
        self.username = username
        await self.send_message({
            "type": "set_username",
            "username": username
        })
    
    async def set_ready(self, ready: bool = True):
        """Set the player's ready state."""
        self.ready = ready
        await self.send_message({
            "type": "ready"
        })
    
    async def send_move(self, move_data: Dict[str, Any]):
        """Send a move in a turn-based game."""
        if not self.is_turn_based or not self.is_my_turn:
            return
        
        await self.send_message({
            "type": "move",
            "move": move_data
        })
    
    async def send_chat(self, text: str):
        """Send a chat message."""
        if not text.strip():
            return
        
        await self.send_message({
            "type": "chat",
            "text": text
        })
    
    async def handle_message(self, message: Dict[str, Any]):
        """Handle a message from the server."""
        message_type = message.get("type")
        
        if message_type == "connection_established":
            self.player_id = message.get("player_id")
            self.game_mode = message.get("game_mode")
            self.is_turn_based = self.game_mode == "turn_based"
            self.min_players = message.get("min_players", 1)
            self.max_players = message.get("max_players", 0)
            self.game_in_progress = message.get("game_in_progress", False)
            self.waiting_for_players = message.get("waiting_for_players", False)
            
            print(f"Connection established! Player ID: {self.player_id}")
            print(f"Game mode: {self.game_mode}")
            
            # Update UI state
            self.ui_state = "lobby"
        
        elif message_type == "join_rejected":
            reason = message.get("reason", "Unknown reason")
            print(f"Join rejected: {reason}")
            self.ui_state = "join_rejected"
            self.connected = False
        
        elif message_type == "lobby_state":
            self.waiting_for_players = message.get("waiting_for_players", False)
            self.game_in_progress = message.get("game_in_progress", False)
            self.lobby_players = message.get("players", [])
        
        elif message_type == "game_starting":
            print("Game is starting!")
            self.ui_state = "game"
            self.game_in_progress = True
            self.waiting_for_players = False
        
        elif message_type == "game_state":
            self.game_state = message.get("state", {})
            
            # For turn-based games, update turn info
            if self.is_turn_based:
                self.current_player = message.get("current_player")
                self.is_my_turn = message.get("is_your_turn", False)
        
        elif message_type == "turn_change":
            self.current_player = message.get("player_id")
            self.is_my_turn = self.current_player == self.player_id
            reason = message.get("reason", "normal")
            
            print(f"Turn changed to {self.current_player}" + 
                  (f" (reason: {reason})" if reason != "normal" else ""))
        
        elif message_type == "move_result":
            result = message.get("result", {})
            valid = result.get("valid", False)
            
            if not valid:
                reason = result.get("reason", "Unknown reason")
                print(f"Invalid move: {reason}")
        
        elif message_type == "chat":
            player_id = message.get("player_id")
            username = message.get("username", player_id)
            text = message.get("text", "")
            
            self.chat_messages.append((username, text))
            if len(self.chat_messages) > self.max_chat_messages:
                self.chat_messages.pop(0)
            
            print(f"Chat: {username}: {text}")
        
        elif message_type == "game_over":
            self.ui_state = "game_over"
            self.game_in_progress = False
            
            winner = message.get("winner")
            reason = message.get("reason", "normal")
            
            if winner:
                # Find username for winner
                winner_username = winner
                for player in self.lobby_players:
                    if player.get("id") == winner:
                        winner_username = player.get("username", winner)
                        break
                
                print(f"Game over! Winner: {winner_username}")
            else:
                print(f"Game over! {reason}")
    
    async def process_events(self):
        """Process pygame events."""
        # Process mouse position for hover effects
        mouse_pos = pygame.mouse.get_pos()
        
        # Update buttons hover state
        for button in self.buttons:
            button["hovered"] = button["rect"].collidepoint(mouse_pos)
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            
            # Track key presses for game input
            elif event.type == pygame.KEYDOWN:
                # Chat input handling
                if self.chat_active:
                    if event.key == pygame.K_BACKSPACE:
                        self.chat_input = self.chat_input[:-1]
                    elif event.key == pygame.K_RETURN:
                        if self.chat_input:
                            await self.send_chat(self.chat_input)
                            self.chat_input = ""
                        self.chat_active = False
                    elif event.key == pygame.K_ESCAPE:
                        self.chat_active = False
                        self.chat_input = ""
                    else:
                        self.chat_input += event.unicode
                else:
                    # Toggle chat with Enter key
                    if event.key == pygame.K_RETURN:
                        self.chat_active = True
                    
                    # Regular game input
                    key_name = pygame.key.name(event.key)
                    self.active_keys.add(key_name)
                    await self.send_input()
            
            elif event.type == pygame.KEYUP:
                key_name = pygame.key.name(event.key)
                if key_name in self.active_keys:
                    self.active_keys.remove(key_name)
                await self.send_input()
            
            # Mouse handling
            elif event.type == pygame.MOUSEBUTTONDOWN:
                # Check button clicks
                for button in self.buttons:
                    if button["rect"].collidepoint(event.pos) and button.get("enabled", True):
                        if button["action"] == "ready":
                            await self.set_ready(not self.ready)
                        elif button["action"] == "username":
                            # Simple username generation
                            new_username = "Player" + str(random.randint(100, 999))
                            await self.set_username(new_username)
                        elif button["action"] == "reconnect":
                            await self.connect()
                        elif button["action"] == "quit":
                            return False
                
                # Handle game-specific clicks
                if self.ui_state == "game" and self.is_turn_based and self.is_my_turn:
                    # Example: Tic-Tac-Toe cell selection
                    if "board" in self.game_state:
                        board = self.game_state["board"]
                        board_size = len(board)
                        
                        # Calculate cell size and position
                        board_width = 300
                        cell_size = board_width / board_size
                        board_x = (self.screen_size[0] - board_width) / 2
                        board_y = (self.screen_size[1] - board_width) / 2
                        
                        # Determine which cell was clicked
                        x, y = event.pos
                        if (board_x <= x <= board_x + board_width and 
                            board_y <= y <= board_y + board_width):
                            col = int((x - board_x) / cell_size)
                            row = int((y - board_y) / cell_size)
                            
                            # Make sure cell is valid
                            if 0 <= row < board_size and 0 <= col < board_size:
                                # Check if cell is empty
                                if board[row][col] is None:
                                    # Send move to server
                                    await self.send_move({
                                        "row": row,
                                        "col": col
                                    })
                
                # Handle mouse position for real-time games
                if self.ui_state == "game" and not self.is_turn_based:
                    # Update mouse position for aiming, etc.
                    x, y = event.pos
                    self.active_keys.add("mousex")
                    self.active_keys.add("mousey")
                    self.active_keys["mousex"] = str(x)
                    self.active_keys["mousey"] = str(y)
                    await self.send_input()
            
            elif event.type == pygame.MOUSEBUTTONUP:
                pass
            
            elif event.type == pygame.MOUSEMOTION:
                # Update mouse position for real-time games
                if self.ui_state == "game" and not self.is_turn_based:
                    x, y = event.pos
                    self.active_keys["mousex"] = str(x)
                    self.active_keys["mousey"] = str(y)
                    await self.send_input()
        
        return True
    
    def update_ui_elements(self):
        """Update UI elements based on current state."""
        self.buttons = []
        
        if self.ui_state == "connecting":
            pass
        
        elif self.ui_state == "connection_failed" or self.ui_state == "join_rejected":
            # Add reconnect button
            reconnect_btn = {
                "rect": pygame.Rect(300, 350, 200, 50),
                "text": "Reconnect",
                "action": "reconnect",
                "hovered": False,
                "enabled": True
            }
            self.buttons.append(reconnect_btn)
            
            # Add quit button
            quit_btn = {
                "rect": pygame.Rect(300, 420, 200, 50),
                "text": "Quit",
                "action": "quit",
                "hovered": False,
                "enabled": True
            }
            self.buttons.append(quit_btn)
        
        elif self.ui_state == "lobby":
            # Add ready button
            ready_btn = {
                "rect": pygame.Rect(300, 350, 200, 50),
                "text": "Ready" if not self.ready else "Unready",
                "action": "ready",
                "hovered": False,
                "enabled": True,
                "color": self.colors["green"] if self.ready else self.colors["yellow"]
            }
            self.buttons.append(ready_btn)
            
            # Add username button
            username_btn = {
                "rect": pygame.Rect(300, 420, 200, 50),
                "text": "Change Username",
                "action": "username",
                "hovered": False,
                "enabled": True
            }
            self.buttons.append(username_btn)
        
        elif self.ui_state == "game_over":
            # Add reconnect button
            reconnect_btn = {
                "rect": pygame.Rect(300, 350, 200, 50),
                "text": "Play Again",
                "action": "reconnect",
                "hovered": False,
                "enabled": True
            }
            self.buttons.append(reconnect_btn)
            
            # Add quit button
            quit_btn = {
                "rect": pygame.Rect(300, 420, 200, 50),
                "text": "Quit",
                "action": "quit",
                "hovered": False,
                "enabled": True
            }
            self.buttons.append(quit_btn)
    
    def render(self):
        """Render the game state."""
        # Update UI elements
        self.update_ui_elements()
        
        # Clear the screen
        self.screen.fill(self.colors["dark_gray"])
        
        # Render based on UI state
        if self.ui_state == "connecting":
            self.render_connecting()
        elif self.ui_state == "connection_failed":
            self.render_connection_failed()
        elif self.ui_state == "join_rejected":
            self.render_join_rejected()
        elif self.ui_state == "lobby":
            self.render_lobby()
        elif self.ui_state == "game":
            self.render_game()
        elif self.ui_state == "game_over":
            self.render_game_over()
        
        # Render buttons
        for button in self.buttons:
            color = button.get("color", self.colors["blue"])
            if button["hovered"]:
                color = self.colors["cyan"] if button.get("enabled", True) else self.colors["gray"]
            elif not button.get("enabled", True):
                color = self.colors["gray"]
            
            pygame.draw.rect(self.screen, color, button["rect"])
            pygame.draw.rect(self.screen, self.colors["white"], button["rect"], 2)
            
            text = self.font_medium.render(button["text"], True, self.colors["white"])
            text_rect = text.get_rect(center=button["rect"].center)
            self.screen.blit(text, text_rect)
        
        # Always render connection status
        status = "Connected" if self.connected else "Disconnected"
        text = self.font_small.render(f"Status: {status}", True, self.colors["white"])
        self.screen.blit(text, (10, 10))
        
        # Always render player ID if available
        if self.player_id:
            text = self.font_small.render(f"Player ID: {self.player_id[:8]}...", True, self.colors["white"])
            self.screen.blit(text, (10, 30))
        
        # Always render chat if it's active
        if self.chat_active:
            self.render_chat_input()
        
        # Update the display
        pygame.display.flip()
    
    def render_connecting(self):
        """Render connecting screen."""
        text = self.font_large.render("Connecting to server...", True, self.colors["white"])
        text_rect = text.get_rect(center=(self.screen_size[0] // 2, self.screen_size[1] // 2))
        self.screen.blit(text, text_rect)
    
    def render_connection_failed(self):
        """Render connection failed screen."""
        text = self.font_large.render("Connection Failed", True, self.colors["red"])
        text_rect = text.get_rect(center=(self.screen_size[0] // 2, 200))
        self.screen.blit(text, text_rect)
        
        text = self.font_medium.render("Could not connect to the game server.", True, self.colors["white"])
        text_rect = text.get_rect(center=(self.screen_size[0] // 2, 250))
        self.screen.blit(text, text_rect)
    
    def render_join_rejected(self):
        """Render join rejected screen."""
        text = self.font_large.render("Join Rejected", True, self.colors["red"])
        text_rect = text.get_rect(center=(self.screen_size[0] // 2, 200))
        self.screen.blit(text, text_rect)
        
        text = self.font_medium.render("The game server rejected your join request.", True, self.colors["white"])
        text_rect = text.get_rect(center=(self.screen_size[0] // 2, 250))
        self.screen.blit(text, text_rect)
    
    def render_lobby(self):
        """Render lobby screen."""
        text = self.font_large.render("Game Lobby", True, self.colors["white"])
        text_rect = text.get_rect(center=(self.screen_size[0] // 2, 100))
        self.screen.blit(text, text_rect)
        
        # Render game mode
        mode_text = "Turn-Based" if self.is_turn_based else "Real-Time"
        text = self.font_medium.render(f"Game Mode: {mode_text}", True, self.colors["white"])
        text_rect = text.get_rect(center=(self.screen_size[0] // 2, 150))
        self.screen.blit(text, text_rect)
        
        # Render player count
        player_count = len(self.lobby_players) if self.lobby_players else 1
        max_text = str(self.max_players) if self.max_players > 0 else "∞"
        text = self.font_medium.render(f"Players: {player_count}/{max_text}", True, self.colors["white"])
        text_rect = text.get_rect(center=(self.screen_size[0] // 2, 180))
        self.screen.blit(text, text_rect)
        
        # Render waiting status
        if self.waiting_for_players:
            status_text = f"Waiting for more players... (need {self.min_players})"
            text = self.font_medium.render(status_text, True, self.colors["yellow"])
            text_rect = text.get_rect(center=(self.screen_size[0] // 2, 210))
            self.screen.blit(text, text_rect)
        elif self.game_in_progress:
            text = self.font_medium.render("Game in progress...", True, self.colors["green"])
            text_rect = text.get_rect(center=(self.screen_size[0] // 2, 210))
            self.screen.blit(text, text_rect)
        else:
            text = self.font_medium.render("Waiting for players to ready up...", True, self.colors["cyan"])
            text_rect = text.get_rect(center=(self.screen_size[0] // 2, 210))
            self.screen.blit(text, text_rect)
        
        # Render player list
        y_pos = 250
        text = self.font_medium.render("Players:", True, self.colors["white"])
        self.screen.blit(text, (300, y_pos))
        y_pos += 30
        
        for player in self.lobby_players:
            player_id = player.get("id", "")
            username = player.get("username", player_id)
            ready = player.get("ready", False)
            
            # Highlight current player
            color = self.colors["green"] if player_id == self.player_id else self.colors["white"]
            
            # Show ready status
            status = "[READY]" if ready else "[NOT READY]"
            status_color = self.colors["green"] if ready else self.colors["red"]
            
            text = self.font_small.render(username, True, color)
            self.screen.blit(text, (300, y_pos))
            
            text = self.font_small.render(status, True, status_color)
            self.screen.blit(text, (450, y_pos))
            
            y_pos += 25
    
    def render_game(self):
        """Render the game state."""
        # This will vary based on the specific game
        if self.is_turn_based:
            self.render_turn_based_game()
        else:
            self.render_real_time_game()
        
        # Render chat messages
        self.render_chat_messages()
    
    def render_turn_based_game(self):
        """Render a turn-based game."""
        # Example: Render a Tic-Tac-Toe board
        if "board" in self.game_state:
            board = self.game_state["board"]
            board_size = len(board)
            
            # Calculate board position and size
            board_width = 300
            cell_size = board_width / board_size
            board_x = (self.screen_size[0] - board_width) / 2
            board_y = (self.screen_size[1] - board_width) / 2
            
            # Draw board background
            pygame.draw.rect(self.screen, self.colors["light_gray"], 
                            (board_x, board_y, board_width, board_width))
            
            # Draw grid lines
            for i in range(1, board_size):
                # Horizontal lines
                pygame.draw.line(
                    self.screen, self.colors["black"],
                    (board_x, board_y + i * cell_size),
                    (board_x + board_width, board_y + i * cell_size),
                    2
                )
                # Vertical lines
                pygame.draw.line(
                    self.screen, self.colors["black"],
                    (board_x + i * cell_size, board_y),
                    (board_x + i * cell_size, board_y + board_width),
                    2
                )
            
            # Draw X's and O's
            for row in range(board_size):
                for col in range(board_size):
                    cell_value = board[row][col]
                    if cell_value:
                        cell_x = board_x + col * cell_size + cell_size / 2
                        cell_y = board_y + row * cell_size + cell_size / 2
                        
                        if cell_value == 'X':
                            # Draw X
                            color = self.colors["blue"]
                            margin = cell_size * 0.2
                            pygame.draw.line(
                                self.screen, color,
                                (cell_x - cell_size/2 + margin, cell_y - cell_size/2 + margin),
                                (cell_x + cell_size/2 - margin, cell_y + cell_size/2 - margin),
                                6
                            )
                            pygame.draw.line(
                                self.screen, color,
                                (cell_x + cell_size/2 - margin, cell_y - cell_size/2 + margin),
                                (cell_x - cell_size/2 + margin, cell_y + cell_size/2 - margin),
                                6
                            )
                        elif cell_value == 'O':
                            # Draw O
                            color = self.colors["red"]
                            margin = cell_size * 0.2
                            pygame.draw.circle(
                                self.screen, color,
                                (int(cell_x), int(cell_y)),
                                int(cell_size/2 - margin),
                                6
                            )
            
            # Draw turn indicator
            turn_text = "Your turn" if self.is_my_turn else "Opponent's turn"
            turn_color = self.colors["green"] if self.is_my_turn else self.colors["red"]
            text = self.font_medium.render(turn_text, True, turn_color)
            text_rect = text.get_rect(center=(self.screen_size[0] // 2, 50))
            self.screen.blit(text, text_rect)
            
            # Draw player symbols
            if "your_symbol" in self.game_state:
                symbol = self.game_state["your_symbol"]
                text = self.font_small.render(f"You are playing as: {symbol}", True, self.colors["white"])
                text_rect = text.get_rect(center=(self.screen_size[0] // 2, 80))
                self.screen.blit(text, text_rect)
    
    def render_real_time_game(self):
        """Render a real-time game."""
        # Example: Render a racing game
        if "track_length" in self.game_state:
            track_length = self.game_state["track_length"]
            positions = self.game_state.get("positions", {})
            
            # Draw track
            track_width = 600
            track_height = 80
            track_x = (self.screen_size[0] - track_width) / 2
            track_y = self.screen_size[1] - track_height - 50
            
            # Draw track background
            pygame.draw.rect(self.screen, self.colors["gray"], 
                            (track_x, track_y, track_width, track_height))
            
            # Draw finish line
            finish_x = track_x + track_width - 10
            pygame.draw.rect(self.screen, self.colors["white"],
                            (finish_x, track_y, 10, track_height))
            
            # Draw players on track
            for player_id, position in positions.items():
                # Calculate player position on track
                player_x = track_x + (position / track_length) * track_width
                player_y = track_y + track_height / 2
                
                # Choose color (green for current player)
                color = self.colors["green"] if player_id == self.player_id else self.colors["blue"]
                
                # Draw player
                pygame.draw.circle(self.screen, color, (int(player_x), int(player_y)), 15)
            
            # Draw countdown if active
            countdown = self.game_state.get("countdown", 0)
            if countdown > 0:
                text = self.font_large.render(f"{int(countdown) + 1}", True, self.colors["yellow"])
                text_rect = text.get_rect(center=(self.screen_size[0] // 2, self.screen_size[1] // 2))
                self.screen.blit(text, text_rect)
            
            # Draw race time
            race_time = self.game_state.get("race_time", 0)
            text = self.font_medium.render(f"Time: {race_time:.2f}s", True, self.colors["white"])
            self.screen.blit(text, (50, 50))
            
            # Draw position and speed
            your_position = self.game_state.get("your_position", 0)
            your_velocity = self.game_state.get("your_velocity", 0)
            
            progress = (your_position / track_length) * 100
            text = self.font_medium.render(f"Progress: {progress:.1f}%", True, self.colors["white"])
            self.screen.blit(text, (50, 80))
            
            text = self.font_medium.render(f"Speed: {your_velocity:.1f}", True, self.colors["white"])
            self.screen.blit(text, (50, 110))
            
            # Draw boost cooldown
            your_boost = self.game_state.get("your_boost_cooldown", 0)
            if your_boost > 0:
                text = self.font_medium.render(f"Boost: {your_boost:.1f}s", True, self.colors["red"])
            else:
                text = self.font_medium.render("Boost: READY", True, self.colors["green"])
            self.screen.blit(text, (50, 140))
            
            # Draw controls help
            text = self.font_small.render("Controls: W/Up = Accelerate, S/Down = Brake, Space = Boost", 
                                        True, self.colors["white"])
            text_rect = text.get_rect(center=(self.screen_size[0] // 2, 20))
            self.screen.blit(text, text_rect)
            
            # Draw finished players
            finished = self.game_state.get("finished", {})
            finished_players = [(pid, time) for pid, time in finished.items() if time is not None]
            finished_players.sort(key=lambda x: x[1])
            
            y_pos = 200
            text = self.font_medium.render("Finished Players:", True, self.colors["white"])
            self.screen.blit(text, (550, y_pos))
            y_pos += 30
            
            for player_id, finish_time in finished_players:
                color = self.colors["green"] if player_id == self.player_id else self.colors["white"]
                text = self.font_small.render(f"{player_id[:6]}: {finish_time:.2f}s", True, color)
                self.screen.blit(text, (550, y_pos))
                y_pos += 25
    
    def render_game_over(self):
        """Render game over screen."""
        text = self.font_large.render("Game Over", True, self.colors["white"])
        text_rect = text.get_rect(center=(self.screen_size[0] // 2, 150))
        self.screen.blit(text, text_rect)
        
        # Show winner if there is one
        winner = self.game_state.get("winner")
        if winner:
            winner_text = "You won!" if winner == self.player_id else "You lost!"
            color = self.colors["green"] if winner == self.player_id else self.colors["red"]
            
            text = self.font_large.render(winner_text, True, color)
            text_rect = text.get_rect(center=(self.screen_size[0] // 2, 220))
            self.screen.blit(text, text_rect)
        else:
            text = self.font_large.render("It's a draw!", True, self.colors["yellow"])
            text_rect = text.get_rect(center=(self.screen_size[0] // 2, 220))
            self.screen.blit(text, text_rect)
    
    def render_chat_messages(self):
        """Render chat messages."""
        # Draw chat background
        chat_height = 150
        chat_y = self.screen_size[1] - chat_height - 10
        pygame.draw.rect(self.screen, self.colors["black"], 
                        (10, chat_y, 300, chat_height), 0, 5)
        pygame.draw.rect(self.screen, self.colors["white"], 
                        (10, chat_y, 300, chat_height), 1, 5)
        
        # Draw chat messages
        y_pos = chat_y + 10
        for username, text in self.chat_messages:
            name_text = self.font_small.render(f"{username}:", True, self.colors["cyan"])
            self.screen.blit(name_text, (15, y_pos))
            
            msg_text = self.font_small.render(text, True, self.colors["white"])
            self.screen.blit(msg_text, (15 + name_text.get_width() + 5, y_pos))
            
            y_pos += 20
            
            # Wrap long messages
            if len(text) > 35:
                continuation = text[35:]
                wrap_text = self.font_small.render(continuation, True, self.colors["white"])
                self.screen.blit(wrap_text, (15, y_pos))
                y_pos += 20
    
    def render_chat_input(self):
        """Render chat input box."""
        # Draw input background
        input_height = 30
        input_y = self.screen_size[1] - input_height - 15
        pygame.draw.rect(self.screen, self.colors["black"], 
                        (10, input_y, 400, input_height), 0, 5)
        pygame.draw.rect(self.screen, self.colors["white"], 
                        (10, input_y, 400, input_height), 1, 5)
        
        # Draw input text
        input_text = self.font_small.render(self.chat_input, True, self.colors["white"])
        self.screen.blit(input_text, (15, input_y + 5))
        
        # Draw cursor
        if int(pygame.time.get_ticks() / 500) % 2 == 0:
            cursor_x = 15 + input_text.get_width()
            pygame.draw.line(self.screen, self.colors["white"],
                            (cursor_x, input_y + 5),
                            (cursor_x, input_y + 25), 2)
        
        # Draw hint
        hint_text = self.font_small.render("Press Enter to send, Esc to cancel", True, self.colors["gray"])
        self.screen.blit(hint_text, (15, input_y - 20))
    
    async def run(self):
        """Run the game client."""
        if not await self.connect():
            print("Failed to connect to the server.")
            
            # Keep rendering the connection failed screen until quit
            running = True
            while running:
                running = await self.process_events()
                self.render()
                self.clock.tick(60)
                await asyncio.sleep(0)
            
            return
        
        running = True
        while running:
            # Process events
            running = await self.process_events()
            
            # Render the game
            self.render()
            
            # Cap the frame rate
            self.clock.tick(60)
            
            # Yield to allow other async tasks to run
            await asyncio.sleep(0)
        
        # Clean up
        pygame.quit()
            
        if self.connection:
            await self.connection.close()


if __name__ == "__main__":
    # Create and run client
    client = GameClient("127.0.0.1", 8888)
    
    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        print("Client shutting down...")
    finally:
        pygame.quit()
        sys.exit()