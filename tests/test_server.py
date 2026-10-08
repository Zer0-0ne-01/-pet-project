import unittest

from server.server import GameServer
from shared.protocol import MSG_JOIN, MSG_REJECT, MSG_SHOOT, MSG_WELCOME


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

    def join(self, index, name="player", now=10.0):
        self.game.handle_message(
            self.sock, {"type": MSG_JOIN, "name": name}, self.addresses[index], now,
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

    def test_projectile_damages_other_player(self):
        self.join(0, "Alice")
        self.join(1, "Bob")
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
        winner = self.game.players[1]
        self.game.players[2]["alive"] = False

        self.game.tick(10.1, 1 / 30)
        self.assertEqual(self.game.phase, "round_over")
        self.assertEqual(winner["score"], 1)
        self.assertEqual(self.game.winner_id, 1)

        self.game.tick(self.game.phase_until, 1 / 30)
        self.assertEqual(self.game.phase, "playing")
        self.assertEqual(self.game.round_number, 2)
        self.assertTrue(all(player["alive"] for player in self.game.players.values()))
        self.assertTrue(all(player["hp"] == 100 for player in self.game.players.values()))


if __name__ == "__main__":
    unittest.main()
