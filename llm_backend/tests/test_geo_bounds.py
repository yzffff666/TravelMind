from app.services.geo_bounds import destination_bounds, is_coord_within_destination


def test_domestic_city_bounds_reject_obvious_cross_city_poi():
    assert destination_bounds("上海 3天 文化") is not None
    assert is_coord_within_destination("上海", 31.2304, 121.4737)
    assert not is_coord_within_destination("上海", 35.6586, 139.7454)


def test_hong_kong_macau_and_san_francisco_bounds():
    assert is_coord_within_destination("香港", 22.3027, 114.1772)
    assert not is_coord_within_destination("香港", 22.1987, 113.5439)

    assert is_coord_within_destination("澳门", 22.1987, 113.5439)
    assert not is_coord_within_destination("澳门", 22.5431, 114.0579)

    assert is_coord_within_destination("San Francisco", 37.7749, -122.4194)
    assert not is_coord_within_destination("旧金山", 34.0522, -118.2437)
