# FAF Logs Parser - DDoS Investigation Tool

Инструмент для анализа FAF логов с целью выявления подозрительных паттернов игроков и IP адресов.

## Структура проекта

```
.
├── config.py              # Конфигурация: пути, regex patterns
├── models.py              # Peewee модели БД
├── main.py                # CLI точка входа
├── analysis.py            # Аналитические запросы
├── parsers/
│   ├── __init__.py
│   ├── game_logs.py       # Парсер game_*.log файлов
│   └── client_logs.py     # Парсер client.log.*.0.log файлов
├── logs/                  # Директория с логами (автоматически создаётся)
└── faf_logs.db            # SQLite БД (создаётся при инициализации)
```

## Установка

```bash
# Установить зависимости
pip install peewee

# Или если используешь requirements.txt:
pip install -r requirements.txt
```

## Использование

### 1. Инициализация БД

```bash
python main.py init-db
```

Это создаст `faf_logs.db` со всеми таблицами.

### 2. Подготовить логи

Скопировать все логи FAF в директорию `logs/`:

```
logs/
├── game_25997214.log
├── game_25997260.log
├── game_25997456.log
├── client.log.2025-11-26.0.log
├── client.log.2025-11-27.0.log
└── ...
```

### 3. Загрузить game logs

```bash
python main.py load-game-logs
```

Это спарсит все `game_*.log` файлы и заполнит таблицы:
- `players` (ники и FAF UID)
- `matches` (матчи и их параметры)
- `match_players` (связь игроков с матчами)
- `ip_addresses` (IP адреса)
- `player_ips` (связь игроков с IP)

### 4. Загрузить client logs

```bash
python main.py load-client-logs
```

Это спарсит все `client.log.*.0.log` файлы и заполнит таблицы:
- `connection_events` (все ICE события)
- Дополнительно заполнит `ip_addresses` с более точными типами кандидатов

### 5. Полная переиндексация

Если нужно с нуля пересчитать всё:

```bash
python main.py rebuild-all
```

### 6. Генерировать отчёт

```bash
python main.py report-suspects --min-occurrences 2
```

Это выведет:
- Игроков, повторяющихся в разных матчах
- IP адреса, используемые несколькими игроками (alt аккаунты?)
- Подозрительные комбинации (игрок + IP в разных матчах)

## Схема БД

### Основные таблицы

**players**
- `id` (PK)
- `faf_id` (unique) — UID из логов FAF
- `current_nick` — текущий ник
- `first_seen`, `last_seen` — когда виден был впервые/в последний раз
- `is_suspect` — флаг подозрительности
- `notes` — пользовательские примечания

**matches**
- `id` (PK)
- `match_id` (unique) — UID из имени файла game_*.log
- `title`, `mapname`, `game_type`
- `host` (FK → Player)
- `started_at`, `ended_at` — таймштампы
- `raw_json`, `source_file`

**match_players** (многие-ко-многим: игрок ↔ матч)
- `id` (PK)
- `match` (FK)
- `player` (FK)
- `team` — номер команды
- `role` — 'host', 'player', 'observer'
- `first_seen`, `last_seen`

**ip_addresses**
- `id` (PK)
- `ip` (unique) — строка IP
- `is_private` — RFC1918?
- `kind` — 'HOST', 'SERVER_REFLEXIVE', 'RELAYED', 'UNKNOWN'
- `asn`, `country` — опционально

**player_ips** (многие-ко-многим: игрок ↔ IP)
- `id` (PK)
- `player` (FK)
- `ip` (FK)
- `first_seen`, `last_seen`
- `source` — 'ICE', 'GAME_LOG', 'MANUAL'

**connection_events**
- `id` (PK)
- `timestamp`
- `src_player` (FK) — инициировавший
- `dst_player` (FK) — с кем соединялся
- `match` (FK) — если известен
- `event_type` — 'ICE_CONNECTED', 'PEER_CONNECTED', 'PEER_DISCONNECTED' и т.п.
- `raw` — оригинальный текст из лога

**parsed_files**
- `id` (PK)
- `path` (unique) — полный путь к файлу
- `kind` — 'GAME', 'CLIENT'
- `mtime` — время модификации при парсинге
- `parsed_at` — когда был спарсён

## Примеры запросов

### Найти все матчи конкретного игрока

```python
from models import Player, MatchPlayer, Match

player = Player.get(Player.faf_id == 324211)
matches = Match.select().join(MatchPlayer).where(MatchPlayer.player == player)

for match in matches:
    print(f"Match {match.match_id}: {match.title}")
```

### Найти все игроки, использовавшие конкретный IP

```python
from models import IpAddress, PlayerIp, Player

ip = IpAddress.get(IpAddress.ip == "77.51.212.234")
players = Player.select().join(PlayerIp).where(PlayerIp.ip == ip)

for player in players:
    print(f"{player.faf_id}: {player.current_nick}")
```

### Найти IP адреса, используемые несколькими игроками

```python
from analysis import find_shared_ips

shared = find_shared_ips(min_players=2)
for ip, count, players in shared:
    print(f"{ip.ip}: {count} players")
    for p in players:
        print(f"  - {p.current_nick}")
```

## Логирование

По умолчанию уровень DEBUG. Для изменения:

```python
# В config.py
LOG_LEVEL = logging.INFO  # или WARNING
```

## Оптимизация

- Индексы создаются автоматически для часто используемых полей
- Парсеры используют `db.atomic()` для групповых операций
- `ParsedFile` отслеживает обработанные файлы, чтобы избежать повторной парсинга

## TODO

- [ ] Экспорт отчётов в CSV/JSON
- [ ] Кросс-матч анализ (когда вместе были одни же игроки в разных матчах)
- [ ] Временной анализ (корреляция DDoS с появлением подозрительных IP)
- [ ] GeoIP обогащение (определить страну/ASN для IP)
- [ ] Web UI для просмотра БД
- [ ] Автоматический импорт когда матчи закончились
- [ ] Детекция ботов по паттернам поведения

## Лицензия

MIT
