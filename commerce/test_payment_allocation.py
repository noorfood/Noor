from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from bag_stock.models import SalesManagerStock
from .models import ReportedPaymentAllocation
from .services import record_sale,record_customer_payment,report_money_handover,report_payment_allocation

class AllocationTests(TestCase):
    def setUp(self):
        self.sm=User(username='alloc_sm',full_name='Fictional sales',role='sales_manager',status='active');self.sm.set_password('fictional-test-password-837!');self.sm.save()
        self.other=User(username='alloc_other',full_name='Other sales',role='sales_manager',status='active');self.other.save()
        self.gm=User(username='alloc_gm',full_name='GM',role='manager',status='active');self.gm.set_password('fictional-test-password-837!');self.gm.save()
        d=timezone.localdate();SalesManagerStock.objects.create(officer=self.sm,material='maize',pack_size_kg=10,packs=1)
        self.sale=record_sale(actor=self.sm,key=uuid4(),date=d,material='maize',pack_size_kg=10,packs=1,unit_price=200)
        self.payment=record_customer_payment(sale_id=self.sale.pk,actor=self.sm,key=uuid4(),date=d,method='cash',amount=100)
        self.h=report_money_handover(actor=self.sm,recipient_id=self.gm.pk,key=uuid4(),date=d,method='transfer',amount=80)
    def link(self,**kw):
        args=dict(actor=self.sm,payment_id=self.payment.pk,handover_id=self.h.pk,key=uuid4(),amount='30',note='');args.update(kw)
        return report_payment_allocation(**args)
    def test_link_is_explicit_and_does_not_confirm_receipts(self):
        self.link();self.h.refresh_from_db()
        self.assertEqual(self.h.status,'pending');self.assertFalse(self.h.receipts.exists());self.assertEqual(self.sale.customer_payments.get().amount,Decimal('100'))
        self.link(amount='50');self.assertEqual(self.h.payment_allocations.count(),2)
        with self.assertRaises(ValidationError):self.link(amount='1')
    def test_payment_limit_cannot_be_exceeded_across_handovers(self):
        h2=report_money_handover(actor=self.sm,recipient_id=self.gm.pk,key=uuid4(),date=timezone.localdate(),method='cash',amount='80')
        self.link(amount='70')
        with self.assertRaises(ValidationError):self.link(handover_id=h2.pk,amount='31')
        self.link(handover_id=h2.pk,amount='30')
    def test_permissions_duplicate_and_instance_guards(self):
        with self.assertRaises(ValidationError):self.link(actor=self.other)
        key=uuid4();a=self.link(key=key)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():self.link(key=key)
        with self.assertRaises(ValueError):a.save()
        with self.assertRaises(ValueError):a.delete()
    def test_view_scope_audit_rollback_and_display(self):
        url=reverse('commerce:money_detail',args=[self.h.pk]);gm=Client();gm.post(reverse('login'),{'username':self.gm.username,'password':'fictional-test-password-837!'})
        data={'action':'allocate','request_key':str(uuid4()),'payment':self.payment.pk,'amount':'30','note':''}
        self.assertEqual(gm.post(url,data).status_code,403)
        c=Client();c.post(reverse('login'),{'username':self.sm.username,'password':'fictional-test-password-837!'})
        with patch('commerce.views.log_action',side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):c.post(url,data)
        self.assertEqual(ReportedPaymentAllocation.objects.count(),0)
        self.assertEqual(c.post(url,data).status_code,302)
        self.assertContains(c.post(url,data),'already recorded')
        page=gm.get(url);self.assertContains(page,'Sale #');self.assertContains(page,'₦30.00')
