#!/usr/bin/env python3
"""
Скрипт управления многосекционным столом для Klipper/Moonraker.
Управляет 9 зонами нагрева и поддерживает профили под разные материалы.
"""

import requests
import json
import time
import sys
import logging
from typing import Dict, List, Optional

# ---------------------------- НАСТРОЙКИ ----------------------------
MOONRAKER_URL = "192.168.0.105"          # Адрес Moonraker (локально на Orange Pi)
MOONRAKER_PORT = 7125                       # Стандартный порт
PRINTER_NAME = "printer"                    # Имя принтера в Moonraker (обычно "printer")

# Имена нагревателей в Klipper (должны совпадать с именами в printer.cfg)
ZONE_HEATERS = [
    "heater_bed_zone1",
    "heater_bed_zone2",
    "heater_bed_zone3",
    "heater_bed_zone4",
    "heater_bed_zone5",
    "heater_bed_zone6",
    "heater_bed_zone7",
    "heater_bed_zone8",
    "heater_bed_zone9",
]

# Температурные профили для разных пластиков (в °C)
# Каждый профиль — список из 9 значений, соответствующих зонам
PROFILES = {
    "PLA": {
        "temps": [60, 60, 60, 60, 60, 60, 60, 60, 60],
        "description": "ПЛА (190-220°C сопло, стол 60°C)"
    },
    "ABS": {
        "temps": [100, 100, 100, 100, 100, 100, 100, 100, 100],
        "description": "АБС (230-250°C сопло, стол 100°C)"
    },
    "PETG": {
        "temps": [80, 80, 80, 80, 80, 80, 80, 80, 80],
        "description": "ПЕТГ (230-250°C сопло, стол 80°C)"
    },
    "TPU": {
        "temps": [50, 50, 50, 50, 50, 50, 50, 50, 50],
        "description": "ТПУ (210-230°C сопло, стол 50°C)"
    },
    "NYLON": {
        "temps": [100, 100, 100, 100, 100, 100, 100, 100, 100],
        "description": "Нейлон (250-270°C сопло, стол 100°C)"
    },
    # Можно добавить свои профили
    "CUSTOM": {
        "temps": [0, 0, 0, 0, 0, 0, 0, 0, 0],
        "description": "Пользовательский профиль (задаётся вручную)"
    }
}

# ---------------------------- НАСТРОЙКА ЛОГИРОВАНИЯ ----------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("BedController")

# ---------------------------- КЛАСС ДЛЯ РАБОТЫ С MOONRAKER ----------------------------
class MoonrakerController:
    """
    Класс-обёртка для взаимодействия с Moonraker API.
    Предоставляет методы для отправки G-кода, получения состояния принтера и управления нагревателями.
    """
    def __init__(self, base_url: str, port: int, printer_name: str):
        self.base_url = f"{base_url}:{port}"
        self.printer_name = printer_name
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})

    def _send_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Dict:
        """Отправляет запрос к Moonraker API и обрабатывает ошибки."""
        url = f"{self.base_url}{endpoint}"
        try:
            if method.upper() == "GET":
                resp = self.session.get(url)
            elif method.upper() == "POST":
                resp = self.session.post(url, json=data)
            else:
                raise ValueError(f"Unsupported method: {method}")

            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при запросе к Moonraker: {e}")
            if resp := getattr(e, 'response', None):
                logger.error(f"Ответ сервера: {resp.text}")
            raise

    def send_gcode(self, gcode: str) -> Dict:
        """Отправляет G-код команду через Moonraker."""
        endpoint = f"/printer/gcode/script"
        data = {"script": gcode}
        return self._send_request("POST", endpoint, data)

    def get_printer_objects(self, objects: List[str]) -> Dict:
        """Получает состояние запрошенных объектов Klipper."""
        endpoint = f"/printer/objects/query?{ '&'.join(objects) }"
        return self._send_request("GET", endpoint)

    def get_heater_temp(self, heater_name: str) -> Optional[float]:
        """Возвращает текущую температуру указанного нагревателя."""
        try:
            data = self.get_printer_objects([heater_name])
            return data['result']['status'][heater_name]['temperature']
        except Exception:
            return None

    def set_heater_temp(self, heater_name: str, target: float, wait: bool = False) -> None:
        """Устанавливает целевую температуру для нагревателя."""
        gcode = f"SET_HEATER_TEMPERATURE HEATER={heater_name} TARGET={target:.1f}"
        logger.info(f"Установка {heater_name} -> {target:.1f}°C")
        self.send_gcode(gcode)

        if wait:
            self.wait_for_heater(heater_name, target)

    def wait_for_heater(self, heater_name: str, target: float, tolerance: float = 2.0, timeout: int = 600) -> None:
        """Ожидает достижения нагревателем заданной температуры."""
        logger.info(f"Ожидание нагрева {heater_name} до {target:.1f}°C...")
        start = time.time()
        while time.time() - start < timeout:
            current = self.get_heater_temp(heater_name)
            if current is not None and abs(current - target) <= tolerance:
                logger.info(f"{heater_name} достиг {current:.1f}°C")
                return
            time.sleep(2)
        logger.warning(f"Таймаут ожидания нагрева {heater_name}!")

