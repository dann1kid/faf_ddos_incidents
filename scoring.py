# scoring.py
import datetime
import math
from models import *


def exp_decay(dt: datetime.datetime, now=None, tau_days=7):
    now = now or datetime.datetime.utcnow()
    delta = (now - dt).total_seconds()
    tau = tau_days * 86400
    return math.exp(-max(0, delta) / tau)


def recompute_risk_scores(now=None):
    now = now or datetime.datetime.utcnow()
    with db.atomic():
        for p in Player.select():
            score = 0.0

            # 1) Совпадения с DDoS-матчами
            ddos_sessions = (
                PlayerSession.select(PlayerSession, Match)
                .join(Match)
                .where((PlayerSession.player == p) & (Match.ddos_detected))
            )
            for s in ddos_sessions:
                w = exp_decay(s.joined_at or now, now)
                score += 0.3 * w
            score = min(score, 0.9)

            # 2) Совпадение target_ip с IP игрока
            incidents = DDoSIncident.select().where(
                DDoSIncident.target_ip.is_null(False)
            )
            player_ips = set(lease.ip.ip for lease in p.ip_leases)
            for inc in incidents:
                if inc.target_ip in player_ips:
                    w = exp_decay(inc.detected_at, now)
                    score += 0.7 * w

            # 3) Частота участия в помеченных матчах в окно 24ч
            day_ago = now - datetime.timedelta(hours=24)
            ddos_count = (
                PlayerSession.select()
                .join(Match)
                .where(
                    (PlayerSession.player == p)
                    & (Match.ddos_detected)
                    & (
                        (PlayerSession.joined_at >= day_ago)
                        | (PlayerSession.left_at >= day_ago)
                    )
                )
            )
            if ddos_count.count() >= 3:
                score += 0.2

            p.risk_score = max(0.0, min(1.0, score))
            p.save()


def confidence_for_candidate_type(cand_type: str, ip: str) -> float:
    cand_type = cand_type.upper()
    try:
        import ipaddress

        addr = ipaddress.ip_address(ip)
        is_public = not (addr.is_private or addr.is_loopback or addr.is_link_local)
    except ValueError:
        is_public = True
    if "SERVER_REFLEXIVE" in cand_type:
        return 1.0
    if "HOST" in cand_type:
        return 0.8 if is_public else 0.0
    if "RELAY" in cand_type:
        return 0.3
    return 0.5
