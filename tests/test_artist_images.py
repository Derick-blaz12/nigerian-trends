import io
import os

import pytest
from PIL import Image

from app.services import artist_service
from app.storage import LocalStorage

URL = "/api/v1/admin/artists"


def upload(client, artist_id, data, filename="cover.png"):
    return client.post(
        f"{URL}/{artist_id}/image",
        data={"image": (io.BytesIO(data), filename)},
        content_type="multipart/form-data",
    )


def stored_files(app):
    return [name for _, _, files in os.walk(app.config["UPLOAD_DIR"]) for name in files]


def new_artist():
    return artist_service.create_artist({"name": "Tems"})


def test_upload_stores_a_resized_jpeg(app, admin_client, client, make_image):
    artist = new_artist()

    response = upload(admin_client, artist.id, make_image(size=(3000, 2000)))
    url = response.get_json()["data"]["image_url"]

    assert response.status_code == 200
    assert url.startswith("/media/artists/") and url.endswith(".jpg")
    served = client.get(url)
    assert served.status_code == 200
    assert served.mimetype == "image/jpeg"
    image = Image.open(io.BytesIO(served.data))
    assert image.format == "JPEG"
    assert max(image.size) == 1200


def test_transparent_png_is_flattened_onto_white(app, admin_client, client, make_image):
    artist = new_artist()
    data = make_image(size=(300, 300), mode="RGBA", color=(255, 0, 0, 0))

    url = upload(admin_client, artist.id, data).get_json()["data"]["image_url"]

    image = Image.open(io.BytesIO(client.get(url).data))
    assert image.mode == "RGB"
    assert all(channel > 240 for channel in image.getpixel((10, 10)))


def test_rejects_files_that_are_not_images(admin_client):
    artist = new_artist()
    response = upload(admin_client, artist.id, b"just some text", "evil.jpg")
    assert response.status_code == 422
    assert "image" in response.get_json()["error"]["details"]


def test_rejects_unsupported_image_formats(admin_client, make_image):
    artist = new_artist()
    response = upload(admin_client, artist.id, make_image(fmt="GIF"), "anim.gif")
    assert response.status_code == 422


def test_rejects_images_that_are_too_small(admin_client, make_image):
    artist = new_artist()
    response = upload(admin_client, artist.id, make_image(size=(100, 100)))
    assert response.status_code == 422


def test_rejects_oversized_uploads(app, admin_client, make_image):
    artist = new_artist()
    app.config["MAX_IMAGE_BYTES"] = 100
    response = upload(admin_client, artist.id, make_image())
    assert response.status_code == 413
    assert response.get_json()["error"]["code"] == "payload_too_large"
    assert stored_files(app) == []


def test_requires_an_image_field(admin_client):
    artist = new_artist()
    response = admin_client.post(
        f"{URL}/{artist.id}/image", data={"other": "x"}, content_type="multipart/form-data"
    )
    assert response.status_code == 422


def test_replacing_an_image_removes_the_old_file(app, admin_client, make_image):
    artist = new_artist()
    first = upload(admin_client, artist.id, make_image()).get_json()["data"]["image_url"]
    second = upload(admin_client, artist.id, make_image()).get_json()["data"]["image_url"]

    assert first != second
    assert stored_files(app) == [os.path.basename(second)]


def test_removing_an_image(app, admin_client, make_image):
    artist = new_artist()
    upload(admin_client, artist.id, make_image())

    response = admin_client.delete(f"{URL}/{artist.id}/image")

    assert response.status_code == 200
    assert response.get_json()["data"]["image_url"] is None
    assert stored_files(app) == []


def test_storage_refuses_paths_outside_its_folder(tmp_path):
    storage = LocalStorage(str(tmp_path / "root"), "/media")
    with pytest.raises(ValueError):
        storage.save("../escape.jpg", b"x")
    assert not (tmp_path / "escape.jpg").exists()