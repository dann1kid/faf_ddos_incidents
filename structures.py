from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional
import ipaddress
from pathlib import Path

@dataclass
class IceAdapterCandidate:
    player_uid: int
    ip: str
    type: str  # HOST_CANDIDATE / SERVER_REFLEXIVE_CANDIDATE / RELAYED_CANDIDATE
    protocol: str  # udp / tcp
    port: int
    foundation: str
    priority: int
    rel_addr: Optional[str]
    rel_port: Optional[int]
    timestamp: datetime

    def is_public_ip(self) -> bool:
        try:
            addr = ipaddress.ip_address(self.ip)
        except ValueError:
            return False
        return not (addr.is_private or addr.is_loopback or addr.is_link_local)

@dataclass
class PlayerSessionInfo:
    match_id: int
    joined_at: datetime
    left_at: Optional[datetime]
    role: str  # 'host' | 'player' | 'observer'


@dataclass
class AggregatedPlayer:
    uid: int
    nick: Optional[str] = None
    match_id: Optional[int] = None
    joined_at: Optional[datetime] = None
    left_at: Optional[datetime] = None
    role: str = "player"
    # Приватное поле для хранения
    _public_ips: List[str] = field(default_factory=list)
    all_candidates: List[IceAdapterCandidate] = field(default_factory=list)
    connected_successfully: bool = False

    @property
    def public_ips(self) -> List[str]:
        """Возвращает публичные IP (интерфейс как у IceAdapterPlayer)"""
        return self._public_ips

    def add_public_ip(self, ip: str):
        """Добавляет IP, если его ещё нет"""
        if ip not in self._public_ips:
            self._public_ips.append(ip)


@dataclass
class AggregatedMatch:
    match_id: int
    game_id: Optional[int] = None  # из ice-adapter telemetry URL
    local_player_id: Optional[int] = None
    host_uid: Optional[int] = None
    started_at: Optional[datetime] = None
    players: Dict[int, AggregatedPlayer] = field(default_factory=dict)


@dataclass
class IceCandidate:
    player_uid: int
    ip: str
    type: str
    time_connected: datetime
    time_disconnected: datetime | None = None


@dataclass
class CandidatesCollection:
    candidates: List[IceCandidate]





@dataclass
class IceAdapterPlayer:
    uid: int
    nick: Optional[str] = None
    joined_at: Optional[datetime] = None
    connected_at: Optional[datetime] = None  # время onConnected
    disconnected_at: Optional[datetime] = None  # время Disconnected
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    candidates: List[IceAdapterCandidate] = field(default_factory=list)

    def add_event_time(self, ts: datetime):
        if self.first_seen is None or ts < self.first_seen:
            self.first_seen = ts
        if self.last_seen is None or ts > self.last_seen:
            self.last_seen = ts

    def public_ips(self) -> List[str]:
        ips = {c.ip for c in self.candidates if c.is_public_ip()}
        return sorted(ips)


@dataclass
class IceAdapterParseResult:
    log_path: Path
    game_id: Optional[int]
    local_player_id: Optional[int]
    players: Dict[int, IceAdapterPlayer] = field(default_factory=dict)
    candidates: List[IceAdapterCandidate] = field(default_factory=list)
    
