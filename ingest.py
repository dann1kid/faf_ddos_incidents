# ingest.py
from peewee import *
from models import Player, PlayerIpLease, IpAddress, Match, PlayerSession
from typing import Optional
import datetime
import ipaddress
from models import db

from structures import AggregatedMatch
from scoring import confidence_for_candidate_type


def get_or_create_player(uid: int, nick: Optional[str] = None) -> Player:
    """Получить или создать игрока по UID"""
    player, created = Player.get_or_create(
        faf_uid=uid,
        defaults={
            "current_nick": nick,
            "first_seen_global": datetime.datetime.utcnow(),
            "last_seen_global": datetime.datetime.utcnow(),
        },
    )
    if not created and nick and player.current_nick != nick:
        player.current_nick = nick
        player.save()
    return player


def get_or_create_ip(ip: str, candidate_type: str = "unknown") -> IpAddress:
    """Получить или создать IP адрес"""
    try:
        addr = ipaddress.ip_address(ip)
        is_private = addr.is_private
        is_loopback = addr.is_loopback
        is_relay = "RELAY" in candidate_type.upper()
    except:
        is_private = False
        is_loopback = False
        is_relay = False

    ip_record, _ = IpAddress.get_or_create(
        ip=ip,
        defaults={
            "candidate_type": candidate_type,
            "is_private": is_private,
            "is_loopback": is_loopback,
            "is_relay": is_relay,
        },
    )
    return ip_record


def ingest_player_ip_lease(
    player_uid: int,
    ip: str,
    source: str,
    timestamp: datetime.datetime,
    leased_until: Optional[datetime.datetime] = None,
) -> PlayerIpLease:
    """Записать аренду IP игрока"""
    player = get_or_create_player(player_uid)
    ip_record = get_or_create_ip(ip, source)

    lease, created = PlayerIpLease.get_or_create(
        player=player,
        ip=ip_record,
        leased_from=timestamp,
        source=source,
        defaults={
            "leased_until": leased_until,
            "confidence": 1.0,
        },
    )
    return lease


def ingest_player_session(
    player_uid: int,
    match_id: int,
    joined_at: datetime.datetime,
    left_at: Optional[datetime.datetime],
    role: str = "player",
) -> PlayerSession:
    """Записать сессию игрока в матче"""
    player = get_or_create_player(player_uid)
    match, _ = Match.get_or_create(
        match_id=match_id,
        defaults={
            "started_at": joined_at,
            "ended_at": left_at,
        },
    )

    session, created = PlayerSession.get_or_create(
        match=match,
        player=player,
        joined_at=joined_at,
        defaults={
            "left_at": left_at,
            "role": role,
        },
    )

    if not created and left_at:
        session.left_at = left_at
        session.save()

    return session


def ingest_match(agg_match: AggregatedMatch):
    """Загрузить весь матч со всеми игроками, IP и сессиями"""

    with db.atomic():
        # Создаём матч
        match, _ = Match.get_or_create(
            match_id=agg_match.match_id,
            defaults={
                "game_id": agg_match.game_id,
                "started_at": None,
                "ended_at": None,
            },
        )

        # Загружаем игроков
        for uid, player in agg_match.players.items():
            # Создаём игрока
            db_player = get_or_create_player(uid, player.nick)

            # Загружаем IP кандидаты
            for cand in player.all_candidates:
                ip_record = get_or_create_ip(cand.ip, cand.type)

                # ВАЖНО: используем INSERT OR IGNORE для гарантии идемпотентности
                query = PlayerIpLease.insert(
                    player=db_player,
                    ip=ip_record,
                    leased_from=cand.timestamp,
                    leased_until=None,
                    source="ICE_ADAPTER",
                    confidence=1.0,
                ).on_conflict_ignore()  # <-- SQLite расширение

                query.execute()
                conf = confidence_for_candidate_type(cand.type, cand.ip)
                PlayerIpLease.insert(
                    player=db_player,
                    ip=ip_record,
                    leased_from=cand.timestamp,
                    leased_until=None,
                    source="ICE_ADAPTER",
                    confidence=conf,
                ).on_conflict_ignore().execute()

            # Загружаем сессию
            ingest_player_session(
                player_uid=uid,
                match_id=agg_match.match_id,
                joined_at=player.joined_at or datetime.datetime.min,
                left_at=player.left_at,
                role=player.role,
            )
