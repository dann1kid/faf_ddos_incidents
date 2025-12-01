# parsers/client_logs.py
"""
Парсер client.log.*.0.log файлов

Ищет:
- ICE connection state changes
- Connection established/lost между пирами
- ICE candidates (SERVER_REFLEXIVE, RELAYED и т.п. с IP адресами)
"""

import re
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple

from config import PARSER_CONFIG
from models import Player, IpAddress, PlayerIp, ConnectionEvent, ParsedFile, db

logger = logging.getLogger(__name__)


class ClientLogParser:
    """Парсер client.log файлов"""

    def __init__(self):
        self.patterns = PARSER_CONFIG["client_log"]["patterns"]
        self.players_seen = {}  # faf_id → Player obj
        self.ips_seen = {}  # ip_str → IpAddress obj

    def parse_file(self, filepath: Path) -> int:
        """
        Парсить один client.log.*.0.log файл

        Returns:
            Количество спарсённых событий
        """
        logger.info(f"Parsing client log: {filepath}")

        # Проверить, не спарсили ли уже
        if ParsedFile.select().where(ParsedFile.path == str(filepath)).exists():
            if not self._file_modified(filepath):
                logger.debug(f"File already parsed and not modified: {filepath.name}")
                return 0
            logger.info(f"File modified, reparsing: {filepath.name}")

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except Exception as e:
            logger.error(f"Failed to read {filepath}: {e}")
            return 0

        events_parsed = 0

        with db.atomic():
            for line_no, line in enumerate(lines, 1):
                try:
                    # Парсить timestamp
                    ts = self._extract_timestamp(line)
                    if not ts:
                        continue

                    # 1. ICE state changes
                    match = re.search(self.patterns["ice_state_change"], line)
                    if match:
                        peer_id_str, new_state = match.groups()
                        peer_id = int(peer_id_str)

                        try:
                            player = Player.get(Player.faf_id == peer_id)
                        except Player.DoesNotExist:
                            # Создать плейхолдер игрока с неизвестным ником
                            player, _ = Player.get_or_create(
                                faf_id=peer_id,
                                defaults={"current_nick": f"UNKNOWN_{peer_id}"},
                            )

                        _ = ConnectionEvent.create(
                            timestamp=ts,
                            dst_player=player,
                            event_type=f"ICE_STATE_{new_state.upper()}",
                            raw=line.strip(),
                        )
                        events_parsed += 1
                        logger.debug(f"  ICE state: peer={peer_id} → {new_state}")
                        continue

                    # 2. Connection established
                    match = re.search(self.patterns["connection_established"], line)
                    if match:
                        src_id_str, dst_id_str = match.groups()
                        src_id, dst_id = int(src_id_str), int(dst_id_str)

                        src_player = self._get_or_create_player(src_id)
                        dst_player = self._get_or_create_player(dst_id)

                        _ = ConnectionEvent.create(
                            timestamp=ts,
                            src_player=src_player,
                            dst_player=dst_player,
                            event_type="PEER_CONNECTED",
                            raw=line.strip(),
                        )
                        events_parsed += 1
                        logger.debug(f"  Connection: {src_id} ↔ {dst_id}")
                        continue

                    # 3. Connection lost
                    match = re.search(self.patterns["connection_lost"], line)
                    if match:
                        src_id_str, dst_id_str = match.groups()
                        src_id, dst_id = int(src_id_str), int(dst_id_str)

                        src_player = self._get_or_create_player(src_id)
                        dst_player = self._get_or_create_player(dst_id)

                        _ = ConnectionEvent.create(
                            timestamp=ts,
                            src_player=src_player,
                            dst_player=dst_player,
                            event_type="PEER_DISCONNECTED",
                            raw=line.strip(),
                        )
                        events_parsed += 1
                        logger.debug("  Disconnection: %s ↔ %s", src_id, dst_id)
                        continue

                    # 4. ICE candidates (парсить типы и IP адреса)
                    match = re.search(self.patterns["ice_message"], line)
                    if match:
                        src_id_str, dst_id_str, rest = match.groups()
                        src_id, dst_id = int(src_id_str), int(dst_id_str)

                        # Это более сложная парсинг: нужно вытянуть все IP из rest
                        ips = self._extract_ips_from_ice_message(rest)

                        if ips:
                            src_player = self._get_or_create_player(src_id)

                            for ip_str, candidate_type in ips:
                                ip_obj = self._get_or_create_ip(ip_str, candidate_type)

                                PlayerIp.get_or_create(
                                    player=src_player,
                                    ip=ip_obj,
                                    source="ICE",
                                    defaults={"first_seen": ts, "last_seen": ts},
                                )

                            events_parsed += 1
                            logger.debug(
                                f"  ICE candidates for {src_id}: {len(ips)} IPs extracted"
                            )

                except Exception as e:
                    logger.warning(f"Error parsing line {line_no}: {e}")

        # Отметить файл как спарсённый
        try:
            ParsedFile.create(
                path=str(filepath),
                kind="CLIENT",
                mtime=datetime.fromtimestamp(filepath.stat().st_mtime),
            )
        except (ValueError, AttributeError):
            pass  # Может быть дубликат, но это OK

        logger.info(f"✓ Parsed {events_parsed} events from {filepath.name}")
        return events_parsed

    @staticmethod
    def _extract_timestamp(line: str) -> Optional[datetime]:
        """
        Извлечь timestamp из строки лога

        Формат: 2025-11-26T002251.2280300
        """
        match = re.search(r"(\d{4}-\d{2}-\d{2}T\d{6}\.\d+)", line)
        if match:
            ts_str = match.group(1)
            try:
                # Парсить, отбросив микросекунды
                ts_str_trimmed = ts_str[:15]  # '2025-11-26T002251'
                return datetime.strptime(ts_str_trimmed, "%Y-%m-%dT%H%M%S")
            except (ValueError, AttributeError):
                return None
        return None

    @staticmethod
    def _file_modified(filepath: Path) -> bool:
        """Проверить модификацию файла"""
        try:
            parsed = ParsedFile.get(ParsedFile.path == str(filepath))
            return datetime.fromtimestamp(filepath.stat().st_mtime) > parsed.mtime
        except ParsedFile.DoesNotExist:
            return True

    def _extract_ips_from_ice_message(self, ice_msg: str) -> List[Tuple[str, str]]:
        """
        Извлечь IP и типы кандидатов из ICE сообщения

        Формат: ...ip77.51.212.234,port6573,typeSERVERREFLEXIVECANDIDATE...
                ...ip192.168.1.9,port6730,typeHOSTCANDIDATE...
                ...ip138.197.167.11,port58952,typeRELAYEDCANDIDATE...

        Returns:
            List[Tuple[ip, candidate_type]]
        """
        result = []

        # Парсить всё вида: ip<IP_ADDRESS>,port<PORT>,type<CANDIDATE_TYPE>
        pattern = r"ip([^,]+),port\d+,type(\w+CANDIDATE)"

        for match in re.finditer(pattern, ice_msg):
            ip, candidate_type = match.groups()

            # Фильтровать некорректные IP
            if self._is_valid_ip(ip):
                result.append((ip, candidate_type))

        return result

    @staticmethod
    def _is_valid_ip(ip_str: str) -> bool:
        """Проверить, является ли строка валидным IP адресом"""
        import ipaddress

        try:
            ipaddress.ip_address(ip_str)
            return True
        except (ValueError, AttributeError):
            return False

    def _get_or_create_player(self, faf_id: int) -> "Player":
        """Получить или создать плейхолдер игрока"""
        if faf_id in self.players_seen:
            return self.players_seen[faf_id]

        try:
            player = Player.get(Player.faf_id == faf_id)
        except Player.DoesNotExist:
            player, _ = Player.get_or_create(
                faf_id=faf_id,
                defaults={
                    "current_nick": f"UNKNOWN_{faf_id}",
                    "first_seen": datetime.now(),
                },
            )

        self.players_seen[faf_id] = player
        return player

    def _get_or_create_ip(
        self, ip_str: str, candidate_type: str = "UNKNOWN"
    ) -> IpAddress:
        """Получить или создать IP адрес с типом"""
        if ip_str in self.ips_seen:
            return self.ips_seen[ip_str]

        is_private = self._is_private_ip(ip_str)

        # Нормализовать тип кандидата
        kind_map = {
            "HOSTCANDIDATE": "HOST",
            "SERVERREFLEXIVECANDIDATE": "SERVER_REFLEXIVE",
            "RELAYEDCANDIDATE": "RELAYED",
        }
        kind = kind_map.get(candidate_type, "UNKNOWN")

        ip_obj, created = IpAddress.get_or_create(
            ip=ip_str,
            defaults={
                "is_private": is_private,
                "kind": kind,
            },
        )

        # Если уже существовал, обновить kind если он более точный
        if not created and kind != "UNKNOWN" and ip_obj.kind == "UNKNOWN":
            ip_obj.kind = kind
            ip_obj.save()

        self.ips_seen[ip_str] = ip_obj
        return ip_obj

    @staticmethod
    def _is_private_ip(ip_str: str) -> bool:
        """Проверить приватность IP"""
        import ipaddress

        try:
            ip = ipaddress.ip_address(ip_str)
            return ip.is_private
        except (ValueError, AttributeError):
            return False


def parse_client_logs(log_paths: List[Path], skip_existing: bool = True) -> int:
    """
    Парсить все client.log.*.0.log файлы

    Args:
        log_paths: список путей к файлам
        skip_existing: пропускать уже спарсённые файлы

    Returns:
        Общее количество спарсённых событий
    """
    parser = ClientLogParser()
    total_events = 0

    for filepath in log_paths:
        try:
            events = parser.parse_file(filepath)
            total_events += events
        except Exception as e:
            logger.error(f"Exception while parsing {filepath}: {e}", exc_info=True)

    logger.info(f"✓ Parsed {total_events} events from client logs")
    return total_events
