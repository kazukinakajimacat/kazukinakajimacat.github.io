#!/usr/bin/env python3
"""note・しずかなインターネット・LinkedIn（記事のみ）の投稿を集めて data/posts.json に保存する。

- note は公開API、しずかなインターネットは記事一覧APIから自動で取る。
- 2025年1月1日以降の記事だけを載せる（SINCE）。
- LinkedIn は data/linkedin.json（手で足すリスト）を読み込む。
- 既存の posts.json に「足していく」方式。取得に失敗した配信元があっても、前回までの記事は消さない。
- 標準ライブラリだけで動く（GitHub Actions でもローカルでも python3 scripts/collect_posts.py で実行）。
- 過去分を全部取り直したいときは --full を付ける。
"""
import json
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
DATA = Path(__file__).resolve().parent.parent / "data"
OUT = DATA / "posts.json"
LINKEDIN_LIST = DATA / "linkedin.json"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"

NOTE_USER = "yakitori_marinos"
SIZU_USER = "kazu_yakitori"
SIZU_USER_ID = 21558
SINCE = "2025-01-01"  # これより前の記事は載せない


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def jst_iso(dt):
    return dt.astimezone(JST).isoformat(timespec="seconds")


def collect_note():
    posts, page = [], 1
    while page <= 50:
        d = json.loads(get(f"https://note.com/api/v2/creators/{NOTE_USER}/contents?kind=note&page={page}"))["data"]
        for c in d["contents"]:
            if not c.get("publishAt") or c.get("status") not in (None, "published"):
                continue
            posts.append({
                "source": "note",
                "title": c["name"],
                "url": c["noteUrl"],
                "date": jst_iso(datetime.fromisoformat(c["publishAt"])),
            })
        if d.get("isLastPage", True):
            break
        page += 1
    return posts


def collect_sizu(known=frozenset()):
    # 公開ページが使っている記事一覧API（1ページ18件）。2025年より前に届くか、
    # 1ページまるごと取り込み済みの記事だったらそこで止める（普段は1ページで終わる）。
    posts, page = [], 1
    while page and page <= 100:
        q = urllib.parse.quote(json.dumps({"0": {"userId": SIZU_USER_ID, "pageNumber": page}}, separators=(",", ":")))
        d = json.loads(get(f"https://sizu.me/api/trpc/postList.index?batch=1&input={q}"))[0]["result"]["data"]
        d = d.get("json", d)
        got = []
        for x in d["posts"]:
            if x.get("visibility") != "ANYONE" or not x.get("firstPublishedAt"):
                continue
            got.append({
                "source": "sizu",
                "title": (x.get("title") or "").strip() or "（無題）",
                "url": f"https://sizu.me/{SIZU_USER}/posts/{x['slug']}",
                "date": jst_iso(datetime.fromisoformat(x["firstPublishedAt"]["iso"].replace("Z", "+00:00"))),
            })
        posts += got
        if not got or all(p["url"] in known for p in got) or min(p["date"] for p in got) < SINCE:
            break
        page = d.get("nextPage")
    return posts


def collect_linkedin():
    # LinkedIn は自動アクセスを弾く（規約でも自動収集は禁止）ので、data/linkedin.json に手で足した記事を読む。
    # 形式: [{"title": "...", "url": "https://www.linkedin.com/pulse/...", "date": "2026-09-27"}, ...]
    if not LINKEDIN_LIST.exists():
        return []
    posts = []
    for p in json.loads(LINKEDIN_LIST.read_text("utf-8")):
        posts.append({
            "source": "linkedin",
            "title": p["title"].strip(),
            "url": p["url"].strip(),
            "date": jst_iso(datetime.fromisoformat(p["date"]).replace(tzinfo=JST)),
        })
    return posts


def main():
    old = json.loads(OUT.read_text("utf-8")) if OUT.exists() else {"posts": []}
    merged = {p["url"]: p for p in old.get("posts", [])}
    failed = []
    # --full のときは取り込み済みでも止まらず、2025年まで全部さかのぼる
    known = frozenset() if "--full" in sys.argv else frozenset(merged)
    sources = (("note", collect_note), ("sizu", lambda: collect_sizu(known)), ("linkedin", collect_linkedin))
    for name, fn in sources:
        try:
            got = fn()
            for p in got:
                merged[p["url"]] = p
            print(f"{name}: {len(got)} 件", file=sys.stderr)
        except Exception as e:  # 1つ失敗しても他は続ける
            failed.append(name)
            print(f"{name}: 取得失敗 {e!r}", file=sys.stderr)

    posts = sorted((p for p in merged.values() if p["date"] >= SINCE), key=lambda p: p["date"], reverse=True)
    if posts == old.get("posts"):
        print("変更なし", file=sys.stderr)
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"updated": jst_iso(datetime.now(JST)), "posts": posts},
                              ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(f"保存しました: {len(posts)} 件", file=sys.stderr)
    if len(failed) >= 2:  # note と sizu の両方が落ちたら Actions を失敗にして気づけるように
        sys.exit(1)


if __name__ == "__main__":
    main()
