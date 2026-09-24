import os
import unittest
from unittest.mock import patch

from app.athena_backend import (
    AthenaQueryError,
    convert_athena_value,
    execute_named_query,
    fetch_all_rows,
    load_named_query,
)


class FakeAthenaClient:
    def __init__(self, states: list[str]) -> None:
        self.states = iter(states)
        self.stopped = False
        self.result_calls = 0

    def start_query_execution(self, **kwargs):
        self.start_request = kwargs
        return {"QueryExecutionId": "query-123"}

    def get_query_execution(self, **kwargs):
        state = next(self.states)
        status = {"State": state}
        if state == "FAILED":
            status["StateChangeReason"] = "table missing"
        return {"QueryExecution": {"Status": status}}

    def stop_query_execution(self, **kwargs):
        self.stopped = True

    def get_query_results(self, **kwargs):
        self.result_calls += 1
        metadata = {
            "ColumnInfo": [
                {"Name": "id", "Type": "bigint"},
                {"Name": "amount", "Type": "decimal(10,2)"},
                {"Name": "active", "Type": "boolean"},
            ]
        }
        if "NextToken" not in kwargs:
            return {
                "ResultSet": {
                    "ResultSetMetadata": metadata,
                    "Rows": [
                        {"Data": [{"VarCharValue": "id"}, {"VarCharValue": "amount"}, {"VarCharValue": "active"}]},
                        {"Data": [{"VarCharValue": "1"}, {"VarCharValue": "10.50"}, {"VarCharValue": "true"}]},
                    ],
                },
                "NextToken": "page-2",
            }
        return {
            "ResultSet": {
                "ResultSetMetadata": metadata,
                "Rows": [{"Data": [{"VarCharValue": "2"}, {}, {"VarCharValue": "false"}]}],
            }
        }


class AthenaBackendTests(unittest.TestCase):
    def test_value_conversion_preserves_decimal_precision(self):
        self.assertEqual(convert_athena_value("7", "bigint"), 7)
        self.assertEqual(convert_athena_value("1.25", "double"), 1.25)
        self.assertEqual(convert_athena_value("19.90", "decimal(10,2)"), "19.90")
        self.assertIs(convert_athena_value("true", "boolean"), True)
        self.assertIsNone(convert_athena_value(None, "varchar"))

    def test_result_pagination_and_header_removal(self):
        client = FakeAthenaClient(["SUCCEEDED"])
        rows = fetch_all_rows(client, "query-123")
        self.assertEqual(
            rows,
            [
                {"id": 1, "amount": "10.50", "active": True},
                {"id": 2, "amount": None, "active": False},
            ],
        )
        self.assertEqual(client.result_calls, 2)

    @patch("app.athena_backend.load_named_query", return_value="SELECT 1")
    @patch("app.athena_backend.time.sleep", return_value=None)
    def test_query_waits_and_returns_typed_rows(self, _sleep, _load_query):
        client = FakeAthenaClient(["QUEUED", "RUNNING", "SUCCEEDED"])
        result = execute_named_query("event_count", client=client)
        self.assertEqual(result.execution_id, "query-123")
        self.assertEqual(len(result.rows), 2)
        self.assertEqual(client.start_request["WorkGroup"], "hardtech-workgroup")

    @patch("app.athena_backend.load_named_query", return_value="SELECT 1")
    def test_failed_query_is_controlled(self, _load_query):
        client = FakeAthenaClient(["FAILED"])
        with self.assertRaises(AthenaQueryError) as raised:
            execute_named_query("event_count", client=client)
        self.assertEqual(raised.exception.execution_id, "query-123")
        self.assertIn("table missing", str(raised.exception))

    @patch("app.athena_backend.load_named_query", return_value="SELECT 1")
    def test_timeout_cancels_query(self, _load_query):
        client = FakeAthenaClient(["QUEUED"])
        with patch.dict(os.environ, {"ATHENA_QUERY_TIMEOUT_SECONDS": "0"}):
            with self.assertRaises(AthenaQueryError) as raised:
                execute_named_query("event_count", client=client)
        self.assertEqual(raised.exception.status_code, 504)
        self.assertTrue(client.stopped)

    @patch("app.athena_backend.load_named_query", return_value="SELECT 1")
    def test_invalid_timeout_is_controlled_configuration_error(self, _load_query):
        client = FakeAthenaClient(["SUCCEEDED"])
        with patch.dict(os.environ, {"ATHENA_QUERY_TIMEOUT_SECONDS": "invalid"}):
            with self.assertRaises(AthenaQueryError) as raised:
                execute_named_query("event_count", client=client)
        self.assertEqual(raised.exception.status_code, 500)

    def test_only_known_queries_can_be_loaded(self):
        with self.assertRaises(ValueError):
            load_named_query("../../unsafe")

    def test_inventory_queries_are_versioned_and_use_latest_snapshot(self):
        summary = load_named_query("inventory_summary")
        low_stock = load_named_query("inventory_low_stock")
        self.assertIn("MAX(snapshot_at)", summary)
        self.assertIn("MAX(snapshot_at)", low_stock)
        self.assertIn("low_stock", low_stock)


if __name__ == "__main__":
    unittest.main()
