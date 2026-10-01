import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.ha_mqtt import HAMQTTBridge, mqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.reasoncodes import ReasonCode


class Store:
    def __init__(self, root):
        self.root = root

    def list_devices(self):
        return []


class ClientFactory:
    def __init__(self):
        self.clients = []
        self.active = set()
        self.max_active = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self.pause_first = False
        self.fail_start = False
        self.fail_stop = False

    def __call__(self, *args, **kwargs):
        client = FakeClient(self, len(self.clients))
        self.clients.append(client)
        return client


class FakeClient:
    def __init__(self, factory, index):
        self.factory = factory
        self.index = index
        self.events = []
        self.subscriptions = []

    def reconnect_delay_set(self, **kwargs):
        self.delays = kwargs

    def username_pw_set(self, *args):
        self.credentials = args

    def connect_async(self, *args):
        self.connection = args
        self.events.append('connect_async')
        if self.index == 0 and self.factory.pause_first:
            self.factory.entered.set()
            if not self.factory.release.wait(5):
                raise RuntimeError('test timeout')
        # Paho 2.1.0 returns None, not MQTT_ERR_SUCCESS.

    def loop_start(self):
        self.events.append('loop_start')
        if self.factory.fail_start:
            return mqtt.MQTT_ERR_INVAL
        self.factory.active.add(self.index)
        self.factory.max_active = max(self.factory.max_active, len(self.factory.active))
        return mqtt.MQTT_ERR_SUCCESS

    def disconnect(self):
        self.events.append('disconnect')

    def loop_stop(self):
        self.events.append('loop_stop')
        if self.factory.fail_stop:
            raise RuntimeError('stop failed')
        self.factory.active.discard(self.index)

    def subscribe(self, topic, qos):
        self.subscriptions.append((topic, qos))


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.commands = []
        self.bridge = HAMQTTBridge(Store(self.temporary.name), lambda *args: self.commands.append(args))
        self.bridge.config['host'] = 'unused.invalid'
        self.factory = ClientFactory()
        self.patcher = patch.object(mqtt, 'Client', self.factory)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_restart_stops_before_starting_replacement(self):
        self.bridge.restart()
        old = self.bridge.client
        self.bridge.restart()
        self.assertEqual(old.events[-2:], ['disconnect', 'loop_stop'])
        self.assertEqual(self.factory.max_active, 1)
        self.assertEqual(self.bridge.client.delays, {'min_delay': 1, 'max_delay': 30})

    def test_concurrent_startup_is_serialized(self):
        self.factory.pause_first = True
        worker = threading.Thread(target=self.bridge.restart)
        worker.start()
        self.assertTrue(self.factory.entered.wait(5))
        second_entered = threading.Event()

        def second_restart():
            second_entered.set()
            self.bridge.restart()

        second = threading.Thread(target=second_restart)
        second.start()
        try:
            self.assertTrue(second_entered.wait(5))
            # Lifecycle lock stays owned until connect_async and loop_start finish.
            self.assertFalse(self.bridge._restart_lock.acquire(blocking=False))
        finally:
            self.factory.release.set()
            worker.join(5)
            second.join(5)
        self.assertFalse(worker.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(len(self.factory.clients), 2)
        self.assertEqual(self.factory.max_active, 1)
        self.assertEqual(self.factory.active, {1})

    def test_old_callbacks_cannot_change_new_connection(self):
        self.bridge.restart()
        old = self.bridge.client
        # Simulate callbacks captured by Paho before handlers are cleared.
        captured = (old.on_connect, old.on_disconnect, old.on_message)
        self.bridge.restart()
        self.bridge.connected = True
        self.bridge.error = 'new status'
        captured[0](old, None, None, 0, None)
        captured[0](old, None, None, 128, None)
        captured[1](old, None, None, 128, None)
        captured[2](old, None, SimpleNamespace(topic='mttl/1234567/set/all', payload=b'ON'))
        self.assertTrue(self.bridge.connected)
        self.assertEqual(self.bridge.error, 'new status')
        self.assertIsNone(self.bridge.last_connected)
        self.assertEqual(old.subscriptions, [])
        self.assertEqual(self.commands, [])

    def test_current_connect_and_disconnect(self):
        self.bridge.restart()
        client = self.bridge.client
        client.on_connect(client, None, None, ReasonCode(PacketTypes.CONNACK, identifier=0), None)
        self.assertTrue(self.bridge.connected)
        self.assertEqual(client.subscriptions, [('mttl/+/set/+', 1)])
        self.assertTrue(self.bridge.status_path.exists())
        client.on_disconnect(client, None, None, 0, None)
        self.assertFalse(self.bridge.connected)

    def test_refused_current_connection(self):
        self.bridge.restart()
        client = self.bridge.client
        client.on_connect(client, None, None, 128, None)
        self.assertFalse(self.bridge.connected)
        self.assertIn('connection refused', self.bridge.error)

    def test_empty_host_stops_existing_client(self):
        self.bridge.restart()
        self.bridge.config['host'] = ''
        self.bridge.restart()
        self.assertIsNone(self.bridge.client)
        self.assertFalse(self.factory.active)
        self.assertEqual(len(self.factory.clients), 1)

    def test_start_failure_cleans_up_then_allows_retry(self):
        self.factory.fail_start = True
        self.bridge.restart()
        self.assertIsNone(self.bridge.client)
        self.assertFalse(self.bridge.connected)
        self.assertIn('failed to start', self.bridge.error)
        self.assertEqual(self.factory.clients[0].events[-2:], ['disconnect', 'loop_stop'])
        self.factory.fail_start = False
        self.bridge.restart()
        self.assertEqual(self.factory.active, {1})
        self.assertEqual(self.bridge.error, '')

    def test_stop_failure_does_not_start_duplicate(self):
        self.bridge.restart()
        old = self.bridge.client
        self.factory.fail_stop = True
        self.bridge.restart()
        self.assertIs(self.bridge.client, old)
        self.assertFalse(self.bridge.connected)
        self.assertEqual(len(self.factory.clients), 1)
        self.assertIn('stop failed', self.bridge.error)
        self.factory.fail_stop = False
        self.bridge.restart()
        self.assertEqual(self.factory.active, {1})

    def test_concurrent_saves_use_one_temp_file_safely(self):
        barrier = threading.Barrier(5)
        errors = []

        def save(index):
            try:
                barrier.wait(timeout=5)
                self.bridge.save_config({'host': f'host-{index}', 'port': 1883})
            except Exception as error:
                errors.append(error)

        workers = [threading.Thread(target=save, args=(index,)) for index in range(4)]
        for worker in workers:
            worker.start()
        barrier.wait(timeout=5)
        for worker in workers:
            worker.join(5)
            self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        persisted = json.loads(self.bridge.path.read_text())
        self.assertEqual(persisted, self.bridge.config)
        self.assertEqual(self.bridge.client.connection[0], persisted['host'])
        self.assertEqual(self.factory.max_active, 1)

    def test_duplicate_start_does_not_create_two_publishers(self):
        with patch('server.ha_mqtt.threading.Thread') as thread:
            self.bridge.start()
            self.bridge.start()
            thread.assert_called_once()
        self.assertEqual(len(self.factory.clients), 1)

    def test_paho_reason_code_comparison(self):
        reason = ReasonCode(PacketTypes.CONNACK, identifier=0)
        self.assertEqual(reason, 0)
        self.assertFalse(reason != 0)
        self.assertEqual(self.bridge._rc_value(reason), 0)


class PahoIntegrationTests(unittest.TestCase):
    def test_real_paho_sends_disconnect_before_replacement(self):
        # Minimal loopback-only MQTT 3.1.1 peer; no Home Assistant/server access.
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(2)
        listener.settimeout(0.2)
        stopped = threading.Event()
        events = []
        errors = []

        def exact(peer, size):
            data = b''
            while len(data) < size:
                chunk = peer.recv(size - len(data))
                if not chunk:
                    raise EOFError()
                data += chunk
            return data

        def serve():
            try:
                while not stopped.is_set():
                    try:
                        peer, _ = listener.accept()
                    except socket.timeout:
                        continue
                    with peer:
                        peer.settimeout(3)
                        while not stopped.is_set():
                            first = exact(peer, 1)[0]
                            remaining, multiplier = 0, 1
                            while True:
                                digit = exact(peer, 1)[0]
                                remaining += (digit & 127) * multiplier
                                if not digit & 128:
                                    break
                                multiplier *= 128
                            payload = exact(peer, remaining)
                            kind = first >> 4
                            if kind == 1:
                                events.append('CONNECT')
                                peer.sendall(b'\x20\x02\x00\x00')
                            elif kind == 8:
                                peer.sendall(b'\x90\x03' + payload[:2] + b'\x01')
                            elif kind == 12:
                                peer.sendall(b'\xd0\x00')
                            elif kind == 14:
                                events.append('DISCONNECT')
                                break
            except (OSError, EOFError) as error:
                if not stopped.is_set():
                    errors.append(error)

        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        with tempfile.TemporaryDirectory() as root:
            bridge = HAMQTTBridge(Store(root), lambda *args: None)
            bridge.config.update(host='127.0.0.1', port=listener.getsockname()[1])

            def wait_connected():
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    if bridge.public_config()['connected']:
                        return
                    time.sleep(0.01)
                self.fail(f'Paho connection timed out: {bridge.error}; {errors}')

            try:
                bridge.restart()
                wait_connected()
                bridge.restart()
                wait_connected()
                bridge.config['host'] = ''
                bridge.restart()
            finally:
                bridge.config['host'] = ''
                bridge.restart()
                stopped.set()
                worker.join(4)
                listener.close()
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(events, ['CONNECT', 'DISCONNECT', 'CONNECT', 'DISCONNECT'])
            self.assertIsNone(bridge.client)


if __name__ == '__main__':
    unittest.main()
