import uuid
from datetime import date, timedelta
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from procurement.models import RawMaterialReceipt
from .models import BagPosition,BagMovement,CleaningJob,CleaningReturn
from . import services

class BagWorkflowTests(TestCase):
    def setUp(self):
        self.raw=User.objects.create(username='raw_bags',full_name='Store',role='store_officer',store_type='raw',status='active')
        self.prod=User.objects.create(username='prod_bags',full_name='Production',role='production_officer',status='active')
        self.other=User.objects.create(username='other_prod',full_name='Other',role='production_officer',status='active')
        self.today=date(2026,11,3)
    def session(self,user):
        from accounts.session_security import session_fingerprint
        s=self.client.session;s['password_fingerprint']=session_fingerprint(user);s['user_id']=user.pk;s['actual_user_id']=user.pk;s['user_role']=user.role;s['store_type']=user.store_type or '';s.save()
    def receipt(self,bags=10,weight=None):
        r=RawMaterialReceipt.objects.create(date=self.today,material_type='maize',supplier='Supplier',num_bags=bags,approx_weight_kg=weight,received_by=self.raw)
        services.post_receipt(r,self.raw);return r
    def balance(self,location):
        p=BagPosition.objects.filter(material='maize',location=location).first();return p.bags if p else 0
    def job(self,bags=10,weight=None,key=None):
        return services.send_to_cleaner(key=key or uuid.uuid4(),date=self.today,material='maize',cleaner='Cleaner',bags=bags,weight_kg=weight,actor=self.raw)
    def ret(self,job,bags,final=False,key=None,date_=None,loss=None):
        return services.receive_from_cleaner(key=key or uuid.uuid4(),job_id=job.pk,date=date_ or self.today,clean_bags=bags,clean_weight_kg=None,loss_weight_kg=loss,is_final=final,actor=self.raw)
    def cleaned(self):
        self.receipt(20);job=self.job(10);self.ret(job,9,True);return job
    def transfer(self):
        return services.send_to_production(key=uuid.uuid4(),date=self.today,material='maize',bags=5,weight_kg=None,sender=self.raw,recipient=self.prod)
    def test_separate_receipts_and_no_assumed_weight_or_source(self):
        first=self.receipt(10);second=self.receipt(20);job=self.job(15)
        self.assertEqual(self.balance('raw_store'),15);self.assertIsNone(job.weight_kg)
        self.assertEqual(BagMovement.objects.filter(receipt__in=[first,second]).count(),2)
        self.assertIsNone(job.movements.get().receipt_id)
        self.assertFalse(BagPosition.objects.filter(location='cleaning').exists())
    def test_receipt_form_without_weight_saves_null(self):
        self.session(self.raw)
        response=self.client.post(reverse('procurement:receive'),{'request_key':str(uuid.uuid4()),'date':'2026-11-03','material_type':'wheat','supplier':'Supplier','num_bags':'12','approx_weight_kg':'','reference_no':'','notes':''})
        self.assertEqual(response.status_code,302);r=RawMaterialReceipt.objects.get();self.assertIsNone(r.approx_weight_kg)
        self.assertEqual(BagPosition.objects.get(material='wheat',location='raw_store').bags,12)
    def test_partial_and_final_do_not_infer_remaining_or_loss(self):
        self.receipt(10);job=self.job(10);r=self.ret(job,4)
        job.refresh_from_db();self.assertEqual(job.status,'in_progress');self.assertIsNone(job.remaining_input_bags)
        self.assertEqual(self.balance('clean_store'),4);self.assertIsNone(r.input_bags_accounted);self.assertIsNone(r.loss_weight_kg)
        self.assertFalse(BagMovement.objects.filter(kind='cleaning_input').exists())
        last=self.ret(job,5,True);job.refresh_from_db()
        self.assertEqual(job.status,'closed');self.assertTrue(job.counts_differ);self.assertEqual(self.balance('clean_store'),9)
        self.assertTrue(last.is_final);self.assertIsNone(last.loss_weight_kg)
    def test_final_matching_counts_not_marked_as_difference(self):
        self.receipt(10);job=self.job();self.ret(job,10,True);job.refresh_from_db();self.assertFalse(job.counts_differ)
    def test_zero_partial_rejected_zero_final_allowed_and_flagged(self):
        self.receipt(10);job=self.job()
        with self.assertRaises(ValidationError):self.ret(job,0,False)
        self.assertEqual(CleaningReturn.objects.count(),0)
        self.ret(job,0,True);job.refresh_from_db();self.assertEqual(job.status,'closed');self.assertTrue(job.counts_differ)
    def test_no_returns_after_final_and_no_double_submit(self):
        self.receipt(10);job=self.job();key=uuid.uuid4();self.ret(job,4,key=key)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():self.ret(job,4,key=key)
        self.assertEqual(self.balance('clean_store'),4);self.ret(job,5,True)
        with self.assertRaises(ValidationError):self.ret(job,1)
        self.assertEqual(CleaningReturn.objects.count(),2)
    def test_review_jobs_are_not_writable(self):
        self.receipt(10);job=self.job();job.status='needs_review';job.save(update_fields=['status'])
        with self.assertRaises(ValidationError):self.ret(job,3)
    def test_wrong_return_dates_rejected(self):
        self.receipt(10);job=self.job();self.ret(job,2,date_=self.today)
        with self.assertRaises(ValidationError):self.ret(job,2,date_=self.today-timedelta(days=1))
    def test_optional_weight_and_explicit_loss(self):
        self.receipt(20,Decimal('1800'));job=self.job(10,Decimal('905.50'))
        self.assertEqual(job.weight_kg,Decimal('905.50'));r=self.ret(job,9,True,loss='0');self.assertEqual(r.loss_weight_kg,Decimal('0'))
    def test_overissue_rolls_back(self):
        self.receipt(10)
        with self.assertRaises(ValidationError):self.job(11)
        self.assertEqual(CleaningJob.objects.count(),0);self.assertEqual(self.balance('raw_store'),10)
    def test_duplicate_issue_key_no_double_decrement(self):
        self.receipt(10);key=uuid.uuid4();self.job(3,key=key)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():self.job(3,key=key)
        self.assertEqual(self.balance('raw_store'),7);self.assertEqual(CleaningJob.objects.count(),1)
    def test_production_confirmation_only_once_by_recipient(self):
        self.cleaned();transfer=self.transfer();self.assertEqual(self.balance('clean_store'),4)
        with self.assertRaises(ValidationError):services.decide_transfer(transfer_id=transfer.pk,actor=self.other,accept=True)
        services.decide_transfer(transfer_id=transfer.pk,actor=self.prod,accept=True)
        with self.assertRaises(ValidationError):services.decide_transfer(transfer_id=transfer.pk,actor=self.prod,accept=True)
        self.assertEqual(self.balance('production'),5);self.assertEqual(self.balance('transit'),0)
    def test_rejected_transfer_requires_reason(self):
        self.cleaned();transfer=self.transfer()
        with self.assertRaises(ValidationError):services.decide_transfer(transfer_id=transfer.pk,actor=self.prod,accept=False)
        services.decide_transfer(transfer_id=transfer.pk,actor=self.prod,accept=False,reason='Difference');self.assertEqual(self.balance('clean_store'),9)
    def test_http_forms_and_record_details(self):
        self.receipt(10);self.session(self.raw)
        response=self.client.post(reverse('operations:cleaning_issue'),{'request_key':str(uuid.uuid4()),'date':'2026-11-03','material':'maize','cleaner':'Cleaner','bags':'10','weight_kg':''})
        self.assertEqual(response.status_code,302);job=CleaningJob.objects.get();url=reverse('operations:cleaning_return')
        page=self.client.get(url);self.assertContains(page,'Return type');self.assertNotContains(page,'Original bags processed')
        data={'date':'2026-11-03','job':job.pk,'clean_bags':'4','clean_weight_kg':'','loss_weight_kg':''}
        self.assertEqual(self.client.post(url,{**data,'request_key':str(uuid.uuid4()),'return_type':'partial'}).status_code,302)
        self.assertEqual(self.client.post(url,{**data,'request_key':str(uuid.uuid4()),'clean_bags':'5','return_type':'final'}).status_code,302)
        detail=self.client.get(reverse('operations:cleaning_detail',args=[job.pk]));self.assertContains(detail,'4 clean bags · Partial');self.assertContains(detail,'5 clean bags · Final');self.assertContains(detail,'Counts differ');self.assertNotContains(detail,'loss: 1')
        self.assertEqual(self.balance('clean_store'),9)
    def test_role_and_object_protection(self):
        self.receipt(10);movement=BagMovement.objects.get()
        with self.assertRaises(ValueError):movement.save()
        with self.assertRaises(ValueError):movement.delete()
        self.session(self.raw);self.raw.store_type='finished';self.raw.save(update_fields=['store_type'])
        self.assertEqual(self.client.get(reverse('operations:home')).status_code,403)
    def test_bad_inputs_are_rejected(self):
        for value in ['-1','1.5','NaN',True]:
            with self.assertRaises(ValidationError): services.count(value)
        for value in ['-1','NaN','Infinity']:
            with self.assertRaises(ValidationError): services.weight(value)