# ---------------------------- КЛАСС УПРАВЛЕНИЯ ЗОНАМИ ----------------------------
class MultiZoneBed:
    """
    Класс для управления всеми зонами нагрева стола.
    Позволяет применять профили, устанавливать произвольные температуры и выключать все зоны.
    """
    def __init__(self, moonraker: MoonrakerController, zones: List[str], profiles: Dict):
        self.mr = moonraker
        self.zones = zones
        self.profiles = profiles

    def set_profile(self, profile_name: str, wait: bool = False) -> None:
        """Применяет температурный профиль ко всем зонам."""
        if profile_name not in self.profiles:
            raise ValueError(f"Профиль '{profile_name}' не найден. Доступны: {', '.join(self.profiles.keys())}")

        temps = self.profiles[profile_name]["temps"]
        if len(temps) != len(self.zones):
            raise ValueError(f"Количество температур в профиле ({len(temps)}) не совпадает с количеством зон ({len(self.zones)})")

        logger.info(f"Применение профиля '{profile_name}': {self.profiles[profile_name]['description']}")
        for zone, temp in zip(self.zones, temps):
            self.mr.set_heater_temp(zone, temp, wait=False)

        if wait:
            self.wait_all_zones(temps)

    def set_custom_temps(self, temps: List[float], wait: bool = False) -> None:
        """Устанавливает произвольные температуры для зон."""
        if len(temps) != len(self.zones):
            raise ValueError("Длина списка температур не соответствует числу зон")
        logger.info("Применение пользовательских температур")
        for zone, temp in zip(self.zones, temps):
            self.mr.set_heater_temp(zone, temp, wait=False)
        if wait:
            self.wait_all_zones(temps)

    def wait_all_zones(self, target_temps: List[float], tolerance: float = 2.0) -> None:
        """Ожидает, пока все зоны достигнут своих целей."""
        logger.info("Ожидание нагрева всех зон...")
        for zone, target in zip(self.zones, target_temps):
            if target > 0:
                self.mr.wait_for_heater(zone, target, tolerance)

    def turn_off_all(self) -> None:
        """Выключает все нагреватели (устанавливает 0)."""
        logger.info("Выключение всех зон стола")
        for zone in self.zones:
            self.mr.set_heater_temp(zone, 0)

    def print_status(self) -> None:
        """Выводит текущие температуры всех зон."""
        print("\nТекущие температуры зон:")
        for i, zone in enumerate(self.zones):
            temp = self.mr.get_heater_temp(zone)
            if temp is not None:
                print(f"  Зона {i+1} ({zone}): {temp:.1f}°C")
            else:
                print(f"  Зона {i+1} ({zone}): ошибка чтения")
        print()

# ---------------------------- ИНТЕРАКТИВНОЕ МЕНЮ ----------------------------
def interactive_menu(controller: MultiZoneBed):
    """Простое меню для ручного управления."""
    while True:
        print("\n" + "="*50)
        print("УПРАВЛЕНИЕ МНОГОЗОННЫМ СТОЛОМ")
        print("="*50)
        print("1. Применить профиль материала")
        print("2. Установить свои температуры")
        print("3. Выключить все зоны")
        print("4. Показать текущие температуры")
        print("5. Выход")

        choice = input("Выберите действие [1-5]: ").strip()

        if choice == "1":
            print("\nДоступные профили:")
            for i, (name, data) in enumerate(controller.profiles.items(), 1):
                print(f"  {i}. {name}: {data['description']}")
            prof_choice = input("Введите имя профиля: ").strip().upper()
            if prof_choice in controller.profiles:
                wait = input("Ждать нагрева? (y/n): ").strip().lower() == 'y'
                try:
                    controller.set_profile(prof_choice, wait=wait)
                except Exception as e:
                    logger.error(f"Ошибка: {e}")
            else:
                print("Неверное имя профиля.")

        elif choice == "2":
            print(f"Введите 9 температур через пробел (в °C):")
            temps_str = input().strip()
            try:
                temps = [float(x) for x in temps_str.split()]
                if len(temps) != len(controller.zones):
                    print(f"Нужно ровно {len(controller.zones)} значений!")
                    continue
                wait = input("Ждать нагрева? (y/n): ").strip().lower() == 'y'
                controller.set_custom_temps(temps, wait=wait)
            except ValueError:
                print("Ошибка: введите числа через пробел.")

        elif choice == "3":
            controller.turn_off_all()

        elif choice == "4":
            controller.print_status()

        elif choice == "5":
            print("Выход.")
            break
        else:
            print("Неверный ввод.")

# ---------------------------- ТОЧКА ВХОДА ----------------------------
def main():
    # Инициализация Moonraker
    mr = MoonrakerController(MOONRAKER_URL, MOONRAKER_PORT, PRINTER_NAME)

    # Проверка соединения
    try:
        mr.get_printer_objects(["toolhead"])  # простой запрос
        logger.info("Соединение с Moonraker установлено")
    except Exception as e:
        logger.error(f"Не удалось подключиться к Moonraker: {e}")
        sys.exit(1)

    # Инициализация контроллера зон
    bed = MultiZoneBed(mr, ZONE_HEATERS, PROFILES)

    # Запуск меню (или можно вызывать конкретные методы из командной строки)
    if len(sys.argv) > 1:
        # Пример командной строки: ./script.py profile PLA --wait
        # Можно расширить парсинг аргументов через argparse
        pass
    else:
        interactive_menu(bed)

if __name__ == "__main__":
    main()