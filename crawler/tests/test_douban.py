"""Offline Douban Suzhou adapter checks. Synthetic fixtures through MockTransport only.

The 地点/时间 fixtures below are the REAL markup of ``https://www.douban.com/event/35866026/``
(server-rendered, captured 2026-10-13): the 地点 row is itemscope region/locality/street-address
spans whose concatenated text is the source's place line, and the 时间 row carries both the
human label ``10月17日 周六`` and the machine ``<time datetime="2026-10-17T16:00:00">``.

These tests pin the adapter's fail-closed contract. The crux is year resolution: Douban prints
``10月14日 周三`` largely without a year, so a date is accepted only from an explicit year-bearing
source field, or from a ``M月D日`` label whose own weekday claim selects exactly ONE candidate year
inside the bounded window (or is anchored to the explicit year the source printed on the other end
of the SAME interval). Everything else is rejected, no date is ever inferred from a publication
date, the crawl date or the ``?start`` offset, and no field is ever Verified because Douban is a
UGC/community aggregator.
"""
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
import pytest

from backend.database import connect
from crawler.extractor import extract
from crawler.http import PublicClient
from crawler.pipeline import run_pipeline
from crawler.schema import CollectedItem
from crawler.sources.community.douban import (
    DETAIL_PATH,
    HOST,
    LISTING_URL,
    DoubanSource,
    card_records,
    detail_record,
    douban_event,
    explicit_date,
    resolve_year,
    unlabelled_month_day,
    venue_from,
    weekday_name,
)

HOST_URL = 'https://' + HOST
TODAY = date(2026, 10, 13)  # the verified recon date; only used for deterministic probes
# A routable policy for the adapter tests. The live host serves a real 895-byte robots.txt with
# usable rules; `test_live_robots_rules_are_not_opted_out_of` pins that the strict default stays.
ROBOTS = 'User-agent: *\nDisallow: /search\nDisallow: /event/search\nDisallow: /forum/\n'
WEEKDAYS = '一二三四五六日'
HTML_HEADERS = {'Content-Type': 'text/html; charset=utf-8'}


# --------------------------------------------------------------------------------------
# Fixtures: the verified live shapes, reduced to the fields the adapter reads
# --------------------------------------------------------------------------------------

def eventwrap(*, event_id='35866026', name='苏州丨必打卡丨爆笑丨演出丨嘻哈壹笑堂相声专场',
              time_text='10月17日 周六 16:00 ~ 10月31日 周六 21:30',
              start='2026-10-17T16:00:00', end='2026-10-31T21:30:00',
              region='苏州', locality='姑苏区',
              address='嘻哈壹笑堂相声茶馆 平江街道大儒巷38号(近长发商场)',
              etype='喜剧-相声', provider='猫眼演出'):
    """The live ``div.eventwrap`` block. ``None`` drops the corresponding source span."""
    clock = ('<time itemprop="startDate" datetime="%s"></time>' % start) if start else ''
    finish = ('<time itemprop="endDate" datetime="%s"></time>' % end) if end else ''
    street = ('<span itemprop="street-address" class="micro-address">%s</span>' % address) \
        if address else ''
    place = ('<span itemprop="address" itemscope '
             'itemtype="http://data-vocabulary.org/Address" class="micro-address">%s%s%s</span>'
             % ('<span itemprop="region" class="micro-address">%s</span>' % region if region else '',
                '<span itemprop="locality" class="micro-address">%s</span>' % locality if locality else '',
                street))
    rows = [
        '<div class="event-detail"><span class="pl">时间:&nbsp;&nbsp;</span>'
        '<ul class="calendar-strs "><li class="calendar-str-item">%s</li></ul>%s%s'
        '<span style="color:red;">活动结束时间以实际活动为准</span></div>' % (time_text, clock, finish),
        '<div class="event-detail" itemprop="location" itemscope '
        'itemtype="http://data-vocabulary.org/Organization"><span class="pl" >地点:&nbsp;</span>'
        + place + '</div>',
    ]
    if etype:
        rows.append('<div class="event-detail"><span class="pl">类型:&nbsp;&nbsp;</span>'
                    '<a href="https://www.douban.com/location/suzhou/events/future-comedy" '
                    'itemprop="eventType">%s</a></div>' % etype)
    if provider:
        rows.append('<div class="event-detail" itemscope '
                    'itemtype="http://data-vocabulary.org/Organization">'
                    '<span class="pl">信息提供者:&nbsp;&nbsp;</span>'
                    '<a href="https://site.douban.com/307085/" target="_blank" '
                    'itemprop="name">%s</a></div>' % provider)
    return (
        '<div class="eventwrap" itemscope itemtype="http://data-vocabulary.org/Event">'
        '<div class="poster"><a href="https://img3.doubanio.com/pview/event_poster/raw/x.jpg">'
        '<img id="poster_img" itemprop="image" src="x.jpg" width="175" height="260"/></a></div>'
        '<div id="event-info"><div class="event-info">'
        '<h1 itemprop="summary">%s\n</h1>' % name
        + ''.join(rows)
        + '<div class="interest-attend"><span>7</span>人感兴趣</div>'
          '</div></div>'
          # The live page states its own event id here; the record is checked against it.
          '<div class="event-share" share-id="%s" data-mode="plain" data-count="10" '
          'data-object_kind="1011" data-object_id="%s" data-href="%s/event/%s/"></div>'
          '</div>' % (event_id, event_id, HOST_URL, event_id)
    )


def detail_html(**kwargs):
    return ('<!DOCTYPE html><html><head><title>%s_豆瓣</title></head><body>'
            '<div class="article">%s<div class="add-cal"></div></div></body></html>'
            % (kwargs.get('name', '苏州丨必打卡丨爆笑丨演出丨嘻哈壹笑堂相声专场'),
               eventwrap(**kwargs)))


