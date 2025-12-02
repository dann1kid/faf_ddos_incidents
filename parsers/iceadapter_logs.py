from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import json
import re

from structures import IceAdapterParseResult, IceAdapterPlayer, IceAdapterCandidate

class IceAdapterLogParser:
    """
    Целостный парсер для logs/iceAdapterLogs/ice-adapter.YYYY-MM-DD.log. [file:99]
    Достаёт:
      - game_id и local_player_id из строки Telemetry UI
      - onJoinGame / onConnectToPeer → UID + ник
      - IceMsg received {...} → кандидаты (IP, тип и т.д.) по player_uid=srcId
    """

    # 2025-11-26 00:22:34.477 INFO  Open the telemetry ui via https://...gameId=25986537&playerId=324211
    TELEMETRY_URL_RE = re.compile(
        r"Open the telemetry ui via .*?[?&]gameId=(\d+)&playerId=(\d+)"
    )

    # 2025-11-26 00:22:44.020 INFO  onJoinGame 537506 CTPAX
    ON_JOIN_GAME_RE = re.compile(r"\bonJoinGame\s+(\d+)\s+(\S+)")

    # 2025-11-26 00:22:44.025 INFO  onConnectToPeer 536233 pashalapa, offer: true
    ON_CONNECT_TO_PEER_RE = re.compile(
        r"\bonConnectToPeer\s+(\d+)\s+([^,]+),\s+offer:\s+(true|false)"
    )

    # 2025-11-26 00:22:44.338 INFO  IceMsg received {...}
    ICEMSG_RE = re.compile(
        r"IceMsg received (\{.*\})\s+\(c\.f\.iceadapter\.rpc\.RPCHandler:", re.DOTALL
    )

    # timestamp в начале строки: 2025-11-26 00:22:44.338
    TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})")

    ON_CONNECTED_RE = re.compile(r"onConnected.*?\[(\d+),(\d+)")

    # Disconnected 364009
    DISCONNECTED_RE = re.compile(r"\bDisconnected\s+(\d+)\b")

    def __init__(self, log_path: str | Path):
        self.log_path = Path(log_path)

    def parse(self) -> IceAdapterParseResult:
        text = self.log_path.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()

        game_id: Optional[int] = None
        local_player_id: Optional[int] = None
        players: Dict[int, IceAdapterPlayer] = {}
        all_candidates: List[IceAdapterCandidate] = []

        # 1. Одним проходом собираем всё
        for line in lines:
            ts = self._parse_ts(line)

            # Telemetry URL → gameId + local playerId
            if game_id is None or local_player_id is None:
                m_tel = self.TELEMETRY_URL_RE.search(line)
                if m_tel:
                    game_id = int(m_tel.group(1))
                    local_player_id = int(m_tel.group(2))

            # onJoinGame UID Nick
            m_join = self.ON_JOIN_GAME_RE.search(line)
            if m_join:
                uid = int(m_join.group(1))
                nick = m_join.group(2)
                p = players.get(uid)
                if p is None:
                    p = IceAdapterPlayer(uid=uid, nick=nick, joined_at=ts)
                    players[uid] = p
                else:
                    if not p.nick:
                        p.nick = nick
                    if p.joined_at is None:
                        p.joined_at = ts
                if ts:
                    p.add_event_time(ts)
                continue

            # onConnectToPeer UID Nick
            m_conn = self.ON_CONNECT_TO_PEER_RE.search(line)
            if m_conn:
                uid = int(m_conn.group(1))
                nick = m_conn.group(2).strip()
                p = players.get(uid)
                if p is None:
                    p = IceAdapterPlayer(uid=uid, nick=nick)
                    players[uid] = p
                else:
                    if not p.nick:
                        p.nick = nick
                if ts:
                    p.add_event_time(ts)
                continue

            # IceMsg received {...}
            m_ice = self.ICEMSG_RE.search(line)
            if m_ice:
                json_str = m_ice.group(1)
                try:
                    data = json.loads(json_str)
                except json.JSONDecodeError:
                    continue

                src_id = int(data.get("srcId"))
                dest_id = int(data.get("destId"))
                cand_list = data.get("candidates", [])

                # Убедимся, что у srcId есть Player
                p_src = players.get(src_id)
                if p_src is None:
                    p_src = IceAdapterPlayer(uid=src_id)
                    players[src_id] = p_src
                if ts:
                    p_src.add_event_time(ts)

                # Кандидаты принадлежат srcId (отправитель IceMsg). [file:99][web:88]
                for c in cand_list:
                    ip = c.get("ip")
                    if not ip:
                        continue

                    cand = IceAdapterCandidate(
                        player_uid=src_id,
                        ip=ip,
                        type=c.get("type", ""),
                        protocol=c.get("protocol", ""),
                        port=int(c.get("port", 0)),
                        foundation=str(c.get("foundation", "")),
                        priority=int(c.get("priority", 0)),
                        rel_addr=c.get("relAddr"),
                        rel_port=int(c["relPort"])
                        if c.get("relPort") is not None
                        else None,
                        timestamp=ts or datetime.min,
                    )
                    all_candidates.append(cand)
                    p_src.candidates.append(cand)

                continue

        return IceAdapterParseResult(
            log_path=self.log_path,
            game_id=game_id,
            local_player_id=local_player_id,
            players=players,
            candidates=all_candidates,
        )

    def parse_all_matches(self) -> Dict[int, IceAdapterParseResult]:
        text = self.log_path.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()

        matches: Dict[int, IceAdapterParseResult] = {}
        current_game_id: Optional[int] = None
        current_result: Optional[IceAdapterParseResult] = None

        for line in lines:
            ts = self._parse_ts(line)

            # Telemetry URL — начало нового матча
            m_tel = self.TELEMETRY_URL_RE.search(line)
            if m_tel:
                new_game_id = int(m_tel.group(1))
                local_player_id = int(m_tel.group(2))

                # Сохраняем предыдущий матч
                if current_result is not None and current_game_id is not None:
                    matches[current_game_id] = current_result

                # Создаём новый
                current_game_id = new_game_id
                current_result = IceAdapterParseResult(
                    log_path=self.log_path,
                    game_id=new_game_id,
                    local_player_id=local_player_id,
                    players={},
                    candidates=[],
                )
                continue

            if current_result is None or current_game_id is None:
                continue

            # onJoinGame
            m_join = self.ON_JOIN_GAME_RE.search(line)
            if m_join:
                uid = int(m_join.group(1))
                nick = m_join.group(2)
                p = current_result.players.get(uid)
                if p is None:
                    p = IceAdapterPlayer(uid=uid, nick=nick, joined_at=ts)
                    current_result.players[uid] = p
                else:
                    if not p.nick:
                        p.nick = nick
                    if p.joined_at is None:
                        p.joined_at = ts
                if ts:
                    p.add_event_time(ts)
                continue

            # onConnectToPeer
            m_conn = self.ON_CONNECT_TO_PEER_RE.search(line)
            if m_conn:
                uid = int(m_conn.group(1))
                nick = m_conn.group(2).strip()
                p = current_result.players.get(uid)
                if p is None:
                    p = IceAdapterPlayer(uid=uid, nick=nick)
                    current_result.players[uid] = p
                else:
                    if not p.nick:
                        p.nick = nick
                if ts:
                    p.add_event_time(ts)
                continue

            # IceMsg received
            m_ice = self.ICEMSG_RE.search(line)
            if m_ice:
                json_str = m_ice.group(1)
                try:
                    data = json.loads(json_str)
                except json.JSONDecodeError:
                    continue

                src_id = int(data.get("srcId"))
                dest_id = int(data.get("destId"))
                cand_list = data.get("candidates", [])

                # Убеждаемся, что src_id есть в players
                p_src = current_result.players.get(src_id)
                if p_src is None:
                    p_src = IceAdapterPlayer(uid=src_id)
                    current_result.players[src_id] = p_src
                if ts:
                    p_src.add_event_time(ts)

                # Добавляем кандидатов
                for c in cand_list:
                    ip = c.get("ip")
                    if not ip:
                        continue
                    cand = IceAdapterCandidate(
                        player_uid=src_id,
                        ip=ip,
                        type=c.get("type", ""),
                        protocol=c.get("protocol", ""),
                        port=int(c.get("port", 0)),
                        foundation=str(c.get("foundation", "")),
                        priority=int(c.get("priority", 0)),
                        rel_addr=c.get("relAddr"),
                        rel_port=int(c["relPort"])
                        if c.get("relPort") is not None
                        else None,
                        timestamp=ts or datetime.min,
                    )
                    current_result.candidates.append(cand)
                    p_src.candidates.append(cand)
                continue

            # onConnected
            m_on_conn = self.ON_CONNECTED_RE.search(line)
            if m_on_conn:
                uid1 = int(m_on_conn.group(1))
                uid2 = int(m_on_conn.group(2))
                for uid in (uid1, uid2):
                    if uid in current_result.players:
                        current_result.players[uid].connected_at = ts
                        if ts:
                            current_result.players[uid].add_event_time(ts)
                continue

            # Disconnected
            m_disc = self.DISCONNECTED_RE.search(line)
            if m_disc:
                uid = int(m_disc.group(1))
                if uid in current_result.players:
                    current_result.players[uid].disconnected_at = ts
                    if ts:
                        current_result.players[uid].add_event_time(ts)
                continue

        # Сохраняем последний матч
        if current_result is not None and current_game_id is not None:
            matches[current_game_id] = current_result

        return matches

    @staticmethod
    def _parse_ts(line: str) -> Optional[datetime]:
        m = IceAdapterLogParser.TS_RE.match(line)
        if not m:
            return None
        # 2025-11-26 00:22:44.338 → naive datetime
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S.%f")
