import datetime
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse, NoReverseMatch
from django.utils import timezone
from accounts.models import User
from sales.models import DirectSalePayment


def _week_bounds(today):
    start = today - datetime.timedelta(days=(today.weekday() + 1) % 7)
    return start, start + datetime.timedelta(days=6)


def _week_heading(start, end):
    return (f"Week of {start.day} {start.strftime('%B %Y')} "
            f"to {end.day} {end.strftime('%B %Y')}")


class SafeReportingTests(TestCase):
    def setUp(self):
        user = User.objects.create(username='boss', full_name='Director', role='md', status='active')
        user.set_password('test-password')
        user.save()
        self.client.post(reverse('login'), {'username':'boss', 'password':'test-password'})

    def test_overview_renders(self):
        response = self.client.get(reverse('reports:dashboard'))
        self.assertContains(response, 'Needs attention')
        self.assertContains(response, 'What do you want to do?')
        self.assertNotContains(response, 'Receive raw materials')
        self.assertNotContains(response, 'Profit')

    def test_profit_routes_are_gone(self):
        with self.assertRaises(NoReverseMatch):
            reverse('reports:financial_summary')
        with self.assertRaises(NoReverseMatch):
            reverse('reports:estimate_opening')
        with self.assertRaises(NoReverseMatch):
            reverse('reports:estimate_batches')
        with self.assertRaises(NoReverseMatch):
            reverse('reports:estimate_expenses')

    def test_weekly_summary_and_reports_index_render(self):
        self.assertEqual(self.client.get(reverse('reports:weekly_summary')).status_code, 200)
        response = self.client.get(reverse('reports:index'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Weekly summary')
        self.assertContains(response, 'Outstanding balances')


class OversightAndWeeklyTests(TestCase):
    """MD oversight nav (Nov 2026 follow-up): the MD gets an Oversight
    hub page; the weekly summary week ends on Saturday and shows
    per-staff performance; the outstanding list shows name + balance."""

    def setUp(self):
        self.md = User.objects.create(username='boss', full_name='Director', role='md', status='active')
        self.md.set_password('test-password')
        self.md.save()
        self.gm = User.objects.create(username='gm', full_name='General Manager', role='manager', status='active')
        self.gm.set_password('test-password')
        self.gm.save()
        self.client.post(reverse('login'), {'username': 'boss', 'password': 'test-password'})
        self.gm_client = Client()
        self.gm_client.post(reverse('login'), {'username': 'gm', 'password': 'test-password'})

    def test_md_nav_has_oversight_gm_does_not(self):
        self.assertContains(self.client.get(reverse('reports:dashboard')), 'Oversight')
        self.assertNotContains(self.gm_client.get(reverse('reports:dashboard')), 'Oversight')

    def test_oversight_page_md_only(self):
        resp = self.client.get(reverse('reports:oversight'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Procurement records')
        self.assertContains(resp, 'Staff')
        self.assertContains(resp, 'Prices')
        self.assertEqual(self.gm_client.get(reverse('reports:oversight')).status_code, 403)

    def test_oversight_holdings_one_row_per_cleaner(self):
        # Two spellings of one cleaner (the MD confirmed it is one
        # person, Abdullahi) must show as a single row with the combined
        # bags out for cleaning. A per-name distinct() repeats rows on
        # PostgreSQL when the model has a default ordering, so the view
        # groups with aggregates instead.
        from procurement.models import RawMaterialIssuance
        from cleaning.models import CleanRawReceipt
        today = timezone.localdate()
        iss1 = RawMaterialIssuance.objects.create(
            date=today, material_type='maize', num_bags_issued=40,
            issued_to='Abdullahi', issued_by=self.gm)
        RawMaterialIssuance.objects.create(
            date=today, material_type='maize', num_bags_issued=20,
            issued_to='Abdullahhi', issued_by=self.gm)
        CleanRawReceipt.objects.create(
            date=today, raw_issuance=iss1, material_type='maize',
            num_bags=10, received_by=self.gm)
        resp = self.client.get(reverse('reports:oversight'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        # 40 + 20 issued, 10 received back = 50 out, one row.
        self.assertEqual(content.count('Cleaner — Abdullahi'), 1)
        self.assertNotContains(resp, 'Abdullahhi')
        self.assertContains(resp, '50 bags issued, not yet received back')

    def test_weekly_summary_week_ends_saturday(self):
        today = timezone.localdate()
        start, end = _week_bounds(today)
        resp = self.client.get(reverse('reports:weekly_summary'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, _week_heading(start, end))
        self.assertContains(resp, 'Previous week')
        # A past week, picked by its Saturday date.
        past_end = end - datetime.timedelta(days=14)
        past_start = past_end - datetime.timedelta(days=6)
        resp = self.client.get(reverse('reports:weekly_summary'), {'week': past_end.isoformat()})
        self.assertContains(resp, _week_heading(past_start, past_end))

    def test_weekly_summary_staff_performance(self):
        DirectSalePayment.objects.create(
            date=timezone.localdate(), material_type='maize', qty_sold=2,
            unit_price=Decimal('8000'), buyer_name='Amina',
            customer_phone='08031234567', customer_location='Kano',
            payment_type='full', amount_received_cash=Decimal('16000'),
            recorded_by=self.gm, status='confirmed')
        resp = self.client.get(reverse('reports:weekly_summary'))
        self.assertContains(resp, 'What each person did this week')
        self.assertContains(resp, 'General Manager')
        self.assertContains(resp, '16000')

    def test_outstanding_list_shows_name_and_balance_only(self):
        DirectSalePayment.objects.create(
            date=timezone.localdate(), material_type='maize', qty_sold=2,
            unit_price=Decimal('8000'), buyer_name='Amina',
            customer_phone='08031234567', customer_location='Kano',
            payment_type='partial', amount_received_cash=Decimal('5000'),
            balance=Decimal('11000'), recorded_by=self.gm, status='confirmed')
        resp = self.client.get(reverse('sales:outstanding_balances'))
        self.assertContains(resp, 'Amina')
        self.assertContains(resp, '11000')
        self.assertContains(resp, 'Balance owed')
        self.assertNotContains(resp, 'Paid so far')
        self.assertNotContains(resp, 'Date collected')


class SalesReportTotalsTests(TestCase):
    """The sales report totals are computed in the database (Nov 2026
    rewrite). These figures pin the exact numbers the old row-by-row
    version produced, so a regression in the aggregation shows up here."""

    def setUp(self):
        self.md = User.objects.create(username='boss', full_name='Director', role='md', status='active')
        self.md.set_password('test-password')
        self.md.save()
        self.gm = User.objects.create(username='gm', full_name='General Manager', role='manager', status='active')
        self.gm.set_password('test-password')
        self.gm.save()
        self.sm = User.objects.create(username='sm', full_name='Sales Manager', role='sales_manager', status='active')
        self.sm.set_password('test-password')
        self.sm.save()
        self.client.post(reverse('login'), {'username': 'boss', 'password': 'test-password'})
        from sales.models import (SalesPerson, SalesRecord, SalesPayment,
                                  SalesResult, DirectSaleFollowUpPayment)
        self.sp = SalesPerson.objects.create(name='Promoter One', channel='promoter', created_by=self.sm)
        # Archive sale: maize, value 100000, commission 5000, net 95000.
        # Paid: 40000 cash + 10000 transfer on the record, plus a
        # 20000 cash + 5000 transfer payment row = 75000 total paid.
        self.record = SalesRecord.objects.create(
            date=timezone.localdate(), recorded_by=self.sm, sales_person=self.sp,
            buyer_name='', material_type='maize', product_size='10kg',
            channel='promoter', qty_sold=10, unit_price=Decimal('10000'),
            total_value=Decimal('100000'), commission_amount=Decimal('5000'),
            amount_received_cash=Decimal('40000'),
            amount_received_transfer=Decimal('10000'))
        SalesPayment.objects.create(
            sales_record=self.record, date=timezone.localdate(),
            amount_cash=Decimal('20000'), amount_transfer=Decimal('5000'),
            recorded_by=self.sm)
        # Team sale: wheat, gross 50000, commission 5% = 2500, returned 30000.
        # (SalesResult.save() computes gross/commission/net from price,
        # quantity and commission_pct, so pass the pct, not the amounts.)
        SalesResult.objects.create(
            date=timezone.localdate(), sales_person=self.sp, material_type='wheat',
            qty_sold=5, qty_pieces_sold=0, unit_price=Decimal('10000'),
            unit_price_piece=Decimal('1000'), commission_pct=Decimal('5'),
            amount_returned=Decimal('30000'), recorded_by=self.sm)
        # Direct sale: maize, value 16000, paid 10000 cash + 6000 follow-up.
        self.direct = DirectSalePayment.objects.create(
            date=timezone.localdate(), material_type='maize', qty_sold=2,
            unit_price=Decimal('8000'), buyer_name='Amina',
            customer_phone='08031234567', customer_location='Kano',
            payment_type='partial', amount_received_cash=Decimal('10000'),
            balance=Decimal('0'), recorded_by=self.gm, status='confirmed')
        DirectSaleFollowUpPayment.objects.create(
            sale=self.direct, date=timezone.localdate(),
            amount=Decimal('6000'), method='cash', recorded_by=self.gm)

    def test_totals_match_the_old_row_by_row_figures(self):
        resp = self.client.get(reverse('reports:sales'))
        self.assertEqual(resp.status_code, 200)
        ctx = resp.context
        self.assertEqual(ctx['total_value'], 166000.0)
        self.assertEqual(ctx['total_commission'], 7500.0)
        self.assertEqual(ctx['total_net'], 158500.0)
        self.assertEqual(ctx['total_received'], 121000.0)
        self.assertEqual(ctx['total_outstanding'], 37500.0)
        self.assertEqual(ctx['maize_value'], 116000.0)
        self.assertEqual(ctx['wheat_value'], 50000.0)
        self.assertEqual(ctx['maize_received'], 91000.0)
        self.assertEqual(ctx['wheat_received'], 30000.0)
        self.assertEqual(ctx['maize_outstanding'], 20000.0)
        self.assertEqual(ctx['wheat_outstanding'], 17500.0)
        # The direct-sale row now shows the customer's name.
        self.assertContains(resp, 'Amina')

    def test_person_filter_actually_filters(self):
        resp = self.client.get(reverse('reports:sales'),
                               {'sales_person': 'Promoter One'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Promoter One')
        # A person with no sales: the team and archive tables are empty
        # and only the direct sale (which has no sales person) remains.
        resp = self.client.get(reverse('reports:sales'),
                               {'sales_person': 'Nobody Here'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No team sales match the current filter.')
        self.assertContains(resp, 'No sales records match the current filter.')
        self.assertEqual(resp.context['total_value'], 16000.0)
        self.assertEqual(resp.context['total_commission'], 0.0)
