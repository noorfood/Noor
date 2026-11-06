#!/usr/bin/env python3
"""Check manually prepared migration rehearsal controls. Never imports data."""
import argparse
import json
if __package__:
    from .finance_rehearsal import InvalidInput, money, text
else:
    from finance_rehearsal import InvalidInput, money, text

def count(value):
    if type(value) is not int or value < 0:
        raise InvalidInput('Counts must be non-negative integers.')
    return value

def evaluate(data):
    if not isinstance(data, dict):
        raise InvalidInput('Expected an object.')
    text(data.get('source_snapshot_id'), 'Source snapshot ID')
    text(data.get('target_snapshot_id'), 'Target snapshot ID')
    if data['source_snapshot_id'] == data['target_snapshot_id']:
        raise InvalidInput('Source and target snapshot IDs must differ.')
    text(data.get('mapping_version'), 'Mapping version')
    tables = data.get('tables')
    if not isinstance(tables, list) or not tables:
        raise InvalidInput('At least one table mapping is required.')
    seen, issues = set(), []
    for table in tables:
        if not isinstance(table, dict):
            raise InvalidInput('Invalid table mapping.')
        name = text(table.get('source_table'), 'Source table')
        if name in seen:
            raise InvalidInput('Duplicate source table.')
        seen.add(name)
        text(table.get('mapping_reference'), 'Mapping reference')
        source = count(table.get('source_count'))
        imported = count(table.get('target_count'))
        excluded = count(table.get('excluded_count'))
        unresolved = count(table.get('unresolved_count'))
        if excluded:
            text(table.get('exclusion_approval_reference'), 'Exclusion approval reference')
        if source != imported + excluded + unresolved:
            issues.append(name + ':count_mismatch')
        if unresolved:
            issues.append(name + ':unresolved')
        controls = table.get('controls')
        if not isinstance(controls, list) or not controls:
            raise InvalidInput('Each table must include at least one unit-specific control.')
        units = set()
        for control in controls:
            if not isinstance(control, dict):
                raise InvalidInput('Invalid control.')
            unit = text(control.get('unit'), 'Control unit')
            if unit in units:
                raise InvalidInput('Duplicate unit control.')
            units.add(unit)
            source_ref = text(control.get('source_reference'), 'Source control reference')
            target_ref = text(control.get('target_reference'), 'Target control reference')
            if source_ref == target_ref:
                raise InvalidInput('Source and target control references must differ.')
            # Explicit excluded and unresolved amounts avoid silently declaring
            # a source-to-target match when records were not imported.
            src = money(control.get('source_total'))
            dest = money(control.get('target_total'))
            omit = money(control.get('excluded_total'))
            pending = money(control.get('unresolved_total'))
            if src != dest + omit + pending:
                issues.append(name + ':control_mismatch:' + unit)
            if (excluded == 0 and omit != 0) or (unresolved == 0 and pending != 0):
                issues.append(name + ':unexplained_control:' + unit)
    return {'status': 'blocked' if issues else 'rehearsal_controls_match', 'issues': issues,
            'limitations': 'Manual assertions only; not an import, completeness proof, sign-off, or authorization for cutover.'}

def main():
    parser = argparse.ArgumentParser(description='Check fictional manual migration rehearsal controls; no database access.')
    parser.add_argument('json_file')
    args = parser.parse_args()
    try:
        with open(args.json_file, encoding='utf-8') as f:
            result = evaluate(json.load(f))
        print(json.dumps(result, indent=2))
        if result['status'] == 'blocked':
            raise SystemExit(1)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(2, 'Invalid manifest: ' + str(exc) + '\n')

if __name__ == '__main__':
    main()
