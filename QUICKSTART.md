# QUICKSTART.md

## Быстрый старт за 5 минут

### Шаг 1: Установка зависимостей

```bash
pip install -r requirements.txt
```

### Шаг 2: Инициализация БД

```bash
python main.py init-db
```

**Результат:** создаётся файл `faf_logs.db` (пустая SQLite БД со всеми таблицами)

### Шаг 3: Подготовить логи

Скопировать все логи FAF в директорию `logs/`:

```bash
mkdir -p logs
cp /путь/к/game_*.log logs/
cp /путь/к/client.log.*.0.log logs/
```

Проверить:
```bash
ls logs/ | head -5
# game_25997214.log
# game_25997260.log
# game_25997456.log
# client.log.2025-11-26.0.log
# client.log.2025-11-27.0.log
```

### Шаг 4: Парсить игровые логи

```bash
python main.py load-game-logs
```

**Вывод:**
```
Parsing game log: logs/game_25997214.log
  Found ConnectToPeer: uid=324211, nick=Nucka_Sempai, addr=127.0.0.1:52930
  Found LOBBY entry: uid=197190, nick=bubushin, connections_to=...
  ...
✓ Successfully parsed logs/game_25997214.log: Match(25997214) with 12 players
✓ Parsed 3 game logs
```

**Заполнено в БД:**
- `players` — Nucka_Sempai, bubushin, ThKracken, ... (по uid)
- `matches` — Match(25997214), Match(25997260), Match(25997456)
- `match_players` — связь между игроками и матчами
- `ip_addresses` — 127.0.0.1, kubernetes.docker.internal и т.п.
- `player_ips` — сопоставление игрока ↔ IP

### Шаг 5: Парсить логи клиента

```bash
python main.py load-client-logs
```

**Вывод:**
```
Parsing client log: logs/client.log.2025-11-26.0.log
  ICE state: peer=324211 → connected
  Connection: 324211 ↔ 361113
  ICE candidates for 324211: 9 IPs extracted
    - 77.51.212.234 (SERVER_REFLEXIVE)
    - 95.165.173.218 (SERVER_REFLEXIVE)
    - 138.197.167.11 (RELAYED)
  ...
✓ Parsed 15847 events from client logs
```

**Заполнено в БД:**
- `connection_events` — все события подключений/отключений
- `ip_addresses` — дополнительно уточнены типы (REFLEXIVE, RELAYED и т.п.)
- `player_ips` — добавлены связи между игроками и их реальными WAN IP

### Шаг 6: Генерировать отчёт

```bash
python main.py report-suspects
```

**Вывод (пример):**
```
================================================================================
SUSPECT REPORT
================================================================================
Generated: 2025-11-30T04:52:31.234567

RECURRING PLAYERS (appears in multiple matches):
────────────────────────────────────────────────────────────────────────────
  #324211    | Nucka_Sempai         |  3 matches | Notes: (none)
  #197190    | bubushin             |  2 matches | Notes: (none)
  #148836    | ThKracken            |  2 matches | Notes: (none)

SHARED IPs (used by multiple players - possible alt accounts):
────────────────────────────────────────────────────────────────────────────
  77.51.212.234            (SERVER_REFLEXIVE) | 2 players
      → #324211 Nucka_Sempai
      → #197190 bubushin

SUSPICIOUS COMBINATIONS (player + IP in multiple matches):
────────────────────────────────────────────────────────────────────────────
#324211    Nucka_Sempai         ← 77.51.212.234          (3 matches)
      Match #25997214: wellCUM GAYS
      Match #25997260: wellCUM GAYS
      Match #25997456: rage quiters suck.
```

---

## Что это означает?

### RECURRING PLAYERS
Игроки, которые повторяются в разных матчах. Может указывать на:
- Активных игроков (нормально)
- Alt аккаунты одного и того же человека (подозрительно)
- Модераторов, которые вмешиваются (подозрительно)

### SHARED IPs
IP адреса, используемые несколькими разными игроками. Может указывать на:
- NAT (нормально, несколько людей за одним маршрутизатором)
- VPN/прокси (одна точка для разных аккаунтов)
- Alt аккаунты (один человек, разные ники)

### SUSPICIOUS COMBINATIONS
Комбинация (игрок + IP) повторяется в разных матчах. Это означает:
- Конкретный игрок с конкретным IP был в разных матчах
- Полезно для отслеживания того, кто действительно за компьютером

---

## Примеры использования из Python

### Найти все матчи игрока

```python
from models import Player, MatchPlayer, Match

# Найти игрока
player = Player.get(Player.faf_id == 324211)

# Получить все его матчи
matches = Match.select().join(MatchPlayer).where(MatchPlayer.player == player)

for match in matches:
    print(f"Match {match.match_id}: {match.title}")
```

### Найти всех игроков на конкретном IP

```python
from models import IpAddress, PlayerIp, Player

# Найти IP
ip = IpAddress.get(IpAddress.ip == "77.51.212.234")

# Получить всех игроков, использовавших этот IP
players = Player.select().join(PlayerIp).where(PlayerIp.ip == ip)

for player in players:
    print(f"{player.faf_id}: {player.current_nick}")
```

### Применить пользовательскую пометку

```python
from models import Player

# Найти игрока
player = Player.get(Player.faf_id == 197190)

# Отметить как подозрительного
player.is_suspect = True
player.notes = "Appears with same IP as Nucka_Sempai, likely alt account"
player.save()

print(f"✓ Marked {player.current_nick} as suspect")
```

---

## Команды CLI

```bash
# Инициализация
python main.py init-db              # Создать пустую БД
python main.py init-db --force      # Пересоздать БД (удалит данные!)

# Парсинг логов
python main.py load-game-logs       # Парсить game_*.log
python main.py load-game-logs --reparse    # Перепарсить даже уже обработанные
python main.py load-client-logs     # Парсить client.log.*.0.log
python main.py load-client-logs --reparse

# Управление
python main.py rebuild-all          # Drop DB + init + load all (с нуля)
python main.py status               # Показать статус БД

# Анализ
python main.py report-suspects      # Генерировать отчёт
python main.py report-suspects --min-occurrences 3  # Минимум 3 матча
```

---

## Если что-то пошло не так

### БД повреждена

```bash
rm faf_logs.db
python main.py init-db
python main.py load-game-logs
python main.py load-client-logs
```

### Логи не находятся

```bash
ls -la logs/
# Должны быть файлы типа:
# game_XXXXX.log
# client.log.2025-XX-XX.0.log
```

### Парсинг зависает

```bash
# Ctrl+C для остановки
# Проверить размер log файла
ls -lh logs/ | tail -5
# Если какой-то очень большой, может быть проблемой
```

### Хочу увидеть логи парсинга

```python
# В config.py измените
LOG_LEVEL = logging.DEBUG  # Вместо DEBUG
# Или в консоли запустите с DEBUG
python main.py load-game-logs  # Будет много деталей в stdout
```

---

## Архитектура в картинке

```
logs/ (game_*.log, client.log.*.0.log)
   │
   ├─→ parsers/game_logs.py ──────┐
   │                              ├─→ SQLite БД
   └─→ parsers/client_logs.py ────┤
                                  │
                    analysis.py ←─┴─→ Отчёты
```

---

## Далее

- [ ] Прочитать `README.md` для полной документации
- [ ] Изучить `models.py` для понимания структуры БД
- [ ] Запустить `analysis.py` функции для своих запросов
- [ ] Посмотреть `ARCHITECTURE.md` для деталей дизайна

---

**Вопросы?** Смотри README.md и ARCHITECTURE.md
