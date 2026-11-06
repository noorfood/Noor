import copy
from unittest import TestCase
from scripts.finance_rehearsal import BUCKETS, BALANCES, InvalidInput, evaluate
from scripts.migration_manifest import evaluate as evaluate_migration


def finance_input():
    amounts = ['10000.00','500.00','6000.00','1200.00','200.00','100.00','300.00']
    return {'period_start': '2026-01-01', 'period_end': '2026-01-31', 'currency':'NGN',
            'policy': {x:'Example only' for x in ('revenue_recognition','costing_method','returns_discounts','tax_treatment','expenses_and_other_items')},
            'signoffs': {'management':'Example', 'accountant':'Example'},
            'lines':[{'reference':'line-'+k,'category':k,'amount':n} for k,n in zip(BUCKETS, amounts)],
            'controls':{k:{'reference':'control-'+k,'amount':n} for k,n in zip(BUCKETS,amounts)},
            'balances':{side:{k:{'ledger_reference':f'{side}-{k}-ledger','evidence_reference':f'{side}-{k}-evidence','ledger_amount':'100.00','evidence_amount':'100.00'} for k in BALANCES} for side in ('opening','closing')}}

def migration_input():
    return {'source_snapshot_id':'fictional-source', 'target_snapshot_id':'fictional-target', 'mapping_version':'example-v1',
            'tables':[{'source_table':'example', 'mapping_reference':'example-map', 'source_count':4,'target_count':3,'excluded_count':1,'unresolved_count':0,
            'exclusion_approval_reference':'fictional-approval','controls':[{'unit':'NGN','source_reference':'source-report','target_reference':'target-report','source_total':'10.00','target_total':'7.00','excluded_total':'3.00','unresolved_total':'0.00'}]}]}

class FinanceRehearsalTests(TestCase):
    def test_provisional_arithmetic(self):
        result=evaluate(finance_input())
        self.assertEqual(result['status'],'draft_rehearsal_only')
        self.assertEqual((result['net_sales'],result['gross_profit'],result['operating_profit'],result['profit_before_tax'],result['profit_after_tax']),('9500.00','3500.00','2300.00','2400.00','2100.00'))

    def test_a_control_mismatch_blocks_result(self):
        obj=finance_input(); obj['controls']['gross_sales']['amount']='10001.00'
        result=evaluate(obj)
        self.assertEqual(result['status'],'blocked'); self.assertIsNone(result['profit'])

    def test_balance_mismatch_blocks_result(self):
        obj=finance_input(); obj['balances']['opening']['bank']['evidence_amount']='0.00'
        self.assertEqual(evaluate(obj)['differences'],['balance:opening:bank'])

    def test_missing_data_and_duplicate_references_rejected(self):
        obj=finance_input(); del obj['controls']['tax']
        with self.assertRaises(InvalidInput): evaluate(obj)
        obj=finance_input(); obj['lines'][1]['reference']=obj['lines'][0]['reference']
        with self.assertRaises(InvalidInput): evaluate(obj)
        obj=finance_input(); del obj['balances']['closing']['inventory']
        with self.assertRaises(InvalidInput): evaluate(obj)

    def test_invalid_money_and_date_rejected(self):
        for amount in ('NaN','Infinity','-1','0.001',10.1,True):
            obj=finance_input(); obj['lines'][0]['amount']=amount
            with self.assertRaises(InvalidInput): evaluate(obj)
        obj=finance_input(); obj['period_start']='2026-02-01'
        with self.assertRaises(InvalidInput): evaluate(obj)

    def test_unapproved_policy_fields_not_inferred(self):
        obj=finance_input(); obj['policy']['costing_method']=' '
        with self.assertRaises(InvalidInput): evaluate(obj)
        obj=finance_input(); obj['signoffs']['accountant']=''
        with self.assertRaises(InvalidInput): evaluate(obj)

    def test_self_referencing_evidence_rejected(self):
        obj=finance_input(); obj['balances']['opening']['bank']['evidence_reference']=obj['balances']['opening']['bank']['ledger_reference']
        with self.assertRaises(InvalidInput): evaluate(obj)
        obj=finance_input(); obj['controls']['gross_sales']['reference']=obj['lines'][0]['reference']
        with self.assertRaises(InvalidInput): evaluate(obj)

    def test_negative_profit_retained(self):
        obj=finance_input(); obj['lines'][2]['amount']='20000.00'; obj['controls']['cost_of_sales']['amount']='20000.00'
        self.assertEqual(evaluate(obj)['profit_after_tax'],'-11900.00')

class MigrationManifestTests(TestCase):
    def test_rehearsal_does_not_claim_cutover(self):
        result=evaluate_migration(migration_input())
        self.assertEqual(result['status'],'rehearsal_controls_match')
        self.assertIn('not an import', result['limitations'])

    def test_unresolved_and_mismatches_block(self):
        obj=migration_input(); t=obj['tables'][0]; t['unresolved_count']=1
        result=evaluate_migration(obj)
        self.assertEqual(result['status'],'blocked')
        self.assertIn('example:count_mismatch', result['issues']); self.assertIn('example:unresolved',result['issues'])
        obj=migration_input(); obj['tables'][0]['controls'][0]['target_total']='6.99'
        self.assertIn('example:control_mismatch:NGN', evaluate_migration(obj)['issues'])

    def test_reject_unapproved_exclusions_missing_controls_and_bad_counts(self):
        obj=migration_input(); del obj['tables'][0]['exclusion_approval_reference']
        with self.assertRaises(InvalidInput): evaluate_migration(obj)
        obj=migration_input(); obj['tables'][0]['controls']=[]
        with self.assertRaises(InvalidInput): evaluate_migration(obj)
        obj=migration_input(); obj['tables'][0]['source_count']=True
        with self.assertRaises(InvalidInput): evaluate_migration(obj)

    def test_unexplained_control_amount_blocks(self):
        obj=migration_input(); table=obj['tables'][0]; control=table['controls'][0]
        control['unresolved_total']='1.00'; control['target_total']='6.00'
        self.assertIn('example:unexplained_control:NGN', evaluate_migration(obj)['issues'])

    def test_duplicate_table_and_units_rejected(self):
        obj=migration_input(); obj['tables'].append(copy.deepcopy(obj['tables'][0]))
        with self.assertRaises(InvalidInput): evaluate_migration(obj)
        obj=migration_input(); obj['tables'][0]['controls'].append(copy.deepcopy(obj['tables'][0]['controls'][0]))
        with self.assertRaises(InvalidInput): evaluate_migration(obj)
