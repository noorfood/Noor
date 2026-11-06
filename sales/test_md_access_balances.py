"""Tests for the MD-access, balances-in-hand and SM-report work (Nov 2026):

- The MD can open (GET) every store-level page in his responsibility
  scope; submitting (POST) stays with the role that does the work.
- Bran receipts/sales keep an honest bran balance; a sale above the
  balance is refused and records nothing.
- The SM report shows one manager's stock, sales and money to send;
  an SM sees only his own report.
- The Oversight page shows what is in each person's hands.
"""
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse

from production.models import BranReceipt, BrandSale
from sales.models import SalesManagerCollection, SalesManagerPayment
from sales.test_direct_sale_partial import make_user, login
from sales.views import get_bran_balance


class MdReadAccessTests(TestCase):
    def setUp(self):
        self.md = make_user('md', 'md')
        self.gm = make_user('gm', 'manager')
        self.raw = make_user('raw', 'store_officer', store_type='raw')
        self.fin = make_user('fin', 'store_officer', store_type='finished')
        self.sm1 = make_user('sm1', 'sales_manager')
        self.sm2 = make_user('sm2', 'sales_manager')
        self.client_md = Client()
        login(self.client_md, 'md')
        self.client_raw = Client()
        login(self.client_raw, 'raw')
        self.client_fin = Client()
        login(self.client_fin, 'fin')
        self.client_sm1 = Client()
        login(self.client_sm1, 'sm1')
        self.client_sm2 = Client()
        login(self.client_sm2, 'sm2')

    def test_md_can_read_store_pages_but_cannot_record(self):
        # Every store-level page in the MD's responsibility scope opens.
        for url_name in ('procurement:dashboard', 'procurement:receive',
                         'procurement:issue', 'finished_store:issue',
                         'finished_store:record_delivery',
                         'sales:record_bran_sale',
                         'sales:record_bran_receipt'):
            resp = self.client_md.get(reverse(url_name))
            self.assertEqual(resp.status_code, 200, url_name)
        # But an MD submission is refused with the friendly denied page,
        # and nothing is recorded.
        for url_name, data in (
            ('procurement:issue', {'material_type': 'maize', 'num_bags': '1',
                                   'issued_to': 'Test', 'date': '2026-11-06'}),
            ('finished_store:issue', {'material_type': 'maize',
                                         'qty_sacks': '1', 'date': '2026-11-06'}),
            ('sales:record_bran_sale', {'date': '2026-11-06',
                                        'material_type': 'maize', 'qty': '1',
                                        'buyer_name': 'MD test',
                                        'amount_paid': '1000'}),
            ('sales:record_bran_receipt', {'date': '2026-11-06',
                                           'material_type': 'maize',
                                           'qty': '1'}),
        ):
            resp = self.client_md.post(reverse(url_name), data)
            self.assertEqual(resp.status_code, 403, url_name)
            self.assertContains(resp, 'Access denied', status_code=403)
        self.assertEqual(BranReceipt.objects.count(), 0)
        self.assertEqual(BrandSale.objects.count(), 0)

    def test_md_still_cannot_open_sm_recording_forms(self):
        # The SM's own recording forms would key their figures on
        # recorded_by = the SM, so the MD cannot open them at all — his
        # window into the SM is the SM dashboard and the SM report.
        for url_name in ('sales:record_distribution',
                         'sales:record_sales_result',
                         'sales:record_sm_payment'):
            resp = self.client_md.get(reverse(url_name))
            self.assertEqual(resp.status_code, 403, url_name)

    def test_bran_receipt_sale_and_balance(self):
        # No receipts yet: the balance is zero and a sale is refused.
        self.assertEqual(get_bran_balance('maize'), 0)
        resp = self.client_raw.post(reverse('sales:record_bran_sale'), {
            'date': '2026-11-06', 'material_type': 'maize', 'qty': '1',
            'buyer_name': 'Buyer One', 'amount_paid': '5000'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Not enough bran')
        self.assertEqual(BrandSale.objects.count(), 0)

        # A receipt makes the balance real.
        resp = self.client_raw.post(reverse('sales:record_bran_receipt'), {
            'date': '2026-11-06', 'material_type': 'maize', 'qty': '10'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(get_bran_balance('maize'), 10)

        # A sale within the balance reduces it, and the message says so.
        resp = self.client_raw.post(reverse('sales:record_bran_sale'), {
            'date': '2026-11-06', 'material_type': 'maize', 'qty': '6',
            'buyer_name': 'Buyer One', 'amount_paid': '30000'},
            follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Maize bran on hand now: 4 sacks')
        self.assertEqual(get_bran_balance('maize'), 4)

        # A sale above the balance is refused and records nothing.
        resp = self.client_raw.post(reverse('sales:record_bran_sale'), {
            'date': '2026-11-06', 'material_type': 'maize', 'qty': '5',
            'buyer_name': 'Buyer Two', 'amount_paid': '25000'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Not enough bran')
        self.assertEqual(BrandSale.objects.count(), 1)
        self.assertEqual(get_bran_balance('maize'), 4)

    def test_bran_report_reachable_by_raw_store_not_finished(self):
        BranReceipt.objects.create(date='2026-11-06', material_type='maize',
                                   qty_sacks=10, received_by=self.raw)
        BrandSale.objects.create(date='2026-11-06', material_type='maize',
                                 qty_sacks=6, buyer_name='Buyer One',
                                 price_per_sack=Decimal('5000'),
                                 total_amount=Decimal('30000'),
                                 payment_method='cash',
                                 amount_cash=Decimal('30000'),
                                 recorded_by=self.raw)
        resp = self.client_raw.get(reverse('reports:bran_sales'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Maize bran on hand')
        self.assertContains(resp, 'Bran received from milling')
        # A finished-store officer is not the raw store — denied.
        self.assertEqual(
            self.client_fin.get(reverse('reports:bran_sales')).status_code, 403)
        # The MD reads it.
        self.assertEqual(
            self.client_md.get(reverse('reports:bran_sales')).status_code, 200)

    def _make_collection(self, sm, qty=10):
        return SalesManagerCollection.objects.create(
            date='2026-11-06', material_type='maize', qty_sacks=qty,
            store_officer=self.fin, sales_manager=sm,
            price_per_sack=Decimal('8500'),
            total_value=Decimal('8500') * qty, status='accepted')

    def test_sm_report_shows_own_data_only(self):
        self._make_collection(self.sm1, qty=10)
        # SM1 sees his own report: 10 sacks and ₦85,000 to send.
        resp = self.client_sm1.get(reverse('sales:sm_report'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '10 bags')
        self.assertContains(resp, '85000')
        # SM2 cannot see SM1's report — even with ?sm=, he is forced
        # back to his own (empty) report.
        resp = self.client_sm2.get(
            reverse('sales:sm_report') + f'?sm={self.sm1.pk}')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, '85000')
        # The GM and the MD can pick SM1's report.
        gm_client = Client()
        login(gm_client, 'gm')
        resp = gm_client.get(
            reverse('sales:sm_report') + f'?sm={self.sm1.pk}')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '85000')
        resp = self.client_md.get(
            reverse('sales:sm_report') + f'?sm={self.sm1.pk}')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '85000')

    def test_oversight_shows_holdings_for_md_not_gm(self):
        self._make_collection(self.sm1, qty=10)
        resp = self.client_md.get(reverse('reports:oversight'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'What is in each person')
        self.assertContains(resp, 'Test sm1')
        self.assertContains(resp, 'Money to send to the company')
        # Oversight is the MD's hub — the GM is denied.
        gm_client = Client()
        login(gm_client, 'gm')
        self.assertEqual(
            gm_client.get(reverse('reports:oversight')).status_code, 403)

    def test_sm_dashboard_has_duty_buttons_and_money(self):
        self._make_collection(self.sm1, qty=10)
        resp = self.client_sm1.get(reverse('sales:dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Record a sale')
        self.assertContains(resp, 'My report')
        self.assertContains(resp, 'Record payment to company')
        self.assertContains(resp, 'Money to send to the company')
        self.assertContains(resp, '85000')
