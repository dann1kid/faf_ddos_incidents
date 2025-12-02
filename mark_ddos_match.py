# cli.py
import typer
from models import Match, PlayerSession, DDoSIncident, PlayerIpLease, IpAddress, Player, ParsedFile, db
from pathlib import Path
from main import scan_and_aggregate
from config import config

from typing import Optional
import datetime


app = typer.Typer(help="FAF DDoS Analysis CLI")


# Callback для загрузки конфига при старте
@app.callback()
def main(
    config_file: Optional[Path] = typer.Option(None, "--config", "-c", help="Путь к конфигу TOML"),
    logs_dir: Optional[Path] = typer.Option(None, "--logs", "-l", help="Путь к логам (перезаписывает конфиг)"),
):
    """
    FAF DDoS Analysis CLI — анализ логов и триангуляция IP
    """
    # Перезагрузка конфига если указан файл
    if config_file:
        global config
        config = Config(config_file)
    
    # Перезаписываем logs_dir если передан в CLI
    if logs_dir:
        config.logs_dir = logs_dir
        

@app.command()
def list_matches(
    ddos_only: bool = typer.Option(False, "--ddos", help="Показать только матчи с DDoS")
):
    """Показать все матчи в базе"""
    query = Match.select()
    if ddos_only:
        query = query.where(Match.ddos_detected == True)
    
    matches = query.order_by(Match.match_id.desc())
    
    if not matches:
        typer.echo("❌ Матчи не найдены")
        return
    
    typer.echo(f"{'ID':<12} {'Game ID':<12} {'Игроков':<8} {'DDoS':<6} {'Дата начала'}")
    typer.echo("-" * 60)
    
    for m in matches:
        player_count = PlayerSession.select().where(PlayerSession.match == m).count()
        ddos_flag = "✅" if m.ddos_detected else "❌"
        start_date = m.started_at.strftime("%Y-%m-%d %H:%M") if m.started_at else "N/A"
        typer.echo(f"{m.match_id:<12} {m.game_id or 'N/A':<12} {player_count:<8} {ddos_flag:<6} {start_date}")

@app.command()
def mark_ddos(
    match_id: int = typer.Argument(..., help="ID матча для пометки как DDoS"),
    attack_type: str = typer.Option("udp_flood", "--type", help="Тип атаки: udp_flood, icmp_flood, tcp_syn"),
    pps_peak: Optional[int] = typer.Option(None, "--pps", help="Пиковый пакетов в секунду"),
):
    """Отметить матч как DDoS-инцидент"""
    success, message = mark_ddos_logic(match_id, attack_type, pps_peak)
    typer.echo(f"✅ {message}" if success else f"❌ {message}")

@app.command()
def unmark_ddos(match_id: int = typer.Argument(..., help="ID матча для снятия отметки")):
    """Снять отметку DDoS с матча"""
    success, message = unmark_ddos_logic(match_id)
    typer.echo(f"✅ {message}" if success else f"❌ {message}")


@app.command()
def report(
    match_id: Optional[int] = typer.Option(None, "--match", help="Показать отчёт по конкретному матчу"),
    ip: Optional[str] = typer.Option(None, "--ip", help="Показать все матчи, где встречался IP"),
):
    """Вывести детальный отчёт"""
    if ip:
        ip_record = IpAddress.get_or_none(IpAddress.ip == ip)
        if not ip_record:
            typer.echo(f"❌ IP {ip} не найден в базе")
            return
        
        leases = PlayerIpLease.select().where(PlayerIpLease.ip == ip_record).order_by(PlayerIpLease.leased_from.desc())
        if not leases:
            typer.echo(f"📊 IP {ip} не найден ни в одном матче")
            return
        
        typer.echo(f"📊 Отчёт по IP {ip}:")
        for lease in leases:
            player = lease.player
            typer.echo(f"  {player.faf_uid} ({player.current_nick}) в {lease.leased_from}")
        return
    
    if match_id is None:
        typer.echo("❌ Укажите --match или --ip")
        return
    
    report_text = get_match_report(match_id)
    typer.echo(report_text)


