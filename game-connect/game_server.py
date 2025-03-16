import asyncio
import json
import uuid
import os
import ssl
import time
from typing import Dict, List, Set, Any, Optional, Tuple, Callable

from aioquic.asyncio import serve
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import QuicEvent, StreamDataReceived, ConnectionTerminated
from aioquic.h3.connection import H3_ALPN
from aioquic.quic.logger import QuicFileLogger

from game_framework import GameState, Player


class GameProtocol:
    """QUIC protocol handler for the game server."""
    
    def __init__(self, game_server):
        self.game_server = game_server
        self.connections = {}  # connection_id -> QuicConnection
    
    def connection_made(self, connection):
        """Called when a new connection is established."""
        connection_id = id(connection)
        self.connections[connection_id] = connection
        print(f"New connection established: {connection_id}")
    
    def connection_lost(self, connection):
        """Called when a connection is lost."""
        connection_id = id(connection)
        if connection_id in self.connections:
            del self.connections[connection_id]
            
            # Remove all players associated with this connection
            players_to_remove = []
            for player_id, player in self.game_server.players.items():
                if player.connection_id == connection_id:
                    players_to_remove.append(player_id)
            
            for player_id in players_to_remove:
                self.game_server.remove_player(player_id)
            
            print(f"Connection lost: {connection_id}, removed {len(players_to_remove)} players")
    
    def quic_event_received(self, event: QuicEvent, connection):
        """Handle QUIC events."""
        connection_id = id(connection)
        
        if isinstance(event, StreamDataReceived):
            # Process received data
            data = event.data
            if data:
                try:
                    message = json.loads(data.decode())
                    asyncio.create_task(
                        self.game_server.handle_message(
                            connection_id, event.stream_id, message
                        )
                    )
                except json.JSONDecodeError:
                    print(f"Received invalid JSON from connection {connection_id}")
        
        elif isinstance(event, ConnectionTerminated):
            print(f"Connection terminated: {connection_id}, reason: {event.error_code}")
            self.connection_lost(connection)


