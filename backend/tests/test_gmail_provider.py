"""
Unit tests for GmailProvider helper functions.
No real OAuth or network calls — tests only the pure helper logic.
"""

from datetime import datetime, timezone


class TestBuildQueryString:
    def test_date_range_only(self):
        from app.providers.gmail import _build_query_string
        from app.providers.base import ProviderQuery

        q = ProviderQuery(
            after=datetime(2023, 1, 1, tzinfo=timezone.utc),
            before=datetime(2026, 6, 11, tzinfo=timezone.utc),
            subject_any=[],
            category_purchases=False,
        )
        qs = _build_query_string(q)
        assert "after:2023/01/01" in qs
        assert "before:2026/06/11" in qs

    def test_category_purchases(self):
        from app.providers.gmail import _build_query_string
        from app.providers.base import ProviderQuery

        q = ProviderQuery(
            after=None,
            before=None,
            subject_any=[],
            category_purchases=True,
        )
        qs = _build_query_string(q)
        assert "category:purchases" in qs

    def test_subject_keywords_joined_with_or(self):
        from app.providers.gmail import _build_query_string
        from app.providers.base import ProviderQuery

        q = ProviderQuery(
            after=None,
            before=None,
            subject_any=["order", "receipt", "invoice"],
            category_purchases=False,
        )
        qs = _build_query_string(q)
        assert "subject:" in qs
        assert "order" in qs
        assert "receipt" in qs
        assert "invoice" in qs

    def test_category_and_subjects_are_or_grouped(self):
        from app.providers.gmail import _build_query_string
        from app.providers.base import ProviderQuery

        q = ProviderQuery(
            after=None,
            before=None,
            subject_any=["order"],
            category_purchases=True,
        )
        qs = _build_query_string(q)
        # Both should be inside a single OR group
        assert "category:purchases OR" in qs or "OR category:purchases" in qs

    def test_no_category_no_subjects_produces_no_or_group(self):
        from app.providers.gmail import _build_query_string
        from app.providers.base import ProviderQuery

        q = ProviderQuery(
            after=datetime(2024, 1, 1, tzinfo=timezone.utc),
            before=None,
            subject_any=[],
            category_purchases=False,
        )
        qs = _build_query_string(q)
        assert "category:" not in qs
        assert "subject:" not in qs


class TestWalkMimeParts:
    def test_simple_text_plain(self):
        from app.providers.gmail import _walk_parts

        payload = {
            "mimeType": "text/plain",
            "body": {"data": _b64("Hello plain text")},
        }
        text, html = _walk_parts(payload)
        assert text == "Hello plain text"
        assert html is None

    def test_simple_text_html(self):
        from app.providers.gmail import _walk_parts

        payload = {
            "mimeType": "text/html",
            "body": {"data": _b64("<p>Hello HTML</p>")},
        }
        text, html = _walk_parts(payload)
        assert text is None
        assert html == "<p>Hello HTML</p>"

    def test_multipart_alternative(self):
        from app.providers.gmail import _walk_parts

        payload = {
            "mimeType": "multipart/alternative",
            "body": {},
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _b64("Plain version")},
                },
                {
                    "mimeType": "text/html",
                    "body": {"data": _b64("<p>HTML version</p>")},
                },
            ],
        }
        text, html = _walk_parts(payload)
        assert text == "Plain version"
        assert html == "<p>HTML version</p>"

    def test_deeply_nested_multipart(self):
        from app.providers.gmail import _walk_parts

        payload = {
            "mimeType": "multipart/mixed",
            "body": {},
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "body": {},
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "body": {"data": _b64("Nested plain")},
                        }
                    ],
                }
            ],
        }
        text, html = _walk_parts(payload)
        assert text == "Nested plain"

    def test_empty_payload_returns_none_none(self):
        from app.providers.gmail import _walk_parts

        text, html = _walk_parts({"mimeType": "multipart/mixed", "body": {}})
        assert text is None
        assert html is None


class TestExtractImageSrcs:
    def test_extracts_img_srcs(self):
        from app.providers.gmail import _extract_image_srcs

        html = '<html><body><img src="https://cdn.zara.com/img1.jpg"><img src="https://cdn.zara.com/img2.jpg"></body></html>'
        srcs = _extract_image_srcs(html)
        assert len(srcs) == 2
        assert "https://cdn.zara.com/img1.jpg" in srcs

    def test_skips_imgs_without_src(self):
        from app.providers.gmail import _extract_image_srcs

        html = '<html><body><img alt="logo"><img src="https://cdn.zara.com/img.jpg"></body></html>'
        srcs = _extract_image_srcs(html)
        assert len(srcs) == 1

    def test_empty_html_returns_empty_list(self):
        from app.providers.gmail import _extract_image_srcs

        assert _extract_image_srcs("") == []


def _b64(text: str) -> str:
    import base64

    return base64.urlsafe_b64encode(text.encode()).decode()
