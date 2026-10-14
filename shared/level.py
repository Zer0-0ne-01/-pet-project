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
ARENA_BACKGROUND = (26, 26, 36)
PLATFORM_COLOR = (43, 44, 56)
PLATFORM_TOP_COLOR = (78, 79, 91)

MAPS = (
    GameMap(
        "classic", "Классика", ARENA_BACKGROUND, PLATFORM_COLOR, PLATFORM_TOP_COLOR,
        (
            Platform(0, GROUND_Y, WIDTH, 60),
            Platform(150, 620, 180, 30),
            Platform(780, 620, 180, 30),
            Platform(480, 510, 200, 30),
        ),
    ),
    GameMap(
        "crossfire", "Перекрёстный огонь",
        ARENA_BACKGROUND, PLATFORM_COLOR, PLATFORM_TOP_COLOR,
        (
            Platform(0, GROUND_Y, WIDTH, 60),
            Platform(95, 610, 210, 28),
            Platform(719, 610, 210, 28),
            Platform(407, 560, 210, 28),
            Platform(235, 465, 180, 28),
            Platform(609, 465, 180, 28),
        ),
    ),
    GameMap(
        "towers", "Башни", ARENA_BACKGROUND, PLATFORM_COLOR, PLATFORM_TOP_COLOR,
        (
            Platform(0, GROUND_Y, WIDTH, 60),
            Platform(120, 620, 190, 28),
            Platform(714, 620, 190, 28),
            Platform(418, 620, 188, 28),
            Platform(265, 510, 185, 28),
            Platform(574, 510, 185, 28),
        ),
    ),
    GameMap(
        "high_ground", "Высота",
        ARENA_BACKGROUND, PLATFORM_COLOR, PLATFORM_TOP_COLOR,
        (
            Platform(0, GROUND_Y, WIDTH, 60),
            Platform(80, 630, 200, 28),
            Platform(744, 630, 200, 28),
            Platform(300, 545, 180, 28),
            Platform(544, 545, 180, 28),
            Platform(422, 435, 180, 28),
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
