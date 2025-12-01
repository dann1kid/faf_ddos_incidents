# parsers/game_logs.py

import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import os

class GameLogParser:
    """Parse FAF game_*match_id*.log files to extract player connection info"""
    
    # Patterns for extracting player data
    LOCAL_PLAYER_PATTERN = r'starting with local uid of (\d+) \[([^\]]+)\]'
    CONNECT_TO_PEER_PATTERN = r'ConnectToPeer \(name=([^,]+), uid=(\d+), address=([^,]+)'
    ESTABLISHED_CONNECTION_PATTERN = r'"([^"]+)" \[.*?uid=(\d+)\] has established connections to: ([\d,\s]+)'
    DISCONNECT_PATTERN = r'DisconnectFromPeer \(uid=(\d+)\)'
    
    def __init__(self, log_file_path: str):
        self.log_file_path = log_file_path
        self.match_id = self._extract_match_id()
        self.players: Dict[int, Dict] = {}  # uid -> player info
        self.sessions: List[Dict] = []  # list of (player, join_time, leave_time)
        
    def _extract_match_id(self) -> Optional[int]:
        """Extract match_id from filename like game_25997456.log"""
        match = re.search(r'game_(\d+)\.log', os.path.basename(self.log_file_path))
        return int(match.group(1)) if match else None
    
    def parse(self) -> Dict:
        """Parse the entire log file and return structured data"""
        with open(self.log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        local_uid = None
        timestamps = {}  # uid -> first_seen, last_seen
        
        for line in lines:
            # Extract local player (ты сам)
            local_match = re.search(self.LOCAL_PLAYER_PATTERN, line)
            if local_match:
                local_uid = int(local_match.group(1))
                nick = local_match.group(2)
                self.players[local_uid] = {
                    'uid': local_uid,
                    'nick': nick,
                    'role': 'host'  # обычно начинающий матч — хост
                }
                timestamps[local_uid] = (self._extract_timestamp(line), None)
            
            # Extract peer connections
            peer_match = re.search(self.CONNECT_TO_PEER_PATTERN, line)
            if peer_match:
                nick = peer_match.group(1)
                uid = int(peer_match.group(2))
                address = peer_match.group(3)  # 127.0.0.1:63122 (localhost через ICE)
                
                if uid not in self.players:
                    self.players[uid] = {
                        'uid': uid,
                        'nick': nick,
                        'role': 'player'
                    }
                
                if uid not in timestamps:
                    timestamps[uid] = (self._extract_timestamp(line), None)
                else:
                    old_time, _ = timestamps[uid]
                    timestamps[uid] = (old_time, self._extract_timestamp(line))
            
            # Extract established connections confirmation
            conn_match = re.search(self.ESTABLISHED_CONNECTION_PATTERN, line)
            if conn_match:
                nick = conn_match.group(1)
                uid = int(conn_match.group(2))
                connected_to = [int(x.strip()) for x in conn_match.group(3).split(',')]
                
                if uid not in self.players:
                    self.players[uid] = {
                        'uid': uid,
                        'nick': nick,
                        'role': 'player'
                    }
                
                # Update last_seen
                if uid in timestamps:
                    old_time, _ = timestamps[uid]
                    timestamps[uid] = (old_time, self._extract_timestamp(line))
                else:
                    timestamps[uid] = (self._extract_timestamp(line), None)
            
            # Extract disconnections
            disconnect_match = re.search(self.DISCONNECT_PATTERN, line)
            if disconnect_match:
                uid = int(disconnect_match.group(1))
                if uid in timestamps:
                    old_time, _ = timestamps[uid]
                    timestamps[uid] = (old_time, self._extract_timestamp(line))
        
        # Build sessions list
        for uid, (first_seen, last_seen) in timestamps.items():
            if uid in self.players:
                self.sessions.append({
                    'player_uid': uid,
                    'player_nick': self.players[uid]['nick'],
                    'joined_at': first_seen,
                    'left_at': last_seen,
                    'role': self.players[uid].get('role', 'player')
                })
        
        return {
            'match_id': self.match_id,
            'players': self.players,
            'sessions': self.sessions,
            'local_uid': local_uid
        }
    
    @staticmethod
    def _extract_timestamp(line: str) -> Optional[datetime]:
        """Extract timestamp from log line if present
        
        FAF logs часто не имеют явного timestamp в каждой строке,
        но можно добавить общую логику для экстракции из имени файла
        или использовать mtime файла как fallback.
        """
        # Placeholder: в реальности можно парсить из JSON заголовков или файла
        return datetime.utcnow()
