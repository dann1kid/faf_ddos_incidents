from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from models import init_database, db
from ingest import ingest_match


from parsers.game_logs import GameLogParser
import ipaddress
from parsers.iceadapter_logs import IceAdapterLogParser
from structures import IceAdapterParseResult



def is_public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (addr.is_private or addr.is_loopback or addr.is_link_local)


from structures import AggregatedMatch, AggregatedPlayer

def aggregate_game_and_ice(
    game_result: dict,  # результат GameLogParser.parse()
    ice_result: IceAdapterParseResult,  # результат IceAdapterLogParser.parse()
) -> AggregatedMatch:
    """
    Сопоставляет данные из game_*.log и ice-adapter.*.log.
    Ключ: match_id (из game) ↔ game_id (из ice-adapter telemetry URL)
    """
    match_id = game_result.get("match_id")
    if not match_id:
        raise ValueError("game_result не содержит match_id")

    # Начинаем с game данных
    agg = AggregatedMatch(
        match_id=match_id,
        game_id=ice_result.game_id,
        local_player_id=ice_result.local_player_id,
    )

    # 1. Добавляем игроков из game логов (сессии)
    for sess in game_result.get("sessions", []):
        uid = sess["player_uid"]
        nick = sess.get("player_nick")
        role = sess.get("role", "player")

        player = agg.players.get(uid)
        if player is None:
            player = AggregatedPlayer(uid=uid, nick=nick, match_id=match_id)
            agg.players[uid] = player

        player.nick = player.nick or nick
        player.joined_at = sess["joined_at"]
        player.left_at = sess.get("left_at")
        player.role = role

        # Хост — это обычно первый игрок в сессиях или тот, у кого role == 'host'
        if role == "host" or agg.host_uid is None:
            agg.host_uid = uid

    # 2. Добавляем данные из ice-adapter (UID, ники, IP)
    for uid, ice_player in ice_result.players.items():
        player = agg.players.get(uid)
        if player is None:
            player = AggregatedPlayer(uid=uid, match_id=match_id)
            agg.players[uid] = player

        # Обновляем ник
        player.nick = player.nick or ice_player.nick

        # Копируем кандидаты
        player.all_candidates.extend(ice_player.candidates)

        # Добавляем публичные IP (через метод, чтобы избежать дубликатов)
        for ip in ice_player.public_ips():
            player.add_public_ip(ip)

        # Статус подключения
        player.connected_successfully = (
            ice_player.connected_at is not None and ice_player.disconnected_at is None
        )

    return agg


def scan_and_aggregate(logs_dir: str = "."):
    logs_path = Path(logs_dir)

    # 1. Парсим все ice-adapter логи
    ice_matches: Dict[int, IceAdapterParseResult] = {}
    ice_files = sorted(logs_path.glob("logs/iceAdapterLogs/ice-adapter.*.log"))

    print(f"🔍 Найдено ice-adapter логов: {len(ice_files)}")
    for ice_file in ice_files:
        print(f"   - {ice_file}")
        parser = IceAdapterLogParser(str(ice_file))
        matches_in_file = parser.parse_all_matches()
        ice_matches.update(matches_in_file)
        print(f"     📄 Матчей в файле: {len(matches_in_file)}")

    # 2. Парсим game_*.log
    game_files = sorted(logs_path.glob("./logs/game_*.log"))
    print(f"\n🔍 Найдено game_*.log файлов: {len(game_files)}")
    for gf in game_files:
        print(f"   - {gf.name}")

    all_matches: List[AggregatedMatch] = []

    # 3. Сопоставляем
    print("\n🔍 Сопоставление матчей:")
    for game_file in game_files:
        game_parser = GameLogParser(str(game_file))
        game_data = game_parser.parse()
        match_id = game_data.get("match_id")

        if match_id is None:
            print(f"   ⚠️ {game_file.name}: match_id не найден")
            continue

        ice_data = ice_matches.get(match_id)
        if ice_data:
            agg = aggregate_game_and_ice(game_data, ice_data)
            all_matches.append(agg)
            print(
                f"   ✅ {game_file.name} (id={match_id}) → {len(agg.players)} игроков"
            )
        else:
            print(f"   ❌ {game_file.name} (id={match_id}) → нет ice-adapter данных")

    return all_matches