def card_html(*, event_id='35866026', name='苏州丨必打卡丨爆笑丨演出丨嘻哈壹笑堂相声专场',
              time_text='时间： 10月17日 周六 16:00 ~ 10月31日 周六 21:30',
              start='2026-10-17T16:00:00', end='2026-10-31T21:30:00',
              place='苏州 姑苏区 嘻哈壹笑堂相声茶馆 平江街道大儒巷38号(近长发商场)'):
    """The live ``li.list-entry`` card shape (captured 2026-10-13)."""
    clock = '<time datetime="%s" itemprop="startDate"></time>' % start if start else ''
    finish = '<time datetime="%s" itemprop="endDate"></time>' % end if end else ''
    return (
        '<li class="list-entry" itemscope itemtype="http://data-vocabulary.org/Event">'
        '<div class="pic"><a href="%s/event/%s/"><img data-lazy="x.jpg" src="blank.gif"/></a></div>'
        '<div class="info"><div class="title">'
        '<a href="%s/event/%s/" itemprop="url" title="%s"><span itemprop="summary">%s</span></a>'
        '</div><ul class="event-meta">'
        '<li class="event-time"><span class="hidden-xs">时间：</span>%s%s%s</li>'
        '<li title="%s"><span class="hidden-xs">地点：</span>%s'
        '<meta content="%s" itemprop="location" itemscope=""/></li>'
        '<li class="fee"><span class="hidden-xs">费用：</span><strong>30.0元起</strong></li>'
        '<li><span class="meta-title">发起：</span>'
        '<a href="%s/location/people/161552261/" target="db-event-owner">猫眼演出</a></li>'
        '</ul><p class="counts"><span>8人感兴趣</span></p></div></li>'
        % (HOST_URL, event_id, HOST_URL, event_id, name, name, time_text, clock, finish,
           place, place, place, HOST_URL)
    )


def page_html(cards, total_pages=24):
    return (
        '<!DOCTYPE html><html><head><title>苏州近期同城活动_豆瓣</title></head><body>'
        '<div class="mod event-mod event-mod-1col"><div class="hd"></div>'
        '<ul class="events-list events-list-pic100 events-list-psmall">'
        + ''.join(cards)
        + '</ul><div class="paginator"><span class="thispage" data-total-page="%d">1</span>'
          '<a href="?start=10">2</a></div></div></body></html>' % total_pages
    )


def unique_future_date(weekday=None):
    """A future ``(date, weekday)`` that resolves to exactly one year in the bounded window."""
    for offset in range(1, 500):
        candidate = date.today() + timedelta(days=offset)
        label = WEEKDAYS[candidate.isoweekday() - 1]
        if weekday and label != weekday:
            continue
        if resolve_year(candidate.month, candidate.day, label) == candidate.isoformat():
            return candidate, label
    raise AssertionError('no unambiguous future date found')


def ambiguous_future_date():
    """A future ``(date, weekday)`` whose weekday claim fits two years in the window."""
    for offset in range(1, 500):
        candidate = date.today() + timedelta(days=offset)
        label = WEEKDAYS[candidate.isoweekday() - 1]
        if resolve_year(candidate.month, candidate.day, label) is None:
            return candidate, label
    raise AssertionError('no ambiguous future date found')


def chinese(date_value):
    return '%d月%d日' % (date_value.month, date_value.day)


def timing(*, start=None, end=None, start_time='10:00', end_time='12:00', text=None):
    """One coherent ``时间`` row for a test: label, start and end never disagree by accident."""
    start = start or date.today() + timedelta(days=3)
    end = start if end is None else end
    if text is None:
        text = '%s 周%s %s' % (chinese(start), WEEKDAYS[start.isoweekday() - 1], start_time)
        if end != start:
            text += ' ~ %s 周%s %s' % (chinese(end), WEEKDAYS[end.isoweekday() - 1], end_time)
    return dict(time_text=text, start=start.isoformat() + 'T' + start_time + ':00',
                end=(end.isoformat() + 'T' + end_time + ':00') if end else None)


def listing_client(handler):
    """A client with zero host spacing so the offline suite stays fast."""
    return PublicClient(transport=httpx.MockTransport(handler), interval=0, sleep=lambda n: None)


def item(raw, url=None, event_id='35866026', locator=None):
    """A collected item whose key/locator/URL all agree with the detail page it carries."""
    url = url or (HOST_URL + '/event/' + event_id + '/')
    page_id = urlparse(url).path.strip('/').split('/')[-1]
    return CollectedItem(
        item_key='douban-event-' + page_id,
        original_url=url,
        source_name='豆瓣同城苏州',
        crawl_time=datetime.now(timezone.utc),
        raw_content=raw,
        extractor='douban_event',
        locator=locator if locator is not None else page_id,
    )


# --------------------------------------------------------------------------------------
# Pure extraction: explicit years, provenance, never-Verified
# --------------------------------------------------------------------------------------

def test_live_shaped_detail_extracts_every_contract_field_with_provenance():
    raw = detail_html()
    event = douban_event(item(raw))
    assert event['event_name'] == '苏州丨必打卡丨爆笑丨演出丨嘻哈壹笑堂相声专场'
    assert event['start_date'] == '2026-10-17' and event['end_date'] == '2026-10-31'
    assert event['venue'] == '嘻哈壹笑堂相声茶馆'
    assert event['location'] == '苏州 姑苏区 嘻哈壹笑堂相声茶馆 平江街道大儒巷38号(近长发商场)'
    assert event['organizer'] == '猫眼演出'
    assert event['category'] == 'culture' and event['city'] == '苏州'
    assert event['venue_id'] is None and event['district_id'] is None
    assert event['source_url'] == HOST_URL + '/event/35866026/'
    for field, claim in event['field_evidence'].items():
        assert 0 <= claim['confidence'] <= 1
        assert claim['method']
        assert claim['status'] in ('Unverified', 'Missing', 'Needs Review'), field
        assert claim['status'] != 'Verified', field
        if claim['status'] == 'Missing':
            assert claim['confidence'] == 0.0
        else:
            assert claim['snippet'], field
    evidence = event['field_evidence']
    assert evidence['start_date']['method'] == 'explicit_itemprop_startDate_year'
    assert evidence['end_date']['method'] == 'explicit_itemprop_endDate_year'
    assert 'itemscope startDate.datetime=2026-10-17T16:00:00' in evidence['start_date']['snippet']
    assert '时间=10月17日 周六 16:00 ~ 10月31日 周六 21:30' in evidence['start_date']['snippet']
    assert evidence['venue']['snippet'] == (
        'itemprop street-address=嘻哈壹笑堂相声茶馆 平江街道大儒巷38号(近长发商场)')
    assert evidence['location']['snippet'] == (
        '地点:苏州 姑苏区 嘻哈壹笑堂相声茶馆 平江街道大儒巷38号(近长发商场)')
    assert evidence['organizer']['snippet'] == '信息提供者:猫眼演出'
    assert evidence['source_url']['snippet'] == HOST_URL + '/event/35866026/'


