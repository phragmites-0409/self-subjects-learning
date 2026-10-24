"""Persistent vocabulary sessions. Answers are rules-based and user adjudicated."""
import csv
import io
import json
import random
import re
import unicodedata
from collections import Counter

from sqlalchemy import func, or_, select
from app.modules.learning import service as flow
from app.modules.learning.models import LearningEvent
from .models import Alias, Attempt, Sense, SessionWord, VocabularyImport, VocabularySession, Word

DEFAULTS = {"enabled": True, "daily_count": 20, "time": "18:00", "mode": "any",
            "scope": "all", "order": "oldest", "intervals": [1, 3, 7, 15, 30]}


def preferences(db):
    return {**DEFAULTS, **flow.setting(db, "vocabulary", {})}


def save_preferences(db, changes):
    p = {**preferences(db), **{k: v for k, v in changes.items() if k in DEFAULTS}}
    if type(p["enabled"]) is not bool or type(p["daily_count"]) is not int or not 1 <= p["daily_count"] <= 200:
        flow.fail("每日词数须为1–200的整数，开关须为布尔值")
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(p["time"])):
        flow.fail("推送时刻应为HH:MM")
    if p["mode"] not in ("any", "all") or p["scope"] not in ("all", "daily", "exam_3500") or p["order"] not in ("oldest", "alphabetical", "random"):
        flow.fail("单词模式、范围或顺序不正确")
    if not isinstance(p["intervals"], list) or not 1 <= len(p["intervals"]) <= 10 or any(type(x) is not int or not 1 <= x <= 365 for x in p["intervals"]):
        flow.fail("复习间隔须为1–365天的整数列表（1–10阶段）")
    flow.set_setting(db, "vocabulary", p)
    db.commit()
    return p


def normalize(value):
    return "".join(c.casefold() for c in unicodedata.normalize("NFKC", str(value)) if not c.isspace() and not unicodedata.category(c).startswith("P"))


def alternatives(meaning):
    return {normalize(meaning), *(normalize(v) for v in re.split(r"[;；、，,\n/]", meaning) if normalize(v))}


def word_view(db, word):
    senses = db.scalars(select(Sense).where(Sense.word_id == word.id).order_by(Sense.pos, Sense.id)).all()
    return {"id": word.id, "word": word.word, "sources": word.sources, "enabled": word.enabled,
            "status": word.status, "stage": word.stage, "due": word.due, "correct": word.correct, "wrong": word.wrong,
            "senses": [{"id": s.id, "pos": s.pos, "meaning": s.meaning, "enabled": s.enabled,
                        "aliases": [{"id": a.id, "answer": a.answer, "enabled": a.enabled} for a in db.scalars(select(Alias).where(Alias.sense_id == s.id))]} for s in senses]}


def upsert(db, body):
    spelling = unicodedata.normalize("NFKC", str(body.get("word", ""))).strip().casefold()
    if not re.fullmatch(r"[a-z][a-z '\-]{0,119}", spelling):
        flow.fail("请输入英文单词或短语（可含空格、连字符、撇号）")
    source = body.get("source", "daily")
    if source not in ("daily", "exam_3500"):
        flow.fail("单词来源不正确")
    senses = body.get("senses", [])
    if not isinstance(senses, list) or not senses or len(senses) > 100:
        flow.fail("请提供1–100个词性义项")
    cleaned = []
    for s in senses:
        pos, meaning = str(s.get("pos", s.get("part_of_speech", ""))).strip(), str(s.get("meaning", "")).strip()
        if len(pos) > 40 or not normalize(meaning) or len(meaning) > 2000:
            flow.fail("词性过长或中文释义为空/过长")
        cleaned.append((pos, meaning))
    word = db.scalar(select(Word).where(Word.word == spelling))
    created = word is None
    if created:
        word = Word(word=spelling, sources=[source])
        db.add(word)
        db.flush()
    word.sources = sorted(set(word.sources) | {source})
    added = 0
    for pos, meaning in set(cleaned):
        if not db.scalar(select(Sense.id).where(Sense.word_id == word.id, Sense.pos == pos, Sense.meaning == meaning)):
            db.add(Sense(word_id=word.id, pos=pos, meaning=meaning))
            added += 1
    db.flush()
    if added and not created:
        word.status, word.stage, word.due = "new", 0, None
    return word, created, added


