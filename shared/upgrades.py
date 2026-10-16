"""Набор карт улучшений и их максимальные уровни."""

import random

from shared.config import (
    PLAYER_MAX_HP, PROJECTILE_DAMAGE, PROJECTILE_SPEED, RELOAD_DURATION,
    SHOOT_COOLDOWN,
)

RARITY_WEIGHTS = {
    "Обычная": 8,
    "Необычная": 3,
    "Редкая": 1,
}

UPGRADES = {
    "power_shot": {
        "name": "Сильные выстрелы",
        "description": "+8 урона за уровень",
        "max_level": 3,
        "rarity": "Обычная",
    },
    "armor": {
        "name": "Броня",
        "description": "На 15% меньше урона за уровень",
        "max_level": 3,
        "rarity": "Необычная",
    },
    "double_jump": {
        "name": "Двойной прыжок",
        "description": "Дополнительный прыжок в воздухе",
        "max_level": 1,
        "rarity": "Редкая",
    },
    "large_health": {
        "name": "Большое здоровье",
        "description": "+80% максимального здоровья за уровень",
        "stats": "+80% здоровье",
        "max_health_bonus": 0.8,
        "max_level": 3,
        "rarity": "Обычная",
    },
    "fast_shot": {
        "name": "Быстрый выстрел",
        "description": "Пули летят на 150% быстрее; перезарядка дольше на 0.25 с",
        "stats": "+150% скорость пули, +0.25с перезарядка",
        "projectile_speed_bonus": 1.5,
        "cooldown_addition": 0.25,
        "max_level": 3,
        "rarity": "Обычная",
    },
    "acceleration": {
        "name": "Ускорение",
        "description": "Пули летят на 100% быстрее, перезарядка ускоряется на 30%",
        "stats": "+100% скорость снаряда, +30% скорость перезарядки",
        "projectile_speed_bonus": 1.0,
        "cooldown_multiplier": 1 / 1.3,
        "max_level": 3,
        "rarity": "Обычная",
    },
    "reload": {
        "name": "Перезарядка",
        "description": "На 70% меньше времени между выстрелами за уровень",
        "stats": "-70% время перезарядки",
        "cooldown_multiplier": 0.3,
        "max_level": 3,
        "rarity": "Обычная",
    },
    "stable_shot": {
        "name": "Устойчивый выстрел",
        "description": "+40% здоровья и +100% скорости пуль за уровень",
        "stats": "+40% здоровье, +100% скорость пули, +0.25с перезарядка",
        "max_health_bonus": 0.4,
        "projectile_speed_bonus": 1.0,
        "cooldown_addition": 0.25,
        "max_level": 3,
        "rarity": "Обычная",
    },
    "tank": {
        "name": "Танк",
        "description": "+100% здоровья, но на 25% ниже скорость стрельбы за уровень",
        "stats": "+100% здоровье, -25% скорость атаки, +0.5с перезарядка",
        "max_health_bonus": 1.0,
        "cooldown_multiplier": 1 / 0.75,
        "cooldown_addition": 0.5,
        "max_level": 3,
        "rarity": "Обычная",
    },
    "poison": {
        "name": "Яд",
        "description": "Попадания отравляют: урон со временем длится дольше и сильнее с уровнем",
        "stats": "+60% урон ядом, +30% скорость перезарядки",
        "poison_damage_per_second": PROJECTILE_DAMAGE * 0.2,
        "poison_duration": 3.0,
        "cooldown_multiplier": 1 / 1.3,
        "max_level": 3,
        "rarity": "Обычная",
    },
    "timed_detonation": {
        "name": "Детонация по таймеру",
        "description": "Снаряды взрываются через 0.5 секунды",
        "stats": "-15% урон, +0.25с перезарядка",
        "projectile_damage_multiplier": 0.85,
        "explosion_damage_multiplier": 1.0,
        "explosion_radius": 70.0,
        "explosion_fuse": 0.5,
        "cooldown_addition": 0.25,
        "max_level": 3,
        "rarity": "Обычная",
    },
    "explosive_bullets": {
        "name": "Разрывные пули",
        "description": "Попадания и столкновения снарядов вызывают взрыв",
        "stats": "+90 радиус взрыва, +0.25с перезарядка",
        "explosion_damage_multiplier": 1.0,
        "explosion_radius": 90.0,
        "explode_on_impact": True,
        "cooldown_addition": 0.25,
        "max_level": 3,
        "rarity": "Необычная",
    },
    "ricochet": {
        "name": "Рикошет",
        "description": "Снаряды отскакивают от платформ дважды за уровень",
        "stats": "+2 отскока, +25% скорость атаки",
        "projectile_bounces": 2,
        "bounce_speed_multiplier": 0.8,
        "cooldown_multiplier": 1 / 1.25,
        "max_level": 3,
        "rarity": "Необычная",
    },
    "barrage_bounce": {
        "name": "Беспредел",
        "description": "Снаряды отскакивают от платформ пять раз за уровень",
        "stats": "+5 отскоков, -15% урон",
        "projectile_bounces": 5,
        "projectile_damage_multiplier": 0.85,
        "max_level": 3,
        "rarity": "Необычная",
    },
    "trickster": {
        "name": "Трикстер",
        "description": "Каждый отскок усиливает урон снаряда на 80%",
        "stats": "+2 отскока, -20% урон, +0.5с перезарядка",
        "projectile_bounces": 2,
        "projectile_damage_multiplier": 0.8,
        "bounce_damage_multiplier": 1.8,
        "cooldown_addition": 0.5,
        "max_level": 3,
        "rarity": "Редкая",
    },
}