def test_yearless_label_is_resolved_by_its_own_weekday_claim_and_recorded_as_such():
    target, weekday = unique_future_date()
    label = '%s 周%s 19:30-21:00' % (chinese(target), weekday)
    event = douban_event(item(detail_html(time_text=label, start=None, end=None)))
    assert event['start_date'] == target.isoformat()
    assert event['end_date'] is None
    evidence = event['field_evidence']['start_date']
    assert evidence['status'] == 'Needs Review'
    assert evidence['method'].startswith('M月D日 + source weekday claim')
    assert label in evidence['snippet']


def test_yearless_end_date_is_anchored_to_the_explicit_year_of_the_same_interval():
    """Live case (event 37874621): ``08月25日 周二 09:00-20:00 ~ 2026年11月02日 周一 20:00``.

    The start is printed WITHOUT a year while the end carries one, so the explicit year printed
    on the other end of the SAME interval is the anchor for the year-less start.
    """
    anchored = date.today() + timedelta(days=60)
    label = WEEKDAYS[anchored.isoweekday() - 1]
    raw = detail_html(time_text='%s 周%s 09:00 ~ %d年%d月%d日 周%s 17:00'
                      % (chinese(anchored), label, anchored.year, anchored.month,
                         anchored.day, label),
                      start=None, end=anchored.isoformat() + 'T17:00:00')
    event = douban_event(item(raw))
    assert event['start_date'] == anchored.isoformat()
    assert event['end_date'] == anchored.isoformat()
    evidence = event['field_evidence']['start_date']
    assert evidence['method'].startswith('M月D日 + source weekday claim')
    assert anchored.isoformat() not in evidence['snippet']  # the year came off the other end
    # Both ends year-less and weekday-ambiguous must still be refused outright.
    ambiguous, ambiguous_weekday = ambiguous_future_date()
    with pytest.raises(ValueError, match='never guessed|does not select'):
        douban_event(item(detail_html(time_text='%s 周%s 09:00 ~ %s 周%s 17:00'
                                      % (chinese(ambiguous), ambiguous_weekday,
                                         chinese(ambiguous), ambiguous_weekday),
                                      start=None, end=None)))


def test_weekday_claim_naming_a_different_year_than_the_explicit_date_is_rejected():
    target, weekday = unique_future_date()
    other = WEEKDAYS[(WEEKDAYS.index(weekday) + 3) % 7]
    raw = detail_html(time_text='%s 周%s 19:30-21:00' % (chinese(target), other),
                      start=target.isoformat() + 'T19:30:00',
                      end=target.isoformat() + 'T21:00:00')
    with pytest.raises(ValueError, match='rejected instead of preferring') as failure:
        douban_event(item(raw))
    assert target.isoformat() in str(failure.value)


@pytest.mark.parametrize('time_text', [
    '10月14日 20:00-22:00',
    '10月14日 20:00-22:00 活动结束时间以实际活动为准',
])
def test_no_weekday_and_no_year_is_rejected_instead_of_guessed(time_text):
    assert resolve_year(10, 14, None) is None
    with pytest.raises(ValueError, match='never guessed|does not select'):
        douban_event(item(detail_html(time_text=time_text, start=None, end=None)))


def test_ambiguous_year_across_the_bounded_window_is_rejected():
    """Two candidate years satisfying the same weekday claim must never be resolved."""
    target, weekday = ambiguous_future_date()
    assert resolve_year(target.month, target.day, weekday) is None
    with pytest.raises(ValueError, match='never guessed|does not select'):
        douban_event(item(detail_html(time_text='%s 周%s 10:00-12:00' % (chinese(target), weekday),
                                      start=None, end=None)))


def test_publication_date_and_scrape_date_are_never_substituted_for_an_event_date():
    raw = detail_html(time_text='10月14日 20:00-22:00', start=None, end=None).replace(
        '<title>', '<meta name="PubDate" content="2026-10-13"/>'
        '<time itemprop="datePublished" datetime="2026-10-13T09:00:00"></time><title>')
    with pytest.raises(ValueError, match='never guessed'):
        douban_event(item(raw))


def test_place_line_without_a_venue_name_publishes_no_venue_but_keeps_the_event():
    """A page whose place line names only a street or landmark is published with venue=null.

    It is NOT rejected: the event has an explicit location, and dropping it would lose a real
    booked demand signal. The street/landmark is never promoted to a venue name.
    """
    raw = detail_html(locality='吴中区', address='科技路 1088号')
    assert venue_from('科技路 1088号', '苏州') is None
    event = douban_event(item(raw))
    assert event['venue'] is None
    assert event['location']
    claim = event['field_evidence']['venue']
    assert claim['status'] == 'Missing' and claim['confidence'] == 0.0
    assert claim['method'] == 'absent_venue_name_in_source_place_line'
    assert 'not promoted to a venue' in claim['snippet']

    landmark = douban_event(item(detail_html(locality='吴中区', address='大治桥地铁站')))
    assert landmark['venue'] is None
    assert landmark['location']


@pytest.mark.parametrize('change, match', [
    ({'region': None, 'locality': None, 'address': None}, 'place line'),
    ({'region': '北京', 'locality': '朝阳区', 'address': '测试大剧院 朝阳路1号'}, 'Suzhou'),
    ({'region': None, 'locality': None, 'address': '杭州 西湖区 测试大剧院 文一路1号'}, 'Suzhou'),
])
def test_missing_place_or_wrong_city_is_rejected(change, match):
    with pytest.raises(ValueError, match=match):
        douban_event(item(detail_html(**change)))


def test_a_type_label_that_is_absent_defaults_to_others_instead_of_guessing():
    raw = detail_html(etype=None, name='苏州测试活动')
    assert 'itemprop="eventType"' not in raw
    event = douban_event(item(raw))
    assert event['category'] == 'others'
    assert 'defaults_to_others' in event['field_evidence']['category']['snippet']


