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
MATCH_WINS = 2

# --- СЕТЕВОЙ ИГРОК: ФИЗИКА ---
NET_PLAYER_SPEED = 300.0           # горизонтальная скорость, px/s

PLAYER_W = 40                      # ширина AABB круглого сетевого персонажа (чуть меньше для стиля)
PLAYER_H = 40                      # высота AABB круглого сетевого персонажа

GRAVITY = 1800.0                   # px/s²
JUMP_SPEED = 650.0                 # начальная вертикальная скорость прыжка, px/s
MAX_FALL_SPEED = 1200.0            # ограничение скорости падения

COYOTE_TIME = 0.10                 # сек — «прощение» прыжка после схода с платформы
JUMP_BUFFER_TIME = 0.12            # сек — «память» о нажатии прыжка в воздухе

# Яркие, неоновые цвета как в ROUNDS
NET_COLORS = [
    (255, 126, 38),   # Neon Orange (Player 1)
    (52, 202, 255),   # Cyan (Player 2)
    (255, 216, 74),   # Yellow
    (100, 239, 155),  # Neon Green
    (193, 122, 255),  # Purple
    (255, 108, 190),  # Pink
]

# --- СНАРЯДЫ ---
PROJECTILE_SPEED = 700.0           # px/s
PROJECTILE_GRAVITY = 700.0         # px/s²; gravity gives shots a ballistic arc
PROJECTILE_LIFETIME = 1.5          # сек до самоуничтожения
PROJECTILE_RADIUS = 5              # визуальный радиус (чуть меньше)
SHOOT_COOLDOWN = 0.20              # сек между выстрелами
PROJECTILE_DAMAGE = 25
PROJECTILE_KNOCKBACK = 420.0
PLAYER_MAX_HP = 100
MAGAZINE_SIZE = 3
RELOAD_DURATION = 1.5
EXPLOSION_RADIUS = 90.0

# --- UI: меню и HUD ---
MENU_BG = (18, 18, 24)            # Темный фон меню
UI_TEXT = (240, 240, 240)
HP_BACK = (60, 60, 60)
HP_FILL = (220, 60, 60)
HP_FILL_LOW = (240, 180, 40)
HP_BORDER = (200, 200, 200)

BUTTON_BG = (40, 45, 60)
BUTTON_BG_HOVER = (70, 80, 110)
BUTTON_BORDER = (120, 140, 180)
BUTTON_TEXT = (255, 255, 255)