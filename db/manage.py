#!/usr/bin/env python3
"""쏘카존 데이터 관리 CLI"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from init_db import get_conn

USAGE = """
쏘카존 관리 도구
================
  python manage.py list [--sido 서울] [--sigungu 강남구] [--inactive] [--limit 20]
  python manage.py search <키워드>
  python manage.py show <zone_id>
  python manage.py edit <zone_id> <필드=값> [필드=값 ...]
  python manage.py deactivate <zone_id>
  python manage.py activate <zone_id>
  python manage.py add --name "쏘카존 이름" --address "주소" [--road "도로명"] [--lat 0] [--lng 0]
  python manage.py delete <zone_id>
  python manage.py tag <zone_id> <태그명>
  python manage.py untag <zone_id> <태그명>
  python manage.py tags
  python manage.py profiles
  python manage.py add-profile <slug> <title> <description> [filter_sql] [template]
  python manage.py stats
  python manage.py export [--profile main] [--format json|csv]
"""


def cmd_list(args):
    conn = get_conn()
    sql = """
        SELECT z.id, z.name, z.address, z.is_active,
               s.short_name as sido, sg.name as sigungu
        FROM zone z
        LEFT JOIN sido s ON z.sido_id = s.id
        LEFT JOIN sigungu sg ON z.sigungu_id = sg.id
        WHERE 1=1
    """
    params = []
    show_inactive = "--inactive" in args
    if not show_inactive:
        sql += " AND z.is_active = 1"

    sido = _get_arg(args, "--sido")
    if sido:
        sql += " AND s.short_name = ?"
        params.append(sido)

    sigungu = _get_arg(args, "--sigungu")
    if sigungu:
        sql += " AND sg.name LIKE ?"
        params.append(f"%{sigungu}%")

    sql += " ORDER BY s.sort_order, sg.name, z.name"

    limit = int(_get_arg(args, "--limit") or 50)
    sql += f" LIMIT {limit}"

    rows = conn.execute(sql, params).fetchall()
    for r in rows:
        status = "" if r["is_active"] else " [비활성]"
        print(f"  [{r['id']:5d}] {r['sido']} {r['sigungu']} | {r['name']}{status}")
    print(f"\n총 {len(rows)}건 (limit {limit})")
    conn.close()


def cmd_search(args):
    if not args:
        print("검색어를 입력하세요")
        return
    keyword = " ".join(args)
    conn = get_conn()
    rows = conn.execute("""
        SELECT z.id, z.name, z.address, z.is_active,
               s.short_name as sido, sg.name as sigungu
        FROM zone z
        LEFT JOIN sido s ON z.sido_id = s.id
        LEFT JOIN sigungu sg ON z.sigungu_id = sg.id
        WHERE z.name LIKE ? OR z.address LIKE ? OR z.road_address LIKE ?
        ORDER BY z.name LIMIT 50
    """, (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%")).fetchall()
    for r in rows:
        status = "" if r["is_active"] else " [비활성]"
        print(f"  [{r['id']:5d}] {r['sido']} {r['sigungu']} | {r['name']}{status}")
    print(f"\n검색결과: {len(rows)}건")
    conn.close()


def cmd_show(args):
    if not args:
        print("zone_id를 입력하세요")
        return
    conn = get_conn()
    r = conn.execute("""
        SELECT z.*, s.name as sido_name, s.short_name as sido_short, sg.name as sigungu_name
        FROM zone z
        LEFT JOIN sido s ON z.sido_id = s.id
        LEFT JOIN sigungu sg ON z.sigungu_id = sg.id
        WHERE z.id = ?
    """, (int(args[0]),)).fetchone()
    if not r:
        print("해당 쏘카존이 없습니다")
        return
    print(f"  ID: {r['id']}")
    print(f"  이름: {r['name']}")
    print(f"  카카오ID: {r['kakao_id']}")
    print(f"  주소: {r['address']}")
    print(f"  도로명: {r['road_address']}")
    print(f"  좌표: {r['lat']}, {r['lng']}")
    print(f"  시도: {r['sido_name']} ({r['sido_short']})")
    print(f"  시군구: {r['sigungu_name']}")
    print(f"  카테고리: {r['category']}")
    print(f"  활성: {'예' if r['is_active'] else '아니오'}")
    print(f"  메모: {r['memo']}")
    print(f"  생성: {r['created_at']}")
    print(f"  수정: {r['updated_at']}")

    tags = conn.execute("""
        SELECT t.name FROM tourist_tag t
        JOIN zone_tourist_tag zt ON t.id = zt.tag_id
        WHERE zt.zone_id = ?
    """, (r['id'],)).fetchall()
    if tags:
        print(f"  태그: {', '.join(t['name'] for t in tags)}")
    conn.close()


def cmd_edit(args):
    if len(args) < 2:
        print("사용법: edit <zone_id> <필드=값> [필드=값 ...]")
        return
    zone_id = int(args[0])
    allowed = {"name", "address", "road_address", "lat", "lng", "category", "memo", "is_active"}
    conn = get_conn()
    for pair in args[1:]:
        if "=" not in pair:
            print(f"잘못된 형식: {pair} (필드=값 형태로 입력)")
            continue
        field, value = pair.split("=", 1)
        if field not in allowed:
            print(f"수정 불가 필드: {field} (가능: {', '.join(sorted(allowed))})")
            continue
        conn.execute(f"UPDATE zone SET {field} = ?, updated_at = datetime('now','localtime') WHERE id = ?",
                     (value, zone_id))
        print(f"  {field} → {value}")
    conn.commit()
    conn.close()
    print("수정 완료")


def cmd_activate(args, active=1):
    if not args:
        print("zone_id를 입력하세요")
        return
    conn = get_conn()
    conn.execute("UPDATE zone SET is_active = ?, updated_at = datetime('now','localtime') WHERE id = ?",
                 (active, int(args[0])))
    conn.commit()
    conn.close()
    status = "활성화" if active else "비활성화"
    print(f"쏘카존 #{args[0]} {status} 완료")


def cmd_add(args):
    name = _get_arg(args, "--name")
    if not name:
        print("--name 필수")
        return
    address = _get_arg(args, "--address") or ""
    road = _get_arg(args, "--road") or ""
    lat = float(_get_arg(args, "--lat") or 0)
    lng = float(_get_arg(args, "--lng") or 0)

    from init_db import parse_address, SIDO_MAP
    conn = get_conn()
    addr = address or road
    sido_short, sigungu_name = parse_address(addr)

    sido_id = None
    sigungu_id = None
    if sido_short:
        row = conn.execute("SELECT id FROM sido WHERE short_name = ?", (sido_short,)).fetchone()
        if row:
            sido_id = row["id"]
            conn.execute("INSERT OR IGNORE INTO sigungu (sido_id, name) VALUES (?, ?)",
                         (sido_id, sigungu_name))
            sg = conn.execute("SELECT id FROM sigungu WHERE sido_id = ? AND name = ?",
                              (sido_id, sigungu_name)).fetchone()
            sigungu_id = sg["id"] if sg else None

    conn.execute("""
        INSERT INTO zone (name, address, road_address, lat, lng, sido_id, sigungu_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (name, address, road, lat, lng, sido_id, sigungu_id))
    conn.commit()
    new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    print(f"쏘카존 추가 완료 (ID: {new_id})")


