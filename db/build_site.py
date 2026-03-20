#!/usr/bin/env python3
"""DB 기반 사이트 빌더 — site_profile별로 정적 웹사이트 생성"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from init_db import get_conn, SIDO_MAP

SIDO_SHORT = {v: k for k, v in SIDO_MAP.items() if isinstance(v, tuple)}
# SIDO_MAP: short → (full, order)
SIDO_ORDER = {short: order for short, (full, order) in SIDO_MAP.items()}
SIDO_FULL = {short: full for short, (full, order) in SIDO_MAP.items()}


def load_zones(conn, profile):
    """프로필의 filter_sql을 적용하여 존 목록 로드"""
    base = """
        SELECT z.id, z.name, z.address, z.road_address, z.lat, z.lng,
               z.category, z.is_active, z.memo,
               s.name as sido_name, s.short_name as sido_short, s.sort_order,
               sg.name as sigungu_name
        FROM zone z
        LEFT JOIN sido s ON z.sido_id = s.id
        LEFT JOIN sigungu sg ON z.sigungu_id = sg.id
    """
    filter_sql = profile["filter_sql"] or ""
    # filter_sql은 WHERE 또는 INNER JOIN 등으로 시작
    sql = base + filter_sql + " AND z.is_active = 1" if "WHERE" in filter_sql.upper() else base + (" WHERE z.is_active = 1" if not filter_sql else filter_sql + " WHERE z.is_active = 1")
    sql += " ORDER BY s.sort_order, sg.name, z.name"
    return conn.execute(sql).fetchall()


def load_tourist_data(conn, zone_ids):
    """관광태그 정보 로드"""
    if not zone_ids:
        return {}, {}
    placeholders = ",".join("?" * len(zone_ids))
    rows = conn.execute(f"""
        SELECT zt.zone_id, t.name as tag_name
        FROM zone_tourist_tag zt
        JOIN tourist_tag t ON zt.tag_id = t.id
        WHERE zt.zone_id IN ({placeholders})
    """, zone_ids).fetchall()

    zone_tags = defaultdict(list)  # zone_id → [tag_name, ...]
    tag_zones = defaultdict(list)  # tag_name → [zone_id, ...]
    for r in rows:
        zone_tags[r["zone_id"]].append(r["tag_name"])
        tag_zones[r["tag_name"]].append(r["zone_id"])
    return zone_tags, tag_zones


def structure_zones(zones):
    """존 목록을 시도→시군구 구조로 변환"""
    structured = defaultdict(lambda: defaultdict(list))
    for z in zones:
        sido = z["sido_name"] or "기타"
        sigungu = z["sigungu_name"] or "(미분류)"
        structured[sido][sigungu].append(dict(z))
    return structured


def generate_site(conn, profile, out_dir):
    """하나의 사이트 프로필에 대해 정적 사이트 생성"""
    slug = profile["slug"]
    title = profile["title"]
    description = profile["description"]
    template = profile["template"]

    zones = load_zones(conn, profile)
    total = len(zones)
    if total == 0:
        print(f"  [{slug}] 존 0개 — 스킵")
        return

    zone_ids = [z["id"] for z in zones]
    zone_tags, tag_zones = load_tourist_data(conn, zone_ids)
    structured = structure_zones(zones)

    today = datetime.now().strftime("%Y-%m-%d")

    # 시도별 통계
    sido_stats = {}
    for sido, districts in structured.items():
        sido_stats[sido] = sum(len(zs) for zs in districts.values())

    # 시도 정렬 (존 수 기준)
    sorted_sidos = sorted(
        [s for s in sido_stats if s != "기타"],
        key=lambda x: -sido_stats[x]
    )

    # JSON-LD
    json_ld_items = []
    for z in zones[:100]:
        json_ld_items.append({
            "@type": "Place",
            "name": z["name"],
            "address": {
                "@type": "PostalAddress",
                "addressLocality": z["sigungu_name"] or "",
                "addressRegion": z["sido_name"] or "",
                "addressCountry": "KR",
                "streetAddress": z["road_address"] or z["address"]
            },
            "geo": {
                "@type": "GeoCoordinates",
                "latitude": z["lat"],
                "longitude": z["lng"]
            }
        })

    json_ld = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": title,
        "description": f"{description} — {total}개 쏘카존 위치 정보",
        "numberOfItems": total,
        "itemListElement": json_ld_items
    }

    # 관광섹션 (태그별)
    tourist_html = ""
    for tag_name, zids in sorted(tag_zones.items(), key=lambda x: -len(x[1])):
        tag_zone_list = [dict(z) for z in zones if z["id"] in zids][:30]
        if not tag_zone_list:
            continue
        tourist_html += f'''
    <section id="tourist-{tag_name}" class="tourist-section">
      <h3>{tag_name} 근처 쏘카존 ({len(zids)}개)</h3>
      <table>
        <thead><tr><th>쏘카존 이름</th><th>주소</th></tr></thead>
        <tbody>
'''
        for z in tag_zone_list:
            addr = (z["road_address"] or z["address"]).replace("|", " ")
            tourist_html += f'          <tr><td>{z["name"]}</td><td>{addr}</td></tr>\n'
        tourist_html += '        </tbody>\n      </table>\n    </section>\n'

    # 관광 네비
    tourist_nav = ""
    for tag_name in sorted(tag_zones, key=lambda x: -len(tag_zones[x])):
        tourist_nav += f'      <a href="#tourist-{tag_name}" class="tourist-chip">{tag_name}</a>\n'

    if tourist_nav.strip():
        tourist_nav_section = f'<nav class="nav-section" id="navTourist">\n      <h2>관광명소 근처 쏘카존</h2>\n      <div class="chips">\n{tourist_nav}      </div>\n    </nav>'
    else:
        tourist_nav_section = ""

    # 지역 네비
    nav_html = ""
    for sido in sorted_sidos:
        short = None
        for s, (f, o) in SIDO_MAP.items():
            if f == sido:
                short = s
                break
        short = short or sido
        nav_html += f'      <a href="#{sido}" class="region-chip">{short} <span class="count">{sido_stats[sido]}</span></a>\n'

    # 지역 섹션
    regions_html = ""
    for sido in sorted_sidos:
        districts = structured[sido]
        count = sido_stats[sido]
        regions_html += f'''
    <section id="{sido}" class="region-section">
      <h2>{sido} 쏘카존 ({count}개)</h2>
'''
        for district in sorted(districts.keys()):
            zs = districts[district]
            regions_html += f'''      <details>
        <summary><h3>{district} ({len(zs)}개)</h3></summary>
        <table>
          <thead><tr><th>쏘카존 이름</th><th>주소</th></tr></thead>
          <tbody>
'''
            for z in zs:
                addr = (z["road_address"] or z["address"]).replace("|", " ")
                regions_html += f'            <tr><td>{z["name"]}</td><td>{addr}</td></tr>\n'
            regions_html += '          </tbody>\n        </table>\n      </details>\n'
        regions_html += '    </section>\n'

    # FAQ
    faq_items = [
        ("쏘카존이란 무엇인가요?", "쏘카존은 쏘카(SOCAR) 카셰어링 서비스의 차량 대여 및 반납 장소입니다. 전국에 약 5,000개 이상의 쏘카존이 운영되고 있으며, 주로 아파트, 오피스텔, 주차장, 역세권 등에 위치해 있습니다."),
        ("쏘카존은 전국에 몇 개 있나요?", f"2026년 3월 기준 전국에 약 {total}개의 쏘카존이 운영 중입니다."),
        ("쏘카존 위치를 찾는 방법은?", "쏘카 공식 앱에서 지도를 통해 가까운 쏘카존을 검색할 수 있습니다. 또한 네이버 지도, 카카오맵에서 '쏘카존'을 검색하면 주변 쏘카존 위치를 확인할 수 있습니다."),
    ]
    faq_html = ""
    faq_schema_items = []
    for q, a in faq_items:
        faq_html += f'''      <details class="faq-item" itemscope itemprop="mainEntity" itemtype="https://schema.org/Question">
        <summary itemprop="name">{q}</summary>
        <div itemscope itemprop="acceptedAnswer" itemtype="https://schema.org/Answer">
          <p itemprop="text">{a}</p>
        </div>
      </details>
'''
        faq_schema_items.append({"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}})

    faq_schema = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": faq_schema_items}

    # llms.txt
    llms_txt = f"# {title}\n\n> {description} — {total}개 쏘카존 위치 정보\n\n"
    llms_txt += "## 지역별 쏘카존 수\n"
    for sido in sorted_sidos:
        llms_txt += f"- {sido}: {sido_stats[sido]}개\n"
    if tag_zones:
        llms_txt += "\n## 관광지 쏘카존\n"
        for tag_name in sorted(tag_zones, key=lambda x: -len(tag_zones[x])):
            llms_txt += f"- {tag_name}: {len(tag_zones[tag_name])}개\n"
    llms_txt += "\n## 이용 안내\n- 쏘카 앱에서 예약 가능\n- 24시간 무인 대여/반납\n- 문의: 1661-3315\n"

    # robots.txt
    robots = """User-agent: *
