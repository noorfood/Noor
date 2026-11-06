"""Fictional end-to-end role journey; clients have independent sessions."""
import uuid
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from procurement.models import RawMaterialReceipt
from .models import CleaningJob, ProductionTransfer, FinishedHandover, FinishedStoreStock, SalesGoodsHandover, SalesManagerStock

def key():return str(uuid.uuid4())

class RoleJourneyTests(TestCase):
    def setUp(self):
        self.users={};self.clients={}
        for name,role,store in [('raw','store_officer','raw'),('prod','production_officer',None),('store','store_officer','finished'),('sales','sales_manager',None),('gm','manager',None),('md','md',None)]:
            user=User(username='journey_'+name,full_name='Test '+name,role=role,store_type=store,status='active');user.set_password('fictional-test-only-983!');user.save()
            client=Client();response=client.post(reverse('login'),{'username':user.username,'password':'fictional-test-only-983!'})
            self.assertEqual(response.status_code,302,name);self.users[name]=user;self.clients[name]=client
        self.today=timezone.localdate().isoformat()
    def post_ok(self,who,route,data):
        response=self.clients[who].post(route,data)
        self.assertEqual(response.status_code,302, f'{who} {route}: {response.status_code} {response.content[:1500]}')
        return response
    def test_full_recording_journey_across_six_roles(self):
        u=self.users;t=self.today
        self.post_ok('raw',reverse('procurement:receive'),{'request_key':key(),'date':t,'material_type':'maize','supplier':'Fictional supplier','num_bags':'20','approx_weight_kg':'','reference_no':'','notes':''})
        self.assertIsNone(RawMaterialReceipt.objects.get().approx_weight_kg)
        self.post_ok('raw',reverse('operations:cleaning_issue'),{'request_key':key(),'date':t,'material':'maize','cleaner':'Cleaner','bags':'10','weight_kg':''})
        job=CleaningJob.objects.get()
        self.post_ok('raw',reverse('operations:cleaning_return'),{'request_key':key(),'date':t,'job':job.pk,'clean_bags':'10','return_type':'final','clean_weight_kg':'','loss_weight_kg':''})
        self.post_ok('raw',reverse('operations:production_issue'),{'request_key':key(),'date':t,'material':'maize','bags':'5','weight_kg':'','recipient':u['prod'].pk})
        transfer=ProductionTransfer.objects.get()
        self.post_ok('prod',reverse('operations:production_decide',args=[transfer.pk]),{'decision':'accept','reason':''})
        self.post_ok('prod',reverse('operations:milling'),{'request_key':key(),'date':t,'material':'maize','shift':'morning','bags':'5','input_weight_kg':'','powder_kg':'400','powder_bags':'','machine':''})
        self.post_ok('prod',reverse('operations:packaging'),{'request_key':key(),'date':t,'material':'maize','shift':'morning','powder_used_kg':'100','powder_used_bags':'','packs':'10','pack_size_kg':'10'})
        self.post_ok('prod',reverse('operations:finished_send'),{'request_key':key(),'date':t,'material':'maize','pack_size_kg':'10','packs':'8','recipient':u['store'].pk})
        fg=FinishedHandover.objects.get()
        self.post_ok('store',reverse('operations:finished_detail',args=[fg.pk]),{'action':'receive','receipt-request_key':key(),'receipt-packs':'8','receipt-receipt_type':'final','receipt-reason':''})
        self.assertEqual(FinishedStoreStock.objects.get().packs,8)
        self.post_ok('store',reverse('operations:sales_goods_send'),{'request_key':key(),'date':t,'material':'maize','pack_size_kg':'10','packs':'3','recipient':u['sales'].pk})
        sg=SalesGoodsHandover.objects.get()
        self.post_ok('sales',reverse('operations:sales_goods_detail',args=[sg.pk]),{'action':'decide','decision-decision':'accept','decision-reason':''})
        self.assertEqual(SalesManagerStock.objects.get(officer=u['sales']).packs,3)
        self.assertEqual(FinishedStoreStock.objects.get().packs,5)
        self.post_ok('sales',reverse('commerce:create'),{'request_key':key(),'date':t,'material':'maize','pack_size_kg':'10','packs':'2','unit_price':'1000','buyer':'Fictional buyer','notes':''})
        from commerce.models import ReportedSale, ReportedCustomerPayment
        sale=ReportedSale.objects.get()
        self.post_ok('sales',reverse('commerce:detail',args=[sale.pk]),{'request_key':key(),'date':t,'method':'cash','amount':'500','note':''})
        self.assertEqual(SalesManagerStock.objects.get(officer=u['sales']).packs,1)
        self.assertEqual(ReportedCustomerPayment.objects.count(),1)
        from commerce.models import MoneyHandover
        self.post_ok('sales',reverse('commerce:money_send'),{'request_key':key(),'date':t,'recipient':u['gm'].pk,'method':'cash','amount':'500','reference':'','note':''})
        handover=MoneyHandover.objects.get(route='sales_to_gm')
        payment=ReportedCustomerPayment.objects.get()
        self.post_ok('sales',reverse('commerce:money_detail',args=[handover.pk]),{'action':'allocate','request_key':key(),'payment':payment.pk,'amount':'500','note':'Reported attribution'})
        self.post_ok('gm',reverse('commerce:money_detail',args=[handover.pk]),{'action':'receipt','request_key':key(),'amount':'200','note':''})
        self.post_ok('gm',reverse('commerce:money_detail',args=[handover.pk]),{'decision':'confirmed','reason':''})
        self.assertEqual(handover.receipts.count(),2)
        self.assertEqual(handover.payment_allocations.count(),1)
        from commerce.models import MoneyCorrectionRequest
        receipt=handover.receipts.first()
        self.post_ok('gm',reverse('commerce:correction_request',args=[handover.pk,'receipt',receipt.pk]),{'request_key':key(),'reason':'Incorrect amount'})
        correction=MoneyCorrectionRequest.objects.get()
        self.post_ok('md',reverse('commerce:correction_detail',args=[correction.pk]),{'decision':'approved','note':'Checked'})
        self.post_ok('gm',reverse('commerce:money_detail',args=[handover.pk]),{'action':'receipt','request_key':key(),'amount':'200','note':'Corrected receipt'})
        handover.refresh_from_db();self.assertEqual(handover.status,'confirmed')
        self.post_ok('gm',reverse('commerce:money_send'),{'request_key':key(),'date':t,'recipient':u['md'].pk,'method':'cash','amount':'500','reference':'','note':''})
        handover=MoneyHandover.objects.get(route='gm_to_md')
        self.post_ok('md',reverse('commerce:money_detail',args=[handover.pk]),{'decision':'confirmed','reason':''})
        self.assertEqual(MoneyHandover.objects.filter(status='confirmed').count(),2)
        for who in ('gm','md'):
            for name in ('operations:home','operations:production_home','operations:finished_home','operations:sales_goods_home','commerce:home'):
                resp=self.clients[who].get(reverse(name))
                self.assertEqual(resp.status_code,200,f'{who} {name}')
        self.assertEqual(self.clients['raw'].get(reverse('operations:sales_goods_home')).status_code,403)
        self.assertEqual(self.clients['sales'].get(reverse('operations:finished_home')).status_code,403)