def preview_import(db, text, source):
    if len(text) > 2_000_000:
        flow.fail("词表过大，请分批导入")
    records, errors = [], []
    raw = text.strip().lstrip("\ufeff")
    if raw.startswith(("[", "{")):
        try:
            data = json.loads(raw)
            rows = data.get("words", []) if isinstance(data, dict) else data
            if not isinstance(rows, list):
                raise ValueError()
            for n, row in enumerate(rows, 1):
                records.append((n, row))
        except (ValueError, TypeError):
            flow.fail("JSON词表应为数组或包含words数组")
    else:
        for n, line in enumerate(raw.splitlines(), 1):
            line = line.strip().strip("|")
            if not line or line.startswith("#") or re.fullmatch(r"[|:\-\s]+", line):
                continue
            try:
                parts = next(csv.reader([line], delimiter="|" if "|" in line else "\t" if "\t" in line else ","))
                if parts[0].strip().casefold() in ("word", "单词"):
                    continue
                if len(parts) < 3:
                    raise ValueError("每行需要 单词 | 词性 | 中文释义")
                records.append((n, {"word": parts[0].strip(), "senses": [{"pos": parts[1].strip(), "meaning": ",".join(parts[2:]).strip()}]}))
            except (csv.Error, ValueError) as exc:
                errors.append({"line": n, "text": line, "error": str(exc)})
    valid = []
    # Validate using a savepoint: preview never persists words.
    for n, row in records:
        try:
            if not isinstance(row, dict):
                raise ValueError("词条必须为对象")
            entry = {**row, "source": source}
            if "senses" not in entry:
                entry["senses"] = [{"pos": row.get("pos", ""), "meaning": row.get("meaning", "")}]
            with db.begin_nested() as savepoint:
                word, created, added = upsert(db, entry)
                valid.append({**entry, "line": n, "action": "新增" if created else "追加义项" if added else "重复跳过"})
                savepoint.rollback()
        except Exception as exc:
            from app.core.errors import AppError
            if not isinstance(exc, (AppError, ValueError, TypeError, AttributeError)):
                raise
            errors.append({"line": n, "text": str(row), "error": getattr(exc, "message", str(exc))})
    simulated = {}
    for entry in valid:
        spelling = entry["word"].strip().casefold()
        word = db.scalar(select(Word).where(Word.word == spelling))
        existed = spelling in simulated or word is not None
        if spelling not in simulated:
            simulated[spelling] = {(s.pos, s.meaning) for s in db.scalars(select(Sense).where(Sense.word_id == word.id))} if word else set()
        incoming = {(str(s.get("pos", s.get("part_of_speech", ""))).strip(), str(s["meaning"]).strip()) for s in entry["senses"]}
        entry["action"] = "新增" if not existed else "追加义项" if incoming - simulated[spelling] else "重复跳过"
        simulated[spelling].update(incoming)
    item = VocabularyImport(data={"items": valid, "errors": errors, "source": source})
    db.add(item)
    db.commit()
    return {"id": item.id, **item.data}


def confirm_import(db, iid):
    entry = db.get(VocabularyImport, iid)
    if not entry:
        flow.fail("导入预览不存在", status=404)
    if entry.confirmed:
        return entry.data["result"]
    counts = Counter()
    for body in entry.data["items"]:
        _, created, added = upsert(db, body)
        counts["created" if created else "merged" if added else "skipped"] += 1
    result = {**dict(counts), "errors": len(entry.data["errors"])}
    entry.confirmed = True
    entry.data = {**entry.data, "result": result}
    db.commit()
    return result


def snapshot(db, word):
    data = word_view(db, word)
    return {"word": word.word, "senses": [s for s in data["senses"] if s["enabled"]],
            "had_wrong": False}


