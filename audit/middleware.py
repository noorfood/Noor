class AuditMiddleware:
    """
    Light middleware that injects current user info into request for easy access.
    Actual logging is done explicitly in views via log_action().
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from accounts.mixins import get_current_user
        request.current_user = get_current_user(request)
        response = self.get_response(request)
        return response
