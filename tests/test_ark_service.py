import asyncio
import socket
import unittest
from unittest.mock import Mock, patch

from src.ark_service import ArkRconService, SourceRconClient, parse_player_snapshot, parse_players


class ArkServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_parse_players_hides_ids_and_handles_empty(self):
        response = "0. Alice, 123456789, 00000000000000000000000000000001\n1. Bob, 987654321, 00000000000000000000000000000002"
        self.assertEqual(parse_players(response), ["Alice", "Bob"])
        self.assertEqual(parse_players("No Players Connected"), [])

    def test_parse_player_snapshot_uses_internal_ids_without_exposing_them(self):
        response = "0. Alice, 123456789, EOSABC123\n1. Bob, 987654321, EOSXYZ999"
        snapshot = parse_player_snapshot(response)
        self.assertEqual(set(snapshot.values()), {"Alice", "Bob"})
        self.assertTrue(all(key.startswith("id:") for key in snapshot))

    async def test_successful_status_and_empty_server(self):
        service = ArkRconService(password="secret")
        with patch.object(service, "players", return_value=[]):
            result = await service.status()
        self.assertTrue(result.reachable)
        self.assertTrue(result.authenticated)
        self.assertEqual(result.players, ())

    async def test_successful_status_with_players(self):
        service = ArkRconService(password="secret")
        with patch.object(service, "players", return_value=["Alice"]):
            result = await service.status()
        self.assertEqual(result.players, ("Alice",))

    async def test_unavailable_server(self):
        service = ArkRconService(password="secret")
        with patch.object(service, "players", side_effect=ConnectionError):
            result = await service.status()
        self.assertFalse(result.reachable)
        self.assertFalse(result.authenticated)
        self.assertEqual(result.error, "RCON server unavailable")

    async def test_authentication_failure(self):
        service = ArkRconService(password="secret")
        with patch.object(service, "players", side_effect=PermissionError):
            result = await service.status()
        self.assertTrue(result.reachable)
        self.assertFalse(result.authenticated)

    def test_credential_not_logged_or_exposed_by_service_repr(self):
        service = ArkRconService(password="super-secret")
        self.assertNotIn("super-secret", repr(service))


class RconCommandSafetyTests(unittest.TestCase):
    def test_client_rejects_non_read_only_command(self):
        client = object.__new__(SourceRconClient)
        with self.assertRaises(ValueError):
            client.run("ServerChat unsafe")

    def test_server_chat_is_fixed_command_with_text_argument(self):
        client = object.__new__(SourceRconClient)
        client.sock = type("Sock", (), {"gettimeout": lambda self: 5, "settimeout": lambda self, value: None})()
        client._send_packet = lambda packet_type, body: 1
        client._read_packet = lambda: (1, 0, "")
        client.sock.recv = lambda size, flags=0: (_ for _ in ()).throw(socket.timeout())
        # The service constructs the command; arbitrary command names are not accepted.
        with patch("src.ark_service.select.select", return_value=([], [], [])):
            self.assertIsNone(client.server_chat("hello"))

    def test_response_packet_limit_and_size_constants_exist(self):
        import src.ark_service as service
        self.assertGreater(service.MAX_RESPONSE_PACKETS, 1)
        self.assertGreater(service.MAX_RESPONSE_BYTES, 1024)

    def test_delayed_multi_packet_response_is_assembled_and_stale_id_rejected(self):
        import src.ark_service as service
        client = object.__new__(SourceRconClient)
        client.sock = type("Sock", (), {"gettimeout": lambda self: 5, "settimeout": lambda self, value: None})()
        client._next_id = 1
        client._send_packet = lambda packet_type, body: 7
        client._read_packet = Mock(side_effect=[(7, 0, "a"), (7, 0, "b")])
        with patch("src.ark_service.select.select", side_effect=[([client.sock], [], []), ([], [], [])]):
            self.assertEqual(client._response("ListPlayers"), "ab")
        client._read_packet = Mock(return_value=(8, 0, "stale"))
        with patch("src.ark_service.select.select", return_value=([client.sock], [], [])):
            with self.assertRaises(ConnectionError): client._response("ListPlayers")


if __name__ == "__main__":
    unittest.main()