def test_an_ended_record_is_rejected_while_a_long_running_one_is_kept():
    past = date.today() - timedelta(days=400)
    with pytest.raises(ValueError, match='already ended|bounded window'):
        douban_event(item(detail_html(**timing(start=past))))
    started = date.today() - timedelta(days=200)
    still_running = date.today() + timedelta(days=60)
    label = ('%d年%d月%d日 ~ %d年%d月%d日' % (started.year, started.month, started.day,
                                             still_running.year, still_running.month,
                                             still_running.day))
    event = douban_event(item(detail_html(**timing(start=started, end=still_running,
                                                   text=label))))
    assert event['start_date'] == started.isoformat()
    assert event['end_date'] == still_running.isoformat()
    assert event['field_evidence']['start_date']['method'] == 'explicit_itemprop_startDate_year'


def test_an_interval_that_runs_backwards_is_rejected():
    """The source printing an end before its start is an interval failure, not a date guess."""
    from crawler.sources.community.douban import interval_dates
    later = date.today() + timedelta(days=14)
    earlier = date.today() + timedelta(days=7)
    label = '%s 周%s 10:00 ~ %s 周%s 12:00' % (
        chinese(later), WEEKDAYS[later.isoweekday() - 1],
        chinese(earlier), WEEKDAYS[earlier.isoweekday() - 1])
    with pytest.raises(ValueError, match='precedes'):
        interval_dates(later.isoformat(), earlier.isoformat(), label, today=date.today())
    with pytest.raises(ValueError, match='precedes'):
        douban_event(item(detail_html(**timing(start=later, end=earlier, text=label))))


def test_detail_shape_change_fails_closed_without_inventing_a_record():
    shell = '<!DOCTYPE html><html><body><h1>苏州测试话剧</h1><p>10月14日 周三</p></body></html>'
    with pytest.raises(ValueError, match='unverified page state'):
        douban_event(item(shell))
    # The Event scope survives but the labelled rows are gone: no label, no event.
    no_rows = ('<div class="eventwrap" itemscope itemtype="http://data-vocabulary.org/Event">'
               '<div class="event-info"><h1 itemprop="summary">苏州测试话剧</h1>'
               '<p>10月14日 周三 20:00-22:00</p></div></div>')
    with pytest.raises(ValueError, match='never guessed'):
        douban_event(item(no_rows))
    blocked = detail_html().replace('<div class="event-info">',
                                    '<div class="event-info">请先登录后查看')
    with pytest.raises(ValueError, match='access wall'):
        douban_event(item(blocked))


def test_locator_must_match_the_detail_page_event_id():
    raw = detail_html()
    url = HOST_URL + '/event/38048360/'
    with pytest.raises(ValueError, match='does not match'):
        douban_event(item(raw, url=url, locator='38048360'))
    with pytest.raises(ValueError, match='does not match'):
        douban_event(item(raw, url=url))


def test_detail_page_url_must_be_an_approved_public_event_page():
    raw = detail_html()
    for url in (HOST_URL + '/event/35866026', HOST_URL + '/event/search?query=x',
                'http://' + HOST + '/event/35866026/', 'https://evil.test/event/35866026/'):
        with pytest.raises(ValueError, match='approved public detail page'):
            douban_event(item(raw, url=url))


def test_region_and_locality_spans_together_form_the_source_place_line():
    """The live region/locality spans carry '苏州'/'姑苏区', and the row text is their join."""
    record = detail_record(detail_html(), HOST_URL + '/event/35866026/')
    assert record['city'] == '苏州'
    assert record['district'] == '姑苏区'
    assert record['place'] == '苏州 姑苏区 嘻哈壹笑堂相声茶馆 平江街道大儒巷38号(近长发商场)'
    event = douban_event(item(detail_html()))
    assert event['city'] == '苏州'
    assert event['venue'] == '嘻哈壹笑堂相声茶馆'
    assert event['field_evidence']['city']['snippet'] == 'itemprop region=苏州'


# --------------------------------------------------------------------------------------
# Year resolution unit contract
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize('month, day, weekday, expected', [
    (10, 14, '三', '2026-10-14'),
    (10, 14, None, None),
    (10, 17, '六', '2026-10-17'),
    (10, 17, '一', None),
    (12, 31, '四', '2026-12-31'),
    (9, 20, '日', None),
    (2, 30, '一', None),
])
def test_resolve_year_contract(month, day, weekday, expected):
    assert resolve_year(month, day, weekday, today=TODAY) == expected


def test_resolution_window_is_bounded_and_forward_only():
    assert resolve_year(5, 15, '六', today=TODAY) == '2027-05-15'
    assert resolve_year(10, 10, '六', today=TODAY) is None  # behind the window
    assert resolve_year(10, 10, '六', today=TODAY, max_drift_days=4) == '2026-10-10'


@pytest.mark.parametrize('value, expected', [
    ('2026-10-14T20:00:00', '2026-10-14'),
    ('2026-10-14 20:00', '2026-10-14'),
    ('2026-10-14', '2026-10-14'),
    ('2026年10月14日', None),
    ('10月14日 周三', None),
    ('10-14', None),
    ('', None),
    (None, None),
    ('2026-13-01', None),
    ('2026-02-30', None),
])
def test_explicit_date_requires_a_complete_real_source_value(value, expected):
    assert explicit_date(value) == expected


@pytest.mark.parametrize('value, weekday, month_day', [
    ('时间: 10月17日 周六 16:00 ~ 10月31日 周六 21:30', '六', (10, 17)),
    ('时间: 10月14日 周三 20:00-22:00', '三', (10, 14)),
    ('时间: 10月14日周三20:00-22:00', '三', (10, 14)),
    ('时间: 10月17日 星期六 19:30', '六', (10, 17)),
    ('时间: 10月17日 16:00 ~ 10月31日 21:30', None, (10, 17)),
    ('时间: 11月01日 周日 20:40', '日', (11, 1)),
    ('', None, None),
    (None, None, None),
])
def test_readable_label_parsing(value, weekday, month_day):
    assert weekday_name(value) == weekday
    assert unlabelled_month_day(value) == month_day


