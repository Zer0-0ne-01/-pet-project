# shared/level.py
"""Статичные платформы уровня.

Используется и сервером (для коллизий), и клиентом (для отрисовки),
поэтому не зависит от pygame — только от констант.
"""

from typing import List, NamedTuple

from shared.config import WIDTH, HEIGHT


class Platform(NamedTuple):
    x: float
    y: float
    w: float
    h: float


GROUND_Y = HEIGHT - 60             # верхняя граница «земли»


def get_platforms() -> List[Platform]:
    """
    Возвращает список платформ уровня.

    Пол — самая нижняя платформа во всю ширину экрана.
    Платформы расставлены так, чтобы между ними был «шаг» в 88–120 px
    по вертикали — это чуть меньше максимальной высоты прыжка
    (JUMP_SPEED² / 2G ≈ 117 px), то есть все достижимы.
    """
    return [
        Platform(0, GROUND_Y, WIDTH, 60),      # пол
        Platform(150, 620, 180, 30),           # нижняя левая
        Platform(780, 620, 180, 30),           # нижняя правая
        Platform(480, 500, 200, 30),           # средняя
    ]