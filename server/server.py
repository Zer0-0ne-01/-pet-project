"""Авторитарный UDP-сервер сетевого режима Shuffling."""

import json
import math
import random
import socket
import time

from shared.config import (
    BUFFER_SIZE, COYOTE_TIME, GRAVITY, HEIGHT, JUMP_BUFFER_TIME,
    JUMP_SPEED, MATCH_WINS, MAX_FALL_SPEED, NET_COLORS,
    EXPLOSION_RADIUS, MAGAZINE_SIZE, NET_HOST, NET_MAX_PLAYERS,
    NET_PLAYER_SPEED, NET_PLAYER_TIMEOUT,
    NET_PORT, NET_TICK_DT, PLAYER_H, PLAYER_MAX_HP, PLAYER_W,
    PROJECTILE_GRAVITY,
    PROJECTILE_DAMAGE, PROJECTILE_KNOCKBACK, PROJECTILE_LIFETIME,
    ROUND_END_DELAY, UPGRADE_DRAFT_TIMEOUT, WIDTH,
)
from shared.level import MAPS, get_map
from shared.protocol import (
    MSG_INPUT, MSG_JOIN, MSG_LEAVE, MSG_REJECT, MSG_SHOOT, MSG_STATE,
    MSG_PROFILE, MSG_START, MSG_UPGRADE, MSG_WELCOME,
)
from shared.upgrades import (
    get_bounce_damage_multiplier, get_bounce_speed_multiplier,
    get_explosion_damage_multiplier, get_explosion_fuse,
    get_explosion_radius, get_max_health, get_poison_damage_per_second,
    get_poison_duration, get_projectile_bounces,
    get_projectile_damage_multiplier, get_projectile_speed,
    get_reload_duration, get_shoot_cooldown, get_upgrade_choices,
    has_upgrade_effect,
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
    can_ground_jump = player["coyote_timer"] > 0 and player["jump_count"] == 0
    can_double_jump = (
        player["upgrades"].get("double_jump", 0) > 0
        and player["jump_count"] < 2
    )
    if player["jump_buffer"] > 0 and (can_ground_jump or can_double_jump):
        player["vy"] = -JUMP_SPEED
        player["jump_buffer"] = 0
        player["coyote_timer"] = 0
        player["jump_count"] += 1
    player["vy"] = min(player["vy"] + GRAVITY * dt, MAX_FALL_SPEED)
    x, y, vx, vy, grounded = move_and_collide(
        player["x"], player["y"], player["vx"], player["vy"], dt, platforms,
    )
    bounded_x = clamp(x, PLAYER_W / 2, WIDTH - PLAYER_W / 2)
    if bounded_x != x:
        vx = 0.0
    x = bounded_x
    player.update(x=x, y=y, vx=vx, vy=vy, on_ground=grounded)
    if grounded:
        player["jump_count"] = 0
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
        self.map_id = MAPS[0].map_id
        self.platforms = get_map(self.map_id).platforms
        self.previous_map_id = None
        self.players = {}
        self.addr_to_id = {}
        self.projectiles = {}
        self.next_id = 1
        self.next_projectile_id = 1
        self.round_number = 0
        self.phase = "waiting"
        self.winner_id = None
        self.match_winner_id = None
        self.draft_player_ids = set()
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
        color = self._available_color()
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
            "round_streak": 0, "score_squares": 0,
            "eyes_style": 0, "mouth_style": 0, "weapon_style": 0,
            "address": address, "knockback_x": 0.0, "knockback_timer": 0.0,
            "jump_count": 0, "upgrades": {},
            "ammo": MAGAZINE_SIZE, "reload_timer": 0.0,
            "reload_duration": 0.0,
            "poison_effects": {},
            "upgrade_choices": [], "upgrade_selected": True,
        }

    def _available_color(self, requested=None):
        used = {player["color"] for player in self.players.values()}
        if requested is not None and requested not in used:
            return requested
        return next((color for color in NET_COLORS if color not in used), None)

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
            if self.phase != "waiting":
                self._send(sock, address, {"type": MSG_REJECT, "reason": "game_started"})
                return
            if len(self.players) >= NET_MAX_PLAYERS:
                self._send(sock, address, {"type": MSG_REJECT, "reason": "server_full"})
                return
            name = message.get("name", "player")
            if not isinstance(name, str):
                return
            name = "".join(c for c in name.strip() if c.isprintable())[:16] or "player"
            requested_color = message.get("color")
            if requested_color is not None:
                if (not isinstance(requested_color, list) or len(requested_color) != 3
                        or any(isinstance(channel, bool) or not isinstance(channel, int)
                               or not 0 <= channel <= 255 for channel in requested_color)):
                    self._send(sock, address, {"type": MSG_REJECT, "reason": "invalid_color"})
                    return
                requested_color = tuple(requested_color)
                if requested_color not in NET_COLORS:
                    self._send(sock, address, {"type": MSG_REJECT, "reason": "invalid_color"})
                    return
                if requested_color in {p["color"] for p in self.players.values()}:
                    self._send(sock, address, {
                        "type": MSG_REJECT, "reason": "color_taken",
                        "available_colors": [
                            list(color) for color in NET_COLORS
                            if color not in {p["color"] for p in self.players.values()}
                        ],
                    })
                    return
            appearance = {}
            for key in ("eyes_style", "mouth_style", "weapon_style"):
                style = message.get(key, 0)
                if (isinstance(style, bool) or not isinstance(style, int)
                        or style not in (0, 1)):
                    self._send(sock, address, {
                        "type": MSG_REJECT, "reason": "invalid_appearance",
                    })
                    return
                appearance[key] = style
            player_id = self.next_id
            self.next_id += 1
            self.addr_to_id[address] = player_id
            self._new_player(player_id, address, name, now)
            if requested_color is not None:
                self.players[player_id]["color"] = requested_color
            self.players[player_id].update(appearance)
            self._welcome(sock, address, player_id)
            print(f"[SERVER] {address} joined as {name!r} (id={player_id})")
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
                    or player["ammo"] <= 0
                    or now - player["last_shot"] < get_shoot_cooldown(
                        player["upgrades"],
                    )):
                return
            dx, dy = dx / length, dy / length
            projectile_speed = get_projectile_speed(player["upgrades"])
            fuse = get_explosion_fuse(player["upgrades"])
            poison_dps = get_poison_damage_per_second(player["upgrades"])
            explosion_radius = get_explosion_radius(player["upgrades"])
            bounces = get_projectile_bounces(player["upgrades"])
            projectile_color = player["color"]
            effect = "normal"
            if explosion_radius > 0:
                projectile_color, effect = (255, 130, 65), "explosion"
            elif poison_dps > 0:
                projectile_color, effect = (120, 235, 120), "poison"
            elif bounces > 0:
                projectile_color, effect = (190, 145, 255), "ricochet"
            self.projectiles[self.next_projectile_id] = {
                "x": player["x"], "y": player["y"], "vx": dx * projectile_speed,
                "vy": dy * projectile_speed, "color": projectile_color,
                "effect": effect,
                "ttl": PROJECTILE_LIFETIME, "owner": player_id,
                "damage_level": player["upgrades"].get("power_shot", 0),
                "damage_multiplier": get_projectile_damage_multiplier(
                    player["upgrades"],
                ),
                "bounces_left": bounces,
                "bounce_damage_multiplier": get_bounce_damage_multiplier(
                    player["upgrades"],
                ),
                "bounce_speed_multiplier": get_bounce_speed_multiplier(
                    player["upgrades"],
                ),
                "bounce_count": 0,
                "poison_dps": poison_dps,
                "poison_duration": get_poison_duration(player["upgrades"]),
                "explosion_radius": explosion_radius,
                "explosion_damage_multiplier": get_explosion_damage_multiplier(
                    player["upgrades"],
                ),
                "explosion_fuse": fuse,
                "explode_on_impact": has_upgrade_effect(
                    player["upgrades"], "explode_on_impact",
                ),
            }
            self.next_projectile_id += 1
            player["last_shot"] = now
            player["ammo"] -= 1
            if player["ammo"] == 0:
                player["reload_timer"] = get_reload_duration(player["upgrades"])
                player["reload_duration"] = player["reload_timer"]
        elif kind == MSG_LEAVE:
            self.remove_player(player_id)
        elif kind == MSG_PROFILE and self.phase == "waiting":
            name = message.get("name", player["name"])
            requested_color = message.get("color")
            appearance = {
                key: message.get(key, player[key])
                for key in ("eyes_style", "mouth_style", "weapon_style")
            }
            if not isinstance(name, str):
                return
            if any(
                isinstance(style, bool) or not isinstance(style, int)
                or style not in (0, 1)
                for style in appearance.values()
            ):
                return
            if (not isinstance(requested_color, list) or len(requested_color) != 3
                    or any(isinstance(channel, bool) or not isinstance(channel, int)
                           or not 0 <= channel <= 255 for channel in requested_color)):
                return
            requested_color = tuple(requested_color)
            if requested_color not in NET_COLORS:
                return
            if requested_color in {
                    other["color"] for other_id, other in self.players.items()
                    if other_id != player_id}:
                self._send(sock, address, {"type": MSG_REJECT, "reason": "color_taken"})
                return
            player["name"] = "".join(c for c in name.strip() if c.isprintable())[:16] or "player"
            player["color"] = requested_color
            player.update(appearance)
        elif kind == MSG_START:
            if (self.phase == "waiting" and len(self.players) >= 2
                    and player_id == min(self.players)):
                self._start_round()
        elif kind == MSG_UPGRADE:
            upgrade_id = message.get("upgrade")
            if (self.phase != "draft" or player_id not in self.draft_player_ids
                    or player["upgrade_selected"]
                    or not isinstance(upgrade_id, str)
                    or upgrade_id not in {
                        card["id"] for card in player["upgrade_choices"]
                    }):
                return
            player["upgrades"][upgrade_id] = player["upgrades"].get(upgrade_id, 0) + 1
            player["upgrade_selected"] = True
            self._finish_draft_if_ready(now)

    def _projectile_damage(self, projectile):
        bounce_bonus = projectile["bounce_damage_multiplier"] ** (
            projectile["bounce_count"]
        )
        return max(1, round(
            (PROJECTILE_DAMAGE + 8 * projectile["damage_level"])
            * projectile["damage_multiplier"]
            * bounce_bonus
        ))

    def _damage_player(self, target, damage, knockback_x=None, knockback_y=None):
        if not target["alive"]:
            return
        armor_level = target["upgrades"].get("armor", 0)
        damage = max(1, round(damage * (1 - 0.15 * armor_level)))
        target["hp"] = max(0, target["hp"] - damage)
        if knockback_x is not None:
            target["knockback_x"] = knockback_x
            target["knockback_timer"] = 0.18
            target["vy"] = min(target["vy"], knockback_y)
        if target["hp"] == 0:
            target["alive"] = False
            target["input_dx"] = 0
            target["input_jump"] = False
            target["poison_effects"].clear()

    def _apply_poison(self, projectile, target):
        duration = projectile["poison_duration"]
        damage_per_second = projectile["poison_dps"]
        if not target["alive"] or duration <= 0 or damage_per_second <= 0:
            return
        effect = target["poison_effects"].get(projectile["owner"])
        if effect is None:
            target["poison_effects"][projectile["owner"]] = {
                "remaining": duration,
                "damage_per_second": damage_per_second,
                "damage_accumulator": 0.0,
            }
        else:
            effect["remaining"] = max(effect["remaining"], duration)
            effect["damage_per_second"] = max(
                effect["damage_per_second"], damage_per_second,
            )

    def _damage_projectile_target(self, projectile, target):
        damage = self._projectile_damage(projectile)
        direction = 1 if projectile["vx"] >= 0 else -1
        self._damage_player(
            target,
            damage,
            direction * PROJECTILE_KNOCKBACK,
            -PROJECTILE_KNOCKBACK * 0.35,
        )
        self._apply_poison(projectile, target)

    def _explode_projectile(self, projectile):
        radius = projectile["explosion_radius"] or EXPLOSION_RADIUS
        damage = max(1, round(
            self._projectile_damage(projectile)
            * projectile["explosion_damage_multiplier"]
        ))
        for target_id, target in self.players.items():
            if target_id == projectile["owner"] or not target["alive"]:
                continue
            dx = target["x"] - projectile["x"]
            dy = target["y"] - projectile["y"]
            distance = math.hypot(dx, dy)
            if distance > radius:
                continue
            direction = dx / distance if distance > 1e-6 else (
                1 if projectile["vx"] >= 0 else -1
            )
            self._damage_player(
                target,
                damage,
                direction * PROJECTILE_KNOCKBACK,
                -PROJECTILE_KNOCKBACK * 0.35,
            )
            self._apply_poison(projectile, target)

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
        elif self.phase == "draft":
            self.draft_player_ids.discard(player_id)
            self._finish_draft_if_ready(time.monotonic())
        if len(self.players) < 2 and self.phase != "match_over":
            self.phase = "waiting"
            self.winner_id = None
            self.projectiles.clear()

    def _start_round(self):
        self.round_number += 1
        self.phase = "playing"
        self.winner_id = None
        self.match_winner_id = None
        self.projectiles.clear()
        available_maps = [
            game_map for game_map in MAPS
            if game_map.map_id != self.previous_map_id
        ]
        selected_map = random.choice(available_maps)
        self.map_id = selected_map.map_id
        self.previous_map_id = self.map_id
        self.platforms = selected_map.platforms
        for index, player in enumerate(self.players.values()):
            player.update(
                x=float(180 + index * (WIDTH - 360) / max(1, len(self.players) - 1)),
                y=100.0, vx=0.0, vy=0.0,
                hp=get_max_health(player["upgrades"]), alive=True,
                ammo=MAGAZINE_SIZE, reload_timer=0.0, poison_effects={},
                reload_duration=0.0,
                input_dx=0, input_jump=False, coyote_timer=0.0, jump_buffer=0.0,
                jump_was_pressed=False,
                jump_count=0,
                knockback_x=0.0, knockback_timer=0.0,
                upgrade_choices=[], upgrade_selected=True,
            )

    def _finish_round(self, winner_id, now, offer_upgrades=False):
        self.winner_id = winner_id
        self.match_winner_id = (
            winner_id
            if winner_id is not None and self.players[winner_id]["score"] == MATCH_WINS
            else None
        )
        self.projectiles.clear()
        if not offer_upgrades:
            self.draft_player_ids.clear()
            for player in self.players.values():
                player["upgrade_choices"] = []
                player["upgrade_selected"] = True
            if len(self.players) >= 2:
                self.phase_until = now + ROUND_END_DELAY
                self.phase = "round_over"
            else:
                self.phase = "waiting"
                self.phase_until = 0.0
            return

        self.phase = "draft"
        self.phase_until = now + UPGRADE_DRAFT_TIMEOUT
        self.draft_player_ids = set(self.players) - ({winner_id} if winner_id else set())
        for player_id, player in self.players.items():
            player["upgrade_choices"] = (
                get_upgrade_choices(player["upgrades"])
                if player_id in self.draft_player_ids else []
            )
            player["upgrade_selected"] = (
                player_id not in self.draft_player_ids
                or not player["upgrade_choices"]
            )
        self._finish_draft_if_ready(now)

    def _finish_draft_if_ready(self, now):
        if self.phase != "draft" or any(
                not self.players[player_id]["upgrade_selected"]
                for player_id in self.draft_player_ids if player_id in self.players):
            return
        for player_id, player in self.players.items():
            if player_id != self.winner_id:
                player["round_streak"] = 0
        self.draft_player_ids.clear()
        if len(self.players) >= 2:
            self.phase_until = now + ROUND_END_DELAY
            self.phase = "round_over"
        else:
            self.phase = "waiting"
            self.phase_until = 0.0

    def _check_round_end(self, now):
        alive = [pid for pid, player in self.players.items() if player["alive"]]
        if self.phase == "playing" and len(alive) <= 1:
            winner_id = alive[0] if alive else None
            square_completed = False
            if winner_id is not None:
                self.players[winner_id]["score"] += 1
                self.players[winner_id]["round_streak"] += 1
                if self.players[winner_id]["round_streak"] >= 2:
                    self.players[winner_id]["score_squares"] += 1
                    self.players[winner_id]["round_streak"] = 0
                    square_completed = True
            self._finish_round(winner_id, now, offer_upgrades=square_completed)

    def tick(self, now, dt):
        for player_id, player in list(self.players.items()):
            if now - player["last_seen"] > NET_PLAYER_TIMEOUT:
                print(f"[SERVER] player {player_id} timed out")
                self.remove_player(player_id)

        if self.phase == "draft" and now >= self.phase_until:
            for player_id in list(self.draft_player_ids):
                player = self.players.get(player_id)
                if player is None or player["upgrade_selected"]:
                    continue
                if player["upgrade_choices"]:
                    card = random.choice(player["upgrade_choices"])
                    upgrade_id = card["id"]
                    player["upgrades"][upgrade_id] = (
                        player["upgrades"].get(upgrade_id, 0) + 1
                    )
                player["upgrade_selected"] = True
            self._finish_draft_if_ready(now)

        if self.phase == "round_over" and now >= self.phase_until:
            if len(self.players) >= 2:
                self._start_round()
            else:
                self.phase = "waiting"
                self.winner_id = None

        if self.phase == "playing":
            for player in self.players.values():
                if player["reload_timer"] > 0:
                    timer_remaining = player["reload_timer"] - dt
                    player["reload_timer"] = (
                        0.0 if timer_remaining <= 1e-9 else timer_remaining
                    )
                    if player["reload_timer"] == 0:
                        player["ammo"] = MAGAZINE_SIZE
                if player["alive"]:
                    step_player(player, dt, self.platforms)
                    if player["y"] > HEIGHT + PLAYER_H:
                        player["alive"] = False
                        player["hp"] = 0
                        player["poison_effects"].clear()
                        continue

                    for owner_id, effect in list(player["poison_effects"].items()):
                        elapsed = min(dt, effect["remaining"])
                        effect["remaining"] -= elapsed
                        effect["damage_accumulator"] += (
                            effect["damage_per_second"] * elapsed
                        )
                        damage = int(effect["damage_accumulator"])
                        if effect["remaining"] <= 0:
                            damage += round(effect["damage_accumulator"] - damage)
                            del player["poison_effects"][owner_id]
                        else:
                            effect["damage_accumulator"] -= damage
                        if damage:
                            self._damage_player(player, damage)

            for projectile_id in list(self.projectiles):
                projectile = self.projectiles[projectile_id]
                steps = max(
                    1,
                    math.ceil(max(
                        abs(projectile["vx"] * dt),
                        abs(projectile["vy"] * dt),
                    ) / 4),
                )
                hit = False
                substep_dt = dt / steps
                for _ in range(steps):
                    old_x, old_y = projectile["x"], projectile["y"]
                    old_vy = projectile["vy"]
                    projectile["x"] += projectile["vx"] * substep_dt
                    projectile["vy"] += PROJECTILE_GRAVITY * substep_dt
                    projectile["y"] += (
                        old_vy * substep_dt
                        + 0.5 * PROJECTILE_GRAVITY * substep_dt ** 2
                    )
                    collided_platform = next((
                        platform for platform in self.platforms
                        if _overlaps_platform(
                            projectile["x"], projectile["y"], 6, platform,
                        )
                    ), None)
                    if collided_platform is not None:
                        horizontal_collision = _overlaps_platform(
                            projectile["x"], old_y, 6, collided_platform,
                        )
                        vertical_collision = _overlaps_platform(
                            old_x, projectile["y"], 6, collided_platform,
                        )
                        if horizontal_collision:
                            projectile["x"] = old_x
                            velocity_key = "vx"
                        elif vertical_collision:
                            projectile["y"] = old_y
                            velocity_key = "vy"
                        else:
                            projectile["x"], projectile["y"] = old_x, old_y
                            projectile["vy"] = old_vy
                            hit = True
                            break
                        should_explode = (
                            projectile["explode_on_impact"]
                            or (projectile["explosion_radius"] > 0
                                and projectile["bounces_left"] <= 0)
                        )
                        if should_explode:
                            self._explode_projectile(projectile)
                            hit = True
                            break
                        if projectile["bounces_left"] > 0:
                            projectile[velocity_key] *= (
                                -projectile["bounce_speed_multiplier"]
                            )
                            projectile["bounces_left"] -= 1
                            projectile["bounce_count"] += 1
                        else:
                            hit = True
                            break

                    if not -50 <= projectile["x"] <= WIDTH + 50:
                        hit = True
                        break

                    for target_id, target in self.players.items():
                        if target_id == projectile["owner"] or not target["alive"]:
                            continue
                        if (abs(projectile["x"] - target["x"]) <= PLAYER_W / 2 + 6
                                and abs(projectile["y"] - target["y"]) <= PLAYER_H / 2 + 6):
                            if projectile["explosion_radius"] > 0:
                                self._explode_projectile(projectile)
                            else:
                                self._damage_projectile_target(projectile, target)
                            hit = True
                            break
                    if hit:
                        break

                if projectile["explosion_fuse"] is not None:
                    fuse_remaining = projectile["explosion_fuse"] - dt
                    projectile["explosion_fuse"] = (
                        0.0 if fuse_remaining <= 1e-9 else fuse_remaining
                    )
                    if projectile["explosion_fuse"] == 0 and not hit:
                        self._explode_projectile(projectile)
                        hit = True
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
            "match_winner_id": self.match_winner_id,
            "host_id": min(self.players) if self.players else None,
            "map_id": self.map_id,
            "players": [
                {
                    "id": pid, "name": p["name"], "x": p["x"], "y": p["y"],
                    "vx": p["vx"], "vy": p["vy"], "hp": p["hp"],
                    "alive": p["alive"], "score": p["score"],
                    "round_streak": p["round_streak"],
                    "score_squares": p["score_squares"],
                    "on_ground": p["on_ground"], "facing": p["facing"],
                    "color": list(p["color"]),
                    "eyes_style": p["eyes_style"],
                    "mouth_style": p["mouth_style"],
                    "weapon_style": p["weapon_style"],
                    "ammo": p["ammo"], "reloading": p["reload_timer"] > 0,
                    "reload_time": p["reload_timer"],
                    "reload_duration": p["reload_duration"],
                    "upgrades": dict(p["upgrades"]),
                    "upgrade_choices": p["upgrade_choices"],
                    "upgrade_selected": p["upgrade_selected"],
                }
                for pid, p in self.players.items()
            ],
            "projectiles": [
                {
                    "id": pid, "x": p["x"], "y": p["y"], "vx": p["vx"],
                    "vy": p["vy"], "color": list(p["color"]),
                    "effect": p["effect"], "gravity": PROJECTILE_GRAVITY,
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