def get_max_health(levels):
    """Максимальное здоровье с учетом выбранных улучшений."""
    bonus = sum(
        details.get("max_health_bonus", 0) * levels.get(upgrade_id, 0)
        for upgrade_id, details in UPGRADES.items()
    )
    return round(PLAYER_MAX_HP * (1 + bonus))


def get_projectile_speed(levels):
    """Скорость снаряда с учетом выбранных улучшений."""
    bonus = sum(
        details.get("projectile_speed_bonus", 0) * levels.get(upgrade_id, 0)
        for upgrade_id, details in UPGRADES.items()
    )
    return PROJECTILE_SPEED * (1 + bonus)


def get_shoot_cooldown(levels):
    """Интервал между выстрелами с учетом выбранных улучшений."""
    addition = sum(
        details.get("cooldown_addition", 0) * levels.get(upgrade_id, 0)
        for upgrade_id, details in UPGRADES.items()
    )
    multiplier = 1.0
    for upgrade_id, details in UPGRADES.items():
        multiplier *= details.get("cooldown_multiplier", 1) ** levels.get(
            upgrade_id, 0,
        )
    return max(0.05, (SHOOT_COOLDOWN + addition) * multiplier)


def get_reload_duration(levels):
    """Длительность перезарядки магазина с учетом улучшений."""
    addition = sum(
        details.get("cooldown_addition", 0) * levels.get(upgrade_id, 0)
        for upgrade_id, details in UPGRADES.items()
    )
    multiplier = 1.0
    for upgrade_id, details in UPGRADES.items():
        multiplier *= details.get("cooldown_multiplier", 1) ** levels.get(
            upgrade_id, 0,
        )
    return max(0.1, (RELOAD_DURATION + addition) * multiplier)


def get_projectile_property(levels, property_name, default=0):
    """Суммирует параметр снаряда от всех выбранных улучшений."""
    return sum(
        details.get(property_name, default) * levels.get(upgrade_id, 0)
        for upgrade_id, details in UPGRADES.items()
    )


def get_projectile_multiplier(levels, property_name):
    """Перемножает модификаторы урона снаряда."""
    multiplier = 1.0
    for upgrade_id, details in UPGRADES.items():
        multiplier *= details.get(property_name, 1) ** levels.get(upgrade_id, 0)
    return multiplier


def get_projectile_bounces(levels):
    return int(get_projectile_property(levels, "projectile_bounces"))


def get_explosion_radius(levels):
    return get_projectile_property(levels, "explosion_radius")


def get_explosion_damage_multiplier(levels):
    return get_projectile_multiplier(levels, "explosion_damage_multiplier")


def get_bounce_damage_multiplier(levels):
    return get_projectile_multiplier(levels, "bounce_damage_multiplier")


def get_bounce_speed_multiplier(levels):
    return get_projectile_multiplier(levels, "bounce_speed_multiplier")


def get_poison_damage_per_second(levels):
    return get_projectile_property(levels, "poison_damage_per_second")


def get_poison_duration(levels):
    return get_projectile_property(levels, "poison_duration")


def get_projectile_damage_multiplier(levels):
    return get_projectile_multiplier(levels, "projectile_damage_multiplier")


def has_upgrade_effect(levels, effect_name):
    return any(
        details.get(effect_name, False) and levels.get(upgrade_id, 0) > 0
        for upgrade_id, details in UPGRADES.items()
    )


def get_explosion_fuse(levels):
    fuses = [
        details["explosion_fuse"]
        for upgrade_id, details in UPGRADES.items()
        if "explosion_fuse" in details and levels.get(upgrade_id, 0) > 0
    ]
    return min(fuses, default=None)


def get_upgrade_choices(levels, count=3):
    """Выбирает случайные карты с меньшим весом для высокой редкости."""
    available = [
        {
            "id": upgrade_id,
            **details,
            "level": levels.get(upgrade_id, 0),
        }
        for upgrade_id, details in UPGRADES.items()
        if levels.get(upgrade_id, 0) < details["max_level"]
    ]
    choices = []
    while available and len(choices) < count:
        weights = [RARITY_WEIGHTS[card["rarity"]] for card in available]
        card = random.choices(available, weights=weights, k=1)[0]
        choices.append(card)
        available.remove(card)
    return choices
