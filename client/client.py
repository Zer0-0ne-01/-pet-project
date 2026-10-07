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
)
from shared.protocol import (
    MSG_JOIN, MSG_INPUT, MSG_SHOOT, MSG_LEAVE,
    MSG_WELCOME, MSG_STATE,
)
from shared.level import get_platforms
from client.ui import draw_crosshair


# --- ЦВЕТА УРОВНЯ ---
BG_COLOR = (30, 30, 60)
PLATFORM_COLOR = (70, 70, 110)
PLATFORM_TOP_COLOR = (100, 100, 160)


class RemotePlayer:
    """Сглаженное представление игрока в клиенте (интерполяция)."""

    def __init__(self, pid, x, y, color, facing, on_ground, now):
        self.pid = pid
        self.color = color
        self.facing = facing
        self.on_ground = on_ground

        self.prev_x = x
        self.prev_y = y
        self.target_x = x
        self.target_y = y
        self.snapshot_time = now

    def push_snapshot(self, x, y, color, facing, on_ground, now):
        t = min(1.0, (now - self.snapshot_time) / SERVER_TICK_DT)
        self.prev_x += (self.target_x - self.prev_x) * t
        self.prev_y += (self.target_y - self.prev_y) * t
        self.target_x = x
        self.target_y = y
        self.snapshot_time = now
        self.color = color
        self.facing = facing
        self.on_ground = on_ground

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


