# client/client.py
"""Сетевой UDP-клиент Shuffling: арена, круглые игроки и стрельба по ЛКМ.

Игроки настраивают ник и цвет до подключения; хост запускает матч из лобби.
"""

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
    PLAYER_MAX_HP,
    SHOOT_COOLDOWN,
    NET_JOIN_RETRY,
    NET_COLORS,
)
from shared.protocol import (
    MSG_JOIN, MSG_INPUT, MSG_SHOOT, MSG_LEAVE,
    MSG_PROFILE, MSG_REJECT, MSG_START, MSG_UPGRADE, MSG_WELCOME, MSG_STATE,
)
from shared.level import get_map
from client.ui import draw_crosshair


class RemotePlayer:
    """Сглаженное представление игрока в клиенте (интерполяция)."""

    def __init__(self, pid, x, y, color, facing, on_ground, now,
                 name="player", hp=100, alive=True, score=0, upgrades=None):
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
        self.vx = 0.0
        self.vy = 0.0

        self.prev_x = x
        self.prev_y = y
        self.target_x = x
        self.target_y = y
        self.snapshot_time = now

    def push_snapshot(self, x, y, color, facing, on_ground, now,
                      name, hp, alive, score, upgrades, vx, vy):
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
        self.vx = vx
        self.vy = vy

    def render_pos(self, now):
        t = min(1.0, (now - self.snapshot_time) / SERVER_TICK_DT)
        x = self.prev_x + (self.target_x - self.prev_x) * t
        y = self.prev_y + (self.target_y - self.prev_y) * t
        return x, y