def ensure_session(db, day=None, force=False, clock=None):
    day = day or flow.today()
    p = preferences(db)
    existing = db.scalar(select(VocabularySession).where(VocabularySession.day == day))
    if existing:
        return existing
    if not p["enabled"] and not force:
        return None
    if clock is None:
        from datetime import datetime, timedelta, timezone
        clock = datetime.now(timezone(timedelta(hours=8))).strftime("%H:%M")
    if not force and clock < p["time"]:
        return None
    unfinished = select(SessionWord.word_id).where(SessionWord.status.in_(["pending", "review", "retry"]))
    carried = db.scalar(select(func.count()).select_from(SessionWord).where(SessionWord.status.in_(["pending", "review", "retry"])))
    capacity = max(0, p["daily_count"] - carried)
    stmt = select(Word).where(Word.enabled.is_(True), Word.status != "mastered", Word.id.notin_(unfinished),
                               or_(Word.status == "new", Word.due <= day))
    if p["scope"] != "all":
        from app.modules.question_bank.service import tagged
        stmt = stmt.where(tagged(Word.sources, p["scope"]))
    words = db.scalars(stmt.order_by(Word.due, Word.created_at, Word.id)).all()
    words = [w for w in words if db.scalar(select(Sense.id).where(Sense.word_id == w.id, Sense.enabled.is_(True)))]
    due = [w for w in words if w.status != "new"]
    new = [w for w in words if w.status == "new"]
    if p["order"] == "alphabetical":
        new.sort(key=lambda w: w.word)
    elif p["order"] == "random":
        random.Random(day).shuffle(new)
    chosen = (due + new)[:capacity]
    if not chosen:
        return None
    session = VocabularySession(day=day, data={"preferences": p})
    db.add(session)
    db.flush()
    for n, w in enumerate(chosen):
        db.add(SessionWord(session_id=session.id, word_id=w.id, position=n, data=snapshot(db, w)))
    event = LearningEvent(key=f"vocabulary:{day}", kind="vocabulary", subject="英语", title=f"英语单词过关 · {len(chosen)}词",
                          day=day, week=flow.week(day), original_deadline=flow.plus(flow.week(day), 6), data={"session_id": session.id})
    db.add(event)
    db.commit()
    return session


def matching(item, answers, mode):
    senses = item.data["senses"]
    expected = senses if mode == "all" else senses[:1]
    if len(answers) != len(expected):
        flow.fail("回答框数量与本轮模式不一致")
    edges = {}
    for n, answer in enumerate(answers):
        normalized = normalize(answer)
        edges[n] = [s["id"] for s in senses if normalized and (mode == "any" or s["pos"] == expected[n]["pos"]) and (
            normalized in alternatives(s["meaning"]) or normalized in {normalize(a["answer"]) for a in s["aliases"] if a["enabled"]})]
    owners = {}
    def visit(n, seen):
        for sid in edges[n]:
            if sid in seen:
                continue
            seen.add(sid)
            if sid not in owners or visit(owners[sid], seen):
                owners[sid] = n
                return True
        return False
    for n in range(len(answers)):
        visit(n, set())
    return {str(n): sid for sid, n in owners.items()}


def session_view(db, sid):
    session = db.get(VocabularySession, sid)
    if not session:
        flow.fail("单词任务不存在", status=404)
    items = db.scalars(select(SessionWord).where(SessionWord.session_id == sid).order_by(SessionWord.position)).all()
    visible = []
    for item in items:
        # Answers are revealed only after an attempt. The browser never receives hidden meanings.
        revealed = item.status in ("review", "passed", "retry")
        senses = item.data["senses"]
        targets = senses if session.data["preferences"]["mode"] == "all" else senses[:1]
        visible.append({"id": item.id, "word": item.data["word"], "status": item.status,
                        "targets": [{"pos": s["pos"] if session.data["preferences"]["mode"] == "all" else "任一义项"} for s in targets],
                        "senses": senses if revealed else [], "last": item.data.get("last"), "had_wrong": item.data.get("had_wrong", False)})
    return {"id": session.id, "day": session.day, "status": session.status,
            "preferences": session.data["preferences"], "items": visible,
            "completed": sum(i.status == "passed" for i in items), "total": len(items)}


