#!/usr/bin/env python3
"""쏘카존 SQLite 데이터베이스 초기화 및 JSON 데이터 이관"""
import sqlite3
import json
import os
import re

DB_PATH = os.path.join(os.path.dirname(__file__), "socar_zones.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn):
    conn.executescript("""
    -- 시도 (광역시/도)
    CREATE TABLE IF NOT EXISTS sido (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL UNIQUE,          -- 서울특별시
        short_name  TEXT NOT NULL,                  -- 서울
        sort_order  INTEGER DEFAULT 0
    );

    -- 시군구
    CREATE TABLE IF NOT EXISTS sigungu (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        sido_id     INTEGER NOT NULL REFERENCES sido(id),
        name        TEXT NOT NULL,                  -- 강남구
        UNIQUE(sido_id, name)
    );

    -- 관광명소 태그
    CREATE TABLE IF NOT EXISTS tourist_tag (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL UNIQUE,           -- 해운대, 제주공항, 경포대 등
        description TEXT DEFAULT ''
    );

    -- 쏘카존
    CREATE TABLE IF NOT EXISTS zone (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        kakao_id        TEXT UNIQUE,                -- 카카오맵 confirmid
        name            TEXT NOT NULL,              -- 쏘카존 강남역 1번출구
        address         TEXT DEFAULT '',            -- 지번 주소
        road_address    TEXT DEFAULT '',            -- 도로명 주소
        lat             REAL DEFAULT 0,
        lng             REAL DEFAULT 0,
        sido_id         INTEGER REFERENCES sido(id),
        sigungu_id      INTEGER REFERENCES sigungu(id),
        category        TEXT DEFAULT '카셰어링',
        is_active       INTEGER DEFAULT 1,          -- 운영 여부
        memo            TEXT DEFAULT '',             -- 관리용 메모
        created_at      TEXT DEFAULT (datetime('now','localtime')),
        updated_at      TEXT DEFAULT (datetime('now','localtime'))
    );

    -- 쏘카존 ↔ 관광태그 다대다
    CREATE TABLE IF NOT EXISTS zone_tourist_tag (
        zone_id     INTEGER NOT NULL REFERENCES zone(id) ON DELETE CASCADE,
        tag_id      INTEGER NOT NULL REFERENCES tourist_tag(id) ON DELETE CASCADE,
        PRIMARY KEY (zone_id, tag_id)
    );

    -- 웹사이트 프로필 (하나의 DB에서 여러 사이트 빌드)
    CREATE TABLE IF NOT EXISTS site_profile (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        slug        TEXT NOT NULL UNIQUE,            -- 'main', 'jeju', 'tourist' 등
        title       TEXT NOT NULL,
        description TEXT DEFAULT '',
        filter_sql  TEXT DEFAULT '',                 -- 이 사이트에 포함할 존 필터 조건
        template    TEXT DEFAULT 'default',          -- 사용할 템플릿
        created_at  TEXT DEFAULT (datetime('now','localtime'))
    );

    -- 인덱스
    CREATE INDEX IF NOT EXISTS idx_zone_sido ON zone(sido_id);
    CREATE INDEX IF NOT EXISTS idx_zone_sigungu ON zone(sigungu_id);
    CREATE INDEX IF NOT EXISTS idx_zone_active ON zone(is_active);
    CREATE INDEX IF NOT EXISTS idx_zone_name ON zone(name);
    CREATE INDEX IF NOT EXISTS idx_sigungu_sido ON sigungu(sido_id);
    """)
    conn.commit()


SIDO_MAP = {
    "서울": ("서울특별시", 1), "경기": ("경기도", 2), "인천": ("인천광역시", 3),
    "부산": ("부산광역시", 4), "대구": ("대구광역시", 5), "대전": ("대전광역시", 6),
    "광주": ("광주광역시", 7), "울산": ("울산광역시", 8), "세종": ("세종특별자치시", 9),
    "강원": ("강원특별자치도", 10), "충북": ("충청북도", 11), "충남": ("충청남도", 12),
    "전북": ("전북특별자치도", 13), "전남": ("전라남도", 14),
    "경북": ("경상북도", 15), "경남": ("경상남도", 16), "제주": ("제주특별자치도", 17),
}

# 시군구 → 시도 short_name 매핑 (경기도 등 주소에 "경기"가 안 붙는 케이스)
CITY_TO_SIDO = {}
_gyeonggi = ["수원","성남","고양","용인","부천","안산","안양","화성","평택","시흥","파주","김포","광명","하남","구리","남양주","의정부","오산","군포","이천","양주","동두천","포천","여주","양평","가평","연천"]
for c in _gyeonggi: CITY_TO_SIDO[c] = "경기"
_gangwon = ["춘천","원주","강릉","속초","동해","삼척","태백","정선","평창","횡성","홍천","영월","철원","양양","인제","고성"]
for c in _gangwon: CITY_TO_SIDO[c] = "강원"
_chungbuk = ["청주","충주","제천","음성","진천","괴산","단양","옥천","영동","보은","증평"]
for c in _chungbuk: CITY_TO_SIDO[c] = "충북"
_chungnam = ["천안","아산","서산","당진","논산","공주","보령","홍성","예산","태안","부여","서천","금산","청양"]
for c in _chungnam: CITY_TO_SIDO[c] = "충남"
_jeonbuk = ["전주","익산","군산","정읍","남원","김제","완주","무주","장수","임실","순창","진안","고창"]
for c in _jeonbuk: CITY_TO_SIDO[c] = "전북"
_jeonnam = ["여수","순천","목포","광양","나주","무안","해남","고흥","영암","담양","장성","화순","강진","장흥","완도","보성","신안","함평","진도","영광","곡성"]
for c in _jeonnam: CITY_TO_SIDO[c] = "전남"
_gyeongbuk = ["포항","경주","구미","김천","안동","영주","문경","상주","영천","경산","칠곡","성주","군위","의성","청송","영양","영덕","봉화","울진","예천","고령"]
for c in _gyeongbuk: CITY_TO_SIDO[c] = "경북"
_gyeongnam = ["창원","김해","거제","양산","진주","통영","사천","밀양","거창","함안","창녕","합천","산청","하동","남해","함양","고성","의령"]
for c in _gyeongnam: CITY_TO_SIDO[c] = "경남"


def parse_address(address):
    """주소 → (sido_short, sigungu_name)"""
    if not address:
        return None, ""

    for short in SIDO_MAP:
        if address.startswith(short):
            parts = address.split()
            sigungu = parts[1] if len(parts) > 1 else ""
            return short, sigungu

    for city, sido_short in CITY_TO_SIDO.items():
        if city in address:
            # 시군 이름 추출
            m = re.search(rf'({city}\S*?[시군구])', address)
            sigungu = m.group(1) if m else city
            return sido_short, sigungu

    return None, ""


TOURIST_TAGS_DEF = {
    "제주공항": ["제주시"],
    "서귀포": ["서귀포"],
    "한라산": ["제주시", "서귀포"],
    "해운대": ["해운대구"],
    "남포동": ["중구"],
    "경포대": ["강릉"],
    "설악산": ["속초"],
    "불국사": ["경주"],
    "여수밤바다": ["여수"],
    "한옥마을": ["전주"],
    "남이섬": ["춘천", "가평"],
    "순천만": ["순천"],
    "유성온천": ["유성구"],
    "동피랑": ["통영"],
    "호미곶": ["포항"],
}


def import_json(conn, json_path):
    """JSON 데이터를 DB로 이관"""
    with open(json_path, "r", encoding="utf-8") as f:
        zones = json.load(f)

    # 1. 시도 삽입
    sido_ids = {}
    for short, (full, order) in SIDO_MAP.items():
        conn.execute(
            "INSERT OR IGNORE INTO sido (name, short_name, sort_order) VALUES (?, ?, ?)",
            (full, short, order)
        )
        row = conn.execute("SELECT id FROM sido WHERE short_name = ?", (short,)).fetchone()
        sido_ids[short] = row["id"]
    conn.commit()

    # 2. 관광태그 삽입
    tag_ids = {}
    for tag_name in TOURIST_TAGS_DEF:
        conn.execute("INSERT OR IGNORE INTO tourist_tag (name) VALUES (?)", (tag_name,))
        row = conn.execute("SELECT id FROM tourist_tag WHERE name = ?", (tag_name,)).fetchone()
        tag_ids[tag_name] = row["id"]
    conn.commit()

    # 3. 쏘카존 삽입
    sigungu_cache = {}
    imported = 0

    for z in zones:
        addr = z.get("address", "") or z.get("road_address", "")
        sido_short, sigungu_name = parse_address(addr)

        if not sido_short or sido_short not in sido_ids:
            continue

        sido_id = sido_ids[sido_short]

        # 시군구
        sg_key = (sido_id, sigungu_name)
        if sg_key not in sigungu_cache:
            conn.execute(
                "INSERT OR IGNORE INTO sigungu (sido_id, name) VALUES (?, ?)",
                (sido_id, sigungu_name)
            )
            row = conn.execute(
                "SELECT id FROM sigungu WHERE sido_id = ? AND name = ?",
                (sido_id, sigungu_name)
            ).fetchone()
            sigungu_cache[sg_key] = row["id"]

        sigungu_id = sigungu_cache[sg_key]

        conn.execute("""
            INSERT OR IGNORE INTO zone (kakao_id, name, address, road_address, lat, lng, sido_id, sigungu_id, category)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            z.get("id", ""),
            z["name"],
            z.get("address", ""),
            z.get("road_address", ""),
            z.get("lat", 0),
            z.get("lng", 0),
            sido_id,
            sigungu_id,
            z.get("category", "카셰어링"),
        ))
        imported += 1

    conn.commit()

    # 4. 관광태그 연결
    for tag_name, keywords in TOURIST_TAGS_DEF.items():
        tag_id = tag_ids[tag_name]
        for kw in keywords:
            rows = conn.execute("""
                SELECT z.id FROM zone z
                JOIN sigungu sg ON z.sigungu_id = sg.id
                WHERE sg.name LIKE ?
            """, (f"%{kw}%",)).fetchall()
            for row in rows:
                conn.execute(
                    "INSERT OR IGNORE INTO zone_tourist_tag (zone_id, tag_id) VALUES (?, ?)",
                    (row["id"], tag_id)
                )
    conn.commit()

    # 5. 기본 사이트 프로필 등록
    profiles = [
        ("main", "전국 쏘카존 위치 안내", "전국 쏘카존 검색 사이트", "", "default"),
        ("jeju", "제주 쏘카존 안내", "제주도 쏘카존 검색", "WHERE s.short_name = '제주'", "default"),
        ("seoul", "서울 쏘카존 안내", "서울 쏘카존 검색", "WHERE s.short_name = '서울'", "default"),
        ("tourist", "관광지 근처 쏘카존", "전국 관광명소 주변 쏘카존", "INNER JOIN zone_tourist_tag zt ON z.id = zt.zone_id", "tourist"),
        ("busan", "부산 쏘카존 안내", "부산 쏘카존 검색", "WHERE s.short_name = '부산'", "default"),
        ("gangwon", "강원 쏘카존 안내", "강원도 쏘카존 검색", "WHERE s.short_name = '강원'", "default"),
    ]
    for slug, title, desc, filter_sql, template in profiles:
        conn.execute(
            "INSERT OR IGNORE INTO site_profile (slug, title, description, filter_sql, template) VALUES (?, ?, ?, ?, ?)",
            (slug, title, desc, filter_sql, template)
        )
    conn.commit()

    return imported


def print_stats(conn):
    total = conn.execute("SELECT COUNT(*) FROM zone").fetchone()[0]
    active = conn.execute("SELECT COUNT(*) FROM zone WHERE is_active = 1").fetchone()[0]
    sidos = conn.execute("SELECT COUNT(*) FROM sido").fetchone()[0]
    sigungu = conn.execute("SELECT COUNT(*) FROM sigungu").fetchone()[0]
    tags = conn.execute("SELECT COUNT(*) FROM tourist_tag").fetchone()[0]
    profiles = conn.execute("SELECT COUNT(*) FROM site_profile").fetchone()[0]

    print(f"\n=== 데이터베이스 통계 ===")
    print(f"  전체 쏘카존: {total}개 (활성: {active}개)")
    print(f"  시도: {sidos}개")
    print(f"  시군구: {sigungu}개")
    print(f"  관광태그: {tags}개")
    print(f"  사이트 프로필: {profiles}개")

    print(f"\n=== 시도별 쏘카존 수 ===")
    rows = conn.execute("""
        SELECT s.name, s.short_name, COUNT(z.id) as cnt
        FROM sido s LEFT JOIN zone z ON z.sido_id = s.id
        GROUP BY s.id ORDER BY cnt DESC
    """).fetchall()
    for r in rows:
        print(f"  {r['name']} ({r['short_name']}): {r['cnt']}개")

    print(f"\n=== 사이트 프로필 ===")
    rows = conn.execute("SELECT slug, title FROM site_profile").fetchall()
    for r in rows:
        print(f"  [{r['slug']}] {r['title']}")


def main():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

    conn = get_conn()
    print("스키마 초기화...")
    init_schema(conn)

    json_path = os.path.join(os.path.dirname(__file__), "..", "socar_zones.json")
    if os.path.exists(json_path):
        print(f"JSON 데이터 이관: {json_path}")
        imported = import_json(conn, json_path)
        print(f"  → {imported}건 처리")
    else:
        print(f"JSON 파일 없음: {json_path}")

    print_stats(conn)
    conn.close()
    print(f"\n✅ DB 생성 완료: {DB_PATH}")


if __name__ == "__main__":
    main()
