# server/server.py
"""UDP-сервер Shuffling.

Был "import json.txt" — переименован и переведён на пакетные импорты.
Логика не менялась: приём join/input/leave, тик 30 Гц, рассылка состояния.
"""

import json
import socket
import time

from shared.config import (
    WIDTH, HEIGHT,
    BUFFER_SIZE,
    NET_HOST, NET_PORT,
    NET_TICK_DT,
    NET_PLAYER_SPEED,
    NET_COLORS,
)
from shared.protocol import (
    MSG_JOIN, MSG_INPUT, MSG_LEAVE,
    MSG_WELCOME, MSG_STATE,
)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((NET_HOST, NET_PORT))
    sock.setblocking(False)
    print(f"[SERVER] listening on {NET_HOST}:{NET_PORT}")

    # id -> {"addr":..., "x":..., "y":..., "dx":..., "dy":..., "color":...}
    players = {}
    addr_to_id = {}          # addr -> id
    next_id = 1
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

                if mtype == MSG_JOIN:
                    if addr not in addr_to_id:
                        pid = next_id
                        next_id += 1
                        color = NET_COLORS[next_color % len(NET_COLORS)]
                        next_color += 1
                        addr_to_id[addr] = pid
                        players[pid] = {
                            "addr": addr,
                            "x": WIDTH / 2,
                            "y": HEIGHT / 2,
                            "dx": 0,
                            "dy": 0,
                            "color": color,
                        }
                        welcome = json.dumps({
                            "type": MSG_WELCOME,
                            "id": pid,
                            "color": list(color),
                        }).encode("utf-8")
                        sock.sendto(welcome, addr)
                        print(f"[SERVER] {addr} joined as id={pid}")

                elif mtype == MSG_INPUT:
                    pid = addr_to_id.get(addr)
                    if pid is not None:
                        p = players[pid]
                        p["dx"] = clamp(int(msg.get("dx", 0)), -1, 1)
                        p["dy"] = clamp(int(msg.get("dy", 0)), -1, 1)

                elif mtype == MSG_LEAVE:
                    pid = addr_to_id.pop(addr, None)
                    if pid is not None:
                        players.pop(pid, None)
                        print(f"[SERVER] {addr} (id={pid}) left")

            # --- 2. ТИК И РАССЫЛКА ---
            if now - last_tick >= NET_TICK_DT:
                dt = now - last_tick
                last_tick = now

                for p in players.values():
                    p["x"] = clamp(p["x"] + p["dx"] * NET_PLAYER_SPEED * dt, 0, WIDTH)
                    p["y"] = clamp(p["y"] + p["dy"] * NET_PLAYER_SPEED * dt, 0, HEIGHT)

                state = {
                    "type": MSG_STATE,
                    "players": [
                        {"id": pid, "x": p["x"], "y": p["y"],
                         "color": list(p["color"])}
                        for pid, p in players.items()
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