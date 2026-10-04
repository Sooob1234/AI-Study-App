"""A real end-to-end check of summaries, with a real open model.

Run on GitHub's servers (see .github/workflows/live-checks.yml) with Ollama
serving the model named in AI_MODEL. A small Persian study text is stored as
a processed source, summarised through the app, and the result printed.
"""

import json
import sys
import time

PAGES = [
    [
        "1 جزوه نمونه درست نویسی",
        "1- حشو و انواع آن",
        "حشو یعنی آوردن واژه یا عبارتی که معنای آن پیش از این در جمله آمده است",
        "و حذف آن به معنای جمله آسیبی نمی زند. نویسنده باید بداند که هر حشوی نادرست نیست.",
        "1 -1 - حشو ملیح",
        "حشوی است که به زیبایی سخن می افزاید و معمولا دعا یا توضیحی کوتاه است.",
        "مثال: استاد، که عمرش دراز باد، امروز به کلاس آمد. این نوع حشو پذیرفته است.",
        "1 -2- حشو متوسط",
        "حشوی است که نه به زیبایی جمله کمک می کند و نه آن را زشت می سازد.",
        "مثال: او با چشم خود دید. بهتر است در نوشته رسمی حذف شود.",
    ],
    [
        "2 جزوه نمونه درست نویسی",
        "1 -3- حشو قبیح",
        "حشوی است که تکرار بی فایده است و نوشته را سست می کند. باید همیشه حذف شود.",
        "نمونه ها: سوال پرسیدن به جای پرسیدن، فریضه واجب به جای فریضه،",
        "سال عام الفیل به جای عام الفیل، شب لیله القدر به جای لیله القدر.",
        "توجه: در آزمون ها بیشترین پرسش از همین نوع می آید.",
    ],
    [
        "3 جزوه نمونه درست نویسی",
        "2- جمع بستن اسم",
        "در فارسی اسم را با نشانه های گوناگون جمع می بندند و هر نشانه جای خود را دارد.",
        "2 -1 - جمع با ها",
        "نشانه ها برای همه اسم ها درست است: کتاب ها، درخت ها، استادها.",
        "2 -2- جمع با ان",
        "نشانه ان بیشتر برای جانداران به کار می رود: درختان، استادان، دانشجویان.",
        "2 -3- جمع با ات",
        "نشانه ات عربی است و آوردن آن با واژه فارسی نادرست است.",
        "نادرست: پیشنهادات، گزارشات، آزمایشات. درست: پیشنهادها، گزارش ها، آزمایش ها.",
    ],
]


def notice(title: str, message: str) -> None:
    text = str(message).replace("\n", " ⏎ ")
    for index in range(0, max(1, len(text)), 3000):
        print(f"::notice title={title} {index // 3000 + 1}::{text[index:index + 3000]}", flush=True)


def add_source(project_id: int, user_id: int) -> int:
    """Store the sample as a processed PDF source.

    PDF extraction is checked elsewhere; here the pages are stored directly
    and only the chunking and the summary are real.
    """
    from sqlalchemy import insert

    from app.api.source_chunks import save_chunks
    from app.core.database import SessionLocal
    from app.models.source import SourceDB, project_sources
    from app.models.source_page import SourcePageDB
    from app.services.chunking import build_chunks

    pages = [(number, "\n".join(lines)) for number, lines in enumerate(PAGES, start=1)]

    db = SessionLocal()
    try:
        source = SourceDB(
            user_id=user_id, title="sample.pdf", source_type="PDF",
            page_count=len(pages), status="READY", language="fa",
        )
        db.add(source)
        db.flush()
        db.execute(insert(project_sources).values(project_id=project_id, source_id=source.id))
        for number, text in pages:
            db.add(SourcePageDB(source_id=source.id, page_number=number, text=text))
        save_chunks(db, source.id, build_chunks(pages))
        db.commit()
        return source.id
    finally:
        db.close()


def main() -> int:
    from fastapi.testclient import TestClient

    from app.ai import llm
    from app.main import app

    client = TestClient(app)
    client.post("/auth/register", json={
        "name": "Live check", "email": "live@example.com", "password": "live-check-pass",
    })
    token = client.post("/auth/login", data={
        "username": "live@example.com", "password": "live-check-pass",
    }).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    project_id = client.post("/projects/", json={"title": "Live"}, headers=headers).json()["id"]

    notice("summary ai status", client.get("/ai/status", headers=headers).json())

    user_id = client.get("/auth/me", headers=headers).json()["id"]
    source = client.get(f"/sources/{add_source(project_id, user_id)}", headers=headers).json()
    chunks = client.get(f"/sources/{source['id']}/chunks/", headers=headers).json()
    notice("summary source", f"chunks={[c['heading'] for c in chunks]}")

    failed = False
    for mode in ("SOURCE_ONLY", "SOURCE_PLUS_AI"):
        started = time.time()
        created = client.post(
            f"/projects/{project_id}/outputs/",
            json={"goal_type": "SUMMARY", "mode": mode, "source_ids": [source["id"]]},
            headers=headers,
        )
        if created.status_code != 200:
            notice(f"summary {mode}", f"CREATE FAILED {created.status_code} {created.text}")
            return 1

        while True:
            output = client.get(f"/outputs/{created.json()['id']}", headers=headers).json()
            if output["status"] != "PROCESSING" or time.time() - started > 3000:
                break
            time.sleep(3)

        content = output["content"] or {}
        notice(
            f"summary {mode} result",
            f"model={llm.model_name()} status={output['status']} detail={output['status_detail']} "
            f"took={time.time() - started:.0f}s parts={output['progress_done']}/{output['progress_total']} "
            f"coverage={[(c['title'], c['status']) for c in content.get('coverage', [])]}",
        )
        notice(f"summary {mode} content", json.dumps(content, ensure_ascii=False))

        sections = content.get("sections", [])
        points = sum(len(s["key_points"]) for s in sections)
        if output["status"] != "READY" or len(sections) != 2 or points < 4 or not content.get("overview"):
            notice(f"summary {mode} verdict", "NOT AS EXPECTED")
            failed = True
        if mode == "SOURCE_ONLY" and any(s["ai_notes"] for s in sections):
            notice(f"summary {mode} verdict", "ai_notes present in SOURCE_ONLY")
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
