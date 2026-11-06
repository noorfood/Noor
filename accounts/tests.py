import hashlib
from django.test import TestCase
from django.urls import reverse
from accounts.models import User


class PasswordUpgradeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='staff', full_name='Store Officer', role='store_officer', store_type='raw', status='active', password_hash=hashlib.sha256(b'old-test-password').hexdigest(), plain_password='old-test-password')

    def test_legacy_password_is_upgraded_on_login(self):
        response = self.client.post(reverse('login'), {'username': 'staff', 'password': 'old-test-password'})
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.password_hash.startswith('pbkdf2_'))
        self.assertIsNone(self.user.plain_password)
        self.assertTrue(self.user.check_password('old-test-password'))
        self.assertFalse(self.user.check_password('wrong'))

    def test_new_password_does_not_store_plaintext(self):
        self.user.set_password('new-test-password')
        self.assertIsNone(self.user.plain_password)
        self.assertNotEqual(self.user.password_hash, hashlib.sha256(b'new-test-password').hexdigest())
        self.assertTrue(self.user.check_password('new-test-password'))

    def test_wrong_password_does_not_upgrade(self):
        old_hash = self.user.password_hash
        self.client.post(reverse('login'), {'username': 'staff', 'password': 'incorrect'})
        self.user.refresh_from_db()
        self.assertEqual(old_hash, self.user.password_hash)

class AccessHardeningTests(TestCase):
    def setUp(self):
        self.md=User(username='safe_md',full_name='MD',role='md',status='active');self.md.set_password('test-only-strong-password!');self.md.save()
        self.raw=User(username='safe_raw',full_name='Raw',role='store_officer',store_type='raw',status='active');self.raw.set_password('test-only-strong-password!');self.raw.save()
        self.client.post(reverse('login'),{'username':self.md.username,'password':'test-only-strong-password!'})
    def test_explorer_mutations_and_staff_delete_are_blocked(self):
        from audit.models import AuditLog
        log=AuditLog.objects.create(module='test',action='KEEP')
        for url in (reverse('data_explorer:clear_database'),reverse('data_explorer:edit',args=['audit-log',log.pk]),reverse('data_explorer:delete',args=['audit-log',log.pk]),reverse('data_explorer:bulk_delete',args=['audit-log']),reverse('accounts:staff_delete',args=[self.raw.pk])):
            for method in (self.client.get,self.client.post):self.assertEqual(method(url).status_code,403)
        self.assertTrue(AuditLog.objects.filter(pk=log.pk).exists());self.assertTrue(User.objects.filter(pk=self.raw.pk).exists())
    def test_impersonation_cannot_start(self):
        self.assertEqual(self.client.get(reverse('accounts:md_impersonate',args=[self.raw.pk])).status_code,403)
        self.assertNotIn('impersonate_id',self.client.session)
    def test_live_role_and_status_are_checked_despite_old_session(self):
        self.assertEqual(self.client.get(reverse('accounts:staff_list')).status_code,200)
        self.md.role='sales_manager';self.md.save(update_fields=['role'])
        self.assertEqual(self.client.get(reverse('accounts:staff_list')).status_code,403)
        self.md.status='suspended';self.md.save(update_fields=['status'])
        self.assertEqual(self.client.get(reverse('operations:sales_goods_home')).status_code,403)
    def test_invalid_impersonated_or_mismatched_session_denied(self):
        session=self.client.session;session['impersonate_id']=self.raw.pk;session.save()
        self.assertEqual(self.client.get(reverse('accounts:staff_list')).status_code,403)
        self.assertEqual(self.client.get(reverse('operations:finished_home')).status_code,403)
    def test_audit_admin_disallows_add_change_delete(self):
        from audit.admin import AuditLogAdmin
        from audit.models import AuditLog
        from django.contrib import admin
        view=AuditLogAdmin(AuditLog,admin.site)
        self.assertFalse(view.has_add_permission(None));self.assertFalse(view.has_change_permission(None));self.assertFalse(view.has_delete_permission(None))

    def test_staff_creation_validates_role_store_and_password(self):
        url=reverse('accounts:staff_register')
        data={'username':'new_user','full_name':'New Staff','role':'store_officer','store_type':'raw','password':'123','confirm_password':'123'}
        self.assertEqual(self.client.post(url,data).status_code,200)
        self.assertFalse(User.objects.filter(username='new_user').exists())
        data.update(password='valid-test-6942-password!',confirm_password='valid-test-6942-password!',store_type='not_a_store')
        self.assertEqual(self.client.post(url,data).status_code,200)
        self.assertFalse(User.objects.filter(username='new_user').exists())
        data['store_type']='raw'
        self.assertEqual(self.client.post(url,data).status_code,302)
        self.assertTrue(User.objects.get(username='new_user').check_password('valid-test-6942-password!'))
    def test_edit_persists_store_assignment_and_rejects_unknown_role(self):
        url=reverse('accounts:staff_edit',args=[self.raw.pk])
        self.assertEqual(self.client.post(url,{'full_name':'Raw','role':'invented'}).status_code,200)
        self.raw.refresh_from_db();self.assertEqual(self.raw.role,'store_officer')
        self.assertEqual(self.client.post(url,{'full_name':'Raw','role':'store_officer','store_type':'finished'}).status_code,302)
        self.raw.refresh_from_db();self.assertEqual(self.raw.store_type,'finished')
    def test_password_reset_rejects_weak_password(self):
        url=reverse('accounts:staff_reset_password',args=[self.raw.pk])
        self.assertEqual(self.client.post(url,{'password':'123','confirm_password':'123'}).status_code,200)
        self.raw.refresh_from_db();self.assertFalse(self.raw.check_password('123'))

    def test_password_reset_invalidates_previously_signed_in_session(self):
        from django.test import Client
        c=Client();c.post(reverse('login'),{'username':self.raw.username,'password':'test-only-strong-password!'})
        self.assertEqual(c.get(reverse('operations:home')).status_code,200)
        result=self.client.post(reverse('accounts:staff_reset_password',args=[self.raw.pk]),{'password':'fresh-credential-8472!','confirm_password':'fresh-credential-8472!'})
        self.assertEqual(result.status_code,302)
        self.assertEqual(c.get(reverse('operations:home')).status_code,302)
        self.assertFalse(c.session.get('user_id'))
        self.assertEqual(c.post(reverse('login'),{'username':self.raw.username,'password':'fresh-credential-8472!'}).status_code,302)
        self.assertEqual(c.get(reverse('operations:home')).status_code,200)
    def test_old_unsigned_session_is_invalidated(self):
        from django.test import Client
        c=Client();s=c.session;s['user_id']=self.raw.pk;s['actual_user_id']=self.raw.pk;s.save()
        self.assertEqual(c.get(reverse('operations:home')).status_code,302)
        self.assertFalse(c.session.get('user_id'))

class LoginDisclosureTests(TestCase):
    def test_missing_suspended_and_wrong_password_return_same_error(self):
        u=User(username='suspended_test',full_name='Test',role='manager',status='suspended');u.set_password('fictional-password-498!');u.save()
        active=User(username='active_test',full_name='Test',role='manager',status='active');active.set_password('fictional-password-498!');active.save()
        bodies=[]
        for name in ('missing_test','suspended_test','active_test'):
            response=self.client.post(reverse('login'),{'username':name,'password':'wrong-password'})
            self.assertContains(response,'Invalid username or password.');bodies.append(response.content)
            self.assertNotContains(response,'suspended')
