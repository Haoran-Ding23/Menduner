"""A region name is not a venue, and must never become one.

The official-article extractor reads the leading 单位： prefix of a title as the venue. A
city-wide event is titled 太仓市:捡个秋天·太仓漫游季, so the prefix is an administrative
region rather than a place. Storing that as a venue row is wrong twice over:

  * it splits a region-wide event off as if it had happened at one location, and
  * it invites a coordinate, because AMap does return a 太仓市 POI - the city centre.

Pinning region-wide demand to a city-centre point would put it on the map as a real venue
and distort every distance calculation that reads it. This was found on live data: the
coordinate enrichment tool proposed marking 太仓市 as VERIFIED at the city centre.

``crawler.pipeline`` applies ``is_region_name`` before creating a venue row, so the guard
these tests pin is the one the pipeline actually calls.
"""
from crawler.venue_duplicates import is_region_name


def test_a_city_name_is_a_region_and_a_museum_is_not():
    assert is_region_name("太仓市")
    assert is_region_name("姑苏区")
    assert is_region_name("江苏省")
    assert is_region_name("木渎镇")
    assert is_region_name("双塔街道")
    assert not is_region_name("太仓市博物馆")
    assert not is_region_name("太仓名人馆")
    assert not is_region_name("苏州文化艺术中心")


def test_an_embedded_region_token_does_not_make_a_venue_a_region():
    """The suffix must end the name, or every theatre in a district would be caught.

    苏州市体育中心, 苏州工业园区文化馆 and 太仓市博物馆 all begin with or contain a region
    token and are all real venues. An earlier, looser rule matched names *containing* a
    region token, which is what produced the false-positive merge proposals.
    """
    for name in ("苏州市体育中心", "苏州工业园区文化馆", "太仓市博物馆", "昆山文化艺术中心"):
        assert not is_region_name(name), name


def test_the_region_name_that_appears_on_live_data_is_caught():
    """太仓市 is the one bare region name the live database holds.

    It came from a single crawl of the Suzhou festival calendar and carried one region-wide
    event (太仓市:捡个秋天·太仓漫游季) and no coordinate.
    """
    assert is_region_name("太仓市")


def test_scenic_areas_and_old_towns_are_places_not_regions():
    """These rows look similar but are real places with real geometry.

    周庄古镇, 黎里古镇 and 天平山景区 already carry verified coordinates on the live database,
    so treating them as regions would have discarded usable geography. 周庄镇 (no 古) is a
    genuine administrative town and must still be caught.
    """
    for name in ("周庄古镇", "黎里古镇", "震泽古镇", "天平山景区", "金鸡湖景区",
                 "盘门景区", "大阳山景区", "尚湖风景区", "香山景区", "虎丘山风景名胜区"):
        assert not is_region_name(name), name
    assert is_region_name("周庄镇"), "the administrative town is still a region"


def test_the_pipeline_module_applies_the_guard():
    """The guard is only worth having if the writer uses it.

    The check runs inside ``run_pipeline``'s publish loop, so importing the module and
    confirming it resolves the same predicate is the cheapest way to catch a refactor that
    silently drops the call.
    """
    import crawler.pipeline as pipeline

    assert pipeline.is_region_name is is_region_name
