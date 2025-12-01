# parsers/game_logs.py
"""
Парсер game_*match_id*.log файлов

Ищет:
- ConnectToPeer → регистрация игроков
- LOBBY: "nick" [...] → информация о лобби и подключениях
- Время старта/окончания матча
"""

import re
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

from config import PARSER_CONFIG
from models import Player, Match, MatchPlayer, IpAddress, PlayerIp, ParsedFile, db

logger = logging.getLogger(__name__)


class GameLogParser:
    """Парсер game_*.log файлов"""

    def __init__(self):
        self.patterns = PARSER_CONFIG["game_log"]["patterns"]
        self.players_seen = {}  # faf_id → Player obj
        self.ips_seen = {}  # ip_str → IpAddress obj

    def parse_file(self, filepath: Path) -> Optional[int]:
        """
        Парсить один game_*.log файл

        Returns:
            match_id если успешно, None если ошибка
        """
        logger.info(f"Parsing game log: {filepath}")

        # Извлечь match_id из имени файла
        match_id = self._extract_match_id(filepath)
        if not match_id:
            logger.error(f"Cannot extract match_id from {filepath.name}")
            return None

        # Проверить, не спарсили ли уже этот файл
        if ParsedFile.select().where(ParsedFile.path == str(filepath)).exists():
            if not self._file_modified(filepath):
                logger.debug(f"File already parsed and not modified: {filepath.name}")
                return match_id
            logger.info(f"File modified, reparsing: {filepath.name}")

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Failed to read {filepath}: {e}")
            return None

        # Парсить контент
        players_in_match = {}  # faf_id → {'nick': ..., 'team': ..., 'ips': [...]}

        # 1. Ищем ConnectToPeer для получения ников и IP адресов
        for match in re.finditer(self.patterns["connect_to_peer"], content):
            nick, uid_str, address, flags = match.groups()
            uid = int(uid_str)

            if uid not in players_in_match:
                players_in_match[uid] = {
                    "nick": nick,
                    "ips": [],
                    "team": None,
                    "first_seen": None,
                    "last_seen": None,
                }

            players_in_match[uid]["ips"].append(address)
            logger.debug(
                f"  Found ConnectToPeer: uid={uid}, nick={nick}, addr={address}"
            )

        # 2. Ищем LOBBY строки для получения команд и уточнения информации
        for match in re.finditer(self.patterns["player_in_lobby"], content):
            nick, host, port, uid_str, connections_str = match.groups()
            uid = int(uid_str)

            if uid not in players_in_match:
                players_in_match[uid] = {
                    "nick": nick,
                    "ips": [f"{host}:{port}"],
                    "team": None,
                    "first_seen": None,
                    "last_seen": None,
                }
            else:
                players_in_match[uid]["nick"] = nick  # update ник если есть новый

            logger.debug(
                f"  Found LOBBY entry: uid={uid}, nick={nick}, connections_to={connections_str}"
            )

        # Попробовать извлечь JSON заголовок (если есть сериализованный JSON матча)
        raw_json = self._extract_json_header(content)
        match_info = self._parse_json_header(raw_json) if raw_json else {}

        # Определить хоста (может быть в JSON или в логах)
        host_nick = match_info.get("host")
        host_player = None

        # Транзакция: создать/обновить матч и его участников
        with db.atomic():
            # Создать/обновить игроков
            for uid, info in players_in_match.items():
                player = self._get_or_create_player(uid, info["nick"])

                # Сохранить IP адреса
                for ip_str in info["ips"]:
                    ip_obj = self._get_or_create_ip(ip_str)
                    PlayerIp.get_or_create(
                        player=player,
                        ip=ip_obj,
                        source="GAME_LOG",
                        defaults={
                            "first_seen": datetime.now(),
                            "last_seen": datetime.now(),
                        },
                    )

                if host_nick and info["nick"] == host_nick:
                    host_player = player

            # Создать матч
            match_defaults = {
                "title": match_info.get("title", ""),
                "mapname": match_info.get("mapname"),
                "game_type": match_info.get("game_type"),
                "started_at": match_info.get("started_at"),
                "ended_at": match_info.get("ended_at"),
                "host": host_player,
                "raw_json": raw_json,
                "source_file": str(filepath),
            }

            match_obj, created = Match.get_or_create(
                match_id=match_id, defaults=match_defaults
            )

            logger.info(f"  {'Created' if created else 'Updated'} Match(id={match_id})")

            # Связать игроков с матчем
            for uid, info in players_in_match.items():
                player = Player.get(Player.faf_id == uid)

                MatchPlayer.get_or_create(
                    match=match_obj,
                    player=player,
                    defaults={
                        "team": info["team"],
                        "first_seen": datetime.now(),
                        "last_seen": datetime.now(),
                    },
                )

            # Отметить файл как спарсённый
            ParsedFile.create(
                path=str(filepath),
                kind="GAME",
                mtime=datetime.fromtimestamp(filepath.stat().st_mtime),
            )

        logger.info(
            f"✓ Successfully parsed {filepath.name}: Match({match_id}) with {len(players_in_match)} players"
        )
        return match_id

    @staticmethod
    def _extract_match_id(filepath: Path) -> Optional[int]:
        """Извлечь match_id из имени файла game_123456.log"""
        match = re.search(r"game_(\d+)\.log", filepath.name)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def _file_modified(filepath: Path) -> bool:
        """Проверить, был ли файл изменён после последнего парсинга"""
        try:
            parsed = ParsedFile.get(ParsedFile.path == str(filepath))
            return datetime.fromtimestamp(filepath.stat().st_mtime) > parsed.mtime
        except ParsedFile.DoesNotExist:
            return True

    @staticmethod
    def _extract_json_header(content: str) -> Optional[str]:
        """Попытаться извлечь JSON заголовок из начала лога"""
        # На случай, если JSON находится в начале файла
        match = re.search(r'\{[^{}]*"match_id"[^{}]*\}', content, re.DOTALL)
        return match.group(0) if match else None

    @staticmethod
    def _parse_json_header(raw_json: str) -> Dict:
        """Парсить JSON заголовок матча"""
        import json

        try:
            data = json.loads(raw_json)
            return {
                "title": data.get("title", ""),
                "mapname": data.get("mapname"),
                "game_type": data.get("game_type"),
                "host": data.get("host"),
                # Если есть таймштампы
                "started_at": data.get("game_start") or data.get("launched_at"),
                "ended_at": data.get("game_end"),
            }
        except (ValueError, AttributeError):
            return {}

    def _get_or_create_player(self, faf_id: int, nick: str) -> Player:
        """Получить или создать игрока"""
        if faf_id in self.players_seen:
            return self.players_seen[faf_id]

        player, _ = Player.get_or_create(
            faf_id=faf_id, defaults={"current_nick": nick, "first_seen": datetime.now()}
        )

        # Обновить ник если он изменился
        if player.current_nick != nick:
            # TODO: можно сохранять в NicknameHistory
            player.current_nick = nick
            player.last_seen = datetime.now()
            player.save()

        self.players_seen[faf_id] = player
        return player

    def _get_or_create_ip(self, ip_str: str) -> IpAddress:
        """Получить или создать IP адрес"""
        if ip_str in self.ips_seen:
            return self.ips_seen[ip_str]

        # Определить тип IP
        is_private = self._is_private_ip(ip_str)

        ip_obj, _ = IpAddress.get_or_create(
            ip=ip_str,
            defaults={
                "is_private": is_private,
                "kind": "UNKNOWN",  # Уточнится при парсинге ICE логов
            },
        )

        self.ips_seen[ip_str] = ip_obj
        return ip_obj

    @staticmethod
    def _is_private_ip(ip_str: str) -> bool:
        """Проверить, является ли IP приватным"""
        import ipaddress

        try:
            ip = ipaddress.ip_address(ip_str.split(":")[0])  # Отделить порт
            return ip.is_private
        except (ValueError, AttributeError):
            return False


def parse_game_logs(log_paths: List[Path], skip_existing: bool = True) -> int:
    """
    Парсить все game_*.log файлы

    Args:
        log_paths: список путей к файлам
        skip_existing: пропускать уже спарсённые файлы

    Returns:
        Количество спарсённых матчей
    """
    parser = GameLogParser()
    parsed_count = 0

    for filepath in log_paths:
        try:
            match_id = parser.parse_file(filepath)
            if match_id:
                parsed_count += 1
        except Exception as e:
            logger.error(f"Exception while parsing {filepath}: {e}", exc_info=True)

    logger.info(f"✓ Parsed {parsed_count} game logs")
    return parsed_count