Allow: /

User-agent: GPTBot
Allow: /

User-agent: Google-Extended
Allow: /

User-agent: ChatGPT-User
Allow: /

User-agent: Claude-Web
Allow: /

User-agent: PerplexityBot
Allow: /

Sitemap: sitemap.xml
"""

    # sitemap.xml
    sitemap = f'''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://socarzone.socar.kr/{slug}/</loc>
    <lastmod>{today}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>'''

    # HTML
    html = f'''<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} | SOCAR Zone - {total}개 쏘카존</title>
  <meta name="description" content="{description} — {total}개 쏘카존 위치를 검색하세요.">
  <meta name="keywords" content="쏘카존, SOCAR Zone, 쏘카존 위치, 카셰어링, {title}">
  <link rel="canonical" href="https://socarzone.socar.kr/{slug}/">
  <meta property="og:title" content="{title} | {total}개 쏘카존">
  <meta property="og:description" content="{description}">
  <meta property="og:type" content="website">
  <meta property="og:locale" content="ko_KR">

  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "Organization",
    "name": "쏘카 (SOCAR)",
    "url": "https://www.socar.kr",
    "contactPoint": {{ "@type": "ContactPoint", "telephone": "1661-3315", "contactType": "customer service" }}
  }}
  </script>
  <script type="application/ld+json">
  {json.dumps(json_ld, ensure_ascii=False, indent=2)}
  </script>
  <script type="application/ld+json">
  {json.dumps(faq_schema, ensure_ascii=False, indent=2)}
  </script>

  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f7fa; color: #1a1a2e; line-height: 1.6; }}
    header {{ background: linear-gradient(135deg, #00b4d8, #0077b6); color: white; padding: 2rem 1rem; text-align: center; }}
    header h1 {{ font-size: 1.8rem; margin-bottom: 0.5rem; }}
    header p {{ opacity: 0.9; font-size: 1rem; }}
    .stats {{ display: flex; justify-content: center; gap: 2rem; margin-top: 1rem; flex-wrap: wrap; }}
    .stat {{ text-align: center; }}
    .stat-num {{ font-size: 2rem; font-weight: bold; }}
    .stat-label {{ font-size: 0.85rem; opacity: 0.8; }}
    main {{ max-width: 1200px; margin: 0 auto; padding: 1.5rem; }}
    .search-box {{ background: white; border-radius: 12px; padding: 1rem; margin-bottom: 1.5rem; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
    .search-box input {{ width: 100%; padding: 0.8rem 1rem; border: 2px solid #e0e0e0; border-radius: 8px; font-size: 1rem; outline: none; }}
    .search-box input:focus {{ border-color: #00b4d8; }}
    .search-info {{ padding: 0.5rem 0; font-size: 0.9rem; color: #666; display:none; }}
    .search-results {{ background: white; border-radius: 12px; padding: 1.5rem; margin-bottom: 1rem; box-shadow: 0 2px 8px rgba(0,0,0,0.05); display:none; }}
    .search-results h2 {{ font-size: 1.2rem; color: #0077b6; margin-bottom: 0.8rem; }}
    mark {{ background: #fff3cd; padding: 0 2px; border-radius: 2px; }}
    .nav-section {{ margin-bottom: 1.5rem; }}
    .nav-section h2 {{ font-size: 1.1rem; margin-bottom: 0.5rem; color: #555; }}
    .chips {{ display: flex; flex-wrap: wrap; gap: 0.5rem; }}
    .region-chip, .tourist-chip {{ display: inline-flex; align-items: center; gap: 4px; padding: 0.4rem 0.8rem; background: white; border: 1px solid #ddd; border-radius: 20px; text-decoration: none; color: #333; font-size: 0.9rem; transition: all 0.2s; }}
    .region-chip:hover {{ background: #00b4d8; color: white; border-color: #00b4d8; }}
    .tourist-chip {{ background: #fff3e0; border-color: #ffcc80; }}
    .tourist-chip:hover {{ background: #ff9800; border-color: #ff9800; color: white; }}
    .count {{ background: #eee; padding: 0 6px; border-radius: 10px; font-size: 0.8rem; }}
    .region-section {{ background: white; border-radius: 12px; padding: 1.5rem; margin-bottom: 1rem; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }}
    .region-section h2 {{ font-size: 1.3rem; color: #0077b6; margin-bottom: 1rem; padding-bottom: 0.5rem; border-bottom: 2px solid #e0f2fe; }}
    details {{ margin-bottom: 0.5rem; }}
    summary {{ cursor: pointer; padding: 0.5rem; border-radius: 6px; background: #f8f9fa; }}
    summary:hover {{ background: #e0f2fe; }}
    summary h3 {{ display: inline; font-size: 1rem; font-weight: 500; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 0.5rem; font-size: 0.9rem; }}
    th {{ background: #f1f5f9; padding: 0.5rem; text-align: left; font-weight: 600; }}
    td {{ padding: 0.5rem; border-bottom: 1px solid #f0f0f0; }}
    tr:hover {{ background: #f8fafe; }}
    .tourist-section {{ background: #fffde7; border-radius: 12px; padding: 1.5rem; margin-bottom: 1rem; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }}
    .tourist-section h3 {{ color: #e65100; margin-bottom: 0.5rem; }}
    .faq-section {{ background: white; border-radius: 12px; padding: 1.5rem; margin-bottom: 1rem; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }}
    .faq-section h2 {{ font-size: 1.3rem; color: #0077b6; margin-bottom: 1rem; }}
    .faq-item {{ margin-bottom: 0.5rem; }}
    .faq-item summary {{ font-weight: 500; padding: 0.7rem; }}
    .faq-item p {{ padding: 0.5rem 0.7rem 0.7rem; color: #555; }}
    footer {{ text-align: center; padding: 2rem 1rem; color: #888; font-size: 0.85rem; }}
    @media (max-width: 768px) {{
      header h1 {{ font-size: 1.4rem; }}
      .stat-num {{ font-size: 1.5rem; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{title}</h1>
    <p>{description}</p>
    <div class="stats">
      <div class="stat"><div class="stat-num">{total:,}</div><div class="stat-label">쏘카존</div></div>
      <div class="stat"><div class="stat-num">{len(sorted_sidos)}</div><div class="stat-label">서비스 지역</div></div>
      <div class="stat"><div class="stat-num">{today}</div><div class="stat-label">업데이트</div></div>
    </div>
  </header>

  <main>
    <div class="search-box">
      <input type="search" id="searchInput" placeholder="쏘카존 이름 또는 주소 검색 (예: 강남역, 해운대)" aria-label="쏘카존 검색">
      <div class="search-info" id="searchInfo"></div>
    </div>

    <nav class="nav-section" id="navRegion">
      <h2>지역별 보기</h2>
      <div class="chips">
{nav_html}      </div>
    </nav>

    {tourist_nav_section}

    <div id="searchResults" class="search-results"></div>

    <section class="faq-section" itemscope itemtype="https://schema.org/FAQPage">
      <h2>자주 묻는 질문</h2>
{faq_html}    </section>

{tourist_html}
{regions_html}
  </main>

  <footer>
    <p>{title} — {today} 기준. 최신 정보는 <a href="https://www.socar.kr">쏘카 공식 사이트</a>에서 확인하세요.</p>
    <p>쏘카 고객센터: 1661-3315</p>
  </footer>

  <script>
  (function() {{
    const zoneData = [];
    document.querySelectorAll('.region-section table tbody tr, .tourist-section table tbody tr').forEach(row => {{
      const cells = row.querySelectorAll('td');
      if (cells.length >= 2) {{
        zoneData.push({{ name: cells[0].textContent, addr: cells[1].textContent, text: (cells[0].textContent + ' ' + cells[1].textContent).toLowerCase() }});
      }}
    }});

    const input = document.getElementById('searchInput');
    const info = document.getElementById('searchInfo');
    const results = document.getElementById('searchResults');
    const sections = document.querySelectorAll('.region-section, .tourist-section, .nav-section, .faq-section');
    let timer;

    input.addEventListener('input', function() {{
      clearTimeout(timer);
      timer = setTimeout(() => doSearch(this.value.trim()), 200);
    }});

    function doSearch(query) {{
      if (query.length < 1) {{
        results.style.display = 'none';
        info.style.display = 'none';
        sections.forEach(s => s.style.display = '');
        return;
      }}
      const keywords = query.toLowerCase().split(/\\s+/).filter(k => k.length > 0);
      const matches = zoneData.filter(z => keywords.every(kw => z.text.includes(kw)));

      info.style.display = 'block';
      info.textContent = `"${{query}}" 검색 결과: ${{matches.length}}개 쏘카존`;

      if (matches.length > 0 && matches.length <= 500) {{
        sections.forEach(s => s.style.display = 'none');
        let html = '<h2>검색 결과 (' + matches.length + '개)</h2><table><thead><tr><th>쏘카존 이름</th><th>주소</th></tr></thead><tbody>';
        matches.slice(0, 100).forEach(m => {{
          let name = m.name, addr = m.addr;
          keywords.forEach(kw => {{
            const re = new RegExp('(' + kw.replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&') + ')', 'gi');
            name = name.replace(re, '<mark>$1</mark>');
            addr = addr.replace(re, '<mark>$1</mark>');
          }});
          html += '<tr><td>' + name + '</td><td>' + addr + '</td></tr>';
        }});
        if (matches.length > 100) html += '<tr><td colspan="2" style="text-align:center;color:#888;">... 외 ' + (matches.length - 100) + '개</td></tr>';
        html += '</tbody></table>';
        results.innerHTML = html;
        results.style.display = 'block';
      }} else if (matches.length > 500) {{
        sections.forEach(s => s.style.display = 'none');
        results.innerHTML = '<p style="padding:1rem;color:#888;">결과가 너무 많습니다. 더 구체적으로 검색해주세요.</p>';
        results.style.display = 'block';
      }} else {{
        sections.forEach(s => s.style.display = '');
        results.innerHTML = '<p style="padding:1rem;color:#888;">검색 결과가 없습니다.</p>';
        results.style.display = 'block';
      }}
    }}
  }})();
  </script>
</body>
</html>'''

    # Write files
    site_dir = os.path.join(out_dir, slug)
    os.makedirs(site_dir, exist_ok=True)

    with open(os.path.join(site_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    with open(os.path.join(site_dir, "llms.txt"), "w", encoding="utf-8") as f:
        f.write(llms_txt)
    with open(os.path.join(site_dir, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(robots)
    with open(os.path.join(site_dir, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write(sitemap)

    # JSON data export
    export = [{"name": z["name"], "address": z["address"], "road_address": z["road_address"],
               "lat": z["lat"], "lng": z["lng"], "sido": z["sido_name"], "sigungu": z["sigungu_name"]}
              for z in zones]
    with open(os.path.join(site_dir, "zones.json"), "w", encoding="utf-8") as f:
        json.dump(export, f, ensure_ascii=False, indent=2)

    print(f"  [{slug}] {total}개 존 → {site_dir}/ (index.html, llms.txt, robots.txt, sitemap.xml, zones.json)")


def main():
    conn = get_conn()

    # 빌드할 프로필 (인자 없으면 전체)
    target_slugs = sys.argv[1:] if len(sys.argv) > 1 else None

    profiles = conn.execute("SELECT * FROM site_profile ORDER BY id").fetchall()
    out_dir = os.path.join(os.path.dirname(__file__), "..", "sites")
    os.makedirs(out_dir, exist_ok=True)

    print(f"사이트 빌드 시작 → {out_dir}/")
    for p in profiles:
        if target_slugs and p["slug"] not in target_slugs:
            continue
        generate_site(conn, p, out_dir)

    conn.close()
    print(f"\n빌드 완료!")


if __name__ == "__main__":
    main()
