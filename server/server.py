"""Авторитарный UDP-сервер сетевого режима Shuffling."""

import json
import math
import socket
import time

from shared.config import (
    BUFFER_SIZE, COYOTE_TIME, GRAVITY, HEIGHT, JUMP_BUFFER_TIME,
    JUMP_SPEED, MATCH_END_DELAY, MATCH_WINS, MAX_FALL_SPEED, NET_COLORS,
    NET_HOST, NET_MAX_PLAYERS, NET_PLAYER_SPEED, NET_PLAYER_TIMEOUT,
    NET_PORT, NET_TICK_DT, PLAYER_H, PLAYER_MAX_HP, PLAYER_W,
    PROJECTILE_DAMAGE, PROJECTILE_KNOCKBACK, PROJECTILE_LIFETIME,
    PROJECTILE_SPEED, ROUND_END_DELAY, SHOOT_COOLDOWN, WIDTH,
)
from shared.level import get_platforms
from shared.protocol import (
    MSG_INPUT, MSG_JOIN, MSG_LEAVE, MSG_REJECT, MSG_SHOOT, MSG_STATE,
    MSG_WELCOME,
)


def clamp(value, low, high):
    return max(low, min(high, value))


def move_and_collide(x, y, vx, vy, dt, platforms):
    """Раздельное по осям движение AABB с короткими шагами."""
    dx, dy = vx * dt, vy * dt
    steps = max(1, math.ceil(max(abs(dx), abs(dy)) / 10))
    step_dx, step_dy = dx / steps, dy / steps
    on_ground = False
    half_w, half_h = PLAYER_W / 2, PLAYER_H / 2

    for _ in range(steps):
        if step_dx:
            x += step_dx
            left, right = x - half_w, x + half_w
            top, bottom = y - half_h, y + half_h
            for platform in platforms:
                if (left < platform.x + platform.w and right > platform.x
                        and top < platform.y + platform.h and bottom > platform.y):
                    x = platform.x - half_w if step_dx > 0 else platform.x + platform.w + half_w
                    step_dx = 0
                    vx = 0
                    break

        if step_dy:
            y += step_dy
            left, right = x - half_w, x + half_w
            top, bottom = y - half_h, y + half_h
            for platform in platforms:
                if (left < platform.x + platform.w and right > platform.x
                        and top < platform.y + platform.h and bottom > platform.y):
                    if step_dy > 0:
                        y = platform.y - half_h
                        on_ground = True
                    else:
                        y = platform.y + platform.h + half_h
                    step_dy = 0
                    vy = 0
                    break
    return x, y, vx, vy, on_ground


def step_player(player, dt, platforms):
    player["knockback_timer"] = max(0.0, player["knockback_timer"] - dt)
    knockback = player["knockback_x"] if player["knockback_timer"] > 0 else 0.0
    player["vx"] = player["input_dx"] * NET_PLAYER_SPEED + knockback
    if player["input_jump"] and not player["jump_was_pressed"]:
        player["jump_buffer"] = JUMP_BUFFER_TIME
    player["jump_was_pressed"] = player["input_jump"]
    if player["jump_buffer"] > 0 and player["coyote_timer"] > 0:
        player["vy"] = -JUMP_SPEED
        player["jump_buffer"] = 0
        player["coyote_timer"] = 0
    player["vy"] = min(player["vy"] + GRAVITY * dt, MAX_FALL_SPEED)
    x, y, vx, vy, grounded = move_and_collide(
        player["x"], player["y"], player["vx"], player["vy"], dt, platforms,
    )
    bounded_x = clamp(x, PLAYER_W / 2, WIDTH - PLAYER_W / 2)
    if bounded_x != x:
        vx = 0.0
    x = bounded_x
    player.update(x=x, y=y, vx=vx, vy=vy, on_ground=grounded)
    player["coyote_timer"] = COYOTE_TIME if grounded else max(
        0.0, player["coyote_timer"] - dt,
    )
    player["jump_buffer"] = max(0.0, player["jump_buffer"] - dt)


def _overlaps_platform(x, y, radius, platform):
    nearest_x = clamp(x, platform.x, platform.x + platform.w)
    nearest_y = clamp(y, platform.y, platform.y + platform.h)
    return (x - nearest_x) ** 2 + (y - nearest_y) ** 2 <= radius ** 2


