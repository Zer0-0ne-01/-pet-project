# server/server.py
"""Авторитарный UDP-сервер Shuffling с side-view физикой."""

import json
import math
import socket
import time

from shared.config import (
    WIDTH, HEIGHT,
    BUFFER_SIZE,
    NET_HOST, NET_PORT, NET_TICK_DT,
    NET_PLAYER_SPEED, NET_COLORS,
    PLAYER_W, PLAYER_H,
    GRAVITY, JUMP_SPEED, MAX_FALL_SPEED,
    COYOTE_TIME, JUMP_BUFFER_TIME,
    PROJECTILE_SPEED, PROJECTILE_LIFETIME, SHOOT_COOLDOWN,
)
from shared.protocol import (
    MSG_JOIN, MSG_INPUT, MSG_SHOOT, MSG_LEAVE,
    MSG_WELCOME, MSG_STATE,
)
from shared.level import get_platforms


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def move_and_collide(x, y, vx, vy, dt, platforms):
    """Раздельное по осям движение AABB игрока с подшагами ≤15 px."""
    total_dx, total_dy = vx * dt, vy * dt
    longest = max(abs(total_dx), abs(total_dy))
    steps = max(1, int(longest / 15) + 1)
    step_dx, step_dy = total_dx / steps, total_dy / steps

    on_ground = False
    new_vx, new_vy = vx, vy
    half_w, half_h = PLAYER_W / 2, PLAYER_H / 2

    for _ in range(steps):
        if step_dx != 0:
            x += step_dx
            left, top = x - half_w, y - half_h
            right, bottom = left + PLAYER_W, top + PLAYER_H
            for p in platforms:
                if left < p.x + p.w and right > p.x and top < p.y + p.h and bottom > p.y:
                    x = p.x - half_w if step_dx > 0 else p.x + p.w + half_w
                    step_dx, new_vx = 0, 0
                    left, right = x - half_w, x + half_w

        if step_dy != 0:
            y += step_dy
            left, top = x - half_w, y - half_h
            right, bottom = left + PLAYER_W, top + PLAYER_H
            for p in platforms:
                if left < p.x + p.w and right > p.x and top < p.y + p.h and bottom > p.y:
                    if step_dy > 0:
                        y = p.y - half_h
                        on_ground = True
                    else:
                        y = p.y + p.h + half_h
                    step_dy, new_vy = 0, 0
                    top, bottom = y - half_h, y + half_h

    return x, y, new_vx, new_vy, on_ground


def step_player(p, dt, platforms):
    p["vx"] = p["input_dx"] * NET_PLAYER_SPEED

    if p["input_jump"]:
        p["jump_buffer"] = JUMP_BUFFER_TIME

    if p["jump_buffer"] > 0 and p["coyote_timer"] > 0:
        p["vy"] = -JUMP_SPEED
        p["jump_buffer"] = 0
        p["coyote_timer"] = 0
        p["on_ground"] = False

    p["vy"] = min(p["vy"] + GRAVITY * dt, MAX_FALL_SPEED)

    x, y, vx, vy, on_ground = move_and_collide(
        p["x"], p["y"], p["vx"], p["vy"], dt, platforms,
    )
    p["x"], p["y"], p["vx"], p["vy"] = x, y, vx, vy
    p["on_ground"] = on_ground

    if on_ground:
        p["coyote_timer"] = COYOTE_TIME
    else:
        p["coyote_timer"] = max(0.0, p["coyote_timer"] - dt)
    p["jump_buffer"] = max(0.0, p["jump_buffer"] - dt)


