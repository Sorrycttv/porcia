import json
from types import SimpleNamespace
import httpx
import pytest
from sqlalchemy.orm import Session
from app import meal_replacement, menu_ai
from app.main import app, current_user
from app.models import Profile, SavedPlan, User, MealPlanItem
from tests.test_fridge_flow import fridge_client


@pytest.fixture(autouse=True)
def select_model(monkeypatch):
    monkeypatch.setattr(meal_replacement, 'recommend_replacement', lambda candidates, *args: (candidates[0].id, 'applied'))


def swap(client, plan, day=0, meal='Обед', reason='different'):
    return client.post('/api/v1/plans/replace-meal', json={
        'revision': plan['revision'], 'day_index': day, 'meal': meal, 'reason': reason})


@pytest.mark.parametrize('days', [1, 7])
def test_single_replacement_keeps_all_other_meals_and_persists(fridge_client, days):
    client, engine = fridge_client
    plan = client.post('/api/v1/plans/generate', json={'days': days}).json()
    response = swap(client, plan)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['days'][0]['meals'][1]['recipe'] != plan['days'][0]['meals'][1]['recipe']
    for i, day in enumerate(plan['days']):
        if i != 0: assert result['days'][i]['estimated_cost'] == day['estimated_cost']
        for j, meal in enumerate(day['meals']):
            if (i,j) != (0,1): assert result['days'][i]['meals'][j] == meal
    assert result['meals'] == result['days'][0]['meals']
    assert result['shopping_list'] == result['weekly_shopping'][0]['items']
    assert result['revision'] != plan['revision']
    assert client.get('/api/v1/plans/current').json()['plan'] == result
    with Session(engine) as db:
        item = db.query(MealPlanItem).filter_by(plan_id=plan['plan_id'], meal='Обед').one()
        assert item.recipe_name == result['meals'][1]['recipe']
    assert swap(client, plan).status_code == 409


def test_original_unused_pantry_is_used_after_replacement(fridge_client):
    client, _ = fridge_client
    stock = [{'product':'Куриное филе','grams':100000}, {'product':'Рис','grams':100000}]
    plan = client.post('/api/v1/plans/generate', json={'days':1,'pantry':stock}).json()
    client.put('/api/v1/fridge',json=[{'product':'Яблоко','grams':10}])
    response = swap(client, plan, reason='pantry')
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['generation_context']['pantry'] == plan['generation_context']['pantry']
    assert not any(x['product'].casefold() in ('куриное филе','рис') for x in result['shopping_list'])
    assert client.get('/api/v1/fridge').json()['items'] == [{'product':'Яблоко','grams':10}]


@pytest.mark.parametrize('failure', ['profile', 'legacy', 'empty_pantry', 'other_user'])
def test_rejected_change_does_not_mutate_saved_plan(fridge_client, failure):
    client, engine = fridge_client
    plan = client.post('/api/v1/plans/generate', json={'days':7}).json()
    if failure == 'profile':
        with Session(engine) as db:
            db.get(Profile,1).restrictions='milk';db.commit()
    if failure == 'legacy':
        with Session(engine) as db:
            p=json.loads(db.get(SavedPlan,1).payload);del p['generation_context']
            db.get(SavedPlan,1).payload=json.dumps(p);db.commit()
    before=client.get('/api/v1/plans/current').json()
    if failure == 'other_user': app.dependency_overrides[current_user]=lambda:User(id=2)
    response=swap(client,plan,reason='pantry' if failure=='empty_pantry' else 'different')
    assert response.status_code==400
    app.dependency_overrides[current_user]=lambda:User(id=1)
    assert client.get('/api/v1/plans/current').json()==before


@pytest.mark.parametrize('status', ['unavailable','invalid_response'])
def test_fallback_is_explicit_and_safe(fridge_client, monkeypatch, status):
    client,_=fridge_client
    monkeypatch.setattr(meal_replacement,'recommend_replacement',lambda *args:(None,status))
    plan=client.post('/api/v1/plans/generate',json={'days':1}).json()
    response=swap(client,plan)
    assert response.status_code==200,response.text
    assert response.json()['replacement']['ai_status']==status
    assert response.json()['ai_selection']['applied_meals']==0


