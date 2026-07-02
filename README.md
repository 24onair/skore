# 패러글라이딩 XC 경기 성적 계산기 (Paragliding XC Scoring)

트래커(비행계기)의 **IGC 트랙로그**를 받아 **FAI/CIVL 규정(Sporting Code S7F, GAP)** 에 따라
XC **Race-to-Goal** 경기 성적을 산출하는 서비스.

## 단계
- **Phase 1 (완료): 단일 트랙 분석** — IGC 1개 + 과제 정의 → 달성 여부 / 비행거리 / 최적경로 대비 /
  SSS·ESS·Goal 시각을 지도와 함께 표시 (`/`).
- **Phase 2 (완료): 다중 선수 대회 채점** — 여러 IGC 일괄 처리 → GAP 점수(거리/시간/리딩) +
  Day quality + 순위표 (`/comp.html`, `POST /api/score`).
  - ⚠️ **GAP 상수(nominal 파라미터·weight 계수·리딩 정규화)는 골든 데이터 보정 전** — 절대 점수는
    잠정값. 구조는 표준 GAP. 공식 사용 전 실제 대회 결과와 대조 필요. 상수는 `scoring/params.py`에 집약.
- **Phase 3 (예정): 운영/완성도** — 추가 포맷(GPX/FIT), PWCA 룰 토글, 정지과제·페널티, 결과 내보내기,
  DB 영속화, 골든 픽스처 검증.

## 구조 (모노레포)
- `scoring/` — 순수 Python 채점 엔진 (부수효과 없는 함수 + 단위테스트). **단일 진실 공급원**.
- `api/` — FastAPI (IGC 업로드·분석 엔드포인트).
- `web/` — React + MapLibre (지도 시각화, 결과 패널). *Phase 1 후반에 추가.*

## 규정/라이선스
- 채점 공식은 **FAI Sporting Code Section 7F (GAP)** — 공개 규정 → **클린룸 구현**.
- 본 코드는 **MIT**. `airscore`(GPL) / `FAI-Airscore`(강한 카피레프트) 코드는 **복사하지 않으며**
  동작·결과 대조에만 참고한다. 측지 계산은 `GeographicLib`(MIT) 재사용.
- 적용 규정 버전·지구 모델·룰셋 결정은 [`DECISIONS.md`](./DECISIONS.md) 참조.

## 개발 환경
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[api,dev]"
pytest                 # 엔진 단위테스트
uvicorn api.main:app --reload   # API 로컬 실행
```
