from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
for path in ['/health', '/login']:
    r = client.get(path)
    print(path, '->', r.status_code)
    print(r.text[:400])