class GameServer:
    """Хранит состояние игры и обрабатывает проверенные клиентские сообщения."""

    def __init__(self):
        self.platforms = get_platforms()
        self.players = {}
        self.addr_to_id = {}
        self.projectiles = {}
        self.next_id = 1
        self.next_projectile_id = 1
        self.round_number = 0
        self.phase = "waiting"
        self.winner_id = None
        self.phase_until = 0.0

    def _welcome(self, sock, address, player_id):
        player = self.players[player_id]
        self._send(sock, address, {
            "type": MSG_WELCOME, "id": player_id, "color": list(player["color"]),
        })

    @staticmethod
    def _send(sock, address, message):
        try:
            sock.sendto(json.dumps(message, allow_nan=False).encode("utf-8"), address)
        except OSError:
            pass

    def _new_player(self, player_id, address, name, now):
        color = NET_COLORS[(player_id - 1) % len(NET_COLORS)]
        spawn_x = 180 + (len(self.players) % NET_MAX_PLAYERS) * (
            (WIDTH - 360) / max(1, NET_MAX_PLAYERS - 1)
        )
        self.players[player_id] = {
            "x": float(spawn_x), "y": 100.0, "vx": 0.0, "vy": 0.0,
            "on_ground": False, "facing": 1, "coyote_timer": 0.0,
            "jump_buffer": 0.0, "input_dx": 0, "input_jump": False,
            "jump_was_pressed": False,
            "color": color, "last_shot": 0.0, "last_seen": now,
            "name": name, "hp": PLAYER_MAX_HP, "alive": False, "score": 0,
            "address": address, "knockback_x": 0.0, "knockback_timer": 0.0,
        }

    def handle_message(self, sock, message, address, now):
        if not isinstance(message, dict):
            return
        kind = message.get("type")
        player_id = self.addr_to_id.get(address)

        if kind == MSG_JOIN:
            if player_id is not None:
                self.players[player_id]["last_seen"] = now
                self._welcome(sock, address, player_id)
                return
            if len(self.players) >= NET_MAX_PLAYERS:
                self._send(sock, address, {"type": MSG_REJECT, "reason": "server_full"})
                return
            name = message.get("name", "player")
            if not isinstance(name, str):
                return
            name = "".join(c for c in name.strip() if c.isprintable())[:16] or "player"
            player_id = self.next_id
            self.next_id += 1
            self.addr_to_id[address] = player_id
            self._new_player(player_id, address, name, now)
            self._welcome(sock, address, player_id)
            print(f"[SERVER] {address} joined as {name!r} (id={player_id})")
            if self.phase == "waiting" and len(self.players) >= 2:
                self._start_round()
            return

        if player_id is None:
            return
        player = self.players[player_id]
        player["last_seen"] = now

        if kind == MSG_INPUT:
            dx = message.get("dx", 0)
            jump = message.get("jump", False)
            facing = message.get("facing", player["facing"])
            if (isinstance(dx, bool) or not isinstance(dx, int)
                    or dx not in (-1, 0, 1) or not isinstance(jump, bool)
                    or isinstance(facing, bool) or not isinstance(facing, int)
                    or facing not in (-1, 1)):
                return
            player["input_dx"] = dx if player["alive"] else 0
            player["input_jump"] = jump if player["alive"] else False
            player["facing"] = facing
        elif kind == MSG_SHOOT and player["alive"] and self.phase == "playing":
            dx, dy = message.get("dx"), message.get("dy")
            if (isinstance(dx, bool) or not isinstance(dx, (int, float))
                    or isinstance(dy, bool) or not isinstance(dy, (int, float))
                    or abs(dx) > 1e6 or abs(dy) > 1e6
                    or not math.isfinite(dx) or not math.isfinite(dy)):
                return
            length = math.hypot(dx, dy)
            if (not math.isfinite(length) or length < 1e-6
                    or now - player["last_shot"] < SHOOT_COOLDOWN):
                return
            dx, dy = dx / length, dy / length
            self.projectiles[self.next_projectile_id] = {
                "x": player["x"], "y": player["y"], "vx": dx * PROJECTILE_SPEED,
                "vy": dy * PROJECTILE_SPEED, "color": player["color"],
                "ttl": PROJECTILE_LIFETIME, "owner": player_id,
            }
            self.next_projectile_id += 1
            player["last_shot"] = now
        elif kind == MSG_LEAVE:
            self.remove_player(player_id)

    def remove_player(self, player_id):
        player = self.players.pop(player_id, None)
        if player is None:
            return
        self.addr_to_id.pop(player["address"], None)
        self.projectiles = {
            projectile_id: projectile for projectile_id, projectile in self.projectiles.items()
            if projectile["owner"] != player_id
        }
        if self.phase == "playing":
            self._check_round_end(time.monotonic())
        if len(self.players) < 2 and self.phase != "match_over":
            self.phase = "waiting"
            self.winner_id = None
            self.projectiles.clear()

    def _start_round(self):
        self.round_number += 1
        self.phase = "playing"
        self.winner_id = None
        self.projectiles.clear()
        for index, player in enumerate(self.players.values()):
            player.update(
                x=float(180 + index * (WIDTH - 360) / max(1, len(self.players) - 1)),
                y=100.0, vx=0.0, vy=0.0, hp=PLAYER_MAX_HP, alive=True,
                input_dx=0, input_jump=False, coyote_timer=0.0, jump_buffer=0.0,
                jump_was_pressed=False,
                knockback_x=0.0, knockback_timer=0.0,
            )

    def _finish_round(self, winner_id, now):
        self.phase = "match_over" if winner_id is not None and self.players[winner_id]["score"] >= MATCH_WINS else "round_over"
        self.winner_id = winner_id
        self.phase_until = now + (MATCH_END_DELAY if self.phase == "match_over" else ROUND_END_DELAY)
        self.projectiles.clear()

    def _check_round_end(self, now):
        alive = [pid for pid, player in self.players.items() if player["alive"]]
        if self.phase == "playing" and len(alive) <= 1:
            winner_id = alive[0] if alive else None
            if winner_id is not None:
                self.players[winner_id]["score"] += 1
            self._finish_round(winner_id, now)

    def tick(self, now, dt):
        for player_id, player in list(self.players.items()):
            if now - player["last_seen"] > NET_PLAYER_TIMEOUT:
                print(f"[SERVER] player {player_id} timed out")
                self.remove_player(player_id)

        if self.phase in ("round_over", "match_over") and now >= self.phase_until:
            if len(self.players) >= 2:
                if self.phase == "match_over":
                    for player in self.players.values():
                        player["score"] = 0
                self._start_round()
            else:
                self.phase = "waiting"
                self.winner_id = None

        if self.phase == "playing":
            for player in self.players.values():
                if player["alive"]:
                    step_player(player, dt, self.platforms)
                    if player["y"] > HEIGHT + PLAYER_H:
                        player["alive"] = False
                        player["hp"] = 0

            for projectile_id in list(self.projectiles):
                projectile = self.projectiles[projectile_id]
                dx, dy = projectile["vx"] * dt, projectile["vy"] * dt
                steps = max(1, math.ceil(max(abs(dx), abs(dy)) / 4))
                hit = False
                for _ in range(steps):
                    projectile["x"] += dx / steps
                    projectile["y"] += dy / steps
                    if any(_overlaps_platform(projectile["x"], projectile["y"], 6, platform)
                           for platform in self.platforms):
                        hit = True
                        break
                    for target_id, target in self.players.items():
                        if target_id == projectile["owner"] or not target["alive"]:
                            continue
                        if (abs(projectile["x"] - target["x"]) <= PLAYER_W / 2 + 6
                                and abs(projectile["y"] - target["y"]) <= PLAYER_H / 2 + 6):
                            target["hp"] = max(0, target["hp"] - PROJECTILE_DAMAGE)
                            direction = 1 if projectile["vx"] >= 0 else -1
                            target["knockback_x"] = direction * PROJECTILE_KNOCKBACK
                            target["knockback_timer"] = 0.18
                            target["vy"] = min(target["vy"], -PROJECTILE_KNOCKBACK * 0.35)
                            if target["hp"] == 0:
                                target["alive"] = False
                                target["input_dx"] = 0
                                target["input_jump"] = False
                            hit = True
                            break
                    if hit:
                        break
                projectile["ttl"] -= dt
                if (hit or projectile["ttl"] <= 0
                        or not -50 <= projectile["x"] <= WIDTH + 50
                        or not -50 <= projectile["y"] <= HEIGHT + 50):
                    del self.projectiles[projectile_id]
            self._check_round_end(now)

    def state_message(self):
        return {
            "type": MSG_STATE,
            "phase": self.phase,
            "round": self.round_number,
            "winner_id": self.winner_id,
            "players": [
                {
                    "id": pid, "name": p["name"], "x": p["x"], "y": p["y"],
                    "vx": p["vx"], "vy": p["vy"], "hp": p["hp"],
                    "alive": p["alive"], "score": p["score"],
                    "on_ground": p["on_ground"], "facing": p["facing"],
                    "color": list(p["color"]),
                }
                for pid, p in self.players.items()
            ],
            "projectiles": [
                {
                    "id": pid, "x": p["x"], "y": p["y"], "vx": p["vx"],
                    "vy": p["vy"], "color": list(p["color"]),
                }
                for pid, p in self.projectiles.items()
            ],
        }


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((NET_HOST, NET_PORT))
    sock.setblocking(False)
    print(f"[SERVER] listening on {NET_HOST}:{NET_PORT}")
    game = GameServer()
    last_tick = time.monotonic()

    try:
        while True:
            now = time.monotonic()
            while True:
                try:
                    data, address = sock.recvfrom(BUFFER_SIZE)
                except BlockingIOError:
                    break
                except OSError as error:
                    print(f"[SERVER] receive error: {error}")
                    break
                try:
                    message = json.loads(data.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                game.handle_message(sock, message, address, now)

            if now - last_tick >= NET_TICK_DT:
                dt = min(now - last_tick, NET_TICK_DT * 2)
                last_tick = now
                game.tick(now, dt)
                payload = json.dumps(game.state_message(), allow_nan=False).encode("utf-8")
                for player in list(game.players.values()):
                    try:
                        sock.sendto(payload, player["address"])
                    except OSError:
                        pass
            time.sleep(0.001)
    except KeyboardInterrupt:
        print("\n[SERVER] shutting down")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