@pytest.mark.parametrize('value', [
    '时间: 2026年10月04日 ~ 2026年12月27日 每周日,六 14:00 - 18:00',
    '时间: 2026年08月25日-2026年11月02日',
    '时间: 2026年10月11日 ~ 2026年12月15日 每天 19:00 - 20:30',
    '时间: 09月20日 周日 00:00 ~ 2027年08月29日 周日 23:59',
    '时间: 08月25日 周二 09:00-20:00 ~ 2026年11月02日 周一 20:00',
])
def test_a_label_that_prints_any_explicit_year_is_not_a_year_less_claim(value):
    """An explicit year anywhere in the label is enough: this path must never add a second one."""
    assert unlabelled_month_day(value) is None


@pytest.mark.parametrize('address, city, expected', [
    # the live street-address span holds only the venue + street, and the 地点 line holds all
    ('嘻哈壹笑堂相声茶馆 平江街道大儒巷38号(近长发商场)', '苏州', '嘻哈壹笑堂相声茶馆'),
    ('慎德堂评弹茶馆-平江路店 平江街道南石子街11号', '苏州', '慎德堂评弹茶馆-平江路店'),
    ('印象百戏-苏州状元府 钮家巷3号', '苏州', '印象百戏-苏州状元府'),
    ('苏州市第二工人文化宫 玉成路219号', '苏州', '苏州市第二工人文化宫'),
    ('橙天嘉禾剧场 引黛街9号', '苏州', '橙天嘉禾剧场'),
    # a span that carries the whole place line resolves through the same rule
    ('苏州 姑苏区 嘻哈壹笑堂相声茶馆 平江街道大儒巷38号(近长发商场)', '苏州', '嘻哈壹笑堂相声茶馆'),
    ('苏州 吴中区 科技路 1088号', '苏州', None),
    ('苏州 吴中区 星湖街 12号', '苏州', None),
    ('苏州 吴中区 大治桥地铁站', '苏州', None),
    ('苏州 吴中区 万达广场(苏州吴中店)', '苏州', None),
    ('苏州 姑苏区 东环路711 智慧交通3楼311室', '苏州', None),
    ('大治桥地铁站', None, None),
    ('', None, None),
    (None, None, None),
])
def test_venue_is_the_sources_own_named_place_or_nothing(address, city, expected):
    assert venue_from(address, city) == expected


# --------------------------------------------------------------------------------------
# Adapter collection: paging, caps, stale cards, policy, and never-Verified
# --------------------------------------------------------------------------------------

def test_listing_discovery_uses_only_approved_routes_and_the_sources_own_single_page():
    """A normal run: the landed registry row 302s to ``future-all`` and publishes from there."""
    visited = []

    def handler(request):
        visited.append(str(request.url))
        assert request.url.path not in ('/search', '/event/search', '/subject_search',
                                        '/group/search') and not request.url.path.startswith('/j/')
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text=ROBOTS)
        if request.url.path == '/location/suzhou/events/future':
            return httpx.Response(302, headers={'Location': '/location/suzhou/events/future-all'})
        if request.url.path == '/location/suzhou/events/future-all':
            return httpx.Response(200, text=page_html([card_html()], total_pages=1),
                                  headers=HTML_HEADERS)
        assert request.url.path == '/event/35866026/'
        return httpx.Response(200, text=detail_html(), headers=HTML_HEADERS)

    source = DoubanSource(client=listing_client(handler), max_items=3)
    source.crawl_url = HOST_URL + '/location/suzhou/events/future'  # the landed registry row
    try:
        items = source.collect()
        events = [entry for entry in items if entry.is_event]
        assert [entry.item_key for entry in events] == ['douban-event-35866026']
        assert events[0].original_url == HOST_URL + '/event/35866026/'
        assert events[0].locator == '35866026'
        assert events[0].mock is False
        assert events[0].request_metadata['status'] == 200
        assert all(urlparse(url).hostname == HOST for url in visited)
        listing = [entry for entry in items
                   if not entry.is_event and 'future-all' in entry.original_url]
        assert listing[0].original_url == HOST_URL + '/location/suzhou/events/future-all'
        assert source.investigation['listing_pages_fetched'] == 1
        assert source.investigation['detail_pages_fetched'] == 1
        assert source.investigation['cards_seen'] == 1
        assert source.pages_collected == 2
        # robots + listing + detail. httpx resolves a same-host 302 inside the one request, so
        # the redirect hop is not a second attempt here; the live CLI run shows the same count.
        assert source.request_attempts == 3
    finally:
        source.client.close()


def test_registry_entry_url_redirect_chain_is_followed_within_the_same_host():
    """The landed registry row is ``/future``, which 302s to ``/future-all`` on the same host.

    ``PublicClient`` refuses a cross-host redirect outright, and this source re-checks the target
    against its own approved routes, so the documented ``/future`` -> ``/future/`` ->
    ``/future-all`` chain is the only way that request can finish.
    """
    requested = []

    def handler(request):
        requested.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text=ROBOTS)
        if request.url.path in ('/location/suzhou/events/future',
                                '/location/suzhou/events/future/'):
            raise AssertionError('a redirect target is followed by the client, not re-requested here')
        if request.url.path == '/location/suzhou/events/future-all':
            return httpx.Response(200, text=page_html([card_html()], total_pages=1),
                                  headers=HTML_HEADERS)
        return httpx.Response(200, text=detail_html(), headers=HTML_HEADERS)

    source = DoubanSource(client=listing_client(handler), max_items=1)
    source.crawl_url = HOST_URL + '/location/suzhou/events/future'
    try:
        items = source.collect()
        listing = [entry for entry in items if 'future-all' in entry.original_url]
        assert listing, 'the redirect target must be the collected listing page'
        assert listing[0].original_url == HOST_URL + '/location/suzhou/events/future-all'
        assert listing[0].request_metadata['status'] == 200
        assert [entry.item_key for entry in items if entry.is_event] == ['douban-event-35866026']
        assert all(urlparse(url).hostname == HOST for url in requested)
        assert [error for error in source.errors if 'Cross-host' in error['error']] == []
    finally:
        source.client.close()


