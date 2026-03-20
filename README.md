# 쏘카존 웹사이트

전국 5,096개 쏘카존의 위치 정보를 지역별로 검색할 수 있는 정적 웹사이트입니다.

## 빠른 시작

```bash
# 1. 레포 클론
git clone https://github.com/david-superhero/socar-zone-website.git
cd socar-zone-website

# 2. 로컬에서 웹사이트 확인 (Python 내장 서버)
python3 -m http.server 8000

# 브라우저에서 http://localhost:8000 접속
```

지역별 사이트는 `sites/` 디렉토리에 있습니다:
```bash
python3 -m http.server 8000 --directory sites/jeju    # 제주
python3 -m http.server 8000 --directory sites/seoul    # 서울
python3 -m http.server 8000 --directory sites/busan    # 부산
```

## 프로젝트 구조

```
socar-zone-website/
├── db/
│   ├── init_db.py           # DB 스키마 생성 + JSON 데이터 임포트
│   ├── manage.py            # 쏘카존 CRUD 관리 CLI
│   ├── build_site.py        # DB → 정적 사이트 빌더
│   └── socar_zones.db       # SQLite 데이터베이스
├── sites/                   # 빌드된 사이트들
│   ├── main/                # 전국 (5,096개)
│   ├── seoul/               # 서울 (1,452개)
│   ├── jeju/                # 제주 (97개)
│   ├── busan/               # 부산 (366개)
│   ├── gangwon/             # 강원 (152개)
│   └── tourist/             # 관광지 (754개)
├── index.html               # 기존 전체 사이트
├── socar_zones.json         # 원본 데이터
├── llms.txt                 # AI 에이전트용
├── robots.txt               # AI 크롤러 허용
└── sitemap.xml              # 검색엔진 색인용
```

## 데이터 관리

### 검색
```bash
python3 db/manage.py search 강남역
python3 db/manage.py list --sido 서울 --sigungu 강남구
python3 db/manage.py show 907
```

### 수정
```bash
python3 db/manage.py edit 907 memo=테스트메모
python3 db/manage.py deactivate 907      # 비활성화 (사이트에서 제외)
python3 db/manage.py activate 907        # 재활성화
```

### 추가 / 삭제
```bash
python3 db/manage.py add --name "쏘카존 테스트" --address "서울 강남구 역삼동"
python3 db/manage.py delete 5097
```

### 태그 관리
```bash
python3 db/manage.py tags                # 전체 태그 목록
python3 db/manage.py tag 907 해운대       # 태그 연결
python3 db/manage.py untag 907 해운대     # 태그 해제
```

### 데이터 내보내기
```bash
python3 db/manage.py export --profile jeju --format json
python3 db/manage.py export --profile seoul --format csv
```

## 사이트 빌드

데이터를 수정한 후 사이트를 재생성합니다:

```bash
# 전체 프로필 빌드
python3 db/build_site.py

# 특정 프로필만 빌드
python3 db/build_site.py jeju busan
```

### 새 지역 사이트 추가
```bash
# 1. 프로필 등록
python3 db/manage.py add-profile daegu "대구 쏘카존 안내" "대구 쏘카존 검색" "WHERE s.short_name = '대구'" default

# 2. 사이트 빌드
python3 db/build_site.py daegu

# 3. 확인
python3 -m http.server 8000 --directory sites/daegu
```

## DB 초기화 (처음부터 다시 할 경우)

```bash
# socar_zones.json이 프로젝트 루트에 있어야 함
python3 db/init_db.py
```

## 사이트 프로필

| slug | 제목 | 필터 | 존 수 |
|------|------|------|-------|
| main | 전국 쏘카존 위치 안내 | (전체) | 5,096 |
| seoul | 서울 쏘카존 안내 | `WHERE s.short_name = '서울'` | 1,452 |
| jeju | 제주 쏘카존 안내 | `WHERE s.short_name = '제주'` | 97 |
| busan | 부산 쏘카존 안내 | `WHERE s.short_name = '부산'` | 366 |
| gangwon | 강원 쏘카존 안내 | `WHERE s.short_name = '강원'` | 152 |
| tourist | 관광지 근처 쏘카존 | `INNER JOIN zone_tourist_tag` | 754 |

## 기술 스택

- **데이터 수집**: 카카오맵 내부 JSONP API (`collect_socar_zones.py`)
- **데이터베이스**: SQLite (sido → sigungu → zone 계층 구조)
- **사이트 생성**: Python 정적 HTML 빌더
- **SEO**: Schema.org JSON-LD (Organization, ItemList, FAQPage), sitemap.xml
- **AI 최적화**: llms.txt, robots.txt (GPTBot, Claude-Web, PerplexityBot 허용)
- **검색 UI**: 클라이언트 AND 키워드 매칭, 하이라이트

## 관련 문서

- [Confluence 가이드](https://socarcorp.atlassian.net/wiki/spaces/PRD/pages/4505436809)
