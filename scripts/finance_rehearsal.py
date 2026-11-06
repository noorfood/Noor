#!/usr/bin/env python3
"""Isolated, manual finance rehearsal. Not integrated with application ledgers.

Only use fictional figures in this development build. Matching declared controls
and sign-offs are assertions, not verified evidence or accounting approval.
"""
import argparse
import json
from datetime import date
from decimal import Decimal, InvalidOperation

BUCKETS = ('gross_sales', 'sales_returns_discounts', 'cost_of_sales',
           'operating_expenses', 'other_income', 'other_expenses', 'tax')
BALANCES = ('cash', 'bank', 'inventory', 'receivables', 'payables')

class InvalidInput(ValueError):
    pass

def money(value):
    # JSON decimals must be strings, never floats; negative values belong in
    # an appropriate category and are not silently interpreted here.
    if not isinstance(value, str):
        raise InvalidInput('Amounts must be decimal strings.')
    try:
        n = Decimal(value)
    except InvalidOperation:
        raise InvalidInput('Invalid amount.') from None
    if not n.is_finite() or n < 0 or n.as_tuple().exponent < -2 or n > Decimal('999999999999999.99'):
        raise InvalidInput('Amounts must be non-negative, finite and at most two decimal places.')
    return n

def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise InvalidInput(f'{name} is required.')
    return value.strip()

def day(value):
    if not isinstance(value, str):
        raise InvalidInput('Dates must use YYYY-MM-DD.')
    try:
        result = date.fromisoformat(value)
    except ValueError:
        raise InvalidInput('Dates must use YYYY-MM-DD.') from None
    if result.isoformat() != value:
        raise InvalidInput('Dates must use YYYY-MM-DD.')
    return result

def evaluate(data):
    if not isinstance(data, dict):
        raise InvalidInput('Expected an object.')
    start, end = day(data.get('period_start')), day(data.get('period_end'))
    if start > end:
        raise InvalidInput('Period start is after period end.')
    if data.get('currency') != 'NGN':
        raise InvalidInput('Expected NGN.')
    policy = data.get('policy')
    if not isinstance(policy, dict):
        raise InvalidInput('Policy is required.')
    for name in ('revenue_recognition', 'costing_method', 'returns_discounts', 'tax_treatment', 'expenses_and_other_items'):
        text(policy.get(name), name)
    # Explicit declarations are not authentication, evidence or real approval.
    signoffs = data.get('signoffs')
    if not isinstance(signoffs, dict):
        raise InvalidInput('Signoffs are required.')
    for role in ('management', 'accountant'):
        text(signoffs.get(role), role + ' signoff')
    lines, controls, balances = data.get('lines'), data.get('controls'), data.get('balances')
    if not isinstance(lines, list) or not isinstance(controls, dict) or set(controls) != set(BUCKETS):
        raise InvalidInput('Every income and expense control must be provided.')
    sums = {k: Decimal('0') for k in BUCKETS}
    refs = set()
    for line in lines:
        if not isinstance(line, dict) or line.get('category') not in sums:
            raise InvalidInput('Invalid line category.')
        ref = text(line.get('reference'), 'Line reference')
        if ref in refs:
            raise InvalidInput('Duplicate line reference.')
        refs.add(ref)
        sums[line['category']] += money(line.get('amount'))
    differences = []
    for key in BUCKETS:
        control = controls[key]
        if not isinstance(control, dict):
            raise InvalidInput('Control must be an object.')
        control_ref = text(control.get('reference'), 'Control reference')
        if control_ref in refs:
            raise InvalidInput('A control reference cannot also be a line reference.')
        expected = money(control.get('amount'))
        if expected != sums[key]:
            differences.append('control:' + key)
    if not isinstance(balances, dict) or set(balances) != {'opening', 'closing'}:
        raise InvalidInput('Opening and closing balance checks are required.')
    for side in ('opening', 'closing'):
        group = balances[side]
        if not isinstance(group, dict) or set(group) != set(BALANCES):
            raise InvalidInput('All balance checks must be provided.')
        for category in BALANCES:
            entry = group[category]
            if not isinstance(entry, dict):
                raise InvalidInput('Balance check must be an object.')
            actual_ref = text(entry.get('ledger_reference'), 'Ledger reference')
            evidence_ref = text(entry.get('evidence_reference'), 'Evidence reference')
            if actual_ref == evidence_ref:
                raise InvalidInput('Ledger and evidence references must differ.')
            if money(entry.get('ledger_amount')) != money(entry.get('evidence_amount')):
                differences.append('balance:' + side + ':' + category)
    if differences:
        return {'status': 'blocked', 'differences': differences, 'profit': None}
    net_sales = sums['gross_sales'] - sums['sales_returns_discounts']
    gross_profit = net_sales - sums['cost_of_sales']
    operating_profit = gross_profit - sums['operating_expenses']
    before_tax = operating_profit + sums['other_income'] - sums['other_expenses']
    result = before_tax - sums['tax']
    def fmt(n):
        return format(n, '.2f')
    return {'status': 'draft_rehearsal_only', 'period_start': start.isoformat(), 'period_end': end.isoformat(),
            'currency': 'NGN', 'net_sales': fmt(net_sales), 'gross_profit': fmt(gross_profit),
            'operating_profit': fmt(operating_profit), 'profit_before_tax': fmt(before_tax), 'profit_after_tax': fmt(result),
            'limitations': 'Self-declared controls and signoffs are not verified. Not a posted or approved financial report.'}

def main():
    parser = argparse.ArgumentParser(description='Calculate a fictional offline finance rehearsal, not a financial report.')
    parser.add_argument('json_file')
    args = parser.parse_args()
    try:
        with open(args.json_file, encoding='utf-8') as f:
            result = evaluate(json.load(f))
        print(json.dumps(result, indent=2))
        if result['status'] == 'blocked':
            raise SystemExit(1)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(2, 'Invalid rehearsal input: ' + str(exc) + '\n')

if __name__ == '__main__':
    main()
