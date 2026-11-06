from datetime import date
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from accounts.models import User
from audit.models import AuditLog
from procurement.models import RawMaterialReceipt

class CostApprovalSecurityTests(TestCase):
    def setUp(self):
        self.md=User(username='cost_md',full_name='MD',role='md',status='active'); self.md.set_password('test-password!'); self.md.save()
        self.raw=User.objects.create(username='cost_raw',full_name='Raw',role='store_officer',store_type='raw',status='active')
        self.receipt=RawMaterialReceipt.objects.create(date=date(2024,1,1),material_type='maize',supplier='Example',num_bags=3,received_by=self.raw)
        self.url=reverse('procurement:set_cost',args=[self.receipt.pk])
        self.client.post(reverse('login'),{'username':self.md.username,'password':'test-password!'})
    def post(self, value, **kw):
        return self.client.post(self.url,{'cost_per_bag':value,**kw})
    def test_exact_decimal_and_audit(self):
        self.assertEqual(self.post('0.10').status_code,302)
        self.receipt.refresh_from_db(); self.assertEqual(self.receipt.total_cost,Decimal('0.30'))
        log=AuditLog.objects.get(action='SET_COST'); self.assertIn('0.30',log.new_data)
    def test_bad_amounts_are_rejected(self):
        for value in ('0','-1','NaN','Infinity','1.234','9999999999999999999'):
            self.assertEqual(self.post(value).status_code,200)
        self.receipt.refresh_from_db(); self.assertEqual(self.receipt.cost_status,'pending')
    def test_revision_requires_note(self):
        self.post('2.00'); self.assertEqual(self.post('3.00').status_code,200)
        self.receipt.refresh_from_db(); self.assertEqual(self.receipt.total_cost,Decimal('6.00'))
        self.assertEqual(self.post('3.00',revision_note='Invoice corrected').status_code,302)
        self.assertIn('Invoice corrected',AuditLog.objects.filter(action='SET_COST').latest('timestamp').description)
    def test_logging_failure_rolls_back_cost(self):
        with patch('procurement.views.log_action',side_effect=RuntimeError('test')):
            with self.assertRaises(RuntimeError): self.post('10.00')
        self.receipt.refresh_from_db(); self.assertEqual(self.receipt.cost_status,'pending'); self.assertIsNone(self.receipt.total_cost)
    def test_role_rechecked(self):
        self.md.role='manager';self.md.save(update_fields=['role'])
        self.assertEqual(self.post('5.00').status_code,403)