def test_redirect_outside_the_approved_routes_is_refused_before_the_target_is_read():
    """A same-host 302 that leaves the approved paths must be refused, not followed."""
    requested = []

    def handler(request):
        requested.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text=ROBOTS)
        if request.url.path == '/location/suzhou/events/future-all':
            return httpx.Response(302, headers={'Location': 'https://' + HOST + '/search?q=suzhou'})
        raise AssertionError('the disallowed redirect target must never be requested')

    source = DoubanSource(client=listing_client(handler), max_items=1)
    try:
        items = source.collect()
        assert requested == [HOST_URL + '/robots.txt', LISTING_URL]
        assert [entry for entry in items if entry.is_event] == []
        assert any('approved public page routes' in error['error'] for error in source.errors)
    finally:
        source.client.close()


def test_cross_host_redirect_is_rejected_by_the_shared_client():
    def handler(request):
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text=ROBOTS)
        return httpx.Response(302, headers={'Location': 'https://evil.test/location/suzhou/events/'})

    source = DoubanSource(client=listing_client(handler), max_items=1)
    try:
        items = source.collect()
        assert [entry for entry in items if entry.is_event] == []
        assert any('Cross-host redirect' in error['error'] for error in source.errors)
    finally:
        source.client.close()


@pytest.mark.parametrize('url', [
    'http://' + HOST + '/location/suzhou/events/future-all',
    'https://' + HOST + ':444/location/suzhou/events/future-all',
    'https://m.douban.com/location/suzhou/events/future-all',
    'https://evil.test/location/suzhou/events/future-all',
    'https://' + HOST + '/location/suzhou/events/future-all?start=abc',
    'https://' + HOST + '/location/suzhou/events/future-all?start=11',
    'https://' + HOST + '/location/suzhou/events/future-all?start=10&sort=time',
    'https://' + HOST + '/event/35866026',
    'https://' + HOST + '/event/35866026/join',
    'https://' + HOST + '/event/35866026/#join',
    'https://' + HOST + '/location/suzhou/events/past',
    'https://' + HOST + '/search?q=suzhou',
    'https://' + HOST + '/event/search?q=1',
    'https://' + HOST + '/forum/suzhou',
    'https://' + HOST + '/j/collect',
])
def test_only_approved_public_douban_routes_are_ever_requestable(url):
    assert DoubanSource.is_public_url(url) is False
    assert DoubanSource.is_public_url(LISTING_URL) is True
    assert DoubanSource.is_public_url(LISTING_URL + '?start=10') is True
    assert DoubanSource.is_public_url(HOST_URL + '/event/35866026/') is True


def test_a_disallowed_registry_crawl_url_is_never_requested_and_a_wall_stops_the_host():
    visited = []

    def handler(request):
        visited.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text=ROBOTS)
        return httpx.Response(200, text=page_html([card_html()]), headers=HTML_HEADERS)

    source = DoubanSource(client=listing_client(handler), max_items=1)
    source.crawl_url = HOST_URL + '/event/search?q=suzhou'  # a robots-disallowed route
    try:
        items = source.collect()
        assert visited == []
        assert [entry for entry in items if entry.is_event] == []
        assert any('not an approved public Douban event route' in error['error']
                   for error in source.errors)
    finally:
        source.client.close()

    def walled(request):
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text=ROBOTS)
        return httpx.Response(200, text='<html>访问验证</html>', headers=HTML_HEADERS)

    source = DoubanSource(client=listing_client(walled), max_items=1)
    try:
        source.collect()
        assert any('access wall' in error['error'].lower() for error in source.errors)
        assert source.investigation['detail_pages_fetched'] == 0
    finally:
        source.client.close()


def test_paging_continues_past_stale_cards_until_the_page_cap():
    """Stale cards never stop paging: page 3 still contributes the accepted record."""
    stale_a = date.today() - timedelta(days=60)
    stale_b = date.today() - timedelta(days=90)
    visited = []

    def handler(request):
        visited.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text=ROBOTS)
        if request.url.path != '/location/suzhou/events/future-all':
            return httpx.Response(200, text=detail_html(), headers=HTML_HEADERS)
        start = int(request.url.params.get('start', 0))
        if start == 0:
            cards = [card_html(event_id='101', name='过期活动一',
                               start=stale_a.isoformat() + 'T10:00:00',
                               end=stale_a.isoformat() + 'T12:00:00',
                               time_text='时间： %s 周%s 10:00-12:00'
                                         % (chinese(stale_a), WEEKDAYS[stale_a.isoweekday() - 1]))]
        elif start == 10:
            cards = [card_html(event_id='102', name='过期活动二',
                               start=stale_b.isoformat() + 'T10:00:00',
                               end=stale_b.isoformat() + 'T12:00:00')]
        elif start == 20:
            cards = [card_html()]
        else:
            cards = [card_html(event_id='104', name='不应被请求')]
        return httpx.Response(200, text=page_html(cards, total_pages=24), headers=HTML_HEADERS)

    source = DoubanSource(client=listing_client(handler), max_items=5)
    try:
        items = source.collect()
        assert source.page_cap == 3
        assert [url for url in visited if 'start=30' in url] == []
        assert [url for url in visited if '/event/104/' in url] == []
        assert [url for url in visited if '/event/101/' in url] == []
        assert LISTING_URL + '?start=10' in visited
        assert LISTING_URL + '?start=20' in visited
        assert source.investigation['cards_skipped_stale'] == 2
        assert source.investigation['listing_pages_fetched'] == 3
        assert [entry.item_key for entry in items if entry.is_event] == ['douban-event-35866026']
    finally:
        source.client.close()


def test_page_cap_is_configurable_and_counts_pages_not_cards():
    visited = []

    def handler(request):
        visited.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text=ROBOTS)
        if request.url.path == '/location/suzhou/events/future-all':
            return httpx.Response(200, text=page_html([card_html()], total_pages=24),
                                  headers=HTML_HEADERS)
        return httpx.Response(200, text=detail_html(), headers=HTML_HEADERS)

    source = DoubanSource(client=listing_client(handler), max_items=1)
    source.page_cap = 2
    try:
        source.collect()
        assert [url for url in visited if 'future-all' in url] == [
            LISTING_URL, LISTING_URL + '?start=10']
        assert [url for url in visited if 'start=20' in url] == []
        assert source.investigation['listing_pages_fetched'] == 2
        assert source.investigation['listing_total_pages'] == 24
    finally:
        source.client.close()


