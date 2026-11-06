from datetime import timedelta
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
from .models import ReportedSale, ReportedCustomerPayment
from .services import record_sale, record_customer_payment

class CommerceTests(TestCase):
    def setUp(self):
        self.users={};self.clients={}
        for name,role in [('sm','sales_manager'),('other','sales_manager'),('md','md'),('gm','manager'),('production','production_officer')]:
            u=User(username='commerce_'+name,full_name=name,role=role,status='active');u.set_password('fictional-test-password!');u.save()
            c=Client();c.post(reverse('login'),{'username':u.username,'password':'fictional-test-password!'})
            self.users[name]=u;self.clients[name]=c
        self.today=timezone.localdate();self.holding=SalesManagerStock.objects.create(officer=self.users['sm'],material='maize',pack_size_kg=10,packs=10)
    def sale(self,**overrides):
        d=dict(actor=self.users['sm'],key=uuid4(),date=self.today,material='maize',pack_size_kg=10,packs=3,unit_price='100.50');d.update(overrides)
        return record_sale(**d)
    def payment(self,sale,**overrides):
        d=dict(sale_id=sale.pk,actor=self.users['sm'],key=uuid4(),date=self.today,amount='100',method='cash');d.update(overrides)
        return record_customer_payment(**d)
    def test_sale_uses_only_own_stock_and_computes_total(self):
        s=self.sale();self.holding.refresh_from_db();self.assertEqual(self.holding.packs,7);self.assertEqual(s.total,Decimal('301.50'))
        with self.assertRaises(ValidationError):self.sale(packs=8)
        with self.assertRaises(ValidationError):self.sale(actor=self.users['other'])
        self.holding.refresh_from_db();self.assertEqual(self.holding.packs,7)
    def test_duplicate_key_does_not_double_deplete(self):
        k=uuid4();self.sale(key=k)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():self.sale(key=k)
        self.holding.refresh_from_db();self.assertEqual(self.holding.packs,7);self.assertEqual(ReportedSale.objects.count(),1)
    def test_invalid_price_date_and_role(self):
        for changes in ({'unit_price':'0'},{'unit_price':'NaN'},{'date':self.today+timedelta(days=1)},{'actor':self.users['md']}):
            with self.subTest(changes=changes),self.assertRaises(ValidationError):self.sale(**changes)
        self.assertEqual(ReportedSale.objects.count(),0)
    def test_payments_are_reports_and_do_not_change_stock(self):
        s=self.sale();self.payment(s,amount='200');self.payment(s,amount='150',method='transfer')
        self.holding.refresh_from_db();self.assertEqual(self.holding.packs,7)
        page=self.clients['md'].get(reverse('commerce:detail',args=[s.pk]))
        self.assertContains(page,'Reported payments exceed the reported sale total');self.assertContains(page,'not been verified')
        with self.assertRaises(ValidationError):self.payment(s,actor=self.users['other'])
        with self.assertRaises(ValidationError):self.payment(s,date=self.today-timedelta(days=1))
        self.assertEqual(ReportedCustomerPayment.objects.count(),2)
    def test_access_and_scope(self):
        s=self.sale();url=reverse('commerce:detail',args=[s.pk])
        for name in ('sm','md','gm'):self.assertEqual(self.clients[name].get(url).status_code,200)
        self.assertEqual(self.clients['other'].get(url).status_code,404)
        self.assertEqual(self.clients['production'].get(url).status_code,403)
        self.assertEqual(self.clients['md'].post(url,{}).status_code,403)
        self.assertEqual(self.clients['gm'].post(reverse('commerce:create'),{}).status_code,403)
    def test_http_sale_payment_and_duplicate(self):
        k=str(uuid4());t=self.today.isoformat();c=self.clients['sm']
        data={'request_key':k,'date':t,'material':'maize','pack_size_kg':'10','packs':'3','unit_price':'100.50','buyer':'','notes':''}
        r=c.post(reverse('commerce:create'),data);self.assertEqual(r.status_code,302)
        r=c.post(reverse('commerce:create'),data);self.assertContains(r,'already recorded')
        s=ReportedSale.objects.get();p={'request_key':str(uuid4()),'date':t,'method':'cash','amount':'50','note':''};url=reverse('commerce:detail',args=[s.pk])
        self.assertEqual(c.post(url,p).status_code,302);self.assertContains(c.post(url,p),'already recorded')
        self.assertEqual(ReportedCustomerPayment.objects.count(),1)
    def test_audit_failure_rolls_back_sale_and_stock(self):
        data={'request_key':str(uuid4()),'date':self.today.isoformat(),'material':'maize','pack_size_kg':'10','packs':'3','unit_price':'100','buyer':'','notes':''}
        with patch('commerce.views.log_action',side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):self.clients['sm'].post(reverse('commerce:create'),data)
        self.holding.refresh_from_db();self.assertEqual(self.holding.packs,10);self.assertFalse(ReportedSale.objects.exists())
    def test_instance_edit_delete_blocked(self):
        s=self.sale();p=self.payment(s)
        for obj in (s,p):
            with self.assertRaises(ValueError):obj.save()
            with self.assertRaises(ValueError):obj.delete()
