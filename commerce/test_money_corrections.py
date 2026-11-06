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
from commerce.models import MoneyCorrectionRequest, MoneyHandoverEvent
from commerce.services import (record_sale,record_customer_payment,report_money_handover,record_money_receipt,report_payment_allocation,request_money_correction,decide_money_correction,decide_money_handover,_received_total)

class CorrectionTests(TestCase):
    def setUp(self):
        self.users={};self.clients={}
        for name,role in [('sm','sales_manager'),('gm','manager'),('md','md'),('md2','md'),('other','sales_manager')]:
            u=User(username='corr_'+name,full_name='Test '+name,role=role,status='active');u.set_password('fictional-correction-458!');u.save()
            c=Client();c.post(reverse('login'),{'username':u.username,'password':'fictional-correction-458!'})
            self.users[name]=u;self.clients[name]=c
        sm=self.users['sm'];gm=self.users['gm'];today=timezone.localdate()
        SalesManagerStock.objects.create(officer=sm,material='maize',pack_size_kg=10,packs=1)
        sale=record_sale(actor=sm,key=uuid4(),date=today,material='maize',pack_size_kg=10,packs=1,unit_price=100)
        self.p=record_customer_payment(sale_id=sale.pk,actor=sm,key=uuid4(),date=today,method='cash',amount=100)
        self.h=report_money_handover(actor=sm,recipient_id=gm.pk,key=uuid4(),date=today,method='cash',amount=100)
    def receipt(self,amount='100'):
        return record_money_receipt(handover_id=self.h.pk,actor=self.users['gm'],key=uuid4(),amount=amount)
    def allocation(self,amount='80'):
        return report_payment_allocation(actor=self.users['sm'],payment_id=self.p.pk,handover_id=self.h.pk,key=uuid4(),amount=amount)
    def req(self,kind,target,actor='gm',reason='Mistake'):
        return request_money_correction(actor=self.users[actor],handover_id=self.h.pk,kind=kind,target_id=target.pk,key=uuid4(),reason=reason)
    def decide(self,c,decision='approved',actor='md',note='Checked'):
        return decide_money_correction(actor=self.users[actor],correction_id=c.pk,decision=decision,note=note)
    def test_receipt_correction_reopens_confirmed_and_retains_history(self):
        r=self.receipt();self.h.refresh_from_db();self.assertEqual(self.h.status,'confirmed')
        c=self.req('receipt',r);self.assertEqual(_received_total(self.h),Decimal('100'))
        self.decide(c);self.h.refresh_from_db();self.assertEqual(self.h.status,'review');self.assertEqual(_received_total(self.h),Decimal('0'))
        self.assertEqual(self.h.receipts.count(),1)
        with self.assertRaises(ValidationError):self.receipt()
        record_money_receipt(handover_id=self.h.pk,actor=self.users['gm'],key=uuid4(),amount='100',note='Corrected receipt')
        self.h.refresh_from_db();self.assertEqual(self.h.status,'confirmed');self.assertEqual(_received_total(self.h),Decimal('100'))
        self.assertEqual(self.h.events.filter(kind='confirmed').count(),2);self.assertEqual(self.h.events.filter(kind='corrected').count(),1)
    def test_allocation_correction_releases_caps_only_when_approved(self):
        a=self.allocation();c=self.req('allocation',a,actor='sm')
        with self.assertRaises(ValidationError):self.allocation('30')
        self.decide(c);self.allocation('100')
        self.assertEqual(self.h.payment_allocations.count(),2);self.assertEqual(self.h.status,'pending')
    def test_rejection_does_not_change_balance_and_can_be_requested_again(self):
        r=self.receipt('30');c=self.req('receipt',r);self.decide(c,'rejected')
        self.assertEqual(_received_total(self.h),Decimal('30'));self.assertEqual(self.req('receipt',r).status,'pending')
    def test_permissions_reasons_duplicate_and_decisions(self):
        r=self.receipt('30')
        with self.assertRaises(ValidationError):self.req('receipt',r,actor='other')
        with self.assertRaises(ValidationError):self.req('receipt',r,reason=' ')
        c=self.req('receipt',r)
        with self.assertRaises(ValidationError):self.req('receipt',r)
        with self.assertRaises(ValidationError):self.decide(c,actor='gm')
        with self.assertRaises(ValidationError):self.decide(c,note='')
        self.decide(c)
        with self.assertRaises(ValidationError):self.decide(c)
        with self.assertRaises(ValidationError):self.req('receipt',r)
        with self.assertRaises(ValueError):c.delete()
    def test_md_cannot_approve_own_request_or_receipt(self):
        gm=self.users['gm'];md=self.users['md'];h=report_money_handover(actor=gm,recipient_id=md.pk,key=uuid4(),date=timezone.localdate(),method='cash',amount=100)
        r=record_money_receipt(handover_id=h.pk,actor=md,key=uuid4(),amount=20)
        c=request_money_correction(actor=gm,handover_id=h.pk,kind='receipt',target_id=r.pk,key=uuid4(),reason='Mistake')
        with self.assertRaises(ValidationError):self.decide(c,actor='md')
        self.decide(c,actor='md2')
    def test_http_workflow_permission_and_audit_rollback(self):
        r=self.receipt('30');url=reverse('commerce:correction_request',args=[self.h.pk,'receipt',r.pk]);data={'request_key':str(uuid4()),'reason':'Mistake'}
        self.assertEqual(self.clients['other'].get(url).status_code,404)
        with patch('commerce.views.log_action',side_effect=RuntimeError('audit failure')):
            with self.assertRaises(RuntimeError):self.clients['gm'].post(url,data)
        self.assertEqual(MoneyCorrectionRequest.objects.count(),0)
        self.assertEqual(self.clients['gm'].post(url,data).status_code,302)
        c=MoneyCorrectionRequest.objects.get();detail=reverse('commerce:correction_detail',args=[c.pk])
        self.assertEqual(self.clients['gm'].get(detail).status_code,403)
        with patch('commerce.views.log_action',side_effect=RuntimeError('audit failure')):
            with self.assertRaises(RuntimeError):self.clients['md'].post(detail,{'decision':'approved','note':'Checked'})
        c.refresh_from_db();self.assertEqual(c.status,'pending');self.assertEqual(_received_total(self.h),Decimal('30'))
        self.assertEqual(self.clients['md'].post(detail,{'decision':'approved','note':'Checked'}).status_code,302)
        self.assertEqual(_received_total(self.h),Decimal('0'))
        page=self.clients['gm'].get(reverse('commerce:money_detail',args=[self.h.pk]));self.assertContains(page,'Corrected');self.assertContains(page,'₦0')
    def test_database_constraints_enforce_target_and_decision(self):
        r=self.receipt('20');c=self.req('receipt',r)
        for changes in ({'receipt':None},{'status':'approved'}):
            with self.subTest(changes=changes),self.assertRaises(IntegrityError):
                with transaction.atomic():MoneyCorrectionRequest.objects.filter(pk=c.pk).update(**changes)
    def test_correction_requests_and_decisions_require_csrf(self):
        from accounts.session_security import session_fingerprint
        def client_for(u):
            client=Client(enforce_csrf_checks=True);s=client.session
            s['user_id']=u.pk;s['actual_user_id']=u.pk;s['user_role']=u.role;s['user_name']=u.full_name;s['password_fingerprint']=session_fingerprint(u);s.save()
            return client
        r=self.receipt('30');gm=client_for(self.users['gm'])
        url=reverse('commerce:correction_request',args=[self.h.pk,'receipt',r.pk]);data={'request_key':str(uuid4()),'reason':'Correction'}
        self.assertEqual(gm.post(url,data).status_code,403);self.assertEqual(MoneyCorrectionRequest.objects.count(),0)
        self.assertEqual(gm.get(url).status_code,200)
        self.assertEqual(gm.post(url,data,HTTP_X_CSRFTOKEN=gm.cookies['csrftoken'].value).status_code,302)
        c=MoneyCorrectionRequest.objects.get();md=client_for(self.users['md']);detail=reverse('commerce:correction_detail',args=[c.pk])
        self.assertEqual(md.post(detail,{'decision':'approved','note':'Checked'}).status_code,403)
        self.assertEqual(md.get(detail).status_code,200)
        self.assertEqual(md.post(detail,{'decision':'approved','note':'Checked'},HTTP_X_CSRFTOKEN=md.cookies['csrftoken'].value).status_code,302)
