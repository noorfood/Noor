"""Custom-account session binding; not a replacement for a full security review."""
from django.utils.crypto import constant_time_compare, salted_hmac
from accounts.models import User

def session_fingerprint(user):
    return salted_hmac('noor.custom-account.session.v1',user.password_hash).hexdigest()

class PasswordSessionMiddleware:
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        pk=request.session.get('actual_user_id') or request.session.get('user_id')
        if pk:
            user=User.objects.filter(pk=pk).only('password_hash').first()
            fingerprint=request.session.get('password_fingerprint','')
            if not user or not isinstance(fingerprint,str) or not constant_time_compare(fingerprint,session_fingerprint(user)):
                request.session.flush()
        return self.get_response(request)
