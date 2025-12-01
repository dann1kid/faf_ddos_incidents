# config.py
"""
Конфигурация проекта: пути, логирование, параметры парсинга
"""

from pathlib import Path
import logging

# ==================== PATHS ====================

PROJECT_ROOT = Path(__file__).parent

# Директория с логами FAF
LOGS_DIR = PROJECT_ROOT / "logs"  # Сюда кладёшь файлы game_*.log и client.log.*.0.log

# База данных
DB_PATH = PROJECT_ROOT / "faf_logs.db"

# ==================== LOGGING ====================

LOG_LEVEL = logging.DEBUG
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

logging.basicConfig(
    level=LOG_LEVEL,
    format=LOG_FORMAT,
)

logger = logging.getLogger(__name__)

# ==================== PARSER CONFIG ====================

# Regex patterns и параметры парсинга
PARSER_CONFIG = {
    # Для game_*.log
    "game_log": {
        "patterns": {
            # ConnectToPeer (name=..., uid=..., address=..., USE PROXY)
            "connect_to_peer": r"ConnectToPeer \(name=(\S+), uid=(\d+), address=([^,]+), (.+)\)",
            # LOBBY: "nick" [host:port, uid=123] has established connections to: ...
            "player_in_lobby": r'LOBBY: "(\S+)" \[(.+):(\d+), uid=(\d+)\] has established connections to: (.*)',
            # DisconnectFromPeer (uid=...)
            "disconnect_peer": r"DisconnectFromPeer \(uid=(\d+)\)",
        }
    },
    # Для client.log.*.0.log
    "client_log": {
        "patterns": {
            # ICE connection state for peer XYZ changed to connected
            "ice_state_change": r"ICE connection state for peer (\d+) changed to (\w+)",
            # Connection between 324211 and 361113 has been established
            "connection_established": r"Connection between (\d+) and (\d+) has been established",
            # Connection between 324211 and 250109 has been lost
            "connection_lost": r"Connection between (\d+) and (\d+) has been lost",
            # ICE message for connection XXXYYY srcId..., with candidate list
            "ice_message": r"ICE message for connection (\d+)(\d+)\s+(.+)",
        }
    },
}

# ==================== PARSING OPTIONS ====================

# Временная зона логов (если указана)
LOG_TIMEZONE = "UTC"

# Пример временной метки в client.log
# 2025-11-26T002251.2280300 DEBUG
CLIENT_LOG_TIMESTAMP_FORMAT = "%Y-%m-%dT%H%M%S.%f"

# Пример временной метки в game log
# может быть другой формат

# ==================== BATCH OPTIONS ====================

# Размер батча при загрузке в БД (для оптимизации)
DB_BATCH_SIZE = 500

# ==================== PATHS CREATION ====================

if not LOGS_DIR.exists():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"Created logs directory: {LOGS_DIR}")