class RemoteProjectile:
    """Снаряд на клиенте: экстраполяция позиции (скорость постоянна)."""

    def __init__(self, pid, x, y, vx, vy, color, now):
        self.pid = pid
        self.color = color
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.updated_at = now

    def push_snapshot(self, x, y, vx, vy, color, now):
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.color = color
        self.updated_at = now

    def render_pos(self, now):
        dt = now - self.updated_at
        return self.x + self.vx * dt, self.y + self.vy * dt


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
        remaining = max(0, 180 - len(self.particles))
        for _ in range(min(count, remaining)):
            angle = random.uniform(0, math.tau)
            velocity = random.uniform(speed * 0.35, speed)
            self.particles.append(Particle(
                x, y,
                math.cos(angle) * velocity,
                math.sin(angle) * velocity,
                color,
                random.uniform(size * 0.55, size * 1.3),
                random.uniform(0.22, 0.48),
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
            particle.vx *= max(0.0, 1 - 2.5 * dt)
            particle.vy = particle.vy * max(0.0, 1 - 2.5 * dt) + 260 * dt
            progress = particle.age / particle.lifetime
            radius = max(1, round(particle.size * (1 - progress * 0.72)))
            alpha = round(255 * (1 - progress) ** 1.5)
            color = (*particle.color, alpha)
            center = (round(particle.x), round(particle.y))
            if particle.square:
                rect = pygame.Rect(0, 0, radius * 2, radius * 2)
                rect.center = center
                pygame.draw.rect(self.surface, color, rect, border_radius=1)
            else:
                pygame.gfxdraw.filled_circle(self.surface, *center, radius, color)
                pygame.gfxdraw.aacircle(self.surface, *center, radius, color)
        self.particles = alive
        screen.blit(self.surface, (0, 0))


@lru_cache(maxsize=48)
def _make_glow(color, radius, alpha):
    margin = radius * 5
    diameter = margin * 2 + 1
    glow = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
    center = (margin, margin)
    for scale, opacity in ((2.8, 0.10), (2.1, 0.16), (1.55, 0.27), (1.0, 0.72)):
        ring_radius = max(1, round(radius * scale))
        ring_color = (*color, round(alpha * opacity))
        pygame.gfxdraw.filled_circle(glow, *center, ring_radius, ring_color)
        pygame.gfxdraw.aacircle(glow, *center, ring_radius, ring_color)
    return glow


BACKGROUND_COLOR = (26, 26, 36)


@lru_cache(maxsize=96)
def _make_player_body(color, width, height):
    scale = 3
    padding = 6
    sprite = pygame.Surface(
        (width * scale + padding * 2, height * scale + padding * 2),
        pygame.SRCALPHA,
    )
    bounds = pygame.Rect(
        padding, padding, width * scale, height * scale,
    )
    pygame.draw.ellipse(sprite, (8, 8, 12), bounds)
    pygame.draw.ellipse(
        sprite, color,
        bounds.inflate(-4 * scale, -4 * scale),
    )
    return pygame.transform.smoothscale(sprite, (width, height))


def draw_arena_background(screen):
    screen.fill(BACKGROUND_COLOR)


def draw_platforms(screen, platforms, platform_color, platform_top_color):
    for p in platforms:
        rect = pygame.Rect(int(p.x), int(p.y), int(p.w), int(p.h))
        pygame.draw.rect(screen, platform_color, rect, border_radius=6)
        pygame.draw.line(
            screen, platform_top_color, (rect.left + 6, rect.top + 2),
            (rect.right - 7, rect.top + 2), 2,
        )


def draw_player(screen, x, y, color, facing, name, hp, alive, font,
                now, vx, vy, on_ground, player_id, aim_target=None,
                recoil=0.0, landed_at=0.0):
    """Рисует сглаженного персонажа с простой процедурной анимацией."""
    if not alive:
        return

    radius = PLAYER_W // 2
    moving = abs(vx) > 25
    gait_phase = now * 12 + player_id * 1.7
    gait = math.sin(gait_phase) if moving else 0.0
    bob = abs(math.sin(gait_phase)) * 1.5 if moving else 0.0
    stretch = 0.12 if not on_ground and vy < -80 else 0.04 if not on_ground else 0.0
    landing = max(0.0, 1.0 - (now - landed_at) / 0.16) if landed_at else 0.0
    body_w = int(PLAYER_W * (1.0 - stretch * 0.35 + landing * 0.18))
    body_h = int(PLAYER_H * (1.0 + stretch - landing * 0.22))
    cx, cy = int(x + (vx / 300) * 2), int(y + bob)
    rect = pygame.Rect(0, 0, body_w, body_h)
    rect.center = (cx, cy)
    shadow_width = max(18, int(radius * 1.8 - min(abs(vy) / 40, 14)))
    shadow = pygame.Rect(cx - shadow_width // 2, int(y + radius - 2), shadow_width, 8)
    pygame.draw.ellipse(screen, (13, 13, 20), shadow)

    limb_color = (18, 18, 25)
    leg_length = 14
    hip_y = rect.bottom - 5
    for side in (-1, 1):
        leg_angle = gait * 32 * side if moving else 0.0
        leg_vector = pygame.math.Vector2(0, leg_length).rotate(leg_angle)
        leg_start = (cx + side * 6, hip_y)
        leg_end = (round(leg_start[0] + leg_vector.x), round(leg_start[1] + leg_vector.y))
        pygame.draw.line(screen, limb_color, leg_start, leg_end, 3)

    if aim_target is None:
        aim_target = (cx + facing * 100, cy)
    aim_angle = math.atan2(aim_target[1] - cy, aim_target[0] - cx)
    aim_direction = pygame.math.Vector2(math.cos(aim_angle), math.sin(aim_angle))
    perpendicular = pygame.math.Vector2(-aim_direction.y, aim_direction.x)
    if perpendicular.y < 0:
        perpendicular = -perpendicular
    arm_side = 1 if aim_direction.x >= 0 else -1
    shoulder = pygame.math.Vector2(cx + arm_side * body_w * 0.40, cy - 3)
    hand = shoulder + aim_direction * (16 - max(0.0, min(1.0, recoil)) * 6)
    other_shoulder = pygame.math.Vector2(cx - arm_side * body_w * 0.36, cy - 2)
    other_elbow = other_shoulder + pygame.math.Vector2(-arm_side * 5, 7)
    other_hand = other_elbow + pygame.math.Vector2(-arm_side * 12, 3)

    body = _make_player_body(tuple(color), body_w, body_h)
    screen.blit(body, body.get_rect(center=(cx, cy)))
    pygame.draw.line(screen, limb_color, other_shoulder, other_elbow, 3)
    pygame.draw.line(screen, limb_color, other_elbow, other_hand, 3)
    pygame.draw.line(screen, limb_color, shoulder, hand, 3)

    muzzle = hand + aim_direction * 14
    grip_start = hand + aim_direction * 5
    grip_end = grip_start + perpendicular * 8
    pygame.draw.line(screen, (17, 17, 23), hand, muzzle, 4)
    pygame.draw.line(screen, (17, 17, 23), grip_start, grip_end, 4)
    pygame.draw.line(screen, (92, 92, 105), hand + aim_direction * 7,
                     muzzle - aim_direction * 2, 1)
    pygame.draw.circle(screen, (24, 24, 31), (round(other_hand.x), round(other_hand.y)), 2)
    pygame.draw.circle(screen, (24, 24, 31), (round(hand.x), round(hand.y)), 2)

    eye_y = cy - 4
    eye_offset = 5
    for offset in (-eye_offset, eye_offset):
        eye_x = cx + facing * 2 + offset
        pygame.gfxdraw.filled_circle(screen, eye_x, eye_y, 2, (14, 14, 19))
    name_surface = _cached_text(font, name, (231, 236, 249))
    screen.blit(name_surface, name_surface.get_rect(midbottom=(cx, rect.top - 8)))
    bar_width, bar_height = 40, 3
    bar_x, bar_y = cx - bar_width // 2, rect.top - 5
    pygame.draw.rect(screen, (26, 29, 43), (bar_x, bar_y, bar_width, bar_height))
    hp_ratio = max(0.0, min(1.0, hp / PLAYER_MAX_HP))
    if hp_ratio:
        hp_color = (255, 199, 94) if hp_ratio > 0.3 else (255, 104, 112)
        pygame.draw.rect(screen, hp_color,
                         (bar_x, bar_y, round(bar_width * hp_ratio), bar_height))


def draw_projectile(screen, x, y, color):
    ix, iy = int(x), int(y)
    glow = _make_glow(tuple(color), PROJECTILE_RADIUS, 210)
    screen.blit(glow, glow.get_rect(center=(ix, iy)))
    pygame.gfxdraw.filled_circle(screen, ix, iy, PROJECTILE_RADIUS, color)
    pygame.gfxdraw.aacircle(screen, ix, iy, PROJECTILE_RADIUS, (255, 255, 255))
    pygame.gfxdraw.filled_circle(
        screen, ix - 1, iy - 1, max(1, PROJECTILE_RADIUS // 3), (255, 255, 255),
    )


# --- ОСНОВНОЙ ЦИКЛ ---

def run_client(host="127.0.0.1", port=9999, name="player", color=None):
    server_addr = (host, port)
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption(f"Shuffling — {name}")
    pygame.mouse.set_visible(False)
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("arial", 20)
    card_font = pygame.font.SysFont("arial", 16)
    title_font = pygame.font.SysFont("arial", 30, bold=True)
    current_map = get_map("classic")
    platforms = current_map.platforms
    selected_color = tuple(color or NET_COLORS[0])
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    join_payload = json.dumps({
        "type": MSG_JOIN, "name": name, "color": list(selected_color),
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
    round_number = 0
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
                    elif (phase == "playing" and my_id is not None
                          and now - last_shot_time >= SHOOT_COOLDOWN):
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
                        round_number = int(message["round"])
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
                            vx, vy = float(entry["vx"]), float(entry["vy"])
                            if not math.isfinite(x) or not math.isfinite(y):
                                continue
                            incoming_ids.add(player_id)
                            remote = players.get(player_id)
                            if remote is None:
                                players[player_id] = RemotePlayer(
                                    player_id, x, y, color, facing, on_ground, now,
                                    player_name, hp, alive, score, upgrades,
                                )
                            else:
                                if (phase == previous_phase == "playing"
                                        and remote.alive and hp < remote.hp):
                                    particles.burst(x, y, color, count=14, speed=210, size=6)
                                remote.push_snapshot(
                                    x, y, color, facing, on_ground, now,
                                    player_name, hp, alive, score, upgrades,
                                    vx, vy,
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
                            if projectile is None:
                                projectiles[projectile_id] = RemoteProjectile(
                                    projectile_id, *values, tuple(entry["color"]), now,
                                )
                            else:
                                projectile.push_snapshot(
                                    *values, tuple(entry["color"]), now,
                                )
                        for projectile_id in list(projectiles):
                            if projectile_id not in incoming_projectiles:
                                if phase == previous_phase == "playing":
                                    projectile = projectiles[projectile_id]
                                    x, y = projectile.render_pos(now)
                                    particles.burst(
                                        x, y, projectile.color,
                                        count=7, speed=130, size=4,
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
                )
            for projectile in projectiles.values():
                x, y = projectile.render_pos(now)
                draw_projectile(screen, x, y, projectile.color)
            particles.update_and_draw(screen, frame_dt)

            scoreboard = "   ".join(
                f"{remote.name}: {remote.score}" for remote in players.values()
            )
            screen.blit(font.render(f"Раунд {round_number}   {scoreboard}", True,
                                    (255, 255, 255)), (20, 20))
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
                    banner = font.render(status_text, True, (255, 230, 120))
                    screen.blit(banner, banner.get_rect(center=(WIDTH // 2, HEIGHT // 2)))
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
                        pygame.draw.rect(screen, (40, 43, 65), rect, border_radius=12)
                        pygame.draw.rect(screen, (220, 200, 110), rect, 2, border_radius=12)
                        title = font.render(f"{index + 1}. {card['name']}", True, (255, 240, 180))
                        description = card_font.render(
                            card["description"], True, (235, 235, 245),
                        )
                        level_text = font.render(
                            f"Уровень {card['level']} → {card['level'] + 1}",
                            True, (180, 215, 255),
                        )
                        screen.blit(title, (rect.x + 14, rect.y + 24))
                        screen.blit(description, (rect.x + 14, rect.y + 78))
                        screen.blit(level_text, (rect.x + 14, rect.y + 132))
                    prompt = font.render(status_text + " (клик или клавиши 1–3)",
                                         True, (255, 230, 120))
                    screen.blit(prompt, prompt.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 125)))
            if phase == "match_over":
                champ = players.get(match_winner_id)
                if champ is not None:
                    banner = font.render(
                        f"Матч выиграл {champ.name}!", True, (255, 230, 120),
                    )
                    screen.blit(banner, banner.get_rect(center=(WIDTH // 2, HEIGHT // 2)))
            if phase == "waiting":
                panel_surface = pygame.Surface(lobby_panel.size, pygame.SRCALPHA)
                panel_surface.fill((19, 23, 40, 232))
                screen.blit(panel_surface, lobby_panel.topleft)
                pygame.draw.rect(screen, (116, 131, 177), lobby_panel, 2, border_radius=20)
                lobby_title = title_font.render("ПРЕДСТАРТОВОЕ ЛОББИ", True, (247, 225, 164))
                screen.blit(lobby_title, lobby_title.get_rect(
                    center=(WIDTH // 2, lobby_panel.y + 48),
                ))
                lobby_subtitle = card_font.render(
                    "Соберите друзей · выберите цвета · дождитесь старта хоста",
                    True, (184, 195, 220),
                )
                screen.blit(lobby_subtitle, lobby_subtitle.get_rect(
                    center=(WIDTH // 2, lobby_panel.y + 82),
                ))
                for index, remote in enumerate(players.values()):
                    row_y = lobby_panel.y + 115 + index * 48
                    row_rect = pygame.Rect(lobby_panel.x + 42, row_y, 576, 44)
                    pygame.draw.rect(screen, (34, 39, 60), row_rect, border_radius=12)
                    pygame.draw.circle(screen, remote.color, (row_rect.x + 31, row_rect.centery), 16)
                    pygame.draw.circle(screen, (255, 255, 255),
                                       (row_rect.x + 31, row_rect.centery), 16, 2)
                    player_label = font.render(remote.name, True, (245, 245, 250))
                    screen.blit(player_label, (row_rect.x + 62, row_rect.y + 15))
                    role = "ХОСТ" if remote.pid == host_id else "ИГРОК"
                    role_color = (246, 210, 120) if remote.pid == host_id else (160, 174, 207)
                    role_label = card_font.render(role, True, role_color)
                    screen.blit(role_label, role_label.get_rect(
                        midright=(row_rect.right - 18, row_rect.centery),
                    ))
                palette_label = card_font.render(
                    "ВАШ ЦВЕТ — кликните, чтобы выбрать другой",
                    True, (185, 197, 224),
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
                    button_color = (83, 174, 119) if len(players) >= 2 else (74, 80, 100)
                    pygame.draw.rect(screen, button_color, lobby_start_rect, border_radius=13)
                    pygame.draw.rect(screen, (208, 231, 198), lobby_start_rect, 2, border_radius=13)
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
                True, (255, 255, 255),
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