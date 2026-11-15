"""공개 실거래 집계 API. 원본 접근은 서버 계정의 SELECT로 제한한다."""
import logging
from typing import Literal
from datetime import date
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from app.services import real_estate as service
from app.services import real_estate_db

router = APIRouter(prefix='/api/v1/real-estate', tags=['real-estate'])
log = logging.getLogger(__name__)


@router.get('/metadata')
async def metadata():
    try:
        return await real_estate_db.metadata()
    except (SQLAlchemyError, ValueError, RuntimeError):
        log.exception('부동산 메타데이터 조회 실패')
        raise HTTPException(503, '부동산 데이터에 연결할 수 없습니다. 조회 권한과 수집 상태를 확인해 주세요.')


@router.get('')
async def overview(
    unit: Literal['month','quarter','year'] = 'quarter',
    end: str = Query(pattern=r'^\d{4}-(0[1-9]|1[0-2])$'),
    count: int = Query(4, ge=2, le=12),
    comparison: Literal['previous','year'] = 'previous',
):
    if unit == 'year' and count > 5:
        raise HTTPException(422, '연간 분석은 한 번에 최대 5년까지 선택할 수 있습니다.')
    try:
        date.fromisoformat(end + '-01')
        result = await service.snapshot(unit, end, count, comparison)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except (SQLAlchemyError, RuntimeError):
        log.exception('부동산 조회 실패')
        raise HTTPException(503, '부동산 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.')
    return JSONResponse(result, status_code=202 if result.get('pending') else 200,
                        headers={'Cache-Control':'no-store', **({'Retry-After':'3'} if result.get('pending') else {})})


@router.get('/history')
async def history(span: Literal['1', '3', '5', '10', 'all'] = '3',
                  first: int | None = Query(None, ge=8024), last: int | None = Query(None, ge=8024)):
    try:
        result = await service.history(span, first, last)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except (SQLAlchemyError, RuntimeError):
        log.exception('부동산 기간 차트 조회 실패')
        raise HTTPException(503, '부동산 기간 데이터를 불러오지 못했습니다.')
    return JSONResponse(result, status_code=202 if result.get('pending') else 200,
                        headers={'Cache-Control': 'no-store'})


@router.get('/explorer')
async def explorer(region: str = 'KR'):
    from fastapi.responses import Response
    try:
        result = await real_estate_db.explorer(region)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    except SQLAlchemyError:
        log.exception('부동산 완성본 조회 실패')
        raise HTTPException(503, '부동산 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.')
    if isinstance(result, bytes):
        return Response(result, media_type='application/json', headers={
            'Content-Encoding':'gzip', 'Cache-Control':'no-store'})
    return JSONResponse(result, status_code=202, headers={'Cache-Control':'no-store'})
