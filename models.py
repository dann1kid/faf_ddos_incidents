# models.py
# Peewee ORM модели для FAF лог анализа и DDoS триангуляции

import datetime
from peewee import *



db = SqliteDatabase("faf_analysis.db")


class BaseModel(Model):
    """Базовая модель с общей БД"""

    class Meta:
        database = db


class ParsedFile(BaseModel):
    """Отслеживание уже обработанных файлов для идемпотентности"""

    path = TextField(unique=True)
    kind = TextField(index=True)  # 'GAME' | 'ICE_ADAPTER' | 'CLIENT'
    mtime = DateTimeField()
    parsed_at = DateTimeField(default=datetime.datetime.utcnow)

    class Meta:
        table_name = "parsed_files"


class Player(BaseModel):
    """Уникальный игрок по FAF UID"""

    faf_uid = IntegerField(unique=True, index=True)
    current_nick = TextField(index=True, null=True)
    ingame_name = TextField(null=True)

    first_seen_global = DateTimeField(null=True)
    last_seen_global = DateTimeField(null=True)

    is_local_player = BooleanField(default=False)
    notes = TextField(null=True)
    risk_score = FloatField(default=0.0)
    is_banned = BooleanField(default=False)

    class Meta:
        table_name = "players"


class PlayerNickname(BaseModel):
    """История ников игрока"""

    player = ForeignKeyField(Player, backref="nicknames", index=True)
    nickname = TextField(index=True)

    first_seen = DateTimeField()
    last_seen = DateTimeField(null=True)
    source = TextField()  # 'ICE_ADAPTER' | 'GAME_LOG' | 'MANUAL'

    class Meta:
        table_name = "player_nicknames"
        indexes = ((("player", "nickname", "source"), True),)


class IpAddress(BaseModel):
    """Реестр всех IP адресов"""

    ip = TextField(unique=True, index=True)
    candidate_type = TextField(index=True)  # 'host' | 'srflx' | 'relay' | 'prflx'

    is_private = BooleanField(default=False, index=True)
    is_loopback = BooleanField(default=False)
    is_relay = BooleanField(default=False)
    is_vpn_candidate = BooleanField(default=False)

    geo_country = TextField(null=True)
    asn = TextField(null=True)

    class Meta:
        table_name = "ip_addresses"


class PlayerIpLease(BaseModel):
    """Аренда IP игроком во временном интервале (динамические IP за NAT)"""

    player = ForeignKeyField(Player, backref="ip_leases", index=True)
    ip = ForeignKeyField(IpAddress, backref="leases", index=True)

    leased_from = DateTimeField(index=True, default=datetime.datetime.utcnow)
    leased_until = DateTimeField(null=True, index=True)

    source = TextField(index=True)  # 'ICE_ADAPTER' | 'GAME_LOG' | 'MANUAL'
    confidence = FloatField(default=1.0)

    class Meta:
        table_name = "player_ip_leases"
        indexes = ((("player", "ip", "leased_from", "source"), True),)


class Match(BaseModel):
    """Матч (игра)"""

    match_id = IntegerField(unique=True, index=True)
    game_id = IntegerField(null=True, index=True)  # из ice-adapter telemetry

    title = TextField(null=True)
    mapname = TextField(null=True, index=True)
    game_type = TextField(null=True)

    host = ForeignKeyField(Player, backref="hosted_matches", null=True)
    started_at = DateTimeField(null=True)
    ended_at = DateTimeField(null=True)

    ddos_detected = BooleanField(default=False)
    broken_account_suspected = BooleanField(default=False)
    ended_prematurely = BooleanField(default=False)
    suspect_players_count = IntegerField(default=0)

    source_file = TextField(null=True)
    raw_json = TextField(null=True)

    class Meta:
        table_name = "matches"


class PlayerSession(BaseModel):
    """Связь игрока с матчем (многие-ко-многим)"""

    match = ForeignKeyField(Match, backref="sessions", index=True)
    player = ForeignKeyField(Player, backref="sessions", index=True)

    joined_at = DateTimeField()
    left_at = DateTimeField(null=True)

    role = TextField(null=True)  # 'host' | 'player' | 'observer'
    team = IntegerField(null=True)

    class Meta:
        table_name = "player_sessions"
        indexes = ((("match", "player", "joined_at"), False),)


class DDoSIncident(BaseModel):
    """Зафиксированные инциденты DDoS"""

    match = ForeignKeyField(Match, backref="ddos_incidents", index=True)
    target_ip = TextField(null=True)

    detected_at = DateTimeField(index=True)
    attack_type = TextField(null=True)  # 'udp_flood' | 'icmp_flood' | 'tcp_syn'
    packets_per_second_peak = IntegerField(null=True)
    mitigated = BooleanField(default=False)

    class Meta:
        table_name = "ddos_incidents"


def init_database():
    """Создаёт все таблицы в БД"""
    db.create_tables(
        [
            ParsedFile,
            Player,
            PlayerNickname,
            IpAddress,
            PlayerIpLease,
            Match,
            PlayerSession,
            DDoSIncident,
        ]
    )
    print("✅ Таблицы созданы в faf_analysis.db")