def draw_player(screen, x, y, color, facing, is_me):
    """Капсула 30×60 с обводкой для себя и «глазом» со стороны facing."""
    cx, cy = int(x), int(y)
    rect = pygame.Rect(cx - PLAYER_W // 2, cy - PLAYER_H // 2, PLAYER_W, PLAYER_H)

    # тело — прямоугольник со скруглёнными углами радиусом = половина ширины
    pygame.draw.rect(screen, color, rect, border_radius=PLAYER_W // 2)

    # обводка для себя
    if is_me:
        pygame.draw.rect(screen, (255, 255, 255), rect, 2,
                         border_radius=PLAYER_W // 2)

    # «глаз» — куда смотрит
    eye_x = cx + facing * 7
    eye_y = cy - PLAYER_H // 4
    pygame.draw.circle(screen, (255, 255, 255), (eye_x, eye_y), 4)
    pygame.draw.circle(screen, (20, 20, 30), (eye_x, eye_y), 2)


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

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)

    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption(f"Shuffling — {name}")
    pygame.mouse.set_visible(False)          # у нас свой прицел
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("consolas", 20)

    platforms = get_platforms()

    # --- join (трижды, чтобы пережить потерю первого пакета) ---
    join_payload = json.dumps({"type": MSG_JOIN, "name": name}).encode("utf-8")
    for _ in range(3):
        sock.sendto(join_payload, server_addr)
        time.sleep(0.05)

    my_id = None
    players = {}         # id -> RemotePlayer
    projectiles = {}     # id -> RemoteProjectile
    last_shot_time = 0.0

    running = True
    while running:
        now = time.time()

        # --- 1. СОБЫТИЯ ---
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                # ЛКМ — выстрел в направлении мыши
                if my_id is not None and (now - last_shot_time) >= SHOOT_COOLDOWN:
                    me = players.get(my_id)
                    if me is not None:
                        px, py = me.render_pos(now)
                        mx, my = pygame.mouse.get_pos()
                        ddx, ddy = mx - px, my - py
                        length = math.hypot(ddx, ddy)
                        if length > 1e-6:
                            ddx /= length
                            ddy /= length
                            try:
                                sock.sendto(
                                    json.dumps({
                                        "type": MSG_SHOOT,
                                        "dx": ddx, "dy": ddy,
                                    }).encode("utf-8"),
                                    server_addr,
                                )
                                last_shot_time = now
                            except OSError as e:
                                print(f"[CLIENT] shoot send error: {e}")

        # --- 2. ВВОД ---
        keys = pygame.key.get_pressed()
        dx = int(keys[pygame.K_d]) - int(keys[pygame.K_a])
        jump = bool(keys[pygame.K_SPACE])

        # facing — по мыши относительно моего игрока
        facing = 1
        if my_id is not None and my_id in players:
            px, py = players[my_id].render_pos(now)
            mx, _my = pygame.mouse.get_pos()
            facing = 1 if mx >= px else -1

        try:
            sock.sendto(
                json.dumps({
                    "type": MSG_INPUT,
                    "dx": dx,
                    "jump": jump,
                    "facing": facing,
                }).encode("utf-8"),
                server_addr,
            )
        except OSError as e:
            print(f"[CLIENT] send error: {e}")

        # --- 3. ПРИЁМ ---
        while True:
            try:
                data, addr = sock.recvfrom(BUFFER_SIZE)
            except BlockingIOError:
                break
            except OSError as e:
                print(f"[CLIENT] recv error: {e}")
                break

            try:
                msg = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue

            mtype = msg.get("type")

            if mtype == MSG_WELCOME:
                my_id = msg["id"]
                print(f"[CLIENT] joined as id={my_id}")

            elif mtype == MSG_STATE:
                # --- игроки ---
                incoming_ids = set()
                for entry in msg.get("players", []):
                    pid = entry["id"]
                    x = float(entry["x"])
                    y = float(entry["y"])
                    color = tuple(entry["color"])
                    facing = int(entry.get("facing", 1))
                    on_ground = bool(entry.get("on_ground", False))
                    incoming_ids.add(pid)

                    rp = players.get(pid)
                    if rp is None:
                        players[pid] = RemotePlayer(pid, x, y, color,
                                                    facing, on_ground, now)
                    else:
                        rp.push_snapshot(x, y, color, facing, on_ground, now)

                for pid in list(players.keys()):
                    if pid not in incoming_ids:
                        del players[pid]

                # --- снаряды ---
                incoming_proj = set()
                for entry in msg.get("projectiles", []):
                    pr_id = entry["id"]
                    incoming_proj.add(pr_id)
                    rp = projectiles.get(pr_id)
                    if rp is None:
                        projectiles[pr_id] = RemoteProjectile(
                            pr_id,
                            float(entry["x"]), float(entry["y"]),
                            float(entry["vx"]), float(entry["vy"]),
                            tuple(entry["color"]),
                            now,
                        )
                    else:
                        rp.push_snapshot(
                            float(entry["x"]), float(entry["y"]),
                            float(entry["vx"]), float(entry["vy"]),
                            tuple(entry["color"]),
                            now,
                        )

                for pr_id in list(projectiles.keys()):
                    if pr_id not in incoming_proj:
                        del projectiles[pr_id]

        # --- 4. РИСОВАНИЕ ---
        screen.fill(BG_COLOR)
        draw_platforms(screen, platforms)

        # игроки
        for pid, rp in players.items():
            x, y = rp.render_pos(now)
            draw_player(screen, x, y, rp.color, rp.facing, pid == my_id)

        # снаряды
        for pr in projectiles.values():
            x, y = pr.render_pos(now)
            draw_projectile(screen, x, y, pr.color)

        # прицел
        draw_crosshair(screen, pygame.mouse.get_pos())

        # подсказки
        hint = font.render(
            "A/D — движение, Space — прыжок, ЛКМ — выстрел, Esc — выход",
            True, (255, 255, 255),
        )
        screen.blit(hint, (20, 20))

        status = f"id: {my_id}   players: {len(players)}   bullets: {len(projectiles)}"
        screen.blit(font.render(status, True, (220, 220, 220)), (20, 50))

        pygame.display.flip()
        clock.tick(FPS)

    try:
        sock.sendto(json.dumps({"type": MSG_LEAVE}).encode("utf-8"), server_addr)
    except OSError:
        pass
    sock.close()
    pygame.quit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--name", default="player")
    args = parser.parse_args()

    run_client(args.host, args.port, args.name)


if __name__ == "__main__":
    main()