def mark_ddos_logic(match_id: int, attack_type: str = "udp_flood", pps_peak: Optional[int] = None) -> tuple[bool, str]:
    """Чистая логика пометки матча как DDoS"""
    try:
        match = Match.get(Match.match_id == match_id)
    except Match.DoesNotExist:
        return False, f"Матч {match_id} не найден в базе"
    
    # Обновляем флаг матча
    match.ddos_detected = True
    match.save()
    
    # Создаём запись инцидента
    incident = DDoSIncident.create(
        match=match,
        detected_at=datetime.datetime.utcnow(),
        attack_type=attack_type,
        packets_per_second_peak=pps_peak,
    )
    
    # Обновляем счётчик подозрительных игроков (ПРАВИЛЬНО)
    match.suspect_players_count = (
        PlayerSession
        .select()
        .join(Player)  # JOIN для доступа к risk_score
        .where(
            (PlayerSession.match == match) & 
            (Player.risk_score > 0.5)  # Используем Player.risk_score, а не PlayerSession.player.risk_score
        )
        .count()
    )
    match.save()
    
    return True, f"Матч {match_id} отмечен как DDoS (инцидент #{incident.id})"



def unmark_ddos_logic(match_id: int) -> tuple[bool, str]:
    """Чистая логика снятия отметки DDoS"""
    try:
        match = Match.get(Match.match_id == match_id)
    except Match.DoesNotExist:
        return False, f"Матч {match_id} не найден в базе"
    
    match.ddos_detected = False
    match.save()
    
    deleted_count = DDoSIncident.delete().where(DDoSIncident.match == match).execute()
    return True, f"Отметка DDoS снята с матча {match_id} (удалено {deleted_count} инцидентов)"

def get_match_report(match_id: int) -> str:
    """Генерирует текстовый отчёт по матчу"""
    try:
        match = Match.get(Match.match_id == match_id)
    except Match.DoesNotExist:
        return f"Матч {match_id} не найден в базе"
    
    sessions = (PlayerSession
                .select(PlayerSession, Player)
                .join(Player)
                .where(PlayerSession.match == match))
    
    if not sessions:
        return f"Матч {match_id} не имеет игроков в базе"
    
    lines = []
    lines.append(f"{'='*80}")
    lines.append(f"МАТЧ {match.match_id} (Game ID: {match.game_id})")
    lines.append(f"{'='*80}")
    
    for session in sessions:
        player = session.player
        ips = (PlayerIpLease
               .select()
               .where((PlayerIpLease.player == player) & 
                      (PlayerIpLease.leased_from >= session.joined_at))
               .order_by(PlayerIpLease.leased_from))
        
        ip_list = [lease.ip.ip for lease in ips]
        ip_str = ", ".join(ip_list) if ip_list else "(нет IP)"
        lines.append(f"{player.faf_uid:8} | {player.current_nick:20} | {ip_str}")
    
    return "\n".join(lines)

def update_database(logs_dir: str = "."):
    """
    Обновить базу данных новыми данными из логов.
    Пропускает уже обработанные файлы.
    """
    logs_path = Path(logs_dir)
    
    # 1. Получаем список уже обработанных файлов
    processed_files = set(
        ParsedFile.select(ParsedFile.path).where(ParsedFile.kind.in_(['GAME', 'ICE_ADAPTER']))
    )
    
    # 2. Находим все файлы логов
    game_files = list(logs_path.glob("game_*.log"))
    ice_files = list(logs_path.glob("logs/iceAdapterLogs/ice-adapter.*.log"))
    
    # 3. Фильтруем только новые файлы
    new_game_files = [f for f in game_files if str(f) not in processed_files]
    new_ice_files = [f for f in ice_files if str(f) not in processed_files]
    
    if not new_game_files and not new_ice_files:
        typer.echo("✅ Все файлы уже обработаны, обновление не требуется")
        return
    
    typer.echo(f"📂 Найдено {len(new_game_files)} новых game файлов и {len(new_ice_files)} ice-adapter файлов")
    
    # 4. Парсим и загружаем новые данные
    matches = scan_and_aggregate(logs_dir)
    
    # 5. Отмечаем файлы как обработанные
    with db.atomic():
        for file_path in new_game_files + new_ice_files:
            file_stat = file_path.stat()
            ParsedFile.get_or_create(
                path=str(file_path),
                kind='GAME' if file_path.name.startswith('game_') else 'ICE_ADAPTER',
                mtime=datetime.datetime.fromtimestamp(file_stat.st_mtime),
            )
    
    # 6. Статистика
    total_matches = Match.select().count()
    ddos_matches = Match.select().where(Match.ddos_detected == True).count()
    
    typer.echo(f"✅ Обновление завершено:")
    typer.echo(f"   - Загружено {len(matches)} новых матчей")
    typer.echo(f"   - Всего матчей в базе: {total_matches}")
    typer.echo(f"   - Отмечено как DDoS: {ddos_matches}")


