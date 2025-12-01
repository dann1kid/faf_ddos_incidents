# ARCHITECTURE.md

## Архитектура FAF Logs Parser

### High-Level Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│                      Входные данные                                  │
│  game_*.log (матчи, игроки, подключения)                            │
│  client.log.*.0.log (ICE события, IP адреса)                        │
└────────────────────────┬─────────────────────────────────────────────┘
                         │
                         ▼
        ┌────────────────────────────────────┐
        │   Парсеры (parsers/*.py)           │
        │                                    │
        │  ├─ game_logs.py                   │
        │  │  └─ Regex + File I/O            │
        │  │     └─ Извлечение игроков,     │
        │  │        матчей, IP               │
        │  │                                 │
        │  └─ client_logs.py                 │
        │     └─ Regex + Timestamp parsing   │
        │        └─ ICE события, IP типы    │
        │                                    │
        └────────────────────────────────────┘
                         │
                         ▼
        ┌────────────────────────────────────┐
        │   Нормализация & Дедупликация      │
        │   (db.atomic() + get_or_create)   │
        └────────────────────────────────────┘
                         │
                         ▼
        ┌────────────────────────────────────┐
        │         SQLite БД                  │
        │   (models.py + peewee ORM)         │
        │                                    │
        │  Таблицы:                          │
        │  ├─ players                        │
        │  ├─ matches                        │
        │  ├─ match_players (M:M)           │
        │  ├─ ip_addresses                   │
        │  ├─ player_ips (M:M)              │
        │  ├─ connection_events              │
        │  └─ parsed_files                   │
        │                                    │
        └────────────────────────────────────┘
                         │
                         ▼
        ┌────────────────────────────────────┐
        │      Аналитика (analysis.py)       │
        │                                    │
        │  Запросы:                          │
        │  ├─ find_recurring_players()      │
        │  ├─ find_shared_ips()             │
        │  ├─ get_player_matches()          │
        │  ├─ get_match_players()           │
        │  └─ generate_suspect_report()    │
        │                                    │
        └────────────────────────────────────┘
                         │
                         ▼
        ┌────────────────────────────────────┐
        │     Отчёты & Результаты           │
        │                                    │
        │  Вывод:                            │
        │  ├─ Повторяющиеся игроки          │
        │  ├─ Общие IP адреса (alt акки?)  │
        │  ├─ Подозрительные комбинации    │
        │  └─ JSON/CSV экспорт (TODO)      │
        │                                    │
        └────────────────────────────────────┘
```

### Особенности дизайна

#### 1. Парсеры (Parsers)

- **Stateless**: каждый файл парсится независимо
- **Regex-based**: простые регулярные выражения (не полные парсеры)
- **Idempotent**: `ParsedFile` таблица отслеживает уже обработанные файлы
- **Transactional**: `db.atomic()` гарантирует консистентность

Пример:
```python
with db.atomic():
    # Все операции либо успешны, либо откатываются
    player = get_or_create_player(uid, nick)
    ip = get_or_create_ip(ip_str)
    PlayerIp.get_or_create(player=player, ip=ip, ...)
```

#### 2. Модели (Models)

Нормализация «многие-ко-многим» без потери информации:

```
Player ────┐
           ├─── MatchPlayer ──── Match
           │
MatchPlayer (отслеживает: какой игрок в каком матче, команда, роль)

Player ────┐
           ├─── PlayerIp ──── IpAddress
           │
PlayerIp (отслеживает: когда впервые/в последний раз видели IP для игрока)
```

**Преимущества:**
- Один игрок → множество IP
- Один IP → множество игроков (alt акки, NAT, прокси)
- Один матч → множество игроков
- Один игрок → множество матчей

#### 3. Connection Events

Детальный лог всех ICE/P2P событий с таймштампами:
- Помогает триангулировать время атак
- Позволяет реконструировать граф соединений в момент матча
- Можно искать аномалии (sudden disconnects, reconnects)

#### 4. Аналитика (Analysis)

Встроенные запросы для поиска паттернов:
- Игроки, присутствующие в разных матчах (возможные alt акки или модераторы)
- IP, используемые несколькими аккаунтами (alt акки, шара VPN)
- Временные корреляции (когда DDoS начался, кто был online в тот момент)

### Обработка ошибок

```python
# Валидация IP
def _is_valid_ip(ip_str):
    try:
        ipaddress.ip_address(ip_str)
        return True
    except:
        return False

# Graceful fallback
try:
    player = Player.get(Player.faf_id == faf_id)
except Player.DoesNotExist:
    player, _ = Player.get_or_create(
        faf_id=faf_id,
        defaults={'current_nick': f'UNKNOWN_{faf_id}'}
    )
```

### Перфоманс

- **Batch inserts**: использование `db.atomic()` для группировки операций
- **Indexes**: на часто используемых полях (faf_id, ip, timestamp)
- **Incremental parsing**: `ParsedFile` таблица избегает переобработки

### Расширяемость

Легко добавить:
1. Новые типы логов (например, relay logs)
2. Новые анализы (хронологический анализ, граф-аналитика)
3. Экспорт (CSV, JSON, HTML отчёты)
4. Web UI (Flask + шаблоны)
5. Распределённая обработка (Celery для параллельного парсинга)

### Потенциальные улучшения

```python
# 1. GeoIP обогащение
from geoip2 import georeader
ip.country = reader.country(ip.ip).country.name

# 2. Кросс-матч анализ
def find_match_groups(min_players=3):
    """Найти матчи с одинаковым составом игроков"""
    ...

# 3. Граф анализ (NetworkX)
def build_connection_graph(match_id):
    """Построить граф P2P соединений в матче"""
    ...

# 4. Временной анализ (Pandas)
def correlate_with_ddos(ddos_events):
    """Коррелировать события матчей с DDoS атаками"""
    ...

# 5. ML детекция ботов
def detect_bot_behavior(player_id):
    """Найти паттерны поведения ботов"""
    ...
```
