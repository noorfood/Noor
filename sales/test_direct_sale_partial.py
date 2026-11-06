"""Tests for the MD/GM direct-sale changes (Nov 2026):
partial payment, outstanding balances, follow-up payments,
procurement removal for GM/MD, and the weekly summary.
"""
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from procurement.models import RawMaterialReceipt
from pricing.models import PriceConfig
from finished_store.models import FinishedGoodsIssuance
from production.models import BrandSale
from sales.models import DirectSalePayment, DirectSaleFollowUpPayment


def make_user(username, role, store_type=None):
    u = User(username=username, full_name='Test ' + username, role=role,
             status='active', store_type=store_type)
    u.set_password('fictional-test-123!')
    u.save()
    return u


def login(client, username):
    client.post(reverse('login'), {'username': username, 'password': 'fictional-test-123!'})


class DirectSalePartialTests(TestCase):
    def setUp(self):
        self.gm = make_user('gm', 'manager')
        self.md = make_user('md', 'md')
        self.fg = make_user('fg', 'store_officer', store_type='finished')
        PriceConfig.objects.create(
            channel='company', material_type='maize', product_size='10kg',
            price_per_unit=Decimal('8000'), effective_from=timezone.localdate(),
            created_by=self.md)
        # GM holds 10 sacks of maize (accepted company issuance).
        FinishedGoodsIssuance.objects.create(
            date=timezone.localdate(), material_type='maize', product_size='10kg',
            qty_issued=10, channel='company', buyer_name='GM hand',
            approver=self.gm, issued_by=self.fg, status='accepted')
        self.client_gm = Client()
        login(self.client_gm, 'gm')
        self.client_md = Client()
        login(self.client_md, 'md')

    def _sale_post(self, **over):
        data = {
            'material_type': 'maize', 'product_size': '10kg', 'qty_sold': '2',
            'buyer_name': 'Amina', 'customer_phone': '08031234567',
            'customer_location': 'Kano', 'payment_type': 'partial',
            'amount_received_cash': '5000', 'amount_received_transfer': '0',
            'notes': '',
        }
        data.update(over)
        return self.client_gm.post(reverse('sales:record_direct_sale'), data)

    def test_partial_sale_records_balance_and_appears_outstanding(self):
        resp = self._sale_post()
        self.assertEqual(resp.status_code, 302)
        sale = DirectSalePayment.objects.get()
        self.assertEqual(sale.payment_type, 'partial')
        self.assertEqual(sale.balance, Decimal('11000'))  # 2 x 8000 - 5000
        self.assertEqual(sale.customer_phone, '08031234567')
        self.assertEqual(sale.customer_location, 'Kano')
        self.assertEqual(sale.date, timezone.localdate())
        # Not outstanding until the MD confirms it.
        resp = self.client_gm.get(reverse('sales:outstanding_balances'))
        self.assertNotContains(resp, 'Amina')
        sale.status = 'confirmed'
        sale.save()
        resp = self.client_gm.get(reverse('sales:outstanding_balances'))
        self.assertContains(resp, 'Amina')
        self.assertContains(resp, '11000')

    def test_full_sale_has_zero_balance_and_never_lists(self):
        self._sale_post(payment_type='full', amount_received_cash='16000')
        sale = DirectSalePayment.objects.get()
        self.assertEqual(sale.balance, Decimal('0'))
        sale.status = 'confirmed'
        sale.save()
        resp = self.client_gm.get(reverse('sales:outstanding_balances'))
        self.assertContains(resp, 'Nobody owes money')

    def test_payment_validation(self):
        # Partial with nothing paid.
        resp = self._sale_post(amount_received_cash='0')
        self.assertEqual(DirectSalePayment.objects.count(), 0)
        self.assertContains(resp, 'more than zero')
        # Partial with everything paid.
        resp = self._sale_post(amount_received_cash='16000')
        self.assertEqual(DirectSalePayment.objects.count(), 0)
        self.assertContains(resp, 'less than the total')
        # Full with less than the total.
        resp = self._sale_post(payment_type='full', amount_received_cash='5000')
        self.assertEqual(DirectSalePayment.objects.count(), 0)
        self.assertContains(resp, 'must equal the total')
        # More than the total.
        resp = self._sale_post(amount_received_cash='20000')
        self.assertEqual(DirectSalePayment.objects.count(), 0)
        self.assertContains(resp, 'cannot be more than the total')
        # Bad phone number.
        resp = self._sale_post(customer_phone='abc')
        self.assertEqual(DirectSalePayment.objects.count(), 0)
        self.assertContains(resp, 'valid customer phone number')

    def test_follow_up_payment_reduces_then_clears(self):
        self._sale_post()
        sale = DirectSalePayment.objects.get()
        sale.status = 'confirmed'
        sale.save()
        url = reverse('sales:outstanding_customer', args=[sale.pk])
        # Overpaying is refused.
        resp = self.client_gm.post(url, {'amount': '20000', 'method': 'cash'})
        sale.refresh_from_db()
        self.assertEqual(sale.balance, Decimal('11000'))
        self.assertContains(resp, 'cannot be more than the balance')
        # A part payment reduces the balance; the customer stays listed.
        resp = self.client_gm.post(url, {'amount': '6000', 'method': 'transfer'})
        sale.refresh_from_db()
        self.assertEqual(sale.balance, Decimal('5000'))
        self.assertEqual(DirectSaleFollowUpPayment.objects.count(), 1)
        resp = self.client_gm.get(reverse('sales:outstanding_balances'))
        self.assertContains(resp, 'Amina')
        # Clearing the balance removes the customer from the page...
        self.client_gm.post(url, {'amount': '5000', 'method': 'cash'})
        sale.refresh_from_db()
        self.assertEqual(sale.balance, Decimal('0'))
        resp = self.client_gm.get(reverse('sales:outstanding_balances'))
        self.assertContains(resp, 'Nobody owes money')
        # ...but the record stays in sales history.
        resp = self.client_gm.get(reverse('sales:list_direct_sales'))
        self.assertContains(resp, 'Amina')

    def test_md_cannot_record_payment_but_can_view(self):
        self._sale_post()
        sale = DirectSalePayment.objects.get()
        sale.status = 'confirmed'
        sale.save()
        url = reverse('sales:outstanding_customer', args=[sale.pk])
        self.assertEqual(self.client_md.get(url).status_code, 200)
        self.assertContains(self.client_md.get(url), 'read-only')
        self.client_md.post(url, {'amount': '1000', 'method': 'cash'})
        sale.refresh_from_db()
        self.assertEqual(sale.balance, Decimal('11000'))
        self.assertEqual(DirectSaleFollowUpPayment.objects.count(), 0)

    def test_gm_can_do_procurement_and_md_can_read_it(self):
        # The GM does the raw-store duties until the MD assigns a raw
        # store officer, so the GM can receive and issue. The MD can open
        # the pages to read the balances, but must not record — a record
        # must show the person who did the work.
        for url_name in ('procurement:receive', 'procurement:issue',
                         'procurement:dashboard'):
            self.assertEqual(
                self.client_gm.get(reverse(url_name)).status_code, 200)
            self.assertEqual(
                self.client_md.get(reverse(url_name)).status_code, 200)
        # An MD submission is refused with the friendly denied page, and
        # nothing is recorded.
        resp = self.client_md.post(reverse('procurement:receive'), {
            'request_key': '00000000-0000-0000-0000-000000000001',
            'date': '2026-11-03', 'material_type': 'maize',
            'supplier': 'MD test', 'num_bags': '5'})
        self.assertEqual(resp.status_code, 403)
        self.assertContains(resp, 'Access denied', status_code=403)
        self.assertContains(resp, 'Go to home', status_code=403)
        self.assertEqual(RawMaterialReceipt.objects.count(), 0)
        # But the MD can still read the procurement records.
        self.assertEqual(self.client_md.get(reverse('procurement:list')).status_code, 200)

    def test_gm_money_outstanding_uses_aggregates(self):
        # Regression (Nov 2026): the old implementation summed
        # total_received per sale, one follow-up query per row — 152
        # queries for the GM's sales on the live data, ~38s on Oversight.
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from sales.views import get_gm_direct_money_outstanding
        for i in range(5):
            self._sale_post(buyer_name=f'Buyer {i}')
        sale = DirectSalePayment.objects.first()
        DirectSaleFollowUpPayment.objects.create(
            sale=sale, date=timezone.localdate(), amount=Decimal('1000'),
            method='cash', recorded_by=self.gm)
        with CaptureQueriesContext(connection) as ctx:
            out = get_gm_direct_money_outstanding(self.gm)
        # 5 sales x 5000 cash received + 1000 follow-up, nothing remitted.
        self.assertEqual(out, 26000)
        self.assertLessEqual(len(ctx), 5)

    def test_gm_receipt_records_gm_as_receiver(self):
        import uuid
        data = {'request_key': str(uuid.uuid4()), 'date': '2026-11-03',
                'material_type': 'maize', 'supplier': 'Test Supplier',
                'num_bags': '20', 'approx_weight_kg': '2000.00',
                'reference_no': 'TEST-GM-1', 'notes': ''}
        resp = self.client_gm.post(reverse('procurement:receive'), data)
        self.assertEqual(resp.status_code, 302)
        receipt = RawMaterialReceipt.objects.get()
        self.assertEqual(receipt.received_by, self.gm)

    def test_bran_sale_is_raw_store_only(self):
        raw = make_user('raw', 'store_officer', store_type='raw')
        client_raw = Client()
        login(client_raw, 'raw')
        self.assertEqual(
            client_raw.get(reverse('sales:record_bran_sale')).status_code, 200)
        self.assertEqual(
            self.client_gm.get(reverse('sales:record_bran_sale')).status_code, 403)
        # The MD can open the form to read the bran balance, but cannot
        # record a sale — that is the raw store officer's work.
        self.assertEqual(
            self.client_md.get(reverse('sales:record_bran_sale')).status_code, 200)
        resp = self.client_md.post(reverse('sales:record_bran_sale'), {
            'date': '2026-11-06', 'material_type': 'maize',
            'qty_sacks': '1', 'buyer_name': 'MD test',
            'unit_price': '1000'})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(BrandSale.objects.count(), 0)

    def test_denied_page_has_a_way_back(self):
        # The MD is not a Sales Manager, so an SM recording form is
        # denied outright — the friendly page must offer a way back.
        resp = self.client_md.get(reverse('sales:record_distribution'))
        self.assertEqual(resp.status_code, 403)
        self.assertContains(resp, 'Access denied', status_code=403)
        self.assertContains(resp, 'Go to home', status_code=403)

    def test_home_nav_is_simple_for_gm(self):
        resp = self.client_gm.get(reverse('reports:dashboard'))
        self.assertContains(resp, 'Outstanding Balances')
        self.assertContains(resp, 'Weekly Summary')
        self.assertContains(resp, 'Warehouse Deliveries')
        self.assertNotContains(resp, 'Receive raw materials')
        self.assertNotContains(resp, 'Profit')

    def test_weekly_summary_renders_for_gm_and_md(self):
        for client in (self.client_gm, self.client_md):
            resp = client.get(reverse('reports:weekly_summary'))
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, 'Outstanding balances')
            self.assertContains(resp, 'Daily records')

    def test_no_activity_today_is_recorded_once(self):
        from audit.models import AuditLog
        resp = self.client_gm.post(reverse('reports:no_activity'), {}, HTTP_REFERER='/')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(AuditLog.objects.filter(action='NO_ACTIVITY').count(), 1)
        self.client_gm.post(reverse('reports:no_activity'), {}, HTTP_REFERER='/')
        self.assertEqual(AuditLog.objects.filter(action='NO_ACTIVITY').count(), 1)
