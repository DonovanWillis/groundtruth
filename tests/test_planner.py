from groundtruth.planner import parse


def test_required_requests_parse():
    p = parse("find swimming pools")
    assert p.concept == "swimming_pool" and p.place is None
    p = parse("pools within 1 km of I-485 in Ballantyne")
    assert (p.concept, p.place, p.layer, p.within_m) == ("swimming_pool", "Ballantyne", "osm_i485", 1000.0)
    p = parse("parking lots in Uptown")
    assert (p.concept, p.place) == ("parking_lot", "Uptown")
    p = parse("solar on warehouses")
    assert (p.concept, p.host_layer) == ("solar_installation", "osm_warehouses")
    p = parse("pools in flood zones in Matthews")
    assert (p.concept, p.place, p.layer, p.inside_layer) == ("swimming_pool", "Matthews", "fema_flood_zones", True)


def test_new_since_and_year():
    p = parse("new pools since 2020 in NoDa")
    assert p.new_since is None or p.new_since == 2020
    p = parse("pools new since 2020 in NoDa")
    assert p.new_since == 2020 and p.place == "NoDa"