@pytest.mark.parametrize('mode', ['balanced','batch'])
def test_replacing_leftover_changes_whole_group(fridge_client, mode):
    client,_=fridge_client
    plan=client.post('/api/v1/plans/generate',json={'days':7,'cooking_mode':mode}).json()
    i,m=next((i,m) for i,d in enumerate(plan['days']) for m in d['meals'] if m['time_kind']=='reheat')
    origin=m['prepared_on_day']
    response=swap(client,plan,i,m['meal'])
    assert response.status_code==200,response.text
    result=response.json()
    affected=result['replacement']['affected_days']
    assert len(affected)>1
    for n in affected:
        replacement=next(x for x in result['days'][n-1]['meals'] if x['meal']==m['meal'])
        assert replacement['recipe']!=m['recipe']
        assert replacement['prepared_on_day']==origin
        assert replacement['time_kind']==('cook' if n-1==origin else 'reheat')


def test_slow_model_cannot_overwrite_newer_plan(fridge_client,monkeypatch):
    client,engine=fridge_client
    plan=client.post('/api/v1/plans/generate',json={'days':1}).json()
    def model(candidates,*args):
        with Session(engine) as db:
            value=json.loads(db.get(SavedPlan,1).payload);value['revision']='newer'
            db.get(SavedPlan,1).payload=json.dumps(value);db.commit()
        return candidates[0].id,'applied'
    monkeypatch.setattr(meal_replacement,'recommend_replacement',model)
    assert swap(client,plan).status_code==409
    assert client.get('/api/v1/plans/current').json()['plan']['revision']=='newer'


def test_profile_change_during_model_call_is_rejected(fridge_client,monkeypatch):
    client,engine=fridge_client
    plan=client.post('/api/v1/plans/generate',json={'days':1}).json()
    def model(candidates,*args):
        with Session(engine) as db:
            db.get(Profile,1).restrictions='milk';db.commit()
        return candidates[0].id,'applied'
    monkeypatch.setattr(meal_replacement,'recommend_replacement',model)
    assert swap(client,plan).status_code==409
    assert client.get('/api/v1/plans/current').json()['plan']==plan


def test_warnings_are_rebuilt_from_result(fridge_client):
    client,engine=fridge_client
    plan=client.post('/api/v1/plans/generate',json={'days':1}).json()
    with Session(engine) as db:
        plan['warnings']=['устаревшее предупреждение']
        db.get(SavedPlan,1).payload=json.dumps(plan);db.commit()
    response=swap(client,plan)
    assert response.status_code==200,response.text
    assert 'устаревшее предупреждение' not in response.json()['warnings']


@pytest.mark.parametrize('content,status', [('{"recipe_id":1}','applied'),
    ('{"recipe_id":999}','invalid_response'), ('{"recipe_id":true}','invalid_response'),
    ('{"recipe_id":1,"price":10}','invalid_response'), ('not json','invalid_response')])
def test_home_ollama_selection_uses_configured_endpoint_and_bounded_ids(monkeypatch,content,status):
    sent={}
    class FakeClient:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def post(self,url,json):
            sent.update(url=url,body=json)
            return httpx.Response(200,request=httpx.Request('POST',url),json={'message':{'content':content}})
    monkeypatch.setattr(menu_ai.httpx,'Client',FakeClient)
    recipe=SimpleNamespace(id=1,name='Проверенное блюдо',preparation_minutes=10,
                           estimated_cost=100,calories=500,ingredients='{"Рис":50}')
    chosen,actual=menu_ai.recommend_replacement([recipe],'different',500,{},[],
                                               'http://home-ollama:11434','test-model')
    assert actual==status
    assert chosen==(1 if status=='applied' else None)
    assert sent['url']=='http://home-ollama:11434/api/chat'
    assert sent['body']['model']=='test-model'
    assert sent['body']['format']['properties']['recipe_id']['enum']==[1]


@pytest.mark.parametrize('reason',['cheaper','faster'])
def test_requested_improvement_is_real_or_plan_stays_unchanged(fridge_client,reason):
    client,_=fridge_client
    plan=client.post('/api/v1/plans/generate',json={'days':1}).json()
    old=plan['meals'][1]
    response=swap(client,plan,reason=reason)
    if response.status_code==400:
        assert client.get('/api/v1/plans/current').json()['plan']==plan
    else:
        assert response.status_code==200,response.text
        new=response.json()['meals'][1]
        key='estimated_cost' if reason=='cheaper' else 'preparation_minutes'
        assert new[key]<old[key]
