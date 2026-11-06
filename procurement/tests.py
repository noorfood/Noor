import uuid
from django.test import TestCase
from django.urls import reverse
from accounts.models import User
from audit.models import AuditLog
from procurement.models import RawMaterialReceipt


class RawReceiptTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='raw', full_name='Raw Store', role='store_officer', store_type='raw', status='active')
        self.user.set_password('test-password')
        self.user.save()
        self.client.post(reverse('login'), {'username':'raw', 'password':'test-password'})
        self.data = {'request_key':str(uuid.uuid4()), 'date':'2026-11-03', 'material_type':'maize', 'supplier':'Test Supplier', 'num_bags':'20', 'approx_weight_kg':'2000.00', 'reference_no':'TEST-1', 'notes':''}

    def test_valid_receipt_creates_pending_cost_and_audit(self):
        response = self.client.post(reverse('procurement:receive'), self.data)
        self.assertRedirects(response, reverse('procurement:receive'))
        receipt = RawMaterialReceipt.objects.get()
        from bag_stock.models import BagMovement
        self.assertTrue(BagMovement.objects.filter(receipt=receipt, to_location='raw_store').exists())
        self.assertEqual(receipt.cost_status, 'pending')
        self.assertEqual(receipt.received_by, self.user)
        self.assertTrue(AuditLog.objects.filter(action='RECEIVE_RAW', object_id=str(receipt.pk)).exists())

    def test_invalid_input_preserves_fields_and_does_not_create(self):
        data = {**self.data, 'num_bags':'0'}
        response = self.client.post(reverse('procurement:receive'), data)
        self.assertContains(response, 'Enter at least one bag.')
        self.assertContains(response, 'Test Supplier')
        self.assertEqual(RawMaterialReceipt.objects.count(), 0)

    def test_unknown_material_is_rejected(self):
        response = self.client.post(reverse('procurement:receive'), {**self.data, 'material_type':'invalid'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(RawMaterialReceipt.objects.count(), 0)

    def test_other_store_cannot_receive_raw_material(self):
        self.user.store_type='finished'
        self.user.save(update_fields=['store_type'])
        response = self.client.post(reverse('procurement:receive'), self.data)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(RawMaterialReceipt.objects.count(), 0)

    def test_duplicate_receipt_is_not_saved_twice(self):
        from bag_stock.models import BagMovement,RawReceiptSubmission
        self.client.post(reverse('procurement:receive'),self.data)
        self.assertContains(self.client.post(reverse('procurement:receive'),self.data),'already recorded')
        self.assertEqual(RawMaterialReceipt.objects.count(),1)
        self.assertEqual(RawReceiptSubmission.objects.count(),1)
        self.assertEqual(BagMovement.objects.filter(kind='receipt').count(),1)
    def test_suspended_account_cannot_receive_using_old_session(self):
        self.user.status='suspended';self.user.save(update_fields=['status'])
        self.assertEqual(self.client.post(reverse('procurement:receive'),self.data).status_code,403)
        self.assertEqual(RawMaterialReceipt.objects.count(),0)
