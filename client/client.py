# client/client.py
"""Сетевой UDP-клиент Shuffling: арена, круглые игроки и стрельба по ЛКМ."""

import argparse
from collections import OrderedDict
from functools import lru_cache
import json
import math
import random
import socket
import time

import pygame
import pygame.gfxdraw

from shared.config import (
    WIDTH, HEIGHT, FPS, BUFFER_SIZE,
    NET_TICK_DT as SERVER_TICK_DT,
    PLAYER_W, PLAYER_H,
    PROJECTILE_RADIUS,
    MAGAZINE_SIZE,
    PLAYER_MAX_HP,
    NET_JOIN_RETRY,
    NET_COLORS,
)
from shared.upgrades import get_max_health, get_shoot_cooldown
from shared.protocol import (
    MSG_JOIN, MSG_INPUT, MSG_SHOOT, MSG_LEAVE,
    MSG_PROFILE, MSG_REJECT, MSG_START, MSG_UPGRADE, MSG_WELCOME, MSG_STATE,
)
from shared.level import get_map
from client.ui import (
    draw_arcade_backdrop, draw_crosshair, draw_panel,
    draw_round_scoreboard,
)


class RemotePlayer:
    """Сглаженное представление игрока в клиенте (интерполяция)."""

    def __init__(self, pid, x, y, color, facing, on_ground, now,
                 name="player", hp=100, alive=True, score=0, upgrades=None,
                 ammo=MAGAZINE_SIZE, reloading=False, reload_time=0.0,
                 reload_duration=0.0, eyes_style=0, mouth_style=0,
                 weapon_style=0, round_streak=0, score_squares=0):
        self.pid = pid
        self.color = color
        self.facing = facing
        self.on_ground = on_ground
        self.landed_at = 0.0
        self.name = name
        self.hp = hp
        self.alive = alive
        self.score = score
        self.upgrades = upgrades or {}
        self.ammo = ammo
        self.reloading = reloading
        self.reload_time = reload_time
        self.reload_duration = reload_duration
        self.eyes_style = eyes_style
        self.mouth_style = mouth_style
        self.weapon_style = weapon_style
        self.round_streak = round_streak
        self.score_squares = score_squares
        self.vx = 0.0
        self.vy = 0.0
        self.anim_phase = 0.0  # Фаза для анимации ходьбы

        self.prev_x = x
        self.prev_y = y
        self.target_x = x
        self.target_y = y
        self.snapshot_time = now

    def push_snapshot(self, x, y, color, facing, on_ground, now,
                      name, hp, alive, score, upgrades, vx, vy,
                      ammo, reloading, reload_time, reload_duration,
                      eyes_style, mouth_style, weapon_style, round_streak,
                      score_squares):
        if on_ground and not self.on_ground:
            self.landed_at = now
        t = min(1.0, (now - self.snapshot_time) / SERVER_TICK_DT)
        self.prev_x += (self.target_x - self.prev_x) * t
        self.prev_y += (self.target_y - self.prev_y) * t
        self.target_x = x
        self.target_y = y
        self.snapshot_time = now
        self.color = color
        self.facing = facing
        self.on_ground = on_ground
        self.name = name
        self.hp = hp
        self.alive = alive
        self.score = score
        self.upgrades = upgrades
        self.ammo = ammo
        self.reloading = reloading
        self.reload_time = reload_time
        self.reload_duration = reload_duration
        self.eyes_style = eyes_style
        self.mouth_style = mouth_style
        self.weapon_style = weapon_style
        self.round_streak = round_streak
        self.score_squares = score_squares
        self.vx = vx
        self.vy = vy

    def render_pos(self, now):
        t = min(1.0, (now - self.snapshot_time) / SERVER_TICK_DT)
        x = self.prev_x + (self.target_x - self.prev_x) * t
        y = self.prev_y + (self.target_y - self.prev_y) * t
        return x, y


class RemoteProjectile:
    """Снаряд на клиенте с баллистической экстраполяцией позиции."""

    def __init__(self, pid, x, y, vx, vy, color, effect, gravity, now):
        self.pid = pid
        self.color = color
        self.effect = effect
        self.gravity = gravity
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.updated_at = now

    def push_snapshot(self, x, y, vx, vy, color, effect, gravity, now):
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.color = color
        self.effect = effect
        self.gravity = gravity
        self.updated_at = now

    def render_pos(self, now):
        dt = now - self.updated_at
        return (
            self.x + self.vx * dt,
            self.y + self.vy * dt + 0.5 * self.gravity * dt * dt,
        )


# --- ОТРИСОВКА ---

_TEXT_CACHE = OrderedDict()


def _cached_text(font, text, color):
    key = (id(font), text, color)
    surface = _TEXT_CACHE.get(key)
    if surface is None:
        surface = font.render(text, True, color)
        _TEXT_CACHE[key] = surface
        if len(_TEXT_CACHE) > 256:
            _TEXT_CACHE.popitem(last=False)
    else:
        _TEXT_CACHE.move_to_end(key)
    return surface


def _wrap_text(font, text, max_width):
    lines = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if line and font.size(candidate)[0] > max_width:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


class Particle:
    def __init__(self, x, y, vx, vy, color, size, lifetime, square):
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.color = color
        self.size = size
        self.lifetime = lifetime
        self.age = 0.0
        self.square = square


