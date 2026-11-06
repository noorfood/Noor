from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from .models import MoneyHandoverReceipt, ReportedCustomerPayment, ReportedSale
from .services import report_money_handover, record_money_receipt, decide_money_handover

class PartialMoneyReceiptTests(TestCase):
    def setUp(self):
        self.sm=User(username='partial_sm',full_name='Test sales',role='sales_manager',status='active');self.sm.set_password('fictional-test-password-837!');self.sm.save()
        self.gm=User(username='partial_gm',full_name='Test gm',role='manager',status='active');self.gm.set_password('fictional-test-password-837!');self.gm.save()
        self.other=User(username='partial_other',full_name='Other gm',role='manager',status='active');self.other.save()
        self.h=report_money_handover(actor=self.sm,recipient_id=self.gm.pk,key=uuid4(),date=timezone.localdate(),method='cash',amount='100')
    def receive(self,amount,**kw):
        values=dict(handover_id=self.h.pk,actor=self.gm,key=uuid4(),amount=amount,note='');values.update(kw)
        return record_money_receipt(**values)
    def test_partial_then_full_is_recorded_without_double_counting(self):
        self.receive('30');self.h.refresh_from_db();self.assertEqual(self.h.status,'pending')
        decide_money_handover(handover_id=self.h.pk,actor=self.gm,decision='confirmed')
        self.h.refresh_from_db();self.assertEqual(self.h.status,'confirmed')
        self.assertEqual(list(self.h.receipts.values_list('amount',flat=True)),[Decimal('30'),Decimal('70')])
        self.assertEqual(self.h.events.count(),2)
        self.assertFalse(ReportedSale.objects.exists());self.assertFalse(ReportedCustomerPayment.objects.exists())
    def test_recipient_and_amount_validation(self):
        for args in ({'amount':'0'}, {'amount':'101'}, {'amount':'NaN'}, {'amount':'1','actor':self.other}):
            with self.subTest(args=args),self.assertRaises(ValidationError): self.receive(**args)
        self.assertFalse(self.h.receipts.exists())
    def test_duplicate_key_rolls_back(self):
        key=uuid4();self.receive('30',key=key)
        with self.assertRaises(IntegrityError):
            with transaction.atomic(): self.receive('30',key=key)
        self.assertEqual(self.h.receipts.count(),1)
    def test_review_preserved_and_requires_resolution_for_completion(self):
        self.receive('30');decide_money_handover(handover_id=self.h.pk,actor=self.gm,decision='review',reason='Please verify')
        with self.assertRaises(ValidationError):self.receive('70')
        self.receive('20');self.receive('50',note='Remainder received')
        self.h.refresh_from_db();self.assertEqual(self.h.status,'confirmed')
        self.assertEqual(self.h.events.get(kind='review').reason,'Please verify')
        self.assertEqual(sum(self.h.receipts.values_list('amount',flat=True)),Decimal('100'))
        with self.assertRaises(ValidationError):self.receive('1')
    def test_view_receipt_and_rollback_when_audit_fails(self):
        self.client.post(reverse('login'),{'username':self.gm.username,'password':'fictional-test-password-837!'})
        url=reverse('commerce:money_detail',args=[self.h.pk]);data={'action':'receipt','request_key':str(uuid4()),'amount':'30','note':''}
        with patch('commerce.views.log_action',side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):self.client.post(url,data)
        self.assertEqual(self.h.receipts.count(),0)
        self.assertEqual(self.client.post(url,data).status_code,302)
        page=self.client.get(url);self.assertContains(page,'₦30.00');self.assertContains(page,'₦70.00');self.assertContains(page,'Part received')
        self.assertContains(self.client.post(url,data),'already recorded');self.assertEqual(self.h.receipts.count(),1)
    def test_receipts_cannot_be_edited_or_deleted_as_objects(self):
        r=self.receive('1')
        with self.assertRaises(ValueError):r.save()
        with self.assertRaises(ValueError):r.delete()
