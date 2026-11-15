"""사전 계산이 기존 단지·면적 매칭과 같고, 갱신 중 완성본이 유지되는지 검증한다."""
from datetime import date
import gzip
import json
from statistics import median

import pytest
from app.services import real_estate_matrix as matrix


def test_triangle_indices_cover_every_range_once():
    indices = [matrix.pair_index(i,j) for j in range(1,84) for i in range(j)]
    assert indices == list(range(3486))


def test_parent_annual_rate_pools_original_cells_and_never_crosses_area_or_lawd():
    nodes={'KR':{'parent':None},'11':{'parent':'KR'},'11110':{'parent':'11'},'11140':{'parent':'11'}}
    left={'11110':[['A','84.0',100],['B','84.0',100]],
          '11140':[['A','84.0',100],['C','84.0',100],['D','84.0',100]]}
    right={'11110':[['A','84.0',144],['B','85.0',200]],
           '11140':[['A','84.0',100],['C','84.0',81],['D','84.0',121]]}
    result=matrix.matched_pair(left,right,2,nodes)
    assert result['KR'][1] == 4
    assert result['KR'][0] == pytest.approx(median([20,0,-10,10]))
    assert result['11'] == result['KR']
    assert result['11110'][0] == pytest.approx(20)
    assert result['11140'][1] == 3


def test_window_revision_tracks_only_overlapping_months():
    window=(date(2026,8,15),date(2026,11,15))
    meta={'regions':{'11110':'종로'},'updated_at':'a','revisions':{f'2026{m:02}':str(m) for m in range(1,13)}}
    initial=matrix.window_revision(window,meta)
    meta['updated_at']='b';meta['revisions']['202607']='changed'
    assert matrix.window_revision(window,meta)==initial
    meta['revisions']['202608']='changed'
    assert matrix.window_revision(window,meta)!=initial


@pytest.mark.asyncio
async def test_incremental_matrix_and_atomic_bundles(tmp_path,monkeypatch):
    monkeypatch.setattr(matrix,'ROOT',tmp_path)
    nodes={'KR':{'parent':None,'children':['11']},'11':{'parent':'KR','children':['11110']},
           '11110':{'parent':'11','children':[]}}
    monkeypatch.setattr(matrix.source,'geography',lambda:{'nodes':nodes})
    monkeypatch.setattr(matrix.source,'public_metadata',lambda meta:{'updated_at':meta['updated_at']})
    monkeypatch.setattr(matrix.source,'history_window',lambda *args:(8104,8107))
    monkeypatch.setattr(matrix.source,'rolling_window',lambda *args:None)
    meta={'regions':{'11110':'종로'},'updated_at':'a','revisions':{f'2026{m:02}':str(m) for m in range(1,13)}}
    full={'periods':['2026 Q1','2026 Q2','2026 Q3','2026 Q4'],
          'regions':{c:[{'count':1}] *4 for c in nodes},'map_summary':{c:{'count':4} for c in nodes}}
    async def history(*args):
        return dict(full,metadata={'updated_at':meta['updated_at']})
    monkeypatch.setattr(matrix.source,'history',history)
    async def cohort(window,current):
        return {'11110':[['A','84.0',100+window[0].month]]},matrix.window_revision(window,current)
    monkeypatch.setattr(matrix,'cohort',cohort)
    calls=[]
    original=matrix.matched_pair
    def match(*args):
        calls.append(args[2])
        return original(*args)
    monkeypatch.setattr(matrix,'matched_pair',match)
    await matrix.build(meta)
    assert len(calls)==6
    first=matrix.current_manifest()
    bundle=json.loads(gzip.decompress((tmp_path/first['version']/'KR.json.gz').read_bytes()))
    assert set(bundle['regions'])=={'KR','11'}
    assert len(bundle['matrix']['regions']['11']['rates'])==6
    assert bundle['matrix']['regions']['11']['samples']==[1]*6
    await matrix.build(meta)
    assert len(calls)==6
    meta['updated_at']='b';meta['revisions']['202610']='new'
    await matrix.build(meta)
    assert len(calls)==9  # 마지막 분기에 관련된 세 조합만 재계산
    second=matrix.current_manifest()
    assert second['version']!=first['version']
    changed=json.loads(gzip.decompress((tmp_path/second['version']/'KR.json.gz').read_bytes()))
    assert changed['matrix']['regions']['11']['rates'][:3]==bundle['matrix']['regions']['11']['rates'][:3]
    # 갱신 실패 시 포인터와 현재 응답은 직전 완성본을 유지한다.
    meta['updated_at']='c';meta['revisions']['202610']='newer'
    def fail(*args):
        raise RuntimeError('중간 실패')
    monkeypatch.setattr(matrix,'matched_pair',fail)
    with pytest.raises(RuntimeError):
        await matrix.build(meta)
    assert matrix.current_manifest()==second
    assert (tmp_path/first['version']/'KR.json.gz').exists()


@pytest.mark.asyncio
async def test_changed_cohort_does_not_reuse_global_watermark_cache(tmp_path,monkeypatch):
    monkeypatch.setattr(matrix,'ROOT',tmp_path)
    meta={'regions':{'11110':'종로'},'updated_at':'same-max','revisions':{'202601':'a','202602':'b','202603':'c'}}
    calls=[]
    async def endpoint(window,meta,**kwargs):
        calls.append(kwargs['reuse'])
        return {'11110':[['A','84.0',100]]}
    monkeypatch.setattr(matrix.source,'endpoint_snapshot',endpoint)
    window=(date(2026,1,1),date(2026,4,1))
    await matrix.cohort(window,meta)
    await matrix.cohort(window,meta)
    meta['revisions']['202602']='changed'
    await matrix.cohort(window,meta)
    assert calls==[True,False]


def test_year_cache_survives_unrelated_collection_update(tmp_path,monkeypatch):
    from datetime import datetime
    source=matrix.source
    monkeypatch.setattr(source,'CACHE_DIR',tmp_path)
    meta={'regions':{'11110':'종로'},'updated_at':'a','revisions':{'202601':'one'}}
    start,stop=date(2026,1,1),date(2026,4,1)
    payload={'metadata':{'as_of_month':datetime.now(source.KST).strftime('%Y-%m')},'periods':['2026 Q1']}
    (tmp_path/'year.json').write_text(json.dumps({'updated_at':'a','payload':payload}))
    assert source._window_cached('year',meta,start,stop)==payload
    meta['updated_at']='b';meta['revisions']['202611']='new'
    assert source._window_cached('year',meta,start,stop)==payload
    meta['revisions']['202601']='changed'
    assert source._window_cached('year',meta,start,stop) is None
