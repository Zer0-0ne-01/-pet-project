#level.py
"""Арены сетевого режима, общие для клиента и авторитарного сервера."""

from typing import NamedTuple

from shared.config import HEIGHT, WIDTH


class Platform(NamedTuple):
    x: float
    y: float
    w: float
    h: float


class GameMap(NamedTuple):
    map_id: str
    name: str
    background: tuple
    platform_color: tuple
    platform_top_color: tuple
    platforms: tuple


GROUND_Y = HEIGHT - 60
# Цвета как в ROUNDS: глубокий темный фон, платформы чуть светлее
ARENA_BACKGROUND = (24, 24, 32)
PLATFORM_COLOR = (45, 45, 55)
PLATFORM_TOP_COLOR = (80, 80, 95)

MAPS = (
    GameMap(
        "classic", "Классика", ARENA_BACKGROUND, PLATFORM_COLOR, PLATFORM_TOP_COLOR,
        (
            Platform(0, GROUND_Y, WIDTH, 60),
            Platform(150, 620, 180, 24),
            Platform(780, 620, 180, 24),
            Platform(480, 510, 200, 24),
        ),
    ),
    GameMap(
        "crossfire", "Перекрёстный огонь",
        ARENA_BACKGROUND, PLATFORM_COLOR, PLATFORM_TOP_COLOR,
        (
            Platform(0, GROUND_Y, WIDTH, 60),
            Platform(95, 610, 210, 24),
            Platform(719, 610, 210, 24),
            Platform(407, 560, 210, 24),
            Platform(235, 465, 180, 24),
            Platform(609, 465, 180, 24),
        ),
    ),
    GameMap(
        "towers", "Башни", ARENA_BACKGROUND, PLATFORM_COLOR, PLATFORM_TOP_COLOR,
        (
            Platform(0, GROUND_Y, WIDTH, 60),
            Platform(120, 620, 190, 24),
            Platform(714, 620, 190, 24),
            Platform(418, 620, 188, 24),
            Platform(265, 510, 185, 24),
            Platform(574, 510, 185, 24),
        ),
    ),
    GameMap(
        "high_ground", "Высота",
        ARENA_BACKGROUND, PLATFORM_COLOR, PLATFORM_TOP_COLOR,
        (
            Platform(0, GROUND_Y, WIDTH, 60),
            Platform(80, 630, 200, 24),
            Platform(744, 630, 200, 24),
            Platform(300, 545, 180, 24),
            Platform(544, 545, 180, 24),
            Platform(422, 435, 180, 24),
        ),
    ),
)

_MAP_BY_ID = {game_map.map_id: game_map for game_map in MAPS}


def get_map(map_id: str) -> GameMap:
    """Возвращает арену по ID; неизвестный ID считается ошибкой протокола."""
    return _MAP_BY_ID[map_id]


def get_platforms():
    """Сохраняет старый API: платформы стартовой арены."""
    return MAPS[0].platforms