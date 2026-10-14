# shared/config.py
"""Общие константы для клиента и сервера Shuffling."""

# --- ЭКРАН ---
WIDTH, HEIGHT = 1024, 768
FPS = 60

# --- СЕТЬ ---
BUFFER_SIZE = 8192
NET_HOST = "0.0.0.0"
NET_PORT = 9999
NET_TICK_DT = 1.0 / 30.0           # серверный тик — 30 Гц
NET_MAX_PLAYERS = 4
NET_PLAYER_TIMEOUT = 10.0
NET_JOIN_RETRY = 1.0
ROUND_END_DELAY = 3.0
UPGRADE_DRAFT_TIMEOUT = 20.0
MATCH_END_DELAY = 6.0
MATCH_WINS = 3

# --- СЕТЕВОЙ ИГРОК: ФИЗИКА ---
NET_PLAYER_SPEED = 300.0           # горизонтальная скорость, px/s

PLAYER_W = 44                      # ширина AABB круглого сетевого персонажа
PLAYER_H = 44                      # высота AABB круглого сетевого персонажа

GRAVITY = 1800.0                   # px/s²
JUMP_SPEED = 650.0                 # начальная вертикальная скорость прыжка, px/s
MAX_FALL_SPEED = 1200.0            # ограничение скорости падения

COYOTE_TIME = 0.10                 # сек — «прощение» прыжка после схода с платформы
JUMP_BUFFER_TIME = 0.12            # сек — «память» о нажатии прыжка в воздухе

NET_COLORS = [
    (255, 126, 38),
    (52, 202, 255),
    (255, 216, 74),
    (100, 239, 155),
    (193, 122, 255),
    (255, 108, 190),
]

# --- СНАРЯДЫ ---
PROJECTILE_SPEED = 700.0           # px/s
PROJECTILE_LIFETIME = 1.5          # сек до самоуничтожения
PROJECTILE_RADIUS = 6              # визуальный радиус
SHOOT_COOLDOWN = 0.20              # сек между выстрелами
PROJECTILE_DAMAGE = 25
PROJECTILE_KNOCKBACK = 420.0
PLAYER_MAX_HP = 100

# --- ЛОКАЛЬНАЯ ИГРА (offline, не менялась) ---
LOCAL_BG_COLOR = (30, 30, 60)
LOCAL_PLAYER_SIZE = 50
LOCAL_PLAYER_SPEED = 5
LOCAL_PLAYER_MAX_HP = 100

LOCAL_ENEMY_SIZE = 40
LOCAL_ENEMY_SPEED = 3
LOCAL_ENEMY_DAMAGE_PER_SEC = 40.0

# --- UI: меню и HUD ---
MENU_BG = (20, 20, 40)
UI_TEXT = (240, 240, 240)
HP_BACK = (60, 60, 60)
HP_FILL = (220, 60, 60)
HP_FILL_LOW = (240, 180, 40)
HP_BORDER = (200, 200, 200)

BUTTON_BG = (60, 80, 140)
BUTTON_BG_HOVER = (90, 120, 190)
BUTTON_BORDER = (200, 220, 255)
BUTTON_TEXT = (255, 255, 255)