class ParticleSystem:
    def __init__(self):
        self.particles = []
        self.surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)

    def burst(self, x, y, color, count=10, speed=180.0, size=5.0):
        remaining = max(0, 200 - len(self.particles))
        for _ in range(min(count, remaining)):
            angle = random.uniform(0, math.tau)
            velocity = random.uniform(speed * 0.35, speed)
            self.particles.append(Particle(
                x, y,
                math.cos(angle) * velocity,
                math.sin(angle) * velocity,
                color,
                random.uniform(size * 0.5, size * 1.5),
                random.uniform(0.2, 0.4), # Быстро исчезают, как в ROUNDS
                random.choice((True, False)),
            ))

    def update_and_draw(self, screen, dt):
        self.surface.fill((0, 0, 0, 0))
        alive = []
        for particle in self.particles:
            particle.age += dt
            if particle.age >= particle.lifetime:
                continue
            alive.append(particle)
            particle.x += particle.vx * dt
            particle.y += particle.vy * dt
            particle.vx *= max(0.0, 1 - 3.0 * dt)
            particle.vy = particle.vy * max(0.0, 1 - 3.0 * dt) + 200 * dt
            progress = particle.age / particle.lifetime
            radius = max(1, round(particle.size * (1 - progress * 0.8)))
            alpha = round(255 * (1 - progress) ** 2)
            color = (*particle.color, alpha)
            center = (round(particle.x), round(particle.y))
            
            # В ROUNDS частицы — это простые квадраты или круги
            if particle.square:
                rect = pygame.Rect(0, 0, radius * 2, radius * 2)
                rect.center = center
                pygame.draw.rect(self.surface, color, rect)
            else:
                pygame.gfxdraw.filled_circle(self.surface, *center, radius, color)
        self.particles = alive
        screen.blit(self.surface, (0, 0))


@lru_cache(maxsize=48)
def _make_glow(color, radius, alpha):
    """Кэшированное свечение для снарядов (как в ROUNDS)."""
    margin = radius * 4
    diameter = margin * 2 + 1
    glow = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
    center = (margin, margin)
    for scale, opacity in ((2.5, 0.1), (1.8, 0.2), (1.2, 0.4), (1.0, 0.8)):
        ring_radius = max(1, round(radius * scale))
        ring_color = (*color, round(alpha * opacity))
        pygame.gfxdraw.filled_circle(glow, *center, ring_radius, ring_color)
    return glow