def test_last_page_reported_by_the_source_ends_paging_early():
    visited = []

    def handler(request):
        visited.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text=ROBOTS)
        if request.url.path == '/location/suzhou/events/future-all':
            return httpx.Response(200, text=page_html([card_html()], total_pages=1),
                                  headers=HTML_HEADERS)
        return httpx.Response(200, text=detail_html(), headers=HTML_HEADERS)

    source = DoubanSource(client=listing_client(handler), max_items=1)
    source.page_cap = 5
    try:
        source.collect()
        assert [url for url in visited if 'start=' in url] == []
        assert source.investigation['listing_pages_fetched'] == 1
        assert source.investigation['listing_total_pages'] == 1
    finally:
        source.client.close()


def test_max_items_bounds_detail_requests_and_duplicate_cards_are_fetched_once():
    visited = []
    cards = ([card_html(event_id=str(900 + index), name='苏州测试活动%d' % index)
              for index in range(4)]
             + [card_html(event_id='900', name='苏州测试活动0')])

    def handler(request):
        visited.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text=ROBOTS)
        if request.url.path == '/location/suzhou/events/future-all':
            return httpx.Response(200, text=page_html(cards, total_pages=1), headers=HTML_HEADERS)
        event_id = request.url.path.strip('/').split('/')[-1]
        return httpx.Response(200, text=detail_html(event_id=event_id), headers=HTML_HEADERS)

    source = DoubanSource(client=listing_client(handler), max_items=2)
    try:
        items = source.collect()
        assert [url for url in visited if '/event/' in url] == [
            HOST_URL + '/event/900/', HOST_URL + '/event/901/']
        assert [entry.item_key for entry in items if entry.is_event] == [
            'douban-event-900', 'douban-event-901']
        assert source.investigation['detail_pages_fetched'] == 2
        assert source.investigation['cards_seen'] == 5
    finally:
        source.client.close()


def test_changed_card_shape_fails_closed_with_an_explicit_reason():
    def handler(request):
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text=ROBOTS)
        return httpx.Response(200, text=page_html([]), headers=HTML_HEADERS)

    source = DoubanSource(client=listing_client(handler), max_items=5)
    try:
        items = source.collect()
        assert [entry for entry in items if entry.is_event] == []
        assert any('card shape changed' in error['error'] for error in source.errors)
        assert source.investigation['detail_pages_fetched'] == 0
    finally:
        source.client.close()


def test_robots_denial_stops_the_host_without_any_content_request():
    visited = []

    def handler(request):
        visited.append(str(request.url))
        assert request.url.path == '/robots.txt'
        return httpx.Response(200, text='User-agent: *\nDisallow: /')

    source = DoubanSource(client=listing_client(handler), max_items=5)
    try:
        items = source.collect()
        assert visited == [HOST_URL + '/robots.txt']
        assert [entry for entry in items if entry.is_event] == []
        assert source.pages_collected == 0
        assert source.errors and 'disallows' in source.errors[0]['error']
    finally:
        source.client.close()


def test_live_robots_rules_are_not_opted_out_of():
    """The live host publishes real rules, so the strict fail-closed default must stay."""
    assert DoubanSource.accept_soft_404_robots is False
    assert DoubanSource.extractor == 'douban_event'
    assert DoubanSource.kind == 'community'
    assert DoubanSource.source_id == 'community-douban-suzhou'

    def handler(request):
        assert request.url.path == '/robots.txt'
        return httpx.Response(200, text='<html>页面走丢了</html>', headers=HTML_HEADERS)

    source = DoubanSource(client=listing_client(handler), max_items=5)
    try:
        source.collect()
        assert source.pages_collected == 0
        assert source.errors
        assert any('HTML/non-rules' in error['error'] for error in source.errors)
    finally:
        source.client.close()


# --------------------------------------------------------------------------------------
# Categories: explicit vocabulary or a clear keyword, otherwise 'others'
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize('etype, expected', [
    ('喜剧-相声', 'culture'),
    ('戏剧-话剧', 'culture'),
    ('音乐-音乐会', 'culture'),
    ('展览', 'culture'),
    ('运动', 'sports'),
    ('赛事', 'sports'),
    ('讲座', 'education'),
    ('亲子', 'education'),
    ('公益', 'government'),
    ('其他', 'others'),
    ('聚会-交友', 'others'),
])
def test_category_mapping_uses_the_sources_own_type_vocabulary(etype, expected):
    event = douban_event(item(detail_html(etype=etype, name='苏州测试活动')))
    assert event['category'] == expected
    assert event['field_evidence']['category']['status'] == 'Needs Review'
    assert '类型=' in event['field_evidence']['category']['snippet']


def test_unmapped_type_and_title_stays_others_rather_than_guessing():
    event = douban_event(item(detail_html(etype='其他', name='苏州测试活动')))
    assert event['category'] == 'others'
    assert 'defaults_to_others' in event['field_evidence']['category']['snippet']


def test_clear_title_keyword_is_used_only_when_the_type_is_unmapped():
    event = douban_event(item(detail_html(etype='其他', name='苏州测试相声专场')))
    assert event['category'] == 'culture'
    assert 'event_name_keyword_rule' in event['field_evidence']['category']['snippet']


# --------------------------------------------------------------------------------------
# End-to-end through the shared extractor/validator/pipeline on an isolated database
# --------------------------------------------------------------------------------------

class DoubanOneShot(DoubanSource):
    """One collected detail item with no HTTP, exercising the real extractor/pipeline path."""

    def __init__(self, raw, event_id='35866026'):
        super().__init__(client=object(), max_items=1)
        self.raw = raw
        self.event_id = event_id

    def collect(self):
        return [item(self.raw, event_id=self.event_id)]