class GameServer:
    """General-purpose game server using QUIC for communication."""
    
    def __init__(self, host: str, port: int, game_state_class, cert_path: str, key_path: str):
        self.host = host
        self.port = port
        self.players: Dict[str, Player] = {}
        self.game_state = game_state_class()
        self.running = False
        self.last_update_time = 0.0
        self.tick_rate = 60  # Updates per second
        
        # Player management
        self.connection_to_players = {}  # connection_id -> set of player_ids
        self.player_timeout = 60  # Seconds before disconnecting inactive players
        
        # Room management (for lobbying/matchmaking)
        self.waiting_for_players = False
        self.game_in_progress = False
        self.lobby_broadcast_interval = 5.0  # Seconds between lobby state broadcasts
        self.last_lobby_broadcast = 0.0
        
        # SSL certificate for QUIC
        self.cert_path = cert_path
        self.key_path = key_path
        
        # Create protocol handler
        self.protocol = GameProtocol(self)
    
    async def start(self):
        """Start the game server."""
        # Configure QUIC
        configuration = QuicConfiguration(
            alpn_protocols=H3_ALPN,
            is_client=False,
            max_datagram_frame_size=65536,
        )
        
        # Set up logging
        configuration.quic_logger = QuicFileLogger("quic-log")
        
        # Load SSL certificates
        configuration.load_cert_chain(self.cert_path, self.key_path)
        
        self.running = True
        print(f"Starting server on {self.host}:{self.port}")
        print(f"Game mode: {self.game_state.game_mode.value}")
        print(f"Min players: {self.game_state.min_players}, Max players: {self.game_state.max_players or 'unlimited'}")
        
        # Start the game loop
        asyncio.create_task(self.game_loop())
        
        # Start QUIC server
        await serve(
            self.host,
            self.port,
            configuration=configuration,
            create_protocol=lambda: self.protocol,
        )
    
    async def handle_message(self, connection_id: int, stream_id: int, message: Dict[str, Any]):
        """Handle a message from a client."""
        message_type = message.get("type")
        
        if message_type == "join":
            # Create a new player
            player_id = str(uuid.uuid4())
            player = Player(player_id, connection_id, stream_id)
            
            # Add the player to our dictionary
            self.players[player_id] = player
            
            # Check if we can add them to the game
            if not self.game_in_progress and (
                self.game_state.max_players == 0 or 
                len(self.players) <= self.game_state.max_players
            ):
                # Add the player to the game state
                self.game_state.add_player(player_id)
                
                # Track which players belong to which connection
                if connection_id not in self.connection_to_players:
                    self.connection_to_players[connection_id] = set()
                self.connection_to_players[connection_id].add(player_id)
                
                # Send player their ID and game info
                await self.send_message_to_player(player, {
                    "type": "connection_established",
                    "player_id": player_id,
                    "game_mode": self.game_state.game_mode.value,
                    "min_players": self.game_state.min_players,
                    "max_players": self.game_state.max_players,
                    "game_in_progress": self.game_in_progress,
                    "waiting_for_players": self.waiting_for_players,
                    "player_count": len(self.players)
                })
                
                print(f"New player joined: {player_id}")
                
                # Check if we have enough players to start the game
                await self.check_game_start()
            else:
                # Game is full or in progress, reject player
                await self.send_message_to_connection(connection_id, stream_id, {
                    "type": "join_rejected",
                    "reason": "Game is full or already in progress"
                })
                # Clean up player 
                del self.players[player_id]
                
        elif message_type == "input":
            # Update player's active keys
            player_id = message.get("player_id")
            keys = message.get("keys", [])
            
            if player_id in self.players:
                self.players[player_id].update_keys(keys)
        
        elif message_type == "set_username":
            # Set the player's username
            player_id = message.get("player_id")
            username = message.get("username", "")
            
            if player_id in self.players and username:
                self.players[player_id].username = username
                print(f"Player {player_id} set username to {username}")
        
        elif message_type == "ready":
            # Player is ready to start the game
            player_id = message.get("player_id")
            if player_id in self.players:
                self.players[player_id].ready = True
                self.players[player_id].mark_active()
                print(f"Player {player_id} is ready")
                
                # Check if all players are ready to start
                await self.check_game_start()
        
        elif message_type == "move":
            # Process a move in a turn-based game
            player_id = message.get("player_id")
            move_data = message.get("move", {})
            
            if player_id in self.players and self.game_state.game_mode.value == "turn_based":
                self.players[player_id].mark_active()
                
                # Validate and process the move
                result = self.game_state.handle_move(player_id, move_data)
                
                # Send move result to the player
                await self.send_message_to_player(self.players[player_id], {
                    "type": "move_result",
                    "result": result
                })
                
                # If move was valid, advance the turn
                if result.get("valid", False):
                    next_player = self.game_state.advance_turn()
                    
                    # Notify all players of the turn change
                    await self.broadcast_message({
                        "type": "turn_change",
                        "player_id": next_player
                    })
        
        elif message_type == "chat":
            # Handle chat messages
            player_id = message.get("player_id")
            text = message.get("text", "")
            
            if player_id in self.players and text:
                self.players[player_id].mark_active()
                
                # Broadcast chat message to all players
                await self.broadcast_message({
                    "type": "chat",
                    "player_id": player_id,
                    "username": self.players[player_id].username,
                    "text": text
                })
    
    async def send_message_to_player(self, player: Player, message: Dict[str, Any]):
        """Send a message to a specific player."""
        await self.send_message_to_connection(player.connection_id, player.stream_id, message)
    
    async def send_message_to_connection(self, connection_id: int, stream_id: int, message: Dict[str, Any]):
        """Send a message to a specific connection and stream."""
        if connection_id not in self.protocol.connections:
            print(f"Cannot send message: connection {connection_id} not found")
            return
        
        connection = self.protocol.connections[connection_id]
        
        # Encode and send the message
        data = json.dumps(message).encode()
        connection.send_stream_data(stream_id, data)
    
    async def broadcast_message(self, message: Dict[str, Any]):
        """Send a message to all connected players."""
        tasks = []
        for player_id, player in self.players.items():
            if player.connected:
                tasks.append(self.send_message_to_player(player, message))
        
        if tasks:
            await asyncio.gather(*tasks)
    
    async def check_game_start(self):
        """Check if we can start the game with the current players."""
        if self.game_in_progress:
            return
        
        player_count = len(self.players)
        
        # If we don't have minimum players yet
        if player_count < self.game_state.min_players:
            self.waiting_for_players = True
            return
        
        # Check if all players are ready
        all_ready = all(player.ready for player in self.players.values())
        
        if all_ready and self.game_state.can_start_game(player_count):
            # Start the game
            self.game_in_progress = True
            self.waiting_for_players = False
            self.game_state.start_game(self.players)
            
            # Notify all players that the game is starting
            await self.broadcast_message({
                "type": "game_starting",
                "player_count": player_count
            })
            
            # For turn-based games, notify who goes first
            if self.game_state.game_mode.value == "turn_based":
                current_player = self.game_state.get_current_player_id()
                await self.broadcast_message({
                    "type": "turn_change",
                    "player_id": current_player
                })
            
            print(f"Game started with {player_count} players")
    
    def remove_player(self, player_id: str):
        """Remove a player from the game."""
        if player_id in self.players:
            player = self.players[player_id]
            
            # Remove from connection tracking
            connection_id = player.connection_id
            if connection_id in self.connection_to_players:
                self.connection_to_players[connection_id].discard(player_id)
                if not self.connection_to_players[connection_id]:
                    del self.connection_to_players[connection_id]
            
            # Remove from players dictionary and game state
            del self.players[player_id]
            self.game_state.remove_player(player_id)
            
            print(f"Player removed: {player_id}")
            
            # If this was the current player in a turn-based game, advance the turn
            if (self.game_state.game_mode.value == "turn_based" and 
                self.game_state.game_started and 
                not self.game_state.game_over and 
                self.game_state.get_current_player_id() == player_id):
                
                # Remove the player from the turn order
                if player_id in self.game_state.turn_order:
                    idx = self.game_state.turn_order.index(player_id)
                    self.game_state.turn_order.pop(idx)
                    if idx <= self.game_state.current_turn and self.game_state.current_turn > 0:
                        self.game_state.current_turn -= 1
                
                # Advance the turn if there are players left
                if self.game_state.turn_order:
                    next_player = self.game_state.get_current_player_id()
                    asyncio.create_task(self.broadcast_message({
                        "type": "turn_change",
                        "player_id": next_player,
                        "reason": "previous_player_disconnected"
                    }))
                else:
                    # End the game if no players are left
                    self.game_state.end_game()
                    self.game_in_progress = False
                    asyncio.create_task(self.broadcast_message({
                        "type": "game_over",
                        "reason": "all_players_disconnected"
                    }))
    
    async def check_inactive_players(self):
        """Check for inactive players and disconnect them."""
        current_time = time.time()
        inactive_players = []
        
        for player_id, player in self.players.items():
            if current_time - player.last_activity > self.player_timeout:
                inactive_players.append(player_id)
        
        for player_id in inactive_players:
            print(f"Player {player_id} timed out due to inactivity")
            self.remove_player(player_id)
    
    async def send_lobby_state(self):
        """Send lobby state to all players."""
        await self.broadcast_message({
            "type": "lobby_state",
            "player_count": len(self.players),
            "min_players": self.game_state.min_players,
            "max_players": self.game_state.max_players,
            "waiting_for_players": self.waiting_for_players,
            "game_in_progress": self.game_in_progress,
            "players": [
                {
                    "id": p_id,
                    "username": player.username,
                    "ready": player.ready,
                }
                for p_id, player in self.players.items()
            ]
        })
    
    async def game_loop(self):
        """Main game loop that updates the game state and sends updates to clients."""
        self.last_update_time = asyncio.get_event_loop().time()
        self.last_lobby_broadcast = self.last_update_time
        
        while self.running:
            current_time = asyncio.get_event_loop().time()
            delta_time = current_time - self.last_update_time
            self.last_update_time = current_time
            
            # Check for inactive players
            await self.check_inactive_players()
            
            # Update game state if game is in progress
            if self.game_in_progress and not self.game_state.game_over:
                # For turn-based games, check if the current turn has timed out
                if self.game_state.game_mode.value == "turn_based":
                    if self.game_state.check_turn_timeout():
                        # Turn timed out, notify players
                        current_player = self.game_state.get_current_player_id()
                        await self.broadcast_message({
                            "type": "turn_change",
                            "player_id": current_player,
                            "reason": "timeout"
                        })
                
                # Update the game state
                self.game_state.update(self.players, delta_time)
                
                # Check if game has ended
                if self.game_state.game_over:
                    self.game_in_progress = False
                    await self.broadcast_message({
                        "type": "game_over",
                        "winner": self.game_state.winner
                    })
                    
                    # Reset player ready states
                    for player in self.players.values():
                        player.ready = False
                else:
                    # Send game state to all players
                    tasks = []
                    for player_id, player in self.players.items():
                        if player.connected:
                            state_for_player = self.game_state.get_state_for_player(player_id)
                            message = {
                                "type": "game_state",
                                "state": state_for_player
                            }
                            
                            # For turn-based games, include whose turn it is
                            if self.game_state.game_mode.value == "turn_based":
                                message["current_player"] = self.game_state.get_current_player_id()
                                message["is_your_turn"] = self.game_state.is_player_turn(player_id)
                            
                            tasks.append(self.send_message_to_player(player, message))
                    
                    if tasks:
                        await asyncio.gather(*tasks)
            elif not self.game_in_progress and self.waiting_for_players:
                # Send lobby state updates periodically
                if current_time - self.last_lobby_broadcast > self.lobby_broadcast_interval:
                    await self.send_lobby_state()
                    self.last_lobby_broadcast = current_time
            
            # Sleep to maintain our tick rate
            target_frame_time = 1.0 / self.tick_rate
            elapsed = asyncio.get_event_loop().time() - current_time
            sleep_time = max(0, target_frame_time - elapsed)
            
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)


# Generate SSL certificate for testing
def generate_ssl_cert():
    """Generate a self-signed certificate for testing."""
    if not os.path.exists("cert.pem") or not os.path.exists("key.pem"):
        print("Generating self-signed SSL certificate...")
        os.system("openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes -subj '/CN=localhost'")
        print("Certificate generated.")
    return "cert.pem", "key.pem"


if __name__ == "__main__":
    # Import game examples
    from game_examples import TicTacToeGame, MultiplayerRaceGame
    
    # Generate SSL certificate for QUIC
    cert_path, key_path = generate_ssl_cert()
    
    # Choose which game to run
    # game_class = TicTacToeGame  # Turn-based for 2 players
    game_class = MultiplayerRaceGame  # Real-time for 1-8 players
    
    # Create and run server
    server = GameServer("127.0.0.1", 8888, game_class, cert_path, key_path)
    
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        print("Server shutting down...")