class ProductionWorkflowTests(BagWorkflowTests):
    def setup_stock(self):
        self.cleaned(); handover=self.transfer();services.decide_transfer(transfer_id=handover.pk,actor=self.prod,accept=True)
    def mill(self, bags=2, powder='175.50', actor=None, date_=None, key=None):
        return services.record_milling(key=key or uuid.uuid4(),date=date_ or self.today,material='maize',shift='morning',bags=bags,input_weight_kg=None,powder_kg=powder,machine='',actor=actor or self.prod)
    def pack(self, used='100', packs=10, actor=None, date_=None, key=None):
        return services.record_packaging(key=key or uuid.uuid4(),date=date_ or self.today,material='maize',shift='morning',powder_used_kg=used,packs=packs,pack_size_kg='10',actor=actor or self.prod)
    def test_end_to_end_with_two_mills_and_pooled_powder(self):
        from .models import ProductionHolding,PowderHolding
        self.setup_stock();first=self.mill(powder='125.50');second=self.mill(powder='80.25')
        package=self.pack(used='180',packs=18)
        self.assertEqual(ProductionHolding.objects.get(officer=self.prod,material='maize').bags,1)
        self.assertEqual(self.balance('production'),1)
        self.assertEqual(PowderHolding.objects.get(officer=self.prod,material='maize').kg,Decimal('25.75'))
        self.assertEqual(first.bag_movements.get().bags,2);self.assertEqual(second.powder_kg,Decimal('80.25'))
        self.assertIsNone(first.input_weight_kg);self.assertFalse(hasattr(package,'milling_batch'))
    def test_production_isolation_and_insufficient_stock(self):
        from .models import MillingRecord,PackagingRecord,PowderHolding
        self.setup_stock()
        with self.assertRaises(ValidationError):self.mill(actor=self.other)
        with self.assertRaises(ValidationError):self.mill(bags=6)
        self.assertEqual(MillingRecord.objects.count(),0);self.assertEqual(self.balance('production'),5)
        self.mill()
        with self.assertRaises(ValidationError):self.pack(used='176')
        with self.assertRaises(ValidationError):self.pack(used='1',actor=self.other)
        self.assertEqual(PackagingRecord.objects.count(),0);self.assertEqual(PowderHolding.objects.get(officer=self.prod,material='maize').kg,Decimal('175.50'))
    def test_milling_duplicate_rolls_back(self):
        from .models import MillingRecord
        self.setup_stock();key=uuid.uuid4();self.mill(key=key)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():self.mill(key=key)
        self.assertEqual(MillingRecord.objects.count(),1);self.assertEqual(self.balance('production'),3)
    def test_packaging_duplicate_rolls_back(self):
        from .models import PowderHolding,PackagingRecord
        self.setup_stock();self.mill();key=uuid.uuid4();self.pack(used='50',key=key)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():self.pack(used='50',key=key)
        self.assertEqual(PackagingRecord.objects.count(),1);self.assertEqual(PowderHolding.objects.get(officer=self.prod,material='maize').kg,Decimal('125.50'))
    def test_dates_and_values(self):
        self.setup_stock()
        with self.assertRaises(ValidationError):self.mill(date_=self.today-timedelta(days=1))
        for value in ('0','-2','NaN'):
            with self.assertRaises(ValidationError):self.mill(powder=value)
        self.mill()
        with self.assertRaises(ValidationError):self.pack(date_=self.today-timedelta(days=1))
    def test_http_production_and_permissions(self):
        from .models import MillingRecord,PackagingRecord
        self.setup_stock();self.session(self.prod)
        page=self.client.get(reverse('operations:production_home'));self.assertContains(page,'5 <small>bags</small>');self.assertNotContains(page,'batch')
        data={'request_key':str(uuid.uuid4()),'date':self.today.isoformat(),'material':'maize','shift':'morning','bags':'2','input_weight_kg':'','powder_kg':'175.5','machine':''}
        self.assertEqual(self.client.post(reverse('operations:milling'),data).status_code,302)
        data={'request_key':str(uuid.uuid4()),'date':self.today.isoformat(),'material':'maize','shift':'morning','powder_used_kg':'100','packs':'10','pack_size_kg':'10'}
        self.assertEqual(self.client.post(reverse('operations:packaging'),data).status_code,302)
        page=self.client.get(reverse('operations:production_home'));self.assertContains(page,'75.50');self.assertContains(page,'10 packs')
        self.assertEqual(MillingRecord.objects.count(),1);self.assertEqual(PackagingRecord.objects.count(),1)
        self.session(self.raw);self.assertEqual(self.client.get(reverse('operations:milling')).status_code,403)
        self.assertEqual(self.client.get(reverse('operations:production_home')).status_code,403)

    def test_unmeasured_use_marks_balance_unknown_and_keeps_it_unknown(self):
        from .models import PowderHolding
        self.setup_stock();self.mill()
        record=services.record_packaging(key=uuid.uuid4(),date=self.today,material='maize',shift='morning',powder_used_kg=None,powder_used_bags=3,packs=10,pack_size_kg='10',actor=self.prod)
        stock=PowderHolding.objects.get(officer=self.prod,material='maize')
        self.assertIsNone(record.powder_used_kg);self.assertEqual(record.powder_used_bags,3);self.assertIsNone(stock.kg)
        self.mill(bags=1,powder='50');stock.refresh_from_db();self.assertIsNone(stock.kg)
        self.pack(used='1');stock.refresh_from_db();self.assertIsNone(stock.kg)
        self.session(self.prod);page=self.client.get(reverse('operations:production_home'))
        self.assertContains(page,'Not confirmed');self.assertContains(page,'Needs review');self.assertContains(page,'3 powder bags')
        self.assertNotContains(page,'None kg')
    def test_no_ledger_requires_record_not_zero_assumption(self):
        from .models import PowderHolding
        with self.assertRaises(ValidationError):self.pack(used=None)
        self.assertFalse(PowderHolding.objects.filter(officer=self.prod,material='maize').exists())
    def test_measured_zero_is_not_unknown(self):
        from .models import PowderHolding
        self.setup_stock();self.mill(powder='100');self.pack(used='100')
        stock=PowderHolding.objects.get(officer=self.prod,material='maize');self.assertEqual(stock.kg,Decimal('0'))
        with self.assertRaises(ValidationError):self.pack(used='1')
    def test_optional_powder_bags_no_conversion(self):
        from .models import PowderHolding
        self.setup_stock()
        obj=services.record_milling(key=uuid.uuid4(),date=self.today,material='maize',shift='night',bags=2,input_weight_kg=None,powder_kg='158.45',powder_bags=3,machine='',actor=self.prod)
        self.assertEqual(obj.powder_bags,3);self.assertEqual(PowderHolding.objects.get(officer=self.prod,material='maize').kg,Decimal('158.45'))
        for bad in ('0','-1','1.5'):
            with self.assertRaises(ValidationError):services.record_packaging(key=uuid.uuid4(),date=self.today,material='maize',shift='night',powder_used_kg=None,powder_used_bags=bad,packs=1,pack_size_kg='10',actor=self.prod)
    def test_packaging_form_accepts_unknown_usage(self):
        from .models import PackagingRecord,PowderHolding
        self.setup_stock();self.mill();self.session(self.prod)
        data={'request_key':str(uuid.uuid4()),'date':self.today.isoformat(),'material':'maize','shift':'morning','powder_used_kg':'','powder_used_bags':'2','packs':'10','pack_size_kg':'10'}
        self.assertEqual(self.client.post(reverse('operations:packaging'),data).status_code,302)
        rec=PackagingRecord.objects.get();self.assertIsNone(rec.powder_used_kg);self.assertEqual(rec.powder_used_bags,2)
        self.assertIsNone(PowderHolding.objects.get(officer=self.prod,material='maize').kg)