def test_shared_extractor_dispatch_publishes_nothing_as_verified(tmp_path):
    raw = detail_html()
    event = extract(item(raw), 'community')
    assert event['start_date'] == '2026-10-17' and event['category'] == 'culture'
    assert event['venue'] == '嘻哈壹笑堂相声茶馆'
    db = tmp_path / 'douban-extract.sqlite3'
    report = run_pipeline(db, [DoubanOneShot(raw)])
    assert report['eventsProcessed'] == 1 and report['eventsStored'] == 1
    assert report['eventsCreated'] == 1
    assert report['attempts'][0]['status'] == 'Success'
    with connect(db) as con:
        assert not con.execute('PRAGMA foreign_key_check').fetchall()
        raw_row = con.execute('SELECT * FROM crawler_raw_items').fetchone()
        assert raw_row['original_url'] == HOST_URL + '/event/35866026/'
        assert raw_row['validation_status'] == 'Published'
        assert raw_row['raw_content'] == raw
        evidence = con.execute('SELECT * FROM crawler_evidence').fetchall()
        assert {row['field_name'] for row in evidence} >= {
            'event_name', 'start_date', 'end_date', 'venue', 'location', 'organizer', 'source_url'}
        assert len(evidence) == len(event['field_evidence']) == 11
        assert all(row['source_url'] == HOST_URL + '/event/35866026/' for row in evidence)
        assert all(row['verification_status'] != 'Verified' for row in evidence)
        stored = con.execute('SELECT * FROM events').fetchone()
        assert stored['startDate'] == '2026-10-17'
        import json as _json
        payload = _json.loads(stored['payload'])
        assert payload['name'] == '苏州丨必打卡丨爆笑丨演出丨嘻哈壹笑堂相声专场'
        unified = con.execute('SELECT * FROM crawler_unified_events').fetchone()
        normalized = _json.loads(unified['normalized_json'])
        assert normalized['venue'] == '嘻哈壹笑堂相声茶馆'
        assert normalized['location'] == '苏州 姑苏区 嘻哈壹笑堂相声茶馆 平江街道大儒巷38号(近长发商场)'


def test_pipeline_rejects_the_unresolvable_year_instead_of_storing_a_record(tmp_path):
    raw = detail_html(time_text='10月14日 20:00-22:00', start=None, end=None)
    db = tmp_path / 'douban-reject.sqlite3'
    report = run_pipeline(db, [DoubanOneShot(raw)])
    assert report['eventsProcessed'] == 0 and report['eventsStored'] == 0
    assert report['itemsRejected'] == 1
    assert report['attempts'][0]['status'] != 'Success'
    with connect(db) as con:
        row = con.execute('SELECT * FROM crawler_raw_items').fetchone()
        assert row['validation_status'] == 'Rejected'
        assert 'never guessed' in row['error']
        assert row['raw_content'] == raw  # raw forensic evidence is retained
        assert con.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 0


def test_detail_record_reports_the_verified_live_shape():
    """The parser against the exact live markup (no network): every field comes from the page."""
    raw = detail_html()
    record = detail_record(raw, HOST_URL + '/event/35866026/')
    assert record['event_id'] == '35866026'
    assert record['name'] == '苏州丨必打卡丨爆笑丨演出丨嘻哈壹笑堂相声专场'
    assert record['start'] == '2026-10-17' and record['end'] == '2026-10-31'
    assert record['start_raw'] == '2026-10-17T16:00:00'
    assert record['end_raw'] == '2026-10-31T21:30:00'
    assert record['venue_address'] == '嘻哈壹笑堂相声茶馆 平江街道大儒巷38号(近长发商场)'
    assert record['city'] == '苏州' and record['district'] == '姑苏区'
    assert record['type'] == '喜剧-相声' and record['provider'] == '猫眼演出'
    assert record['place'] == '苏州 姑苏区 嘻哈壹笑堂相声茶馆 平江街道大儒巷38号(近长发商场)'
    assert record['time_text'] == (
        '10月17日 周六 16:00 ~ 10月31日 周六 21:30 活动结束时间以实际活动为准')
    assert DETAIL_PATH.fullmatch('/event/35866026/') is not None


def test_card_records_skip_foreign_scope_free_and_query_links():
    html = page_html([
        card_html(),
        '<li class="list-entry" itemscope itemtype="http://data-vocabulary.org/Event">'
        '<div class="info"><div class="title">'
        '<a href="https://evil.test/event/999/" title="外部">外部</a></div></div></li>',
        '<li class="list-entry" itemscope itemtype="http://data-vocabulary.org/Event">'
        '<div class="info"><div class="title">'
        '<a href="%s/event/999/?token=x" title="带参">带参</a></div></div></li>' % HOST_URL,
        '<li class="list-entry"><div class="info"><div class="title">'
        '<a href="%s/event/998/" title="无事件作用域">无作用域</a></div></div></li>' % HOST_URL,
    ])
    records = card_records(html)
    assert [record['event_id'] for record in records] == ['35866026']
    assert records[0]['url'] == HOST_URL + '/event/35866026/'
    assert records[0]['name'] == '苏州丨必打卡丨爆笑丨演出丨嘻哈壹笑堂相声专场'
    assert records[0]['place'] == '苏州 姑苏区 嘻哈壹笑堂相声茶馆 平江街道大儒巷38号(近长发商场)'
    assert records[0]['owner'] == '猫眼演出'
    assert records[0]['start'] == '2026-10-17'
    assert records[0]['end'] == '2026-10-31'
    assert records[0]['time_text'] == '时间: 10月17日 周六 16:00 ~ 10月31日 周六 21:30'


def test_never_verified_status_rule_applies_to_every_evidence_row():
    event = douban_event(item(detail_html()))
    assert set(event['field_evidence']) == {
        'event_name', 'category', 'start_date', 'end_date', 'venue', 'location', 'organizer',
        'venue_id', 'district_id', 'city', 'source_url'}
    assert event['field_evidence']['venue_id']['status'] == 'Missing'
    assert event['field_evidence']['district_id']['status'] == 'Missing'
    for field, claim in event['field_evidence'].items():
        assert claim['status'] in ('Unverified', 'Needs Review', 'Missing'), field
        assert claim['status'] != 'Verified', field
        if claim['status'] == 'Missing':
            assert claim['confidence'] == 0.0
        else:
            assert 0 < claim['confidence'] <= 1
            assert claim['snippet'] and claim['method']
    assert re.fullmatch(r'evt-[0-9a-f]{24}', event['event_id'])
