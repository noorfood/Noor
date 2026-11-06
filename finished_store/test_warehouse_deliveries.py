"""Tests for warehouse deliveries (MD/GM request, Nov 2026)."""
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from finished_store.models import (
    FinishedGoodsReceipt, FinishedGoodsIssuance, Warehouse, WarehouseDelivery,
)
from sales.test_direct_sale_partial import make_user, login


class WarehouseDeliveryTests(TestCase):
    def setUp(self):
        self.gm = make_user('gm', 'manager')
        self.md = make_user('md', 'md')
        self.fg = make_user('fg', 'store_officer', store_type='finished')
        # 20 accepted maize sacks in the finished store.
        FinishedGoodsReceipt.objects.create(
            date=timezone.localdate(), material_type='maize', product_size='10kg',
            qty_received=20, received_by=self.fg, submitted_by=self.fg,
            status='accepted')
        # The 0013 migration seeds Kano/Sokoto/Abuja; reuse them.
        self.kano, _ = Warehouse.objects.get_or_create(name='Kano Warehouse', defaults={'state': 'Kano State'})
        self.client_fg = Client()
        login(self.client_fg, 'fg')
        self.client_gm = Client()
        login(self.client_gm, 'gm')
        self.client_md = Client()
        login(self.client_md, 'md')

    def _delivery_post(self, **over):
        data = {
            'warehouse': str(self.kano.pk), 'delivery_name': 'March supply run',
            'supply_to': 'Musa', 'supply_to_phone': '08031234567',
            'quantity': '5', 'material_type': 'maize', 'notes': '',
        }
        data.update(over)
        return self.client_fg.post(reverse('finished_store:record_delivery'), data)

    def test_record_delivery_creates_pending_issuance_and_no_stock_change(self):
        resp = self._delivery_post()
        self.assertEqual(resp.status_code, 302)
        delivery = WarehouseDelivery.objects.get()
        self.assertEqual(delivery.status, 'pending')
        self.assertEqual(delivery.date, timezone.localdate())
        issuance = delivery.issuance
        self.assertEqual(issuance.channel, 'warehouse')
        self.assertEqual(issuance.status, 'pending')
        # Stock is untouched until the receiver confirms.
        from finished_store.views import _fg_balance
        self.assertEqual(_fg_balance('maize', '10kg'), 20)

    def test_confirm_deducts_stock_and_difference_does_not(self):
        self._delivery_post()
        delivery = WarehouseDelivery.objects.get()
        url = reverse('finished_store:confirm_delivery', args=[delivery.pk])
        from finished_store.views import _fg_balance
        resp = self.client_fg.post(url, {'action': 'confirm', 'confirmed_by_name': 'Musa', 'confirm_note': ''})
        self.assertEqual(resp.status_code, 302)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'accepted')
        self.assertEqual(delivery.issuance.status, 'accepted')
        self.assertEqual(_fg_balance('maize', '10kg'), 15)

        self._delivery_post(delivery_name='Second run')
        delivery2 = WarehouseDelivery.objects.get(delivery_name='Second run')
        url2 = reverse('finished_store:confirm_delivery', args=[delivery2.pk])
        self.client_fg.post(url2, {'action': 'difference', 'confirmed_by_name': 'Musa', 'confirm_note': 'Only 4 sacks arrived'})
        delivery2.refresh_from_db()
        self.assertEqual(delivery2.status, 'rejected')
        self.assertEqual(delivery2.issuance.status, 'rejected')
        self.assertEqual(_fg_balance('maize', '10kg'), 15)

    def test_over_stock_delivery_is_refused(self):
        resp = self._delivery_post(quantity='25')
        self.assertEqual(WarehouseDelivery.objects.count(), 0)
        self.assertContains(resp, 'Not enough stock')

    def test_bad_phone_is_refused(self):
        resp = self._delivery_post(supply_to_phone='not-a-phone')
        self.assertEqual(WarehouseDelivery.objects.count(), 0)
        self.assertContains(resp, 'valid phone number')

    def test_gm_and_md_can_view_but_not_record(self):
        self._delivery_post()
        for client in (self.client_gm, self.client_md):
            self.assertEqual(client.get(reverse('finished_store:deliveries_report')).status_code, 200)
            self.assertContains(client.get(reverse('finished_store:deliveries_report')), 'read-only')
        # The GM is still denied the recording form.
        self.assertEqual(self.client_gm.get(reverse('finished_store:record_delivery')).status_code, 403)
        # The MD may open it read-only (Nov 2026: no MD page denied in his
        # responsibility scope), but may not record — the form shows the
        # MD notice instead of a submit button, and a POST is refused.
        resp = self.client_md.get(reverse('finished_store:record_delivery'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'viewing as MD')
        resp = self.client_md.post(reverse('finished_store:record_delivery'), {
            'warehouse': str(self.kano.pk), 'delivery_name': 'MD attempt',
            'supply_to': 'Musa', 'supply_to_phone': '08031234567',
            'quantity': '1', 'material_type': 'maize', 'notes': ''})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(WarehouseDelivery.objects.filter(delivery_name='MD attempt').exists())

    def test_report_filters_by_warehouse(self):
        self._delivery_post()
        sokoto, _ = Warehouse.objects.get_or_create(name='Sokoto Warehouse', defaults={'state': 'Sokoto State'})
        self._delivery_post(delivery_name='Sokoto run', warehouse=str(sokoto.pk))
        url = reverse('finished_store:deliveries_report')
        self.assertContains(self.client_gm.get(url), 'March supply run')
        self.assertContains(self.client_gm.get(url), 'Sokoto run')
        resp = self.client_gm.get(url, {'warehouse': str(sokoto.pk)})
        self.assertContains(resp, 'Sokoto run')
        self.assertNotContains(resp, 'March supply run')

    def test_warehouse_list_is_manageable(self):
        # Add a new warehouse, reject a duplicate, deactivate it.
        resp = self.client_fg.post(reverse('finished_store:warehouses'),
                                   {'action': 'add', 'name': 'Kaduna Warehouse', 'state': 'Kaduna State'})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Warehouse.objects.filter(name='Kaduna Warehouse').exists())
        resp = self.client_fg.post(reverse('finished_store:warehouses'),
                                   {'action': 'add', 'name': 'kaduna warehouse', 'state': ''})
        self.assertContains(resp, 'already exists')
        kaduna = Warehouse.objects.get(name='Kaduna Warehouse')
        self.client_fg.post(reverse('finished_store:warehouses'),
                            {'action': 'toggle', 'warehouse_id': str(kaduna.pk)})
        kaduna.refresh_from_db()
        self.assertFalse(kaduna.is_active)
        # An inactive warehouse is not offered on the delivery form.
        resp = self.client_fg.get(reverse('finished_store:record_delivery'))
        self.assertNotContains(resp, 'Kaduna Warehouse')
