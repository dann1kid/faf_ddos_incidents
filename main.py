# main.py (обновлённая версия с интеграцией парсеров)
import argparse
import sys

from config import logger, LOGS_DIR, DB_PATH
from models import init_db

# Импортируем парсеры
from parsers.game_logs import parse_game_logs
from parsers.client_logs import parse_client_logs
from analysis import generate_suspect_report, print_report


def cmd_init_db(args):
    """Инициализация БД"""
    if DB_PATH.exists():
        logger.warning(f"Database already exists at {DB_PATH}")
        if not args.force:
            logger.info("Use --force to reinitialize")
            return
        DB_PATH.unlink()
        logger.info("Deleted existing database")

    init_db()
    logger.info("✓ Database initialized")


def cmd_load_game_logs(args):
    """Загрузить все game_*.log из директории"""
    if not LOGS_DIR.exists():
        logger.error(f"Logs directory not found: {LOGS_DIR}")
        return

    game_logs = list(LOGS_DIR.glob("game_*.log"))
    if not game_logs:
        logger.warning(f"No game logs found in {LOGS_DIR}")
        return

    logger.info(f"Found {len(game_logs)} game logs")

    # Вызываем парсер
    parsed_count = parse_game_logs(game_logs)
    logger.info(f"✓ Successfully parsed {parsed_count} game logs")


def cmd_load_client_logs(args):
    """Загрузить все client.log.*.0.log из директории"""
    if not LOGS_DIR.exists():
        logger.error(f"Logs directory not found: {LOGS_DIR}")
        return

    client_logs = list(LOGS_DIR.glob("client.log.*.0.log"))
    if not client_logs:
        logger.warning(f"No client logs found in {LOGS_DIR}")
        return

    logger.info(f"Found {len(client_logs)} client logs")

    # Вызываем парсер
    events_count = parse_client_logs(client_logs, skip_existing=not args.reparse)
    logger.info(f"✓ Parsed {events_count} connection events from client logs")


def cmd_rebuild_all(args):
    """Пересчитать всё с нуля: drop DB, create fresh, load all logs"""
    logger.warning("Rebuilding entire database...")

    if DB_PATH.exists():
        DB_PATH.unlink()
        logger.info("Deleted old database")

    cmd_init_db(argparse.Namespace(force=True))
    cmd_load_game_logs(argparse.Namespace(reparse=True))
    cmd_load_client_logs(argparse.Namespace(reparse=True))

    logger.info("✓ Database rebuild complete")


def cmd_status(args):
    """Показать статус БД: кол-во игроков, матчей, IP и т.п."""
    logger.info("Database status:")
    logger.info(f"  DB: {DB_PATH}")
    logger.info(f"  Logs directory: {LOGS_DIR}")

    # Считаем записи
    from models import Player, Match, IpAddress, ConnectionEvent

    player_count = Player.select().count()
    match_count = Match.select().count()
    ip_count = IpAddress.select().count()
    event_count = ConnectionEvent.select().count()

    logger.info(f"  Players: {player_count}")
    logger.info(f"  Matches: {match_count}")
    logger.info(f"  IP addresses: {ip_count}")
    logger.info(f"  Connection events: {event_count}")


def cmd_report_suspects(args):
    """Генерировать отчёт по подозрительным игрокам/IP"""
    logger.info("Generating suspect report...")

    # Вызываем аналитику
    report = generate_suspect_report(min_recurring_matches=args.min_occurrences)
    print_report(report)


def main():
    parser = argparse.ArgumentParser(
        description="FAF Logs Parser: correlate matches, players, IPs to investigate DDoS patterns"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ==================== INIT DB ====================
    init_parser = subparsers.add_parser("init-db", help="Initialize database")
    init_parser.add_argument(
        "--force", action="store_true", help="Force reinitialize (delete existing DB)"
    )
    init_parser.set_defaults(func=cmd_init_db)

    # ==================== LOAD GAME LOGS ====================
    game_parser = subparsers.add_parser("load-game-logs", help="Parse game_*.log files")
    game_parser.add_argument(
        "--reparse", action="store_true", help="Reparse even if file already processed"
    )
    game_parser.set_defaults(func=cmd_load_game_logs)

    # ==================== LOAD CLIENT LOGS ====================
    client_parser = subparsers.add_parser(
        "load-client-logs", help="Parse client.log.*.0.log files"
    )
    client_parser.add_argument(
        "--reparse", action="store_true", help="Reparse even if file already processed"
    )
    client_parser.set_defaults(func=cmd_load_client_logs)

    # ==================== REBUILD ALL ====================
    rebuild_parser = subparsers.add_parser(
        "rebuild-all", help="Rebuild entire DB from scratch (drop + init + load all)"
    )
    rebuild_parser.set_defaults(func=cmd_rebuild_all)

    # ==================== STATUS ====================
    status_parser = subparsers.add_parser("status", help="Show database status")
    status_parser.set_defaults(func=cmd_status)

    # ==================== REPORT SUSPECTS ====================
    report_parser = subparsers.add_parser(
        "report-suspects", help="Generate suspect report"
    )
    report_parser.add_argument(
        "--min-occurrences",
        type=int,
        default=2,
        help="Minimum match occurrences to flag as suspect (default: 2)",
    )
    report_parser.set_defaults(func=cmd_report_suspects)

    # ==================== PARSE ARGS ====================
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    try:
        args.func(args)
    except Exception as e:
        logger.exception(f"Error in command '{args.command}': {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
