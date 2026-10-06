# client/client.py
"""Сетевой UDP-клиент Shuffling.

Логика не менялась. Из main() выделена run_client(host, port, name),
чтобы клиент можно было запускать как из CLI, так и из client/main.py.
"""

import argparse
import json
import socket
import time

import pygame

from shared.config import (
    WIDTH, HEIGHT, FPS, BUFFER_SIZE,
    NET_TICK_DT as SERVER_TICK_DT,
    NET_PLAYER_RADIUS as PLAYER_RADIUS,
)
from shared.protocol import (
    MSG_JOIN, MSG_INPUT, MSG_LEAVE,
    MSG_WELCOME, MSG_STATE,
)


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
        # Текущее «сглаженное» положение становится новым prev,
        # чтобы не было рывка при обновлении target.
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


def run_client(host="127.0.0.1", port=9999, name="player"):
    server_addr = (host, port)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)

    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption(f"Shuffling — {name}")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("consolas", 20)

    # --- join: шлём несколько раз, чтобы уменьшить шанс потери первого пакета ---
    join_payload = json.dumps({"type": MSG_JOIN, "name": name}).encode("utf-8")
    for _ in range(3):
        sock.sendto(join_payload, server_addr)
        time.sleep(0.05)

    my_id = None
    players = {}         # id -> RemotePlayer

    running = True
    while running:
        now = time.time()

        # --- 1. СОБЫТИЯ ---
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        # --- 2. ВВОД И ОТПРАВКА ---
        keys = pygame.key.get_pressed()
        dx = int(keys[pygame.K_d]) - int(keys[pygame.K_a])
        dy = int(keys[pygame.K_s]) - int(keys[pygame.K_w])

        try:
            sock.sendto(
                json.dumps({"type": MSG_INPUT, "dx": dx, "dy": dy}).encode("utf-8"),
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

            if mtype == MSG_WELCOME:
                my_id = msg["id"]
                print(f"[CLIENT] joined as id={my_id}")

            elif mtype == MSG_STATE:
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

        # --- 4. РИСОВАНИЕ ---
        screen.fill((30, 30, 60))

        for pid, rp in players.items():
            x, y = rp.render_pos(now)
            is_me = (pid == my_id)
            radius = PLAYER_RADIUS + (4 if is_me else 0)

            pygame.draw.circle(screen, rp.color, (int(x), int(y)), radius)

            if is_me:
                pygame.draw.circle(screen, (255, 255, 255),
                                   (int(x), int(y)), radius, 2)

        hint = font.render("WASD — движение, Esc — выход", True, (255, 255, 255))
        screen.blit(hint, (20, 20))

        status = f"id: {my_id}   players online: {len(players)}"
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