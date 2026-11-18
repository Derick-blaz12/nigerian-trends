def test_pages_render_the_html_shell(client):
    for path in ["/artists/tems", "/songs/1", "/search"]:
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.mimetype == "text/html"
        assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_static_assets_are_served(client):
    assert client.get("/static/js/site.js").status_code == 200
    assert client.get("/static/css/site.css").status_code == 200

def test_news_and_dashboard_pages_render_the_html_shell(client):
    for path in ["/news", "/news/1", "/admin/editorial"]:
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.mimetype == "text/html"
        assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_dashboard_page_is_not_cached_or_indexed(client):
    response = client.get("/admin/editorial")
    assert response.headers["Cache-Control"] == "no-store"
    assert b"noindex" in response.data