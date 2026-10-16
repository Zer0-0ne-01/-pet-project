import unittest
from unittest.mock import patch

from server.server import GameServer, step_player
from shared.config import MATCH_WINS, NET_COLORS
from shared.level import MAPS, Platform
from shared.protocol import (
    MSG_JOIN, MSG_PROFILE, MSG_REJECT, MSG_SHOOT, MSG_START, MSG_UPGRADE,
    MSG_WELCOME,
)
from shared.upgrades import (
    RARITY_WEIGHTS, get_max_health, get_projectile_speed,
    get_reload_duration, get_shoot_cooldown, get_upgrade_choices,
)


class FakeSocket:
    def __init__(self):
        self.messages = []

    def sendto(self, payload, address):
        self.messages.append((payload, address))


class GameServerTests(unittest.TestCase):
    def setUp(self):
        self.game = GameServer()
        self.sock = FakeSocket()
        self.addresses = [("127.0.0.1", 10000 + i) for i in range(5)]

    def join(self, index, name="player", now=10.0, color=None):
        message = {"type": MSG_JOIN, "name": name}
        if color is not None:
            message["color"] = list(color)
        self.game.handle_message(
            self.sock, message, self.addresses[index], now,
        )

    def start_match(self, now=10.0, index=0):
        self.game.handle_message(
            self.sock, {"type": MSG_START}, self.addresses[index], now,
        )

    def test_join_retry_reuses_player_and_resends_welcome(self):
        self.join(0, "Alice")
        self.join(0, "Alice")

        self.assertEqual(len(self.game.players), 1)
        self.assertEqual(len(self.sock.messages), 2)
        self.assertTrue(all(MSG_WELCOME.encode() in packet for packet, _ in self.sock.messages))

    def test_server_rejects_more_than_four_players(self):
        for index in range(4):
            self.join(index)
        self.join(4)

        self.assertEqual(len(self.game.players), 4)
        self.assertIn(MSG_REJECT.encode(), self.sock.messages[-1][0])

    def test_lobby_enforces_unique_colors_and_host_starts(self):
        self.join(0, "Alice", color=NET_COLORS[0])
        self.join(1, "Bob", color=NET_COLORS[0])
        rejection = self.sock.messages[-1][0]
        self.assertIn(b"color_taken", rejection)
        self.assertEqual(len(self.game.players), 1)

        self.join(1, "Bob", color=NET_COLORS[1])
        self.assertEqual(len(self.game.players), 2)
        self.assertEqual(
            len({player["color"] for player in self.game.players.values()}), 2,
        )
        self.assertEqual(self.game.phase, "waiting")

        self.start_match(index=1)
        self.assertEqual(self.game.phase, "waiting")
        self.start_match(index=0)
        self.assertEqual(self.game.phase, "playing")

    def test_lobby_profile_change_rejects_duplicate_color(self):
        self.join(0, "Alice", color=NET_COLORS[0])
        self.join(1, "Bob", color=NET_COLORS[1])
        self.game.handle_message(
            self.sock,
            {"type": MSG_PROFILE, "name": "Bob", "color": list(NET_COLORS[0])},
            self.addresses[1],
            10.1,
        )
        self.assertEqual(self.game.players[2]["color"], NET_COLORS[1])
        self.assertIn(b"color_taken", self.sock.messages[-1][0])

        self.game.handle_message(
            self.sock,
            {"type": MSG_PROFILE, "name": "Bobby", "color": list(NET_COLORS[2])},
            self.addresses[1],
            10.2,
        )
        self.assertEqual(self.game.players[2]["name"], "Bobby")
        self.assertEqual(self.game.players[2]["color"], NET_COLORS[2])

        self.start_match()
        self.game.handle_message(
            self.sock,
            {"type": MSG_PROFILE, "name": "Nope", "color": list(NET_COLORS[3])},
            self.addresses[1],
            10.3,
        )
        self.assertNotEqual(self.game.players[2]["name"], "Nope")

    def test_player_appearance_choices_are_visual_profile_state(self):
        self.game.handle_message(
            self.sock,
            {
                "type": MSG_JOIN, "name": "Alice",
                "eyes_style": 1, "mouth_style": 1, "weapon_style": 1,
            },
            self.addresses[0],
            10.0,
        )
        player = self.game.players[1]
        self.assertEqual(
            (player["eyes_style"], player["mouth_style"], player["weapon_style"]),
            (1, 1, 1),
        )

        self.game.handle_message(
            self.sock,
            {
                "type": MSG_PROFILE, "name": "Alice",
                "color": list(player["color"]),
                "eyes_style": 0, "mouth_style": 1, "weapon_style": 0,
            },
            self.addresses[0],
            10.1,
        )
        state_player = self.game.state_message()["players"][0]
        self.assertEqual(
            (
                state_player["eyes_style"], state_player["mouth_style"],
                state_player["weapon_style"],
            ),
            (0, 1, 0),
        )

        self.game.handle_message(
            self.sock,
            {
                "type": MSG_PROFILE, "name": "Alice",
                "color": list(player["color"]), "weapon_style": 2,
            },
            self.addresses[0],
            10.2,
        )
        self.assertEqual(player["weapon_style"], 0)

    def test_join_after_host_starts_is_rejected(self):
        self.join(0, "Alice")
        self.join(1, "Bob")
        self.start_match()

        self.join(2, "Late player")

        self.assertEqual(len(self.game.players), 2)
        self.assertIn(b"game_started", self.sock.messages[-1][0])

    def test_projectile_damages_other_player(self):
        self.join(0, "Alice")
        self.join(1, "Bob")
        self.start_match()
        owner = self.game.players[1]
        target = self.game.players[2]
        owner.update(x=300.0, y=400.0, vy=0.0)
        target.update(x=400.0, y=400.0, vy=0.0)

        self.game.handle_message(
            self.sock,
            {"type": MSG_SHOOT, "dx": 1.0, "dy": 0.0},
            self.addresses[0],
            10.3,
        )
        for step in range(1, 6):
            self.game.tick(10.3 + step / 30, 1 / 30)

        self.assertEqual(target["hp"], 75)
        self.assertGreater(target["knockback_timer"], 0)

    def test_last_survivor_scores_and_next_round_resets_health(self):
        self.join(0, "Alice")
        self.join(1, "Bob")
        self.start_match()
        winner = self.game.players[1]
        self.game.players[2]["alive"] = False

        self.game.tick(10.1, 1 / 30)
        self.assertEqual(self.game.phase, "round_over")
        self.assertEqual(winner["score"], 1)
        self.assertEqual(self.game.winner_id, 1)
        self.assertFalse(winner["upgrade_choices"])
        self.assertFalse(self.game.players[2]["upgrade_choices"])

        self.game.tick(self.game.phase_until, 1 / 30)
        self.assertEqual(self.game.phase, "playing")
        self.game.players[2]["alive"] = False
        self.game.tick(self.game.phase_until + 0.1, 1 / 30)
        self.assertEqual(self.game.phase, "draft")
        loser = self.game.players[2]
        self.assertTrue(loser["upgrade_choices"])
        card_id = loser["upgrade_choices"][0]["id"]
        self.game.handle_message(
            self.sock, {"type": MSG_UPGRADE, "upgrade": card_id},
            self.addresses[1], 13.3,
        )
        self.assertEqual(loser["upgrades"][card_id], 1)
        self.assertEqual(self.game.phase, "round_over")

        previous_map = self.game.map_id
        self.game.tick(self.game.phase_until, 1 / 30)
        self.assertEqual(self.game.phase, "playing")
        self.assertEqual(self.game.round_number, 3)
        self.assertNotEqual(self.game.map_id, previous_map)
        self.assertIn(self.game.map_id, {game_map.map_id for game_map in MAPS})
        self.assertTrue(all(player["alive"] for player in self.game.players.values()))
        self.assertTrue(all(
            player["hp"] == get_max_health(player["upgrades"])
            for player in self.game.players.values()
        ))
        self.assertEqual(loser["upgrades"][card_id], 1)

    def test_draft_rejects_winner_and_unoffered_cards(self):
        self.join(0, "Alice")
        self.join(1, "Bob")
        self.start_match()
        self.game.players[2]["alive"] = False
        self.game.tick(10.1, 1 / 30)

        self.game.handle_message(
            self.sock, {"type": MSG_UPGRADE, "upgrade": "power_shot"},
            self.addresses[0], 10.2,
        )
        self.assertEqual(self.game.players[1]["upgrades"], {})

        self.game.handle_message(
            self.sock, {"type": MSG_UPGRADE, "upgrade": "not-a-card"},
            self.addresses[1], 10.3,
        )
        self.assertEqual(self.game.players[2]["upgrades"], {})

    def test_damage_upgrades_and_double_jump_have_server_effects(self):
        self.join(0, "Alice")
        self.join(1, "Bob")
        self.start_match()
        owner = self.game.players[1]
        target = self.game.players[2]
        owner.update(x=300.0, y=400.0, vy=0.0, upgrades={"power_shot": 1})
        target.update(x=400.0, y=400.0, vy=0.0, upgrades={"armor": 1})

        self.game.handle_message(
            self.sock, {"type": MSG_SHOOT, "dx": 1.0, "dy": 0.0},
            self.addresses[0], 10.3,
        )
        for step in range(1, 6):
            self.game.tick(10.3 + step / 30, 1 / 30)
        self.assertEqual(target["hp"], 72)

        target.update(
            x=400.0, y=400.0, vy=100.0, coyote_timer=0.0,
            jump_count=1, input_jump=True, jump_was_pressed=False,
            upgrades={"armor": 1, "double_jump": 1},
        )
        step_player(target, 1 / 30, self.game.platforms)
        self.assertEqual(target["jump_count"], 2)
        self.assertLess(target["vy"], 0)

    def test_stat_upgrades_change_health_projectile_speed_and_fire_rate(self):
        self.assertEqual(get_max_health({"large_health": 1}), 180)
        self.assertEqual(get_max_health({"tank": 1}), 200)
        self.assertEqual(get_projectile_speed({"fast_shot": 1}), 1750.0)
        self.assertAlmostEqual(get_shoot_cooldown({"fast_shot": 1}), 0.45)
        self.assertAlmostEqual(get_shoot_cooldown({"reload": 1}), 0.06)
        self.assertAlmostEqual(get_reload_duration({"reload": 1}), 0.45)

        self.join(0, "Alice")
        self.join(1, "Bob")
        self.start_match()
        player = self.game.players[1]
        player["upgrades"] = {"large_health": 1}
        self.game._start_round()
        self.assertEqual(player["hp"], 180)

    def test_faster_projectile_upgrade_obeys_server_shoot_cooldown(self):
        self.join(0, "Alice")
        self.join(1, "Bob")
        self.start_match()
        player = self.game.players[1]
        player["upgrades"] = {"fast_shot": 1}

        self.game.handle_message(
            self.sock, {"type": MSG_SHOOT, "dx": 1.0, "dy": 0.0},
            self.addresses[0], 10.3,
        )
        self.assertEqual(len(self.game.projectiles), 1)
        projectile = next(iter(self.game.projectiles.values()))
        self.assertEqual(projectile["vx"], 1750.0)

        self.game.handle_message(
            self.sock, {"type": MSG_SHOOT, "dx": 1.0, "dy": 0.0},
            self.addresses[0], 10.4,
        )
        self.assertEqual(len(self.game.projectiles), 1)

        self.game.handle_message(
            self.sock, {"type": MSG_SHOOT, "dx": 1.0, "dy": 0.0},
            self.addresses[0], 10.76,
        )
        self.assertEqual(len(self.game.projectiles), 2)

    def test_magazine_reloads_after_three_shots(self):
        self.join(0, "Alice")
        self.join(1, "Bob")
        self.start_match()
        player = self.game.players[1]
        self.game.platforms = (Platform(0, 600, 1024, 60),)
        player.update(x=100.0, y=100.0)
        self.game.players[2].update(x=800.0, y=100.0)

        for shot_number in range(3):
            self.game.handle_message(
                self.sock, {"type": MSG_SHOOT, "dx": 1.0, "dy": 0.0},
                self.addresses[0], 10.3 + shot_number * 0.21,
            )

        self.assertEqual(player["ammo"], 0)
        self.assertAlmostEqual(player["reload_timer"], 1.5)
        self.game.handle_message(
            self.sock, {"type": MSG_SHOOT, "dx": 1.0, "dy": 0.0},
            self.addresses[0], 10.93,
        )
        self.assertEqual(player["ammo"], 0)
        self.assertTrue(self.game.state_message()["players"][0]["reloading"])

        self.game.tick(11.0, 0.5)
        self.assertEqual(player["ammo"], 0)
        self.game.tick(11.5, 0.5)
        self.assertEqual(player["ammo"], 0)
        self.game.tick(12.0, 0.5)
        self.assertEqual(player["ammo"], 3)

    def test_poison_upgrade_applies_damage_over_time(self):
        self.join(0, "Alice")
        self.join(1, "Bob")
        self.start_match()
        self.game.platforms = ()
        self.game.players[1].update(
            x=100.0, y=100.0, upgrades={"poison": 1},
        )
        self.game.players[2].update(x=180.0, y=100.0)

        self.game.handle_message(
            self.sock, {"type": MSG_SHOOT, "dx": 1.0, "dy": 0.0},
            self.addresses[0], 10.3,
        )
        for step in range(1, 35):
            self.game.tick(10.3 + step / 30, 1 / 30)

        target = self.game.players[2]
        self.assertLess(target["hp"], 75)
        self.assertIn(1, target["poison_effects"])

    def test_explosive_bullets_damage_nearby_players_on_impact(self):
        for index in range(3):
            self.join(index, f"Player {index}")
        self.start_match()
        self.game.platforms = ()
        self.game.players[1].update(
            x=100.0, y=100.0, upgrades={"explosive_bullets": 1},
        )
        self.game.players[2].update(x=180.0, y=100.0)
        self.game.players[3].update(x=220.0, y=100.0)

        self.game.handle_message(
            self.sock, {"type": MSG_SHOOT, "dx": 1.0, "dy": 0.0},
            self.addresses[0], 10.3,
        )
        for step in range(1, 7):
            self.game.tick(10.3 + step / 30, 1 / 30)

        self.assertEqual(self.game.players[2]["hp"], 75)
        self.assertEqual(self.game.players[3]["hp"], 75)
        self.assertFalse(self.game.projectiles)

    def test_timed_detonation_explodes_after_half_a_second(self):
        self.join(0, "Alice")
        self.join(1, "Bob")
        self.start_match()
        self.game.platforms = (Platform(0, 120, 1024, 20),)
        self.game.players[1].update(
            x=100.0, y=100.0, upgrades={"timed_detonation": 1},
        )
        self.game.players[2].update(x=510.0, y=100.0)

        self.game.handle_message(
            self.sock, {"type": MSG_SHOOT, "dx": 1.0, "dy": 0.0},
            self.addresses[0], 10.3,
        )
        with patch("server.server.PROJECTILE_GRAVITY", 0):
            for step in range(1, 16):
                self.game.tick(10.3 + step / 30, 1 / 30)

        self.assertEqual(self.game.players[2]["hp"], 79)
        self.assertFalse(self.game.projectiles)

    def test_ricochet_upgrade_bounces_projectiles_off_platforms(self):
        self.join(0, "Alice")
        self.join(1, "Bob")
        self.start_match()
        self.game.platforms = (Platform(150, 70, 10, 100),)
        self.game.players[1].update(
            x=100.0, y=100.0, upgrades={"ricochet": 1},
        )
        self.game.players[2].update(x=800.0, y=100.0)

        self.game.handle_message(
            self.sock, {"type": MSG_SHOOT, "dx": 1.0, "dy": 0.0},
            self.addresses[0], 10.3,
        )
        for step in range(1, 6):
            self.game.tick(10.3 + step / 30, 1 / 30)

        projectile = next(iter(self.game.projectiles.values()))
        self.assertEqual(projectile["bounce_count"], 1)
        self.assertEqual(projectile["bounces_left"], 1)
        self.assertEqual(projectile["vx"], -560.0)

    def test_projectiles_follow_a_parabolic_trajectory(self):
        self.join(0, "Alice")
        self.join(1, "Bob")
        self.start_match()
        self.game.platforms = ()
        self.game.players[1].update(x=100.0, y=100.0)
        self.game.players[2].update(x=800.0, y=100.0)
        self.game.handle_message(
            self.sock, {"type": MSG_SHOOT, "dx": 1.0, "dy": 0.0},
            self.addresses[0], 10.3,
        )

        for step in range(1, 6):
            self.game.tick(10.3 + step / 30, 1 / 30)

        projectile = next(iter(self.game.projectiles.values()))
        self.assertGreater(projectile["y"], 100.0)
        self.assertGreater(projectile["vy"], 0.0)

    def test_upgrade_draft_has_three_choices_and_weights_rarity(self):
        first_draw = {}

        def choose_highest_weight(population, weights, k):
            if not first_draw:
                first_draw["population"] = list(population)
                first_draw["weights"] = list(weights)
            return [population[weights.index(max(weights))]]

        with patch(
                "shared.upgrades.random.choices",
                side_effect=choose_highest_weight) as weighted_choice:
            choices = get_upgrade_choices({})

        self.assertEqual(len(choices), 3)
        self.assertEqual(len({card["id"] for card in choices}), 3)
        self.assertTrue(all(card["rarity"] == "Обычная" for card in choices))
        self.assertLess(RARITY_WEIGHTS["Редкая"], RARITY_WEIGHTS["Обычная"])
        card_weights = {
            card["id"]: weight
            for card, weight in zip(
                first_draw["population"], first_draw["weights"],
            )
        }
        self.assertEqual(card_weights["power_shot"], RARITY_WEIGHTS["Обычная"])
        self.assertEqual(card_weights["double_jump"], RARITY_WEIGHTS["Редкая"])
        self.assertEqual(weighted_choice.call_count, 3)

    def test_unclaimed_upgrade_is_granted_when_draft_times_out(self):
        self.join(0, "Alice")
        self.join(1, "Bob")
        self.start_match()
        self.game.players[1]["score"] = 1
        self.game.players[1]["round_streak"] = 1
        self.game.players[2]["alive"] = False
        self.game.tick(10.1, 1 / 30)
        self.assertEqual(self.game.phase, "draft")

        for player in self.game.players.values():
            player["last_seen"] = self.game.phase_until
        self.game.tick(self.game.phase_until, 1 / 30)
        self.assertEqual(self.game.phase, "round_over")
        self.assertEqual(sum(self.game.players[2]["upgrades"].values()), 1)

    def test_all_losers_in_free_for_all_get_independent_drafts(self):
        for index in range(4):
            self.join(index, f"Player {index}")
        self.start_match()
        self.game.players[1]["score"] = 1
        self.game.players[1]["round_streak"] = 1
        self.game.players[2]["alive"] = False
        self.game.players[3]["alive"] = False
        self.game.players[4]["alive"] = False

        self.game.tick(10.1, 1 / 30)

        self.assertEqual(self.game.phase, "draft")
        self.assertFalse(self.game.players[1]["upgrade_choices"])
        for player_id in (2, 3, 4):
            choices = self.game.players[player_id]["upgrade_choices"]
            self.assertEqual(len(choices), 3)
            self.game.handle_message(
                self.sock,
                {"type": MSG_UPGRADE, "upgrade": choices[0]["id"]},
                self.addresses[player_id - 1],
                10.2,
            )
        self.assertEqual(self.game.phase, "round_over")
        for player_id in (2, 3, 4):
            self.assertEqual(sum(self.game.players[player_id]["upgrades"].values()), 1)

    def test_two_wins_draft_then_start_next_round_with_score_and_upgrades(self):
        self.join(0, "Alice")
        self.join(1, "Bob")
        self.start_match()
        winner = self.game.players[1]
        loser = self.game.players[2]
        winner["score"] = MATCH_WINS - 1
        winner["round_streak"] = MATCH_WINS - 1
        winner["upgrades"] = {"armor": 1}
        loser["alive"] = False

        self.game.tick(10.1, 1 / 30)
        self.assertEqual(self.game.phase, "draft")
        self.assertEqual(self.game.match_winner_id, 1)
        card_id = loser["upgrade_choices"][0]["id"]
        self.game.handle_message(
            self.sock, {"type": MSG_UPGRADE, "upgrade": card_id},
            self.addresses[1], 10.2,
        )
        self.assertEqual(self.game.phase, "round_over")
        self.assertEqual(winner["score"], 2)
        self.assertEqual(winner["round_streak"], 0)
        self.assertEqual(winner["score_squares"], 1)
        self.assertEqual(winner["upgrades"], {"armor": 1})
        self.assertEqual(sum(loser["upgrades"].values()), 1)

        self.game.tick(self.game.phase_until, 1 / 30)
        self.assertEqual(self.game.phase, "playing")
        self.assertEqual(winner["score"], 2)
        self.assertEqual(winner["round_streak"], 0)
        self.assertEqual(winner["score_squares"], 1)
        self.assertEqual(winner["upgrades"], {"armor": 1})
        self.assertEqual(sum(loser["upgrades"].values()), 1)

    def test_match_requires_two_round_wins_total_not_consecutive(self):
        self.join(0, "Alice")
        self.join(1, "Bob")
        self.start_match()

        for now, winner_id in ((10.1, 1), (13.2, 2), (16.3, 1)):
            for player_id, player in self.game.players.items():
                player["alive"] = player_id == winner_id
            self.game._check_round_end(now)
            if now < 16.3:
                self.assertEqual(self.game.phase, "round_over")
                self.assertTrue(all(
                    not player["upgrade_choices"]
                    for player in self.game.players.values()
                ))
            else:
                self.assertEqual(self.game.phase, "draft")
                self.assertEqual(self.game.players[1]["round_streak"], 0)
                self.assertEqual(self.game.players[1]["score_squares"], 1)
                self.assertEqual(self.game.players[2]["round_streak"], 1)
                for player_id in self.game.draft_player_ids:
                    self.game.players[player_id]["upgrade_selected"] = True
                self.game._finish_draft_if_ready(now)
                self.assertEqual(self.game.players[2]["round_streak"], 0)
            if now < 16.3:
                self.game.tick(self.game.phase_until, 1 / 30)

        self.assertEqual(self.game.players[1]["score"], 2)
        self.assertEqual(self.game.players[2]["score"], 1)
        self.assertEqual(self.game.players[1]["round_streak"], 0)
        self.assertEqual(self.game.players[1]["score_squares"], 1)
        self.assertEqual(self.game.players[2]["round_streak"], 0)
        self.assertEqual(self.game.players[2]["score_squares"], 0)
        self.assertEqual(self.game.match_winner_id, 1)
        self.assertEqual(self.game.phase, "round_over")

    def test_scoreboard_keeps_triangles_on_opponent_wins(self):
        self.join(0, "Alice")
        self.join(1, "Bob")
        self.start_match()

        for round_index, winner_id in enumerate((1, 2)):
            now = 10.1 + round_index * 3.1
            for player_id, player in self.game.players.items():
                player["alive"] = player_id == winner_id
            self.game._check_round_end(now)
            if round_index == 1:
                self.assertEqual(self.game.phase, "round_over")
                self.assertEqual(self.game.players[1]["round_streak"], 1)
                self.assertEqual(self.game.players[2]["round_streak"], 1)
            if round_index < 1:
                self.game.tick(self.game.phase_until, 1 / 30)

        self.assertEqual(self.game.players[1]["round_streak"], 1)
        self.assertEqual(self.game.players[1]["score_squares"], 0)
        self.assertEqual(self.game.players[2]["round_streak"], 1)
        self.assertEqual(self.game.players[2]["score_squares"], 0)


if __name__ == "__main__":
    unittest.main()
