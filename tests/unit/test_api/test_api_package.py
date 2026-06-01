from __future__ import annotations

import pytest


def test_api_package_lazily_exports_create_app():
    import qaplatform.api as api
    from qaplatform.main import create_app

    assert api.create_app is create_app


def test_api_package_unknown_attribute_raises_attribute_error():
    import qaplatform.api as api
    from qaplatform.main import create_app

    with pytest.raises(AttributeError) as exc_info:
        getattr(api, "missing")

    assert exc_info.value.args == ("module 'qaplatform.api' has no attribute 'missing'",)
    assert api.create_app is create_app
