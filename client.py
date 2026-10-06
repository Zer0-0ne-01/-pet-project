# client.py
import argparse
import json
import socket
import time

import pygame

# --- СЕТЬ ---
BUFFER_SIZE = 2048
SERVER_TICK_DT = 1.0 / 30.0     # должно совпадать с серверным TICK_DT

# --- ВИЗУАЛ ---
WIDTH, HEIGHT = 1024, 768
PLAYER_RADIUS = 20


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
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("consolas", 20)

    # --- join: шлём несколько раз, чтобы уменьшить шанс потери первого пакета ---
    join_payload = json.dumps({"type": "join", "name": args.name}).encode("utf-8")
    for _ in range(3):
        sock.sendto(join_payload, server_addr)
        time.sleep(0.05)

    my_id = None
    players = {}         # id -> RemotePlayer
    last_input = (0, 0)

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

        # шлём каждый кадр — на 60 FPS это ~60 маленьких пакетов/сек,
        # это норм; если менять только при изменении, потеря пакета
        # оставит сервер с устаревшим вводом
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

                # убираем тех, кого больше нет в снимке
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
                # белая обводка вокруг своего кружка
                pygame.draw.circle(screen, (255, 255, 255),
                                   (int(x), int(y)), radius, 2)

        hint = font.render("WASD — движение, Esc — выход", True, (255, 255, 255))
        screen.blit(hint, (20, 20))

        status = f"id: {my_id}   players online: {len(players)}"
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