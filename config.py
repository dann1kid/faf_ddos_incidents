# config.py
import os
import tomllib
from pathlib import Path
from typing import Optional


class Config:
    """Конфигурация приложения"""

    def __init__(self, config_path: Optional[Path] = None):
        search_paths = [
            config_path,
            Path("faf_config.toml"),
            Path.home() / ".faf_analysis" / "config.toml",
            Path("/etc/faf_analysis/config.toml"),
        ]

        self.data = {}
        self._load_config(search_paths)
        self._load_env()

    def _load_config(self, search_paths: list[Optional[Path]]):
        """Загрузить конфиг из первого найденного файла"""
        for path in search_paths:
            if path and path.exists():
                try:
                    with open(path, "rb") as f:
                        self.data = tomllib.load(f)
                    print(f"✅ Конфиг загружен из {path}")
                    return
                except Exception as e:
                    print(f"⚠️ Ошибка загрузки {path}: {e}")

        print("⚠️ Конфиг не найден, используются значения по умолчанию")

    def _load_env(self):
        """Переменные окружения перезаписывают конфиг"""
        logs_dir_str = os.getenv("FAF_LOGS_DIR", self._get("paths.logs_dir", "./logs"))
        db_file_str = os.getenv(
            "FAF_DB_FILE", self._get("database.db_file", "faf_analysis.db")
        )

        # Конвертируем в Path и проверяем существование
        self.logs_dir = Path(logs_dir_str).expanduser().resolve()
        self.db_file = Path(db_file_str).expanduser().resolve()

        # Если директория не существует, выводим предупреждение
        if not self.logs_dir.exists():
            print(f"⚠️ ВНИМАНИЕ: Директория логов не найдена: {self.logs_dir}")
            print("   Проверьте путь в faf_config.toml")
        else:
            print(f"✅ Директория логов найдена: {self.logs_dir}")

        self.auto_mark_ddos = (
            os.getenv(
                "FAF_AUTO_MARK_DDOS", str(self._get("analysis.auto_mark_ddos", False))
            ).lower()
            == "true"
        )
        self.ip_threshold = float(
            os.getenv("FAF_IP_THRESHOLD", str(self._get("analysis.ip_threshold", 0.5)))
        )

    def _get(self, path: str, default=None):
        """Получить значение из конфига по пути"""
        keys = path.split(".")
        value = self.data
        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default

    def __str__(self):
        return f"Config(logs_dir={self.logs_dir}, db_file={self.db_file})"


config = Config()
