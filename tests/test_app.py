import os
import tempfile
import pytest
from app import app, init_db

@pytest.fixture()
def client():
    fd, path = tempfile.mkstemp()
    app.config.update(TESTING=True, DATABASE=path, SECRET_KEY="test")
    with app.app_context(): init_db()
    with app.test_client() as client: yield client
    os.close(fd); os.unlink(path)

def login(client):
    return client.post("/login", data={"username":"admin","password":"admin123"}, follow_redirects=True)

def test_login_and_dashboard(client):
    assert b"Dashboard" in login(client).data

def test_patient_workflow(client):
    login(client)
    response = client.post("/patients", data={"name":"Anita Rao","age":"29","gender":"Female","phone":"9876543210","blood_group":"O+","address":"Mysuru"}, follow_redirects=True)
    assert b"Anita Rao" in response.data

def test_protected_route(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302 and "/login" in response.headers["Location"]
