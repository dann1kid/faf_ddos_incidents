from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Set

from parsers.client_logs import IceCandidate, CandidatesCollection
from parsers.game_logs import GameLogParser
from parsers.client_logs import ClientLogParser
from icecream import ic
import ipaddress
from parsers.iceadapter_logs import IceAdapterLogParser, IceAdapterParseResult

def is_public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
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
class PlayerAggregate:
    uid: int
    nick: Optional[str] = None
    sessions: List[PlayerSessionInfo] = field(default_factory=list)
    candidates: List[IceCandidate] = field(default_factory=list)
    
    def get_unique_ips(self) -> Dict[str, str]:
        """Возвращает словарь уникальных IP → тип кандидата"""
        ips = {}
        for cand in self.candidates:
            if cand.ip not in ips:
                ips[cand.ip] = cand.type
        return ips
    
    def get_reflexive_ips(self) -> Set[str]:
        """Возвращает только PUBLIC IP (SERVER_REFLEXIVE)"""
        return {
            cand.ip for cand in self.candidates 
            if 'SERVER_REFLEXIVE_CANDIDATE' in cand.type
        }
        
    def get_public_ips(self) -> Set[str]:
        return {
            cand.ip for cand in self.candidates
            if is_public_ip(cand.ip)
        }

@dataclass
class AggregationResult:
    players: Dict[int, PlayerAggregate]


def aggregate_players(
    match_data: dict,              # результат GameLogParser.parse()
    ice_data: CandidatesCollection # результат ClientLogParser.parse()
) -> AggregationResult:
    players: Dict[int, PlayerAggregate] = {}

    # 1) Сессии из game_*.log
    match_id = match_data.get('match_id')
    for sess in match_data.get('sessions', []):
        uid = sess['player_uid']
        nick = sess.get('player_nick')

        agg = players.get(uid)
        if agg is None:
            agg = PlayerAggregate(uid=uid, nick=nick)
            players[uid] = agg
        else:
            if nick and not agg.nick:
                agg.nick = nick

        agg.sessions.append(
            PlayerSessionInfo(
                match_id=match_id,
                joined_at=sess['joined_at'],
                left_at=sess.get('left_at'),
                role=sess.get('role', 'player'),
            )
        )

    # 2) ICE‑кандидаты из client.log.* (все типы)
    for cand in ice_data.candidates:
        uid = cand.player_uid
        agg = players.get(uid)
        if agg is None:
            agg = PlayerAggregate(uid=uid)
            players[uid] = agg
        agg.candidates.append(cand)

    return AggregationResult(players=players)


def print_player_summary(agg_result: AggregationResult):
    """Выводит полный отчёт игроков с сопоставлением IP"""
    
    print("=" * 100)
    print("PLAYER AGGREGATION REPORT")
    print("=" * 100)
    
    for uid, player in sorted(agg_result.players.items()):
        print(f"\n🎮 PLAYER UID {uid} | Nick: {player.nick or 'UNKNOWN'}")
        print("-" * 100)
        
        # Сессии в матчах
        if player.sessions:
            print(f"  📊 SESSIONS ({len(player.sessions)}):")
            for session in player.sessions:
                duration = (session.left_at - session.joined_at).total_seconds() / 60 if session.left_at else "ongoing"
                if isinstance(duration, float):
                    duration = f"{duration:.1f} min"
                print(f"    • Match {session.match_id} | Role: {session.role:10} | "
                      f"{session.joined_at.isoformat()} → {session.left_at.isoformat() if session.left_at else 'N/A'} "
                      f"({duration})")
        else:
            print(f"  📊 SESSIONS: None")
        
        # IP адреса с типами
        if player.candidates:
            print(f"\n  🌐 ICE CANDIDATES ({len(player.candidates)} events):")
            
            # Уникальные IP с типами
            unique_ips = player.get_unique_ips()
            print(f"\n    Unique IPs: {len(unique_ips)}")
            for ip, cand_type in sorted(unique_ips.items()):
                is_reflexive = '✓ PUBLIC' if 'SERVER_REFLEXIVE_CANDIDATE' in cand_type else '  private'
                print(f"      {is_reflexive} | {ip:20} | Type: {cand_type}")
            
            # Только PUBLIC IP
            reflexive_ips = player.get_reflexive_ips()
            if reflexive_ips:
                print(f"\n    🔴 PUBLIC IPs (SERVER_REFLEXIVE): {', '.join(sorted(reflexive_ips))}")
            
            # Временная шкала
            print(f"\n    Timeline:")
            for cand in sorted(player.candidates, key=lambda c: c.time_connected):
                disconnect = f" → {cand.time_disconnected.isoformat()}" if cand.time_disconnected else ""
                cand_short = 'SRFLX' if 'SERVER_REFLEXIVE' in cand.type else 'RELAY' if 'RELAYED' in cand.type else 'HOST'
                print(f"      [{cand_short}] {cand.ip:20} | {cand.time_connected.isoformat()}{disconnect}")
        else:
            print(f"\n  🌐 ICE CANDIDATES: None")
        
        print()


def print_player_mapping(agg_result: AggregationResult):
    """Компактный вывод: UID → IP mapping"""
    
    print("\n" + "=" * 100)
    print("QUICK REFERENCE: UID ↔ IP MAPPING")
    print("=" * 100)
    
    for uid, player in sorted(agg_result.players.items()):
        nick = player.nick or '?'
        public_ips = player.get_public_ips()
        if public_ips:
            print(f"{uid:10} | {nick:20} | IPs: {', '.join(sorted(public_ips))}")
        else:
            print(f"{uid:10} | {nick:20} | IPs: (none detected)")


# if __name__ == "__main__":
#     # Пример использования
#     game_parser = GameLogParser("./logs/game_26002356.log")
#     match_data = game_parser.parse()

#     client_parser = ClientLogParser("./logs/client.log.2025-11-28.0.log")
#     ice_data = client_parser.parse()

#     agg = aggregate_players(match_data, ice_data)
    
#     # Полный отчёт
#     print_player_summary(agg)
    
#     # Быстрая таблица
#     print_player_mapping(agg)


def print_player_ip_mapping(result: IceAdapterParseResult):
    print(f"Log: {result.log_path}")
    print(f"GameId: {result.game_id}, local_player_id: {result.local_player_id}")
    print("=" * 80)

    for uid in sorted(result.players.keys()):
        p = result.players[uid]
        public_ips = p.public_ips()
        nick = p.nick or "UNKNOWN"
        if public_ips:
            ips_str = ", ".join(public_ips)
        else:
            ips_str = "(no public IPs detected)"
        print(f"{uid:8} | {nick:20} | {ips_str}")


if __name__ == "__main__":
    parser = IceAdapterLogParser("logs/iceAdapterLogs/ice-adapter.2025-11-26.log")
    res = parser.parse()
    print_player_ip_mapping(res)
