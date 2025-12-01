"""
Database models for FAF log analysis.

This module defines the Peewee ORM models for storing:
- Players and their nicknames
- IP addresses and their associations with players
- Matches and player sessions
- Connection events and IP leases
"""
import datetime
from peewee import (
    SqliteDatabase,
    Model,
    IntegerField,
    TextField,
    DateTimeField,
    BooleanField,
    FloatField,
    ForeignKeyField,
)

db = SqliteDatabase('logs.db')


class BaseModel(Model):
    class Meta:
        database = db


class Player(BaseModel):
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
        table_name = 'players'


class PlayerNickname(BaseModel):
    player = ForeignKeyField(Player, backref='nicknames', index=True)
    nickname = TextField(index=True)

    first_seen = DateTimeField()
    last_seen = DateTimeField(null=True)

    source = TextField()  # e.g. 'GAME_LOG', 'ICE_LOG', 'MANUAL'

    class Meta:
        table_name = 'player_nicknames'
        indexes = (
            (('player', 'nickname', 'source'), True),
        )


class IpAddress(BaseModel):
    ip = TextField(unique=True, index=True)

    is_private = BooleanField(default=False, index=True)
    is_loopback = BooleanField(default=False)
    is_relay = BooleanField(default=False)
    is_vpn_candidate = BooleanField(default=False)

    geo_country = TextField(null=True)
    asn = TextField(null=True)

    class Meta:
        table_name = 'ip_addresses'


class PlayerIpLease(BaseModel):
    """Represents a lease/association between a player and an IP address.
    
    Tracks when a player was seen using a specific IP address, with source
    information (ICE_HOST, ICE_REFLEXIVE, ICE_RELAY, GAME_LOG, MANUAL) and
    confidence level.
    """
    player = ForeignKeyField(Player, backref='ip_leases', index=True)
    ip = ForeignKeyField(IpAddress, backref='leases', index=True)

    leased_from = DateTimeField(index=True, default=datetime.datetime.utcnow)
    leased_until = DateTimeField(null=True, index=True)

    source = TextField(index=True)  # 'ICE_HOST', 'ICE_REFLEXIVE', 'ICE_RELAY', 'GAME_LOG', 'MANUAL'
    confidence = FloatField(default=1.0)

    class Meta:
        table_name = 'player_ip_leases'
        indexes = (
            (('player', 'ip', 'leased_from', 'source'), True),
        )


class Match(BaseModel):
    match_id = IntegerField(unique=True, index=True)

    title = TextField(null=True)
    mapname = TextField(null=True, index=True)
    game_type = TextField(null=True)

    host = ForeignKeyField(Player, backref='hosted_matches', null=True)

    started_at = DateTimeField(null=True)
    ended_at = DateTimeField(null=True)

    ddos_detected = BooleanField(default=False)
    ddos_start = DateTimeField(null=True)
    network_quality_metrics = TextField(null=True)  # JSON blob as text
    suspect_players_count = IntegerField(default=0)

    source_file = TextField(null=True)
    raw_json = TextField(null=True)

    class Meta:
        table_name = 'matches'


class PlayerSession(BaseModel):
    match = ForeignKeyField(Match, backref='sessions', index=True)
    player = ForeignKeyField(Player, backref='sessions', index=True)

    joined_at = DateTimeField()
    left_at = DateTimeField(null=True)

    role = TextField(null=True)  # 'host', 'player', 'observer'
    team = IntegerField(null=True)

    class Meta:
        table_name = 'player_sessions'
        indexes = (
            (('match', 'player', 'joined_at'), False),
        )


class ParsedFile(BaseModel):
    path = TextField(unique=True)
    kind = TextField(index=True)  # 'GAME' | 'CLIENT'
    mtime = DateTimeField()
    parsed_at = DateTimeField(default=datetime.datetime.utcnow)

    class Meta:
        table_name = 'parsed_files'


class DDoSIncident(BaseModel):
    match = ForeignKeyField(Match, backref='ddos_incidents', index=True)
    target_ip = TextField(null=True)
    detected_at = DateTimeField(index=True)
    attack_type = TextField(null=True)  # 'udp_flood', 'icmp_flood', 'tcp_syn'
    packets_per_second_peak = IntegerField(null=True)
    mitigated = BooleanField(default=False)

    class Meta:
        table_name = 'ddos_incidents'