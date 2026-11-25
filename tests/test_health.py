import os
import socket
import sqlite3
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from smart_ask_data.api import create_api
from smart_ask_data.config import load_settings
from smart_ask_data.health import classify_data_source_error
from tools.trino_client import SQLiteDemoClient, TrinoClient


class HealthCheckTest(unittest.TestCase):
    def test_health_endpoint_does_not_reflect_an_invalid_backend_value(self):
        unsafe_backend = "trino://demo:example-password@db.internal:8080/catalog"
        with (
            patch.dict(os.environ, {"SAD_QUERY_BACKEND": unsafe_backend}),
            patch("smart_ask_data.api.get_service", side_effect=RuntimeError("invalid backend")),
        ):
            response = TestClient(create_api()).get("/health")

        self.assertEqual(503, response.status_code)
        self.assertEqual("unknown", response.json()["query_backend"])
        self.assertNotIn("example-password", response.text)
        self.assertNotIn("db.internal", response.text)

    def test_health_endpoint_sanitizes_all_config_derived_labels(self):
        unsafe = "https://demo:example-token@internal.example/api"
        environment = {
            "SAD_ENVIRONMENT": unsafe,
            "SAD_KNOWLEDGE_BACKEND": unsafe,
            "SAD_LLM_BACKEND": unsafe,
        }
        with patch.dict(os.environ, environment):
            response = TestClient(create_api()).get("/health")

        payload = response.json()
        self.assertEqual("unknown", payload["environment"])
        self.assertEqual("unknown", payload["knowledge_backend"])
        self.assertEqual("unknown", payload["llm_backend"])
        self.assertNotIn("example-token", response.text)
        self.assertNotIn("internal.example", response.text)

    def test_any_configuration_load_failure_still_exposes_safe_health(self):
        error = RuntimeError("invalid yaml contains password=super-secret at config.internal")
        with patch("smart_ask_data.api.load_settings", side_effect=error):
            response = TestClient(create_api()).get("/health")

        self.assertEqual(503, response.status_code)
        self.assertEqual("DATA_SOURCE_CONFIGURATION_INVALID", response.json()["data_source"]["error"]["code"])
        self.assertNotIn("super-secret", response.text)
        self.assertNotIn("config.internal", response.text)

    def test_invalid_boolean_configuration_still_exposes_a_safe_health_endpoint(self):
        with patch.dict(os.environ, {"SAD_TRINO_READ_ONLY": "not-a-bool"}):
            response = TestClient(create_api()).get("/health")

        self.assertEqual(503, response.status_code)
        payload = response.json()
        self.assertEqual("unknown", payload["query_backend"])
        self.assertEqual("DATA_SOURCE_CONFIGURATION_INVALID", payload["data_source"]["error"]["code"])
        self.assertNotIn("not-a-bool", response.text)

    def test_data_source_timeout_has_a_stable_safe_error(self):
        result = classify_data_source_error(TimeoutError("deadline exceeded at db.internal"))

        self.assertEqual({
            "code": "DATA_SOURCE_TIMEOUT",
            "message": "数据源连接超时",
        }, result)

    def test_invalid_data_source_configuration_has_a_stable_safe_error(self):
        result = classify_data_source_error(ValueError("missing secret catalog"))

        self.assertEqual({
            "code": "DATA_SOURCE_CONFIGURATION_INVALID",
            "message": "数据源配置无效",
        }, result)

    def test_trino_read_only_declaration_can_be_set_from_environment(self):
        with patch.dict("os.environ", {"SAD_TRINO_READ_ONLY": "false"}):
            settings = load_settings()

        self.assertFalse(settings.trino.read_only)

    def test_sqlite_health_check_executes_a_real_probe(self):
        client = SQLiteDemoClient()

        result = client.health_check()

        self.assertEqual({
            "status": "ok",
            "backend": "sqlite",
            "read_only": True,
            "read_only_basis": "isolated_demo_database",
        }, result)

    def test_sqlite_demo_database_rejects_writes_after_seeding(self):
        client = SQLiteDemoClient()

        with self.assertRaises(sqlite3.DatabaseError):
            client.execute("CREATE TABLE should_not_exist (id INTEGER)")

    def test_sqlite_demo_database_cannot_disable_read_only_mode(self):
        client = SQLiteDemoClient()

        with self.assertRaises(sqlite3.DatabaseError):
            client.execute("PRAGMA query_only = OFF")
        with self.assertRaises(sqlite3.DatabaseError):
            client.execute("CREATE TABLE should_not_exist (id INTEGER)")

    def test_sqlite_health_check_is_safe_across_threads(self):
        client = SQLiteDemoClient()
        results = []

        worker = threading.Thread(target=lambda: results.append(client.health_check()))
        worker.start()
        worker.join()

        self.assertEqual("ok", results[0]["status"])

    def test_trino_health_check_classifies_and_redacts_authentication_failure(self):
        class FailingCursor:
            def execute(self, _sql):
                raise RuntimeError(
                    "authentication failed for password=super-secret "
                    "at trino.internal.example.com"
                )

        class FailingConnection:
            def cursor(self):
                return FailingCursor()

        client = TrinoClient.__new__(TrinoClient)
        client.connection = FailingConnection()
        client.read_only = True

        result = client.health_check()

        self.assertEqual("error", result["status"])
        self.assertEqual("trino", result["backend"])
        self.assertTrue(result["read_only"])
        self.assertEqual("declared_by_configuration", result["read_only_basis"])
        self.assertEqual("DATA_SOURCE_AUTHENTICATION_FAILED", result["error"]["code"])
        self.assertEqual("数据源认证失败", result["error"]["message"])
        self.assertNotIn("super-secret", str(result))
        self.assertNotIn("trino.internal.example.com", str(result))

    def test_trino_health_check_rejects_a_non_read_only_configuration(self):
        class HealthyCursor:
            def execute(self, _sql):
                return None

            def fetchone(self):
                return (1,)

        class HealthyConnection:
            def cursor(self):
                return HealthyCursor()

        client = TrinoClient.__new__(TrinoClient)
        client.connection = HealthyConnection()
        client.read_only = False

        result = client.health_check()

        self.assertEqual("error", result["status"])
        self.assertEqual("DATA_SOURCE_NOT_READ_ONLY", result["error"]["code"])

    def test_trino_health_check_accepts_a_successful_read_only_probe(self):
        class HealthyCursor:
            def execute(self, _sql):
                return None

            def fetchone(self):
                return (1,)

        client = TrinoClient.__new__(TrinoClient)
        client.connection = SimpleNamespace(cursor=lambda: HealthyCursor())
        client.read_only = True

        self.assertEqual("ok", client.health_check()["status"])

    def test_trino_client_rejects_non_boolean_read_only_configuration(self):
        fake_trino = SimpleNamespace(dbapi=SimpleNamespace(connect=lambda **_kwargs: object()))
        config = {
            "host": "localhost", "port": 8080, "user": "demo",
            "catalog": "hive", "schema": "default", "read_only": "false",
        }

        with (
            patch.dict("sys.modules", {"trino": fake_trino}),
            self.assertRaisesRegex(TypeError, "read_only"),
        ):
            TrinoClient(config)

    def test_socket_failure_is_classified_as_connection_failure(self):
        result = classify_data_source_error(socket.gaierror("getaddrinfo failed"))

        self.assertEqual("DATA_SOURCE_CONNECTION_FAILED", result["code"])

    def test_actual_sqlite_health_endpoint_returns_200(self):
        from smart_ask_data.api import get_service

        get_service.cache_clear()
        try:
            response = TestClient(create_api()).get("/health")
        finally:
            get_service.cache_clear()

        self.assertEqual(200, response.status_code)
        self.assertEqual("ok", response.json()["data_source"]["status"])

    def test_health_endpoint_returns_503_for_unavailable_data_source(self):
        class UnavailableService:
            def health_check(self):
                return {
                    "status": "error",
                    "backend": "trino",
                    "read_only": True,
                    "read_only_basis": "declared_by_configuration",
                    "error": {
                        "code": "DATA_SOURCE_CONNECTION_FAILED",
                        "message": "无法连接数据源",
                    },
                }

        with patch("smart_ask_data.api.get_service", return_value=UnavailableService()):
            response = TestClient(create_api()).get("/health")

        self.assertEqual(503, response.status_code)
        payload = response.json()
        self.assertEqual("unavailable", payload["status"])
        self.assertEqual("DATA_SOURCE_CONNECTION_FAILED", payload["data_source"]["error"]["code"])

    def test_health_endpoint_redacts_service_creation_failure(self):
        error = RuntimeError("connection refused at db.internal.example.com")

        with patch("smart_ask_data.api.get_service", side_effect=error):
            response = TestClient(create_api()).get("/health")

        self.assertEqual(503, response.status_code)
        payload_text = response.text
        self.assertIn("DATA_SOURCE_CONNECTION_FAILED", payload_text)
        self.assertNotIn("db.internal.example.com", payload_text)


if __name__ == "__main__":
    unittest.main()
