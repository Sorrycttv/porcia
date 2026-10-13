import asyncio
import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from app import magnit_prices, product_search, main


def fixture():
    return json.loads((Path(__file__).parent / 'fixtures/magnit-public-cards-2026-10-09.json').read_text(encoding='utf-8'))['nuxt']


def page(flat):
    return '<script type="application/json" data-nuxt-data="nuxt-app">' + json.dumps(flat) + '</script>'


def moscow_page():
    flat = fixture()
    return page(['Москва, улица Примерная, 1' if isinstance(x,str) and 'Дзержинского' in x else x for x in flat])


def test_actual_public_cards_preserve_prices_units_and_delivery_scope():
    result = magnit_prices.parse_page(page(fixture()), '992301', None)
    assert result['status'] == 'ok'
    rice = next(o for o in result['offers'] if o['title'].startswith('Рис'))
    assert rice['price'] == 134.99 and rice['package_quantity'] == 900
    assert rice['price_per_unit'] == 149.99
    assert rice['valid_until'] is None and rice['price_scope'] == 'delivery_store'
    milk = next(o for o in result['offers'] if o['title'].startswith('Молоко'))
    assert milk['package_unit'] == 'ml' and milk['package_quantity'] == 930
    onion = next(o for o in result['offers'] if o['title'].startswith('Лук'))
    assert onion['weighted'] and onion['package_quantity'] == 700
    assert onion['price'] == 37.09 and onion['price_per_unit'] == 52.99
    assert 'Премиум' in onion['conditions']


def test_default_krasnodar_store_is_never_used_as_moscow_prices():
    result = magnit_prices.parse_page(page(fixture()), '992301', 1)
    assert result['status'] == 'region_mismatch' and result['offers'] == []
    assert 'Краснодар' in result['store_address']


def test_retailer_switching_the_selected_shop_is_rejected():
    with pytest.raises(ValueError): magnit_prices.parse_page(page(fixture()), '123456', 1)


@pytest.mark.parametrize('bad', ['https://evil.example/product/1234?shopCode=992301&shopType=dostavka',
                             '/product/1234?shopCode=123456&shopType=dostavka',
                             '/product/1234?shopCode=992301&shopType=pickup'])
def test_foreign_urls_stores_and_purchase_modes_are_not_imported(bad):
    flat = fixture()
    flat = [bad if isinstance(x,str) and x.startswith('/product/') else x for x in flat]
    assert magnit_prices.parse_page(page(flat), '992301', None)['offers'] == []


def test_missing_nuxt_or_invalid_references_fail_closed():
    with pytest.raises(ValueError): magnit_prices.parse_page('<html>blocked</html>', '992301', 1)
    with pytest.raises(ValueError): magnit_prices.parse_page(page([{'$scurrentStore':100}]), '992301', 1)


def test_negative_nan_prices_and_unknown_package_are_not_invented():
    flat = fixture()
    flat = ['NaN' if x == '134.99' else '-1' if x == '84.99' else x for x in flat]
    result = magnit_prices.parse_page(page(flat), '992301', None)
    assert [o['title'] for o in result['offers']] == ['Лук репчатый']


def test_explicit_multipack_mass_is_for_all_bags_and_ambiguous_forms_are_unknown():
    assert magnit_prices.catalogue_size('Рис 5пак*80г')['package_quantity'] == 400
    assert magnit_prices.catalogue_size('Рис 8пак*62.5г')['package_quantity'] == 500
    assert magnit_prices.catalogue_size('Рис 5x80г') is None
    assert magnit_prices.catalogue_size('Рис 5пак*80г 500г') is None
    assert magnit_prices.catalogue_size('Вес 400–500г') is None


def test_unselected_shop_does_not_request_an_ip_default_catalogue(monkeypatch):
    client = AsyncMock()
    monkeypatch.setattr(magnit_prices.httpx, 'AsyncClient', client)
    result = asyncio.run(magnit_prices.search('рис', None, 1))
    assert result['status'] == 'shop_required' and result['offers'] == []
    client.assert_not_called()


def test_selected_store_query_is_cached_with_original_observation_time(monkeypatch):
    magnit_prices._cache.clear()
    magnit_prices._last_request = 0
    calls = []
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def get(self,url,params):
            calls.append(params)
            return httpx.Response(200,text=moscow_page(),request=httpx.Request('GET',url))
    monkeypatch.setattr(magnit_prices.httpx,'AsyncClient',lambda **kwargs:Client())
    async def run():
        first = await magnit_prices.search('рис','992301',1)
        assert first['status'] == 'ok'
        second = await magnit_prices.search('рис','992301',1)
        assert second == first
        assert all(o['fetched_at']==first['fetched_at'] for o in first['offers'])
    asyncio.run(run())
    assert len(calls)==1 and calls[0]['shopType']=='dostavka' and calls[0]['term']=='рис'
    magnit_prices._cache.clear()


def test_two_sources_reach_model_candidates_without_starvation():
    verny = [{'id':f'v{i}','chain':'Верный','title':'Рис','product':'Рис','price':100} for i in range(6)]
    magnit = [{'id':f'm{i}','chain':'Магнит','title':'Рис','product':'Рис','price':120} for i in range(6)]
    row = product_search.candidates_for([{'product':'Рис','grams':1200}],verny+magnit,'')[0]
    assert [o['id'] for o in row['candidates']] == ['v0','v1','v2','m0','m1','m2']
    selected = product_search.apply_selections([row],json.dumps({'selections':[{'index':0,'offer_id':'m1','reason':'price'}]}))
    assert selected[0]['offer']['price']==120


def test_api_shop_identifiers_cannot_be_urls_or_shell_arguments():
    for invalid in ('https://evil.example','992301;echo','../1234'):
        with pytest.raises(ValueError): main.PlanProductsInput(magnit_shop_code=invalid)
