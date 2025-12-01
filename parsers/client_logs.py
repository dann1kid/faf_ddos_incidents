from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
import re
import json
from pathlib import Path

@dataclass
class IceCandidate:
    player_uid: int
    ip: str
    type: str
    time_connected: datetime
    time_disconnected: datetime | None = None

@dataclass
class CandidatesCollection:
    candidates: List[IceCandidate]

class ClientLogParser:
    """Улучшенный парсер client.log с отладкой"""
    
    # Более точная регулярка для ICE message
    ICE_MESSAGE_PATTERN = re.compile(
        r"ICE message for connection '(\d+)/(\d+)':\s*(\{.*?\})\s*$",
        re.DOTALL | re.MULTILINE
    )
    
    # Альтернативный паттерн на всякий случай
    ICE_SIMPLE_PATTERN = re.compile(
        r"ICE message for connection '(\d+)/(\d+)'"
    )
    
    DISCONNECT_PATTERN = re.compile(
        r"Message from game: 'Disconnected' '\[(.*?)\]'"
    )
    
    TIMESTAMP_PATTERN = re.compile(r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{2}:\d{2})')
    
    def __init__(self, log_file_path: str):
        self.file_path = Path(log_file_path)
        self.candidates: List[IceCandidate] = []
        self.disconnect_events: dict[int, datetime] = {}
        self.ice_count = 0  # DEBUG
        self.debug_lines = []  # DEBUG
    
    def parse(self) -> CandidatesCollection:
        with open(self.file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # Разбиваем на строки для timestamp
        lines = content.splitlines()
        
        for line_num, line in enumerate(lines, 1):
            self._process_line(line, line_num)
        
        print(f"DEBUG: Обработано строк: {len(lines)}")
        print(f"DEBUG: Найдено ICE сообщений: {self.ice_count}")
        print(f"DEBUG: Найдено disconnect: {len(self.disconnect_events)}")
        print(f"DEBUG: Первая проблемная строка: {self.debug_lines[:1] if self.debug_lines else 'OK'}")
        
        self._apply_disconnect_times()
        return CandidatesCollection(candidates=self.candidates)
    
    def _process_line(self, line: str, line_num: int):
        timestamp_match = self.TIMESTAMP_PATTERN.match(line)
        if not timestamp_match:
            return
        
        timestamp_str = timestamp_match.group(1)
        try:
            # Правильно парсим timezone
            dt = datetime.fromisoformat(timestamp_str)
        except ValueError:
            return
        
        # Пробуем основной паттерн ICE
        ice_match = self.ICE_MESSAGE_PATTERN.search(line)
        if ice_match:
            self.ice_count += 1
            self._parse_ice_message(ice_match, dt)
            return
        
        # Пробуем простой паттерн (только для отладки)
        simple_match = self.ICE_SIMPLE_PATTERN.search(line)
        if simple_match:
            self.debug_lines.append(f"Line {line_num}: {line[:200]}...")
    
        # Disconnect
        disconnect_match = self.DISCONNECT_PATTERN.search(line)
        if disconnect_match:
            self._parse_disconnect_message(disconnect_match, dt)
    
    def _parse_ice_message(self, match: re.Match, timestamp: datetime):
        """Упрощенный парсинг ICE"""
        src_uid = int(match.group(1))
        dest_uid = int(match.group(2))
        json_str = match.group(3).strip()
        
        print(f"DEBUG: Парсим ICE для {src_uid}/{dest_uid}")
        print(f"DEBUG: JSON fragment: {json_str[:300]}...")
        
        try:
            data = json.loads(json_str)
            candidates = data.get('candidates', [])
            print(f"DEBUG: Найдено кандидатов: {len(candidates)}")
            
            for cand in candidates:
                ip = cand.get('ip', '')
                cand_type = cand.get('type', '')
                if not ip:
                    continue
                self.candidates.append(IceCandidate(
                    player_uid=src_uid,   # или owner_uid = data['srcId']
                    ip=ip,
                    type=cand_type,
                    time_connected=timestamp,
                ))
                print(f"DEBUG: Добавлен кандидат: {ip} ({cand_type})")
                    
        except json.JSONDecodeError as e:
            print(f"DEBUG: JSON ошибка: {e}")
            print(f"DEBUG: Попытка парсинга: {json_str[:500]}")
    
    def _parse_disconnect_message(self, match: re.Match, timestamp: datetime):
        uids_str = match.group(1)
        uids = re.findall(r'\d+', uids_str)
        for uid_str in uids:
            uid = int(uid_str)
            self.disconnect_events[uid] = timestamp
    
    def _apply_disconnect_times(self):
        for candidate in self.candidates:
            if candidate.player_uid in self.disconnect_events:
                candidate.time_disconnected = self.disconnect_events[candidate.player_uid]

# Тест
if __name__ == "__main__":
    parser = ClientLogParser("client.log.2025-11-26.0.log")
    result = parser.parse()
    
    print(f"\nИТОГО reflexive candidates: {len(result.candidates)}")
    for cand in result.candidates:
        print(f"  UID {cand.player_uid}: {cand.ip} ({cand.type})")