class FinishedGoodsWorkflowTests(TestCase):
    def setUp(self):
        from .models import FinishedStoreStock
        self.raw=User.objects.create(username='fg_raw',full_name='Raw Store',role='store_officer',store_type='raw',status='active')
        self.prod=User.objects.create(username='fg_prod',full_name='Production',role='production_officer',status='active')
        self.other=User.objects.create(username='fg_other',full_name='Other Production',role='production_officer',status='active')
        self.store=User.objects.create(username='fg_store',full_name='Finished Store',role='store_officer',store_type='finished',status='active')
        self.store2=User.objects.create(username='fg_store2',full_name='Other Store',role='store_officer',store_type='finished',status='active')
        self.md=User.objects.create(username='fg_md',full_name='MD',role='md',status='active')
        self.today=date(2026,11,3)
        receipt=RawMaterialReceipt.objects.create(date=self.today,material_type='maize',supplier='Supplier',num_bags=10,received_by=self.raw)
        services.post_receipt(receipt,self.raw)
        job=services.send_to_cleaner(key=uuid.uuid4(),date=self.today,material='maize',cleaner='Cleaner',bags=10,weight_kg=None,actor=self.raw)
        services.receive_from_cleaner(key=uuid.uuid4(),job_id=job.pk,date=self.today,clean_bags=10,clean_weight_kg=None,loss_weight_kg=None,is_final=True,actor=self.raw)
        handover=services.send_to_production(key=uuid.uuid4(),date=self.today,material='maize',bags=5,weight_kg=None,sender=self.raw,recipient=self.prod)
        services.decide_transfer(transfer_id=handover.pk,actor=self.prod,accept=True)
        services.record_milling(key=uuid.uuid4(),date=self.today,material='maize',shift='morning',bags=2,input_weight_kg=None,powder_kg='220',machine='',actor=self.prod)
        services.record_packaging(key=uuid.uuid4(),date=self.today,material='maize',shift='morning',powder_used_kg='100',packs=10,pack_size_kg='10',actor=self.prod)
        services.record_packaging(key=uuid.uuid4(),date=self.today,material='maize',shift='morning',powder_used_kg='100',packs=10,pack_size_kg='10',actor=self.prod)
    def session(self,user):
        from accounts.session_security import session_fingerprint
        s=self.client.session;s['password_fingerprint']=session_fingerprint(user);s['user_id']=user.pk;s['actual_user_id']=user.pk;s['user_role']=user.role;s['store_type']=user.store_type or '';s.save()
    def send(self,packs=7,key=None,recipient=None,sender=None,size='10',date_=None):
        return services.send_finished(key=key or uuid.uuid4(),date=date_ or self.today,material='maize',pack_size_kg=size,packs=packs,recipient=recipient or self.store,sender=sender or self.prod)
    def prod_stock(self):
        from .models import FinishedProductionStock
        return FinishedProductionStock.objects.get(officer=self.prod,material='maize',pack_size_kg='10').packs
    def store_stock(self):
        from .models import FinishedStoreStock
        item=FinishedStoreStock.objects.filter(material='maize',pack_size_kg='10').first();return item.packs if item else 0
    def receive(self,obj,packs,is_final=False,key=None,actor=None,reason=''):
        return services.receive_finished(handover_id=obj.pk,actor=actor or self.store,key=key or uuid.uuid4(),packs=packs,is_final=is_final,reason=reason)
    def ret(self,obj,packs,key=None,actor=None):
        return services.return_finished(handover_id=obj.pk,actor=actor or self.prod,key=key or uuid.uuid4(),packs=packs)
    def test_partial_then_final_moves_only_confirmed_packs(self):
        from .models import FinishedStockEvent
        obj=self.send();self.assertEqual(self.prod_stock(),13);self.assertEqual(self.store_stock(),0)
        first=self.receive(obj,3);obj.refresh_from_db();self.assertEqual(obj.status,'partial');self.assertEqual(obj.received_packs,3);self.assertEqual(self.store_stock(),3)
        self.receive(obj,4,is_final=True);obj.refresh_from_db();self.assertEqual(obj.status,'accepted');self.assertEqual(self.store_stock(),7)
        self.assertEqual(list(obj.stock_events.order_by('id').values_list('kind',flat=True)),['sent','received','received'])
        with self.assertRaises(ValidationError):self.receive(obj,1,True)
        self.assertEqual(FinishedStockEvent.objects.filter(kind='packaged').count(),2);self.assertEqual(first.stock_event.packs,3)
    def test_discrepancy_partial_return_and_management_close(self):
        obj=self.send()
        with self.assertRaises(ValidationError):self.receive(obj,4,is_final=True)
        self.receive(obj,4,is_final=True,reason='Count differs')
        obj.refresh_from_db();self.assertEqual(obj.status,'disputed');self.assertEqual(obj.received_packs,4);self.assertEqual(self.store_stock(),4);self.assertEqual(self.prod_stock(),13)
        with self.assertRaises(ValidationError):services.resolve_finished(handover_id=obj.pk,actor=self.md,note='Checked')
        with self.assertRaises(ValidationError):self.ret(obj,2,actor=self.other)
        self.ret(obj,2);obj.refresh_from_db();self.assertEqual(obj.returned_packs,2);self.assertEqual(self.prod_stock(),15)
        with self.assertRaises(ValidationError):self.ret(obj,2)
        self.receive(obj,1,is_final=True);obj.refresh_from_db();self.assertEqual(obj.status,'disputed');self.assertEqual(self.store_stock(),5)
        with self.assertRaises(ValidationError):services.resolve_finished(handover_id=obj.pk,actor=self.prod,note='Checked')
        with self.assertRaises(ValidationError):services.resolve_finished(handover_id=obj.pk,actor=self.md,note='')
        services.resolve_finished(handover_id=obj.pk,actor=self.md,note='Counts checked')
        obj.refresh_from_db();self.assertEqual(obj.status,'resolved');self.assertEqual(obj.resolution_note,'Counts checked');self.assertEqual(self.prod_stock()+self.store_stock(),20)
    def test_all_returned_needs_management_review(self):
        obj=self.send()
        with self.assertRaises(ValidationError):services.flag_finished(handover_id=obj.pk,actor=self.store,reason='')
        services.flag_finished(handover_id=obj.pk,actor=self.store,reason='Count differs')
        self.ret(obj,7);obj.refresh_from_db();self.assertEqual(obj.status,'disputed');self.assertEqual(self.prod_stock(),20)
        services.resolve_finished(handover_id=obj.pk,actor=self.md,note='Returned and checked')
        obj.refresh_from_db();self.assertEqual(obj.status,'returned');self.assertEqual(self.store_stock(),0)
    def test_roles_size_and_quantity_limits(self):
        from .models import FinishedHandover
        for kwargs in ({'packs':21},{'packs':0},{'size':'5'},{'sender':self.other},{'recipient':self.raw},{'date_':self.today-timedelta(days=1)}):
            with self.assertRaises(ValidationError):self.send(**kwargs)
        self.assertEqual(self.prod_stock(),20);self.assertEqual(FinishedHandover.objects.count(),0)
        obj=self.send()
        with self.assertRaises(ValidationError):self.receive(obj,7,True,actor=self.store2)
        with self.assertRaises(ValidationError):self.receive(obj,7,False)
        with self.assertRaises(ValidationError):self.receive(obj,8,True)
        self.assertEqual(self.store_stock(),0)
    def test_duplicate_send_and_partial_actions_roll_back(self):
        from .models import FinishedHandover,FinishedPartialReceipt,FinishedPartialReturn
        key=uuid.uuid4();obj=self.send(key=key)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():self.send(packs=2,key=key)
        self.assertEqual(self.prod_stock(),13);self.assertEqual(FinishedHandover.objects.count(),1)
        key2=uuid.uuid4();self.receive(obj,2,key=key2)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():self.receive(obj,2,key=key2)
        self.assertEqual(self.store_stock(),2);self.assertEqual(FinishedPartialReceipt.objects.count(),1)
        services.flag_finished(handover_id=obj.pk,actor=self.store,reason='Count differs')
        key3=uuid.uuid4();self.ret(obj,2,key=key3)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():self.ret(obj,2,key=key3)
        self.assertEqual(self.prod_stock(),15);self.assertEqual(FinishedPartialReturn.objects.count(),1)
    def test_http_views_and_permissions(self):
        from .models import FinishedHandover
        self.session(self.prod)
        form={'request_key':str(uuid.uuid4()),'date':self.today.isoformat(),'material':'maize','pack_size_kg':'10','packs':'7','recipient':str(self.store.pk)}
        self.assertEqual(self.client.post(reverse('operations:finished_send'),form).status_code,302)
        obj=FinishedHandover.objects.get();self.assertContains(self.client.get(reverse('operations:finished_home')),'Waiting')
        detail=reverse('operations:finished_detail',args=[obj.pk])
        self.session(self.store2);self.assertEqual(self.client.get(detail).status_code,404)
        self.session(self.raw);self.assertEqual(self.client.get(reverse('operations:finished_home')).status_code,403)
        self.session(self.store);page=self.client.get(detail);self.assertContains(page,'Record receipt');self.assertContains(page,'Request review')
        data={'action':'receive','receipt-request_key':str(uuid.uuid4()),'receipt-packs':'4','receipt-receipt_type':'partial','receipt-reason':''}
        self.assertEqual(self.client.post(detail,data).status_code,302)
        invalid=self.client.post(detail,{'action':'flag','review-reason':''});self.assertContains(invalid,'This field is required')
        self.assertEqual(self.client.post(detail,{'action':'flag','review-reason':'Count differs'}).status_code,302)
        self.session(self.prod);self.assertContains(self.client.get(detail),'Confirm goods returned')
        self.assertEqual(self.client.post(detail,{'action':'return','return-request_key':str(uuid.uuid4()),'return-packs':'3'}).status_code,302)
        self.session(self.md);self.assertEqual(self.client.get(reverse('operations:finished_send')).status_code,403)
        self.assertContains(self.client.get(detail),'Close review')
        self.assertEqual(self.client.post(detail,{'action':'resolve','resolve-note':'Checked'}).status_code,302)
        obj.refresh_from_db();self.assertEqual(obj.status,'resolved');self.assertEqual(self.prod_stock(),16);self.assertEqual(self.store_stock(),4)
        page=self.client.get(detail);self.assertContains(page,'4 packs received');self.assertContains(page,'3 packs returned');self.assertContains(page,'Checked')
    def test_audit_transaction_rollback_if_record_fails(self):
        from .models import FinishedHandover,FinishedStockEvent
        self.session(self.prod)
        form={'request_key':str(uuid.uuid4()),'date':self.today.isoformat(),'material':'maize','pack_size_kg':'10','packs':'99','recipient':str(self.store.pk)}
        response=self.client.post(reverse('operations:finished_send'),form)
        self.assertContains(response,'Not enough recorded packs');self.assertEqual(self.prod_stock(),20)
        self.assertEqual(FinishedHandover.objects.count(),0);self.assertEqual(FinishedStockEvent.objects.filter(kind='sent').count(),0)
    def test_finished_store_home_routes_to_new_workflow(self):
        self.session(self.store)
        self.assertRedirects(self.client.get(reverse('dashboard')),reverse('operations:finished_home'),fetch_redirect_response=False)
    def test_event_object_cannot_be_edited_or_deleted(self):
        obj=self.send();event=obj.stock_events.get()
        with self.assertRaises(ValueError):event.save()
        with self.assertRaises(ValueError):event.delete()

    def test_receipt_and_return_history_object_protection(self):
        obj=self.send()
        receipt=self.receive(obj,3)
        services.flag_finished(handover_id=obj.pk,actor=self.store,reason='Check count')
        returned=self.ret(obj,2)
        for entry in (receipt,returned):
            with self.assertRaises(ValueError):entry.save()
            with self.assertRaises(ValueError):entry.delete()
    def test_review_notes_are_authorized_and_do_not_move_stock(self):
        from .models import FinishedReviewNote,FinishedStockEvent
        obj=self.send()
        with self.assertRaises(ValidationError):services.add_finished_review_note(handover_id=obj.pk,actor=self.md,key=uuid.uuid4(),note='Not yet open')
        services.flag_finished(handover_id=obj.pk,actor=self.store,reason='Count differs')
        old_events=FinishedStockEvent.objects.count();before=(self.prod_stock(),self.store_stock())
        for user in (self.other,self.store2,self.raw):
            with self.assertRaises(ValidationError):services.add_finished_review_note(handover_id=obj.pk,actor=user,key=uuid.uuid4(),note='Test')
        for note in ('','   ','x'*1001):
            with self.assertRaises(ValidationError):services.add_finished_review_note(handover_id=obj.pk,actor=self.md,key=uuid.uuid4(),note=note)
        for user in (self.prod,self.store,self.md):
            services.add_finished_review_note(handover_id=obj.pk,actor=user,key=uuid.uuid4(),note='  Count being checked  ')
        self.assertEqual(FinishedReviewNote.objects.count(),3)
        self.assertEqual(FinishedReviewNote.objects.first().note,'Count being checked')
        self.assertEqual((self.prod_stock(),self.store_stock()),before);self.assertEqual(FinishedStockEvent.objects.count(),old_events)
        obj.refresh_from_db();self.assertEqual((obj.status,obj.received_packs,obj.returned_packs),('disputed',0,0))
        self.ret(obj,7);services.resolve_finished(handover_id=obj.pk,actor=self.md,note='All returned')
        with self.assertRaises(ValidationError):services.add_finished_review_note(handover_id=obj.pk,actor=self.md,key=uuid.uuid4(),note='Closed')
    def test_review_note_duplicate_and_history_protection(self):
        from .models import FinishedReviewNote
        obj=self.send();services.flag_finished(handover_id=obj.pk,actor=self.store,reason='Check')
        key=uuid.uuid4();note=services.add_finished_review_note(handover_id=obj.pk,actor=self.md,key=key,note='Investigating')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():services.add_finished_review_note(handover_id=obj.pk,actor=self.md,key=key,note='Duplicate')
        with self.assertRaises(ValueError):note.save()
        with self.assertRaises(ValueError):note.delete()
        self.assertEqual(FinishedReviewNote.objects.count(),1)
    def test_review_note_http_and_access(self):
        from .models import FinishedReviewNote
        from audit.models import AuditLog
        obj=self.send();services.flag_finished(handover_id=obj.pk,actor=self.store,reason='Count differs')
        detail=reverse('operations:finished_detail',args=[obj.pk]);payload={'action':'note','note-request_key':str(uuid.uuid4()),'note-note':'Count being checked'}
        self.session(self.other);self.assertEqual(self.client.post(detail,payload).status_code,404)
        self.session(self.store);self.assertContains(self.client.get(detail),'Add review note')
        self.assertEqual(self.client.post(detail,payload).status_code,302)
        self.assertContains(self.client.get(detail),'Count being checked')
        self.assertEqual(FinishedReviewNote.objects.count(),1);self.assertTrue(AuditLog.objects.filter(action='FINISHED_NOTE',object_id=str(FinishedReviewNote.objects.first().pk)).exists())
        self.assertContains(self.client.post(detail,payload),'already recorded')
        self.session(self.prod);self.assertContains(self.client.get(detail),'Count being checked')
        self.session(self.md);self.assertContains(self.client.get(detail),'Count being checked')
    def test_store_count_records_observation_without_stock_adjustment(self):
        from .models import FinishedStoreCount,FinishedStockEvent
        from django.utils import timezone
        obj=self.send();self.receive(obj,3)
        before=(self.prod_stock(),self.store_stock(),FinishedStockEvent.objects.count())
        observation=services.record_finished_store_count(actor=self.store,key=uuid.uuid4(),material='maize',pack_size_kg='10',counted_packs=2,counted_at=timezone.now(),scope='Store shelves; waiting handover excluded',note='Recount planned')
        self.assertEqual((observation.counted_packs,observation.recorded_balance),(2,3))
        self.assertEqual((self.prod_stock(),self.store_stock(),FinishedStockEvent.objects.count()),before)
        obj.refresh_from_db();self.assertEqual(obj.status,'partial')
        unknown=services.record_finished_store_count(actor=self.md,key=uuid.uuid4(),material='wheat',pack_size_kg='5',counted_packs=0,counted_at=timezone.now(),scope='Store shelves')
        self.assertIsNone(unknown.recorded_balance);self.assertEqual(unknown.counted_packs,0)
        self.assertEqual(FinishedStoreCount.objects.count(),2)
        for entry in (observation,unknown):
            with self.assertRaises(ValueError):entry.save()
            with self.assertRaises(ValueError):entry.delete()
    def test_store_count_validation_permissions_and_idempotency(self):
        from .models import FinishedStoreCount
        from django.utils import timezone
        args=dict(actor=self.store,key=uuid.uuid4(),material='maize',pack_size_kg='10',counted_packs=0,counted_at=timezone.now(),scope='Shelf')
        for changes in ({'actor':self.raw},{'actor':self.prod},{'material':'invalid'},{'pack_size_kg':'0'},{'counted_packs':-1},{'counted_packs':True},{'counted_at':timezone.now()+timedelta(days=1)},{'scope':'  '}):
            with self.assertRaises(ValidationError):services.record_finished_store_count(**(args|changes))
        self.assertEqual(FinishedStoreCount.objects.count(),0)
        services.record_finished_store_count(**args)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():services.record_finished_store_count(**args)
        self.assertEqual(FinishedStoreCount.objects.count(),1)
    def test_store_count_http_permissions_and_no_automatic_difference(self):
        from .models import FinishedStoreCount
        from audit.models import AuditLog
        from django.utils import timezone
        path=reverse('operations:finished_counts')
        self.session(self.prod);self.assertEqual(self.client.get(path).status_code,403)
        self.session(self.raw);self.assertEqual(self.client.get(path).status_code,403)
        self.session(self.store);self.assertContains(self.client.get(path),'Record a count')
        data={'request_key':str(uuid.uuid4()),'material':'wheat','pack_size_kg':'10','counted_packs':'0','counted_at':timezone.localtime().strftime('%Y-%m-%dT%H:%M'),'scope':'All shelf stock, excludes waiting','note':'Recount'}
        resp=self.client.post(path,data);self.assertEqual(resp.status_code,302)
        observation=FinishedStoreCount.objects.get();detail=reverse('operations:finished_count_detail',args=[observation.pk])
        self.assertRedirects(resp,detail);page=self.client.get(detail)
        self.assertContains(page,'No stock adjustment has been made');self.assertContains(page,'Not recorded');self.assertContains(page,'Recount')
        self.assertTrue(AuditLog.objects.filter(action='FINISHED_STORE_COUNT',object_id=str(observation.pk)).exists())
        self.assertContains(self.client.post(path,data),'already recorded')
        self.session(self.md);self.assertContains(self.client.get(detail),'Store count')
    def test_sales_manager_handover_reserves_and_confirms_stock(self):
        from .models import SalesManagerStock,SalesGoodsHandover,SalesGoodsEvent
        sm=User.objects.create(username='sm_one',full_name='Sales One',role='sales_manager',status='active')
        other_sm=User.objects.create(username='sm_two',full_name='Sales Two',role='sales_manager',status='active')
        inbound=self.send();self.receive(inbound,7,is_final=True)
        self.assertEqual(self.store_stock(),7)
        key=uuid.uuid4();obj=services.send_sales_goods(actor=self.store,key=key,date=self.today,material='maize',pack_size_kg='10',packs=4,recipient=sm)
        self.assertEqual(self.store_stock(),3);self.assertEqual(SalesManagerStock.objects.count(),0)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():services.send_sales_goods(actor=self.store,key=key,date=self.today,material='maize',pack_size_kg='10',packs=2,recipient=sm)
        with self.assertRaises(ValidationError):services.decide_sales_goods(handover_id=obj.pk,actor=other_sm,accept=True)
        self.assertEqual(self.store_stock(),3)
        services.decide_sales_goods(handover_id=obj.pk,actor=sm,accept=True)
        self.assertEqual(SalesManagerStock.objects.get(officer=sm).packs,4)
        self.assertEqual(self.prod_stock()+self.store_stock()+SalesManagerStock.objects.get(officer=sm).packs,20)
        with self.assertRaises(ValidationError):services.decide_sales_goods(handover_id=obj.pk,actor=sm,accept=True)
        self.assertEqual(list(obj.events.values_list('kind',flat=True)),['sent','received'])
        event=obj.events.first()
        with self.assertRaises(ValueError):event.save()
        with self.assertRaises(ValueError):event.delete()
        self.assertEqual(SalesGoodsEvent.objects.count(),2);self.assertEqual(SalesGoodsHandover.objects.count(),1)
    def test_sales_manager_dispute_requires_physical_return(self):
        from .models import SalesManagerStock
        sm=User.objects.create(username='sm_review',full_name='Sales Review',role='sales_manager',status='active')
        inbound=self.send();self.receive(inbound,7,True)
        obj=services.send_sales_goods(actor=self.store,key=uuid.uuid4(),date=self.today,material='maize',pack_size_kg='10',packs=4,recipient=sm)
        with self.assertRaises(ValidationError):services.decide_sales_goods(handover_id=obj.pk,actor=sm,accept=False,reason='')
        services.decide_sales_goods(handover_id=obj.pk,actor=sm,accept=False,reason='Count needs checking')
        self.assertEqual(self.store_stock(),3);self.assertFalse(SalesManagerStock.objects.exists())
        with self.assertRaises(ValidationError):services.return_sales_goods(handover_id=obj.pk,actor=self.store2)
        services.return_sales_goods(handover_id=obj.pk,actor=self.store)
        obj.refresh_from_db();self.assertEqual(obj.status,'returned');self.assertEqual(self.store_stock(),7)
        with self.assertRaises(ValidationError):services.return_sales_goods(handover_id=obj.pk,actor=self.store)
    def test_sales_goods_http_and_permissions(self):
        from .models import SalesGoodsHandover
        sm=User.objects.create(username='sm_http',full_name='Sales HTTP',role='sales_manager',status='active')
        other=User.objects.create(username='sm_other',full_name='Other SM',role='sales_manager',status='active')
        inbound=self.send();self.receive(inbound,7,True)
        sendpath=reverse('operations:sales_goods_send');self.session(self.raw);self.assertEqual(self.client.get(sendpath).status_code,403)
        self.session(self.store)
        payload={'request_key':str(uuid.uuid4()),'date':self.today.isoformat(),'material':'maize','pack_size_kg':'10','packs':'4','recipient':str(sm.pk)}
        response=self.client.post(sendpath,payload);self.assertEqual(response.status_code,302)
        obj=SalesGoodsHandover.objects.get();detail=reverse('operations:sales_goods_detail',args=[obj.pk])
        self.session(other);self.assertEqual(self.client.get(detail).status_code,404)
        self.session(sm);self.assertRedirects(self.client.get(reverse('dashboard')),reverse('operations:sales_goods_home'),fetch_redirect_response=False)
        self.assertContains(self.client.get(detail),'Review handover')
        self.assertEqual(self.client.post(detail,{'action':'decide','decision-decision':'accept','decision-reason':''}).status_code,302)
        obj.refresh_from_db();self.assertEqual(obj.status,'received')
        self.assertEqual(self.client.post(detail,{'action':'decide','decision-decision':'accept','decision-reason':''}).status_code,403)
        self.session(self.md);self.assertContains(self.client.get(detail),'Received')
    def test_sales_goods_service_validates_actor_recipient_and_available_stock(self):
        sm=User.objects.create(username='sm_valid',full_name='Sales Manager',role='sales_manager',status='active')
        inactive=User.objects.create(username='sm_inactive',full_name='Inactive Sales',role='sales_manager',status='suspended')
        inbound=self.send();self.receive(inbound,7,True)
        args=dict(actor=self.store,key=uuid.uuid4(),date=self.today,material='maize',pack_size_kg='10',packs=2,recipient=sm)
        for changes in ({'actor':self.raw},{'actor':self.prod},{'recipient':inactive},{'recipient':self.prod},{'packs':0},{'packs':8},{'pack_size_kg':'5'},{'material':'bad'},{'date':timezone.localdate()+timedelta(days=1)}):
            with self.assertRaises(ValidationError):services.send_sales_goods(**(args|changes))
        self.assertEqual(self.store_stock(),7)
    def test_sales_send_rolls_back_if_audit_fails(self):
        from unittest.mock import patch
        from .models import SalesGoodsHandover
        sm=User.objects.create(username='sm_audit',full_name='Sales Audit',role='sales_manager',status='active')
        inbound=self.send();self.receive(inbound,7,True);self.session(self.store)
        payload={'request_key':str(uuid.uuid4()),'date':self.today.isoformat(),'material':'maize','pack_size_kg':'10','packs':'4','recipient':str(sm.pk)}
        with patch('operations.views.log_action',side_effect=RuntimeError('Test audit failure')):
            with self.assertRaises(RuntimeError):self.client.post(reverse('operations:sales_goods_send'),payload)
        self.assertEqual(self.store_stock(),7);self.assertFalse(SalesGoodsHandover.objects.exists())
