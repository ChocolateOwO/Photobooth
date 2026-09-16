"""Route access matrix groundwork (behavioural, independent of FastAPI internals).

Every documented kiosk route must be classified. Every booth/admin route must answer 401 to a
request without the device cookie, whatever the method.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

PROTECTED_PREFIXES = ("/api/booth", "/api/admin")
READ_ONLY_PUBLIC = {"/api/health", "/api/version", "/api/kiosk/status"}
PAIRING = {"/kiosk/pairing-code/rotate"}  # /kiosk/pair is undocumented and tested separately


def test_every_route_is_classified_and_protected_routes_require_device(
    kiosk_client: TestClient,
) -> None:
    spec = kiosk_client.get("/api/openapi.json").json()
    operations = [(path, method.upper()) for path, item in spec["paths"].items() for method in item]
    assert operations
    protected = 0
    for path, method in operations:
        if path.startswith(PROTECTED_PREFIXES):
            protected += 1
            response = kiosk_client.request(method, path)
            assert response.status_code == 401, (method, path, response.status_code)
        elif path in READ_ONLY_PUBLIC:
            assert method in {"GET", "HEAD"}, (method, path)
        else:
            assert path in PAIRING, f"unclassified route: {method} {path}"
    assert protected >= 1