def print_complete_report(
    matches: List[AggregatedMatch], exclude_local_player: bool = True
):
    """Выводит полные данные по всем матчам и игрокам"""

    print("=" * 100)
    print("ПОЛНЫЙ ОТЧЁТ ПО МАТЧАМ И ИГРОКАМ")
    if exclude_local_player:
        print("(Свой IP скрыт для удобства анализа)")
    print("=" * 100)

    total_players = 0
    total_with_ips = 0

    for match in matches:
        # Определяем UID локального игрока для этого матча
        local_uid = match.local_player_id if exclude_local_player else None

        print(f"\n{'=' * 100}")
        print(f"МАТЧ #{match.match_id}")
        print(f"{'=' * 100}")
        print(f"  Game ID: {match.game_id or 'N/A'}")
        print(f"  Host UID: {match.host_uid or 'N/A'}")
        print(f"  Local UID: {local_uid or 'N/A'}")
        print(f"  Всего игроков: {len(match.players)}")

        match_players = 0
        match_with_ips = 0

        for uid in sorted(match.players.keys()):
            player = match.players[uid]
            match_players += 1
            total_players += 1

            # Фильтруем IP локального игрока
            public_ips = player.public_ips
            if exclude_local_player and uid == local_uid:
                public_ips = [
                    ip for ip in public_ips if ip not in player.public_ips()
                ]  # Пустой список
                ip_label = "СКРЫТ (локальный игрок)"
            else:
                ip_label = f"{len(public_ips)} IP(s)" if public_ips else "(отсутствуют)"

            print(f"\n  {'-' * 96}")
            print(
                f"  Игрок #{match_players}: UID {uid} | Ник: {player.nick or 'UNKNOWN'}"
            )
            print(f"  {'-' * 96}")
            print(f"    Роль: {player.role}")
            print(
                f"    Время входа: {player.joined_at.isoformat() if player.joined_at else 'N/A'}"
            )
            print(
                f"    Время выхода: {player.left_at.isoformat() if player.left_at else 'N/A'}"
            )
            print(
                f"    Статус подключения: {'✅ Успешно' if player.connected_successfully else '❌ Не подключен'}"
            )
            print(f"    Публичные IP: {ip_label}")

            # Показываем IP только если их нет и это не локальный игрок
            if public_ips and (not exclude_local_player or uid != local_uid):
                match_with_ips += 1
                total_with_ips += 1
                for ip in public_ips:
                    print(f"      • {ip}")

        print(
            f"\n  📊 Статистика матча: {match_with_ips}/{match_players} игроков с публичными IP"
        )

    print(f"\n{'=' * 100}")
    print("ОБЩАЯ СТАТИСТИКА")
    print(f"{'=' * 100}")
    print(f"Всего матчей: {len(matches)}")
    print(f"Всего игроков: {total_players}")
    print(f"Игроков с публичными IP (исключая локального): {total_with_ips}")
    print(
        f"Процент: {total_with_ips / total_players * 100:.1f}%"
        if total_players > 0
        else "0%"
    )


# if __name__ == "__main__":
#     print("=== Сканирование директорий ===")
#     matches = scan_and_aggregate(".")

#     print(f"\n=== Итог: найдено {len(matches)} совпадений ===")

#     if not matches:
#         print("\n⚠️ ВНИМАНИЕ: Не найдено ни одного совпадения!")
#         print("Возможные причины:")
#         print("1. game_*.log файлы находятся в поддиректории")
#         print("2. Имена файлов отличаются от ожидаемого формата")
#         print("3. Проблемы с правами доступа")

#         # Проверим, что файлы существуют
#         import os
#         print("\nПроверка текущей директории:")
#         for item in os.listdir("."):
#             if item.startswith("game_") or "ice-adapter" in item:
#                 print(f"  {item}")


def ingest_all_matches(matches: List[AggregatedMatch]):
    """Загрузить все матчи в БД"""
    print(f"Загрузка {len(matches)} матчей в базу данных...")
    
    with db.atomic():
        for i, match in enumerate(matches, 1):
            ingest_match(match)
            print(f"  ✅ Матч {match.match_id} загружен ({i}/{len(matches)})")
    
    print("✅ Все матчи загружены успешно!")

if __name__ == "__main__":
    init_database()
    matches = scan_and_aggregate(".")
    ingest_all_matches(matches)

    # Показать отчёт без своего IP
    print_complete_report(matches, exclude_local_player=False)

    # Если нужно показать всё (например, для отладки):
    # print_complete_report(matches, exclude_local_player=False)
