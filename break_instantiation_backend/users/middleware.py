from break_instantiation_backend.users.backends import STAFF_HOME_SESSION_KEY
from break_instantiation_backend.users.backends import staff_home_schema


class StaffHomeMiddleware:
    """Remember whether this session belongs to the public overseer."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        home = None
        if hasattr(request, "session"):
            home = request.session.get(STAFF_HOME_SESSION_KEY)
        token = staff_home_schema.set(home)
        try:
            return self.get_response(request)
        finally:
            staff_home_schema.reset(token)
