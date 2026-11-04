import open_scenario_veloview as osv


def test_pcap_name_for_first_take_has_no_suffix():
    assert osv.pcap_name_for_take("A1", 1) == "A1"


def test_pcap_name_for_later_takes_has_numeric_suffix():
    assert osv.pcap_name_for_take("A1", 2) == "A1_2"
    assert osv.pcap_name_for_take("A1", 4) == "A1_4"


def test_pcap_name_for_take_zero_or_negative_defaults_to_unsuffixed():
    # take<=1 (e.g. an unset/zero value) should behave like the first take,
    # matching pcap_to_pcd's unsuffixed naming for the first extraction.
    assert osv.pcap_name_for_take("D1", 0) == "D1"
    assert osv.pcap_name_for_take("D1", 1) == "D1"
