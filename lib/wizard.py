"""Testable checklist transformations for terminal and headless frontends."""
from __future__ import annotations
import catalog


def filtered_entries(entries, stack):
    if stack not in ('lerd','standalone'):
        raise ValueError('Development stack must be lerd or standalone')
    ignored=set(catalog.LERD_MANAGED) if stack=='lerd' else {'lerd'}
    return [dict(row) for row in entries if row['id'] not in ignored]


def toggle_selection(selected,entries,action):
    names={r['id'] for r in entries}
    chosen=set(selected)&names
    if action=='all':return names
    if action=='none':return set()
    if action.startswith('cat '):
        category=action[4:].strip()
        subset={r['id'] for r in entries if r['category']==category}
        if not subset:raise ValueError('Unknown category')
        return chosen-subset if subset<=chosen else chosen|subset
    if action.startswith('item '):
        name=action[5:].strip()
        if name not in names:raise ValueError('Unknown package')
        if name in chosen:chosen.remove(name)
        else:chosen.add(name)
        return chosen
    raise ValueError('Unknown selection action')


def preview(rows):
    """Review totals before allowing a system mutation."""
    result={'installed':0,'available':0,'managed':0,'unavailable':0}
    for r in rows:
        if r['status'] not in result:raise ValueError('Unknown plan status')
        result[r['status']]+=1
    result['total']=len(rows)
    return result
