# test_parser.py

import sys
from pathlib import Path

# Добавляем путь к парсерам
sys.path.insert(0, str(Path(__file__).parent))

from parsers.game_logs import GameLogParser


def test_game_log_parser():
    # Файл должен быть в той же директории или укажи полный путь
    log_path = Path("logs/game_26002356.log")

    if not log_path.exists():
        print(f"❌ Файл не найден: {log_path.absolute()}")
        print(
            "Пожалуйста, помести game_*.log в ту же директорию или укажи правильный путь"
        )
        return

    print(f"📂 Парсинг файла: {log_path.absolute()}")
    print("-" * 60)

    # Создаем и запускаем парсер
    parser = GameLogParser(str(log_path))
    data = parser.parse()

    # Выводим результаты
    print(f"🎮 Match ID: {data['match_id'] or 'Не найден'}")
    print(f"👤 Local player UID: {data['local_uid'] or 'Не найден'}")
    print(f"👥 Всего игроков найдено: {len(data['players'])}")
    print("-" * 60)

    # Список игроков
    print("📋 Список игроков:")
    for uid, player in data["players"].items():
        marker = "⭐" if uid == data["local_uid"] else "  "
        print(
            f"{marker} UID: {uid:8} | Nick: {player['nick']:20} | Role: {player.get('role', 'unknown')}"
        )

    print("-" * 60)
    print("⏱️  Сессии (время входа/выхода):")

    # Сортировка по времени входа
    sessions_sorted = sorted(
        data["sessions"], key=lambda x: x["joined_at"] or datetime.min
    )

    for session in sessions_sorted:
        join_time = (
            session["joined_at"].strftime("%H:%M:%S")
            if session["joined_at"]
            else "Unknown"
        )
        leave_time = (
            session["left_at"].strftime("%H:%M:%S")
            if session["left_at"]
            else "Still connected"
        )

        print(
            f"   {session['player_nick']:20} | In: {join_time} | Out: {leave_time} | Role: {session['role']}"
        )

    print("-" * 60)
    print("✅ Парсинг завершен")


if __name__ == "__main__":
    from datetime import datetime

    test_game_log_parser()
