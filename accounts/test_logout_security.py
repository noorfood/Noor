from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User

class LogoutSecurityTests(TestCase):
    def setUp(self):
        self.user=User(username='logout_test',full_name='Test',role='md',status='active')
        self.user.set_password('a-test-password!'); self.user.save()
        self.client=Client(enforce_csrf_checks=True)
        self.client.get(reverse('login'))
        token=self.client.cookies['csrftoken'].value
        self.client.post(reverse('login'), {'username':self.user.username,'password':'a-test-password!','csrfmiddlewaretoken':token})
    def test_logout_requires_post_and_csrf(self):
        url=reverse('logout')
        self.assertEqual(self.client.get(url).status_code,405)
        self.assertEqual(self.client.post(url).status_code,403)
        self.assertEqual(self.client.session.get('user_id'),self.user.pk)
        token=self.client.cookies['csrftoken'].value
        self.assertEqual(self.client.post(url,{'csrfmiddlewaretoken':token}).status_code,302)
        self.assertNotIn('user_id',self.client.session)
