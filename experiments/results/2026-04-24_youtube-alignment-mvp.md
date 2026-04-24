# 2026-04-24 YouTube Alignment MVP

## 목적

기존 치지직 요약 타임라인을 유튜브 다시보기 기준 댓글 붙여넣기용 텍스트로 재사용하기 위한
1차 MVP를 추가했다. 목표는 완전 자동 정렬이 아니라 `길이차 기반 auto offset + 수동 앵커 보정`
흐름을 관리자 UI에서 검증 가능하게 만드는 것이다.

## 검증 대상

- Chzzk VOD: `12878342`
- Report: `site/vods/12878342/report.md`
- YouTube VOD: `https://www.youtube.com/watch?v=H2Y2V1DkrcQ`

## 관측값

- Chzzk duration: `37875 sec` (`10:31:15`)
- YouTube duration: `37002 sec` (`10:16:42`)
- auto offset: `873 sec` (`14:33`)

## 샘플 변환

- `01:39:30` → `01:24:57`
- `03:51:50` → `03:37:17`
- `10:09:33` → `09:55:00`

## 구현 범위

- `pipeline/timeline_alignment.py`
  - YouTube URL 메타 읽기
  - auto offset profile
  - manual anchor 기반 offset/piecewise profile
  - timeline/highlight remap
  - YouTube comment text render
- `scripts/report_admin_server.py`
  - YouTube alignment preview/save API
  - editor UI에서 YouTube URL 입력, auto preview, anchor 입력
  - 저장된 `youtube_alignment.json` 재사용

## 운영 메모

- 자동 초안만으로는 중간 컷 편집을 복원할 수 없다.
- 앵커 2개 이상 입력 시 실사용 정확도가 눈에 띄게 올라간다.
- 저장된 `youtube_alignment.json` 이 있으면 다음 편집 세션에서 URL/앵커를 다시 입력하지 않아도 된다.

## 검증 명령

```powershell
python experiments/test_youtube_alignment.py
```
