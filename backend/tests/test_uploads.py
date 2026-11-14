import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import drawings, main, uploads


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LEARGAS_DATA_ROOT", str(tmp_path / "dataset"))
    monkeypatch.setenv("LEARGAS_QUESTIONS", str(tmp_path / "missing.jsonl"))
    monkeypatch.setenv("LEARGAS_MOCK", "1")
    monkeypatch.setattr(drawings, "CACHE", tmp_path / "cache")
    cached_catalogue = drawings._catalogue
    cached_catalogue.cache_clear()
    yield TestClient(main.app)
    cached_catalogue.cache_clear()


def image_bytes(color="white", format="PNG"):
    output = io.BytesIO()
    Image.new("RGB", (32, 24), color).save(output, format=format)
    return output.getvalue()


def upload(client, content, name="Floor plan.png"):
    return client.post("/drawings/upload", params={"filename": name}, content=content,
                       headers={"content-type": "application/octet-stream"})


@pytest.mark.parametrize("name,format", [("Floor plan.png", "PNG"), ("Plan.JPG", "JPEG"), ("Plan.jpeg", "JPEG")])
def test_upload_view_reload_and_ask(client, name, format):
    assert client.get("/drawings").json()["total"] == 0  # prime the dataset cache
    content = image_bytes(format=format)
    response = upload(client, content, name)
    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan["collection"] == "uploads" and plan["questions"] == []
    assert client.get("/drawing", params={"path": plan["path"]}).content == content
    drawings._catalogue.cache_clear()  # simulate process restart
    assert client.get("/drawings").json() == {"total": 1, "drawings": [plan]}
    assert client.post("/ask", json={"path": plan["path"], "question": "How many windows?"}).json()["status"] == "cannot_verify"


def test_same_filename_does_not_overwrite_or_share_preview(client):
    first = upload(client, image_bytes("red")).json()
    second = upload(client, image_bytes("blue")).json()
    assert first["path"] != second["path"]
    assert client.get("/drawings").json()["total"] == 2
    assert client.get("/drawing", params={"path": first["path"]}).content != client.get("/drawing", params={"path": second["path"]}).content


@pytest.mark.parametrize("content,name,status", [
    (b"", "empty.png", 400),
    (b"not an image", "bad.png", 400),
    (image_bytes(), "bad.jpg", 400),
    (b"<script>alert(1)</script>", "plan.svg", 415),
    (b"abc", "plan.dwg", 415),
    (b"not pdf", "plan.pdf", 400),
    (b"not dxf", "plan.dxf", 400),
])
def test_rejects_invalid_files_without_publishing(client, content, name, status):
    response = upload(client, content, name)
    assert response.status_code == status, response.text
    assert client.get("/drawings").json()["total"] == 0
    assert not list(uploads.upload_root().glob(".pending-*"))


def test_size_limit_with_and_without_content_length(client, monkeypatch):
    monkeypatch.setattr(uploads, "MAX_UPLOAD_BYTES", 10)
    assert upload(client, b"x" * 11).status_code == 413
    response = client.post("/drawings/upload?filename=plan.png", content=iter([b"x" * 6, b"x" * 6]))
    assert response.status_code == 413
    assert client.get("/drawings").json()["total"] == 0
    assert not list(uploads.upload_root().glob(".pending-*"))


@pytest.mark.parametrize("name", ["../../outside.png", "C:\\Users\\plans\\outside.png"])
def test_filename_stays_in_upload_directory(client, name):
    plan = upload(client, image_bytes(), name).json()
    path = drawings._resolve(plan["path"])
    assert path.parent.parent == uploads.upload_root()
    assert path.name == "outside.png"
    assert client.get("/drawing?path=../../outside.png").status_code == 400


def test_pdf_preview_available_to_viewer_and_model(client):
    fitz = pytest.importorskip("fitz")
    from app.router import raster_image

    plans = []
    for text in ("FIRST PLAN", "SECOND PLAN"):
        with fitz.open() as doc:
            page = doc.new_page(width=240, height=180)
            page.insert_text((20, 60), text)
            response = upload(client, doc.tobytes(), "Floor.pdf")
        assert response.status_code == 201, response.text
        plan = response.json()
        assert plan["render"] == "pdf"
        image = raster_image(plan["path"])
        assert image and image.is_file()
        preview = client.get("/drawing", params={"path": plan["path"]})
        assert preview.headers["content-type"] == "image/png"
        assert preview.content == image.read_bytes()
        plans.append(preview.content)
    assert plans[0] != plans[1]


def test_dxf_upload_has_independent_render_and_frame(client, tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    responses = []
    for length in (10, 20):
        doc = ezdxf.new()
        doc.modelspace().add_line((0, 0), (length, 10))
        source = tmp_path / "drawing.dxf"
        doc.saveas(source)
        response = upload(client, source.read_bytes(), "Floor.dxf")
        assert response.status_code == 201, response.text
        plan = response.json()
        assert plan["render"] == "dxf"
        preview = client.get("/drawing", params={"path": plan["path"]})
        assert preview.status_code == 200 and "<svg" in preview.text
        responses.append(drawings.dxf_frame(drawings._resolve(plan["path"])))
    assert responses[0] != responses[1]


def test_uploaded_and_dataset_plans_share_pagination(client, monkeypatch):
    existing = {"path": "data/existing.png"}
    monkeypatch.setattr(drawings, "_catalogue", lambda: [existing])
    plan = upload(client, image_bytes()).json()
    assert client.get("/drawings?limit=1").json() == {"total": 2, "drawings": [plan]}
    assert client.get("/drawings?limit=1&offset=1").json()["drawings"] == [existing]


def test_storage_failure_is_actionable(client):
    root = uploads.upload_root()
    root.parent.mkdir(parents=True)
    root.write_text("not a directory")
    assert upload(client, image_bytes()).status_code == 503


def test_delete_plan_upload(client):
    plan = upload(client, image_bytes()).json()
    assert client.delete("/drawings/upload", params={"path": plan["path"]}).status_code == 204
    assert client.get("/drawings").json()["total"] == 0
    assert client.delete("/drawings/upload", params={"path": plan["path"]}).status_code == 404
