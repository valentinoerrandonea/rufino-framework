from rufino.helpers import v1


def test_v1_version():
    assert v1.HELPER_VERSION == "1.0.0"


def test_v1_exposes_version_function():
    assert v1.helper_version() == "1.0.0"
