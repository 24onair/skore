# 설계 결정 기록 (Decision Log)

채점은 "규정 준수 + 공식 결과 일치"가 생명이므로, 점수에 영향을 주는 결정을 여기에 고정한다.

## D1. 규정 버전 — GAP2023 (FS) 골든 검증 완료
- **기준**: FAI Sporting Code Section 7F – XC Scoring (GAP2023, S7F 2024 ed.) + PWCA 2023.
- **골든 픽스처**: `samples/golden/` (2026-06-28 남부리그 5차전 2라운드 FS 공식 결과 + 3개 트랙).
- 검증된 공식(`test_golden.py`로 고정):
  - **거리 기준점 = 이륙장(takeoff)** — FS는 launch부터 잼(우리도 변경). 거리·거리점 공식값과 ~20m 일치.
  - **시간점**: `SpeedFraction = 1 − ((Ptime−BestTime)/√BestTime)^(5/6)`, **시간 단위 hour**.
    BestTime = 골 도착자 중 최속. 송대진 226.7점·구간시간 03:52:37 정확 일치.
  - **거리점**: 선형 `AvailDist × dist/bestDist` (min_dist는 비율식에 안 들어감, 하한 처리만).
  - **가중치(LTR)**: `LeadW=(1−DistW)·LTR`, `TimeW=(1−DistW)·(1−LTR)`. DistW=cubic(goalRatio).
    이 대회 LTR≈0.3539. (FS 기본 0.26)
- ⚠️ **리딩 점수 미보정**: LC의 기준값 LCmin은 **필드 전체(12명) 통계**라 3개 트랙으론 검증 불가.
  PWCA2019 선형 LC(`∫g·dt/(1800·SS_km)`) 구조는 구현했으나, 절대 정규화·착륙자 tail은
  **전체 필드 트랙 확보 후 보정** 필요. 현재 리딩은 `UNVERIFIED`.

## D2. 지구 모델
- **WGS84 타원체** 사용 (현행 CIVL/Airscore PG 관행과 결과 일치 목적). `GeographicLib`로 측지 계산.
- 레거시 FAI 구체(R≈6,371,000m)는 설정 토글로 후순위 지원.

## D3. 룰셋
- 기본: **PG (paragliding)** → Arrival points **OFF**, Distance difficulty **미적용**(HG 전용).
- 점수 = **Distance + Time + Leading**.
- PWCA 룰 vs 순수 S7F 차이는 Phase 2에서 토글로 분리.

## D4. 과제(Task) 입력 포맷 우선순위
1. **XCTrack `.xctsk`** (JSON) — 1순위.
2. 수기 입력(API/UI 폼).
3. (후순위) FS `.fsdb`, 웨이포인트 `.wpt`.

## D5. 라이선스
- 본 저장소 **MIT**. GPL/카피레프트 코드 미복사. 재사용 라이브러리는 MIT(GeographicLib) 한정.

## D6. IGC 파싱
- B레코드는 **고정 컬럼 byte 파싱**. lat/lon `DDMMmmm`(천분의 1분)→/60000. validity 바이트(A=3D/V=2D).
- 타임스탬프는 `HFDTE`(또는 `HFDTEDATE`) + B레코드 시각, **UTC 자정 롤오버** 처리.
- 자체 구현(클린룸). 추후 필요 시 aerofiles(MIT)로 대체 가능.