@lru_cache(maxsize=96)
def _make_player_body(color, width, height):
    scale = 4
    body = pygame.Surface((width * scale, height * scale), pygame.SRCALPHA)
    bounds = pygame.Rect(2 * scale, 2 * scale,
                         (width - 4) * scale, (height - 4) * scale)
    pygame.draw.ellipse(body, (5, 9, 20), bounds.inflate(4 * scale, 4 * scale))
    pygame.draw.ellipse(body, color, bounds)
    inner = bounds.inflate(-6 * scale, -6 * scale)
    pygame.draw.ellipse(
        body,
        tuple(min(255, channel + 24) for channel in color),
        pygame.Rect(inner.x, inner.y, inner.width, max(scale, inner.height // 2)),
    )
    pygame.draw.ellipse(body, (5, 9, 20), bounds, 2 * scale)
    return pygame.transform.smoothscale(body, (width, height))


def draw_arena_background(screen):
    draw_arcade_backdrop(screen, animate=False)


def draw_platforms(screen, platforms, platform_color, platform_top_color):
    for p in platforms:
        rect = pygame.Rect(int(p.x), int(p.y), int(p.w), int(p.h))
        pygame.draw.rect(screen, (10, 17, 31), rect, border_radius=5)
        pygame.draw.rect(screen, (31, 45, 62), rect, 1, border_radius=5)
        pygame.draw.line(
            screen, platform_top_color, (rect.left + 5, rect.top + 1),
            (rect.right - 6, rect.top + 1), 3,
        )
        pygame.draw.line(
            screen, platform_color, (rect.left + 8, rect.bottom - 3),
            (rect.right - 8, rect.bottom - 3), 1,
        )


def draw_player(screen, x, y, color, facing, name, hp, alive, font,
                now, vx, vy, on_ground, player_id, aim_target=None,
                recoil=0.0, landed_at=0.0, max_hp=PLAYER_MAX_HP,
                ammo=MAGAZINE_SIZE, reloading=False, reload_time=0.0,
                reload_duration=0.0, eyes_style=0, mouth_style=0,
                weapon_style=0):
    """Рисует персонажа в стиле ROUNDS: боб + палочки-конечности + пушка."""
    if not alive:
        return

    # --- 1. Физика и анимация (Squash & Stretch) ---
    moving = abs(vx) > 25
    
    # Анимация ходьбы (синусоида)
    if moving and on_ground:
        # Используем player_id для рассинхронизации анимации у разных игроков
        gait_phase = now * 15 + player_id * 1.5
        gait = math.sin(gait_phase)
    else:
        gait = 0.0

    # Эффект желе (Squash & Stretch)
    stretch = 0.0
    if not on_ground:
        stretch = 0.15 if vy < -50 else 0.08
    landing = max(0.0, 1.0 - (now - landed_at) / 0.15) if landed_at else 0.0
    
    body_w = int(PLAYER_W * (1.0 - stretch * 0.4 + landing * 0.2))
    body_h = int(PLAYER_H * (1.0 + stretch - landing * 0.3))
    
    # Легкое покачивание при ходьбе
    bob = abs(math.sin(gait_phase)) * 2.0 if moving and on_ground else 0.0
    cx, cy = int(x), int(y - bob)

    # --- 2. Конечности (Рисуются ПОД телом) ---
    limb_color = (8, 13, 25)
    limb_thickness = 3

    # Keep grounded feet inside the collision box so they meet, not cross, platforms.
    hip_y = cy + round(body_h * 0.22)
    foot_y = (
        round(y + PLAYER_H / 2 - 2)
        if on_ground else cy + body_h // 2 + 8
    )
    for side in (-1, 1):
        stride = gait * 4 * side if moving else 0.0
        hip = (cx + side * 6, hip_y)
        knee = (round(cx + side * 8 + stride * 0.5), round(hip_y + 6))
        foot = (round(cx + side * 8 + stride), foot_y)
        pygame.draw.line(screen, limb_color, hip, knee, limb_thickness)
        pygame.draw.line(screen, limb_color, knee, foot, limb_thickness)

    # --- 3. Тело ---
    # Рисуем эллипс напрямую, чтобы squash & stretch работал идеально
    body_rect = pygame.Rect(0, 0, body_w, body_h)
    body_rect.center = (cx, cy)
    
    body_surface = _make_player_body(tuple(color), body_w, body_h)
    screen.blit(body_surface, body_surface.get_rect(center=(cx, cy)))

    # --- 4. Руки и Оружие (Рисуются ПОВЕРХ тела) ---
    # Задняя рука (просто висит)
    back_shoulder = (cx - facing * 8, cy - 2)
    back_hand = (back_shoulder[0] - facing * 6, back_shoulder[1] + 10)
    pygame.draw.line(screen, limb_color, back_shoulder, back_hand, limb_thickness)

    # Передняя рука (с пушкой) — всегда смотрит на прицел
    if aim_target is None:
        aim_target = (cx + facing * 100, cy)
    
    aim_angle = math.atan2(aim_target[1] - cy, aim_target[0] - cx)
    aim_dir = pygame.math.Vector2(math.cos(aim_angle), math.sin(aim_angle))
    grip_side = pygame.math.Vector2(-aim_dir.y, aim_dir.x)
    if grip_side.y < 0:
        grip_side = -grip_side
    
    # Отдача (recoil) откидывает руку назад
    arm_length = 16 - (recoil * 6)
    shoulder = pygame.math.Vector2(cx + aim_dir.x * 6, cy + aim_dir.y * 6)
    hand = shoulder + aim_dir * arm_length
    
    # Локоть (изгиб руки)
    elbow = shoulder + aim_dir * (arm_length * 0.5) + grip_side * 4
    pygame.draw.line(screen, limb_color, shoulder, elbow, limb_thickness)
    pygame.draw.line(screen, limb_color, elbow, hand, limb_thickness)

    # --- 5. Оружие (Пистолет) ---
    # Ствол
    muzzle = hand + aim_dir * (19 if weapon_style == 1 else 14)
    # Рукоятка
    grip_start = hand + aim_dir * 4
    grip_end = grip_start + grip_side * 8
    
    weapon_width = 9 if weapon_style == 1 else 6
    pygame.draw.line(screen, (7, 12, 23), hand, muzzle, weapon_width)
    if weapon_style == 1:
        pygame.draw.line(
            screen, (32, 95, 116), hand + aim_dir * 4,
            muzzle - aim_dir * 2, 4,
        )
        pygame.draw.circle(
            screen, (115, 232, 235),
            (round(muzzle.x), round(muzzle.y)), 4,
        )
    pygame.draw.line(screen, (8, 15, 28), grip_start, grip_end, 5)
    
    # Блик на стволе
    pygame.draw.line(screen, (190, 242, 240), hand + aim_dir * 6, muzzle - aim_dir * 2, 1)

    # Keep the face unobstructed; eyes and mouth are drawn below.
    pygame.draw.line(
        screen, tuple(color),
        (cx - 9, cy + 8), (cx - 5, cy + 12), 2,
    )

    # --- 6. Глаза ---
    eye_y = cy - 7
    eye_offset = 7
    # Глаза смотрят в сторону прицела
    eye_shift_x = int(aim_dir.x * 2)
    eye_shift_y = int(aim_dir.y * 2)
    
    for offset in (-eye_offset, eye_offset):
        eye_x = cx + eye_shift_x + offset
        eye_position = (eye_x, eye_y + eye_shift_y)
        if eyes_style == 0:
            pygame.draw.circle(screen, (169, 255, 246), eye_position, 3)
        else:
            eye_rect = pygame.Rect(eye_x - 3, eye_position[1] - 2, 7, 3)
            pygame.draw.rect(screen, (169, 255, 246), eye_rect, border_radius=1)

    mouth_color = (11, 30, 41)
    if mouth_style == 0:
        pygame.draw.arc(
            screen, mouth_color, pygame.Rect(cx - 6, cy + 1, 12, 9),
            math.pi, math.tau, 2,
        )
    else:
        pygame.draw.line(screen, mouth_color, (cx - 5, cy + 6), (cx + 5, cy + 6), 2)

    # --- 7. UI Игрока (Имя и HP) ---
    # В ROUNDS UI минималистичен, рисуем просто текст над головой
    name_surface = _cached_text(font, name, (220, 220, 230))
    screen.blit(name_surface, name_surface.get_rect(midbottom=(cx, body_rect.top - 10)))
    
    # Тонкая полоска HP
    bar_width, bar_height = 30, 3
    bar_x, bar_y = cx - bar_width // 2, body_rect.top - 5
    reload_progress = (
        1 - reload_time / reload_duration
        if reloading and reload_duration > 0 else 0.0
    )
    segment_width, segment_height, segment_gap = 8, 3, 2
    segments_width = MAGAZINE_SIZE * segment_width + (MAGAZINE_SIZE - 1) * segment_gap
    segments_x = cx - segments_width // 2
    for index in range(MAGAZINE_SIZE):
        segment = pygame.Rect(
            segments_x + index * (segment_width + segment_gap),
            bar_y - segment_height - 2,
            segment_width,
            segment_height,
        )
        pygame.draw.rect(screen, (19, 30, 43), segment)
        fill = (
            reload_progress * MAGAZINE_SIZE - index
            if reloading else ammo - index
        )
        fill_width = round(segment_width * max(0.0, min(1.0, fill)))
        if fill_width:
            pygame.draw.rect(
                screen, (231, 255, 249),
                (segment.x, segment.y, fill_width, segment.height),
            )
    pygame.draw.rect(screen, (15, 21, 34), (bar_x, bar_y, bar_width, bar_height))
    hp_ratio = max(0.0, min(1.0, hp / max_hp))
    if hp_ratio:
        hp_color = color # Полоска HP того же цвета, что и игрок
        pygame.draw.rect(screen, hp_color, (bar_x, bar_y, round(bar_width * hp_ratio), bar_height))


def draw_projectile(screen, x, y, color):
    """Снаряд в стиле ROUNDS: яркая точка со свечением."""
    ix, iy = int(x), int(y)
    glow = _make_glow(tuple(color), PROJECTILE_RADIUS, 255)
    screen.blit(glow, glow.get_rect(center=(ix, iy)))
    
    # Ядро снаряда
    pygame.draw.circle(screen, (255, 255, 255), (ix, iy), PROJECTILE_RADIUS - 2)
    pygame.draw.circle(screen, color, (ix, iy), PROJECTILE_RADIUS - 1, 2)


# --- ОСНОВНОЙ ЦИКЛ ---

def run_client(host="127.0.0.1", port=9999, name="player", color=None,
               eyes_style=0, mouth_style=0, weapon_style=0):
    server_addr = (host, port)
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption(f"Shuffling — {name}")
    pygame.mouse.set_visible(False)
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("arial", 18)
    card_font = pygame.font.SysFont("arial", 16)
    title_font = pygame.font.SysFont("arial", 30, bold=True)
    current_map = get_map("classic")
    platforms = current_map.platforms
    selected_color = tuple(color or NET_COLORS[0])
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    join_payload = json.dumps({
        "type": MSG_JOIN, "name": name, "color": list(selected_color),
        "eyes_style": eyes_style, "mouth_style": mouth_style,
        "weapon_style": weapon_style,
    }).encode("utf-8")
    my_id = None
    players = {}
    projectiles = {}
    last_shot_time = 0.0
    next_join_time = 0.0
    last_state_time = time.monotonic()
    phase = "connecting"
    particles = ParticleSystem()
    frame_dt = 1.0 / FPS
    winner_id = None
    match_winner_id = None
    host_id = None
    upgrade_choices = []
    upgrade_selected = True
    pending_upgrade = None
    last_upgrade_sent = 0.0
    start_requested = False
    last_start_sent = 0.0
    profile_notice = ""
    profile_notice_until = 0.0
    lobby_panel = pygame.Rect(WIDTH // 2 - 330, 145, 660, 495)
    lobby_start_rect = pygame.Rect(WIDTH // 2 - 140, 570, 280, 54)
    lobby_swatches = [
        pygame.Rect(WIDTH // 2 - 188 + index * 64, 481, 42, 42)
        for index in range(len(NET_COLORS))
    ]
    card_rects = [
        pygame.Rect(WIDTH // 2 - 445 + index * 300, HEIGHT // 2 - 95, 280, 190)
        for index in range(3)
    ]
    error_message = None
    quit_requested = False
    running = True
    try:
        while running:
            frame_dt = min(clock.tick(FPS) / 1000.0, 0.05)
            now = time.monotonic()
            if my_id is None:
                if now >= next_join_time:
                    try:
                        sock.sendto(join_payload, server_addr)
                    except OSError as error:
                        error_message = f"Не удалось подключиться: {error}"
                        running = False
                    next_join_time = now + NET_JOIN_RETRY
                if now - last_state_time > 12.0:
                    error_message = "Нет ответа от сервера. Проверьте адрес и порт."
                    running = False
            elif now - last_state_time > 8.0:
                error_message = "Потеряно соединение с сервером."
                running = False

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    quit_requested = True
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if phase == "waiting":
                        if my_id == host_id and len(players) >= 2 and lobby_start_rect.collidepoint(event.pos):
                            start_requested = True
                            last_start_sent = 0.0
                        elif my_id is not None:
                            for index, rect in enumerate(lobby_swatches):
                                if rect.collidepoint(event.pos):
                                    selected_color = NET_COLORS[index]
                                    try:
                                        sock.sendto(json.dumps({
                                            "type": MSG_PROFILE,
                                            "name": name,
                                            "color": list(selected_color),
                                            "eyes_style": eyes_style,
                                            "mouth_style": mouth_style,
                                            "weapon_style": weapon_style,
                                        }).encode("utf-8"), server_addr)
                                    except OSError as error:
                                        profile_notice = f"Не удалось изменить цвет: {error}"
                                        profile_notice_until = now + 3.0
                                    break
                    elif (phase == "draft" and not upgrade_selected
                            and pending_upgrade is None):
                        for index, rect in enumerate(card_rects[:len(upgrade_choices)]):
                            if rect.collidepoint(event.pos):
                                pending_upgrade = upgrade_choices[index]["id"]
                                break
                    elif (phase == "playing" and my_id in players
                          and now - last_shot_time >= get_shoot_cooldown(
                              players[my_id].upgrades,
                          )
                          and not players[my_id].reloading
                          and players[my_id].ammo > 0):
                        me = players.get(my_id)
                        if me is not None and me.alive:
                            px, py = me.render_pos(now)
                            mx, my = pygame.mouse.get_pos()
                            dx, dy = mx - px, my - py
                            length = math.hypot(dx, dy)
                            if length > 1e-6:
                                try:
                                    sock.sendto(json.dumps({
                                        "type": MSG_SHOOT,
                                        "dx": dx / length, "dy": dy / length,
                                    }).encode("utf-8"), server_addr)
                                    last_shot_time = now
                                except OSError as error:
                                    print(f"[CLIENT] shoot send error: {error}")
                elif (event.type == pygame.KEYDOWN and phase == "draft"
                      and not upgrade_selected and pending_upgrade is None):
                    if pygame.K_1 <= event.key <= pygame.K_3:
                        choice_index = event.key - pygame.K_1
                        if choice_index < len(upgrade_choices):
                            pending_upgrade = upgrade_choices[choice_index]["id"]

            if pending_upgrade is not None and now - last_upgrade_sent >= 0.5:
                try:
                    sock.sendto(json.dumps({
                        "type": MSG_UPGRADE, "upgrade": pending_upgrade,
                    }).encode("utf-8"), server_addr)
                    last_upgrade_sent = now
                except OSError as error:
                    print(f"[CLIENT] upgrade send error: {error}")
            if (start_requested and my_id == host_id and phase == "waiting"
                    and len(players) >= 2 and now - last_start_sent >= 0.5):
                try:
                    sock.sendto(json.dumps({"type": MSG_START}).encode("utf-8"), server_addr)
                    last_start_sent = now
                except OSError as error:
                    print(f"[CLIENT] start send error: {error}")

            keys = pygame.key.get_pressed()
            dx = int(keys[pygame.K_d]) - int(keys[pygame.K_a])
            jump = bool(keys[pygame.K_SPACE])
            facing = 1
            me = players.get(my_id)
            if me is not None:
                px, _ = me.render_pos(now)
                facing = 1 if pygame.mouse.get_pos()[0] >= px else -1
            if my_id is not None:
                try:
                    sock.sendto(json.dumps({
                        "type": MSG_INPUT, "dx": dx, "jump": jump, "facing": facing,
                    }).encode("utf-8"), server_addr)
                except OSError as error:
                    print(f"[CLIENT] input send error: {error}")

            while True:
                try:
                    data, address = sock.recvfrom(BUFFER_SIZE)
                except BlockingIOError:
                    break
                except OSError as error:
                    print(f"[CLIENT] receive error: {error}")
                    break
                if address != server_addr:
                    continue
                try:
                    message = json.loads(data.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(message, dict):
                    continue
                if message.get("type") == MSG_REJECT:
                    reason = message.get("reason")
                    if reason == "color_taken" and my_id is None:
                        available = [
                            tuple(rgb) for rgb in message.get("available_colors", [])
                            if isinstance(rgb, list) and len(rgb) == 3
                        ]
                        if available:
                            selected_color = available[0]
                            join_payload = json.dumps({
                                "type": MSG_JOIN, "name": name,
                                "color": list(selected_color),
                                "eyes_style": eyes_style,
                                "mouth_style": mouth_style,
                                "weapon_style": weapon_style,
                            }).encode("utf-8")
                            profile_notice = "Этот цвет уже выбран — назначен свободный цвет."
                            profile_notice_until = now + 4.0
                            next_join_time = now + 0.2
                        else:
                            error_message = "Нет свободных цветов на сервере."
                            running = False
                    elif reason == "color_taken":
                        profile_notice = "Этот цвет уже занят другим игроком."
                        profile_notice_until = now + 3.0
                    elif reason == "game_started":
                        error_message = "Матч уже начался. Подключиться можно в следующем лобби."
                        running = False
                    elif reason == "invalid_appearance":
                        error_message = "Сервер отклонил параметры внешнего вида игрока."
                        running = False
                    else:
                        error_message = "На сервере нет свободных мест (максимум 4)."
                        running = False
                    continue
                if message.get("type") == MSG_WELCOME:
                    received_id = message.get("id")
                    if isinstance(received_id, int) and not isinstance(received_id, bool):
                        my_id = received_id
                        assigned_color = message.get("color")
                        if isinstance(assigned_color, list) and len(assigned_color) == 3:
                            selected_color = tuple(assigned_color)
                        last_state_time = now
                elif message.get("type") == MSG_STATE:
                    try:
                        previous_phase = phase
                        phase = message["phase"]
                        winner_id = message.get("winner_id")
                        match_winner_id = message.get("match_winner_id")
                        host_id = message.get("host_id")
                        current_map = get_map(message["map_id"])
                        platforms = current_map.platforms
                        incoming_ids = set()
                        for entry in message["players"]:
                            player_id = int(entry["id"])
                            x, y = float(entry["x"]), float(entry["y"])
                            color = tuple(entry["color"])
                            facing = int(entry["facing"])
                            on_ground = bool(entry["on_ground"])
                            player_name = str(entry["name"])
                            hp = int(entry["hp"])
                            alive = bool(entry["alive"])
                            score = int(entry["score"])
                            upgrades = dict(entry["upgrades"])
                            ammo = int(entry["ammo"])
                            reloading = bool(entry["reloading"])
                            reload_time = float(entry["reload_time"])
                            reload_duration = float(entry["reload_duration"])
                            eyes_style = int(entry["eyes_style"])
                            mouth_style = int(entry["mouth_style"])
                            weapon_style = int(entry["weapon_style"])
                            round_streak = int(entry["round_streak"])
                            score_squares = int(entry["score_squares"])
                            vx, vy = float(entry["vx"]), float(entry["vy"])
                            if not math.isfinite(x) or not math.isfinite(y):
                                continue
                            incoming_ids.add(player_id)
                            remote = players.get(player_id)
                            if remote is None:
                                players[player_id] = RemotePlayer(
                                    player_id, x, y, color, facing, on_ground, now,
                                    player_name, hp, alive, score, upgrades,
                                    ammo, reloading, reload_time, reload_duration,
                                    eyes_style, mouth_style, weapon_style,
                                    round_streak,
                                    score_squares,
                                )
                            else:
                                if (phase == previous_phase == "playing"
                                        and remote.alive and hp < remote.hp):
                                    particles.burst(x, y, color, count=14, speed=210, size=6)
                                remote.push_snapshot(
                                    x, y, color, facing, on_ground, now,
                                    player_name, hp, alive, score, upgrades,
                                    vx, vy, ammo, reloading, reload_time,
                                    reload_duration,
                                    eyes_style, mouth_style, weapon_style,
                                    round_streak,
                                    score_squares,
                                )
                            if player_id == my_id:
                                selected_color = color
                                upgrade_choices = list(entry["upgrade_choices"])
                                upgrade_selected = bool(entry["upgrade_selected"])
                                if upgrade_selected:
                                    pending_upgrade = None
                        for player_id in list(players):
                            if player_id not in incoming_ids:
                                del players[player_id]

                        incoming_projectiles = set()
                        for entry in message["projectiles"]:
                            projectile_id = int(entry["id"])
                            incoming_projectiles.add(projectile_id)
                            projectile = projectiles.get(projectile_id)
                            values = (
                                float(entry["x"]), float(entry["y"]),
                                float(entry["vx"]), float(entry["vy"]),
                            )
                            if not all(math.isfinite(value) for value in values):
                                continue
                            gravity = float(entry["gravity"])
                            if not math.isfinite(gravity):
                                continue
                            if projectile is None:
                                projectiles[projectile_id] = RemoteProjectile(
                                    projectile_id, *values, tuple(entry["color"]),
                                    entry["effect"], gravity, now,
                                )
                            else:
                                projectile.push_snapshot(
                                    *values, tuple(entry["color"]),
                                    entry["effect"], gravity, now,
                                )
                        for projectile_id in list(projectiles):
                            if projectile_id not in incoming_projectiles:
                                if phase == previous_phase == "playing":
                                    projectile = projectiles[projectile_id]
                                    x, y = projectile.render_pos(now)
                                    if projectile.effect == "explosion":
                                        count, speed, size = 26, 250, 11
                                    elif projectile.effect == "poison":
                                        count, speed, size = 14, 170, 6
                                    else:
                                        count, speed, size = 7, 130, 4
                                    particles.burst(
                                        x, y, projectile.color,
                                        count=count, speed=speed, size=size,
                                    )
                                del projectiles[projectile_id]
                        last_state_time = now
                        if phase != previous_phase:
                            pending_upgrade = None
                            last_upgrade_sent = 0.0
                            start_requested = False
                    except (KeyError, TypeError, ValueError, OverflowError) as error:
                        print(f"[CLIENT] invalid state packet: {error}")

            draw_arena_background(screen)
            draw_platforms(
                screen, platforms, current_map.platform_color,
                current_map.platform_top_color,
            )
            for player_id, remote in players.items():
                x, y = remote.render_pos(now)
                draw_player(
                    screen, x, y, remote.color, remote.facing,
                    remote.name, remote.hp, remote.alive, font,
                    now, remote.vx, remote.vy, remote.on_ground, player_id,
                    aim_target=pygame.mouse.get_pos() if player_id == my_id else None,
                    recoil=max(0.0, 1.0 - (now - last_shot_time) / 0.12)
                    if player_id == my_id else 0.0,
                    landed_at=remote.landed_at,
                    max_hp=get_max_health(remote.upgrades),
                    ammo=remote.ammo,
                    reloading=remote.reloading,
                    reload_time=remote.reload_time,
                    reload_duration=remote.reload_duration,
                    eyes_style=remote.eyes_style,
                    mouth_style=remote.mouth_style,
                    weapon_style=remote.weapon_style,
                )
            for projectile in projectiles.values():
                x, y = projectile.render_pos(now)
                draw_projectile(screen, x, y, projectile.color)
            particles.update_and_draw(screen, frame_dt)

            # Отрисовка UI (упрощенная)
            if players and phase != "waiting":
                draw_round_scoreboard(screen, players)
            status_text = {
                "connecting": "Подключение...",
                "waiting": "Ожидание второго игрока...",
                "round_over": "Раунд окончен",
                "draft": "Выбор улучшения",
                "match_over": "Матч окончен",
            }.get(phase)
            
            if phase == "draft":
                local_player = players.get(my_id)
                if local_player is not None and winner_id == my_id:
                    status_text = "Раунд выигран — соперники выбирают улучшения"
                elif upgrade_selected:
                    status_text = "Улучшение выбрано — ожидайте следующий раунд"
                elif not upgrade_choices:
                    status_text = "Соперники выбирают улучшения"
                else:
                    status_text = "Проигрыш раунда: выберите улучшение"
                    
            if status_text and phase != "draft":
                if winner_id in players:
                    status_text += f": победил {players[winner_id].name}"
                if phase != "match_over":
                    banner = font.render(status_text, True, (235, 250, 255))
                    banner_rect = banner.get_rect(center=(WIDTH // 2, HEIGHT // 2))
                    panel_rect = banner_rect.inflate(44, 28)
                    draw_panel(screen, panel_rect, fill=(10, 18, 32), border=(255, 111, 105))
                    screen.blit(banner, banner_rect)
                    
            if phase == "draft":
                local_player = players.get(my_id)
                if local_player is not None and winner_id == my_id:
                    banner = font.render(status_text, True, (255, 230, 120))
                    screen.blit(banner, banner.get_rect(center=(WIDTH // 2, HEIGHT // 2)))
                elif upgrade_selected or not upgrade_choices:
                    banner = font.render(status_text, True, (255, 230, 120))
                    screen.blit(banner, banner.get_rect(center=(WIDTH // 2, HEIGHT // 2)))
                else:
                    for index, card in enumerate(upgrade_choices[:3]):
                        rect = card_rects[index]
                        rarity_colors = {
                            "Обычная": (85, 210, 218),
                            "Необычная": (132, 238, 157),
                            "Редкая": (205, 139, 255),
                        }
                        rarity = card["rarity"]
                        border_color = rarity_colors[rarity]
                        draw_panel(screen, rect, fill=(11, 20, 35), border=border_color, radius=14)
                        pygame.draw.line(
                            screen, border_color, (rect.x + 15, rect.bottom - 8),
                            (rect.right - 15, rect.bottom - 8), 2,
                        )
                        title = font.render(
                            f"{index + 1:02d}  {card['name']}", True, (242, 247, 255),
                        )
                        rarity_label = card_font.render(
                            f"◆ {rarity.upper()}", True, rarity_colors[rarity],
                        )
                        description_lines = _wrap_text(
                            card_font, card["description"], rect.width - 28,
                        )
                        stats_lines = _wrap_text(
                            card_font, card.get("stats", ""), rect.width - 28,
                        )
                        level_text = font.render(
                            f"Уровень {card['level']} → {card['level'] + 1}",
                            True, (104, 224, 226),
                        )
                        screen.blit(title, (rect.x + 14, rect.y + 16))
                        screen.blit(rarity_label, (rect.x + 14, rect.y + 48))
                        for line_index, line in enumerate(description_lines[:2]):
                            screen.blit(
                                card_font.render(line, True, (194, 207, 225)),
                                (rect.x + 14, rect.y + 74 + line_index * 20),
                            )
                        for line_index, line in enumerate(stats_lines[:2]):
                            screen.blit(
                                card_font.render(line, True, (143, 166, 194)),
                                (rect.x + 14, rect.y + 120 + line_index * 20),
                            )
                        screen.blit(level_text, (rect.x + 14, rect.y + 162))
                    prompt = font.render(status_text + " · клик или клавиши 1–3",
                                         True, (143, 245, 235))
                    screen.blit(prompt, prompt.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 125)))
                    
            if phase == "match_over":
                champ = players.get(match_winner_id)
                if champ is not None:
                    banner = font.render(
                        f"Матч выиграл {champ.name}!", True, (255, 230, 120),
                    )
                    screen.blit(banner, banner.get_rect(center=(WIDTH // 2, HEIGHT // 2)))
                    
            if phase == "waiting":
                draw_panel(screen, lobby_panel, fill=(10, 17, 31), border=(68, 232, 231), radius=20)
                lobby_title = title_font.render("АРЕНА · ЛОББИ", True, (235, 250, 255))
                screen.blit(lobby_title, lobby_title.get_rect(
                    center=(WIDTH // 2, lobby_panel.y + 48),
                ))
                lobby_subtitle = card_font.render(
                    "Соберите друзей · выберите цвета · дождитесь старта хоста",
                    True, (133, 179, 204),
                )
                screen.blit(lobby_subtitle, lobby_subtitle.get_rect(
                    center=(WIDTH // 2, lobby_panel.y + 82),
                ))
                for index, remote in enumerate(players.values()):
                    row_y = lobby_panel.y + 115 + index * 48
                    row_rect = pygame.Rect(lobby_panel.x + 42, row_y, 576, 44)
                    pygame.draw.rect(screen, (14, 26, 43), row_rect, border_radius=10)
                    pygame.draw.rect(screen, (39, 76, 98), row_rect, 1, border_radius=10)
                    pygame.draw.circle(screen, remote.color, (row_rect.x + 31, row_rect.centery), 13)
                    pygame.draw.circle(screen, (255, 255, 255),
                                       (row_rect.x + 31, row_rect.centery), 16, 2)
                    player_label = font.render(remote.name, True, (235, 244, 252))
                    screen.blit(player_label, (row_rect.x + 62, row_rect.y + 15))
                    role = "ХОСТ" if remote.pid == host_id else "ИГРОК"
                    role_color = (255, 132, 112) if remote.pid == host_id else (104, 201, 211)
                    role_label = card_font.render(role, True, role_color)
                    screen.blit(role_label, role_label.get_rect(
                        midright=(row_rect.right - 18, row_rect.centery),
                    ))
                palette_label = card_font.render(
                    "ВАШ ЦВЕТ — кликните, чтобы выбрать другой",
                    True, (133, 179, 204),
                )
                screen.blit(palette_label, palette_label.get_rect(
                    center=(WIDTH // 2, lobby_panel.y + 322),
                ))
                other_colors = {
                    remote.color for player_id, remote in players.items()
                    if player_id != my_id
                }
                for index, rect in enumerate(lobby_swatches):
                    palette_color = NET_COLORS[index]
                    pygame.draw.circle(screen, palette_color, rect.center, 19)
                    is_selected = palette_color == selected_color
                    is_taken = palette_color in other_colors
                    pygame.draw.circle(
                        screen,
                        (255, 255, 255) if is_selected else (26, 30, 47),
                        rect.center, 21, 3 if is_selected else 2,
                    )
                    if is_taken:
                        pygame.draw.line(screen, (40, 35, 47),
                                         (rect.left + 8, rect.bottom - 8),
                                         (rect.right - 8, rect.top + 8), 4)
                if my_id == host_id:
                    button_color = (28, 135, 132) if len(players) >= 2 else (43, 55, 72)
                    pygame.draw.rect(screen, button_color, lobby_start_rect, border_radius=10)
                    pygame.draw.rect(screen, (68, 232, 231), lobby_start_rect, 2, border_radius=10)
                    button_text = "ЗАПУСТИТЬ МАТЧ" if len(players) >= 2 else "ЖДЁМ ИГРОКОВ..."
                    button_label = font.render(button_text, True, (255, 255, 245))
                    screen.blit(button_label, button_label.get_rect(center=lobby_start_rect.center))
                else:
                    waiting_host = "Хост запустит матч, когда все будут готовы"
                    if host_id in players:
                        waiting_host = f"Ожидание старта от {players[host_id].name}"
                    waiting_label = card_font.render(waiting_host, True, (206, 211, 226))
                    screen.blit(waiting_label, waiting_label.get_rect(
                        center=(WIDTH // 2, lobby_start_rect.centery),
                    ))
                if profile_notice and now < profile_notice_until:
                    toast = card_font.render(profile_notice, True, (255, 209, 145))
                    screen.blit(toast, toast.get_rect(
                        center=(WIDTH // 2, lobby_panel.bottom - 94),
                    ))
                    
            hint = font.render(
                "A/D — движение, Space — прыжок, ЛКМ — выстрел, Esc — выход",
                True, (119, 154, 177),
            )
            screen.blit(hint, (20, HEIGHT - 34))
            
            if error_message:
                error = font.render(error_message, True, (255, 100, 100))
                screen.blit(error, error.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 40)))
                
            if my_id is not None:
                draw_crosshair(screen, pygame.mouse.get_pos())
                
            pygame.display.flip()
    finally:
        if my_id is not None:
            try:
                sock.sendto(json.dumps({"type": MSG_LEAVE}).encode("utf-8"), server_addr)
            except OSError:
                pass
        sock.close()
        pygame.mouse.set_visible(True)
        
    if error_message and not quit_requested:
        while True:
            dismissed = False
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    quit_requested = True
                    dismissed = True
                elif event.type == pygame.KEYDOWN:
                    dismissed = True
            if dismissed:
                break
            screen.fill(current_map.background)
            message = font.render(error_message, True, (255, 120, 120))
            screen.blit(message, message.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 15)))
            hint = font.render("Нажмите любую клавишу для возврата", True, (220, 220, 220))
            screen.blit(hint, hint.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 25)))
            pygame.display.flip()
            clock.tick(FPS)
    return "__quit__" if quit_requested else error_message


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--name", default="player")
    parser.add_argument("--color", type=int, choices=range(len(NET_COLORS)), default=0)
    args = parser.parse_args()

    run_client(args.host, args.port, args.name, NET_COLORS[args.color])


if __name__ == "__main__":
    main()