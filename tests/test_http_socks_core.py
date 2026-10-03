from xrayui.core.profiles import Profile


def test_profile_is_valid_http_socks():
    p = Profile(protocol="http", address="1.2.3.4", port=8080, security="none")
    assert p.is_valid()

    p.security = "tls"
    assert p.is_valid()

    p.security = ""
    assert p.is_valid()

    p.security = "reality"
    assert not p.is_valid()

    p = Profile(protocol="socks", address="1.2.3.4", port=1080, security="none")
    assert p.is_valid()

    p.security = ""
    assert p.is_valid()

    p.security = "tls"
    assert not p.is_valid()

    p = Profile(protocol="http", address="", port=8080)
    assert not p.is_valid()

    p = Profile(protocol="http", address="1.2.3.4", port=0)
    assert not p.is_valid()

    p = Profile(protocol="http", address="1.2.3.4", port=65536)
    assert not p.is_valid()

    # bool is rejected for port
    p = Profile(protocol="http", address="1.2.3.4", port=True)
    assert not p.is_valid()

def test_profile_from_dict_username():
    # old profile dict without username
    old_data = {"protocol": "http", "address": "1.2.3.4", "port": 8080, "id": "pass"}
    p = Profile.from_dict(old_data)
    assert p.username == ""
    assert p.id == "pass"

    # new profile dict with username
    new_data = {"protocol": "http", "address": "1.2.3.4", "port": 8080, "username": "user", "id": "pass"}
    p = Profile.from_dict(new_data)
    assert p.username == "user"
    assert p.id == "pass"

    # round trip
    p_dict = p.to_dict()
    assert p_dict["username"] == "user"
    assert p_dict["id"] == "pass"