@app.command()
def update():
    """Обновить базу данных новыми данными из логов"""
    typer.echo(f"📂 Используется путь к логам: {config.logs_dir}")
    update_database(str(config.logs_dir))




@app.command()
def interactive():
    """Интерактивный режим (использует путь из конфига)"""
    typer.echo(f"📂 Используется путь к логам: {config.logs_dir}")
    typer.echo("🎮 Интерактивный режим DDoS анализа")
    typer.echo("=" * 60)
    typer.echo("Команды:")
    typer.echo("  list              — показать последние 20 матчей")
    typer.echo("  mark <id>         — отметить матч как DDoС")
    typer.echo("  unmark <id>       — снять отметку DDoS")
    typer.echo("  report <id>       — детальный отчёт по матчу")
    typer.echo("  ip <ip>           — показать все матчи с этим IP")
    typer.echo("  exit / quit / q   — выйти из интерактивного режима")
    typer.echo("  update            — обновить базу данных")
    typer.echo("=" * 60)
    
    while True:
        try:
            user_input = typer.prompt("\nВведите команду")
            parts = user_input.strip().split(maxsplit=1)
            
            if not parts:
                continue
                
            command = parts[0].lower()
            
            if command in ('exit', 'quit', 'q'):
                typer.echo("👋 Выход из интерактивного режима")
                break
            
            elif command == 'list':
                matches = Match.select().order_by(Match.match_id.desc()).limit(20)
                if not matches:
                    typer.echo("❌ Матчи не найдены")
                    continue
                
                typer.echo(f"\n{'ID':<12} {'Игроков':<8} {'DDoS':<6} {'Дата начала'}")
                typer.echo("-" * 50)
                for m in matches:
                    player_count = PlayerSession.select().where(PlayerSession.match == m).count()
                    ddos_flag = "✅" if m.ddos_detected else "❌"
                    start_date = m.started_at.strftime("%Y-%m-%d %H:%M") if m.started_at else "N/A"
                    typer.echo(f"{m.match_id:<12} {player_count:<8} {ddos_flag:<6} {start_date}")
            
            elif command == 'mark' and len(parts) > 1:
                try:
                    match_id = int(parts[1])
                    success, message = mark_ddos_logic(match_id)
                    typer.echo(f"✅ {message}" if success else f"❌ {message}")
                except ValueError:
                    typer.echo("❌ Неверный формат ID матча")
                    
            elif command == 'update':
                # Обновляем базу данных
                try:
                    update_database(str(config.logs_dir))
                    typer.echo("✅ Обновление завершено успешно")
                except Exception as e:
                    typer.echo(f"❌ Ошибка при обновлении: {e}")
                continue
            
            elif command == 'unmark' and len(parts) > 1:
                try:
                    match_id = int(parts[1])
                    success, message = unmark_ddos_logic(match_id)
                    typer.echo(f"✅ {message}" if success else f"❌ {message}")
                except ValueError:
                    typer.echo("❌ Неверный формат ID матча")
            
            elif command == 'report' and len(parts) > 1:
                try:
                    match_id = int(parts[1])
                    typer.echo(get_match_report(match_id))
                except ValueError:
                    typer.echo("❌ Неверный формат ID матча")
            
            elif command == 'ip' and len(parts) > 1:
                ip = parts[1]
                report(ip=ip)
            
            else:
                typer.echo("❌ Неизвестная команда или недостаточно аргументов")
                
        except (KeyboardInterrupt, EOFError):
            typer.echo("\n👋 Выход из интерактивного режима")
            break
        

@app.command()
def shell():
    """Алиас для интерактивного режима"""
    interactive()


if __name__ == "__main__":
    app()
