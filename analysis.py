# analysis.py
"""
Аналитика: запросы для поиска подозрительных паттернов
"""

import logging
from datetime import datetime
from typing import List, Dict, Tuple

from models import Player, Match, MatchPlayer, IpAddress, PlayerIp, ConnectionEvent, db

logger = logging.getLogger(__name__)


def get_player_matches(player_id: int) -> List[Tuple[Match, MatchPlayer]]:
    """Получить все матчи игрока"""
    return (
        Match.select(Match, MatchPlayer)
        .join(MatchPlayer)
        .where(MatchPlayer.player_id == player_id)
        .tuples()
    )


def get_match_players(match_id: int) -> List[Tuple[Player, MatchPlayer]]:
    """Получить всех игроков матча с их ролями"""
    return (
        Player.select(Player, MatchPlayer)
        .join(MatchPlayer)
        .where(MatchPlayer.match_id == match_id)
        .tuples()
    )


def get_player_ips(player_id: int) -> List[IpAddress]:
    """Получить все IP адреса, которые когда-либо использовал игрок"""
    return (
        IpAddress.select()
        .join(PlayerIp)
        .where(PlayerIp.player_id == player_id)
        .distinct()
    )


def get_ip_players(ip_id: int) -> List[Player]:
    """Получить всех игроков, которые использовали конкретный IP"""
    return Player.select().join(PlayerIp).where(PlayerIp.ip_id == ip_id).distinct()


def find_recurring_players(min_matches: int = 2) -> List[Tuple[Player, int]]:
    """
    Найти игроков, которые повторяются в разных матчах

    Args:
        min_matches: минимальное количество матчей

    Returns:
        List[(Player, match_count)]
    """
    query = (
        Player.select(Player, db.fn.COUNT(MatchPlayer.id).alias("match_count"))
        .join(MatchPlayer)
        .group_by(Player)
        .having(db.fn.COUNT(MatchPlayer.id) >= min_matches)
        .order_by(db.fn.COUNT(MatchPlayer.id).desc())
    )

    return [(p, p.match_count) for p in query]


def find_shared_ips(min_players: int = 2) -> List[Tuple[IpAddress, int, List[Player]]]:
    """
    Найти IP адреса, которые использовали несколько разных игроков
    Это может указывать на NAT, прокси или смурфов

    Args:
        min_players: минимальное количество игроков на IP

    Returns:
        List[(IpAddress, player_count, [Player])]
    """
    result = []

    for ip in IpAddress.select():
        players = list(get_ip_players(ip.id))

        if len(players) >= min_players:
            result.append((ip, len(players), players))

    return sorted(result, key=lambda x: x[1], reverse=True)


def find_ip_changes_in_match(
    match_id: int,
) -> Dict[Player, List[Tuple[IpAddress, int]]]:
    """
    Для матча, показать какие IP использовал каждый игрок
    (может быть несколько IP за сессию)

    Args:
        match_id: ID матча

    Returns:
        {Player: [(IpAddress, count_occurrences), ...]}
    """
    result = {}

    for mp in MatchPlayer.select().where(MatchPlayer.match_id == match_id):
        player = mp.player
        ips = get_player_ips(player.id)

        # Считать occurrence каждого IP для этого игрока
        ip_counts = {}
        for ip in ips:
            # Подсчитать, сколько раз этот IP упоминался в ConnectionEvents
            count = (
                ConnectionEvent.select()
                .join(PlayerIp)
                .where(
                    (ConnectionEvent.src_player == player)
                    | (ConnectionEvent.dst_player == player)
                )
                .count()
            )
            ip_counts[ip] = count

        result[player] = sorted(ip_counts.items(), key=lambda x: x[1], reverse=True)

    return result


def find_matches_with_player_ip_combination(player_id: int, ip_id: int) -> List[Match]:
    """
    Найти все матчи, где конкретный игрок использовал конкретный IP
    """
    # Это сложный запрос: нужно джойнить через временные окна
    # Упрощённо: найти матчи где был игрок, и есть события с этим IP

    player = Player.get_by_id(player_id)

    matches = []
    for mp in MatchPlayer.select().where(MatchPlayer.player_id == player_id):
        match = mp.match

        # Проверить, были ли события этого игрока с этим IP во время матча
        # (если есть таймштампы)
        if match.started_at and match.ended_at:
            event_count = (
                ConnectionEvent.select()
                .join(PlayerIp)
                .where(
                    (ConnectionEvent.src_player == player)
                    & (ConnectionEvent.timestamp >= match.started_at)
                    & (ConnectionEvent.timestamp <= match.ended_at)
                    & (PlayerIp.ip_id == ip_id)
                )
                .count()
            )

            if event_count > 0:
                matches.append(match)

    return matches


