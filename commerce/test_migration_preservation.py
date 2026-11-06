"""Fictional migration rehearsal using Django's disposable test database."""
from datetime import date
from decimal import Decimal
from uuid import uuid4
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

class DevelopmentMigrationPreservationTests(TransactionTestCase):
    reset_sequences=True
    old=[('commerce','0003_moneyhandover_money_handover_method_valid_and_more'),('sales','0023_salesresult_amount_returned'),('pricing','0015_alter_labourcostconfig_labour_cost_per_sack')]
    def test_forward_preserves_previous_full_confirmation_and_legacy_rows(self):
        executor=MigrationExecutor(connection);executor.migrate(self.old)
        apps=executor.loader.project_state(self.old).apps
        User=apps.get_model('accounts','User');H=apps.get_model('commerce','MoneyHandover')
        Sale=apps.get_model('sales','DirectSalePayment');Expense=apps.get_model('pricing','OperationalExpense')
        sm=User.objects.create(username='migration_sm',full_name='Fictional sales',role='sales_manager',status='active',password_hash='fake')
        gm=User.objects.create(username='migration_gm',full_name='Fictional GM',role='manager',status='active',password_hash='fake')
        sent=H.objects.create(request_key=uuid4(),date=date(2025,1,1),sender_id=sm.pk,recipient_id=gm.pk,route='sales_to_gm',method='cash',amount=Decimal('100'),status='confirmed',decided_at=timezone.now(),decided_by_id=gm.pk)
        pending=H.objects.create(request_key=uuid4(),date=date(2025,1,1),sender_id=sm.pk,recipient_id=gm.pk,route='sales_to_gm',method='cash',amount=Decimal('50'))
        sale=Sale.objects.create(date=date(2025,1,1),material_type='maize',product_size='10kg',qty_sold=2,unit_price=10,total_sale_value=20,recorded_by_id=gm.pk)
        expense=Expense.objects.create(date=date(2025,1,1),description='Fictional expense',amount=5,recorded_by_id=gm.pk)
        executor=MigrationExecutor(connection);executor.migrate(executor.loader.graph.leaf_nodes())
        apps=executor.loader.project_state().apps
        R=apps.get_model('commerce','MoneyHandoverReceipt');Sale=apps.get_model('sales','DirectSalePayment');Expense=apps.get_model('pricing','OperationalExpense')
        r=R.objects.get(handover_id=sent.pk);self.assertEqual(r.amount,Decimal('100'));self.assertEqual(r.actor_id,gm.pk);self.assertEqual(r.source,'legacy_full')
        self.assertFalse(R.objects.filter(handover_id=pending.pk).exists())
        self.assertEqual(Sale.objects.get(pk=sale.pk).product_size,'10kg')
        self.assertEqual(Expense.objects.get(pk=expense.pk).amount,Decimal('5'))
    def tearDown(self):
        executor=MigrationExecutor(connection);executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()
