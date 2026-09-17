from urllib.parse import urlsplit
import httpx

from .config import AppError


class Paperless:
    def __init__(self, settings, client=None):
        self.settings = settings
        self.client = client or httpx.Client(base_url=settings.paperless_url, timeout=30,
                                            follow_redirects=False)

    def request(self, method, path, *, body=None, params=None):
        # Follow pagination paths only against our configured server.
        parsed = urlsplit(path)
        path = parsed.path + ("?" + parsed.query if parsed.query else "")
        if not path.startswith("/api/"):
            raise AppError("paperless_path", "Unexpected Paperless API path.")
        try:
            response = self.client.request(method, path, json=body, params=params,
                headers={"Authorization": "Token " + self.settings.paperless_token,
                         "Accept": "application/json; version=9"})
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as error:
            raise AppError("paperless_http", f"Paperless returned HTTP {error.response.status_code}.") from None
        except (httpx.HTTPError, ValueError):
            raise AppError("paperless_connection", "Paperless request did not complete. Check its connection.") from None

    def login(self, username, password):
        try:
            response = self.client.post("/api/token/", json={"username": username, "password": password})
            return response.json().get("token", "") if response.status_code == 200 else ""
        except (httpx.HTTPError, ValueError):
            return ""

    def all(self, kind):
        path = f"/api/{kind}/?page_size=100"
        rows, visited = [], set()
        while path:
            if path in visited or len(visited) >= 100:
                raise AppError("pagination", "Paperless pagination exceeded its limit.")
            visited.add(path)
            page = self.request("GET", path)
            rows.extend(page["results"])
            path = page.get("next")
        return rows

    def taxonomy(self):
        return {"tags": self.all("tags"), "types": self.all("document_types")}

    def document(self, doc_id):
        return self.request("GET", f"/api/documents/{int(doc_id)}/")

    def documents(self, page=1, query="", tag_id=None):
        params = {"page": page, "page_size": 25, "ordering": "-added"}
        if query:
            params["query"] = query
        if tag_id:
            params["tags__id__all"] = int(tag_id)
        return self.request("GET", "/api/documents/", params=params)

    def file(self, doc_id):
        try:
            with self.client.stream("GET", f"/api/documents/{int(doc_id)}/download/",
                params={"original": "true"},
                headers={"Authorization": "Token " + self.settings.paperless_token}) as response:
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > self.settings.max_file_bytes:
                        raise AppError("file_too_large", "The scan exceeds the 20 MB vision limit.")
                    chunks.append(chunk)
                return b"".join(chunks), response.headers.get("content-type", "").split(";")[0]
        except httpx.HTTPError:
            raise AppError("download_failed", "Could not download the original document for vision.") from None

    def patch(self, doc_id, values):
        if not set(values) <= {"title", "document_type"}:
            raise AppError("invalid_write", "Unsupported metadata change.")
        return self.request("PATCH", f"/api/documents/{int(doc_id)}/", body=values)

    def add_tags(self, doc_id, ids):
        return self.request("POST", "/api/documents/bulk_edit/", body={
            "documents": [doc_id], "method": "modify_tags",
            "parameters": {"add_tags": sorted(set(ids)), "remove_tags": []}})

    def create_tag(self, name):
        return self.request("POST", "/api/tags/", body={"name": name, "matching_algorithm": 0})