def complete_word(db, item, session, day):
    word = db.get(Word, item.word_id)
    intervals = session.data["preferences"]["intervals"]
    word.correct += 1
    if item.data.get("had_wrong"):
        word.status, word.stage, word.due = "learning", 0, flow.plus(day, 1)
    elif word.status == "new":
        word.status, word.stage, word.due = "learning", 0, flow.plus(day, intervals[0])
    elif word.stage + 1 >= len(intervals):
        word.status, word.due = "mastered", None
    else:
        word.stage += 1
        word.due = flow.plus(day, intervals[word.stage])
    item.status = "passed"
    db.flush()
    if not db.scalar(select(SessionWord.id).where(SessionWord.session_id == session.id, SessionWord.status.in_(["pending", "review", "retry"]))):
        session.status = "completed"
        event = db.scalar(select(LearningEvent).where(LearningEvent.key == f"vocabulary:{session.day}"))
        if event and event.status != "abandoned":
            event.status, event.completed_day = "completed", day


def answer(db, iid, answers, request_key, day=None):
    day = day or flow.today()
    previous = db.scalar(select(Attempt).where(Attempt.request_key == request_key))
    item = db.get(SessionWord, iid)
    if not item:
        flow.fail("单词记录不存在", status=404)
    if previous:
        if previous.item_id != iid:
            flow.fail("请求标识已用于其他回答")
        return session_view(db, item.session_id)
    session = db.get(VocabularySession, item.session_id)
    if item.status not in ("pending", "retry") or session.status != "open":
        flow.fail("请先裁决当前答案，或该词已完成")
    answers = [str(a).strip() for a in answers]
    if any(not normalize(a) or len(a) > 1000 for a in answers):
        flow.fail("每个回答均须填写且不能超过1000字")
    matched = matching(item, answers, session.data["preferences"]["mode"])
    attempt = Attempt(item_id=iid, request_key=request_key, data={"answers": answers, "matched": matched, "day": day, "decision": "automatic" if len(matched) == len(answers) else "pending"})
    db.add(attempt)
    db.flush()
    item.data = {**item.data, "last": {"id": attempt.id, **attempt.data}}
    if len(matched) == len(answers):
        complete_word(db, item, session, day)
    else:
        item.status = "review"
    db.commit()
    return session_view(db, session.id)


def adjudicate(db, iid, accepted, corrections, day=None):
    day = day or flow.today()
    item = db.get(SessionWord, iid)
    if not item or item.status != "review":
        flow.fail("该词没有待人工判断的回答")
    session = db.get(VocabularySession, item.session_id)
    last = item.data["last"]
    attempt = db.get(Attempt, last["id"])
    senses = json.loads(json.dumps(item.data["senses"]))
    answers = last["answers"]
    if accepted:
        used_answers, used_senses = set(), set()
        for mapping in corrections:
            n, sid = mapping["answer_index"], mapping["sense_id"]
            sense = next((s for s in senses if s["id"] == sid), None)
            if not sense or not 0 <= n < len(answers) or n in used_answers or sid in used_senses:
                flow.fail("请将认可答案一对一关联到本轮义项")
            if session.data["preferences"]["mode"] == "all" and sense["pos"] != senses[n]["pos"]:
                flow.fail("认可答案的词性须与回答框相同")
            used_answers.add(n); used_senses.add(sid)
            normalized = normalize(answers[n])
            current = db.get(Sense, sid)
            if current and current.pos == sense["pos"] and current.meaning == sense["meaning"]:
                alias = db.scalar(select(Alias).where(Alias.sense_id == sid, Alias.normalized == normalized))
                if not alias:
                    alias = Alias(sense_id=sid, answer=answers[n], normalized=normalized)
                    db.add(alias)
                alias.enabled = True
            sense["aliases"].append({"answer": answers[n], "enabled": True})
        item.data = {**item.data, "senses": senses}
        matched = matching(item, answers, session.data["preferences"]["mode"])
        if len(matched) != len(answers):
            flow.fail("仍有未匹配义项，请补充关联或选择答错重练")
        attempt.data = {**attempt.data, "decision": "accepted", "corrections": corrections}
        complete_word(db, item, session, day)
    else:
        word = db.get(Word, item.word_id)
        word.wrong += 1
        word.status, word.stage, word.due = "learning", 0, flow.plus(day, 1)
        item.data = {**item.data, "had_wrong": True}
        item.status = "retry"
        attempt.data = {**attempt.data, "decision": "wrong"}
    item.data = {**item.data, "last": {"id": attempt.id, **attempt.data}}
    db.commit()
    return session_view(db, session.id)
