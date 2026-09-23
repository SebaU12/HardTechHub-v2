import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


def get_catalog_service_url() -> str:
    return os.getenv("CATALOG_SERVICE_URL", "http://catalog-service:8002")


def fetch_product(product_id: int) -> dict[str, Any]:
    product_url = f"{get_catalog_service_url()}/api/products/{product_id}"
    try:
        with urlopen(product_url, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(status_code=400, detail=f"Product {product_id} not found") from exc
        raise HTTPException(status_code=502, detail="Catalog Service error") from exc
    except URLError as exc:
        raise HTTPException(status_code=503, detail="Catalog Service unavailable") from exc


app = FastAPI(title="Compatibility Service", version="1.0.0")


class ComponentRequest(BaseModel):
    type: str
    product_id: int


class CompatibilityRequest(BaseModel):
    components: list[ComponentRequest]


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"service": "compatibility-service", "status": "healthy", "version": "1.0.0"}


@app.post("/api/compatibility/check")
def check_compatibility(payload: CompatibilityRequest) -> dict[str, Any]:
    components_by_type = {component.type.lower(): component.product_id for component in payload.components}

    cpu_id = components_by_type.get("cpu")
    motherboard_id = components_by_type.get("motherboard")
    if not cpu_id or not motherboard_id:
        raise HTTPException(status_code=400, detail="cpu and motherboard are required for CPU_SOCKET")

    cpu = fetch_product(cpu_id)
    motherboard = fetch_product(motherboard_id)

    cpu_socket = cpu.get("specs", {}).get("socket")
    motherboard_socket = motherboard.get("specs", {}).get("socket")
    if not cpu_socket or not motherboard_socket:
        raise HTTPException(status_code=400, detail="Missing socket spec in catalog data")

    is_compatible = cpu_socket == motherboard_socket
    return {
        "compatible": is_compatible,
        "checks": [
            {
                "rule": "CPU_SOCKET",
                "status": "PASS" if is_compatible else "FAIL",
                "details": {
                    "cpu_socket": cpu_socket,
                    "motherboard_socket": motherboard_socket,
                },
            }
        ],
    }
