from parsers.client_logs import ClientLogParser
from pathlib import Path
from icecream import ic

if __name__ == "__main__":
    parser = ClientLogParser(Path("./logs/client.log.2025-11-28.0.log"))
    result = parser.parse()
    ic(result)
    
    print(f"Найдено reflexive candidates: {len(result.candidates)}")
    for cand in result.candidates[:5]:  # Первые 5
        print(f"UID {cand.player_uid}: {cand.ip} ({cand.type}) "
              f"[{cand.time_connected} -> {cand.time_disconnected}]")
        