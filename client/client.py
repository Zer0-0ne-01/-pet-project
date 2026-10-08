# client/client.py
"""Сетевой UDP-клиент Shuffling: side-view, капсула-игрок, стрельба по ЛКМ.

Что нового по сравнению с top-down версией:
- игрок рисуется как капсула 30×60 с «глазом» со стороны facing
- камера фиксированная, платформы видны сразу
- Space — прыжок (шлётся в input как jump)
- facing считается по положению мыши относительно игрока и шлётся на сервер
- ЛКМ — выстрел в направлении мыши
- снаряды интерполируются экстраполяцией (v = const)
"""

import argparse
import json
import math
import socket
import time

import pygame

from shared.config import (
    WIDTH, HEIGHT, FPS, BUFFER_SIZE,
    NET_TICK_DT as SERVER_TICK_DT,
    PLAYER_W, PLAYER_H,
    PROJECTILE_RADIUS,
    SHOOT_COOLDOWN,
    NET_JOIN_RETRY,
)
from shared.protocol import (
    MSG_JOIN, MSG_INPUT, MSG_SHOOT, MSG_LEAVE,
    MSG_REJECT, MSG_WELCOME, MSG_STATE,
)
from shared.level import get_platforms
from client.ui import draw_crosshair


# --- ЦВЕТА УРОВНЯ ---
BG_COLOR = (30, 30, 60)
PLATFORM_COLOR = (70, 70, 110)
PLATFORM_TOP_COLOR = (100, 100, 160)


class RemotePlayer:
    """Сглаженное представление игрока в клиенте (интерполяция)."""

    def __init__(self, pid, x, y, color, facing, on_ground, now,
                 name="player", hp=100, alive=True, score=0):
        self.pid = pid
        self.color = color
        self.facing = facing
        self.on_ground = on_ground
        self.name = name
        self.hp = hp
        self.alive = alive
        self.score = score

        self.prev_x = x
        self.prev_y = y
        self.target_x = x
        self.target_y = y
        self.snapshot_time = now

    def push_snapshot(self, x, y, color, facing, on_ground, now,
                      name, hp, alive, score):
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

def draw_platforms(screen, platforms):
    for p in platforms:
        rect = pygame.Rect(int(p.x), int(p.y), int(p.w), int(p.h))
        pygame.draw.rect(screen, PLATFORM_COLOR, rect)
        # светлая полоска сверху — «трава»
        pygame.draw.rect(
            screen, PLATFORM_TOP_COLOR,
            (rect.x, rect.y, rect.w, 3),
        )


def draw_player(screen, x, y, color, facing, is_me, name, hp, alive, font):
    """Капсула 30×60 с обводкой для себя и «глазом» со стороны facing."""
    cx, cy = int(x), int(y)
    rect = pygame.Rect(cx - PLAYER_W // 2, cy - PLAYER_H // 2, PLAYER_W, PLAYER_H)
    if not alive:
        return

    pygame.draw.rect(screen, color, rect, border_radius=PLAYER_W // 2)
    if is_me:
        pygame.draw.rect(screen, (255, 255, 255), rect, 2,
                         border_radius=PLAYER_W // 2)
    eye_x = cx + facing * 7
    eye_y = cy - PLAYER_H // 4
    pygame.draw.circle(screen, (255, 255, 255), (eye_x, eye_y), 4)
    pygame.draw.circle(screen, (20, 20, 30), (eye_x, eye_y), 2)
    label = font.render(f"{name}  {hp} HP", True, (255, 255, 255))
    screen.blit(label, label.get_rect(midbottom=(cx, rect.top - 5)))


def draw_projectile(screen, x, y, color):
    ix, iy = int(x), int(y)
    # мягкое свечение
    glow = pygame.Surface((PROJECTILE_RADIUS * 4,) * 2, pygame.SRCALPHA)
    pygame.draw.circle(glow, (*color, 90),
                       (PROJECTILE_RADIUS * 2, PROJECTILE_RADIUS * 2),
                       PROJECTILE_RADIUS * 2)
    screen.blit(glow, (ix - PROJECTILE_RADIUS * 2, iy - PROJECTILE_RADIUS * 2))
    pygame.draw.circle(screen, color, (ix, iy), PROJECTILE_RADIUS)
    pygame.draw.circle(screen, (255, 255, 255), (ix, iy), PROJECTILE_RADIUS, 1)


# --- ОСНОВНОЙ ЦИКЛ ---

def run_client(host="127.0.0.1", port=9999, name="player"):
    server_addr = (host, port)
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption(f"Shuffling — {name}")
    pygame.mouse.set_visible(False)
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("consolas", 20)
    platforms = get_platforms()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    join_payload = json.dumps({"type": MSG_JOIN, "name": name}).encode("utf-8")
    my_id = None
    players = {}
    projectiles = {}
    last_shot_time = 0.0
    next_join_time = 0.0
    last_state_time = time.monotonic()
    phase = "connecting"
    round_number = 0
    winner_id = None
    error_message = None
    quit_requested = False
    running = True
    try:
        while running:
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
                    if my_id is not None and now - last_shot_time >= SHOOT_COOLDOWN:
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
                    error_message = "На сервере нет свободных мест (максимум 4)."
                    running = False
                    continue
                if message.get("type") == MSG_WELCOME:
                    received_id = message.get("id")
                    if isinstance(received_id, int) and not isinstance(received_id, bool):
                        my_id = received_id
                        last_state_time = now
                elif message.get("type") == MSG_STATE:
                    try:
                        phase = message["phase"]
                        round_number = int(message["round"])
                        winner_id = message.get("winner_id")
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
                            if not math.isfinite(x) or not math.isfinite(y):
                                continue
                            incoming_ids.add(player_id)
                            remote = players.get(player_id)
                            if remote is None:
                                players[player_id] = RemotePlayer(
                                    player_id, x, y, color, facing, on_ground, now,
                                    player_name, hp, alive, score,
                                )
                            else:
                                remote.push_snapshot(
                                    x, y, color, facing, on_ground, now,
                                    player_name, hp, alive, score,
                                )
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
                                del projectiles[projectile_id]
                        last_state_time = now
                    except (KeyError, TypeError, ValueError, OverflowError) as error:
                        print(f"[CLIENT] invalid state packet: {error}")

            screen.fill(BG_COLOR)
            draw_platforms(screen, platforms)
            for player_id, remote in players.items():
                x, y = remote.render_pos(now)
                draw_player(
                    screen, x, y, remote.color, remote.facing,
                    player_id == my_id, remote.name, remote.hp, remote.alive, font,
                )
            for projectile in projectiles.values():
                x, y = projectile.render_pos(now)
                draw_projectile(screen, x, y, projectile.color)

            scoreboard = "   ".join(
                f"{remote.name}: {remote.score}" for remote in players.values()
            )
            screen.blit(font.render(f"Раунд {round_number}   {scoreboard}", True,
                                    (255, 255, 255)), (20, 20))
            status_text = {
                "connecting": "Подключение...",
                "waiting": "Ожидание второго игрока...",
                "round_over": "Раунд окончен",
                "match_over": "Матч окончен",
            }.get(phase)
            if status_text:
                if winner_id in players:
                    status_text += f": победил {players[winner_id].name}"
                banner = font.render(status_text, True, (255, 230, 120))
                screen.blit(banner, banner.get_rect(center=(WIDTH // 2, HEIGHT // 2)))
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
            clock.tick(FPS)
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
            screen.fill(BG_COLOR)
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
    args = parser.parse_args()

    run_client(args.host, args.port, args.name)


if __name__ == "__main__":
    main()