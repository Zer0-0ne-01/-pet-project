# server.py
import json
import math
import socket
import time

# --- НАСТРОЙКИ ---
HOST, PORT = "0.0.0.0", 9999
WIDTH, HEIGHT = 1024, 768
PLAYER_SPEED = 300.0
TICK_DT = 1.0 / 30.0
BUFFER_SIZE = 2048

PROJECTILE_SPEED = 700.0        # пикселей в секунду
PROJECTILE_LIFETIME = 1.5       # секунд до самоуничтожения
SHOOT_COOLDOWN = 0.20           # сек между выстрелами одного игрока

COLORS = [
    (80, 200, 120),
    (220, 80, 80),
    (80, 140, 220),
    (220, 200, 80),
    (200, 80, 220),
    (80, 220, 220),
]


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((HOST, PORT))
    sock.setblocking(False)
    print(f"[SERVER] listening on {HOST}:{PORT}")

    players = {}            # id -> {addr, x, y, dx, dy, color, last_shot}
    addr_to_id = {}         # addr -> id
    projectiles = {}        # pid -> {x, y, vx, vy, color, ttl, owner}
    next_id = 1
    next_projectile_id = 1
    next_color = 0

    last_tick = time.time()

    try:
        while True:
            now = time.time()

            # --- 1. ПРИЁМ СООБЩЕНИЙ ---
            while True:
                try:
                    data, addr = sock.recvfrom(BUFFER_SIZE)
                except BlockingIOError:
                    break

                try:
                    msg = json.loads(data.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue

                mtype = msg.get("type")

                if mtype == "join":
                    if addr not in addr_to_id:
                        pid = next_id
                        next_id += 1
                        color = COLORS[next_color % len(COLORS)]
                        next_color += 1
                        addr_to_id[addr] = pid
                        players[pid] = {
                            "addr": addr,
                            "x": WIDTH / 2,
                            "y": HEIGHT / 2,
                            "dx": 0,
                            "dy": 0,
                            "color": color,
                            "last_shot": 0.0,
                        }
                        welcome = json.dumps({
                            "type": "welcome",
                            "id": pid,
                            "color": list(color),
                        }).encode("utf-8")
                        sock.sendto(welcome, addr)
                        print(f"[SERVER] {addr} joined as id={pid}")

                elif mtype == "input":
                    pid = addr_to_id.get(addr)
                    if pid is not None:
                        p = players[pid]
                        p["dx"] = clamp(int(msg.get("dx", 0)), -1, 1)
                        p["dy"] = clamp(int(msg.get("dy", 0)), -1, 1)

                elif mtype == "shoot":
                    pid = addr_to_id.get(addr)
                    if pid is None or pid not in players:
                        continue

                    p = players[pid]
                    if now - p["last_shot"] < SHOOT_COOLDOWN:
                        continue

                    dx = float(msg.get("dx", 0.0))
                    dy = float(msg.get("dy", 0.0))
                    length = math.hypot(dx, dy)
                    if length < 1e-6:
                        continue
                    dx /= length
                    dy /= length

                    projectiles[next_projectile_id] = {
                        "x": p["x"],
                        "y": p["y"],
                        "vx": dx * PROJECTILE_SPEED,
                        "vy": dy * PROJECTILE_SPEED,
                        "color": p["color"],
                        "ttl": PROJECTILE_LIFETIME,
                        "owner": pid,
                    }
                    p["last_shot"] = now
                    next_projectile_id += 1

                elif mtype == "leave":
                    pid = addr_to_id.pop(addr, None)
                    if pid is not None:
                        players.pop(pid, None)
                        print(f"[SERVER] {addr} (id={pid}) left")

            # --- 2. ТИК ---
            if now - last_tick >= TICK_DT:
                dt = now - last_tick
                last_tick = now

                # игроки
                for p in players.values():
                    p["x"] = clamp(p["x"] + p["dx"] * PLAYER_SPEED * dt, 0, WIDTH)
                    p["y"] = clamp(p["y"] + p["dy"] * PLAYER_SPEED * dt, 0, HEIGHT)

                # снаряды
                for pr_id in list(projectiles.keys()):
                    pr = projectiles[pr_id]
                    pr["x"] += pr["vx"] * dt
                    pr["y"] += pr["vy"] * dt
                    pr["ttl"] -= dt

                    if (pr["ttl"] <= 0
                            or pr["x"] < 0 or pr["x"] > WIDTH
                            or pr["y"] < 0 or pr["y"] > HEIGHT):
                        del projectiles[pr_id]

                # --- 3. РАССЫЛКА ---
                state = {
                    "type": "state",
                    "players": [
                        {"id": pid, "x": p["x"], "y": p["y"],
                         "color": list(p["color"])}
                        for pid, p in players.items()
                    ],
                    "projectiles": [
                        {"id": pr_id,
                         "x": pr["x"], "y": pr["y"],
                         "vx": pr["vx"], "vy": pr["vy"],
                         "color": list(pr["color"])}
                        for pr_id, pr in projectiles.items()
                    ],
                }
                payload = json.dumps(state).encode("utf-8")

                for p in players.values():
                    try:
                        sock.sendto(payload, p["addr"])
                    except OSError:
                        pass

            time.sleep(0.001)

    except KeyboardInterrupt:
        print("\n[SERVER] shutting down")
    finally:
        sock.close()


if __name__ == "__main__":
    main()