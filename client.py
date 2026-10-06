# client.py
import argparse
import json
import math
import socket
import time

import pygame

# --- СЕТЬ ---
BUFFER_SIZE = 2048
SERVER_TICK_DT = 1.0 / 30.0

# --- ВИЗУАЛ ---
WIDTH, HEIGHT = 1024, 768
PLAYER_RADIUS = 20
PROJECTILE_RADIUS = 6

# Локальный кулдаун — чтобы клиент не забивал канал пустыми "shoot",
# которые сервер всё равно отбросит. Должен быть >= серверного.
SHOOT_COOLDOWN = 0.20


class RemotePlayer:
    """Сглаженное представление игрока в клиенте."""
    def __init__(self, pid, x, y, color, now):
        self.pid = pid
        self.color = color
        self.prev_x = x
        self.prev_y = y
        self.target_x = x
        self.target_y = y
        self.snapshot_time = now

    def push_snapshot(self, x, y, color, now):
        t = min(1.0, (now - self.snapshot_time) / SERVER_TICK_DT)
        self.prev_x += (self.target_x - self.prev_x) * t
        self.prev_y += (self.target_y - self.prev_y) * t
        self.target_x = x
        self.target_y = y
        self.snapshot_time = now
        self.color = color

    def render_pos(self, now):
        t = min(1.0, (now - self.snapshot_time) / SERVER_TICK_DT)
        x = self.prev_x + (self.target_x - self.prev_x) * t
        y = self.prev_y + (self.target_y - self.prev_y) * t
        return x, y


class RemoteProjectile:
    """
    Снаряд на клиенте. Скорость постоянна, поэтому вместо
    сглаживания используем ЭКСТРАПОЛЯЦИЮ: рисуем позицию,
    продвинутую вперёд на (now - updated_at).
    """
    def __init__(self, pid, x, y, vx, vy, color, now):
        self.pid = pid
        self.color = color
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.updated_at = now

    def push_snapshot(self, x, y, vx, vy, color, now):
        # Просто принимаем серверную правду и «обнуляем» отсчёт времени.
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.color = color
        self.updated_at = now

    def render_pos(self, now):
        dt = now - self.updated_at
        return self.x + self.vx * dt, self.y + self.vy * dt


def draw_crosshair(screen, pos):
    x, y = pos
    color = (230, 230, 230)
    pygame.draw.line(screen, color, (x - 10, y), (x + 10, y), 2)
    pygame.draw.line(screen, color, (x, y - 10), (x, y + 10), 2)
    pygame.draw.circle(screen, color, (x, y), 12, 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--name", default="player")
    args = parser.parse_args()

    server_addr = (args.host, args.port)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)

    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption(f"Shuffling — {args.name}")
    pygame.mouse.set_visible(False)          # рисуем свой прицел
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("consolas", 20)

    # --- join: шлём несколько раз, чтобы уменьшить шанс потери первого пакета ---
    join_payload = json.dumps({"type": "join", "name": args.name}).encode("utf-8")
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
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    # Стреляем в сторону курсора
                    if my_id is not None and (now - last_shot_time) >= SHOOT_COOLDOWN:
                        me = players.get(my_id)
                        if me is not None:
                            px, py = me.render_pos(now)
                            mx, my = pygame.mouse.get_pos()
                            dx = mx - px
                            dy = my - py
                            length = math.hypot(dx, dy)
                            if length > 1e-6:
                                dx /= length
                                dy /= length
                                try:
                                    sock.sendto(
                                        json.dumps({
                                            "type": "shoot",
                                            "dx": dx,
                                            "dy": dy,
                                        }).encode("utf-8"),
                                        server_addr,
                                    )
                                    last_shot_time = now
                                except OSError as e:
                                    print(f"[CLIENT] shoot send error: {e}")

        # --- 2. ВВОД И ОТПРАВКА ---
        keys = pygame.key.get_pressed()
        dx = int(keys[pygame.K_d]) - int(keys[pygame.K_a])
        dy = int(keys[pygame.K_s]) - int(keys[pygame.K_w])

        try:
            sock.sendto(
                json.dumps({"type": "input", "dx": dx, "dy": dy}).encode("utf-8"),
                server_addr,
            )
        except OSError as e:
            print(f"[CLIENT] send error: {e}")

        # --- 3. ПРИЁМ СОСТОЯНИЯ ---
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

            if mtype == "welcome":
                my_id = msg["id"]
                print(f"[CLIENT] joined as id={my_id}")

            elif mtype == "state":
                # --- игроки ---
                incoming_ids = set()
                for entry in msg.get("players", []):
                    pid = entry["id"]
                    x = float(entry["x"])
                    y = float(entry["y"])
                    color = tuple(entry["color"])
                    incoming_ids.add(pid)

                    rp = players.get(pid)
                    if rp is None:
                        players[pid] = RemotePlayer(pid, x, y, color, now)
                    else:
                        rp.push_snapshot(x, y, color, now)

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
        screen.fill((30, 30, 60))

        # игроки
        for pid, rp in players.items():
            x, y = rp.render_pos(now)
            is_me = (pid == my_id)
            radius = PLAYER_RADIUS + (4 if is_me else 0)

            pygame.draw.circle(screen, rp.color, (int(x), int(y)), radius)

            if is_me:
                pygame.draw.circle(screen, (255, 255, 255),
                                   (int(x), int(y)), radius, 2)

        # снаряды
        for pr in projectiles.values():
            x, y = pr.render_pos(now)
            ix, iy = int(x), int(y)
            # мягкое «свечение» — чуть больший полупрозрачный круг
            glow = pygame.Surface((PROJECTILE_RADIUS * 4,
                                   PROJECTILE_RADIUS * 4), pygame.SRCALPHA)
            pygame.draw.circle(glow, (*pr.color, 90),
                               (PROJECTILE_RADIUS * 2, PROJECTILE_RADIUS * 2),
                               PROJECTILE_RADIUS * 2)
            screen.blit(glow, (ix - PROJECTILE_RADIUS * 2,
                               iy - PROJECTILE_RADIUS * 2))
            pygame.draw.circle(screen, pr.color, (ix, iy), PROJECTILE_RADIUS)
            pygame.draw.circle(screen, (255, 255, 255), (ix, iy),
                               PROJECTILE_RADIUS, 1)

        # прицел поверх всего
        draw_crosshair(screen, pygame.mouse.get_pos())

        hint = font.render("WASD — движение, ЛКМ-курсор + Space — выстрел, Esc — выход",
                           True, (255, 255, 255))
        screen.blit(hint, (20, 20))

        status = f"id: {my_id}   players: {len(players)}   bullets: {len(projectiles)}"
        screen.blit(font.render(status, True, (220, 220, 220)), (20, 50))

        pygame.display.flip()
        clock.tick(60)

    try:
        sock.sendto(json.dumps({"type": "leave"}).encode("utf-8"), server_addr)
    except OSError:
        pass
    sock.close()
    pygame.quit()


if __name__ == "__main__":
    main()