def spawn_player(pid, color):
    spawn_x = 300 if pid % 2 == 1 else WIDTH - 300
    return {
        "x": float(spawn_x),
        "y": 100.0,
        "vx": 0.0,
        "vy": 0.0,
        "on_ground": False,
        "facing": 1,
        "coyote_timer": 0.0,
        "jump_buffer": 0.0,
        "input_dx": 0,
        "input_jump": False,
        "color": color,
        "last_shot": 0.0,
    }


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((NET_HOST, NET_PORT))
    sock.setblocking(False)
    print(f"[SERVER] listening on {NET_HOST}:{NET_PORT}")

    platforms = get_platforms()

    players = {}            # id -> dict
    addr_to_id = {}         # addr -> id
    id_to_addr = {}         # id -> addr
    projectiles = {}        # pid -> dict
    next_id = 1
    next_projectile_id = 1
    next_color = 0

    last_tick = time.time()

    try:
        while True:
            now = time.time()

            # --- 1. ПРИЁМ ---
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

                if mtype == MSG_JOIN:
                    if addr not in addr_to_id:
                        pid = next_id
                        next_id += 1
                        color = NET_COLORS[next_color % len(NET_COLORS)]
                        next_color += 1
                        addr_to_id[addr] = pid
                        id_to_addr[pid] = addr
                        players[pid] = spawn_player(pid, color)
                        sock.sendto(
                            json.dumps({
                                "type": MSG_WELCOME,
                                "id": pid,
                                "color": list(color),
                            }).encode("utf-8"),
                            addr,
                        )
                        print(f"[SERVER] {addr} joined as id={pid}")

                elif mtype == MSG_INPUT:
                    pid = addr_to_id.get(addr)
                    if pid is not None:
                        p = players[pid]
                        p["input_dx"] = clamp(int(msg.get("dx", 0)), -1, 1)
                        p["input_jump"] = bool(msg.get("jump", False))
                        facing = int(msg.get("facing", p["facing"]))
                        p["facing"] = 1 if facing >= 0 else -1

                elif mtype == MSG_SHOOT:
                    pid = addr_to_id.get(addr)
                    if pid is None:
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

                elif mtype == MSG_LEAVE:
                    pid = addr_to_id.pop(addr, None)
                    if pid is not None:
                        id_to_addr.pop(pid, None)
                        players.pop(pid, None)
                        print(f"[SERVER] {addr} (id={pid}) left")

            # --- 2. ТИК ---
            if now - last_tick >= NET_TICK_DT:
                dt = now - last_tick
                last_tick = now

                for p in players.values():
                    step_player(p, dt, platforms)

                for pr_id in list(projectiles.keys()):
                    pr = projectiles[pr_id]
                    pr["x"] += pr["vx"] * dt
                    pr["y"] += pr["vy"] * dt
                    pr["ttl"] -= dt
                    if (pr["ttl"] <= 0
                            or pr["x"] < -50 or pr["x"] > WIDTH + 50
                            or pr["y"] < -50 or pr["y"] > HEIGHT + 50):
                        del projectiles[pr_id]

                # --- 3. РАССЫЛКА ---
                state = {
                    "type": MSG_STATE,
                    "players": [
                        {
                            "id": pid,
                            "x": p["x"], "y": p["y"],
                            "vx": p["vx"], "vy": p["vy"],
                            "on_ground": p["on_ground"],
                            "facing": p["facing"],
                            "color": list(p["color"]),
                        }
                        for pid, p in players.items()
                    ],
                    "projectiles": [
                        {
                            "id": pr_id,
                            "x": pr["x"], "y": pr["y"],
                            "vx": pr["vx"], "vy": pr["vy"],
                            "color": list(pr["color"]),
                        }
                        for pr_id, pr in projectiles.items()
                    ],
                }
                payload = json.dumps(state).encode("utf-8")

                for pid, _p in players.items():
                    addr = id_to_addr.get(pid)
                    if addr is None:
                        continue
                    try:
                        sock.sendto(payload, addr)
                    except OSError:
                        pass

            time.sleep(0.001)

    except KeyboardInterrupt:
        print("\n[SERVER] shutting down")
    finally:
        sock.close()


if __name__ == "__main__":
    main()