def cmd_delete(args):
    if not args:
        print("zone_id를 입력하세요")
        return
    zone_id = int(args[0])
    conn = get_conn()
    r = conn.execute("SELECT name FROM zone WHERE id = ?", (zone_id,)).fetchone()
    if not r:
        print("해당 쏘카존이 없습니다")
        return
    conn.execute("DELETE FROM zone WHERE id = ?", (zone_id,))
    conn.commit()
    conn.close()
    print(f"쏘카존 #{zone_id} ({r['name']}) 삭제 완료")


def cmd_tag(args):
    if len(args) < 2:
        print("사용법: tag <zone_id> <태그명>")
        return
    zone_id, tag_name = int(args[0]), args[1]
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO tourist_tag (name) VALUES (?)", (tag_name,))
    tag = conn.execute("SELECT id FROM tourist_tag WHERE name = ?", (tag_name,)).fetchone()
    conn.execute("INSERT OR IGNORE INTO zone_tourist_tag (zone_id, tag_id) VALUES (?, ?)",
                 (zone_id, tag["id"]))
    conn.commit()
    conn.close()
    print(f"쏘카존 #{zone_id}에 '{tag_name}' 태그 추가")


def cmd_untag(args):
    if len(args) < 2:
        print("사용법: untag <zone_id> <태그명>")
        return
    zone_id, tag_name = int(args[0]), args[1]
    conn = get_conn()
    tag = conn.execute("SELECT id FROM tourist_tag WHERE name = ?", (tag_name,)).fetchone()
    if tag:
        conn.execute("DELETE FROM zone_tourist_tag WHERE zone_id = ? AND tag_id = ?",
                     (zone_id, tag["id"]))
        conn.commit()
    conn.close()
    print(f"쏘카존 #{zone_id}에서 '{tag_name}' 태그 제거")


