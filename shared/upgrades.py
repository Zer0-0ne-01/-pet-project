"""Набор карт улучшений и их максимальные уровни."""

import random

UPGRADES = {
    "power_shot": {
        "name": "Сильные выстрелы",
        "description": "+8 урона за уровень",
        "max_level": 3,
    },
    "armor": {
        "name": "Броня",
        "description": "На 15% меньше урона за уровень",
        "max_level": 3,
    },
    "double_jump": {
        "name": "Двойной прыжок",
        "description": "Дополнительный прыжок в воздухе",
        "max_level": 1,
    },
}


def get_upgrade_choices(levels, count=2):
    """Случайная рука карт, не превышающая число доступных улучшений."""
    available = [
        {
            "id": upgrade_id,
            **details,
            "level": levels.get(upgrade_id, 0),
        }
        for upgrade_id, details in UPGRADES.items()
        if levels.get(upgrade_id, 0) < details["max_level"]
    ]
    return random.sample(available, min(count, len(available)))
