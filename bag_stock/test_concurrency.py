"""Run against a disposable PostgreSQL test database, never a live database."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone
from accounts.models import User
from .models import BagPosition, CleaningJob, FinishedProductionStock, FinishedStoreStock, SalesManagerStock, SalesGoodsHandover, SalesGoodsEvent
from . import services

@skipUnlessDBFeature('has_select_for_update')
class ConcurrentWorkflowTests(TransactionTestCase):
    def setUp(self):
        self.raw=User.objects.create(username='race_raw',full_name='Raw',role='store_officer',store_type='raw',status='active')
        self.store1=User.objects.create(username='race_store1',full_name='Store 1',role='store_officer',store_type='finished',status='active')
        self.store2=User.objects.create(username='race_store2',full_name='Store 2',role='store_officer',store_type='finished',status='active')
        self.prod=User.objects.create(username='race_prod',full_name='Production',role='production_officer',status='active')
        self.sm=User.objects.create(username='race_sm',full_name='Sales manager',role='sales_manager',status='active')
        self.today=timezone.localdate()
    def race(self, first, second):
        barrier=Barrier(2)
        def run(f):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                f()
                return 'ok'
            except ValidationError:
                return 'rejected'
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(run,[first,second]))
        self.assertCountEqual(results,['ok','rejected'])
    def test_two_raw_issues_cannot_spend_same_bags(self):
        BagPosition.objects.create(material='maize',location='raw_store',bags=10)
        def issue():services.send_to_cleaner(key=uuid4(),date=self.today,material='maize',cleaner='Cleaner',bags=8,weight_kg=None,actor=self.raw)
        self.race(issue,issue)
        self.assertEqual(BagPosition.objects.get(material='maize',location='raw_store').bags,2)
        self.assertEqual(CleaningJob.objects.count(),1)
    def test_two_store_issues_cannot_spend_same_packs(self):
        FinishedStoreStock.objects.create(material='maize',pack_size_kg='10',packs=7)
        def issue(actor):services.send_sales_goods(actor=actor,key=uuid4(),date=self.today,material='maize',pack_size_kg='10',packs=5,recipient=self.sm)
        self.race(lambda:issue(self.store1),lambda:issue(self.store2))
        self.assertEqual(FinishedStoreStock.objects.get().packs,2)
        self.assertEqual(SalesGoodsHandover.objects.count(),1)
    def test_same_sales_handover_cannot_be_received_twice(self):
        FinishedStoreStock.objects.create(material='maize',pack_size_kg='10',packs=7)
        obj=services.send_sales_goods(actor=self.store1,key=uuid4(),date=self.today,material='maize',pack_size_kg='10',packs=5,recipient=self.sm)
        def receive():services.decide_sales_goods(handover_id=obj.pk,actor=self.sm,accept=True)
        self.race(receive,receive)
        self.assertEqual(SalesManagerStock.objects.get().packs,5)
        self.assertEqual(SalesGoodsEvent.objects.filter(kind='received').count(),1)
    def test_two_production_issues_cannot_spend_same_packs(self):
        FinishedProductionStock.objects.create(officer=self.prod,material='maize',pack_size_kg='10',packs=7)
        def issue():services.send_finished(key=uuid4(),date=self.today,material='maize',pack_size_kg='10',packs=5,recipient=self.store1,sender=self.prod)
        self.race(issue,issue)
        self.assertEqual(FinishedProductionStock.objects.get().packs,2)
    def test_two_sales_cannot_spend_same_holding(self):
        from commerce.services import record_sale
        from commerce.models import ReportedSale
        SalesManagerStock.objects.create(officer=self.sm,material='maize',pack_size_kg='10',packs=7)
        def sell():record_sale(actor=self.sm,key=uuid4(),date=self.today,material='maize',pack_size_kg='10',packs=5,unit_price='100')
        self.race(sell,sell)
        self.assertEqual(SalesManagerStock.objects.get().packs,2)
        self.assertEqual(ReportedSale.objects.count(),1)
    def test_money_handover_cannot_be_confirmed_twice(self):
        from commerce.services import report_money_handover, decide_money_handover
        from commerce.models import MoneyHandoverEvent
        gm=User.objects.create(username='race_gm',full_name='GM',role='manager',status='active')
        h=report_money_handover(actor=self.sm,recipient_id=gm.pk,key=uuid4(),date=self.today,method='cash',amount='100')
        def confirm():decide_money_handover(handover_id=h.pk,actor=gm,decision='confirmed')
        self.race(confirm,confirm)
        self.assertEqual(MoneyHandoverEvent.objects.filter(handover=h,kind='confirmed').count(),1)
    def test_competing_partial_money_receipts_cannot_exceed_reported_amount(self):
        from commerce.services import report_money_handover,record_money_receipt
        from commerce.models import MoneyHandoverReceipt
        gm=User.objects.create(username='partial_race_gm',full_name='GM',role='manager',status='active')
        h=report_money_handover(actor=self.sm,recipient_id=gm.pk,key=uuid4(),date=self.today,method='cash',amount='100')
        def receive():record_money_receipt(handover_id=h.pk,actor=gm,key=uuid4(),amount='70')
        self.race(receive,receive)
        self.assertEqual(MoneyHandoverReceipt.objects.filter(handover=h).count(),1)
        self.assertEqual(h.receipts.first().amount,70)
    def test_concurrent_payment_links_cannot_overallocate_handover(self):
        from commerce.services import record_sale,record_customer_payment,report_money_handover,report_payment_allocation
        from commerce.models import ReportedPaymentAllocation
        gm=User.objects.create(username='alloc_race_gm',full_name='GM',role='manager',status='active')
        SalesManagerStock.objects.create(officer=self.sm,material='maize',pack_size_kg='10',packs=1)
        sale=record_sale(actor=self.sm,key=uuid4(),date=self.today,material='maize',pack_size_kg='10',packs=1,unit_price='200')
        p=record_customer_payment(sale_id=sale.pk,actor=self.sm,key=uuid4(),date=self.today,amount='200',method='cash')
        h=report_money_handover(actor=self.sm,recipient_id=gm.pk,key=uuid4(),date=self.today,method='cash',amount='100')
        def allocate():report_payment_allocation(actor=self.sm,payment_id=p.pk,handover_id=h.pk,key=uuid4(),amount='70')
        self.race(allocate,allocate)
        self.assertEqual(ReportedPaymentAllocation.objects.filter(handover=h).count(),1)
    def test_money_correction_cannot_be_approved_twice(self):
        from commerce.services import report_money_handover,record_money_receipt,request_money_correction,decide_money_correction
        from commerce.models import MoneyHandoverEvent
        gm=User.objects.create(username='corr_race_gm',full_name='GM',role='manager',status='active')
        md=User.objects.create(username='corr_race_md',full_name='MD',role='md',status='active')
        h=report_money_handover(actor=self.sm,recipient_id=gm.pk,key=uuid4(),date=self.today,method='cash',amount='100')
        r=record_money_receipt(handover_id=h.pk,actor=gm,key=uuid4(),amount='50')
        c=request_money_correction(actor=gm,handover_id=h.pk,kind='receipt',target_id=r.pk,key=uuid4(),reason='Correction')
        def approve():decide_money_correction(actor=md,correction_id=c.pk,decision='approved',note='Checked')
        self.race(approve,approve)
        self.assertEqual(MoneyHandoverEvent.objects.filter(handover=h,kind='corrected').count(),1)
    def test_payment_allocation_correction_cannot_be_approved_twice(self):
        from commerce.services import record_sale,record_customer_payment,report_money_handover,report_payment_allocation,request_money_correction,decide_money_correction
        gm=User.objects.create(username='alloc_corr_gm',full_name='GM',role='manager',status='active')
        md=User.objects.create(username='alloc_corr_md',full_name='MD',role='md',status='active')
        SalesManagerStock.objects.create(officer=self.sm,material='maize',pack_size_kg='10',packs=1)
        sale=record_sale(actor=self.sm,key=uuid4(),date=self.today,material='maize',pack_size_kg='10',packs=1,unit_price='100')
        payment=record_customer_payment(sale_id=sale.pk,actor=self.sm,key=uuid4(),date=self.today,amount='100',method='cash')
        handover=report_money_handover(actor=self.sm,recipient_id=gm.pk,key=uuid4(),date=self.today,method='cash',amount='100')
        allocation=report_payment_allocation(actor=self.sm,payment_id=payment.pk,handover_id=handover.pk,key=uuid4(),amount='50')
        correction=request_money_correction(actor=self.sm,handover_id=handover.pk,kind='allocation',target_id=allocation.pk,key=uuid4(),reason='Correction')
        def approve():decide_money_correction(actor=md,correction_id=correction.pk,decision='approved',note='Checked')
        self.race(approve,approve)
        correction.refresh_from_db(); self.assertEqual(correction.status,'approved')
        self.assertEqual(allocation.corrections.filter(status='approved').count(),1)