def generate_suspect_report(
    min_recurring_matches: int = 2, min_shared_ip_players: int = 2
) -> Dict:
    """
    Генерировать отчёт по подозрительным паттернам

    Args:
        min_recurring_matches: минимальное повторение в матчах
        min_shared_ip_players: минимальное количество игроков на одном IP

    Returns:
        Dict с результатами анализа
    """
    logger.info("Generating suspect report...")

    report = {
        "generated_at": datetime.now().isoformat(),
        "recurring_players": [],
        "shared_ips": [],
        "suspicious_combinations": [],
    }

    # 1. Игроки, повторяющиеся в матчах
    logger.info("Analyzing recurring players...")
    recurring = find_recurring_players(min_matches=min_recurring_matches)
    for player, count in recurring[:20]:  # Топ 20
        report["recurring_players"].append(
            {
                "faf_id": player.faf_id,
                "nick": player.current_nick,
                "match_count": count,
                "is_suspect": player.is_suspect,
                "notes": player.notes,
            }
        )

    # 2. IP адреса, используемые несколькими игроками
    logger.info("Analyzing shared IPs...")
    shared_ips = find_shared_ips(min_players=min_shared_ip_players)
    for ip, player_count, players in shared_ips[:20]:  # Топ 20
        report["shared_ips"].append(
            {
                "ip": ip.ip,
                "is_private": ip.is_private,
                "kind": ip.kind,
                "player_count": player_count,
                "players": [
                    {"faf_id": p.faf_id, "nick": p.current_nick} for p in players
                ],
            }
        )

    # 3. Подозрительные комбинации (игрок + IP в разных матчах)
    logger.info("Analyzing suspicious combinations...")
    for player, _ in recurring[:10]:  # Проверить топ 10 повторяющихся
        ips = get_player_ips(player.id)

        for ip in ips:
            matches = find_matches_with_player_ip_combination(player.id, ip.id)

            if len(matches) >= min_recurring_matches:
                report["suspicious_combinations"].append(
                    {
                        "player": {
                            "faf_id": player.faf_id,
                            "nick": player.current_nick,
                        },
                        "ip": ip.ip,
                        "match_count": len(matches),
                        "matches": [
                            {"match_id": m.match_id, "title": m.title}
                            for m in matches[:5]
                        ],
                    }
                )

    logger.info("✓ Report generated")
    return report


def print_report(report: Dict):
    """Красиво вывести отчёт"""
    print("\n" + "=" * 80)
    print("SUSPECT REPORT")
    print("=" * 80)
    print(f"Generated: {report['generated_at']}\n")

    print("RECURRING PLAYERS (appears in multiple matches):")
    print("-" * 80)
    for item in report["recurring_players"]:
        suspect_mark = "⚠️ " if item["is_suspect"] else "  "
        print(
            f"{suspect_mark}#{item['faf_id']:6d} | {item['nick']:20s} | "
            f"{item['match_count']:2d} matches | "
            f"Notes: {item['notes'] or '(none)'}"
        )

    print("\n\nSHARED IPs (used by multiple players - possible alt accounts):")
    print("-" * 80)
    for item in report["shared_ips"]:
        kind = f"({item['kind']})" if not item["is_private"] else "(LOCAL)"
        print(f"  {item['ip']:20s} {kind:20s} | {item['player_count']} players")
        for p in item["players"]:
            print(f"      → #{p['faf_id']:6d} {p['nick']}")

    print("\n\nSUSPICIOUS COMBINATIONS (player + IP in multiple matches):")
    print("-" * 80)
    for item in report["suspicious_combinations"]:
        player = item["player"]
        print(
            f"#{player['faf_id']:6d} {player['nick']:20s} ← {item['ip']:20s} "
            f"({item['match_count']} matches)"
        )
        for m in item["matches"]:
            print(f"      Match #{m['match_id']}: {m['title']}")

    print("\n" + "=" * 80 + "\n")
