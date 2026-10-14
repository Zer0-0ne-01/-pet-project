import unittest

from server.server import GameServer, step_player
from shared.config import MATCH_WINS, NET_COLORS
from shared.level import MAPS
from shared.protocol import (
    MSG_JOIN, MSG_PROFILE, MSG_REJECT, MSG_SHOOT, MSG_START, MSG_UPGRADE,
    MSG_WELCOME,
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
        self.assertEqual(self.game.phase, "draft")
        self.assertEqual(winner["score"], 1)
        self.assertEqual(self.game.winner_id, 1)
        self.assertFalse(winner["upgrade_choices"])

        loser = self.game.players[2]
        self.assertTrue(loser["upgrade_choices"])
        card_id = loser["upgrade_choices"][0]["id"]
        self.game.handle_message(
            self.sock, {"type": MSG_UPGRADE, "upgrade": card_id},
            self.addresses[1], 10.2,
        )
        self.assertEqual(loser["upgrades"][card_id], 1)
        self.assertEqual(self.game.phase, "round_over")

        previous_map = self.game.map_id
        self.game.tick(self.game.phase_until, 1 / 30)
        self.assertEqual(self.game.phase, "playing")
        self.assertEqual(self.game.round_number, 2)
        self.assertNotEqual(self.game.map_id, previous_map)
        self.assertIn(self.game.map_id, {game_map.map_id for game_map in MAPS})
        self.assertTrue(all(player["alive"] for player in self.game.players.values()))
        self.assertTrue(all(player["hp"] == 100 for player in self.game.players.values()))
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

    def test_unclaimed_upgrade_is_granted_when_draft_times_out(self):
        self.join(0, "Alice")
        self.join(1, "Bob")
        self.start_match()
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
        self.game.players[2]["alive"] = False
        self.game.players[3]["alive"] = False
        self.game.players[4]["alive"] = False

        self.game.tick(10.1, 1 / 30)

        self.assertEqual(self.game.phase, "draft")
        self.assertFalse(self.game.players[1]["upgrade_choices"])
        for player_id in (2, 3, 4):
            choices = self.game.players[player_id]["upgrade_choices"]
            self.assertEqual(len(choices), 2)
            self.game.handle_message(
                self.sock,
                {"type": MSG_UPGRADE, "upgrade": choices[0]["id"]},
                self.addresses[player_id - 1],
                10.2,
            )
        self.assertEqual(self.game.phase, "round_over")
        for player_id in (2, 3, 4):
            self.assertEqual(sum(self.game.players[player_id]["upgrades"].values()), 1)

    def test_final_round_still_drafts_then_resets_match_upgrades(self):
        self.join(0, "Alice")
        self.join(1, "Bob")
        self.start_match()
        winner = self.game.players[1]
        loser = self.game.players[2]
        winner["score"] = MATCH_WINS - 1
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
        self.assertEqual(self.game.phase, "match_over")

        self.game.tick(self.game.phase_until, 1 / 30)
        self.assertEqual(self.game.phase, "playing")
        self.assertEqual(winner["score"], 0)
        self.assertEqual(winner["upgrades"], {})
        self.assertEqual(loser["upgrades"], {})


if __name__ == "__main__":
    unittest.main()
