import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.athena_backend import AthenaQueryError, AthenaQueryResult
from app import main


class AnalyticsApiTests(unittest.TestCase):
    def test_s3_backend_keeps_existing_endpoints(self):
        events = [
            {"event_type": "PRODUCT_VIEW", "product_id": 1},
            {"event_type": "PRODUCT_VIEW", "product_id": 1},
            {"event_type": "ORDER_CREATED", "product_id": None},
        ]
        with patch.dict(os.environ, {"ANALYTICS_BACKEND": "s3"}):
            with patch("app.main.load_events", return_value=events):
                count = main.count_events()
                top = main.top_products()
        self.assertEqual(count["total_events"], 3)
        self.assertEqual(count["by_type"]["PRODUCT_VIEW"], 2)
        self.assertEqual(top["top_products"][0], {"product_id": "1", "views": 2})

    def test_athena_event_count_preserves_response_contract(self):
        result = AthenaQueryResult(
            rows=[
                {"event_type": "PRODUCT_VIEW", "event_count": 8},
                {"event_type": "ORDER_CREATED", "event_count": 2},
            ],
            execution_id="query-abc",
            duration_ms=42,
        )
        with patch.dict(os.environ, {"ANALYTICS_BACKEND": "athena"}):
            with patch("app.main.execute_named_query", return_value=result):
                response = main.count_events()
        self.assertEqual(response["total_events"], 10)
        self.assertEqual(response["query_execution_id"], "query-abc")

    def test_new_endpoint_requires_athena_locally(self):
        with patch.dict(os.environ, {"ANALYTICS_BACKEND": "s3"}):
            with self.assertRaises(HTTPException) as raised:
                main.sales_summary()
        self.assertEqual(raised.exception.status_code, 503)

    def test_athena_error_becomes_controlled_http_error(self):
        error = AthenaQueryError("Athena query failed", execution_id="query-bad")
        with patch("app.main.execute_named_query", side_effect=error):
            with self.assertRaises(HTTPException) as raised:
                main.run_athena("sales_summary")
        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(raised.exception.detail["query_execution_id"], "query-bad")

    def test_openapi_contains_every_analytics_endpoint_and_examples(self):
        schema = main.app.openapi()
        expected = {
            "/api/analytics/events/count",
            "/api/analytics/top-products",
            "/api/analytics/sales/summary",
            "/api/analytics/sales/by-category",
            "/api/analytics/products/conversion",
            "/api/analytics/compatibility/failure-rules",
            "/api/analytics/compatibility/summary",
            "/api/analytics/users/registrations",
            "/api/analytics/funnel",
            "/api/analytics/inventory/summary",
            "/api/analytics/inventory/low-stock",
        }
        self.assertTrue(expected.issubset(schema["paths"]))
        for path in expected:
            example = schema["paths"][path]["get"]["responses"]["200"]["content"]["application/json"].get("example")
            self.assertIsNotNone(example, path)

    def test_swagger_embeds_openapi_without_a_secondary_fetch(self):
        response = main.analytics_docs()
        html = response.body.decode("utf-8")
        self.assertIn("Analytics Service - Swagger UI", html)
        self.assertIn("spec:", html)
        self.assertIn('"/api/analytics/events/count"', html)
        self.assertNotIn('url: "/analytics/openapi.json"', html)

    def test_inventory_summary_maps_athena_metadata(self):
        result = AthenaQueryResult(
            rows=[
                {
                    "total_products": 5,
                    "physical_units": 40,
                    "reserved_units": 4,
                    "sellable_units": 36,
                    "low_stock_products": 1,
                    "snapshot_at": "2026-09-23 16:00:00.000",
                }
            ],
            execution_id="query-inventory-summary",
            duration_ms=31,
        )
        with patch.dict(os.environ, {"ANALYTICS_BACKEND": "athena"}), patch(
            "app.main.execute_named_query", return_value=result
        ) as execute:
            response = main.inventory_summary()
        execute.assert_called_once_with("inventory_summary")
        self.assertEqual(response["inventory_summary"]["sellable_units"], 36)
        self.assertEqual(response["backend"], "athena")
        self.assertEqual(response["query_execution_id"], "query-inventory-summary")
        self.assertEqual(response["duration_ms"], 31)

    def test_inventory_low_stock_maps_rows_and_requires_athena(self):
        result = AthenaQueryResult(
            rows=[{"product_id": 7, "sellable_quantity": 2, "minimum_quantity": 2}],
            execution_id="query-inventory-low",
            duration_ms=19,
        )
        with patch.dict(os.environ, {"ANALYTICS_BACKEND": "athena"}), patch(
            "app.main.execute_named_query", return_value=result
        ):
            response = main.inventory_low_stock()
        self.assertEqual(response["low_stock"], result.rows)
        self.assertEqual(response["backend"], "athena")
        self.assertEqual(response["query_execution_id"], "query-inventory-low")

        with patch.dict(os.environ, {"ANALYTICS_BACKEND": "s3"}):
            with self.assertRaises(HTTPException) as raised:
                main.inventory_low_stock()
        self.assertEqual(raised.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