def cmd_tags(args):
    conn = get_conn()
    rows = conn.execute("""
        SELECT t.id, t.name, COUNT(zt.zone_id) as cnt
        FROM tourist_tag t
        LEFT JOIN zone_tourist_tag zt ON t.id = zt.tag_id
        GROUP BY t.id ORDER BY cnt DESC
    """).fetchall()
    for r in rows:
        print(f"  [{r['id']:3d}] {r['name']} ({r['cnt']}개 존)")
    conn.close()


def cmd_profiles(args):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM site_profile ORDER BY id").fetchall()
    for r in rows:
        print(f"  [{r['slug']}] {r['title']}")
        print(f"    설명: {r['description']}")
        print(f"    필터: {r['filter_sql'] or '(전체)'}")
        print(f"    템플릿: {r['template']}")
        print()
    conn.close()


def cmd_add_profile(args):
    if len(args) < 3:
        print("사용법: add-profile <slug> <title> <description> [filter_sql] [template]")
        return
    slug, title, desc = args[0], args[1], args[2]
    filter_sql = args[3] if len(args) > 3 else ""
    template = args[4] if len(args) > 4 else "default"
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO site_profile (slug, title, description, filter_sql, template) VALUES (?, ?, ?, ?, ?)",
        (slug, title, desc, filter_sql, template))
    conn.commit()
    conn.close()
    print(f"프로필 '{slug}' 등록 완료")


def cmd_stats(args):
    from init_db import print_stats
    conn = get_conn()
    print_stats(conn)
    conn.close()


def cmd_export(args):
    import json
    import csv
    import io
    profile_slug = _get_arg(args, "--profile") or "main"
    fmt = _get_arg(args, "--format") or "json"

    conn = get_conn()
    profile = conn.execute("SELECT * FROM site_profile WHERE slug = ?", (profile_slug,)).fetchone()
    if not profile:
        print(f"프로필 '{profile_slug}'이 없습니다")
        conn.close()
        return

    sql = """
        SELECT z.id, z.name, z.address, z.road_address, z.lat, z.lng,
               s.short_name as sido, s.name as sido_name,
               sg.name as sigungu, z.category, z.is_active, z.memo
        FROM zone z
        LEFT JOIN sido s ON z.sido_id = s.id
        LEFT JOIN sigungu sg ON z.sigungu_id = sg.id
    """
    filter_sql = profile["filter_sql"]
    if filter_sql:
        sql += f" {filter_sql}"
    sql += " ORDER BY s.sort_order, sg.name, z.name"

    rows = conn.execute(sql).fetchall()
    conn.close()

    data = [dict(r) for r in rows]
    out_name = f"export_{profile_slug}.{fmt}"
    out_path = os.path.join(os.path.dirname(__file__), "..", out_name)

    if fmt == "csv":
        with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
            if data:
                w = csv.DictWriter(f, fieldnames=data[0].keys())
                w.writeheader()
                w.writerows(data)
    else:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"{len(data)}건 → {out_path}")


def _get_arg(args, flag):
    if flag in args:
        idx = args.index(flag)
        if idx + 1 < len(args):
            return args[idx + 1]
    return None


def main():
    if len(sys.argv) < 2:
        print(USAGE)
        return

    cmd = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "list": cmd_list,
        "search": cmd_search,
        "show": cmd_show,
        "edit": cmd_edit,
        "activate": lambda a: cmd_activate(a, 1),
        "deactivate": lambda a: cmd_activate(a, 0),
        "add": cmd_add,
        "delete": cmd_delete,
        "tag": cmd_tag,
        "untag": cmd_untag,
        "tags": cmd_tags,
        "profiles": cmd_profiles,
        "add-profile": cmd_add_profile,
        "stats": cmd_stats,
        "export": cmd_export,
    }

    if cmd in commands:
        commands[cmd](args)
    else:
        print(f"알 수 없는 명령: {cmd}")
        print(USAGE)


if __name__ == "__main__":
    main()
