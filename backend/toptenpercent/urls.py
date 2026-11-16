from django.db import OperationalError, connection
from django.urls import path
from rest_framework.decorators import api_view
from rest_framework.response import Response


@api_view(["GET"])
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except OperationalError:
        return Response({"database": "unavailable"}, status=503)

    return Response({"database": "ok"})


urlpatterns = [
    path("api/health/", health),
]