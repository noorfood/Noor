from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from .models import MoneyHandover, MoneyHandoverEvent, ReportedSale, ReportedCustomerPayment
from .services import report_money_handover, decide_money_handover

class MoneyHandoverTests(TestCase):
    def setUp(self):
        self.users={};self.clients={};self.today=timezone.localdate()
        for name,role in [('sm','sales_manager'),('other','sales_manager'),('gm','manager'),('gm2','manager'),('md','md'),('prod','production_officer')]:
            u=User(username='money_'+name,full_name='Test '+name,role=role,status='active');u.set_password('fictional-money-test-983!');u.save()
            c=Client();c.post(reverse('login'),{'username':u.username,'password':'fictional-money-test-983!'})
            self.users[name]=u;self.clients[name]=c
    def report(self,**overrides):
        d=dict(actor=self.users['sm'],recipient_id=self.users['gm'].pk,key=uuid4(),date=self.today,method='cash',amount='200.50');d.update(overrides)
        return report_money_handover(**d)
    def test_sender_and_exact_recipient_and_status(self):
        h=self.report();self.assertEqual(h.route,'sales_to_gm');self.assertEqual(h.status,'pending')
        for actor in (self.users['sm'],self.users['gm2'],self.users['md']):
            with self.assertRaises(ValidationError):decide_money_handover(handover_id=h.pk,actor=actor,decision='confirmed')
        decide_money_handover(handover_id=h.pk,actor=self.users['gm'],decision='confirmed')
        h.refresh_from_db();self.assertEqual(h.status,'confirmed');self.assertEqual(h.decided_by_id,self.users['gm'].pk)
        with self.assertRaises(ValidationError):decide_money_handover(handover_id=h.pk,actor=self.users['gm'],decision='confirmed')
        self.assertEqual(list(h.events.values_list('kind',flat=True)),['sent','confirmed'])
        self.assertFalse(ReportedSale.objects.exists());self.assertFalse(ReportedCustomerPayment.objects.exists())
    def test_gm_to_md_and_sender_role_change(self):
        h=self.report(actor=self.users['gm'],recipient_id=self.users['md'].pk,method='transfer')
        self.assertEqual(h.route,'gm_to_md')
        self.users['gm'].role='sales_manager';self.users['gm'].save(update_fields=['role'])
        decide_money_handover(handover_id=h.pk,actor=self.users['md'],decision='confirmed')
        h.refresh_from_db();self.assertEqual(h.status,'confirmed')
    def test_recipient_must_still_be_active_and_authorized(self):
        h=self.report();u=self.users['gm'];u.status='suspended';u.save(update_fields=['status'])
        with self.assertRaises(ValidationError):decide_money_handover(handover_id=h.pk,actor=u,decision='confirmed')
        u.status='active';u.role='sales_manager';u.save(update_fields=['status','role'])
        with self.assertRaises(ValidationError):decide_money_handover(handover_id=h.pk,actor=u,decision='confirmed')
        h.refresh_from_db();self.assertEqual(h.status,'pending')
    def test_review_requires_reason_and_cannot_be_silently_reconfirmed(self):
        h=self.report()
        with self.assertRaises(ValidationError):decide_money_handover(handover_id=h.pk,actor=self.users['gm'],decision='review',reason='  ')
        decide_money_handover(handover_id=h.pk,actor=self.users['gm'],decision='review',reason='Count differs')
        with self.assertRaises(ValidationError):decide_money_handover(handover_id=h.pk,actor=self.users['gm'],decision='confirmed')
        h.refresh_from_db();self.assertEqual(h.reason,'Count differs');self.assertEqual(h.status,'review')
        decide_money_handover(handover_id=h.pk,actor=self.users['gm'],decision='confirmed',reason='Full amount subsequently received')
        h.refresh_from_db();self.assertEqual(h.status,'confirmed')
        self.assertEqual(list(h.events.values_list('kind',flat=True)),['sent','review','confirmed'])
        self.assertEqual(h.events.get(kind='review').reason,'Count differs')
    def test_invalid_data_and_duplicate_request(self):
        for changes in ({'amount':'-1'},{'amount':'NaN'},{'method':'cheque'},{'date':self.today+timedelta(days=1)},{'actor':self.users['prod']},{'recipient_id':self.users['md'].pk}):
            with self.subTest(changes=changes),self.assertRaises(ValidationError):self.report(**changes)
        k=uuid4();self.report(key=k)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():self.report(key=k)
        self.assertEqual(MoneyHandover.objects.count(),1);self.assertEqual(MoneyHandoverEvent.objects.count(),1)
    def test_instance_history_guards(self):
        h=self.report()
        with self.assertRaises(ValueError):h.delete()
        h.amount=1
        with self.assertRaises(ValueError):h.save()
        e=h.events.get()
        with self.assertRaises(ValueError):e.delete()
        with self.assertRaises(ValueError):e.save()
    def test_http_scopes_and_confirmation(self):
        h=self.report();url=reverse('commerce:money_detail',args=[h.pk])
        self.assertEqual(self.clients['other'].get(url).status_code,404)
        self.assertEqual(self.clients['gm2'].get(url).status_code,404)
        self.assertEqual(self.clients['prod'].get(url).status_code,403)
        self.assertEqual(self.clients['md'].get(url).status_code,200)
        self.assertEqual(self.clients['md'].post(url,{'decision':'confirmed','reason':''}).status_code,403)
        self.assertEqual(self.clients['gm'].post(url,{'decision':'review','reason':''}).status_code,200)
        self.assertEqual(self.clients['gm'].post(url,{'decision':'confirmed','reason':''}).status_code,302)
        self.assertEqual(self.clients['gm'].post(url,{'decision':'confirmed','reason':''}).status_code,403)
    def test_http_duplicate_and_audit_rollback(self):
        url=reverse('commerce:money_send');c=self.clients['sm']
        d={'request_key':str(uuid4()),'date':self.today.isoformat(),'recipient':self.users['gm'].pk,'method':'transfer','amount':'200','reference':'','note':''}
        with patch('commerce.views.log_action',side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):c.post(url,d)
        self.assertEqual(MoneyHandover.objects.count(),0);self.assertEqual(MoneyHandoverEvent.objects.count(),0)
        self.assertEqual(c.post(url,d).status_code,302);self.assertContains(c.post(url,d),'already recorded')
        self.assertEqual(MoneyHandover.objects.count(),1)
    def test_decision_audit_failure_rolls_back(self):
        h=self.report();url=reverse('commerce:money_detail',args=[h.pk])
        with patch('commerce.views.log_action',side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):self.clients['gm'].post(url,{'decision':'confirmed','reason':''})
        h.refresh_from_db();self.assertEqual(h.status,'pending');self.assertEqual(h.events.count(),1)
    def test_management_queue_counts_only_assigned_open_handovers(self):
        a=self.report();self.report(recipient_id=self.users['gm2'].pk)
        self.report(actor=self.users['gm'],recipient_id=self.users['md'].pk)
        response=self.clients['gm'].get(reverse('reports:dashboard'))
        self.assertEqual(response.context['my_money_reviews'],1)
        response=self.clients['md'].get(reverse('reports:dashboard'))
        self.assertEqual(response.context['my_money_reviews'],1)
        decide_money_handover(handover_id=a.pk,actor=self.users['gm'],decision='confirmed')
        self.assertEqual(self.clients['gm'].get(reverse('reports:dashboard')).context['my_money_reviews'],0)
    def test_http_review_and_confirm_after_review(self):
        h=self.report();url=reverse('commerce:money_detail',args=[h.pk]);c=self.clients['gm']
        self.assertEqual(c.post(url,{'decision':'review','reason':'Amount not fully received'}).status_code,302)
        self.assertContains(c.post(url,{'decision':'confirmed','reason':''}),'Enter a reason')
        self.assertEqual(c.post(url,{'decision':'confirmed','reason':'Full amount later received'}).status_code,302)
        self.assertContains(c.get(url),'Amount not fully received')
        self.assertContains(c.get(url),'Full amount later received')
    def test_csrf_is_required_for_handover_submission(self):
        from accounts.session_security import session_fingerprint
        c=Client(enforce_csrf_checks=True);s=c.session;u=self.users['sm']
        s['user_id']=u.pk;s['actual_user_id']=u.pk;s['user_role']=u.role;s['user_name']=u.full_name;s['password_fingerprint']=session_fingerprint(u);s.save()
        url=reverse('commerce:money_send')
        d={'request_key':str(uuid4()),'date':self.today.isoformat(),'recipient':self.users['gm'].pk,'method':'cash','amount':'200','reference':'','note':''}
        self.assertEqual(c.post(url,d).status_code,403);self.assertEqual(MoneyHandover.objects.count(),0)
        self.assertEqual(c.get(url).status_code,200)
        self.assertEqual(c.post(url,d,HTTP_X_CSRFTOKEN=c.cookies['csrftoken'].value).status_code,302)
    def test_handovers_are_paginated(self):
        for _ in range(51):self.report()
        c=self.clients['gm'];url=reverse('commerce:money_home')
        first=c.get(url);self.assertEqual(first.context['page_obj'].paginator.count,51);self.assertContains(first,'Next')
        second=c.get(url+'?page=2');self.assertContains(second,'Previous');self.assertEqual(len(second.context['items']),1)
    def test_database_rejects_inconsistent_decision_or_invalid_method(self):
        h=self.report()
        for updates in ({'status':'confirmed'},{'method':'other'},{'route':'unknown'}):
            with self.subTest(updates=updates),self.assertRaises(IntegrityError):
                with transaction.atomic():MoneyHandover.objects.filter(pk=h.pk).update(**updates)
        h.refresh_from_db();self.assertEqual(h.status,'pending');self.assertEqual(h.method,'cash')
