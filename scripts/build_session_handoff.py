"""Build a small, deterministic index of synchronized evidence; never grade it.

No network, clock, credentials, or chat access. Original learning notes, accepted
results and immutable question sheets remain the sources of truth.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

import daily_review as review
from run_daily import apply_exclusions

ROOT = Path(__file__).resolve().parents[1]
REPO = 'pkppkqbobs/kaoyan-english-trainer'
GITHUB = 'https://github.com/' + REPO
PAGES = 'https://pkppkqbobs.github.io/kaoyan-english-trainer/'
KINDS = {'user_reported_wrong': '自述错题', 'correct_but_uncertain': '答对但犹豫',
         'user_reported_confusion': '理解困惑', 'translation_difficulty': '翻译困难'}
FOLLOWUP_HEADER = re.compile(r'后续[^：:\n]{0,16}[（(](\d{4}-\d{2}-\d{2})[）)]\s*[：:]\s*')
CATEGORIES = (
    ('paragraph', 'Part B 指代与前后衔接', r'paragraph-order|^reference$|summary-location'),
    ('stance', '作者态度、评价对象与转折', r'author-stance|attribution|viewpoint|tone|paragraph-scope-attitude|social-message'),
    ('scope', '选项范围与额外限定', r'inference|scope|title|absolute|concession'),
    ('roles', '主语—动作—对象与政策条件', r'role|causal|process|applicant|condition|logic|policy|result-direction|parallel-governance|belief-negation|agreement-target|federal-state-boundary|executive-overreach'),
    ('language', '修饰关系与熟词搭配', r'.*'),
)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def short(value, limit=90):
    text = ' '.join(str(value or '').split())
    text = re.sub(r'github_pat_[\w]+|gh[pousr]_[\w]+|Bearer\s+[\w.\-]+|(?<!\d)\d{17}[\dXx](?!\w)',
                  '[已省略敏感值]', text)
    text = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[已省略邮箱]', text)
    text = re.sub(r'(?<!\d)1[3-9]\d{9}(?!\d)', '[已省略电话]', text)
    return text if len(text) <= limit else text[:limit].rstrip() + '…'


def stamp(value):
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise ValueError('Invalid evidence date') from None


class Inputs:
    def __init__(self, root):
        self.root, self.sources, self.warnings = Path(root), {}, set()

    def read(self, path, default, required=False):
        file = self.root / path
        raw = file.read_bytes() if file.exists() else None
        self.sources[path] = hashlib.sha256(raw).hexdigest() if raw is not None else None
        if raw is None:
            if required:
                self.warnings.add(path + ' 缺失，相关状态未验证')
            return default
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError) as error:
            raise ValueError('Invalid handoff input: ' + path) from error
        if not isinstance(value, type(default)):
            raise ValueError('Invalid handoff input type: ' + path)
        return value


def dated_followup(note):
    # Some existing notes append a dated, explicitly reported clarification.
    # Keep it separate so a later vocabulary question never becomes the
    # supposed cause of an earlier wrong choice.
    text = str(note.get('note', ''))
    matches = list(FOLLOWUP_HEADER.finditer(text))
    if not matches:
        return None
    index = max(range(len(matches)), key=lambda i: (stamp(matches[i][1]), matches[i].start()))
    latest = matches[index]
    end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
    return {'date': stamp(latest[1]), 'summary': short(text[latest.end():end], 140)}


def updated(note):
    dates = [stamp(note['date'])]
    for key in ('clarified_on',):
        if note.get(key):
            dates.append(stamp(note[key]))
    for key in ('followup_clarification', 'understanding_clarification', 'subject_action_clarification'):
        if isinstance(note.get(key), dict) and note[key].get('date'):
            dates.append(stamp(note[key]['date']))
    followup = dated_followup(note)
    if followup:
        dates.append(followup['date'])
    return max(dates)


def paper_key(note):
    part = re.sub(r'^Reading\s+', '', note.get('source_part', ''), flags=re.I)
    return note.get('source_exam', ''), part


def source_ref(note):
    return {'path': 'data/learning-notes.json', 'date': note['date'], 'family': note['family'],
            'question': note.get('source_question'),
            'note_fingerprint': note.get('_parent_fingerprint', fingerprint(note)[:16])}


def confirmed(note):
    return note.get('final_choice_letter_confirmed') is not False and note.get('reported_pick') in ('A', 'B', 'C', 'D')


def observation_summary(note):
    clarified = note.get('understanding_clarification', {}).get('confirmed_root_cause')
    roles = note.get('subject_action_clarification', {}).get('direct_user_explanation')
    original = FOLLOWUP_HEADER.split(str(note.get('note', '')), maxsplit=1)[0]
    return short(note.get('user_reported_reasoning') or clarified or roles or original)


def paper_item(note, checks):
    question = note.get('source_question')
    check = checks.get(note.get('source_exam'), {})
    key = check.get('answers', {}).get(str(question)) if question is not None else None
    recorded = note.get('expected', note.get('answer_from_verified_key'))
    status = 'source_checked' if key and (not recorded or key == recorded) else 'conflict' if key and recorded else 'note_only'
    questions = {n['question'] for n in note.get('user_confirmed_reasoning', []) if type(n.get('question')) is int}
    questions.update(n for n in note.get('source_questions', []) if type(n) is int)
    choice_status = 'confirmed' if confirmed(note) else 'unconfirmed' if question is not None or questions else 'not_applicable'
    return {'kind': note['kind'], 'family': note['family'], 'question': question,
            'related_questions': sorted(questions), 'updated_on': updated(note),
            'final_choice': note.get('reported_pick') if confirmed(note) else None,
            'final_choice_status': choice_status,
            'first_considered': note.get('first_considered'),
            'candidate_choices': [c for c in note.get('candidate_choices', []) if c in ('A', 'B', 'C', 'D')],
            'eliminated_choices': [c for c in note.get('eliminated_choices', note.get('reported_eliminations', [])) if c in ('A', 'B', 'C', 'D')],
            'reference_answer': key or recorded, 'reference_status': status,
            'summary': observation_summary(note),
            'followup': dated_followup(note),
            'spans': [short(span, 42) for span in note.get('source_spans', [])[:6]],
            'source': source_ref(note)}


def paper_summary(notes, sessions, checks):
    groups = defaultdict(list)
    for note in notes:
        if note.get('source_exam') and note.get('source_part'):
            groups[paper_key(note)].append(note)
    stages = []
    for (exam, part), entries in groups.items():
        ordered = sorted(entries, key=lambda n: (updated(n), confirmed(n), fingerprint(n)), reverse=True)
        # One current observation per question/kind; multiple boxed spans are
        # merged below without pretending they were additional wrong attempts.
        latest = {}
        for n in ordered:
            identity = ('question', n['source_question']) if n.get('source_question') is not None and n['kind'] != 'translation_difficulty' else (None, n['kind'], n['family'])
            latest.setdefault(identity, n)
        items = []
        for n in latest.values():
            if n['kind'] == 'translation_difficulty':
                continue
            item = paper_item(n, checks)
            picks = {e['reported_pick'] for e in entries if confirmed(e) and updated(e) == updated(n)
                     and e.get('source_question') == n.get('source_question')}
            item['choice_conflict'] = n.get('source_question') is not None and len(picks) > 1
            if item['choice_conflict']:
                item.update(final_choice=None, final_choice_status='unconfirmed')
            items.append(item)
        items.sort(key=lambda n: (-review.NOTE_PRIORITIES.get(n['kind'], 0),
                                  -date.fromisoformat(n['updated_on']).toordinal(), n['question'] is None,
                                  n['question'] or 0, n['family']))
        spans = sorted({short(s, 42) for n in entries if n['kind'] == 'translation_difficulty'
                        for s in n.get('source_spans', [])})
        stages.append({'date': max(updated(n) for n in entries), 'exam': exam, 'part': part,
                       'items': items[:4], 'boxed_spans': spans[:10],
                       'translation_note_count': len([n for n in entries if n['kind'] == 'translation_difficulty']),
                       'translation_source': next((source_ref(n) for n in ordered if n['kind'] == 'translation_difficulty'), None),
                       'article_session_files': sorted({sessions[n['session_id']] for n in entries
                                                        if n.get('session_id') in sessions})})
    return sorted(stages, key=lambda s: (s['date'], s['exam'], s['part']), reverse=True)[:5]


def pending_items(notes, rejected, recent):
    by_question = defaultdict(list)
    for n in notes:
        if n.get('source_question') is not None:
            by_question[(*paper_key(n), n['source_question'])].append(n)
        for detail in n.get('user_confirmed_reasoning', []):
            if detail.get('question') is not None:
                by_question[(*paper_key(n), detail['question'])].append(
                    {**n, 'source_question': detail['question'], **detail,
                     '_parent_fingerprint': fingerprint(n)[:16]})
    pending = []
    for (exam, part, question), entries in sorted(by_question.items()):
        if (exam, part) not in {(s['exam'], s['part']) for s in recent}:
            continue
        last = max(updated(n) for n in entries)
        current = [n for n in entries if updated(n) == last]
        picks = {n['reported_pick'] for n in current if confirmed(n)}
        if len(picks) != 1 and any(n.get('final_choice_letter_confirmed') is False or n['kind'] == 'user_reported_wrong' for n in current):
            pending.append({'exam': exam, 'part': part, 'question': question, 'date': last,
                            'status': '最终选项未确认' if not picks else '同日选项记录冲突，待核对',
                            'source': source_ref(sorted(current, key=fingerprint)[0])})
        if any(n.get('specific_reason_unconfirmed') for n in current):
            pending.append({'exam': exam, 'part': part, 'question': question, 'date': last,
                            'status': '具体改选推理尚未完全确认', 'source': source_ref(sorted(current, key=fingerprint)[0])})
    pending.sort(key=lambda n: (n['date'], n['exam'], n['part'], n['question']), reverse=True)
    for item in rejected.get('issues', []):
        pending.append({'issue': item['issue'], 'status': 'Issue 当前未验证',
                        'retained_previous': bool(item.get('retained_previous')),
                        'source': {'path': 'data/rejected-results.json'}})
    return pending[:10]


def web_results(inputs, evidence, current_day=None):
    snapshots = []
    for module, directory in (('daily', 'data/days'), ('article', 'data/article-reviews')):
        for path in sorted((inputs.root / directory).glob('*.json')):
            rel = str(path.relative_to(inputs.root))
            payload = inputs.read(rel, {})
            snapshots.append((module, rel, payload))
    accepted = set(evidence.get('issues', []))
    groups = defaultdict(list)
    for row in evidence.get('rows', []):
        if row.get('origin') in accepted and not row.get('partb_result'):
            groups[row['origin']].append(row)
    verified, unverified, seen = [], [], set()
    for issue, rows in sorted(groups.items()):
        try:
            days, rounds = {r.get('source_date') for r in rows}, {r.get('round_id') for r in rows}
            if len(days) != 1 or None in days or len(rounds) != 1 or None in rounds:
                raise ValueError('旧汇总或缺少可核验轮次/题号')
            unique = {}
            for row in rows:
                if type(row.get('ok')) is not bool or not isinstance(row.get('qid'), str):
                    raise ValueError('不完整的首次作答')
                stamp(row['date'])
                if row['qid'] in unique and row != unique[row['qid']]:
                    raise ValueError('同题的首次作答冲突')
                unique[row['qid']] = row
            if len(unique) != 8:
                raise ValueError('首次作答不足或超过8个独立题号')
            matches = [(module, path, p) for module, path, p in snapshots
                       if p.get('date') in days and len(p.get('questions', [])) == 8
                       and len({q['id'] for q in p['questions']}) == 8
                       and {q['id'] for q in p['questions']} == set(unique)
                       and all(q['family'] == unique[q['id']]['family'] for q in p['questions'])]
            if len(matches) != 1:
                raise ValueError('未匹配唯一完整的8题快照')
            module, path, payload = matches[0]
            identity = (next(iter(rounds)), next(iter(days)))
            if identity in seen:
                continue
            seen.add(identity)
            known_dates = sorted({r['date'] for r in unique.values() if not r.get('date_unverified')})
            verified.append({'status': 'verified', 'module': module, 'date': stamp(payload['date']),
                             'issue': issue, 'issue_url': GITHUB + '/issues/' + str(issue),
                             'round_id': short(next(iter(rounds)), 80), 'correct': sum(r['ok'] for r in unique.values()),
                             'total': 8, 'uncertain': sum(bool(r.get('uncertain')) for r in unique.values()),
                             'answer_dates': known_dates, 'answer_date_status': 'verified' if all(not r.get('date_unverified') for r in unique.values()) else '未完全确认',
                             'source': path, 'evidence_source': 'data/result-evidence.json'})
        except (KeyError, TypeError, ValueError) as error:
            unverified.append({'issue': issue, 'status': 'complete_round_unverified', 'reason': str(error)})
    # Accepted Issue number records submission order; an old sheet may be
    # completed/submitted later. Never invent its actual answer date.
    verified.sort(key=lambda r: r['issue'], reverse=True)
    latest = {module: next((r for r in verified if r['module'] == module), None)
              for module in ('daily', 'article')}
    latest['current_daily'] = next((r for r in verified if r['module'] == 'daily' and r['date'] == current_day), None)
    return latest, unverified[-5:]


def priorities(items, notes, state, state_valid, as_of):
    groups, labels = defaultdict(list), {q['family']: q.get('skill', q['target']) for q in items}
    for family in sorted({n['family'] for n in notes} | set(state.get('families', {}))):
        s = state.get('families', {}).get(family, {}) if state_valid else {}
        entries = [n for n in notes if n['family'] == family]
        active = entries if not s or s.get('reported_confusion') else []
        weak = bool(s and s.get('due', '9999') <= as_of and s.get('streak', 0) < 2
                    and (s.get('errors') or s.get('slow_or_uncertain')))
        if not active and not weak:
            continue
        def relevance(n):
            age = (date.fromisoformat(as_of) - date.fromisoformat(updated(n))).days
            return (3 * review.note_priority(n) - age, updated(n), fingerprint(n))
        best = max(active, key=relevance, default=None)
        importance = review.note_priority(best) if best else 0
        if best and importance < 1 and not weak:
            continue
        latest = max((updated(n) for n in active), default=s.get('last') or '')
        category, label, _ = next(c for c in CATEGORIES if re.search(c[2], family))
        focus = observation_summary(best) if best else '网页到期且仍有错误或慢答信号，需跨语境复查。'
        groups[(category, label)].append({'family': family, 'label': short(labels.get(family, family), 48),
                                         'focus': focus,
                                         'paper_kind': best['kind'] if best else None,
                                         'latest_observation': latest or None,
                                         'web_errors': s.get('errors'), 'web_streak': s.get('streak'),
                                         'slow_or_uncertain': s.get('slow_or_uncertain'), 'due': s.get('due'),
                                         'source': source_ref(best) if best else {'path': 'data/review-state.json'},
                                         '_rank': (relevance(best)[0] if best else 0, updated(best) if best else latest,
                                                   int(weak), s.get('errors', 0), family)})
    result = []
    for (category, label), members in groups.items():
        members.sort(key=lambda m: m['_rank'], reverse=True)
        result.append({'mechanism': category, 'label': label, '_rank': members[0]['_rank'], 'families': members[:2]})
    result.sort(key=lambda g: g['_rank'], reverse=True)
    for group in result:
        group.pop('_rank')
        for member in group['families']:
            member.pop('_rank')
    return result[:5]


def article_coverage(source, notes, sessions):
    """A successful build is not proof every synchronized article has a round."""
    grouped = defaultdict(list)
    for note in notes:
        if note.get('session_id') and note.get('source_exam') and note.get('source_part'):
            grouped[note['session_id']].append(note)
    coverage = []
    for sid, entries in grouped.items():
        path = sessions.get(sid)
        definition = source.read(path, {}) if path else {}
        revision = definition.get('revision', 1)
        if not isinstance(sid, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{2,120}', sid):
            raise ValueError('Invalid article observation session id')
        if type(revision) is not int or revision < 1:
            raise ValueError('Invalid article coverage revision')
        key = sid if revision == 1 else f'{sid}-r{revision}'
        round_path = 'data/article-reviews/' + key + '.json' if path else None
        payload = source.read(round_path, {}) if round_path else {}
        page_path = 'article-review-' + key + '.html'
        page = source.root / page_path
        if path:
            source.sources[page_path] = hashlib.sha256(page.read_bytes()).hexdigest() if page.is_file() else None
        published = bool(payload.get('storageId') == key and len(payload.get('questions', [])) == 8 and page.is_file())
        coverage.append({'session_id': sid, 'learning_date': min(n['date'] for n in entries),
                         'updated_on': max(updated(n) for n in entries),
                         'exam': entries[0]['source_exam'], 'part': entries[0]['source_part'],
                         'status': 'published' if published else 'missing_round' if path else 'missing_session',
                         'session_file': path, 'round_file': round_path if published else None,
                         'publication_date': payload.get('date') if published else None})
    coverage.sort(key=lambda item: (item['learning_date'], item['session_id']), reverse=True)
    pending = [item for item in coverage if item['status'] != 'published']
    if pending:
        source.warnings.add(f'有{len(pending)}个已登记学习阶段尚无可用文章专项复盘；任务运行成功不代表篇目覆盖完整')
    return {'pending': pending, 'recent': coverage[:8]}


def make_report(root=ROOT):
    source = Inputs(root)
    notes = source.read('data/learning-notes.json', [], required=True)
    if any(not isinstance(n, dict) or not all(n.get(k) for k in ('family', 'date', 'kind')) for n in notes):
        raise ValueError('Malformed learning observation')
    notes = sorted({fingerprint(n): n for n in notes if not n.get('withdrawn')
                    and n.get('status') not in ('withdrawn', 'retracted', 'superseded')}.values(), key=fingerprint)
    for n in notes:
        updated(n)
        if n['kind'] not in KINDS:
            source.warnings.add('存在未知观察类型，见 learning-notes 原记录')
    evidence = source.read('data/result-evidence.json', {}, required=True)
    state = source.read('data/review-state.json', {}, required=True)
    daily = source.read('data/daily.json', {}, required=True)
    rejected = source.read('data/rejected-results.json', {})
    article = source.read('data/article-review.json', {})
    exclusions = source.read('data/quality-exclusions.json', [])
    if not isinstance(evidence.get('issues', []), list) or not isinstance(evidence.get('rows', []), list):
        raise ValueError('Malformed accepted evidence')
    if any(not isinstance(r, dict) for r in evidence.get('rows', [])):
        raise ValueError('Malformed accepted evidence row')
    accepted_ids = set(evidence.get('issues', []))
    if any(type(i) is not int or i <= 0 for i in accepted_ids):
        raise ValueError('Malformed accepted Issue id')
    rows, _ = apply_exclusions([r for r in evidence.get('rows', []) if r.get('origin') in accepted_ids], exclusions)
    evidence = {**evidence, 'rows': rows}
    items = []
    for path in [source.root / 'data/base-bank.json', *sorted((source.root / 'data/questions').glob('*.json'))]:
        source.read(str(path.relative_to(source.root)), [], required=True)
    source.read('data/question-contexts.json', {})
    if (source.root / 'data/base-bank.json').exists():
        items = review.bank(source.root)  # Base exists, so shared loader cannot bootstrap/write it.
    sessions, checks = {}, {}
    for path in sorted((source.root / 'data/article-sessions').glob('*.json')):
        rel = str(path.relative_to(source.root))
        value = source.read(rel, {})
        if value.get('id'):
            sessions[value['id']] = rel
    for path in sorted((source.root / 'data/source-checks').glob('*.json')):
        value = source.read(str(path.relative_to(source.root)), {})
        if value.get('exam'):
            checks[value['exam']] = value
    dates = [stamp(value) for value in (state.get('as_of'), daily.get('date')) if value]
    dates += [updated(n) for n in notes]
    dates += [stamp(r['date']) for r in evidence.get('rows', []) if r.get('origin') in evidence.get('issues', [])]
    as_of = max(dates, default=None)
    valid = bool(items and state.get('as_of') and state.get('as_of') == as_of and state.get('issues') == evidence.get('issues')
                 and state.get('families') == review.make_stats(items, evidence.get('rows', []), notes,
                                                               date.fromisoformat(state['as_of']))
                 and not any(r['issue'] in accepted_ids and not r.get('retained_previous') for r in rejected.get('issues', [])))
    if not valid:
        source.warnings.add('review-state 与当前证据未完成一致性核验；网页掌握度未验证')
    latest, unknown = web_results(source, evidence, daily.get('date'))
    for rejected_issue in rejected.get('issues', []):
        for module, result in list(latest.items()):
            if result and result['issue'] == rejected_issue['issue']:
                if rejected_issue.get('retained_previous'):
                    result['status'] = 'retained_previous'
                else:
                    latest[module] = None
    for exam in sorted({n.get('source_exam') for n in notes if n.get('source_exam')} - set(checks)):
        source.warnings.add(exam + ' 缺 source-check；纸面参考答案仅沿用学习观察，待核对')
    for n in notes:
        if paper_item(n, checks)['reference_status'] == 'conflict':
            source.warnings.add(f"{n.get('source_exam')} {n.get('source_part')} Q{n.get('source_question')} 记录与source-check冲突，待核对")
    current = latest['current_daily']
    recent = paper_summary(notes, sessions, checks)
    coverage = article_coverage(source, notes, sessions)
    return {'schema_version': 1, 'as_of': as_of,
            'source_dates': {'review_state': state.get('as_of'), 'daily_quiz': daily.get('date'),
                             'latest_observation': max((updated(n) for n in notes), default=None)},
            'project': {'name': '2027 考研英语一自适应训练', 'repo': GITHUB,
                        'daily_url': PAGES + 'today.html', 'article_url': PAGES + 'article-review.html',
                        'history_url': PAGES + 'article-reviews.html'},
            'web': {'current_daily_date': daily.get('date'),
                    'current_daily_issue': current['issue'] if current else None,
                    'current_daily_status': 'verified' if valid and current and current['status'] == 'verified' and current['date'] == daily.get('date') else 'unverified',
                    'latest_daily': latest['daily'], 'latest_article': latest['article'],
                    'available_article': {'date': article.get('date'), 'storageId': article.get('storageId'),
                                          'learning_date': article.get('article_session', {}).get('learning_date', article.get('date'))},
                    'unverified_complete_rounds': unknown, 'review_state_status': 'verified' if valid else 'unverified'},
            'recent_paper': recent,
            'article_review_coverage': coverage,
            'priorities': priorities(items, [n for n in notes if paper_item(n, checks)['reference_status'] != 'conflict'], state, valid, as_of or ''),
            'pending': pending_items(notes, rejected, recent), 'warnings': sorted(source.warnings),
            'sources': dict(sorted(source.sources.items())), 'source_fingerprint': fingerprint(source.sources),
            'scope': 'Only synchronized repository evidence. Paper observations are not web attempts, errors or streak.',
            'handoff_is_not_scoring_evidence': True}


def markdown(report):
    def safe(value):
        return re.sub(r'([`*\[\]<>])', r'\\\1', short(value, 100))
    def paper_label(item):
        return safe(item['exam'].replace('-english1', ' 英语一') + ' ' + item['part'])
    p, web = report['project'], report['web']
    lines = ['# 考研英语一跨对话交接', '', f"数据截至 {report['as_of'] or '未知'}；仅索引已同步到仓库的证据。",
             f"[仓库]({p['repo']}) · [每日8题]({p['daily_url']}) · [文章复盘]({p['article_url']}) · [历史复盘]({p['history_url']})", '',
             '## 接续规则', '',
             '普通对话负责解题与错因分析，Work负责GitHub写入、测试、Actions与Pages验收。先读取本摘要，必要时回查原记录；它不替代证据。',
             '画框只表示翻译困难，横线只表示认为重要；未确认的最终选项保持未知。纸质错题、答对犹豫和理解困惑只影响观察与后续训练，不是网页主测。',
             '原始Issue、首次选择、当天锁定8题、历史快照、localStorage与storageId均须保留。不从未同步的聊天、照片或本地未提交作答补造成绩。', '',
             '## 已核验网页进度', '']
    latest = web['latest_daily']
    if latest:
        suffix = '沿用上一版已核验成绩；当前Issue未验证，需复核' if latest['status'] == 'retained_previous' else '来自已接受成绩与唯一已发布题单'
        lines.append(f"最近已接受的完整daily：题单日期{latest['date']}，[Issue #{latest['issue']}]({latest['issue_url']})，{latest['correct']}/{latest['total']}，犹豫标记{latest['uncertain']}题；{suffix}。")
        if latest['answer_date_status'] != 'verified':
            lines.append('实际作答日期未完全确认，不能据此补造跨日掌握日。')
    else:
        lines.append('最近完整daily：未验证；没有足够的已接受首次作答与唯一题单证据。')
    lines.append(f"当前题单日期：{web['current_daily_date'] or '未知'}；完成状态：{'已核验' if web['current_daily_status'] == 'verified' else '未验证'}。即使本轮全对，也不能替代其他机制的后续跨日验证。")
    lines.append('网页errors/streak只使用有效主测口径；不把纸质记录加入，也不把同日重做当成跨日掌握。')
    lines.append('旧汇总的已接受成绩仍保留；不能从缺失题号的旧报告补造完整8题或具体选择。')
    available = web['available_article']
    lines.append(f"当前文章专项：发布日期{available['date'] or '未知'}，对应学习日期{available['learning_date'] or '未知'}；题单已发布不等于已经作答。")
    missing = len(report['article_review_coverage']['pending'])
    lines.append(f'已登记篇目复盘缺口：{missing}个，详见JSON中的article_review_coverage；不能只凭Actions成功判断学习闭环完整。')
    lines.extend(['', '## 最近纸质学习阶段', ''])
    for stage in report['recent_paper']:
        details = []
        for item in stage['items'][:2]:
            question = f"Q{item['question']}" if item['question'] is not None else '/'.join('Q' + str(n) for n in item['related_questions']) or item['family']
            choice = item['final_choice'] or ('最终选项未确认' if item['final_choice_status'] != 'not_applicable' else '词句观察')
            if item['first_considered']:
                choice = '先考虑' + str(item['first_considered']) + '→' + choice
            reference = ('；参考' + str(item['reference_answer']) + ('（待来源核对）' if item['reference_status'] != 'source_checked' else '')) if item['reference_answer'] else ''
            kind_label = '记录待核对' if item['reference_status'] == 'conflict' or item['choice_conflict'] else KINDS.get(item['kind'], '观察')
            details.append(f"{question} {kind_label}：{choice}{reference}。{safe(item['summary'])}")
            if item['followup']:
                details.append('后续补充（不倒推首次原因）：' + safe(item['followup']['summary']))
        if stage['boxed_spans']:
            details.append('画框翻译：' + '、'.join(safe(s) for s in stage['boxed_spans'][:6]) + ('等。' if len(stage['boxed_spans']) > 6 else '。'))
        elif stage['translation_note_count']:
            details.append('另有翻译困难，详见该篇learning-notes。')
        if not stage['article_session_files']:
            details.append('尚无对应article session；不因此遗漏观察。')
        lines.append(f"- {stage['date']}｜{paper_label(stage)}：" + ' '.join(details))
    if not report['recent_paper']:
        lines.append('尚无可定位到年/篇的已同步纸质观察，最近纸质进度未知。')
    lines.extend(['', '## 当前优先机制', '', '以下顺序由现有观察、到期弱项和跨日表现生成；新证据会改变排序，不能把一次答对视为已掌握。'])
    for group in report['priorities']:
        families = '、'.join(m['family'] for m in group['families'])
        lines.append('- ' + group['label'] + '（' + families + '）：' + safe(group['families'][0]['focus']) + ' 网页错误数/streak单列于JSON。')
    lines.extend(['', '## 待确认', ''])
    for item in report['pending']:
        label = f"Issue #{item['issue']}" if 'issue' in item else paper_label(item) + f" Q{item['question']}"
        lines.append('- ' + label + '：' + item['status'] + '。')
    if not report['pending']:
        lines.append('目前没有结构化记录中明确标记的待确认项；没有记录不等于所有问题均已解决。')
    for warning in report['warnings']:
        lines.append('- ' + safe(warning) + '。')
    lines.extend(['', '## 下一对话怎么继续', '',
                  '先围绕最近一篇的真实误读，核对主语、动作、评价对象、转折和选项新增限定；再用少量不同语境题检验，避免复读原文或凭选项长度猜答案。',
                  '若用户补充新照片或最终选项，先核验来源，再交给Work更新观察；需要新文章轮次时另建session，不能覆盖旧轮或当天daily。未同步材料不会自动出现在本摘要中。',
                  '追溯：`data/learning-notes.json`（按日期/篇目/题号及JSON中的note指纹定位）；`data/result-evidence.json`与对应Issue（网页成绩）；`data/review-state.json`（掌握度）；`data/days/`、`data/article-reviews/`（题单）；`data/source-checks/`（答案核验）。',
                  '机器索引：[`data/session-handoff.json`](data/session-handoff.json)。同输入重复生成无差异；摘要本身不参与评分、选题或曝光统计。', ''])
    return '\n'.join(lines)


def build(root=ROOT):
    root = Path(root)
    result = make_report(root)
    outputs = {root / 'data/session-handoff.json': (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode(),
               root / 'SESSION_HANDOFF.md': markdown(result).encode()}
    changed = {p: raw for p, raw in outputs.items() if not p.exists() or p.read_bytes() != raw}
    # Validate and stage both before replacing either; roll back a partial I/O
    # failure so a failed build does not leave mismatched handoff versions.
    with tempfile.TemporaryDirectory(prefix='.handoff-', dir=root) as temporary:
        staged, previous, written = {}, {}, []
        for i, (path, raw) in enumerate(changed.items()):
            previous[path] = path.read_bytes() if path.exists() else None
            staged[path] = Path(temporary) / str(i)
            staged[path].write_bytes(raw)
        try:
            for path, candidate in staged.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(candidate, path)
                written.append(path)
        except OSError:
            for path in reversed(written):
                if previous[path] is None:
                    path.unlink()
                else:
                    rollback = Path(temporary) / 'rollback'
                    rollback.write_bytes(previous[path])
                    os.replace(rollback, path)
            raise
    return result


if __name__ == '__main__':
    output = build()
    missing = len(output['article_review_coverage']['pending'])
    if missing:
        print(f'::warning title=Article review coverage::{missing} synchronized paper stages have no published article round.')
    print(json.dumps({'as_of': output['as_of'], 'source_fingerprint': output['source_fingerprint'],
                      'latest_daily_issue': (output['web']['latest_daily'] or {}).get('issue'),
                      'pending_article_reviews': missing}, ensure_ascii=False))
