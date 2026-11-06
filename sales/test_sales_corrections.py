from decimal import Decimal
from uuid import uuid4
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.test import TestCase
from django.utils import timezone
from accounts.models import User
from sales.models import SalesPerson, SalesDistributionRecord, SalesResult
from sales.services import request_sales_correction, decide_sales_correction


class SalesCorrectionTests(TestCase):
    def setUp(self):
        self.users = {}
        for name, role in [('sm', 'sales_manager'), ('gm', 'manager'), ('md', 'md'), ('other', 'sales_manager')]:
            u = User(username='sc_' + name, full_name='Test ' + name, role=role, status='active')
            u.set_password('fictional-correction-458!')
            u.save()
            self.users[name] = u
        sm = self.users['sm']
        self.sp = SalesPerson.objects.create(name='Promoter One', channel='promoter', created_by=sm)
        SalesDistributionRecord.objects.create(
            sales_person=self.sp, recorded_by=sm, material_type='maize', qty_given=20,
            date=timezone.localdate())
        self.result = SalesResult.objects.create(
            date=timezone.localdate(), sales_person=self.sp, material_type='maize',
            qty_sold=10, qty_pieces_sold=0, qty_returned=0, qty_pieces_returned=0,
            amount_returned=Decimal('0'), unit_price=Decimal('100'), unit_price_piece=Decimal('10'),
            commission_pct=Decimal('10'), recorded_by=sm)

    def req(self, actor='sm', reason='Wrong quantity recorded'):
        return request_sales_correction(
            actor=self.users[actor], sales_result_id=self.result.pk,
            reason=reason, key=uuid4())

    def test_approval_marks_corrected_and_excludes_from_live_totals(self):
        c = self.req()
        self.assertEqual(c.status, 'pending')
        decide_sales_correction(actor=self.users['md'], correction_id=c.pk, decision='approved', note='Checked')
        self.result.refresh_from_db()
        self.assertTrue(self.result.is_corrected)
        self.assertEqual(
            (SalesResult.objects.filter(sales_person=self.sp, is_corrected=False).aggregate(t=Sum('qty_sold'))['t'] or 0), 0)
        # Original still exists in history
        self.assertEqual(SalesResult.objects.filter(sales_person=self.sp).count(), 1)

    def test_rejection_changes_nothing_and_can_be_requested_again(self):
        c = self.req()
        decide_sales_correction(actor=self.users['md'], correction_id=c.pk, decision='rejected', note='Not proven')
        self.result.refresh_from_db()
        self.assertFalse(self.result.is_corrected)
        self.assertEqual(self.req().status, 'pending')

    def test_permissions_reasons_and_duplicates(self):
        with self.assertRaises(ValidationError):
            self.req(actor='other')
        with self.assertRaises(ValidationError):
            self.req(reason=' ')
        c = self.req()
        with self.assertRaises(ValidationError):
            self.req()
        with self.assertRaises(ValidationError):
            decide_sales_correction(actor=self.users['gm'], correction_id=c.pk, decision='approved', note='x')
        with self.assertRaises(ValidationError):
            decide_sales_correction(actor=self.users['md'], correction_id=c.pk, decision='approved', note='')
        decide_sales_correction(actor=self.users['md'], correction_id=c.pk, decision='approved', note='Checked')
        with self.assertRaises(ValidationError):
            decide_sales_correction(actor=self.users['md'], correction_id=c.pk, decision='approved', note='Again')
